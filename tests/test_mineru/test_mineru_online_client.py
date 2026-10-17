"""MinerU online client contract (issue #20).

Seam under test: the public operations of :class:`MineruClient` — request an
upload ticket, upload the source, poll the task, download the result. The
installed HTTP stack is real; only ``requests.Session.request`` is replaced, so
headers, deadlines and validation all run.
"""

from __future__ import annotations

import json

import pytest

from src.core.mineru.client import API_BASE, MineruClient, RemoteTaskState, UploadTicket
from src.core.mineru.errors import (
    MineruNetworkError,
    MineruRecognitionFailed,
    MineruRequestRejected,
    MineruResponseInvalid,
    MineruResultInvalid,
    MineruSubmissionRejected,
    MineruTimeout,
    MineruUploadFailed,
)
from tests.test_mineru.online_fixtures import (
    BATCH_ID,
    FILE_NAME,
    RESULT_URL,
    UPLOAD_URL,
    FakeClock,
    FakeMineruHttp,
    build_source_pdf,
    install_fake_http,
    response,
    result_zip_bytes,
)

TOKEN = "test-mineru-token"


def _client(clock=None, **kwargs):
    clock = clock or FakeClock()
    return MineruClient(TOKEN, clock=clock, sleep=clock.sleep, **kwargs)


def _deadline(clock, seconds=300):
    return clock() + seconds


def _submit(client, clock):
    return client.request_upload(FILE_NAME, "data-1", deadline=_deadline(clock))


def test_standard_upload_poll_download_contract(tmp_path, monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp(
        zip_bytes=result_zip_bytes(page_count=2)))
    source = build_source_pdf(tmp_path / "source.pdf", pages=2)
    client = _client(clock)

    ticket = _submit(client, clock)
    assert ticket == UploadTicket(batch_id=BATCH_ID, upload_url=UPLOAD_URL)

    submitted = http.submitted_files()
    assert len(submitted) == 1
    assert submitted[0]["files"] == [
        {"name": FILE_NAME, "is_ocr": True, "data_id": "data-1"}]
    assert submitted[0]["model_version"] == "vlm"
    assert submitted[0]["language"] == "latin"
    assert submitted[0]["enable_table"] is True
    assert submitted[0]["enable_formula"] is True

    client.upload(ticket, source, deadline=_deadline(clock))
    state = client.poll(BATCH_ID, expected_file_name=FILE_NAME,
                        deadline=_deadline(clock))
    assert state == RemoteTaskState(state="done", full_zip_url=RESULT_URL)

    destination = tmp_path / "result.zip"
    client.download(state.full_zip_url, destination, deadline=_deadline(clock))
    assert destination.read_bytes() == http.zip_bytes

    # Provider credentials travel only on provider API calls.
    api_headers = [call["headers"] for call in http.api_calls()]
    assert api_headers and all(
        headers.get("Authorization") == f"Bearer {TOKEN}" for headers in api_headers)
    assert http.storage_calls(), "the storage requests were not exercised"
    for call in http.storage_calls():
        assert "Authorization" not in call["headers"]
    # No request may follow a redirect to an unverified destination.
    assert all(call["allow_redirects"] is False for call in http.requests)


