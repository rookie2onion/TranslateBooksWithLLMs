"""One online recognition execution for a task-owned PDF translation job.

The orchestrator ties the pieces together:

    admit -> [durable state] -> submit -> upload -> poll -> download -> validate

Every step that could leave ambiguous remote work is recorded *before* it is
attempted, and it is recorded in the job's own working data. A later execution
(the user's existing Continue action after a local pause, a stop, or a restart)
re-opens that record and:

- reuses an already validated result without any provider request;
- re-polls and re-downloads a *known* remote task through its persisted
  identifier, without uploading or submitting the document again;
- performs the first submission only when the record proves none was ever
  issued (``admitted``);
- refuses every other phase with an actionable error instead of resubmitting.

In particular ``submitting``/``submission_unknown`` stay non-resubmittable (the
outcome is unknown), and an incomplete upload is reported as not automatically
continuable because its one-time destination is deliberately not persisted.

The local budget (five minutes by default) covers transfer and polling for one
attempt *or one user-requested continuation*, and every wait and retry shares
that execution's deadline. A continuation grants a fresh budget for the same
remote task without pretending a new submission attempt happened. A timeout or
local stop is reported as such: it is neither remote cancellation nor successful
completion.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from src.utils.hashing import sha256_file

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
    MineruContinuationResultUnavailable,
    MineruContinuationSourceChanged,
    MineruContinuationUnavailable,
    MineruContinuationUploadUnrecoverable,
    MineruError,
    MineruInterrupted,
    MineruNetworkError,
    MineruRecognitionFailed,
    MineruRequestRejected,
    MineruResponseInvalid,
    MineruResultInvalid,
    MineruSubmissionRejected,
    MineruSubmissionUncertain,
    MineruTimeout,
    MineruTokenMissing,
    MineruUploadFailed,
)
from .recognition_state import RecognitionState
from .result import OnlineResult, build_online_result, load_validated_result
from .structure import SourceContent, adapt

DEFAULT_POLL_INTERVAL_SECONDS = 2.0
_DATA_ID_PREFIX = "tbl-"

# Phases whose persisted identifier provably denotes a known remote task: a
# continuation may re-poll and re-download it, never upload or submit again.
# ``validated`` is handled separately (pure local reuse) and ``admitted`` is the
# only phase that may still submit, because it proves no request was issued.
CONTINUABLE_REMOTE_PHASES = frozenset({
    "submitted",
    "uploaded",
    "recognizing",
    "downloading",
    "validating",
    "timed_out",
    "interrupted_local",
})


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
    continued: bool = False

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
    """Recognize one admitted PDF online, or continue an existing task.

    Args:
        source_path: The PDF the task owns.
        work_dir: Task-owned directory for the downloaded result and its state.
            Ignored when ``store`` is given (the store owns that location).
        authorized: The task's explicit upload authorization. A continuation of
            a known remote task or a validated result needs no new
            authorization because nothing is uploaded again; a first submission
            (including one recorded as ``admitted``) still requires it.
        token: MinerU account token from the environment.
        store: Task-owned durable state store (``TaskRecognitionStore``).
        budget_seconds: The local budget of this execution (300 seconds by
            default). Retries share it; a later continuation gets its own.
        poll_interval_seconds: Delay between remote status polls.
        clock, sleep: Injectable time seam (tests use a fake monotonic clock).
        check_interruption: Cooperative stop probe; returns True to stop local
            work without claiming remote cancellation.
        progress: Called with the phase name as the execution advances.
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
        return _continue_existing(
            existing, source_path=source_path, workspace=workspace, store=store,
            authorized=authorized, token=token, started=started,
            budget_seconds=budget_seconds, clock=clock, sleep=sleep,
            poll_interval_seconds=poll_interval_seconds,
            check_interruption=check_interruption, progress=progress, log=log,
            max_pages=max_pages, max_bytes=max_bytes,
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
    return _run_submission(
        state, admitted, workspace=workspace, store=store, token=token,
        started=started, deadline=deadline, clock=clock, sleep=sleep,
        poll_interval_seconds=poll_interval_seconds,
        check_interruption=check_interruption, progress=progress, log=log,
    )


# ---------------------------------------------------------------------------
# Continuation of a persisted task record
# ---------------------------------------------------------------------------


def _continue_existing(
    state: RecognitionState,
    *,
    source_path: Path,
    workspace: Path,
    store: Optional[object],
    authorized: bool,
    token: Optional[str],
    started: float,
    budget_seconds: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    poll_interval_seconds: float,
    check_interruption: Optional[Callable[[], bool]],
    progress: Optional[Callable[[str], None]],
    log: Optional[Callable[[str, str], None]],
    max_pages: int,
    max_bytes: int,
) -> RecognitionResult:
    """Resume this task's recorded recognition work without resubmitting it."""
    described = describe_pdf(source_path)
    if (described.sha256 != state.source_sha256
            or described.page_count != state.source_pages
            or described.size_bytes != state.source_bytes):
        raise MineruContinuationSourceChanged(
            "The source PDF changed since this recognition task was recorded "
            f"(recorded {state.source_pages} page(s), "
            f"{state.source_bytes} bytes; current {described.page_count} "
            f"page(s), {described.size_bytes} bytes). Saved work is preserved "
            "but cannot be reused for a different document, and the document "
            "will not be submitted again automatically.")

    if state.phase == "validated":
        return _reuse_validated(
            state, described, workspace=workspace, started=started, clock=clock,
            progress=progress, log=log,
        )

    if state.phase == "admitted":
        # No provider request was ever issued for this record: a continuation
        # may perform the (first) submission, still under explicit authorization.
        admitted = admit_pdf_source(
            source_path, authorized=authorized, token=token,
            max_pages=max_pages, max_bytes=max_bytes,
        )
        deadline = started + max(0.0, float(budget_seconds))
        return _run_submission(
            state.with_updates(elapsed_seconds=state.elapsed_seconds),
            admitted, workspace=workspace, store=store, token=token,
            started=started, deadline=deadline, clock=clock, sleep=sleep,
            poll_interval_seconds=poll_interval_seconds,
            check_interruption=check_interruption, progress=progress, log=log,
            continued=True,
        )

    if state.phase not in CONTINUABLE_REMOTE_PHASES:
        raise _continuation_error(state)

    if not state.batch_id:
        raise MineruContinuationUnavailable(
            f"The saved recognition phase '{state.phase}' has no known remote "
            "task identifier, so it cannot be continued automatically. The "
            "document will not be submitted again.")

    if not (token or "").strip():
        raise MineruTokenMissing(
            "No MinerU token is configured. Continuing the saved recognition "
            "task requires the account token; set MINERU_API_TOKEN in the "
            "environment before continuing.")

    deadline = started + max(0.0, float(budget_seconds))
    return _run_continuation(
        state, described, workspace=workspace, store=store, token=token or "",
        started=started, deadline=deadline, clock=clock, sleep=sleep,
        poll_interval_seconds=poll_interval_seconds,
        check_interruption=check_interruption, progress=progress, log=log,
    )


def _continuation_error(state: RecognitionState) -> MineruError:
    """An actionable, truthful error for a phase that cannot be continued."""
    if state.phase in {"submitting", "submission_unknown"}:
        return MineruContinuationUnavailable(
            "A previous MinerU submission may have succeeded but its outcome "
            "is not known. The document will not be submitted again; check "
            "MinerU before starting a new task.")
    if state.phase == "upload_failed":
        return MineruContinuationUploadUnrecoverable(
            "The upload to MinerU storage did not complete, and the one-time "
            "upload destination is not retained in the saved task data. This "
            "task cannot be continued automatically; the document was not "
            "submitted again.")
    if state.phase in {"rejected", "failed"}:
        return MineruContinuationUnavailable(
            f"The previous recognition outcome was terminal ('{state.phase}'). "
            "It cannot be continued automatically and the document will not be "
            "submitted again; start a new task if another recognition is wanted.")
    return MineruContinuationUnavailable(
        f"The saved recognition phase '{state.phase}' cannot be continued "
        "safely. The document will not be submitted again automatically.")


def _reuse_validated(
    state: RecognitionState,
    described: AdmittedSource,
    *,
    workspace: Path,
    started: float,
    clock: Callable[[], float],
    progress: Optional[Callable[[str], None]],
    log: Optional[Callable[[str, str], None]],
) -> RecognitionResult:
    """Reuse an already validated result; no provider request is made."""
    try:
        online = load_validated_result(
            workspace / "result",
            admitted=described,
            expected_zip_sha256=state.result_zip_sha256,
            expected_cache_sha256=state.result_cache_sha256,
        )
    except MineruResultInvalid as exc:
        raise MineruContinuationResultUnavailable(
            "The previously validated recognition result is missing or no "
            f"longer usable ({exc}). The saved task record is preserved and "
            "the document will not be submitted again automatically; start a "
            "new task if recognition must run again.") from exc

    source = adapt(online.cache)
    _notify(progress, "reused")
    _log(log, "pdf_mineru_reused",
         f"♻️ Reusing the validated MinerU result ({online.page_count} pages, "
         f"{len(source.paragraphs)} paragraphs); no provider request was made.")
    return _result(described, source, online, state.batch_id or "", started,
                   clock, state.retries, ("done",), reused=True, continued=False)


def _run_continuation(
    state: RecognitionState,
    admitted: AdmittedSource,
    *,
    workspace: Path,
    store: Optional[object],
    token: str,
    started: float,
    deadline: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    poll_interval_seconds: float,
    check_interruption: Optional[Callable[[], bool]],
    progress: Optional[Callable[[str], None]],
    log: Optional[Callable[[str, str], None]],
) -> RecognitionResult:
    """Re-poll and re-download a known remote task; never re-upload or submit."""
    client = MineruClient(token, clock=clock, sleep=sleep)
    remote_states: List[str] = []
    base_elapsed = float(state.elapsed_seconds)
    base_retries = int(state.retries)

    def save(**changes) -> RecognitionState:
        nonlocal state
        changes.setdefault(
            "elapsed_seconds",
            round(base_elapsed + max(0.0, clock() - started), 3))
        changes.setdefault("retries", base_retries + client.retries)
        state = state.with_updates(**changes)
        if store is not None:
            store.save(state)
        return state

    try:
        _notify(progress, "continuing")
        _log(log, "pdf_mineru_continuing",
             "↻ Continuing the saved MinerU task: checking the existing remote "
             "recognition result. The PDF is not uploaded again.")
        save(
            phase="recognizing",
            continuations=state.continuations + 1,
            error_code=None,
            error_message=None,
        )
        online = _poll_download_validate(
            client, state, admitted,
            workspace=workspace, save=save, deadline=deadline,
            poll_interval_seconds=poll_interval_seconds, clock=clock, sleep=sleep,
            check_interruption=check_interruption, remote_states=remote_states,
            progress=progress, log=log,
        )
        save(
            phase="validated",
            remote_state="done",
            result_zip_sha256=online.zip_sha256,
            result_cache_sha256=online.cache_sha256,
            result_pages=online.page_count,
            error_code=None,
            error_message=None,
        )
        _notify(progress, "validated")
        source = adapt(online.cache)
        _log(log, "pdf_mineru_continued",
             f"✅ Continued the existing MinerU task: {online.page_count} pages "
             f"validated, {len(source.paragraphs)} source paragraphs. No "
             "submission or upload was repeated.")
        return _result(admitted, source, online, state.batch_id or "", started,
                       clock, client.retries, remote_states, reused=False,
                       continued=True)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# First submission of a task record (fresh task, or a recorded ``admitted``)
# ---------------------------------------------------------------------------


def _run_submission(
    state: RecognitionState,
    admitted: AdmittedSource,
    *,
    workspace: Path,
    store: Optional[object],
    token: Optional[str],
    started: float,
    deadline: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    poll_interval_seconds: float,
    check_interruption: Optional[Callable[[], bool]],
    progress: Optional[Callable[[str], None]],
    log: Optional[Callable[[str, str], None]],
    continued: bool = False,
) -> RecognitionResult:
    """Issue the one submission this task record proves never happened."""
    client = MineruClient(token or "", clock=clock, sleep=sleep)
    remote_states: List[str] = []
    base_elapsed = float(state.elapsed_seconds)
    base_retries = int(state.retries)

    def save(**changes) -> RecognitionState:
        nonlocal state
        changes.setdefault(
            "elapsed_seconds",
            round(base_elapsed + max(0.0, clock() - started), 3))
        changes.setdefault("retries", base_retries + client.retries)
        state = state.with_updates(**changes)
        if store is not None:
            store.save(state)
        return state

    def emit(phase: str) -> None:
        _notify(progress, phase)

    try:
        save()
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
        except MineruSubmissionRejected as exc:
            # The provider definitely accepted no task: a later continuation
            # may safely try the submission again.
            save(phase="admitted", error_code=exc.code, error_message=str(exc))
            raise
        except MineruTimeout as exc:
            if getattr(exc, "request_sent", True) is False:
                # The deadline elapsed before the request left the process.
                # This is a local pause, not an ambiguous remote outcome.
                save(phase="admitted", error_code=exc.code,
                     error_message=str(exc))
                raise
            save(phase="submission_unknown", error_code=exc.code,
                 error_message=str(exc))
            raise MineruSubmissionUncertain(
                "The MinerU submission outcome is unknown (the request did not "
                "complete cleanly). The document will not be submitted again "
                "automatically.") from exc
        except (MineruNetworkError, MineruResponseInvalid) as exc:
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
        save(phase="recognizing")
        online = _poll_download_validate(
            client, state, admitted,
            workspace=workspace, save=save, deadline=deadline,
            poll_interval_seconds=poll_interval_seconds, clock=clock, sleep=sleep,
            check_interruption=check_interruption, remote_states=remote_states,
            progress=progress, log=log,
        )
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
        source = adapt(online.cache)
        _log(log, "pdf_mineru_validated",
             f"✅ MinerU result validated: {online.page_count} pages, "
             f"{len(source.paragraphs)} source paragraphs.")
        return _result(admitted, source, online, ticket.batch_id, started, clock,
                       client.retries, remote_states, reused=False,
                       continued=continued)
    finally:
        client.close()


def _poll_download_validate(
    client: MineruClient,
    state: RecognitionState,
    admitted: AdmittedSource,
    *,
    workspace: Path,
    save: Callable[..., RecognitionState],
    deadline: float,
    poll_interval_seconds: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    check_interruption: Optional[Callable[[], bool]],
    remote_states: List[str],
    progress: Optional[Callable[[str], None]],
    log: Optional[Callable[[str, str], None]],
) -> OnlineResult:
    """Poll the known task to completion, download the result and validate it."""
    zip_url = _poll_until_done(
        client, state.batch_id or "", state.file_name, deadline=deadline,
        poll_interval_seconds=poll_interval_seconds, clock=clock, sleep=sleep,
        check_interruption=check_interruption, remote_states=remote_states,
        save=save, log=log,
    )

    _notify(progress, "downloading")
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
    except (MineruResultInvalid, MineruNetworkError, MineruResponseInvalid) as exc:
        save(phase="downloading", error_code=exc.code, error_message=str(exc))
        raise

    _notify(progress, "validating")
    save(phase="validating")
    if sha256_file(admitted.path) != admitted.sha256:
        message = ("The source PDF changed during recognition, so the "
                   "returned result cannot be accepted.")
        save(error_code=MineruResultInvalid.code, error_message=message)
        raise MineruResultInvalid(message)
    try:
        return build_online_result(
            archive_path, work_dir=workspace, admitted=admitted)
    except MineruResultInvalid as exc:
        save(error_code=exc.code, error_message=str(exc))
        raise


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
                 error_code=MineruInterrupted.code,
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
        except MineruRequestRejected as exc:
            # A definite provider rejection of the polling request (for
            # example an unknown/expired task identifier) is terminal: it is
            # not a local deadline and re-polling the same request cannot help.
            save(phase="failed", error_code=exc.code, error_message=str(exc))
            raise
        except (MineruNetworkError, MineruResponseInvalid) as exc:
            # Read-only retries are safe; the known remote task is preserved so
            # a later user-requested continuation can re-poll it.
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
    save(phase="timed_out", error_code=MineruTimeout.code,
         error_message=message)
    raise MineruTimeout(message)


def _result(admitted: AdmittedSource, source: SourceContent, online: OnlineResult,
            batch_id: str, started: float, clock: Callable[[], float],
            retries: int, remote_states: List[str], *, reused: bool,
            continued: bool = False) -> RecognitionResult:
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
        continued=continued,
    )


def _data_id(admitted: AdmittedSource) -> str:
    return f"{_DATA_ID_PREFIX}{admitted.sha256[:20]}"


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
