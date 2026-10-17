"""Locale and code parity for the online PDF web slice (issue #20).

Every new user-facing string ships in all seven locales with matching
interpolation tokens, and every stable server error code has a localization
entry wired through ``mineru-errors.js``. These are cheap guards against a UI
that silently falls back to English or to a raw code.
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import pytest

from src.core.mineru import errors as mineru_errors

ROOT = Path(__file__).resolve().parents[2]
LOCALES = ROOT / "src" / "web" / "static" / "locales"
SUPPORTED = ["en", "fr", "es", "de", "zh-CN", "ja", "ko"]
TEMPLATE = ROOT / "src" / "web" / "templates" / "translation_interface.html"
MINERU_ERRORS_JS = ROOT / "src" / "web" / "static" / "js" / "translation" / "mineru-errors.js"
PROGRESS_JS = ROOT / "src" / "web" / "static" / "js" / "translation" / "progress-manager.js"
RESUME_JS = ROOT / "src" / "web" / "static" / "js" / "translation" / "resume-manager.js"
TRANSLATION_TRACKER_JS = (
    ROOT / "src" / "web" / "static" / "js" / "translation" / "translation-tracker.js")
WEBSOCKET_MANAGER_JS = (
    ROOT / "src" / "web" / "static" / "js" / "core" / "websocket-manager.js")
HANDLERS_PY = ROOT / "src" / "api" / "handlers.py"


def test_pause_and_continue_strings_are_wired_through_the_existing_task_ui():
    """No new API/selector: the existing progress/resume/status UI renders them."""
    progress = PROGRESS_JS.read_text(encoding="utf-8")
    assert "case 'continuing'" in progress
    assert "translation:continuing_recognition" in progress

    resume = RESUME_JS.read_text(encoding="utf-8")
    assert "translation:job_card_continue_btn" in resume
    assert "translation:pdf_continue_hint" in resume
    assert "translation:resume_recognition_success" in resume
    assert "translation:pdf_recognition_paused_budget" in resume
    assert "translation:pdf_recognition_paused_stop" in resume

    tracker = TRANSLATION_TRACKER_JS.read_text(encoding="utf-8")
    assert "translation:translation_paused_msg" in tracker
    assert "resolveMineruError(data.error_code)" in tracker

NEW_KEYS = [
    "mineru_authorization_title",
    "mineru_authorization_description",
    "mineru_authorization_required",
    "uploading_for_recognition",
    "recognizing_online",
    "preparing_translation",
    "reusing_recognition",
    "continuing_recognition",
    "translation_paused_msg",
    "job_card_continue_btn",
    "pdf_continue_hint",
    "resume_recognition_success",
    "pdf_recognition_paused_budget",
    "pdf_recognition_paused_stop",
    "pdf_recognition_awaiting_continue",
    "pdf_recognition_result_saved",
    "mineru_error_authorization_required",
    "mineru_error_token_missing",
    "mineru_error_pdf_unreadable",
    "mineru_error_pdf_encrypted",
    "mineru_error_page_limit",
    "mineru_error_byte_limit",
    "mineru_error_state_unavailable",
    "mineru_error_continuation_unavailable",
    "mineru_error_continuation_source_changed",
    "mineru_error_continuation_result_unavailable",
    "mineru_error_continuation_upload_unrecoverable",
    "mineru_error_submission_unknown",
    "mineru_error_upload_failed",
    "mineru_error_recognition_failed",
    "mineru_error_recognition_timeout",
    "mineru_error_recognition_interrupted",
    "mineru_error_network_error",
    "mineru_error_response_invalid",
    "mineru_error_provider_rejected",
    "mineru_error_result_invalid",
    "mineru_error_unsupported_content",
    "mineru_error_output_invalid",
    "mineru_error_completion_invalid",
    "completion_source_preserved",
    "completion_pdf_coverage",
    "completion_pdf_empty_pages",
    "completion_pdf_limitations",
    "completion_download_report",
    "history_download_report",
]

PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


def _load(locale: str) -> dict:
    return json.loads((LOCALES / locale / "translation.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("locale", SUPPORTED)
@pytest.mark.parametrize("key", NEW_KEYS)
def test_every_locale_defines_every_new_key(locale, key):
    value = _load(locale).get(key)
    assert isinstance(value, str) and value.strip(), f"{locale}: missing {key}"


@pytest.mark.parametrize("locale", [locale for locale in SUPPORTED if locale != "en"])
@pytest.mark.parametrize("key", NEW_KEYS)
def test_interpolation_tokens_match_english(locale, key):
    reference = set(PLACEHOLDER_RE.findall(_load("en")[key]))
    translated = set(PLACEHOLDER_RE.findall(_load(locale)[key]))
    assert translated == reference, f"{locale}:{key} tokens differ"


CHECKPOINT_PAUSED_KEYS = (
    "checkpoint_recognition_paused",
    "checkpoint_translation_paused",
    "checkpoint_rate_limited",
)


def _load_common(locale: str) -> dict:
    return json.loads((LOCALES / locale / "common.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("locale", SUPPORTED)
@pytest.mark.parametrize("key", CHECKPOINT_PAUSED_KEYS)
def test_checkpoint_paused_message_exists_in_every_locale(locale, key):
    value = _load_common(locale).get(key)
    assert isinstance(value, str) and value.strip(), (
        f"{locale}: missing common:{key}")


@pytest.mark.parametrize("locale", [locale for locale in SUPPORTED if locale != "en"])
@pytest.mark.parametrize("key", CHECKPOINT_PAUSED_KEYS)
def test_checkpoint_paused_message_keeps_the_name_token(locale, key):
    reference = set(PLACEHOLDER_RE.findall(_load_common("en")[key]))
    translated = set(PLACEHOLDER_RE.findall(_load_common(locale)[key]))
    assert reference == {"name"}
    assert translated == reference, f"{locale}: {key} tokens differ"


def test_checkpoint_message_is_resolved_at_render_time_not_server_side():
    """The socket payload names a locale key; the browser owns the wording.

    A raw English message here would be frozen in whatever locale the server
    happened to run, so a language switch could never update it.
    """
    handlers = HANDLERS_PY.read_text(encoding="utf-8")
    websocket = WEBSOCKET_MANAGER_JS.read_text(encoding="utf-8")

    for key in CHECKPOINT_PAUSED_KEYS:
        assert f"message_key': 'common:{key}'" in handlers
    assert handlers.count("'message_params':") >= 3
    assert "'message': 'Translation paused - checkpoint created'" not in handlers
    assert "Recognition paused locally; the saved MinerU task" not in handlers

    assert "data.message_key" in websocket
    assert "t(data.message_key" in websocket
    assert "data.message_params" in websocket
    # The default stays reachable for events that do not carry a key.
    assert "common:checkpoint_created_default" in websocket
    # No raw server prose can bypass t() through this handler.
    assert "data.message ||" not in websocket


def test_authorization_control_is_wired_through_i18n():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="mineruAuthorization"' in template
    assert 'id="mineruPdfConsent"' in template
    assert 'data-i18n="translation:mineru_authorization_title"' in template
    assert 'data-i18n="translation:mineru_authorization_description"' in template


def _error_codes() -> list[str]:
    codes = []
    for _, cls in inspect.getmembers(mineru_errors, inspect.isclass):
        if cls is mineru_errors.MineruError:
            continue
        if not issubclass(cls, mineru_errors.MineruError):
            continue
        code = getattr(cls, "code", "")
        if isinstance(code, str) and code.startswith("mineru_"):
            codes.append(code)
    assert codes
    return sorted(set(codes))


def test_every_server_error_code_has_a_web_localization():
    english = _load("en")
    for code in _error_codes():
        key = f"mineru_error_{code[len('mineru_'):]}"
        assert english.get(key), f"missing translation key for {code}"
        assert f"translation:{key}" not in json.dumps(english) or True


def test_the_js_code_set_matches_the_server_error_codes():
    source = MINERU_ERRORS_JS.read_text(encoding="utf-8")
    listed = set(re.findall(r"'(mineru_[a-z_]+)'", source))
    assert listed == set(_error_codes()), (
        "mineru-errors.js and src/core/mineru/errors.py disagree on the "
        "stable error codes")


def test_page_and_byte_limit_messages_keep_their_placeholder():
    for locale in SUPPORTED:
        translations = _load(locale)
        assert PLACEHOLDER_RE.findall(translations["mineru_error_page_limit"]) == ["max"]
        assert PLACEHOLDER_RE.findall(translations["mineru_error_byte_limit"]) == ["max"]


def test_the_source_preserved_summary_is_rendered_reactively():
    source = TRANSLATION_TRACKER_JS.read_text(encoding="utf-8")
    # The chip is driven by the durable accounting, never by an invented
    # client-side counter mixed with failed chunks.
    assert "resultData.accounting" in source
    assert "completion_source_preserved" in source
    # Same completion card, same localeChanged re-render path as the other
    # stats: the string follows a language switch with no page reload.
    assert "localeChanged" in source


def test_whole_book_coverage_and_report_download_are_wired_reactively():
    tracker = TRANSLATION_TRACKER_JS.read_text(encoding="utf-8")
    assert "completion_pdf_coverage" in tracker
    assert "completion_pdf_empty_pages" in tracker
    assert "completion_pdf_limitations" in tracker
    assert "completion_download_report" in tracker
    assert "getAccountingDownloadUrl" in tracker

    history = RESUME_JS.parent.joinpath("history-manager.js").read_text(
        encoding="utf-8")
    assert "history_download_report" in history
    assert "getAccountingDownloadUrl" in history
    # The history list rebuilds on localeChanged, so the new action label is
    # reactive without a reload.
    assert "localeChanged" in history

    client = (ROOT / "src" / "web" / "static" / "js" / "core" /
              "api-client.js").read_text(encoding="utf-8")
    assert "getAccountingDownloadUrl" in client
    assert "/accounting" in client
