"""Admission of a PDF for online recognition (issue #20).

Seam under test: ``admit_pdf_source`` — the single gate every submission path
must pass before a provider request can exist. Missing authorization, missing
configuration, corrupt/encrypted sources and excess limits are rejected here,
so they can never reach the network.
"""

from __future__ import annotations

import pytest

from src.core.mineru.admission import MAX_PAGES, AdmittedSource, admit_pdf_source
from src.core.mineru.errors import (
    MineruAuthorizationRequired,
    MineruByteLimit,
    MineruError,
    MineruPageLimit,
    MineruPdfEncrypted,
    MineruPdfUnreadable,
    MineruTokenMissing,
)
from tests.test_mineru.online_fixtures import (
    FakeMineruHttp,
    build_corrupt_pdf,
    build_encrypted_pdf,
    build_source_pdf,
    install_fake_http,
    sha256_file,
)

TOKEN = "test-mineru-token"


def _admit(path, **overrides):
    options = {"authorized": True, "token": TOKEN}
    options.update(overrides)
    return admit_pdf_source(path, **options)


def test_admitted_source_carries_its_identity(tmp_path):
    source = build_source_pdf(tmp_path / "source.pdf", pages=3)

    admitted = _admit(source)

    assert isinstance(admitted, AdmittedSource)
    assert admitted.path == source
    assert admitted.file_name == "source.pdf"
    assert admitted.page_count == 3
    assert admitted.size_bytes == source.stat().st_size
    assert admitted.sha256 == sha256_file(source)


def test_missing_authorization_is_rejected(tmp_path):
    source = build_source_pdf(tmp_path / "source.pdf", pages=2)

    with pytest.raises(MineruAuthorizationRequired) as raised:
        _admit(source, authorized=False)

    assert raised.value.code == "mineru_authorization_required"
    assert str(raised.value)


def test_missing_token_is_rejected(tmp_path):
    source = build_source_pdf(tmp_path / "source.pdf", pages=2)

    with pytest.raises(MineruTokenMissing) as raised:
        _admit(source, token="")

    assert raised.value.code == "mineru_token_missing"


def test_encrypted_pdf_is_rejected(tmp_path):
    source = build_encrypted_pdf(tmp_path / "secret.pdf")

    with pytest.raises(MineruPdfEncrypted) as raised:
        _admit(source)

    assert raised.value.code == "mineru_pdf_encrypted"


def test_corrupt_pdf_is_rejected(tmp_path):
    source = build_corrupt_pdf(tmp_path / "broken.pdf")

    with pytest.raises(MineruPdfUnreadable) as raised:
        _admit(source)

    assert raised.value.code == "mineru_pdf_unreadable"


def test_missing_file_is_rejected_as_unreadable(tmp_path):
    with pytest.raises(MineruPdfUnreadable):
        _admit(tmp_path / "not-there.pdf")


def test_page_limit_is_enforced(tmp_path, monkeypatch):
    source = build_source_pdf(tmp_path / "long.pdf", pages=MAX_PAGES + 1)
    http = install_fake_http(monkeypatch, FakeMineruHttp())

    with pytest.raises(MineruPageLimit) as raised:
        _admit(source)

    assert raised.value.code == "mineru_page_limit"
    assert raised.value.limits == {"max_pages": MAX_PAGES, "max_bytes": 200_000_000}
    # Admission never talks to the provider.
    assert http.requests == []


def test_byte_limit_is_enforced(tmp_path):
    source = build_source_pdf(tmp_path / "source.pdf", pages=2)

    with pytest.raises(MineruByteLimit) as raised:
        _admit(source, max_bytes=16)

    assert raised.value.code == "mineru_byte_limit"
    assert raised.value.limits["max_bytes"] == 16


def test_errors_share_the_mineru_hierarchy():
    assert issubclass(MineruAuthorizationRequired, MineruError)
    assert issubclass(MineruPdfUnreadable, MineruError)
    assert isinstance(MineruPageLimit("x", limits={"max_pages": 1}), MineruError)
