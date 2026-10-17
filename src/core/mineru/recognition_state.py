"""Durable recognition state owned by one translation task.

The record captures exactly what is needed to reason about continuation:
the admitted source fingerprint, the recognition phase, the known remote task
identifier/state, the validated result identity, and bounded attempt accounting.

It deliberately has no field for a credential or a signed storage URL, and
unknown fields are rejected on load, so a caller can never persist one by
accident. Saving is atomic (write a sibling part file, fsync, replace), which is
why the state is trustworthy before a provider request is issued.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, fields, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .errors import MineruStateUnavailable

# admitted -> submitting -> submitted -> uploaded -> recognizing -> downloading
# -> validating -> validated. A user-requested continuation re-enters the known
# remote task from submitted/uploaded/recognizing/downloading/validating (and
# from the local-pause phases timed_out/interrupted_local); submitting and
# submission_unknown are an uncertain submission and are never resubmittable.
# admitted proves no request was issued, so it may still perform the first
# submission. rejected/failed are terminal for this task.
PHASES = frozenset({
    "admitted",
    "submitting",
    "submitted",
    "uploaded",
    "recognizing",
    "downloading",
    "validating",
    "validated",
    "rejected",
    "failed",
    "upload_failed",
    "submission_unknown",
    "interrupted_local",
    "timed_out",
})

REMOTE_STATES = frozenset(
    {"pending", "running", "converting", "waiting-file", "done", "failed"}
)

STATE_FILE_NAME = "recognition-state.json"
_BATCH_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_ERROR_LIMIT = 300


@dataclass(frozen=True)
class RecognitionState:
    """One atomic snapshot of a task's recognition work."""

    phase: str
    source_sha256: str
    source_bytes: int
    source_pages: int
    file_name: str
    batch_id: Optional[str] = None
    remote_state: Optional[str] = None
    result_zip_sha256: Optional[str] = None
    result_cache_sha256: Optional[str] = None
    result_pages: Optional[int] = None
    attempts: int = 0
    retries: int = 0
    continuations: int = 0
    elapsed_seconds: float = 0.0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    updated_at: str = ""

    def __post_init__(self) -> None:
        if self.phase not in PHASES:
            raise ValueError(f"Unknown recognition phase: {self.phase!r}")
        if not isinstance(self.source_sha256, str) or not _SHA256_RE.fullmatch(
                self.source_sha256):
            raise ValueError("source_sha256 must be a SHA-256 hex digest")
        for name in ("source_bytes", "source_pages", "attempts", "retries",
                     "continuations"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
            if name == "source_pages" and value < 1:
                raise ValueError("source_pages must be at least 1")
        if not isinstance(self.file_name, str) or not self.file_name.strip():
            raise ValueError("file_name must be a non-empty string")
        if any(separator in self.file_name for separator in ("/", "\\")):
            raise ValueError("file_name must not contain a path separator")
        if self.batch_id is not None and (
                not isinstance(self.batch_id, str)
                or not _BATCH_ID_RE.fullmatch(self.batch_id)):
            raise ValueError("batch_id is not a valid remote task identifier")
        if self.remote_state is not None and self.remote_state not in REMOTE_STATES:
            raise ValueError("remote_state is not a documented task state")
        for name in ("result_zip_sha256", "result_cache_sha256"):
            value = getattr(self, name)
            if value is not None and (
                    not isinstance(value, str) or not _SHA256_RE.fullmatch(value)):
                raise ValueError(f"{name} must be a SHA-256 hex digest")
        if self.result_pages is not None and (
                not isinstance(self.result_pages, int)
                or isinstance(self.result_pages, bool)
                or self.result_pages < 1):
            raise ValueError("result_pages must be a positive integer")
        if not isinstance(self.elapsed_seconds, (int, float)) or isinstance(
                self.elapsed_seconds, bool) or self.elapsed_seconds < 0:
            raise ValueError("elapsed_seconds must be a non-negative number")
        if self.error_code is not None and (
                not isinstance(self.error_code, str)
                or not _CODE_RE.fullmatch(self.error_code)):
            raise ValueError("error_code is not a stable error code")
        object.__setattr__(self, "error_message", _sanitize_message(self.error_message))
        if not self.updated_at:
            object.__setattr__(self, "updated_at", _now())

    def to_dict(self) -> Dict[str, Any]:
        """Serializable form: fixed fields only, never arbitrary keys."""
        return {field.name: getattr(self, field.name) for field in fields(self)}

    def with_updates(self, **changes: Any) -> "RecognitionState":
        """Return a new validated state with ``changes`` applied."""
        changes.setdefault("updated_at", _now())
        return replace(self, **changes)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RecognitionState":
        """Validate and rebuild a state; unknown fields are rejected."""
        if not isinstance(data, Mapping):
            raise ValueError("recognition state must be a mapping")
        allowed = {field.name for field in fields(cls)}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(
                f"recognition state contains unsupported field(s): "
                f"{', '.join(sorted(unknown))}")
        return cls(**dict(data))


def write_state(directory: Path, state: RecognitionState) -> Path:
    """Atomically persist one state snapshot inside the task's working data."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / STATE_FILE_NAME
    try:
        dump_json_atomic(path, state.to_dict())
    except MineruStateUnavailable:
        raise
    except (OSError, ValueError) as exc:
        raise MineruStateUnavailable(
            "The recognition state could not be recorded; the task will not "
            "contact the provider without a durable record.") from exc
    return path


def read_state(directory: Path) -> Optional[RecognitionState]:
    """Read the state, or ``None`` when this task never recorded one."""
    path = Path(directory) / STATE_FILE_NAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MineruStateUnavailable(
            "The recorded recognition state is unreadable; safe continuation "
            "cannot be attempted.") from exc
    try:
        return RecognitionState.from_dict(payload)
    except ValueError as exc:
        raise MineruStateUnavailable(
            "The recorded recognition state is invalid; safe continuation "
            "cannot be attempted.") from exc


def delete_state(directory: Path) -> None:
    """Remove the state file (the rest of the task directory is untouched)."""
    path = Path(directory) / STATE_FILE_NAME
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise MineruStateUnavailable(
            "The recorded recognition state could not be removed.") from exc


def dump_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON atomically: sibling part file, fsync, then replace."""
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(dict(payload), stream, ensure_ascii=False, indent=2)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:  # pragma: no cover - fsync support varies by filesystem
                pass
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best-effort cleanup
            pass


class TaskRecognitionStore:
    """The task-owned persistence seam used by the recognition orchestrator."""

    def __init__(self, checkpoint_manager: Any, translation_id: str) -> None:
        if not _TASK_ID_RE.fullmatch(translation_id or ""):
            raise MineruStateUnavailable("The task identifier is not usable.")
        self._manager = checkpoint_manager
        self._translation_id = translation_id

    def workspace(self) -> Path:
        """The task-owned directory for recognition artifacts and state."""
        return self._manager.recognition_dir(self._translation_id)

    def load(self) -> Optional[RecognitionState]:
        return read_state(self.workspace())

    def save(self, state: RecognitionState) -> None:
        write_state(self.workspace(), state)

    def delete(self) -> None:
        delete_state(self.workspace())


def _sanitize_message(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("error_message must be a string")
    cleaned = _URL_RE.sub("<URL>", value).strip()
    return cleaned[:_ERROR_LIMIT] or None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
