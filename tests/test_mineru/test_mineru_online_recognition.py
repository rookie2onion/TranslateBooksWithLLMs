"""Online recognition orchestration for one task (issue #20).

Seam under test: ``recognize_pdf`` — the complete recognition attempt: admission,
durable phase records, provider submission/upload/poll/download, result
validation, the 300-second local budget, bounded retries and cooperative stop.

The provider is the scripted fake HTTP layer; the durable state is the real
task-owned store; the clock is a fake so budget scenarios need no waiting.
"""

from __future__ import annotations

import json

import pytest
import requests

from src.core.mineru.errors import (
    MineruAuthorizationRequired,
    MineruContinuationUnavailable,
    MineruInterrupted,
    MineruNetworkError,
    MineruRecognitionFailed,
    MineruRequestRejected,
    MineruResultInvalid,
    MineruSubmissionRejected,
    MineruSubmissionUncertain,
    MineruTimeout,
    MineruTokenMissing,
    MineruUploadFailed,
)
from src.core.mineru.recognition import recognize_pdf
from src.core.mineru.recognition_state import RecognitionState, TaskRecognitionStore
from src.persistence.checkpoint_manager import CheckpointManager
from tests.test_mineru.online_fixtures import (
    BATCH_ID,
    FakeClock,
    FakeMineruHttp,
    build_source_pdf,
    install_fake_http,
    result_zip_bytes,
    sha256_file,
)

TOKEN = "test-mineru-token"


@pytest.fixture
def manager(tmp_path):
    manager = CheckpointManager(
        db_path=str(tmp_path / "jobs.db"), uploads_dir=tmp_path / "uploads")
    yield manager
    manager.close()


def _recognize(manager, source, *, http, clock=None, budget=300, authorized=True,
               token=TOKEN, check_interruption=None, progress=None, job="trans_1"):
    clock = clock or FakeClock()
    store = TaskRecognitionStore(manager, job)
    result = recognize_pdf(
        source,
        work_dir=store.workspace(),
        authorized=authorized,
        token=token,
        store=store,
        budget_seconds=budget,
        clock=clock,
        sleep=clock.sleep,
        check_interruption=check_interruption,
        progress=progress,
    )
    return result, store, clock


def _http(monkeypatch, tmp_path, pages=3, **kwargs):
    http = FakeMineruHttp(zip_bytes=result_zip_bytes(page_count=pages, **kwargs))
    install_fake_http(monkeypatch, http)
    return http


def test_recognition_runs_the_complete_verifiable_path(tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=3)
    http = _http(monkeypatch, tmp_path, pages=3)
    phases = []

    result, store, _ = _recognize(
        manager, source, http=http, progress=phases.append)

    assert result.reused is False
    assert result.page_count == 3
    assert result.batch_id == BATCH_ID
    assert result.source.paragraphs[0] == "SAMPLE BOOK"
    assert result.admitted.sha256 == sha256_file(source)
    assert len(result.result_zip_sha256) == 64
    assert result.result_cache_sha256 == result.cache_sha256

    state = store.load()
    assert state.phase == "validated"
    assert state.source_sha256 == sha256_file(source)
    assert state.source_pages == 3
    assert state.batch_id == BATCH_ID
    assert state.result_zip_sha256 == result.result_zip_sha256
    assert state.result_cache_sha256 == result.cache_sha256
    assert state.result_pages == 3
    assert state.attempts == 1

    assert phases[0] == "submitting"
    assert "recognizing" in phases
    assert phases[-1] == "validated"
    assert http.storage_calls(), "the source was never uploaded to storage"

    payload = json.loads(
        (store.workspace() / "recognition-state.json").read_text(encoding="utf-8"))
    assert "https://" not in json.dumps(payload)
    assert "token" not in json.dumps(payload).lower()


