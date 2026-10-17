"""Durable, task-owned recognition state (issue #20).

Seam under test: ``CheckpointManager`` recognition-state methods plus the
``RecognitionState`` schema. The state is what makes fail-closed continuation
possible: it records the source fingerprint, phase, known remote identifiers and
the validated result identity, atomically, under the job's own working data.

It must never record credentials or signed storage URLs.
"""

from __future__ import annotations

import json

import pytest

from src.core.mineru.errors import MineruStateUnavailable
from src.core.mineru.recognition_state import (
    PHASES,
    RecognitionState,
    TaskRecognitionStore,
)
from src.persistence.checkpoint_manager import CheckpointManager


@pytest.fixture
def manager(tmp_path):
    manager = CheckpointManager(
        db_path=str(tmp_path / "jobs.db"),
        uploads_dir=tmp_path / "uploads",
    )
    yield manager
    manager.close()


def _state(**overrides) -> RecognitionState:
    values = {
        "phase": "submitted",
        "source_sha256": "a" * 64,
        "source_bytes": 1234,
        "source_pages": 3,
        "file_name": "book.pdf",
        "batch_id": "batch-abc123",
        "remote_state": "running",
        "attempts": 1,
    }
    values.update(overrides)
    return RecognitionState(**values)


def test_state_round_trips_under_the_task_working_data(manager, tmp_path):
    assert manager.load_recognition_state("trans_1") is None

    state = _state()
    manager.save_recognition_state("trans_1", state)
    loaded = manager.load_recognition_state("trans_1")

    assert loaded == state
    path = manager.recognition_dir("trans_1") / "recognition-state.json"
    assert path.is_file()
    assert list(path.parent.glob("*.part")) == []
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["phase"] == "submitted"
    assert payload["batch_id"] == "batch-abc123"


def test_state_is_replaced_atomically(manager, monkeypatch):
    manager.save_recognition_state("trans_1", _state(phase="submitted"))
    path = manager.recognition_dir("trans_1") / "recognition-state.json"
    original = path.read_text(encoding="utf-8")

    import src.core.mineru.recognition_state as state_module

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(state_module, "dump_json_atomic", explode)
    with pytest.raises(MineruStateUnavailable):
        manager.save_recognition_state("trans_1", _state(phase="recognizing"))

    assert path.read_text(encoding="utf-8") == original
    assert manager.load_recognition_state("trans_1").phase == "submitted"


def test_completed_task_deletion_removes_the_recognition_state(manager):
    manager.save_recognition_state("trans_1", _state())
    directory = manager.recognition_dir("trans_1")

    manager.delete_checkpoint("trans_1")

    assert not directory.exists()
    assert manager.load_recognition_state("trans_1") is None


def test_pruning_resume_data_removes_the_recognition_state(manager):
    manager.save_recognition_state("trans_1", _state())
    directory = manager.recognition_dir("trans_1")

    manager.prune_job_data("trans_1")

    assert not directory.exists()


def test_state_schema_has_no_credential_or_signed_url_fields():
    fields = set(RecognitionState.__dataclass_fields__)
    assert "token" not in fields
    assert not any("url" in name for name in fields)
    assert PHASES >= {"submitted", "validated", "submission_unknown", "timed_out"}


def test_old_state_records_still_load_with_the_new_continuation_counter():
    payload = _state().to_dict()
    payload.pop("continuations", None)

    loaded = RecognitionState.from_dict(payload)

    assert loaded.continuations == 0
    assert loaded.attempts == 1


def test_state_rejects_unknown_fields():
    payload = _state().to_dict()
    payload["upload_url"] = "https://bucket.aliyuncs.com/x?Signature=secret"

    with pytest.raises(ValueError):
        RecognitionState.from_dict(payload)


def test_state_rejects_an_invalid_remote_identifier():
    payload = _state().to_dict()
    payload["batch_id"] = "https://bucket.aliyuncs.com/x?Signature=secret"

    with pytest.raises(ValueError):
        RecognitionState.from_dict(payload)


def test_state_rejects_an_invalid_phase():
    with pytest.raises(ValueError):
        RecognitionState.from_dict(_state().to_dict() | {"phase": "uploaded-secretly"})


def test_state_rejects_invalid_result_identity():
    with pytest.raises(ValueError):
        RecognitionState.from_dict(_state().to_dict() | {"result_zip_sha256": "nope"})


def test_error_details_are_sanitized_on_save(manager):
    state = _state(
        phase="failed",
        error_message="boom at https://signed.example.com/x?Signature=secret",
    )
    manager.save_recognition_state("trans_1", state)

    payload = json.loads(
        (manager.recognition_dir("trans_1") / "recognition-state.json")
        .read_text(encoding="utf-8"))

    assert "https://" not in payload["error_message"]
    assert "Signature" not in payload["error_message"]


def test_store_exposes_a_task_owned_workspace(manager):
    store = TaskRecognitionStore(manager, "trans_7")

    assert store.workspace() == manager.recognition_dir("trans_7")
    assert store.load() is None
    store.save(_state(phase="admitted"))
    assert store.load().phase == "admitted"
    assert store.workspace().is_dir()