def test_application_error_under_http_200_is_rejected(tmp_path, monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    http.submit_override = lambda: response(
        f"{API_BASE}/file-urls/batch",
        json.dumps({"code": -60008, "msg": "file read timeout"}).encode(),
    )
    client = _client(clock)

    with pytest.raises(MineruRequestRejected) as raised:
        _submit(client, clock)

    assert raised.value.provider_code == "-60008"
    assert "token" not in str(raised.value).lower()
    assert http.storage_calls() == []


def test_http_auth_failure_is_a_rejection(tmp_path, monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    http.submit_override = lambda: response(
        f"{API_BASE}/file-urls/batch", b"unauthorized", status=401)
    client = _client(clock)

    with pytest.raises(MineruRequestRejected) as raised:
        _submit(client, clock)

    assert "401" in str(raised.value)
    assert TOKEN not in str(raised.value)


@pytest.mark.parametrize("body", [
    b"<html>not json</html>",
    b"[]",
    json.dumps({"code": 0, "data": []}).encode(),
    json.dumps({"code": 0, "data": {"file_urls": [UPLOAD_URL]}}).encode(),
    json.dumps({"code": 0, "data": {
        "batch_id": "bad batch id", "file_urls": [UPLOAD_URL]}}).encode(),
    json.dumps({"code": 0, "data": {
        "batch_id": BATCH_ID, "file_urls": []}}).encode(),
    json.dumps({"code": 0, "data": {
        "batch_id": BATCH_ID, "file_urls": [UPLOAD_URL, UPLOAD_URL]}}).encode(),
])
def test_malformed_submission_payloads_are_rejected(body, monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    http.submit_override = lambda: response(f"{API_BASE}/file-urls/batch", body)
    client = _client(clock)

    with pytest.raises(MineruResponseInvalid):
        _submit(client, clock)
    assert http.storage_calls() == []


@pytest.mark.parametrize("url", [
    "http://mineru-upload.oss-cn-hangzhou.aliyuncs.com/upload/doc-1",
    "https://evil.example.com/upload/doc-1",
    "https://user:pass@mineru-upload.oss-cn-hangzhou.aliyuncs.com/upload/doc-1",
    "https://mineru-upload.oss-cn-hangzhou.aliyuncs.com:8443/upload/doc-1",
    "https://notaliyuncs.com/upload/doc-1",
])
def test_unverified_storage_destinations_are_rejected(url, monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    http.submit_override = lambda: response(
        f"{API_BASE}/file-urls/batch",
        json.dumps({"code": 0, "data": {
            "batch_id": BATCH_ID, "file_urls": [url]}}).encode())
    client = _client(clock)

    with pytest.raises(MineruResponseInvalid):
        client.request_upload(FILE_NAME, "data-1", deadline=_deadline(clock))
    assert http.storage_calls() == []


def test_upload_reports_storage_failure_without_leaking_the_url(tmp_path, monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    http.upload_override = lambda: response(UPLOAD_URL, b"denied", status=403)
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    client = _client(clock)
    ticket = _submit(client, clock)

    with pytest.raises(MineruUploadFailed) as raised:
        client.upload(ticket, source, deadline=_deadline(clock))

    assert "403" in str(raised.value)
    assert "signature" not in str(raised.value).lower()
    assert UPLOAD_URL not in str(raised.value)


@pytest.mark.parametrize("row,expected", [
    ({"file_name": "other.pdf", "state": "done", "full_zip_url": RESULT_URL},
     MineruResponseInvalid),
    ({"file_name": FILE_NAME, "state": "weird", "full_zip_url": RESULT_URL},
     MineruResponseInvalid),
    ({"file_name": FILE_NAME, "state": "done"},
     MineruResponseInvalid),
    ({"file_name": FILE_NAME, "state": "done", "full_zip_url": "https://evil.example.com/x.zip"},
     MineruResponseInvalid),
])
def test_poll_rejects_mismatched_or_unknown_results(row, expected, monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    http.status_override = lambda index: response(
        f"{API_BASE}/extract-results/batch/{BATCH_ID}",
        json.dumps({"code": 0, "data": {"extract_result": [row]}}).encode())
    client = _client(clock)

    with pytest.raises(expected):
        client.poll(BATCH_ID, expected_file_name=FILE_NAME, deadline=_deadline(clock))


def test_poll_rejects_a_multi_document_batch(monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    row = {"file_name": FILE_NAME, "state": "done", "full_zip_url": RESULT_URL}
    http.status_override = lambda index: response(
        f"{API_BASE}/extract-results/batch/{BATCH_ID}",
        json.dumps({"code": 0, "data": {"extract_result": [row, row]}}).encode())
    client = _client(clock)

    with pytest.raises(MineruResponseInvalid):
        client.poll(BATCH_ID, expected_file_name=FILE_NAME, deadline=_deadline(clock))


def test_poll_reports_remote_failure_with_a_sanitized_reason(monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    http.status_override = lambda index: response(
        f"{API_BASE}/extract-results/batch/{BATCH_ID}",
        json.dumps({"code": 0, "data": {"extract_result": [{
            "file_name": FILE_NAME,
            "state": "failed",
            "err_msg": "parse failed, see https://signed.example.com/x?Signature=secret",
        }]}}).encode())
    client = _client(clock)

    with pytest.raises(MineruRecognitionFailed) as raised:
        client.poll(BATCH_ID, expected_file_name=FILE_NAME, deadline=_deadline(clock))

    assert "parse failed" in str(raised.value)
    assert "https://" not in str(raised.value)
    assert "Signature" not in str(raised.value)


def test_a_rate_limited_submission_is_a_definite_rejection(monkeypatch):
    """The submission request is not idempotent: a 429 is not replayed.

    A 429 also means the provider accepted nothing, so it is a definite
    pre-acceptance rejection rather than an ambiguous transport outcome.
    """
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    http.submit_override = lambda: response(
        f"{API_BASE}/file-urls/batch", b"busy", status=429)
    client = _client(clock, max_retries=5)

    with pytest.raises(MineruSubmissionRejected) as raised:
        client.request_upload(FILE_NAME, "data-1", deadline=_deadline(clock))

    assert "429" in str(raised.value)
    assert len(http.submitted_files()) == 1
    assert client.retries == 0


def test_transient_status_errors_are_retried_within_the_deadline(monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    attempts = {"count": 0}

    def status(index):
        attempts["count"] += 1
        if attempts["count"] < 3:
            return response(f"{API_BASE}/extract-results/batch/{BATCH_ID}",
                            b"busy", status=503)
        return response(
            f"{API_BASE}/extract-results/batch/{BATCH_ID}",
            json.dumps({"code": 0, "data": {"extract_result": [{
                "file_name": FILE_NAME, "state": "done",
                "full_zip_url": RESULT_URL}]}}).encode())

    http.status_override = status
    client = _client(clock, max_retries=2)

    state = client.poll(BATCH_ID, expected_file_name=FILE_NAME,
                        deadline=_deadline(clock))

    assert state.state == "done"
    assert attempts["count"] == 3
    assert len(clock.sleeps) == 2
    assert all(seconds > 0 for seconds in clock.sleeps)


def test_exhausted_retries_fail_without_claiming_completion(monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    http.status_override = lambda index: response(
        f"{API_BASE}/extract-results/batch/{BATCH_ID}", b"busy", status=503)
    client = _client(clock, max_retries=1)

    with pytest.raises(MineruNetworkError):
        client.poll(BATCH_ID, expected_file_name=FILE_NAME,
                    deadline=_deadline(clock))


def test_retries_share_the_deadline(monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    http.status_override = lambda index: response(
        f"{API_BASE}/extract-results/batch/{BATCH_ID}", b"busy", status=503)
    client = _client(clock, max_retries=10, retry_backoff_seconds=60.0)

    with pytest.raises(MineruTimeout):
        client.poll(BATCH_ID, expected_file_name=FILE_NAME,
                    deadline=_deadline(clock, seconds=90))


def test_operations_refuse_to_start_after_the_deadline(monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp())
    client = _client(clock)

    with pytest.raises(MineruTimeout):
        client.request_upload(FILE_NAME, "data-1", deadline=clock() - 1)
    assert http.requests == []


def test_download_is_bounded_by_the_resource_ceiling(tmp_path, monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp(zip_bytes=b"x" * 4096))
    client = _client(clock, max_download_bytes=1024)

    with pytest.raises(MineruResultInvalid):
        client.download(RESULT_URL, tmp_path / "result.zip",
                        deadline=_deadline(clock))
    assert not (tmp_path / "result.zip").exists()


def test_download_checks_interruption_and_the_deadline(tmp_path, monkeypatch):
    clock = FakeClock()
    http = install_fake_http(monkeypatch, FakeMineruHttp(zip_bytes=b"x" * 64))
    client = _client(clock)

    with pytest.raises(Exception) as raised:
        client.download(RESULT_URL, tmp_path / "result.zip",
                        deadline=_deadline(clock),
                        check_interruption=lambda: True)
    assert getattr(raised.value, "code", "") == "mineru_recognition_interrupted"

    before = len(http.calls(lambda call: call["url"] == RESULT_URL))
    with pytest.raises(MineruTimeout):
        client.download(RESULT_URL, tmp_path / "result.zip",
                        deadline=clock() - 1)
    after = len(http.calls(lambda call: call["url"] == RESULT_URL))
    assert after == before, "an expired deadline must not issue a request"


def test_upload_is_aborted_when_the_budget_runs_out(tmp_path, monkeypatch):
    """A slow upload is bounded by the remaining budget, not just per-read.

    The fake transport reads the real stream the client passes it, advancing a
    fake clock between reads exactly like a throttled 50 MB upload would.
    """
    clock = FakeClock()
    observed = {}
    reads = []

    class SlowUploadHttp(FakeMineruHttp):
        def dispatch(self, method, url, **kwargs):
            if method.upper() == "PUT" and url == UPLOAD_URL:
                observed["attempts"] = observed.get("attempts", 0) + 1
                observed["timeout"] = kwargs.get("timeout")
                stream = kwargs.get("data")
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    reads.append(len(chunk))
                    clock.advance(60)
            return super().dispatch(method, url, **kwargs)

    http = install_fake_http(monkeypatch, SlowUploadHttp())
    source = tmp_path / "source.pdf"
    source.write_bytes(b"x" * (6 * 1024 * 1024))
    client = _client(clock)
    ticket = _submit(client, clock)
    started = clock()

    with pytest.raises(MineruTimeout):
        client.upload(ticket, source, deadline=started + 300)

    assert clock() - started <= 300, "the upload ran past the local budget"
    assert reads, "the fake transport never streamed the file"
    assert len(reads) == 5, "the upload was not aborted inside the budget"
    assert observed["attempts"] == 1
    connect, read = observed["timeout"]
    assert connect <= 300 and read <= 300
    assert client.retries == 0
