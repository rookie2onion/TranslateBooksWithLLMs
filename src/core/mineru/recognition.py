"""One online recognition attempt for a task-owned PDF translation job.

The orchestrator ties the pieces together:

    admit -> [durable state] -> submit -> upload -> poll -> download -> validate

Every step that could leave ambiguous remote work is recorded *before* it is
attempted, and it is recorded in the job's own working data. Safe continuation
of an in-flight remote task is deliberately not implemented yet (that is the
next slice): any recorded state other than a validated result fails closed, and
a lost or ambiguous submission is never replaced by a second submission.

The local budget (five minutes by default) covers transfer and polling, and
every wait and retry shares it. A timeout or local stop is reported as such: it
is neither remote cancellation nor successful completion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .admission import (
    MAX_BYTES,
    MAX_PAGES,
    RECOGNITION_BUDGET_SECONDS,
    AdmittedSource,
    admit_pdf_source,
    describe_pdf,
)
from .cache import MineruCache
from .client import MineruClient
from .errors import (
    MineruContinuationUnavailable,
    MineruError,
    MineruInterrupted,
    MineruNetworkError,
    MineruRecognitionFailed,
    MineruRequestRejected,
    MineruResponseInvalid,
    MineruResultInvalid,
    MineruSubmissionUncertain,
    MineruTimeout,
    MineruUploadFailed,
)
from .recognition_state import RecognitionState
from .result import OnlineResult, build_online_result, load_validated_result
from .structure import SourceContent, adapt

DEFAULT_POLL_INTERVAL_SECONDS = 2.0
_DATA_ID_PREFIX = "tbl-"


@dataclass(frozen=True)
class RecognitionResult:
    """A validated recognition result plus the accounting of how it happened."""

    admitted: AdmittedSource
    source: SourceContent
    cache: MineruCache
    batch_id: str
    result_zip_sha256: str
    result_cache_sha256: str
    page_count: int
    elapsed_seconds: float
    retries: int
    remote_states: Tuple[str, ...]
    reused: bool

    @property
    def cache_sha256(self) -> str:
        """The validated identity of the loaded recognition result."""
        return self.result_cache_sha256


def recognize_pdf(
    source_path: Path,
    *,
    work_dir: Optional[Path] = None,
    authorized: bool = False,
    token: Optional[str] = None,
    store: Optional[object] = None,
    budget_seconds: float = RECOGNITION_BUDGET_SECONDS,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    check_interruption: Optional[Callable[[], bool]] = None,
    progress: Optional[Callable[[str], None]] = None,
    log: Optional[Callable[[str, str], None]] = None,
    max_pages: int = MAX_PAGES,
    max_bytes: int = MAX_BYTES,
) -> RecognitionResult:
    """Recognize one admitted PDF online, or fail with a typed error.

    Args:
        source_path: The PDF the task owns.
        work_dir: Task-owned directory for the downloaded result and its state.
            Ignored when ``store`` is given (the store owns that location).
        authorized: The task's explicit upload authorization. Reusing an already
            validated result needs no new authorization because nothing is
            uploaded again.
        token: MinerU account token from the environment.
        store: Task-owned durable state store (``TaskRecognitionStore``).
        budget_seconds: The local recognition budget (300 seconds by default).
        poll_interval_seconds: Delay between remote status polls.
        clock, sleep: Injectable time seam (tests use a fake monotonic clock).
        check_interruption: Cooperative stop probe; returns True to stop local
            work without claiming remote cancellation.
        progress: Called with the phase name as the attempt advances.
        log: Called as ``(key, message)`` for the job log.

    Returns:
        The validated recognition result and its accounting.
    """
    source_path = Path(source_path)
    started = clock()
    deadline = started + max(0.0, float(budget_seconds))

    if store is not None:
        workspace = Path(store.workspace())
    elif work_dir is not None:
        workspace = Path(work_dir)
    else:
        raise ValueError("recognize_pdf needs a work_dir or a task-owned store")
    workspace.mkdir(parents=True, exist_ok=True)

    existing = store.load() if store is not None else None
    if existing is not None:
        return _reuse_or_fail(
            existing, source_path=source_path, workspace=workspace, store=store,
            started=started, clock=clock, progress=progress, log=log,
        )

    admitted = admit_pdf_source(
        source_path, authorized=authorized, token=token,
        max_pages=max_pages, max_bytes=max_bytes,
    )
    state = RecognitionState(
        phase="admitted",
        source_sha256=admitted.sha256,
        source_bytes=admitted.size_bytes,
        source_pages=admitted.page_count,
        file_name=admitted.file_name,
    )

    def save(**changes) -> RecognitionState:
        nonlocal state
        state = state.with_updates(**changes)
        if store is not None:
            store.save(state)
        return state

    def emit(phase: str) -> None:
        _notify(progress, phase)

    save()
    client = MineruClient(token or "", clock=clock, sleep=sleep)
    remote_states: List[str] = []
    try:
        emit("submitting")
        _log(log, "pdf_mineru_submitting",
             "⬆️ Submitting the authorized PDF to MinerU online recognition…")
        save(phase="submitting", attempts=state.attempts + 1)
        try:
            ticket = client.request_upload(
                admitted.file_name, _data_id(admitted), deadline=deadline)
        except MineruRequestRejected as exc:
            save(phase="rejected", error_code=exc.code, error_message=str(exc))
            raise
        except (MineruNetworkError, MineruResponseInvalid, MineruTimeout) as exc:
            # The request may have reached the provider. Never resubmit.
            save(phase="submission_unknown", error_code=exc.code,
                 error_message=str(exc))
            raise MineruSubmissionUncertain(
                "The MinerU submission outcome is unknown (the request did not "
                "complete cleanly). The document will not be submitted again "
                "automatically.") from exc

        save(phase="submitted", batch_id=ticket.batch_id)
        emit("uploading")
        _log(log, "pdf_mineru_uploading",
             "⬆️ Uploading the PDF to the one-time MinerU storage destination…")
        try:
            client.upload(ticket, admitted.path, deadline=deadline)
        except MineruTimeout:
            save(phase="upload_failed", error_code=MineruTimeout.code,
                 error_message="The local recognition budget elapsed during upload.")
            raise
        except (MineruUploadFailed, MineruNetworkError) as exc:
            save(phase="upload_failed", error_code=exc.code, error_message=str(exc))
            raise
        save(phase="uploaded")

        emit("recognizing")
        _log(log, "pdf_mineru_recognizing",
             "🔎 MinerU is recognizing the document. Polling within the local "
             "five-minute budget…")
        zip_url = _poll_until_done(
            client, ticket.batch_id, admitted.file_name, deadline=deadline,
            poll_interval_seconds=poll_interval_seconds, clock=clock, sleep=sleep,
            check_interruption=check_interruption, remote_states=remote_states,
            save=save, log=log,
        )

        emit("downloading")
        save(phase="downloading", remote_state="done")
        archive_path = workspace / "result.zip"
        try:
            client.download(zip_url, archive_path, deadline=deadline,
                            check_interruption=check_interruption)
        except MineruInterrupted as exc:
            save(phase="interrupted_local", error_code=exc.code,
                 error_message=str(exc))
            raise
        except MineruTimeout as exc:
            save(phase="timed_out", error_code=exc.code, error_message=str(exc))
            raise
        except (MineruResultInvalid, MineruNetworkError) as exc:
            save(phase="downloading", error_code=exc.code, error_message=str(exc))
            raise

        emit("validating")
        save(phase="validating")
        if _sha256_file(admitted.path) != admitted.sha256:
            message = ("The source PDF changed during recognition, so the "
                       "returned result cannot be accepted.")
            save(error_code="mineru_result_invalid", error_message=message)
            raise MineruResultInvalid(message)
        try:
            online = build_online_result(
                archive_path, work_dir=workspace, admitted=admitted)
        except MineruResultInvalid as exc:
            save(error_code=exc.code, error_message=str(exc))
            raise

        source = adapt(online.cache)
        save(
            phase="validated",
            remote_state="done",
            result_zip_sha256=online.zip_sha256,
            result_cache_sha256=online.cache_sha256,
            result_pages=online.page_count,
            error_code=None,
            error_message=None,
        )
        emit("validated")
        _log(log, "pdf_mineru_validated",
             f"✅ MinerU result validated: {online.page_count} pages, "
             f"{len(source.paragraphs)} source paragraphs.")
        return _result(admitted, source, online, ticket.batch_id, started, clock,
                       client.retries, remote_states, reused=False)
    finally:
        client.close()


def _poll_until_done(
    client: MineruClient,
    batch_id: str,
    file_name: str,
    *,
    deadline: float,
    poll_interval_seconds: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    check_interruption: Optional[Callable[[], bool]],
    remote_states: List[str],
    save: Callable[..., RecognitionState],
    log: Optional[Callable[[str, str], None]],
) -> str:
    previous = None
    while True:
        if check_interruption is not None and check_interruption():
            message = ("Local recognition was stopped. The remote MinerU task "
                       "may continue; this is not remote cancellation.")
            save(phase="interrupted_local",
                 error_code="mineru_recognition_interrupted",
                 error_message=message)
            raise MineruInterrupted(message)
        if clock() >= deadline:
            _raise_timeout(save)

        try:
            snapshot = client.poll(batch_id, expected_file_name=file_name,
                                   deadline=deadline)
        except MineruRecognitionFailed as exc:
            save(phase="failed", remote_state="failed", error_code=exc.code,
                 error_message=str(exc))
            raise
        except MineruTimeout:
            _raise_timeout(save)
        except (MineruNetworkError, MineruResponseInvalid,
                MineruRequestRejected) as exc:
            save(phase="recognizing", error_code=exc.code, error_message=str(exc))
            raise

        remote_states.append(snapshot.state)
        if snapshot.state == "done":
            return snapshot.full_zip_url or ""
        save(phase="recognizing", remote_state=snapshot.state)
        if snapshot.state != previous:
            previous = snapshot.state
            _log(log, "pdf_mineru_remote_state",
                 f"🛰️ MinerU task state: {snapshot.state}")

        remaining = deadline - clock()
        if remaining <= 0:
            _raise_timeout(save)
        sleep(min(max(0.0, poll_interval_seconds), remaining))


def _raise_timeout(save: Callable[..., RecognitionState]) -> None:
    message = ("The local five-minute recognition budget elapsed. The remote "
               "MinerU task may continue, but this attempt did not complete and "
               "will not be reported as successful.")
    save(phase="timed_out", error_code="mineru_recognition_timeout",
         error_message=message)
    raise MineruTimeout(message)


def _reuse_or_fail(
    state: RecognitionState,
    *,
    source_path: Path,
    workspace: Path,
    store: Optional[object],
    started: float,
    clock: Callable[[], float],
    progress: Optional[Callable[[str], None]],
    log: Optional[Callable[[str, str], None]],
) -> RecognitionResult:
    """Reuse an already validated result; every other phase fails closed."""
    described = describe_pdf(source_path)
    if (described.sha256 != state.source_sha256
            or described.page_count != state.source_pages):
        raise MineruContinuationUnavailable(
            "The source PDF changed since its recognition result was validated. "
            "Saved work cannot be reused for a different document, and the "
            "document will not be submitted again automatically.")

    if state.phase != "validated":
        raise MineruContinuationUnavailable(_continuation_message(state))

    try:
        online = load_validated_result(
            workspace / "result",
            admitted=described,
            expected_zip_sha256=state.result_zip_sha256,
            expected_cache_sha256=state.result_cache_sha256,
        )
    except MineruResultInvalid as exc:
        raise MineruContinuationUnavailable(
            "The previously validated recognition result is no longer usable "
            f"({exc}). The document will not be submitted again automatically."
        ) from exc

    source = adapt(online.cache)
    _notify(progress, "reused")
    _log(log, "pdf_mineru_reused",
         f"♻️ Reusing the validated MinerU result ({online.page_count} pages, "
         f"{len(source.paragraphs)} paragraphs); no provider request was made.")
    return _result(described, source, online, state.batch_id or "", started, clock,
                   state.retries, ("done",), reused=True)


def _continuation_message(state: RecognitionState) -> str:
    if state.phase in {"submitting", "submission_unknown"}:
        return (
            "A previous MinerU submission may have succeeded but its outcome is "
            "not known. The document will not be submitted again automatically; "
            "safe continuation arrives in a later slice.")
    if state.phase in {"admitted"}:
        return (
            "A previous recognition attempt stopped before submission. This "
            "slice does not continue an existing attempt; the document will not "
            "be submitted again automatically.")
    return (
        f"The previous recognition attempt is recorded as '{state.phase}'. Safe "
        "continuation of an existing MinerU task is not implemented in this "
        "slice, and the document will not be submitted again automatically.")


def _result(admitted: AdmittedSource, source: SourceContent, online: OnlineResult,
            batch_id: str, started: float, clock: Callable[[], float],
            retries: int, remote_states: List[str], *, reused: bool) -> RecognitionResult:
    return RecognitionResult(
        admitted=admitted,
        source=source,
        cache=online.cache,
        batch_id=batch_id,
        result_zip_sha256=online.zip_sha256,
        result_cache_sha256=online.cache_sha256,
        page_count=online.page_count,
        elapsed_seconds=max(0.0, clock() - started),
        retries=max(0, int(retries)),
        remote_states=tuple(remote_states),
        reused=reused,
    )


def _data_id(admitted: AdmittedSource) -> str:
    return f"{_DATA_ID_PREFIX}{admitted.sha256[:20]}"


def _sha256_file(path: Path) -> str:
    import hashlib

    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _notify(callback: Optional[Callable[[str], None]], phase: str) -> None:
    if callback is None:
        return
    try:
        callback(phase)
    except Exception:  # pragma: no cover - progress must never fail a job
        pass


def _log(callback: Optional[Callable[[str, str], None]], key: str, message: str) -> None:
    if callback is None:
        return
    try:
        callback(key, message)
    except Exception:  # pragma: no cover - logging must never fail a job
        pass
