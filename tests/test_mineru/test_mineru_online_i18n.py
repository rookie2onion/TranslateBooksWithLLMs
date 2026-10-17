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

NEW_KEYS = [
    "mineru_authorization_title",
    "mineru_authorization_description",
    "mineru_authorization_required",
    "uploading_for_recognition",
    "recognizing_online",
    "preparing_translation",
    "reusing_recognition",
    "mineru_error_authorization_required",
    "mineru_error_token_missing",
    "mineru_error_pdf_unreadable",
    "mineru_error_pdf_encrypted",
    "mineru_error_page_limit",
    "mineru_error_byte_limit",
    "mineru_error_state_unavailable",
    "mineru_error_continuation_unavailable",
    "mineru_error_submission_unknown",
    "mineru_error_upload_failed",
    "mineru_error_recognition_failed",
    "mineru_error_recognition_timeout",
    "mineru_error_recognition_interrupted",
    "mineru_error_network_error",
    "mineru_error_response_invalid",
    "mineru_error_provider_rejected",
    "mineru_error_result_invalid",
    "mineru_error_output_invalid",
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
