"""Primary Web/API lifecycle proof for source-preserved table/formula content (#22).

The test enters through the application's own HTTP surface — upload, task
creation, status, artifact download — with a temporary source PDF, a temporary
job database and a temporary output directory. Only the external MinerU HTTP
transport, the external LLM, and time are substituted. Routing, admission, task
storage, recognition-result adaptation, translation orchestration, PDF
generation, validation and the accounting sidecar are real.

Scripted recognition results use the verified MinerU 3.4.4 V2 shapes for
``table`` and ``equation_interline`` blocks (see the loader suite for the
contract citation).
"""

from __future__ import annotations

import io
import json
import time
import unicodedata
import zipfile
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pymupdf
import pytest
from flask import Flask
from PIL import Image

import src.api.auth as api_auth
from src.api.routes import configure_routes
from src.api.translation_state import TranslationStateManager
from src.core.mineru.structure import PRESERVED_LABELS
from src.persistence.checkpoint_manager import CheckpointManager
from src.utils.security import rate_limiter
from tests.test_mineru.online_fixtures import (
    FakeMineruHttp,
    build_source_pdf,
    equation_block,
    image_block,
    install_fake_http,
    install_fake_llm,
    paragraph_block,
    result_zip_bytes,
    table_block,
    title_block,
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

    app = Flask(__name__)
    app.config["TESTING"] = True
    socketio = _FakeSocketIO()

    def start_job(translation_id, config):
        from src.api.handlers import start_translation_job
        start_translation_job(translation_id, config, state_manager, str(output_dir),
                              socketio)

    configure_routes(app, state_manager, str(output_dir), start_job)
    api_auth.register_auth(app)
    rate_limiter._requests.clear()

    client = app.test_client()
    client.environ_base["HTTP_X_API_TOKEN"] = auth_state

    http = FakeMineruHttp()
    install_fake_http(monkeypatch, http)
    llm = install_fake_llm(monkeypatch)
    llm.prefix = LLM_PREFIX

    yield SimpleNamespace(
        app=app, client=client, output_dir=output_dir, uploads_dir=uploads_dir,
        state_manager=state_manager, manager=checkpoint_manager, http=http,
        llm=llm, socketio=socketio, tmp_path=tmp_path,
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


def _translation_payload(upload, *, output_filename="book (French).pdf"):
    return {
        "file_path": upload["file_path"],
        "file_type": "pdf",
        "source_language": "English",
        "target_language": "French",
        "model": "test-model",
        "llm_api_endpoint": "http://localhost:11434/api/generate",
        "llm_provider": "ollama",
        "output_filename": output_filename,
        "prompt_options": {},
        "mineru_authorized": True,
    }


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


def _pdf_text(data: bytes) -> str:
    with pymupdf.open("pdf", data) as document:
        text = " ".join(" ".join(page.get_text() for page in document).split())
    # The serif font applies typographic ligatures (e.g. "fi"); normalise them.
    return unicodedata.normalize("NFKC", text)


def _image_colours(data: bytes) -> set[tuple[int, int, int]]:
    colours = set()
    with pymupdf.open("pdf", data) as document:
        for page in document:
            for item in page.get_image_info(xrefs=True):
                extracted = document.extract_image(item["xref"])
                with Image.open(io.BytesIO(extracted["image"])) as image:
                    image = image.convert("RGB")
                    colours.add(image.getpixel((image.width // 2, image.height // 2)))
    return colours


def _zip_without(data: bytes, member: str) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(data))
    buffer = io.BytesIO()
    with source, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if info.filename != member:
                target.writestr(info, source.read(info.filename))
    return buffer.getvalue()


def _mixed_pages():
    """A leading table, independent captions/notes, a formula and a figure."""
    return [
        [
            table_block(
                "images/table1.png", [60, 80, 940, 300],
                caption="Table 1: Revenue", footnote="Source: annual report",
                html="<table><tr><td>CONFIDENTIAL CELL TEXT</td></tr></table>",
                color=(10, 80, 160)),
            title_block("SAMPLE BOOK", [60, 320, 540, 380]),
            paragraph_block("Intro paragraph.", [60, 400, 540, 460]),
        ],
        [
            paragraph_block("Before the formula.", [60, 80, 540, 140]),
            equation_block("images/eq1.png", [200, 180, 800, 260],
                           math="E = mc^2", color=(200, 40, 40)),
            paragraph_block("After the formula.", [60, 300, 540, 360]),
            image_block("images/fig1.png", [60, 400, 540, 600],
                        caption="A figure caption"),
        ],
    ]


def _wait_for_completion_event(web, translation_id, timeout=30):
    """Wait until the completion payload carrying the accounting is emitted.

    A terminal status poll and the completion socket event are separate
    observations; tests that assert on the payload must wait for it rather than
    infer it from the status. The server publishes the event before the
    terminal status, so this normally returns on the first check.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        for event, data, _ in web.socketio.events:
            if (event == "translation_update" and isinstance(data, dict)
                    and data.get("translation_id") == translation_id
                    and data.get("status") == "completed"
                    and data.get("accounting")):
                return data
        time.sleep(0.01)
    raise AssertionError("completion payload with accounting was not emitted")


def _completed_job(web, *, pages, output_filename="book (French).pdf"):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=len(pages))
    web.http.zip_bytes = result_zip_bytes(page_count=len(pages), pages=pages)
    upload = _upload(web, source)
    response = _start(web, upload, output_filename=output_filename)
    assert response.status_code == 200, response.get_json()
    translation_id = response.get_json()["translation_id"]
    status = _wait_for_terminal(web, translation_id)
    _wait_for_completion_event(web, translation_id)
    return status


def test_scripted_table_and_formula_result_reaches_pdf_download_and_accounting(web):
    pages = _mixed_pages()
    status = _completed_job(web, pages=pages)

    assert status["status"] == "completed", status
    accounting = status["accounting"]
    assert accounting["source_preserved"] == 2
    assert accounting["tables"] == 1
    assert accounting["formulas"] == 1
    assert accounting["images"] == 1
    assert accounting["failed_chunks"] == 0
    assert accounting["unfinished_chunks"] == 0
    assert accounting["body_complete"] is True

    downloaded = _download(web, "book (French).pdf")
    assert downloaded.status_code == 200
    text = _pdf_text(downloaded.data)

    # Independent text stays translatable, including the table caption/note.
    assert "FR: SAMPLE BOOK" in text
    assert "FR: Table 1: Revenue" in text
    assert "FR: Source: annual report" in text
    assert "FR: Before the formula." in text
    assert "FR: After the formula." in text
    assert "FR: A figure caption" in text

    # Preserved blocks are embedded and identified as untranslated.
    assert PRESERVED_LABELS["table"] in text
    assert PRESERVED_LABELS["formula"] in text
    assert _image_colours(downloaded.data) == {
        (10, 80, 160), (20, 120, 40), (200, 40, 40)}
    # No speculative redraw of the table body or the formula LaTeX.
    assert "CONFIDENTIAL CELL TEXT" not in text
    assert "E = mc^2" not in text
    # A leading table stays before the first body text.
    assert text.index(PRESERVED_LABELS["table"]) < text.index("FR: Intro paragraph.")

    document = pymupdf.open("pdf", downloaded.data)
    try:
        assert document.metadata["title"] == "SAMPLE BOOK"
        assert document.metadata["author"] == ""
        assert "untranslated mineru" not in text.lower()
    finally:
        document.close()

    sidecar = Path(web.output_dir) / "book (French).pdf.accounting.json"
    assert sidecar.is_file()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["source_content"]["source_preserved"] == 2
    assert payload["source_content"]["tables"] == 1
    assert payload["source_content"]["formulas"] == 1
    assert payload["translation"]["failed_chunks"] == 0

    # The completion payload carries the same separated counters, so the Web
    # summary never has to manufacture a second source of truth.
    completions = [
        data for event, data, _ in web.socketio.events
        if isinstance(data, dict) and data.get("status") == "completed"
        and event == "translation_update"
    ]
    assert completions, "no completion payload was emitted"
    assert completions[-1]["accounting"]["source_preserved"] == 2
    assert completions[-1]["stats"]["failed_chunks"] == 0


def test_a_missing_supplied_asset_fails_without_publishing_a_book(web):
    pages = [[table_block("images/table1.png", [60, 80, 940, 300],
                          caption="Table 1: Revenue")]]
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    archive = _zip_without(
        result_zip_bytes(page_count=1, pages=pages), "images/table1.png")
    web.http.zip_bytes = archive

    upload = _upload(web, source)
    response = _start(web, upload, output_filename="missing.pdf")
    status = _wait_for_terminal(web, response.get_json()["translation_id"])

    assert status["status"] == "error"
    assert status["error_code"] == "mineru_result_invalid"
    assert "missing image" in (status["error"] or "").lower()
    assert _download(web, "missing.pdf").status_code == 404
    assert not (Path(web.output_dir) / "missing.pdf.accounting.json").exists()


def test_an_inline_formula_fails_with_the_localized_unsupported_content_code(web):
    pages = [[paragraph_block(
        "Energy is conserved.",
        [60, 80, 540, 140],
        spans=[
            {"type": "text", "content": "Energy is conserved: "},
            {"type": "equation_inline", "content": "E = mc^2"},
        ],
    )]]
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1, pages=pages)

    upload = _upload(web, source)
    response = _start(web, upload, output_filename="inline.pdf")
    status = _wait_for_terminal(web, response.get_json()["translation_id"])

    assert status["status"] == "error"
    # A stable code the Web UI resolves in all seven locales; the raw message
    # names the limitation instead of claiming the formula was translated.
    assert status["error_code"] == "mineru_unsupported_content"
    assert "inline formula" in (status["error"] or "").lower()
    assert _download(web, "inline.pdf").status_code == 404
    assert len(web.http.submitted_files()) == 1
