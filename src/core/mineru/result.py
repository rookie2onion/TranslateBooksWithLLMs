"""Validate and load the downloaded MinerU result archive.

The provider returns a ZIP holding ``layout.json``, one ``*_content_list_v2.json``
and the recognised image assets. This module is the only place that turns those
bytes into the application's existing :class:`MineruCache`:

1. the archive is bounded and safely extracted (entry count, expanded size,
   symbolic links, name collisions, path traversal);
2. the extracted directory is proven to be a complete recognition result for the
   *admitted* source (same page count, every source page present);
3. a task-owned source manifest is written from the admitted fingerprint, so the
   existing cache loader can prove the result belongs to this document;
4. the existing loader and structural adapter do the rest unchanged.

Nothing here performs network I/O or trusts provider-supplied paths beyond the
shared archive/asset protections.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from src.utils.atomic_io import write_json_atomic
from src.utils.hashing import sha256_file
from src.utils.security import (
    SecurityError,
    find_unsafe_archive_member,
    safe_extract_zip,
)

from .admission import MAX_PAGES, AdmittedSource
from .cache import (
    MineruCache,
    MineruCacheError,
    MineruUnsupportedContentError,
    load_cache,
)
from .errors import MineruResultInvalid, MineruUnsupportedContent

MAX_ARCHIVE_MEMBERS = 5_000
MAX_ARCHIVE_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_RESULT_JSON_BYTES = 50 * 1024 * 1024
MANIFEST_NAME = "sample-info.json"
_RESULT_DIR_NAME = "result"
_ABSOLUTE_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s'\"]+")


@dataclass(frozen=True)
class OnlineResult:
    """A validated recognition result bound to its admitted source."""

    cache: MineruCache
    root: Path
    zip_sha256: str
    cache_sha256: str
    page_count: int


def build_online_result(
    archive_path: Path,
    *,
    work_dir: Path,
    admitted: AdmittedSource,
    max_members: int = MAX_ARCHIVE_MEMBERS,
    max_expanded_bytes: int = MAX_ARCHIVE_EXPANDED_BYTES,
    max_json_bytes: int = MAX_RESULT_JSON_BYTES,
) -> OnlineResult:
    """Extract, validate and load a downloaded recognition result."""
    archive_path = Path(archive_path)
    if not archive_path.is_file():
        raise MineruResultInvalid("The recognition result archive was not downloaded.")
    if archive_path.stat().st_size > MAX_ARCHIVE_EXPANDED_BYTES:
        raise MineruResultInvalid("The recognition result archive exceeds the allowed size.")

    root = Path(work_dir) / _RESULT_DIR_NAME
    _extract(archive_path, root, max_members=max_members,
             max_expanded_bytes=max_expanded_bytes, max_json_bytes=max_json_bytes)

    result_root = _find_result_root(root)
    _write_source_manifest(result_root, admitted)
    cache = _load_cache(result_root, admitted)
    return OnlineResult(
        cache=cache,
        root=result_root,
        zip_sha256=sha256_file(archive_path),
        cache_sha256=cache_fingerprint(cache),
        page_count=len(cache.pages),
    )


def load_validated_result(root: Path, *, admitted: AdmittedSource,
                          expected_zip_sha256: Optional[str],
                          expected_cache_sha256: Optional[str]) -> OnlineResult:
    """Re-open a previously validated result without any provider request.

    Used only for a task whose durable state says its result was already
    validated. Any mismatch fails closed: the caller reports that safe
    continuation is unavailable instead of starting recognition again.
    """
    root = Path(root)
    if not root.is_dir():
        raise MineruResultInvalid(
            "The validated recognition result is no longer present in this "
            "task's working data.")
    try:
        cache = load_cache(root, source_pdf=admitted.path)
    except MineruCacheError as exc:
        raise _result_error(exc, root) from exc
    _verify_identity(cache, admitted)
    cache_sha256 = cache_fingerprint(cache)
    if expected_cache_sha256 and cache_sha256 != expected_cache_sha256:
        raise MineruResultInvalid(
            "The stored recognition result does not match its validated identity.")
    zip_sha256 = expected_zip_sha256 or ""
    return OnlineResult(
        cache=cache,
        root=root,
        zip_sha256=zip_sha256,
        cache_sha256=cache_sha256,
        page_count=len(cache.pages),
    )


def cache_fingerprint(cache: MineruCache) -> str:
    """Stable digest of every fingerprinted cache file (the validated identity)."""
    digest = hashlib.sha256()
    for key in sorted(cache.fingerprints):
        digest.update(f"{key}\0{cache.fingerprints[key]}\n".encode("utf-8"))
    return digest.hexdigest()


def _extract(archive_path: Path, destination: Path, *, max_members: int,
             max_expanded_bytes: int, max_json_bytes: int) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    if not zipfile.is_zipfile(archive_path):
        raise MineruResultInvalid("The recognition result is not a ZIP archive.")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            _validate_members(archive, max_members, max_expanded_bytes)
            safe_extract_zip(archive, destination)
    except MineruResultInvalid:
        raise
    except SecurityError as exc:
        raise MineruResultInvalid(
            "The recognition result archive contains an unsafe path.") from exc
    except (OSError, zipfile.BadZipFile) as exc:
        raise MineruResultInvalid(
            "The recognition result archive could not be read.") from exc

    for member in destination.rglob("*.json"):
        if member.is_file() and member.stat().st_size > max_json_bytes:
            raise MineruResultInvalid(
                "A recognition result JSON file exceeds the allowed size.")


def _validate_members(archive: zipfile.ZipFile, max_members: int,
                      max_expanded_bytes: int) -> None:
    members = archive.infolist()
    if len(members) > max_members:
        raise MineruResultInvalid(
            "The recognition result archive contains too many files.")
    if sum(member.file_size for member in members) > max_expanded_bytes:
        raise MineruResultInvalid(
            "The recognition result archive expands beyond the allowed size.")
    for member in members:
        if stat.S_ISLNK(member.external_attr >> 16):
            raise MineruResultInvalid(
                "The recognition result archive contains a symbolic link.")
    folded = [member.filename.casefold() for member in members]
    if len(folded) != len(set(folded)):
        raise MineruResultInvalid(
            "The recognition result archive contains colliding member names.")
    if not members:
        raise MineruResultInvalid("The recognition result archive is empty.")
    # Validate before a single byte is written; safe_extract_zip re-checks the
    # resolved join as a second line of defence.
    unsafe = find_unsafe_archive_member(member.filename for member in members)
    if unsafe is not None:
        raise MineruResultInvalid(
            "The recognition result archive contains an unsafe path.")


def _find_result_root(extracted: Path) -> Path:
    candidates: List[Path] = [path.parent for path in extracted.rglob("layout.json")
                              if path.is_file()]
    if not candidates:
        raise MineruResultInvalid(
            "The recognition result has no layout.json file.")
    if len(candidates) > 1:
        raise MineruResultInvalid(
            "The recognition result contains more than one layout.json file.")
    return candidates[0]


def _write_source_manifest(root: Path, admitted: AdmittedSource) -> None:
    """Bind the result to the admitted source (fingerprint and page coverage)."""
    info: Dict[str, object] = {
        "source_path": admitted.file_name,
        "source_sha256": admitted.sha256,
        "source_total_pages": admitted.page_count,
        "source_pages": list(range(1, admitted.page_count + 1)),
        "sample_sha256": admitted.sha256,
        "translation_llm_called": False,
    }
    write_json_atomic(root / MANIFEST_NAME, info)


def _load_cache(root: Path, admitted: AdmittedSource) -> MineruCache:
    try:
        cache = load_cache(root, source_pdf=admitted.path)
    except MineruCacheError as exc:
        raise _result_error(exc, root) from exc
    _verify_identity(cache, admitted)
    return cache


def _verify_identity(cache: MineruCache, admitted: AdmittedSource) -> None:
    if cache.source_sha256 != admitted.sha256:
        raise MineruResultInvalid(
            "The recognition result belongs to a different source document.")
    expected_pages = tuple(range(1, admitted.page_count + 1))
    if cache.source_total_pages != admitted.page_count or cache.source_pages != expected_pages:
        raise MineruResultInvalid(
            "The recognition result does not cover every source page: "
            f"expected {admitted.page_count}, "
            f"got {len(cache.pages)} recognised page(s).")
    if len(cache.pages) != admitted.page_count:
        raise MineruResultInvalid(
            "The recognition result does not cover every source page: "
            f"expected {admitted.page_count}, got {len(cache.pages)}.")
    if admitted.page_count > MAX_PAGES:
        raise MineruResultInvalid("The admitted source exceeds the recognition page limit.")


def _result_error(exc: MineruCacheError, root: Path) -> MineruResultInvalid:
    """Map a loader failure to its stable Web error category.

    A recognised-but-unpreservable construct gets its own code so the UI can
    state the limitation, instead of reusing the generic "result invalid" text.
    """
    text = _ABSOLUTE_PATH_RE.sub("<path>", str(exc))
    text = text.replace(str(root.parent), "<result>").replace(str(root), "<result>")
    if isinstance(exc, MineruUnsupportedContentError):
        return MineruUnsupportedContent(
            f"The recognition result contains unsupported content: {text}")
    return MineruResultInvalid(f"The recognition result did not validate: {text}")
