"""Primary API lifecycle proof for honest completion and task-owned cleanup (#23).

These tests enter through the application's own HTTP surface — upload, task
creation, status, interrupt, continuation, deletion, history and report download
— with temporary source PDFs, a temporary SQLite job store and temporary output
directories. Only the external boundaries are substituted: MinerU HTTP, the
external LLM, and (for the local-stop case) the recognition poll interval.

Routing, admission, task storage, recognition-result adaptation, translation
orchestration, PDF generation/validation and the durable accounting sidecar are
real. Reopening persistence after a run proves that completed history and the
durable report survive working-cache pruning, and that partial/failed recovery
data stays available.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from src.api.translation_state import TranslationStateManager
from src.core.mineru.errors import MineruCompletionInvalid
from src.core.pdf.accounting import PdfCompletionAssessment
from src.persistence.checkpoint_manager import CheckpointManager
from tests.test_mineru.lifecycle_harness import (
    FailingLlmClient,
    LifecycleHarness,
    age_job,
    completed_events,
)
from tests.test_mineru.online_fixtures import (
    FakeMineruHttp,
    build_source_pdf,
    image_block,
    install_fake_http,
    install_fake_llm,
    paragraph_block,
    result_zip_bytes,
    title_block,
)


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "test-mineru-token")
    http = FakeMineruHttp()
    install_fake_http(monkeypatch, http)
    llm = FailingLlmClient()
    install_fake_llm(monkeypatch, llm)
    harness = LifecycleHarness(tmp_path)
    harness.http = http
    harness.llm = llm
    yield harness
    harness.close()


def _pages():
    return [
        [
            title_block("SAMPLE BOOK", [60, 80, 940, 140]),
            paragraph_block("Intro paragraph.", [60, 160, 540, 220]),
            image_block("images/fig1.png", [60, 240, 540, 500],
                        caption="Figure 1: a caption", footnote="Figure credit."),
        ],
        [],
        [
            paragraph_block("The final paragraph.", [60, 80, 540, 140]),
            {"type": "page_header", "text": "Running Header",
             "bbox": [600, 40, 900, 60]},
        ],
    ]


def _sidecar(web, filename="book (French).pdf") -> Path:
    return Path(web.output_dir) / (filename + ".accounting.json")


def _wait_for_path_gone(path: Path, timeout: float = 20) -> None:
    deadline = time.time() + timeout
    while path.exists() and time.time() < deadline:
        time.sleep(0.02)
    assert not path.exists(), f"working data was not pruned: {path}"


def _long_pages():
    long_text = "FAILME " + (
        "This is a long source sentence with enough words to require several "
        "chunks for the translation pipeline. " * 240)
    return [[
        paragraph_block(long_text, [60, 80, 540, 700]),
        paragraph_block("A short second paragraph.", [60, 720, 540, 760]),
    ]]


def test_completed_job_publishes_report_before_status_and_survives_pruning(web):
    web.http.zip_bytes = result_zip_bytes(page_count=3, pages=_pages())
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=3)
    external_source = source.read_bytes()
    upload = web.upload(source)

    response = web.start(upload)
    assert response.status_code == 200, response.get_json()
    translation_id = response.get_json()["translation_id"]

    status = web.wait_for_status(translation_id)
    assert status["status"] == "completed", status

    # The completion payload that carries the same accounting is already
    # published when the terminal status becomes observable.
    completion = completed_events(web, translation_id)
    assert completion, "completed status was visible before the completion payload"
    assert completion[-1]["accounting"]["coverage_complete"] is True

    accounting = status["accounting"]
    assert accounting["coverage_complete"] is True
    assert accounting["source_pages"] == 3
    assert accounting["result_pages"] == 3
    assert accounting["recognized_blocks"] == accounting["accounted_blocks"] == 5
    assert accounting["empty_pages"] == 1
    assert accounting["excluded"] == 1
    assert accounting["body_complete"] is True

    sidecar = _sidecar(web)
    assert sidecar.is_file()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["coverage"]["mapped_source_pages"] == [1, 2, 3]
    assert payload["coverage"]["empty_pages"] == [2]
    assert payload["claims"]["recognition_accuracy_proven"] is False
    assert payload["claims"]["every_visible_word_translated"] is False

    report = web.report(translation_id)
    assert report.status_code == 200
    assert report.get_json()["kind"] == "translated_pdf_accounting"
    assert "attachment" in report.headers.get("Content-Disposition", "").lower()

    # Validated, non-resumable success prunes the task-owned working data only.
    _wait_for_path_gone(web.uploads_dir / translation_id)
    assert web.download("book (French).pdf").status_code == 200
    assert source.read_bytes() == external_source

    # Reopen the real persistence: history and the durable report survive.
    web.close()
    restarted = LifecycleHarness(web.tmp_path, suffix=77)
    try:
        restarted.state_manager.checkpoint_manager.reset_running_jobs_on_startup()
        history = restarted.history()
        assert any(item["translation_id"] == translation_id
                   and item["status"] == "completed"
                   and item["accounting_available"] is True
                   for item in history)
        assert all(job["translation_id"] != translation_id
                   for job in restarted.resumable())
        assert restarted.download("book (French).pdf").status_code == 200
        assert restarted.report(translation_id).status_code == 200
    finally:
        restarted.close()


def test_partial_body_is_resumable_and_keeps_recovery_data_until_it_completes(web):
    web.http.zip_bytes = result_zip_bytes(page_count=1, pages=_long_pages())
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    upload = web.upload(source)

    response = web.start(upload)
    assert response.status_code == 200, response.get_json()
    translation_id = response.get_json()["translation_id"]
    partial = web.wait_for_status(translation_id)

    assert partial["status"] == "partial", partial
    assert partial["accounting"]["body_complete"] is False
    assert partial["accounting"]["failed_chunks"] >= 1
    assert partial["accounting"]["coverage_complete"] is True
    assert web.download("book (French).pdf").status_code == 200
    sidecar = _sidecar(web)
    assert sidecar.is_file()
    first_report = json.loads(sidecar.read_text(encoding="utf-8"))
    identity = first_report["source_content"]["content_identity"]
    images = first_report["images"]

    job_dir = web.uploads_dir / translation_id
    assert (job_dir / "recognition" / "recognition-state.json").is_file()
    assert any(path.suffix == ".json"
               for path in (job_dir / "xhtml_states").glob("*.json"))
    assert any(path.suffix == ".pdf" for path in job_dir.iterdir())
    resumable = web.resumable()
    assert any(job["translation_id"] == translation_id
               and job["file_type"] == "pdf" for job in resumable)
    assert web.report(translation_id).status_code == 200

    # A retry must re-enter the same recognized content and healed chunks.
    web.llm.fail = False
    assert web.resume(translation_id).status_code == 200
    finished = web.wait_for_status(translation_id)
    assert finished["status"] == "completed", finished
    assert finished["accounting"]["body_complete"] is True
    assert finished["accounting"]["failed_chunks"] == 0

    final_report = json.loads(sidecar.read_text(encoding="utf-8"))
    assert final_report["translation"]["complete"] is True
    assert final_report["source_content"]["content_identity"] == identity
    assert final_report["images"] == images
    _wait_for_path_gone(job_dir)
    assert len(web.http.submitted_files()) == 1


def test_failed_recognition_keeps_recovery_data_and_reports_failure(web):
    web.http.poll_states = ["failed"]
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)

    upload = web.upload(source)
    response = web.start(upload)
    translation_id = response.get_json()["translation_id"]
    failed = web.wait_for_status(translation_id)

    assert failed["status"] == "error", failed
    assert failed["error_code"] == "mineru_recognition_failed"
    assert failed["accounting"] is None
    assert web.download("book (French).pdf").status_code == 404
    assert not _sidecar(web).exists()

    job_dir = web.uploads_dir / translation_id
    assert (job_dir / "recognition" / "recognition-state.json").is_file()
    assert any(path.suffix == ".pdf" for path in job_dir.iterdir())
    state = web.recognition_state(translation_id)
    assert state.phase == "failed"
    resumable = web.resumable()
    assert any(job["translation_id"] == translation_id for job in resumable)

    # Reopening persistence keeps the same recovery path.
    web.close()
    restarted = LifecycleHarness(web.tmp_path, suffix=78)
    try:
        assert any(job["translation_id"] == translation_id
                   for job in restarted.resumable())
        job_dir = restarted.uploads_dir / translation_id
        assert (job_dir / "recognition" / "recognition-state.json").is_file()
    finally:
        restarted.close()


def test_local_stop_is_interrupted_and_continues_without_resubmission(
        web, monkeypatch):
    import src.core.pdf.translator as pdf_translator

    real_recognize = pdf_translator.recognize_pdf

    def short_poll(*args, **kwargs):
        kwargs.setdefault("poll_interval_seconds", 0.01)
        return real_recognize(*args, **kwargs)

    monkeypatch.setattr(pdf_translator, "recognize_pdf", short_poll)
    web.http.poll_states = ["running"]
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)

    upload = web.upload(source)
    response = web.start(upload)
    translation_id = response.get_json()["translation_id"]

    deadline = time.time() + 30
    while web.http.poll_count < 1 and time.time() < deadline:
        time.sleep(0.01)
    assert web.http.poll_count >= 1, "recognition never polled"
    stopped = web.client.post(f"/api/translation/{translation_id}/interrupt")
    assert stopped.status_code == 200, stopped.get_json()

    interrupted = web.wait_for_status(translation_id)
    assert interrupted["status"] == "interrupted", interrupted
    assert interrupted["error_code"] in (
        "mineru_recognition_interrupted", "mineru_recognition_timeout")
    assert web.llm.calls == 0
    state = web.recognition_state(translation_id)
    assert state.phase in ("interrupted_local", "timed_out")
    assert state.batch_id
    job_dir = web.uploads_dir / translation_id
    assert (job_dir / "recognition" / "recognition-state.json").is_file()

    web.http.poll_states = ["done"]
    assert web.resume(translation_id).status_code == 200
    finished = web.wait_for_status(translation_id)
    assert finished["status"] == "completed", finished
    assert len(web.http.submitted_files()) == 1


def test_completion_gate_failure_keeps_the_published_artifacts_and_reports_error(
        web, monkeypatch):
    incomplete = lambda path: PdfCompletionAssessment(
        False, "coverage_incomplete",
        "The report does not establish complete whole-book coverage.")
    # The artifact-level assessment runs in the translator (before it drops the
    # segmented checkpoint) and again in the job owner (the final verdict).
    import src.api.handlers as handlers_module
    import src.core.pdf.translator as pdf_translator

    monkeypatch.setattr(pdf_translator, "assess_pdf_completion", incomplete)
    monkeypatch.setattr(handlers_module, "assess_pdf_completion", incomplete)
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    upload = web.upload(source)

    response = web.start(upload)
    translation_id = response.get_json()["translation_id"]
    status = web.wait_for_status(translation_id)

    assert status["status"] == "error", status
    assert status["error_code"] == MineruCompletionInvalid.code
    # A failed final verdict never destroys an already valid artifact/report.
    assert web.download("book (French).pdf").status_code == 200
    assert _sidecar(web).is_file()
    assert web.report(translation_id).status_code == 200
    # The working data, including the segmented checkpoint, is retained; the
    # job stays retryable.
    job_dir = web.uploads_dir / translation_id
    assert job_dir.exists()
    assert any(path.suffix == ".json"
               for path in (job_dir / "xhtml_states").glob("*.json"))
    assert any(job["translation_id"] == translation_id for job in web.resumable())


def test_explicit_deletion_removes_task_owned_data_only(web):
    # A finished book whose output/report live outside the pruned working cache.
    completed_source = build_source_pdf(web.tmp_path / "completed.pdf", pages=1)
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    finished_id, finished = web.start_and_wait(web.upload(completed_source),
                                               output_filename="finished.pdf")
    assert finished["status"] == "completed", finished

    # A failed task that still owns source/recognition/checkpoint data.
    web.http.poll_states = ["failed"]
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    failed_source = build_source_pdf(web.tmp_path / "failed.pdf", pages=1)
    failed_id, failed = web.start_and_wait(web.upload(failed_source),
                                           output_filename="failed.pdf")
    assert failed["status"] == "error", failed

    job_dir = web.uploads_dir / failed_id
    assert (job_dir / "recognition").is_dir()
    evidence = Path(web.output_dir) / "private-probe-evidence.txt"
    evidence.write_text("not an application artifact", encoding="utf-8")
    other_format = web.uploads_dir / "epub-recovery"
    other_format.mkdir(parents=True)
    (other_format / "checkpoint.json").write_text("{}", encoding="utf-8")

    # Deletion owns the job's recovery data even if a claim is still held.
    deadline = time.time() + 10
    while web.state_manager.is_execution_active(failed_id) and time.time() < deadline:
        time.sleep(0.01)
    assert web.state_manager.claim_execution(failed_id) is True
    deleted = web.delete_checkpoint(failed_id)
    assert deleted.status_code == 200, deleted.get_json()
    assert web.state_manager.is_execution_active(failed_id) is False
    _wait_for_path_gone(job_dir)
    assert all(job["translation_id"] != failed_id for job in web.resumable())

    assert web.download("finished.pdf").status_code == 200
    assert (Path(web.output_dir) / "finished.pdf.accounting.json").is_file()
    assert web.report(finished_id).status_code == 200
    assert failed_source.is_file()
    assert completed_source.is_file()
    assert evidence.is_file()
    assert (other_format / "checkpoint.json").is_file()

    # Deleting the completed task's working record is still not output
    # deletion: the finished book and its durable report remain user-owned.
    assert web.delete_checkpoint(finished_id).status_code == 200
    assert web.download("finished.pdf").status_code == 200
    assert (Path(web.output_dir) / "finished.pdf.accounting.json").is_file()


def test_expired_job_cleanup_removes_recognition_files_not_outputs_or_other_tasks(web):
    # A finished book: its output/report must outlive the job row.
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    source = build_source_pdf(web.tmp_path / "finished.pdf", pages=1)
    finished_id, finished = web.start_and_wait(web.upload(source),
                                               output_filename="finished.pdf")
    assert finished["status"] == "completed", finished

    # An old failed task with task-owned recognition data.
    web.http.poll_states = ["failed"]
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    old_source = build_source_pdf(web.tmp_path / "old.pdf", pages=1)
    old_id, old = web.start_and_wait(web.upload(old_source),
                                     output_filename="old.pdf")
    assert old["status"] == "error", old
    old_dir = web.uploads_dir / old_id
    assert (old_dir / "recognition" / "recognition-state.json").is_file()
    age_job(web, old_id, days=40)
    age_job(web, finished_id, days=40)

    # Simulate a completed job whose earlier prune could not remove its
    # task-owned working directory: the same 30-day sweep must still cover it.
    finished_dir = web.uploads_dir / finished_id
    (finished_dir / "recognition").mkdir(parents=True)
    (finished_dir / "recognition" / "recognition-state.json").write_text(
        "{}", encoding="utf-8")

    # A recent failed task in the same store is untouched.
    web.http.poll_states = ["failed"]
    internet_source = build_source_pdf(web.tmp_path / "recent.pdf", pages=1)
    recent_id, recent = web.start_and_wait(web.upload(internet_source),
                                           output_filename="recent.pdf")
    assert recent["status"] == "error", recent
    recent_dir = web.uploads_dir / recent_id
    assert recent_dir.is_dir()

    evidence = Path(web.output_dir) / "private-acceptance-evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    external_source = web.tmp_path / "user-source.pdf"
    external_source.write_bytes(b"the user's own file, never owned by a job")

    deleted_jobs, cleaned_dirs = web.manager.cleanup_old_jobs(max_age_days=30)
    assert deleted_jobs == 2
    assert cleaned_dirs == 2

    _wait_for_path_gone(old_dir)
    _wait_for_path_gone(finished_dir)
    assert recent_dir.is_dir()
    assert (recent_dir / "recognition" / "recognition-state.json").is_file()
    assert web.download("finished.pdf").status_code == 200
    assert (Path(web.output_dir) / "finished.pdf.accounting.json").is_file()
    assert evidence.is_file()
    assert external_source.is_file()


def test_report_and_status_stop_claiming_success_for_a_missing_output(web):
    web.http.zip_bytes = result_zip_bytes(page_count=1)
    source = build_source_pdf(web.tmp_path / "source.pdf", pages=1)
    translation_id, completed = web.start_and_wait(web.upload(source))
    assert completed["status"] == "completed", completed
    assert web.report(translation_id).status_code == 200

    removed = web.client.delete(f"/api/files/{quote('book (French).pdf')}")
    assert removed.status_code == 200, removed.get_json()

    status = web.client.get(f"/api/translation/{translation_id}").get_json()
    assert status["status"] == "completed"
    assert status["accounting"] is None
    assert web.report(translation_id).status_code == 404
    history = web.history()
    item = next(item for item in history
                if item["translation_id"] == translation_id)
    assert item["accounting_available"] is False


def test_a_failed_start_releases_the_execution_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("MINERU_API_TOKEN", "test-mineru-token")
    web = LifecycleHarness(
        tmp_path, start_job=lambda tid, config: (_ for _ in ()).throw(
            RuntimeError("thread start failed")))
    try:
        text_file = tmp_path / "story.txt"
        text_file.write_text("Once upon a time.\n", encoding="utf-8")
        upload = web.upload(text_file)
        payload = {
            "file_path": upload["file_path"],
            "file_type": "txt",
            "source_language": "English",
            "target_language": "French",
            "model": "test-model",
            "llm_api_endpoint": "http://localhost:11434/api/generate",
            "llm_provider": "ollama",
            "output_filename": "story (French).txt",
            "prompt_options": {},
        }
        with pytest.raises(RuntimeError):
            web.client.post("/api/translate", json=payload)
        translation_id = web.state_manager.get_translation_summaries()[0][
            "translation_id"]
        assert web.state_manager.is_execution_active(translation_id) is False
    finally:
        web.close()

    # Deleting a job also abandons any execution claim it still held.
    manager = TranslationStateManager(
        checkpoint_manager=CheckpointManager(
            db_path=str(tmp_path / "claims.db"),
            uploads_dir=tmp_path / "claims-uploads"))
    try:
        manager.create_translation("trans_claim", {})
        assert manager.is_execution_active("trans_claim") is True
        manager.delete_checkpoint("trans_claim")
        assert manager.is_execution_active("trans_claim") is False
    finally:
        manager.checkpoint_manager.close()