def test_recognition_requires_authorization_before_any_provider_request(
        tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    http = _http(monkeypatch, tmp_path, pages=1)

    with pytest.raises(MineruAuthorizationRequired):
        _recognize(manager, source, http=http, authorized=False)

    assert http.requests == []
    assert TaskRecognitionStore(manager, "trans_1").load() is None


def test_recognition_requires_a_configured_token_before_any_provider_request(
        tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    http = _http(monkeypatch, tmp_path, pages=1)

    with pytest.raises(MineruTokenMissing):
        _recognize(manager, source, http=http, token="")

    assert http.requests == []


def test_a_validated_result_is_reused_without_any_provider_request(
        tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=2)
    http = _http(monkeypatch, tmp_path, pages=2)
    first, store, _ = _recognize(manager, source, http=http)
    requests_before = len(http.requests)

    second, _, _ = _recognize(manager, source, http=http)

    assert second.reused is True
    assert second.result_cache_sha256 == first.result_cache_sha256
    assert second.page_count == 2
    assert len(http.requests) == requests_before, "reuse must not contact MinerU"


@pytest.mark.parametrize("phase", [
    "submitted", "uploaded", "recognizing", "downloading", "validating",
    "timed_out", "interrupted_local",
])
def test_a_persisted_remote_task_is_continued_without_resubmission(
        tmp_path, manager, monkeypatch, phase):
    source = build_source_pdf(tmp_path / "source.pdf", pages=2)
    store = TaskRecognitionStore(manager, "trans_1")
    store.save(RecognitionState(
        phase=phase,
        source_sha256=sha256_file(source),
        source_bytes=source.stat().st_size,
        source_pages=2,
        file_name=source.name,
        batch_id=BATCH_ID,
        remote_state="running",
    ))
    http = _http(monkeypatch, tmp_path, pages=2)

    result, _, _ = _recognize(manager, source, http=http)

    assert result.continued is True
    assert result.reused is False
    assert result.batch_id == BATCH_ID
    assert http.submitted_files() == [], "a known remote task must never be resubmitted"
    # Only the result download touches storage: no upload happened again.
    assert len(http.storage_calls()) == 1
    state = store.load()
    assert state.phase == "validated"
    assert state.attempts == 0
    assert state.continuations == 1


def test_a_recorded_admitted_phase_performs_the_first_submission(
        tmp_path, manager, monkeypatch):
    """No request was ever issued, so a continuation may still submit once."""
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    store = TaskRecognitionStore(manager, "trans_1")
    store.save(RecognitionState(
        phase="admitted",
        source_sha256=sha256_file(source),
        source_bytes=source.stat().st_size,
        source_pages=1,
        file_name=source.name,
    ))
    http = _http(monkeypatch, tmp_path, pages=1)

    result, _, _ = _recognize(manager, source, http=http)

    assert result.continued is True
    assert len(http.submitted_files()) == 1
    state = store.load()
    assert state.phase == "validated"
    assert state.attempts == 1
    assert state.continuations == 0


def test_admitted_continuation_still_requires_authorization(
        tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    store = TaskRecognitionStore(manager, "trans_1")
    store.save(RecognitionState(
        phase="admitted",
        source_sha256=sha256_file(source),
        source_bytes=source.stat().st_size,
        source_pages=1,
        file_name=source.name,
    ))
    http = _http(monkeypatch, tmp_path, pages=1)

    with pytest.raises(MineruAuthorizationRequired):
        _recognize(manager, source, http=http, authorized=False)

    assert http.requests == []
    assert store.load().phase == "admitted"


def test_an_unknown_submission_outcome_is_never_replaced(tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    http = _http(monkeypatch, tmp_path, pages=1)

    def fail(**_kwargs):
        raise requests.ConnectionError("connection reset after the request")

    http.submit_override = lambda: fail()
    with pytest.raises(MineruSubmissionUncertain):
        _recognize(manager, source, http=http)

    state = TaskRecognitionStore(manager, "trans_1").load()
    assert state.phase == "submission_unknown"

    posts_before = len(http.submitted_files())
    with pytest.raises(MineruContinuationUnavailable):
        _recognize(manager, source, http=http)
    assert len(http.submitted_files()) == posts_before


def test_a_pre_send_timeout_proves_no_request_was_issued(
        tmp_path, manager, monkeypatch):
    """A timeout before the POST is sent is retryable, not submission_unknown."""
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    http = _http(monkeypatch, tmp_path, pages=1)

    with pytest.raises(MineruTimeout):
        _recognize(manager, source, http=http, budget=0)

    assert http.requests == [], "a pre-send timeout must issue no request"
    state = TaskRecognitionStore(manager, "trans_1").load()
    assert state.phase == "admitted"
    assert state.batch_id is None
    assert state.error_code == "mineru_recognition_timeout"

    # A continuation may perform the first submission: nothing was accepted.
    result, _, _ = _recognize(manager, source, http=http)
    assert result.page_count == 1
    assert len(http.submitted_files()) == 1


def test_a_rate_limited_submission_is_recorded_as_retryable(
        tmp_path, manager, monkeypatch):
    """HTTP 429 definitely accepted no task, so Continue may submit once more."""
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    http = _http(monkeypatch, tmp_path, pages=1)

    from tests.test_mineru.online_fixtures import API_BASE, response
    http.submit_override = lambda: response(
        f"{API_BASE}/file-urls/batch", b"busy", status=429)

    with pytest.raises(MineruSubmissionRejected):
        _recognize(manager, source, http=http)

    state = TaskRecognitionStore(manager, "trans_1").load()
    assert state.phase == "admitted"
    assert state.batch_id is None
    assert state.error_code == "mineru_submission_rejected"
    assert len(http.submitted_files()) == 1

    http.submit_override = None
    result, _, _ = _recognize(manager, source, http=http)
    assert result.page_count == 1
    assert len(http.submitted_files()) == 2, "the rejected submission is retried once"


def test_a_definite_provider_rejection_is_recorded(tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    http = _http(monkeypatch, tmp_path, pages=1)

    def rejected():
        from tests.test_mineru.online_fixtures import API_BASE, response
        return response(f"{API_BASE}/file-urls/batch",
                        json.dumps({"code": -60008, "msg": "timeout"}).encode())

    http.submit_override = rejected
    with pytest.raises(MineruRequestRejected):
        _recognize(manager, source, http=http)

    state = TaskRecognitionStore(manager, "trans_1").load()
    assert state.phase == "rejected"
    assert state.error_code == "mineru_provider_rejected"

    with pytest.raises(MineruContinuationUnavailable):
        _recognize(manager, source, http=http)


def test_an_upload_failure_blocks_automatic_resubmission(tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    http = _http(monkeypatch, tmp_path, pages=1)
    from tests.test_mineru.online_fixtures import UPLOAD_URL, response
    http.upload_override = lambda: response(UPLOAD_URL, status=500)

    with pytest.raises(MineruUploadFailed):
        _recognize(manager, source, http=http)

    state = TaskRecognitionStore(manager, "trans_1").load()
    assert state.phase == "upload_failed"
    assert state.batch_id == BATCH_ID

    with pytest.raises(MineruContinuationUnavailable):
        _recognize(manager, source, http=http)


def test_remote_recognition_failure_is_reported_honestly(tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    http = _http(monkeypatch, tmp_path, pages=1)
    http.poll_states = ["failed"]

    with pytest.raises(MineruRecognitionFailed):
        _recognize(manager, source, http=http)

    state = TaskRecognitionStore(manager, "trans_1").load()
    assert state.phase == "failed"
    assert state.remote_state == "failed"
    assert "https://" not in (state.error_message or "")


def test_the_local_budget_ends_the_attempt_without_claiming_completion(
        tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    http = _http(monkeypatch, tmp_path, pages=1)
    http.poll_states = ["running"]
    clock = FakeClock()

    with pytest.raises(MineruTimeout) as raised:
        _recognize(manager, source, http=http, clock=clock, budget=10)

    assert "budget" in str(raised.value).lower()
    state = TaskRecognitionStore(manager, "trans_1").load()
    assert state.phase == "timed_out"
    assert state.batch_id == BATCH_ID
    assert clock.sleeps, "polling did not wait at all"
    assert sum(clock.sleeps) <= 10
    # No result was downloaded or validated.
    assert not (TaskRecognitionStore(manager, "trans_1").workspace() / "result").exists()


def test_a_local_stop_is_cooperative_and_not_remote_cancellation(
        tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    http = _http(monkeypatch, tmp_path, pages=1)
    stop = {"value": False}
    from tests.test_mineru.online_fixtures import UPLOAD_URL, response
    http.upload_override = lambda: (stop.__setitem__("value", True),
                                    response(UPLOAD_URL, status=200))[1]

    with pytest.raises(MineruInterrupted) as raised:
        _recognize(manager, source, http=http,
                   check_interruption=lambda: stop["value"])

    assert "may continue" in str(raised.value).lower()
    state = TaskRecognitionStore(manager, "trans_1").load()
    assert state.phase == "interrupted_local"
    assert state.batch_id == BATCH_ID


def test_a_result_that_does_not_match_the_source_is_rejected(
        tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=3)
    http = _http(monkeypatch, tmp_path, pages=2)

    with pytest.raises(MineruResultInvalid):
        _recognize(manager, source, http=http)

    state = TaskRecognitionStore(manager, "trans_1").load()
    assert state.phase != "validated"

    # Continuing re-checks the same known task and still refuses the invalid
    # result; it never falls back to submitting the document again.
    with pytest.raises(MineruResultInvalid):
        _recognize(manager, source, http=http)
    assert len(http.submitted_files()) == 1
    assert TaskRecognitionStore(manager, "trans_1").load().phase != "validated"


def test_a_definite_poll_rejection_is_terminal_not_a_local_deadline(
        tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    http = _http(monkeypatch, tmp_path, pages=1)
    from tests.test_mineru.online_fixtures import API_BASE, response
    http.status_override = lambda index: response(
        f"{API_BASE}/extract-results/batch/{BATCH_ID}",
        json.dumps({"code": -60001, "msg": "task not found"}).encode("utf-8"))

    with pytest.raises(MineruRequestRejected):
        _recognize(manager, source, http=http)

    state = TaskRecognitionStore(manager, "trans_1").load()
    assert state.phase == "failed"
    assert state.error_code == "mineru_provider_rejected"

    requests_before = len(http.requests)
    with pytest.raises(MineruContinuationUnavailable):
        _recognize(manager, source, http=http)
    assert len(http.requests) == requests_before
    assert len(http.submitted_files()) == 1


def test_a_transient_status_error_keeps_the_known_remote_task(
        tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    http = _http(monkeypatch, tmp_path, pages=1)
    from tests.test_mineru.online_fixtures import API_BASE, response
    http.status_override = lambda index: response(
        f"{API_BASE}/extract-results/batch/{BATCH_ID}", b"busy", status=503)

    with pytest.raises(MineruNetworkError):
        _recognize(manager, source, http=http)

    state = TaskRecognitionStore(manager, "trans_1").load()
    assert state.phase == "recognizing"
    assert state.batch_id == BATCH_ID


def test_a_changed_source_is_never_validated_against_an_old_result(
        tmp_path, manager, monkeypatch):
    source = build_source_pdf(tmp_path / "source.pdf", pages=2)
    http = _http(monkeypatch, tmp_path, pages=2)
    _recognize(manager, source, http=http)

    # Same path, different bytes: the fingerprint no longer matches.
    build_source_pdf(source, pages=2, text_layer=False)

    with pytest.raises(MineruContinuationUnavailable) as raised:
        _recognize(manager, source, http=http)

    assert "changed" in str(raised.value).lower()
