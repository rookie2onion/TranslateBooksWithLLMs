"""Primary acceptance seam for issue #20: the real Web/API task workflow.

These tests enter through the application's own HTTP surface — upload, task
creation, status, artifact download — with a temporary source file, a temporary
job database and a temporary output directory. Only the three external
boundaries are substituted: MinerU HTTP, the external LLM, and time (no real
waiting). Routing, admission, task storage, recognition-result adaptation,
translation orchestration, PDF generation and validation are real.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pymupdf
import pytest
from flask import Flask

import src.api.auth as api_auth
from src.api.routes import configure_routes
from src.api.translation_state import TranslationStateManager
from src.persistence.checkpoint_manager import CheckpointManager
from src.utils.security import rate_limiter
from tests.test_mineru.online_fixtures import (
    FakeMineruHttp,
    build_corrupt_pdf,
    build_encrypted_pdf,
    build_source_pdf,
    install_fake_http,
    install_fake_llm,
    result_zip_bytes,
)

TERMINAL = {"completed", "partial", "error", "interrupted", "rate_limited"}
PROVIDER_TOKEN = "test-mineru-token"
LLM_PREFIX = "FR: "


class _FakeSocketIO:
    """Records emissions; the WebSocket transport is not the seam under test."""

    def __init__(self):
        self.events = []

    def emit(self, event, data=None, namespace=None, **kwargs):
        self.events.append((event, data, namespace))


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", PROVIDER_TOKEN)
    output_dir = tmp_path / "output"
    uploads_dir = output_dir / "uploads"
    uploads_dir.mkdir(parents=True)

    checkpoint_manager = CheckpointManager(
        db_path=str(tmp_path / "jobs.db"), uploads_dir=uploads_dir)
    state_manager = TranslationStateManager(
        checkpoint_manager=checkpoint_manager, server_session_id=str(int(time.time())))
    auth_state = api_auth.API_TOKEN

    app = Flask(
        __name__,
        template_folder=str(
            Path(__file__).resolve().parents[2] / "src" / "web" / "templates"),
    )
    app.config["TESTING"] = True

    def start_job(translation_id, config):
        from src.api.handlers import start_translation_job
        start_translation_job(
            translation_id, config, state_manager, str(output_dir), _FakeSocketIO())

    configure_routes(app, state_manager, str(output_dir), start_job)
    api_auth.register_auth(app)
    rate_limiter._requests.clear()

    client = app.test_client()
    client.environ_base["HTTP_X_API_TOKEN"] = auth_state

    # A deterministic fake provider for every test in this module.
    http = FakeMineruHttp()
    install_fake_http(monkeypatch, http)
    llm = install_fake_llm(monkeypatch)
    llm.prefix = LLM_PREFIX

    yield SimpleNamespace(
        app=app, client=client, output_dir=output_dir, uploads_dir=uploads_dir,
        state_manager=state_manager, manager=checkpoint_manager, http=http,
        llm=llm, tmp_path=tmp_path,
    )
    checkpoint_manager.close()


def _upload(web, path, filename=None):
    with open(path, "rb") as stream:
        response = web.client.post(
            "/api/upload",
            data={"file": (stream, filename or Path(path).name)},
            content_type="multipart/form-data",
        )
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _translation_payload(upload, *, authorized=True, bilingual=False,
                         output_filename="book (French).pdf"):
    payload = {
        "file_path": upload["file_path"],
        "file_type": "pdf",
        "source_language": "English",
        "target_language": "French",
        "model": "test-model",
        "llm_api_endpoint": "http://localhost:11434/api/generate",
        "llm_provider": "ollama",
        "output_filename": output_filename,
        "prompt_options": {"bilingual": bilingual},
    }
    if authorized:
        payload["mineru_authorized"] = True
    return payload


def _start(web, upload, **kwargs):
    return web.client.post("/api/translate", json=_translation_payload(upload, **kwargs))


def _wait_for_terminal(web, translation_id, timeout=60):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = web.client.get(f"/api/translation/{translation_id}")
        assert response.status_code == 200, response.get_json()
        last = response.get_json()
        if last["status"] in TERMINAL:
            return last
        time.sleep(0.02)
    raise AssertionError(f"job did not finish: {last}")


def _download(web, filename):
    return web.client.get(f"/api/files/{quote(filename)}")


def _pdf_text(path_or_bytes):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        document = pymupdf.open("pdf", bytes(path_or_bytes))
    else:
        document = pymupdf.open(str(path_or_bytes))
    try:
        return " ".join("".join(page.get_text() for page in document).split())
    finally:
        document.close()


def _sidecar_path(output_dir, filename):
    return Path(output_dir) / (filename + ".accounting.json")


def _assert_provider_credential_is_not_browser_visible(web, translation_id, status):
    """No browser-visible surface may echo the MinerU account token.

    The token lives only in the server environment; the job config carries the
    authorization boolean, never the credential. Inspect every payload a page
    actually receives: the status response, the translation/history lists, the
    rendered HTML, and the JS bootstrap config.
    """
    assert status["config"]["mineru_authorized"] is True
    assert "mineru_token" not in status["config"]
    assert "mineru_api_token" not in status["config"]

    payloads = {
        "status": json.dumps(web.client.get(
            f"/api/translation/{translation_id}").get_json()),
        "translations": json.dumps(
            web.client.get("/api/translations").get_json()),
        "history": json.dumps(web.client.get("/api/history").get_json()),
        "html": web.client.get("/").get_data(as_text=True),
        "js_config": json.dumps(web.client.get("/api/config").get_json()),
    }
    for surface, body in payloads.items():
        assert PROVIDER_TOKEN not in body, (
            f"the MinerU token leaked into {surface}")
        assert "mineru_api_token" not in body.lower(), (
            f"the MinerU token field leaked into {surface}")


def test_authorized_text_pdf_completes_and_downloads_a_translated_book(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=3)
    web.http.zip_bytes = result_zip_bytes(page_count=3)

    upload = _upload(web, source)
    response = _start(web, upload)
    assert response.status_code == 200, response.get_json()
    translation_id = response.get_json()["translation_id"]
    assert response.get_json()["config_received"]["mineru_authorized"] is True

    status = _wait_for_terminal(web, translation_id)
    assert status["status"] == "completed", status
    assert status["accounting"]["body_complete"] is True
    assert status["accounting"]["source_pages"] == 3
    assert status["accounting"]["result_pages"] == 3
    assert status["accounting"]["failed_chunks"] == 0
    _assert_provider_credential_is_not_browser_visible(web, translation_id, status)

    downloaded = _download(web, "book (French).pdf")
    assert downloaded.status_code == 200
    text = _pdf_text(downloaded.data)
    assert "FR: SAMPLE BOOK" in text
    assert "FR: Ada Lovelace" in text
    assert "FR: Figure 1: a caption" in text
    assert any(f"FR: A substantive footnote for page {page}" in text
               for page in (1, 2, 3))

    document = pymupdf.open("pdf", downloaded.data)
    try:
        assert document.metadata["title"] == "SAMPLE BOOK"
        assert document.metadata["author"] == ""
        assert "untranslated" not in (document.metadata["title"] or "").lower()
        assert sum(len(page.get_images()) for page in document) >= 1
        assert document.page_count >= 1
    finally:
        document.close()
    assert "untranslated mineru" not in text.lower()

    sidecar = _sidecar_path(web.output_dir, "book (French).pdf")
    assert sidecar.is_file()
    accounting = json.loads(sidecar.read_text(encoding="utf-8"))
    assert accounting["recognition"]["batch_id"] == "batch-abc123"
    assert accounting["translation"]["complete"] is True
    assert accounting["output"]["sha256"]

    # The external contract was exercised exactly once per operation.
    assert len(web.http.submitted_files()) == 1
    storage = web.http.storage_calls()
    assert len(storage) == 2  # upload PUT + result ZIP GET
    assert all("Authorization" not in call["headers"] for call in storage)
    # Completed recognition working data is pruned with the rest of the job
    # data; the status flips to 'completed' just before that cleanup runs, so
    # allow it a moment to finish.
    job_dir = web.uploads_dir / translation_id
    deadline = time.time() + 10
    while job_dir.exists() and time.time() < deadline:
        time.sleep(0.02)
    assert not job_dir.exists()

    history = web.client.get("/api/history").get_json()["history"]
    assert any(item["translation_id"] == translation_id
               and item["status"] == "completed" for item in history)


def test_scanned_pdf_uses_online_recognition_without_a_text_layer(web):
    source = build_source_pdf(web.tmp_path / "scanned.pdf", pages=2, text_layer=False)
    web.http.zip_bytes = result_zip_bytes(page_count=2)

    upload = _upload(web, source)
    assert upload["file_type"] == "pdf"
    response = _start(web, upload, output_filename="scanned (French).pdf")
    assert response.status_code == 200, response.get_json()
    status = _wait_for_terminal(web, response.get_json()["translation_id"])

    assert status["status"] == "completed", status
    downloaded = _download(web, "scanned (French).pdf")
    assert downloaded.status_code == 200
    assert "FR: SAMPLE BOOK" in _pdf_text(downloaded.data)
    assert len(web.http.submitted_files()) == 1


def test_missing_authorization_is_rejected_with_zero_provider_requests(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)

    upload = _upload(web, source)
    response = web.client.post(
        "/api/translate", json=_translation_payload(upload, authorized=False))

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["code"] == "mineru_authorization_required"
    assert web.http.requests == []
    assert web.client.get("/api/translations").get_json()["translations"] == []
    assert not any(web.uploads_dir.glob("trans_*"))


def test_missing_token_is_rejected_before_any_provider_request(web, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "")
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    upload = _upload(web, source)

    response = _start(web, upload)

    assert response.status_code == 400
    assert response.get_json()["code"] == "mineru_token_missing"
    assert web.http.requests == []


def test_encrypted_pdf_is_rejected_before_any_provider_request(web):
    encrypted = build_encrypted_pdf(web.tmp_path / "secret.pdf")
    # The secure uploader refuses it even earlier; prove both boundaries.
    with open(encrypted, "rb") as stream:
        rejected_upload = web.client.post(
            "/api/upload", data={"file": (stream, "secret.pdf")},
            content_type="multipart/form-data")
    assert rejected_upload.status_code == 400
    assert "assword" in rejected_upload.get_json()["error"]

    placed = web.uploads_dir / "0000000000000000_secret.pdf"
    placed.write_bytes(encrypted.read_bytes())
    response = web.client.post("/api/translate", json={
        **_translation_payload({"file_path": str(placed)}),
        "file_type": "pdf",
    })

    assert response.status_code == 400
    assert response.get_json()["code"] == "mineru_pdf_encrypted"
    assert web.http.requests == []


def test_corrupt_pdf_is_rejected_before_any_provider_request(web):
    corrupt = build_corrupt_pdf(web.tmp_path / "broken.pdf")
    with open(corrupt, "rb") as stream:
        rejected_upload = web.client.post(
            "/api/upload", data={"file": (stream, "broken.pdf")},
            content_type="multipart/form-data")
    assert rejected_upload.status_code == 400

    placed = web.uploads_dir / "0000000000000000_broken.pdf"
    placed.write_bytes(corrupt.read_bytes())
    response = web.client.post("/api/translate", json={
        **_translation_payload({"file_path": str(placed)}),
        "file_type": "pdf",
    })

    assert response.status_code == 400
    assert response.get_json()["code"] == "mineru_pdf_unreadable"
    assert web.http.requests == []


def test_the_page_ceiling_is_enforced_with_zero_provider_requests(web):
    source = build_source_pdf(web.tmp_path / "long.pdf", pages=201)
    upload = _upload(web, source)

    response = _start(web, upload)

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["code"] == "mineru_page_limit"
    assert payload["limits"]["max_pages"] == 200
    assert web.http.requests == []


def test_an_incomplete_recognition_result_is_not_published(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=3)
    web.http.zip_bytes = result_zip_bytes(page_count=3, layout_page_count=2)

    upload = _upload(web, source)
    response = _start(web, upload, output_filename="incomplete.pdf")
    assert response.status_code == 200
    status = _wait_for_terminal(web, response.get_json()["translation_id"])

    assert status["status"] == "error"
    assert status["error_code"] == "mineru_result_invalid"
    assert "page" in (status["error"] or "").lower()
    assert _download(web, "incomplete.pdf").status_code == 404
    assert not _sidecar_path(web.output_dir, "incomplete.pdf").exists()


def test_unsupported_content_fails_explicitly_instead_of_being_omitted(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    pages = [[{"type": "chart", "text": "a chart", "bbox": [10, 10, 500, 500]}]]
    web.http.zip_bytes = result_zip_bytes(page_count=1, pages=pages)

    upload = _upload(web, source)
    response = _start(web, upload, output_filename="unsupported.pdf")
    status = _wait_for_terminal(web, response.get_json()["translation_id"])

    assert status["status"] == "error"
    assert status["error_code"] == "mineru_result_invalid"
    assert "chart" in (status["error"] or "").lower()
    assert _download(web, "unsupported.pdf").status_code == 404


def test_attempted_continuation_fails_closed_without_resubmission(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.poll_states = ["failed"]

    upload = _upload(web, source)
    response = _start(web, upload, output_filename="retry.pdf")
    first = _wait_for_terminal(web, response.get_json()["translation_id"])
    assert first["status"] == "error"
    translation_id = response.get_json()["translation_id"]
    assert len(web.http.submitted_files()) == 1

    resumed = web.client.post(f"/api/resume/{translation_id}", json={})
    assert resumed.status_code == 200, resumed.get_json()
    second = _wait_for_terminal(web, translation_id, timeout=60)

    assert second["status"] == "error"
    assert second["error_code"] == "mineru_continuation_unavailable"
    assert len(web.http.submitted_files()) == 1, "the document was submitted again"
    assert _download(web, "retry.pdf").status_code == 404


def test_bilingual_option_still_applies_to_the_translated_book(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)

    upload = _upload(web, source)
    response = _start(web, upload, bilingual=True,
                      output_filename="bilingual (French).pdf")
    status = _wait_for_terminal(web, response.get_json()["translation_id"])

    assert status["status"] == "completed", status
    downloaded = _download(web, "bilingual (French).pdf")
    text = _pdf_text(downloaded.data)
    assert "FR: SAMPLE BOOK" in text
    assert text.count("SAMPLE BOOK") >= 2


def test_non_pdf_workflow_is_unchanged(web):
    text_file = web.tmp_path / "story.txt"
    text_file.write_text("Once upon a time.\n\nA second paragraph.\n", encoding="utf-8")
    upload = _upload(web, text_file)
    assert upload["file_type"] == "txt"

    response = web.client.post("/api/translate", json={
        "file_path": upload["file_path"],
        "file_type": "txt",
        "source_language": "English",
        "target_language": "French",
        "model": "test-model",
        "llm_api_endpoint": "http://localhost:11434/api/generate",
        "llm_provider": "ollama",
        "output_filename": "story (French).txt",
        "prompt_options": {},
    })
    assert response.status_code == 200, response.get_json()
    status = _wait_for_terminal(web, response.get_json()["translation_id"])

    assert status["status"] == "completed", status
    assert web.http.requests == [], "a non-PDF job must never contact MinerU"
    downloaded = _download(web, "story (French).txt")
    assert downloaded.status_code == 200
    assert b"FR: Once upon a time." in downloaded.data
