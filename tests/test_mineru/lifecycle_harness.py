"""Reusable Web/API lifecycle harness for the online PDF translation tests.

Only external boundaries (MinerU HTTP, the LLM, and time) are substituted by the
callers. This helper wires the real Flask routes, task state, temporary SQLite
job store, task-owned uploads directory and output directory, so lifecycle tests
exercise the application's own HTTP seam.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

from flask import Flask

import src.api.auth as api_auth
from src.api.routes import configure_routes
from src.api.translation_state import TranslationStateManager
from src.persistence.checkpoint_manager import CheckpointManager
from src.utils.security import rate_limiter
from tests.test_mineru.online_fixtures import FakeLlmClient

TERMINAL = {"completed", "partial", "error", "interrupted", "rate_limited"}
PROVIDER_TOKEN = "test-mineru-token"
LLM_PREFIX = "FR: "


class FakeSocketIO:
    """Records emissions; the WebSocket transport is not the seam under test."""

    def __init__(self):
        self.events = []

    def emit(self, event, data=None, namespace=None, **kwargs):
        self.events.append((event, data, namespace))


class FailingLlmClient(FakeLlmClient):
    """A fake provider that fails any chunk containing ``fail_marker``."""

    def __init__(self, prefix: str = LLM_PREFIX, fail_marker: str = "FAILME"):
        super().__init__(prefix=prefix)
        self.fail_marker = fail_marker
        self.fail = True

    async def generate(self, prompt: str, timeout: int = 300,
                       system_prompt: str | None = None):
        if self.fail and self.fail_marker in (prompt or ""):
            raise RuntimeError("scripted LLM failure for this chunk")
        return await super().generate(prompt, timeout=timeout,
                                      system_prompt=system_prompt)


class LifecycleHarness:
    """One Web application instance over a shared temporary working directory."""

    def __init__(self, tmp_path: Path, *, start_job=None, suffix: int = 0):
        self.tmp_path = Path(tmp_path)
        self.output_dir = self.tmp_path / "output"
        self.uploads_dir = self.output_dir / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.manager = CheckpointManager(
            db_path=str(self.tmp_path / "jobs.db"),
            uploads_dir=self.uploads_dir)
        self.state_manager = TranslationStateManager(
            checkpoint_manager=self.manager,
            server_session_id=str(int(time.time()) + suffix))
        self.socketio = FakeSocketIO()
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True

        def default_start_job(translation_id, config):
            from src.api.handlers import start_translation_job
            start_translation_job(
                translation_id, config, self.state_manager,
                str(self.output_dir), self.socketio)

        configure_routes(
            self.app, self.state_manager, str(self.output_dir),
            start_job or default_start_job)
        api_auth.register_auth(self.app)
        rate_limiter._requests.clear()
        self.client = self.app.test_client()
        self.client.environ_base["HTTP_X_API_TOKEN"] = api_auth.API_TOKEN

    # -- lifecycle -----------------------------------------------------
    def close(self):
        self.manager.close()

    # -- HTTP helpers --------------------------------------------------
    def upload(self, path: Path, filename: str | None = None):
        with open(path, "rb") as stream:
            result = self.client.post(
                "/api/upload",
                data={"file": (stream, filename or Path(path).name)},
                content_type="multipart/form-data",
            )
        assert result.status_code == 200, result.get_json()
        return result.get_json()

    def start(self, upload, *, authorized: bool = True,
              output_filename: str = "book (French).pdf", **extra):
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

    def start_and_wait(self, upload, **kwargs):
        response = self.start(upload, **kwargs)
        assert response.status_code == 200, response.get_json()
        translation_id = response.get_json()["translation_id"]
        return translation_id, self.wait_for_status(translation_id)

    def wait_for_status(self, translation_id: str, timeout: float = 90):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            response = self.client.get(f"/api/translation/{translation_id}")
            assert response.status_code == 200, response.get_json()
            last = response.get_json()
            if last["status"] in TERMINAL:
                return last
            time.sleep(0.02)
        raise AssertionError(f"job did not finish: {last}")

    def wait_for_event(self, *, event: str, translation_id: str,
                       status: str | None = None, timeout: float = 30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for name, data, _ in self.socketio.events:
                if name != event or not isinstance(data, dict):
                    continue
                if data.get("translation_id") != translation_id:
                    continue
                if status is not None and data.get("status") != status:
                    continue
                return data
            time.sleep(0.01)
        return None

    def resume(self, translation_id: str, body=None, *, wait: bool = True):
        if wait:
            deadline = time.time() + 10
            while (self.state_manager.is_execution_active(translation_id)
                   and time.time() < deadline):
                time.sleep(0.005)
        return self.client.post(
            f"/api/resume/{translation_id}", json=body or {})

    def download(self, filename: str):
        return self.client.get(f"/api/files/{quote(filename)}")

    def report(self, translation_id: str):
        return self.client.get(
            f"/api/translation/{quote(translation_id)}/accounting")

    def delete_checkpoint(self, translation_id: str):
        return self.client.delete(f"/api/checkpoint/{translation_id}")

    def history(self):
        return self.client.get("/api/history").get_json()["history"]

    def resumable(self):
        return self.client.get("/api/resumable").get_json()["resumable_jobs"]

    def recognition_state(self, translation_id: str):
        return self.manager.load_recognition_state(translation_id)


def age_job(harness: LifecycleHarness, translation_id: str, days: int) -> None:
    """Move one job's created_at into the past (the startup sweep's clock)."""
    connection = sqlite3.connect(harness.manager.db.db_path)
    try:
        connection.execute(
            "UPDATE translation_jobs "
            "SET created_at = datetime('now', ? || ' days') "
            "WHERE translation_id = ?",
            (f"-{days}", translation_id),
        )
        connection.commit()
    finally:
        connection.close()


def completed_events(harness: LifecycleHarness, translation_id: str):
    return [
        data for event, data, _ in harness.socketio.events
        if event == "translation_update" and isinstance(data, dict)
        and data.get("translation_id") == translation_id
        and data.get("status") == "completed"
    ]


__all__ = [
    "FakeSocketIO", "FailingLlmClient", "LifecycleHarness", "age_job",
    "completed_events", "LLM_PREFIX", "PROVIDER_TOKEN",
]
