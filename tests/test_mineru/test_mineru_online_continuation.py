"""Safe continuation of an existing online recognition task (issue #21).

Primary seam: the real Web/API task lifecycle (upload, task creation, status,
interrupt, continue, artifact download) with real routing, task-owned temporary
storage, SQLite recovery, recognition-result adaptation, translation
orchestration and PDF generation. Only the external boundaries are substituted:
the MinerU HTTP contract, the external LLM, and time (a fake monotonic clock
injected through the recognition time seam).

Each test asserts externally meaningful behavior: observable task states,
outgoing provider request counts, persisted recovery data, and the downloaded
PDF itself.
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
import src.core.mineru.recognition as recognition_module
import src.core.pdf.translator as pdf_translator_module
from src.api.routes import configure_routes
from src.api.translation_state import TranslationStateManager
from src.persistence.checkpoint_manager import CheckpointManager
from src.utils.security import rate_limiter
from tests.test_mineru.online_fixtures import (
    BATCH_ID,
    UPLOAD_URL,
    FakeClock,
    FakeMineruHttp,
    build_source_pdf,
    install_fake_http,
    install_fake_llm,
    response,
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


class _Harness:
    """One Web application instance over a shared temporary working directory."""

    def __init__(self, tmp_path, http, client_ip_suffix=0):
        self.tmp_path = tmp_path
        self.output_dir = tmp_path / "output"
        self.uploads_dir = self.output_dir / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.manager = CheckpointManager(
            db_path=str(tmp_path / "jobs.db"), uploads_dir=self.uploads_dir)
        self.state_manager = TranslationStateManager(
            checkpoint_manager=self.manager,
            server_session_id=str(int(time.time()) + client_ip_suffix))
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True

        def start_job(translation_id, config):
            from src.api.handlers import start_translation_job
            start_translation_job(
                translation_id, config, self.state_manager, str(self.output_dir),
                _FakeSocketIO())

        configure_routes(self.app, self.state_manager, str(self.output_dir), start_job)
        api_auth.register_auth(self.app)
        rate_limiter._requests.clear()
        self.client = self.app.test_client()
        self.client.environ_base["HTTP_X_API_TOKEN"] = api_auth.API_TOKEN

    def close(self):
        self.manager.close()

    # -- helpers -------------------------------------------------------
    def upload(self, path, filename=None):
        with open(path, "rb") as stream:
            result = self.client.post(
                "/api/upload",
                data={"file": (stream, filename or Path(path).name)},
                content_type="multipart/form-data",
            )
        assert result.status_code == 200, result.get_json()
        return result.get_json()

    def start(self, upload, *, authorized=True, output_filename="book (French).pdf",
              **extra):
        payload = {
            "file_path": upload["file_path"],
            "file_type": "pdf",
            "source_language": "English",
            "target_language": "French",
            "model": "test-model",
            "llm_api_endpoint": "http://localhost:11434/api/generate",
            "llm_provider": "ollama",
            "output_filename": output_filename,
            "prompt_options": {},
            **extra,
        }
        if authorized:
            payload["mineru_authorized"] = True
        return self.client.post("/api/translate", json=payload)

    def wait_for_terminal(self, translation_id, timeout=60):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            result = self.client.get(f"/api/translation/{translation_id}")
            assert result.status_code == 200, result.get_json()
            last = result.get_json()
            if last["status"] in TERMINAL:
                return last
            time.sleep(0.02)
        raise AssertionError(f"job did not finish: {last}")

    def download(self, filename):
        return self.client.get(f"/api/files/{quote(filename)}")

    def start_and_wait(self, upload, **kwargs):
        result = self.start(upload, **kwargs)
        assert result.status_code == 200, result.get_json()
        translation_id = result.get_json()["translation_id"]
        return translation_id, self.wait_for_terminal(translation_id)

    def resume(self, translation_id, body=None, wait=True):
        # The worker releases its execution claim just after publishing the
        # terminal status; wait for it so a rapid Continue is not spuriously
        # refused. Tests that intentionally overlap requests pass wait=False.
        if wait:
            deadline = time.time() + 10
            while (self.state_manager.is_execution_active(translation_id)
                   and time.time() < deadline):
                time.sleep(0.005)
        return self.client.post(f"/api/resume/{translation_id}", json=body or {})

    def recognition_state(self, translation_id):
        return self.manager.load_recognition_state(translation_id)


@pytest.fixture
def fake_clock():
    return FakeClock()


@pytest.fixture
def web(tmp_path, monkeypatch, fake_clock):
    monkeypatch.setenv("MINERU_API_TOKEN", PROVIDER_TOKEN)
    http = FakeMineruHttp()
    install_fake_http(monkeypatch, http)
    llm = install_fake_llm(monkeypatch)
    llm.prefix = LLM_PREFIX

    # Substitute only *time*: the wrapper delegates to the production
    # recognition orchestrator, so durable state, provider request shaping and
    # result validation all stay real.
    real_recognize = recognition_module.recognize_pdf

    def recognize_with_fake_clock(*args, **kwargs):
        kwargs.setdefault("clock", fake_clock)
        kwargs.setdefault("sleep", fake_clock.sleep)
        return real_recognize(*args, **kwargs)

    monkeypatch.setattr(
        pdf_translator_module, "recognize_pdf", recognize_with_fake_clock)

    harness = _Harness(tmp_path, http)
    harness.http = http
    harness.llm = llm
    harness.clock = fake_clock
    try:
        yield harness
    finally:
        harness.close()


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


def _submissions(http):
    return http.submitted_files()


def _storage_uploads(http):
    return http.calls(lambda item: item["method"] == "PUT")


def _result_downloads(http):
    return [
        item for item in http.storage_calls()
        if item["method"] == "GET" and item["url"].startswith("https://")
        and "result" in item["url"]
    ]


# ---------------------------------------------------------------------------
# Deadline: pause locally, then continue the same remote task
# ---------------------------------------------------------------------------


def test_a_paused_recognition_continues_the_same_remote_task_without_resubmission(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=2)
    web.http.zip_bytes = result_zip_bytes(page_count=2)
    # The first attempt never observes completion: only the local budget ends it.
    web.http.poll_states = ["running"]

    upload = web.upload(source)
    translation_id, first = web.start_and_wait(upload)

    # Truthful local pause: interrupted, not completed, not a provider failure.
    assert first["status"] == "interrupted", first
    assert first["error_code"] == "mineru_recognition_timeout"
    assert first["error"] is None or "cancel" not in first["error"].lower()
    assert first["accounting"] is None
    assert web.download("book (French).pdf").status_code == 404
    assert web.llm.calls == 0, "no translation may start after recognition stops"
    assert len(_submissions(web.http)) == 1
    assert len(_storage_uploads(web.http)) == 1
    assert _result_downloads(web.http) == []

    state = web.recognition_state(translation_id)
    assert state.phase == "timed_out"
    assert state.batch_id == BATCH_ID
    assert state.attempts == 1, "a pause is not a new submission attempt"
    assert state.continuations == 0
    assert state.elapsed_seconds >= 300
    assert (web.uploads_dir / translation_id / "recognition" /
            "recognition-state.json").is_file()

    # Continue: the same task, the same remote identifier, a fresh local budget.
    web.http.poll_states = ["running", "done"]
    resumed = web.resume(translation_id)
    assert resumed.status_code == 200, resumed.get_json()
    second = web.wait_for_terminal(translation_id)

    assert second["status"] == "completed", second
    assert len(_submissions(web.http)) == 1, "the PDF was submitted again"
    assert len(_storage_uploads(web.http)) == 1, "the PDF was uploaded again"
    assert len(_result_downloads(web.http)) == 1

    downloaded = web.download("book (French).pdf")
    assert downloaded.status_code == 200
    text = _pdf_text(downloaded.data)
    assert "FR: SAMPLE BOOK" in text
    assert web.llm.calls > 0
    assert _sidecar_path(web.output_dir, "book (French).pdf").is_file()

    # Completed work is not left behind as an unfinished task.
    resumable = web.client.get("/api/resumable").get_json()["resumable_jobs"]
    assert all(job["translation_id"] != translation_id for job in resumable)
    history = web.client.get("/api/history").get_json()["history"]
    assert any(item["translation_id"] == translation_id
               and item["status"] == "completed" for item in history)


def test_a_continued_attempt_grants_a_fresh_budget_without_faking_attempts(
        web, fake_clock):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    web.http.poll_states = ["running"]

    upload = web.upload(source)
    translation_id = web.start(upload).get_json()["translation_id"]
    first = web.wait_for_terminal(translation_id)
    assert first["status"] == "interrupted"
    first_state = web.recognition_state(translation_id)
    assert first_state.attempts == 1

    # Continue but never let the remote task finish: the second budget must run
    # out on its own, from the continuation's start, not inherit the first
    # attempt's already-elapsed time.
    started_clock = fake_clock.now
    web.http.poll_states = ["running"]
    assert web.resume(translation_id).status_code == 200
    second = web.wait_for_terminal(translation_id)

    assert second["status"] == "interrupted"
    assert second["error_code"] == "mineru_recognition_timeout"
    state = web.recognition_state(translation_id)
    assert state.phase == "timed_out"
    assert state.attempts == 1, "a continuation must not be counted as a submission"
    assert state.continuations == 1
    # The second execution consumed its own 300 seconds, so the cumulative
    # elapsed budget is at least one budget past the continuation's start.
    assert fake_clock.now >= started_clock + 300
    assert state.elapsed_seconds >= 600
    assert len(_submissions(web.http)) == 1
    assert len(_storage_uploads(web.http)) == 1


# ---------------------------------------------------------------------------
# Cooperative local stop
# ---------------------------------------------------------------------------


def test_a_local_stop_keeps_the_known_task_and_never_starts_translation(web):
    import threading

    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    web.http.poll_states = ["running"]

    poll_seen = threading.Event()
    release = threading.Event()
    original_sleep = web.clock.sleep

    def gated_sleep(seconds):
        # Time still advances exactly as in production; the gate only holds the
        # worker long enough for the test to deliver a cooperative stop.
        poll_seen.set()
        original_sleep(seconds)
        if not release.is_set():
            release.wait(timeout=10)

    web.clock.sleep = gated_sleep

    upload = web.upload(source)
    response = web.start(upload)
    translation_id = response.get_json()["translation_id"]

    assert poll_seen.wait(timeout=30), "recognition never reached polling"
    interrupted = web.client.post(f"/api/translation/{translation_id}/interrupt")
    assert interrupted.status_code == 200, interrupted.get_json()
    release.set()

    stopped = web.wait_for_terminal(translation_id)
    assert stopped["status"] == "interrupted", stopped
    assert web.llm.calls == 0, "translation started after the local stop"
    assert len(_submissions(web.http)) == 1

    state = web.recognition_state(translation_id)
    assert state is not None
    assert state.phase == "interrupted_local"
    assert state.batch_id == BATCH_ID
    message = (state.error_message or "").lower()
    assert "may continue" in message
    assert "not remote cancellation" in message
    # The UI must not claim remote cancellation/deletion/avoided usage.
    logs = " ".join(str(item) for item in (stopped.get("logs") or [])).lower()
    assert "cancelled" not in logs and "deleted" not in logs

    # Continue the same task; the stop did not discard it.
    web.clock.sleep = original_sleep
    web.http.poll_states = ["done"]
    assert web.resume(translation_id).status_code == 200
    finished = web.wait_for_terminal(translation_id)
    assert finished["status"] == "completed", finished
    assert len(_submissions(web.http)) == 1
    assert len(_storage_uploads(web.http)) == 1
    assert "FR: SAMPLE BOOK" in _pdf_text(
        web.download("book (French).pdf").data)


# ---------------------------------------------------------------------------
# Repeated / concurrent Continue requests
# ---------------------------------------------------------------------------


def test_repeated_continue_requests_leave_one_active_execution(web):
    import threading

    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    web.http.poll_states = ["running"]

    upload = web.upload(source)
    translation_id, first = web.start_and_wait(upload)
    assert first["status"] == "interrupted"

    # Hold the continuation inside recognition polling so a second Continue
    # genuinely overlaps the first execution.
    continuing = threading.Event()
    release = threading.Event()
    original_sleep = web.clock.sleep

    def gated_sleep(seconds):
        continuing.set()
        original_sleep(seconds)
        if not release.is_set():
            release.wait(timeout=10)

    web.clock.sleep = gated_sleep
    web.http.poll_states = ["running", "done"]
    # The first attempt already consumed the fake provider's poll script;
    # restart it so the continuation observes one pending state before "done".
    web.http.poll_count = 0

    try:
        assert web.resume(translation_id).status_code == 200
        assert continuing.wait(timeout=30), "continuation never started"
        assert web.state_manager.is_execution_active(translation_id) is True

        duplicate = web.resume(translation_id, wait=False)
        assert duplicate.status_code == 409, duplicate.get_json()
        assert duplicate.get_json()["active_translations"][0]["id"] == translation_id

        # The job owner itself refuses a second claim while the worker owns it.
        assert web.state_manager.claim_execution(translation_id) is False
    finally:
        release.set()
        web.clock.sleep = original_sleep

    finished = web.wait_for_terminal(translation_id)
    assert finished["status"] == "completed", finished
    assert len(_submissions(web.http)) == 1, "a duplicate Continue submitted again"
    assert len(_storage_uploads(web.http)) == 1
    deadline = time.time() + 10
    while web.state_manager.is_execution_active(translation_id) and time.time() < deadline:
        time.sleep(0.01)
    assert web.state_manager.is_execution_active(translation_id) is False


def test_the_job_owner_allows_exactly_one_execution_claim():
    import threading

    from src.api.translation_state import TranslationStateManager

    manager = TranslationStateManager(
        checkpoint_manager=SimpleNamespace(), server_session_id="1")
    manager.create_translation("trans_1", {})
    assert manager.is_execution_active("trans_1") is True
    manager.release_execution("trans_1")

    barrier = threading.Barrier(8)
    results = []

    def attempt():
        barrier.wait()
        results.append(manager.claim_execution("trans_1"))

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(True) == 1
    manager.release_execution("trans_1")
    assert manager.claim_execution("trans_1") is True


# ---------------------------------------------------------------------------
# Source/result identity and paragraph mapping must authorize replay
# ---------------------------------------------------------------------------


class _IdentitySource:
    def __init__(self, content):
        self._content = content
        self.paragraphs = tuple(content.paragraphs_text)
        self.styles = tuple(content.paragraphs_style)
        self.formats = tuple(content.paragraphs_format)
        self.images_by_paragraph = {}
        self.provenance = ()
        self.counts = {"paragraphs": len(content.paragraphs_text), "images": 0,
                       "blocks_seen": len(content.paragraphs_text),
                       "blocks_accounted": len(content.paragraphs_text),
                       "excluded": 0, "findings": 0}
        self.review_required = False

    def to_plain_content(self):
        return self._content


def _pdf_content(texts):
    from src.core.pdf.content import ParagraphFormat, PdfPlainContent

    return PdfPlainContent(
        paragraphs_text=list(texts),
        paragraphs_style=["normal"] * len(texts),
        paragraphs_format=[ParagraphFormat() for _ in texts],
        page_size=(600, 800),
        title="",
        author="",
        page_count=2,
    )


def _pdf_outcome(content, *, source_sha256="a" * 64, cache_sha256="c" * 64):
    return SimpleNamespace(
        admitted=SimpleNamespace(
            sha256=source_sha256, size_bytes=4321, page_count=2,
            file_name="source.pdf"),
        source=_IdentitySource(content),
        cache=SimpleNamespace(backend="hybrid", engine_version="2.5.4",
                              fingerprints={"layout.json": "f" * 64}),
        batch_id=BATCH_ID,
        result_zip_sha256="b" * 64,
        result_cache_sha256=cache_sha256,
        cache_sha256=cache_sha256,
        page_count=2,
        elapsed_seconds=12.5,
        retries=0,
        remote_states=("done",),
        reused=True,
        continued=False,
    )


def _write_pdf_checkpoint(manager, *, translation_id, file_href, paragraphs,
                          metadata_extra):
    from src.core.epub.xhtml_translation_state import XHTMLTranslationState

    metadata = {"plain_text_mode": True, "paragraph_count": len(paragraphs)}
    metadata.update(metadata_extra)
    state = XHTMLTranslationState(
        file_path=file_href,
        translation_id=translation_id,
        file_href=file_href,
        source_language="English",
        target_language="French",
        model_name="test-model",
        max_tokens_per_chunk=450,
        max_retries=1,
        chunks=[{
            "local_tag_map": {}, "global_indices": [],
            "indices": [0], "text": paragraphs[0], "partial": False,
        }],
        global_tag_map={},
        placeholder_format=("", ""),
        translated_chunks=[f"T:{paragraphs[0]}"],
        current_chunk_index=1,
        original_body_html="",
        doc_metadata=metadata,
        stats={},
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    assert manager.save_xhtml_partial_state(translation_id, file_href, state)


@pytest.fixture
def pdf_job(tmp_path):
    """A real task-owned checkpoint store plus a temporary source PDF."""
    manager = CheckpointManager(
        db_path=str(tmp_path / "jobs.db"), uploads_dir=tmp_path / "uploads")
    source = build_source_pdf(tmp_path / "source.pdf", pages=2)
    try:
        yield manager, source, "trans_identity"
    finally:
        manager.close()


async def _run_pdf_translation(manager, source, *, outcome, translation_id,
                               seen, log_callback=None):
    translator_module = pdf_translator_module

    async def pipeline(*args, paragraphs, **kwargs):
        from src.core.epub.translation_metrics import TranslationMetrics

        seen["paragraphs"] = list(paragraphs)
        seen["resume_segments"] = kwargs.get("resume_segments")
        seen["resume_translated"] = kwargs.get("resume_translated")
        return [f"T:{paragraph}" for paragraph in paragraphs], TranslationMetrics(), False

    from unittest.mock import patch

    output = source.parent / "out.pdf"
    with patch.object(translator_module, "recognize_pdf", return_value=outcome), \
            patch.object(translator_module, "translate_paragraphs_plain", pipeline):
        return await translator_module.translate_pdf_file(
            input_filepath=str(source),
            output_filepath=str(output),
            source_language="English",
            target_language="French",
            model_name="test-model",
            llm_client=object(),
            checkpoint_manager=manager,
            translation_id=translation_id,
            mineru_authorized=True,
            log_callback=log_callback,
        )


@pytest.mark.asyncio
async def test_matching_source_result_and_mapping_authorize_replay(pdf_job):
    from src.core.common.plain_text_checkpoint import paragraph_mapping_sha256

    manager, source, translation_id = pdf_job
    texts = ["Chapter One", "A body paragraph."]
    outcome = _pdf_outcome(_pdf_content(texts))
    _write_pdf_checkpoint(
        manager, translation_id=translation_id, file_href="source.pdf",
        paragraphs=texts,
        metadata_extra={
            "source_sha256": outcome.admitted.sha256,
            "result_cache_sha256": outcome.result_cache_sha256,
            "paragraph_mapping_sha256": paragraph_mapping_sha256(texts),
        })
    seen = {}
    logs = []
    result = await _run_pdf_translation(
        manager, source, outcome=outcome, translation_id=translation_id,
        seen=seen, log_callback=lambda key, message: logs.append(key))

    assert result["success"] is True
    assert seen["resume_segments"] is not None
    assert seen["resume_translated"] == ["T:Chapter One"]
    assert not (manager.uploads_dir / translation_id / "incompatible_states").exists()


@pytest.mark.asyncio
async def test_a_legacy_native_extraction_checkpoint_is_preserved_not_replayed(pdf_job):
    manager, source, translation_id = pdf_job
    texts = ["Chapter One", "A body paragraph."]
    outcome = _pdf_outcome(_pdf_content(texts))
    # Legacy native-extraction PDF work: same paragraph count, no recognition
    # identity. Equal counts alone must not authorize replay.
    _write_pdf_checkpoint(
        manager, translation_id=translation_id, file_href="source.pdf",
        paragraphs=texts, metadata_extra={})
    state_path = manager._xhtml_state_path(translation_id, "source.pdf")
    original = state_path.read_text(encoding="utf-8")

    seen = {}
    logs = []
    result = await _run_pdf_translation(
        manager, source, outcome=outcome, translation_id=translation_id,
        seen=seen, log_callback=lambda key, message: logs.append(key))

    assert result["success"] is True
    assert seen["resume_segments"] is None
    assert "pdf_checkpoint_incompatible" in logs
    preserved = (manager.uploads_dir / translation_id /
                 "incompatible_states" / state_path.name)
    assert preserved.is_file()
    assert preserved.read_text(encoding="utf-8") == original, (
        "the incompatible checkpoint was overwritten instead of preserved")


@pytest.mark.asyncio
async def test_a_changed_paragraph_mapping_is_preserved_not_replayed(pdf_job):
    from src.core.common.plain_text_checkpoint import paragraph_mapping_sha256

    manager, source, translation_id = pdf_job
    texts = ["Chapter One", "A body paragraph."]
    outcome = _pdf_outcome(_pdf_content(texts))
    # Same count, different paragraphs: enough to catch a silent mis-mapping.
    _write_pdf_checkpoint(
        manager, translation_id=translation_id, file_href="source.pdf",
        paragraphs=texts,
        metadata_extra={
            "source_sha256": outcome.admitted.sha256,
            "result_cache_sha256": outcome.result_cache_sha256,
            "paragraph_mapping_sha256": paragraph_mapping_sha256(
                ["Chapter One", "A completely different paragraph."]),
        })
    seen = {}
    logs = []
    result = await _run_pdf_translation(
        manager, source, outcome=outcome, translation_id=translation_id,
        seen=seen, log_callback=lambda key, message: logs.append(key))

    assert result["success"] is True
    assert seen["resume_segments"] is None
    assert "pdf_checkpoint_mapping_mismatch" in logs
    assert (manager.uploads_dir / translation_id / "incompatible_states").is_dir()


@pytest.mark.asyncio
async def test_a_changed_source_identity_is_preserved_not_replayed(pdf_job):
    from src.core.common.plain_text_checkpoint import paragraph_mapping_sha256

    manager, source, translation_id = pdf_job
    texts = ["Chapter One", "A body paragraph."]
    outcome = _pdf_outcome(_pdf_content(texts))
    _write_pdf_checkpoint(
        manager, translation_id=translation_id, file_href="source.pdf",
        paragraphs=texts,
        metadata_extra={
            "source_sha256": "d" * 64,
            "result_cache_sha256": outcome.result_cache_sha256,
            "paragraph_mapping_sha256": paragraph_mapping_sha256(texts),
        })
    seen = {}
    logs = []
    await _run_pdf_translation(
        manager, source, outcome=outcome, translation_id=translation_id,
        seen=seen, log_callback=lambda key, message: logs.append(key))

    assert seen["resume_segments"] is None
    assert "pdf_checkpoint_source_mismatch" in logs
    assert (manager.uploads_dir / translation_id / "incompatible_states").is_dir()


# ---------------------------------------------------------------------------
# Unusable result access and terminal provider failures
# ---------------------------------------------------------------------------


def _multi_chunk_result_zip(paragraphs=12, words=80):
    """A one-page result whose text needs several translation chunks.

    That is what makes a cooperative stop land between chunks, leaving a real
    partial translation checkpoint behind.
    """
    from tests.test_mineru.online_fixtures import paragraph_block, title_block

    blocks = [title_block("SAMPLE BOOK", [60, 20, 940, 60])]
    for index in range(paragraphs):
        blocks.append(paragraph_block(
            f"Paragraph {index}: " + " ".join(["word"] * words),
            [60, 80 + (index % 10) * 60, 940, 120 + (index % 10) * 60]))
    return result_zip_bytes(page_count=1, pages=[blocks])


def _run_until_validated_then_stop(web, translation_id):
    """Start a job, stop it once recognition has validated its result."""
    import asyncio
    import threading

    started = threading.Event()
    release = threading.Event()
    original_generate = web.llm.generate

    async def blocking_generate(prompt, timeout=300, system_prompt=None):
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.005)
        return await original_generate(prompt, timeout, system_prompt)

    web.llm.generate = blocking_generate
    assert started.wait(timeout=40), "translation never started"
    state = web.recognition_state(translation_id)
    assert state.phase == "validated"
    assert web.client.post(
        f"/api/translation/{translation_id}/interrupt").status_code == 200
    release.set()
    return web.wait_for_terminal(translation_id)


def test_continue_reports_an_unusable_saved_result_without_resubmitting(web):
    import shutil

    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = _multi_chunk_result_zip()

    upload = web.upload(source)
    translation_id = web.start(upload).get_json()["translation_id"]
    first = _run_until_validated_then_stop(web, translation_id)
    assert first["status"] == "interrupted", first
    provider_requests_before = len(web.http.requests)

    # The validated result is no longer on disk (expired/removed working data).
    shutil.rmtree(web.manager.recognition_dir(translation_id) / "result")

    assert web.resume(translation_id).status_code == 200
    second = web.wait_for_terminal(translation_id)

    assert second["status"] == "error", second
    assert second["error_code"] == "mineru_continuation_result_unavailable"
    assert len(web.http.requests) == provider_requests_before, (
        "an unusable saved result must not trigger a resubmission")
    # The rest of the task-owned recovery data is retained.
    assert web.recognition_state(translation_id).phase == "validated"
    states = list((web.uploads_dir / translation_id / "xhtml_states").glob("*.json"))
    assert states, "the incomplete translation checkpoint was discarded"


def test_a_terminal_provider_failure_is_distinct_from_the_local_deadline(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    web.http.poll_states = ["failed"]

    upload = web.upload(source)
    translation_id, first = web.start_and_wait(upload)

    assert first["status"] == "error", first
    assert first["error_code"] == "mineru_recognition_failed"
    state = web.recognition_state(translation_id)
    assert state.phase == "failed"
    assert state.remote_state == "failed"

    requests_before = len(web.http.requests)
    assert web.resume(translation_id).status_code == 200
    second = web.wait_for_terminal(translation_id)

    assert second["status"] == "error"
    assert second["error_code"] == "mineru_continuation_unavailable"
    assert len(web.http.requests) == requests_before
    assert len(_submissions(web.http)) == 1


def test_a_continuation_without_a_configured_token_makes_no_provider_request(
        web, monkeypatch):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    web.http.poll_states = ["running"]

    upload = web.upload(source)
    translation_id, first = web.start_and_wait(upload)
    assert first["status"] == "interrupted"
    requests_before = len(web.http.requests)

    monkeypatch.setenv("MINERU_API_TOKEN", "")
    assert web.resume(translation_id).status_code == 200
    second = web.wait_for_terminal(translation_id)

    assert second["status"] == "error"
    assert second["error_code"] == "mineru_token_missing"
    assert len(web.http.requests) == requests_before


# ---------------------------------------------------------------------------
# Recovery data ownership
# ---------------------------------------------------------------------------


def test_paused_jobs_keep_recovery_data_and_finished_jobs_are_not_unfinished(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    web.http.poll_states = ["running"]

    upload = web.upload(source)
    translation_id, first = web.start_and_wait(upload)
    assert first["status"] == "interrupted"

    job_dir = web.uploads_dir / translation_id
    assert (job_dir / "recognition" / "recognition-state.json").is_file()
    assert any(path.suffix == ".pdf" for path in job_dir.iterdir())
    resumable = web.client.get("/api/resumable").get_json()["resumable_jobs"]
    assert [job["translation_id"] for job in resumable] == [translation_id]
    assert resumable[0]["file_type"] == "pdf"

    web.http.poll_states = ["done"]
    assert web.resume(translation_id).status_code == 200
    finished = web.wait_for_terminal(translation_id)
    assert finished["status"] == "completed"

    deadline = time.time() + 10
    while job_dir.exists() and time.time() < deadline:
        time.sleep(0.02)
    assert not job_dir.exists(), (
        "validated, non-resumable success must not keep a fake unfinished task")
    resumable = web.client.get("/api/resumable").get_json()["resumable_jobs"]
    assert all(job["translation_id"] != translation_id for job in resumable)
    history = web.client.get("/api/history").get_json()["history"]
    assert any(item["translation_id"] == translation_id
               and item["status"] == "completed" for item in history)

    # Restart: reopening the real store must not turn the finished job back
    # into unfinished work.
    web.close()
    restarted = _Harness(web.tmp_path, web.http, client_ip_suffix=77)
    try:
        restarted.state_manager.checkpoint_manager.reset_running_jobs_on_startup()
        resumable = restarted.client.get("/api/resumable").get_json()["resumable_jobs"]
        assert all(job["translation_id"] != translation_id for job in resumable)
        history = restarted.client.get("/api/history").get_json()["history"]
        assert any(item["translation_id"] == translation_id
                   and item["status"] == "completed" for item in history)
    finally:
        restarted.close()


def test_continue_reports_a_changed_source_and_preserves_saved_work(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = _multi_chunk_result_zip()

    upload = web.upload(source)
    translation_id = web.start(upload).get_json()["translation_id"]
    first = _run_until_validated_then_stop(web, translation_id)
    assert first["status"] == "interrupted", first

    # The task's saved, authorized source is replaced by different bytes.
    job = web.client.get(f"/api/translation/{translation_id}").get_json()
    preserved = Path(job["config"]["preserved_input_path"])
    build_source_pdf(preserved, pages=3, text_layer=False)
    provider_requests_before = len(web.http.requests)
    saved_states = sorted(
        (web.uploads_dir / translation_id / "xhtml_states").glob("*.json"))
    assert saved_states

    response = web.resume(translation_id)
    assert response.status_code == 200, response.get_json()
    second = web.wait_for_terminal(translation_id)

    assert second["status"] == "error", second
    assert second["error_code"] == "mineru_continuation_source_changed"
    assert len(web.http.requests) == provider_requests_before, (
        "a changed source must never trigger a provider request")
    # The incompatible translated segments and recognition record are retained.
    assert sorted(
        (web.uploads_dir / translation_id / "xhtml_states").glob("*.json")
    ) == saved_states
    assert web.recognition_state(translation_id).phase == "validated"


def test_a_transient_poll_error_is_retried_within_the_continuation_budget(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    web.http.poll_states = ["running"]

    upload = web.upload(source)
    translation_id, first = web.start_and_wait(upload)
    assert first["status"] == "interrupted"

    from tests.test_mineru.online_fixtures import API_BASE, RESULT_URL

    attempts = {"count": 0}

    def status(index):
        attempts["count"] += 1
        url = f"{API_BASE}/extract-results/batch/{BATCH_ID}"
        if attempts["count"] == 1:
            return response(url, b"busy", status=503)
        return response(url, json.dumps({
            "code": 0,
            "data": {"extract_result": [{
                "file_name": web.http.uploaded_name,
                "state": "done",
                "full_zip_url": RESULT_URL,
            }]},
        }).encode("utf-8"))

    web.http.status_override = status
    web.http.poll_count = 0
    response_ = web.resume(translation_id)
    assert response_.status_code == 200, response_.get_json()
    assert response_.get_json()["continues_recognition"] is True
    finished = web.wait_for_terminal(translation_id)

    assert finished["status"] == "completed", finished
    assert attempts["count"] == 2, "the read-only poll was not retried"
    assert len(_submissions(web.http)) == 1
    assert len(_storage_uploads(web.http)) == 1
    assert len(_result_downloads(web.http)) == 1


def test_a_lost_recognition_record_is_never_replaced_by_a_new_submission(web):
    import shutil

    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    web.http.poll_states = ["running"]

    upload = web.upload(source)
    translation_id, first = web.start_and_wait(upload)
    assert first["status"] == "interrupted"

    shutil.rmtree(web.manager.recognition_dir(translation_id))
    assert web.recognition_state(translation_id) is None
    requests_before = len(web.http.requests)

    assert web.resume(translation_id).status_code == 200
    second = web.wait_for_terminal(translation_id)

    assert second["status"] == "error", second
    assert second["error_code"] == "mineru_continuation_unavailable"
    assert "new task" in (second["error"] or "").lower()
    assert len(web.http.requests) == requests_before, (
        "a lost recognition record must never be replaced by a new submission")
    assert len(_submissions(web.http)) == 1


# ---------------------------------------------------------------------------
# Ambiguous submission
# ---------------------------------------------------------------------------


def test_an_ambiguous_submission_stays_unknown_across_continue(web):
    import requests

    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)

    def fail(**_kwargs):
        raise requests.ConnectionError("connection reset after the request")

    web.http.submit_override = lambda: fail()

    upload = web.upload(source)
    translation_id, first = web.start_and_wait(upload)
    assert first["status"] == "error"
    assert first["error_code"] == "mineru_submission_unknown"
    assert len(_submissions(web.http)) == 1
    state = web.recognition_state(translation_id)
    assert state.phase == "submission_unknown"
    assert state.attempts == 1

    web.http.submit_override = None
    requests_before = len(web.http.requests)
    assert web.resume(translation_id).status_code == 200
    second = web.wait_for_terminal(translation_id)

    assert second["status"] == "error"
    assert second["error_code"] == "mineru_continuation_unavailable"
    assert len(_submissions(web.http)) == 1, "the document was submitted again"
    assert len(web.http.requests) == requests_before, (
        "an uncertain submission must not trigger any provider request")
    # The state stays explicitly unknown: it is never rewritten as a known task.
    state = web.recognition_state(translation_id)
    assert state.phase == "submission_unknown"
    assert state.batch_id is None


# ---------------------------------------------------------------------------
# Incomplete upload whose one-time destination cannot be recovered
# ---------------------------------------------------------------------------


def test_an_incomplete_upload_is_reported_as_not_automatically_continuable(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    web.http.upload_override = lambda: response(UPLOAD_URL, status=500)

    upload = web.upload(source)
    translation_id, first = web.start_and_wait(upload)
    assert first["status"] == "error"
    assert first["error_code"] == "mineru_upload_failed"

    state = web.recognition_state(translation_id)
    assert state.phase == "upload_failed"
    assert state.batch_id == BATCH_ID
    payload = (web.uploads_dir / translation_id / "recognition" /
               "recognition-state.json").read_text(encoding="utf-8")
    assert "https://" not in payload, "a signed URL was persisted"
    assert "Signature" not in payload
    assert "upload_url" not in json.loads(payload)

    # The transient one-time upload destination is not retained, so there is no
    # verified way to recover the upload: report the limitation, never resubmit.
    web.http.upload_override = None
    requests_before = len(web.http.requests)
    assert web.resume(translation_id).status_code == 200
    second = web.wait_for_terminal(translation_id)

    assert second["status"] == "error"
    assert second["error_code"] == "mineru_continuation_upload_unrecoverable"
    assert len(_submissions(web.http)) == 1
    assert len(web.http.requests) == requests_before
    assert web.recognition_state(translation_id).phase == "upload_failed"


# ---------------------------------------------------------------------------
# Known validated result reuse (no provider request at all)
# ---------------------------------------------------------------------------


def test_continue_reuses_a_validated_result_instead_of_recognizing_again(web):
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = _multi_chunk_result_zip()

    upload = web.upload(source)
    translation_id = web.start(upload).get_json()["translation_id"]

    # Stop between translation chunks: recognition already validated its
    # result, so the resume must reuse it without any provider request.
    first = _run_until_validated_then_stop(web, translation_id)
    assert first["status"] == "interrupted", first
    provider_requests_before = len(web.http.requests)
    assert web.recognition_state(translation_id).phase == "validated"

    assert web.resume(translation_id).status_code == 200
    second = web.wait_for_terminal(translation_id)

    assert second["status"] in {"completed", "partial"}, second
    assert len(web.http.requests) == provider_requests_before, (
        "a validated result must be reused without contacting MinerU")
    assert len(_submissions(web.http)) == 1

    sidecar = _sidecar_path(web.output_dir, "book (French).pdf")
    accounting = json.loads(sidecar.read_text(encoding="utf-8"))
    assert accounting["recognition"]["reused_validated_result"] is True
    assert accounting["recognition"]["batch_id"] == BATCH_ID


# ---------------------------------------------------------------------------
# Restart: reopen the real temporary job store after process-state loss
# ---------------------------------------------------------------------------


def test_restart_restores_safe_continuation_from_the_real_job_store(
        web, tmp_path, monkeypatch, fake_clock):
    source = build_source_pdf(tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    web.http.poll_states = ["running"]

    upload = web.upload(source)
    translation_id, first = web.start_and_wait(upload)
    assert first["status"] == "interrupted"

    # Simulate process-state loss: only the files and the SQLite database
    # survive. A new state manager restores no in-memory job.
    web.close()
    restarted = _Harness(tmp_path, web.http, client_ip_suffix=99)
    restarted.llm = web.llm
    restarted.clock = fake_clock
    restarted.state_manager.checkpoint_manager.reset_running_jobs_on_startup()

    try:
        resumable = restarted.client.get("/api/resumable").get_json()["resumable_jobs"]
        assert any(job["translation_id"] == translation_id for job in resumable)

        restored = restarted.manager.get_job(translation_id)
        assert restored is not None
        # The existing Continue API reloaded the saved source identity and the
        # task's own authorization instead of registering a replacement task.
        assert restored["config"]["mineru_authorized"] is True
        assert restored["config"]["file_type"] == "pdf"
        assert Path(restored["config"]["file_path"]).is_file()
        assert Path(restored["config"]["preserved_input_path"]).is_file()

        web.http.poll_states = ["done"]
        resumed = restarted.resume(translation_id)
        assert resumed.status_code == 200
        assert resumed.get_json()["translation_id"] == translation_id
        assert resumed.get_json()["continues_recognition"] is True
        finished = restarted.wait_for_terminal(translation_id)

        assert finished["status"] == "completed", finished
        assert len(_submissions(web.http)) == 1
        assert len(_storage_uploads(web.http)) == 1
        downloaded = restarted.download("book (French).pdf")
        assert downloaded.status_code == 200
        assert "FR: SAMPLE BOOK" in _pdf_text(downloaded.data)
        # A continuation after restart keeps the original remote task identity.
        history = restarted.client.get("/api/history").get_json()["history"]
        assert any(item["translation_id"] == translation_id for item in history)
    finally:
        restarted.close()


def test_missing_preserved_source_data_is_an_actionable_error(tmp_path, monkeypatch,
                                                             fake_clock):
    monkeypatch.setenv("MINERU_API_TOKEN", PROVIDER_TOKEN)
    http = FakeMineruHttp(zip_bytes=result_zip_bytes(page_count=1))
    install_fake_http(monkeypatch, http)
    llm = install_fake_llm(monkeypatch)
    llm.prefix = LLM_PREFIX

    real_recognize = recognition_module.recognize_pdf

    def recognize_with_fake_clock(*args, **kwargs):
        kwargs.setdefault("clock", fake_clock)
        kwargs.setdefault("sleep", fake_clock.sleep)
        return real_recognize(*args, **kwargs)

    monkeypatch.setattr(
        pdf_translator_module, "recognize_pdf", recognize_with_fake_clock)

    harness = _Harness(tmp_path, http)
    try:
        source = build_source_pdf(tmp_path / "source.pdf", pages=1)
        http.poll_states = ["running"]
        upload = harness.upload(source)
        translation_id, first = harness.start_and_wait(upload)
        assert first["status"] == "interrupted"

        job_dir = harness.uploads_dir / translation_id
        for path in job_dir.iterdir():
            if path.is_file():
                path.unlink()
        assert not any(p.is_file() for p in job_dir.iterdir())

        response = harness.resume(translation_id)
        assert response.status_code == 404, response.get_json()
        payload = response.get_json()
        assert "preserved" in (payload.get("error") or "").lower()
        assert len(_submissions(http)) == 1
    finally:
        harness.close()
