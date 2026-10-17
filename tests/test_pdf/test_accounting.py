"""Accounting sidecar and translated-PDF validation (issue #20).

Seam under test: ``validate_pdf_output``, ``build_accounting`` and
``write_accounting_sidecar``. The sidecar is the durable report of what actually
completed; a PDF is publishable only after it passed validation.
"""

from __future__ import annotations

import hashlib
import json

import pymupdf
import pytest

from src.core.mineru.errors import MineruOutputInvalid
from src.core.pdf.accounting import (
    accounting_path_for,
    build_accounting,
    read_accounting_summary,
    validate_pdf_output,
    write_accounting_sidecar,
)
from src.core.pdf.builder import build_pdf
from src.core.pdf.content import ParagraphFormat, PdfPlainContent

AUTHOR = ""


def _content(title="Sample Book"):
    return PdfPlainContent(
        paragraphs_text=["Chapter One", "A body paragraph."],
        paragraphs_style=["heading1", "normal"],
        paragraphs_format=[ParagraphFormat(), ParagraphFormat()],
        page_size=(600, 800),
        title=title,
        author=AUTHOR,
        page_count=2,
    )


def _build(path, content=None):
    content = content or _content()
    build_pdf(["Chapitre un", "Un paragraphe."], content, str(path), "French", "English")
    return path


def test_a_valid_translated_pdf_passes_validation(tmp_path):
    path = _build(tmp_path / "out.pdf")
    content = _content()

    stats = validate_pdf_output(
        path, expected_title=content.title, expected_author=AUTHOR,
        expected_paragraphs=len(content.paragraphs_text))

    assert stats.page_count >= 1
    assert stats.text_chars > 0
    assert stats.bytes == path.stat().st_size
    assert stats.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_preview_stamped_pdf_is_rejected(tmp_path):
    path = tmp_path / "preview.pdf"
    document = pymupdf.open()
    try:
        page = document.new_page(width=600, height=800)
        page.insert_text((60, 90), "Untranslated MinerU reconstruction preview", fontsize=12)
        document.set_metadata({
            "title": "Sample Book — untranslated MinerU sample preview",
            "author": "Grace Hopper",
        })
        document.save(str(path))
    finally:
        document.close()

    with pytest.raises(MineruOutputInvalid):
        validate_pdf_output(path, expected_title="Sample Book", expected_author=AUTHOR,
                            expected_paragraphs=2)


def test_a_missing_or_empty_output_is_rejected(tmp_path):
    with pytest.raises(MineruOutputInvalid):
        validate_pdf_output(tmp_path / "missing.pdf", expected_paragraphs=1)
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(MineruOutputInvalid):
        validate_pdf_output(empty, expected_paragraphs=1)


def test_an_unreadable_output_is_rejected(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7\nnot a real document")
    with pytest.raises(MineruOutputInvalid):
        validate_pdf_output(path, expected_paragraphs=1)


def test_accounting_records_what_actually_completed(tmp_path):
    path = _build(tmp_path / "out.pdf")
    content = _content()
    stats = validate_pdf_output(path, expected_title=content.title,
                                expected_author=AUTHOR, expected_paragraphs=2)
    recognition = _recognition()
    translation_stats = {
        "total_chunks": 3, "completed_chunks": 3, "failed_chunks": 0,
        "fallback_used": 0, "processed_chunks": 3,
    }

    accounting = build_accounting(
        recognition=recognition,
        content=content,
        translation_stats=translation_stats,
        output_stats=stats,
        output_filename="book (French).pdf",
        source_language="English",
        target_language="French",
        bilingual=False,
        budget_seconds=300,
    )

    assert accounting["source"]["sha256"] == "a" * 64
    assert accounting["source"]["pages"] == 2
    assert accounting["recognition"]["batch_id"] == "batch-abc123"
    assert accounting["recognition"]["result_zip_sha256"] == "b" * 64
    assert accounting["recognition"]["budget_seconds"] == 300
    assert accounting["translation"]["complete"] is True
    assert accounting["translation"]["total_chunks"] == 3
    assert accounting["output"]["pages"] == stats.page_count
    assert accounting["output"]["sha256"] == stats.sha256
    assert accounting["source_content"]["paragraphs"] == 2
    serialized = json.dumps(accounting)
    assert "https://" not in serialized
    assert "token" not in serialized.lower()


def test_accounting_reports_unfinished_chunks_honestly(tmp_path):
    path = _build(tmp_path / "out.pdf")
    content = _content()
    stats = validate_pdf_output(path, expected_title=content.title,
                                expected_author=AUTHOR, expected_paragraphs=2)

    accounting = build_accounting(
        recognition=_recognition(), content=content,
        translation_stats={"total_chunks": 4, "completed_chunks": 3,
                           "failed_chunks": 1, "fallback_used": 1},
        output_stats=stats, output_filename="out.pdf", source_language="English",
        target_language="French", bilingual=True, budget_seconds=300,
    )

    assert accounting["translation"]["complete"] is False
    assert accounting["translation"]["failed_chunks"] == 1
    assert accounting["translation"]["unfinished_chunks"] == 1
    assert accounting["translation"]["bilingual"] is True


def test_sidecar_is_written_next_to_the_output_and_read_back(tmp_path):
    path = _build(tmp_path / "out.pdf")
    content = _content()
    stats = validate_pdf_output(path, expected_title=content.title,
                                expected_author=AUTHOR, expected_paragraphs=2)
    accounting = build_accounting(
        recognition=_recognition(), content=content,
        translation_stats={"total_chunks": 2, "completed_chunks": 2,
                           "failed_chunks": 0},
        output_stats=stats, output_filename="out.pdf", source_language="English",
        target_language="French", bilingual=False, budget_seconds=300,
    )

    sidecar = write_accounting_sidecar(path, accounting)

    assert sidecar == accounting_path_for(path)
    assert sidecar.is_file()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["kind"] == "translated_pdf_accounting"
    assert read_accounting_summary(path)["body_complete"] is True
    assert read_accounting_summary(tmp_path / "other.pdf") is None


class _Source:
    def __init__(self, content):
        self._content = content
        self.provenance = ()

    def to_plain_content(self):
        return self._content


class _Recognition:
    def __init__(self, content):
        self.admitted = type("Admitted", (), {
            "sha256": "a" * 64, "size_bytes": 1234, "page_count": 2,
            "file_name": "source.pdf",
        })()
        self.source = _Source(content)
        self.cache = type("Cache", (), {
            "backend": "hybrid", "engine_version": "2.5.4", "fingerprints": {},
        })()
        self.batch_id = "batch-abc123"
        self.result_zip_sha256 = "b" * 64
        self.result_cache_sha256 = "c" * 64
        self.page_count = 2
        self.elapsed_seconds = 12.5
        self.retries = 1
        self.remote_states = ("pending", "done")
        self.reused = False


def _recognition():
    return _Recognition(_content())
