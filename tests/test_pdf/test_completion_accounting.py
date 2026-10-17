"""Whole-book accounting and the completion verdict (issue #23).

Seam under test: the durable accounting sidecar of a translated PDF and the
assessment that decides whether its report proves whole-book completion. The
report must represent every expected source page (including empty recognized
pages) and every recognized block, so a sample-only, missing-page, duplicate or
unaccounted result can never be reported as a complete book.

The cache, structural adapter, PDF builder and sidecar writer are the real ones;
the document is a synthetic MinerU V2 cache.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.mineru.cache import load_cache
from src.core.mineru.errors import MineruCompletionInvalid
from src.core.mineru.structure import adapt
from src.core.pdf.accounting import (
    assess_pdf_completion,
    build_accounting,
    read_accounting,
    read_accounting_summary,
    validate_pdf_output,
    write_accounting_sidecar,
)
from src.core.pdf.builder import build_pdf
from src.core.pdf.content import ParagraphFormat, PdfPlainContent
from tests.test_mineru.mineru_fixture import build_cache
from tests.test_mineru.online_fixtures import (
    image_block,
    paragraph_block,
    table_block,
    title_block,
)


def _pages():
    return [
        {"blocks": [
            paragraph_block("Intro paragraph.", [60, 80, 540, 140]),
            image_block("images/fig1.png", [60, 160, 540, 500],
                        caption="Figure 1: a caption", footnote="Figure credit."),
        ]},
        {"blocks": []},
        {"blocks": [
            title_block("Chapter Two", [60, 80, 540, 140]),
            {"type": "page_header", "text": "Running Header", "bbox": [600, 40, 900, 60]},
            paragraph_block("The final paragraph.", [60, 120, 540, 200]),
            table_block("images/table1.png", [60, 300, 940, 500],
                        caption="Table 2: data", footnote="Source: report"),
        ]},
    ]


def _source(tmp_path: Path):
    cache = load_cache(build_cache(tmp_path / "cache", pages=_pages(),
                                   source_pages=[1, 2, 3]))
    return cache, adapt(cache)


def _recognition(cache, source):
    return SimpleNamespace(
        admitted=SimpleNamespace(file_name="source.pdf", sha256="a" * 64,
                                 size_bytes=1234, page_count=3),
        cache=cache,
        source=source,
        batch_id="batch-abc123",
        result_zip_sha256="b" * 64,
        result_cache_sha256="c" * 64,
        page_count=3,
        elapsed_seconds=12.5,
        retries=0,
        remote_states=("pending", "done"),
        reused=False,
    )


def _published(tmp_path: Path):
    """Build the PDF and its durable report, and return (output, accounting)."""
    cache, source = _source(tmp_path)
    content = source.to_plain_content()
    output = tmp_path / "book (French).pdf"
    build_pdf([f"FR: {text}" for text in content.paragraphs_text],
              content, str(output), "French", "English")
    output_stats = validate_pdf_output(
        output, expected_title=content.title, expected_author="",
        expected_paragraphs=len(content.paragraphs_text))
    accounting = build_accounting(
        recognition=_recognition(cache, source), content=content,
        translation_stats={"total_chunks": 3, "completed_chunks": 3,
                           "failed_chunks": 0, "unfinished_chunks": 0},
        output_stats=output_stats, output_filename=output.name,
        source_language="English", target_language="French", bilingual=False,
        budget_seconds=300,
    )
    write_accounting_sidecar(output, accounting)
    return output, accounting


def _rewrite(output: Path, accounting) -> None:
    write_accounting_sidecar(output, accounting)


# ---------------------------------------------------------------------------
# The report represents the whole book, including empty recognized pages
# ---------------------------------------------------------------------------


def test_report_records_exact_page_mapping_and_empty_pages(tmp_path):
    output, accounting = _published(tmp_path)
    coverage = accounting["coverage"]

    assert coverage["expected_source_pages"] == 3
    assert coverage["recognized_pages"] == 3
    assert coverage["mapped_source_pages"] == [1, 2, 3]
    assert coverage["missing_source_pages"] == []
    assert coverage["duplicate_source_pages"] == []
    assert coverage["unexpected_source_pages"] == []
    assert coverage["empty_pages"] == [2]
    assert coverage["complete"] is True

    by_page = {page["source_page"]: page for page in coverage["pages"]}
    assert by_page[1]["empty"] is False
    assert by_page[1]["recognized_blocks"] == 2
    assert by_page[1]["images"] == 1
    assert by_page[2] == {
        "source_page": 2, "result_page": 2, "recognized_blocks": 0,
        "output_paragraphs": 0, "images": 0, "source_preserved": 0,
        "excluded_blocks": 0, "retained_blocks": 0, "empty": True,
    }
    # A running header is a recognized block retained as a justified exclusion.
    assert by_page[3]["excluded_blocks"] == 1
    assert by_page[3]["retained_blocks"] == 3


def test_report_separates_source_preserved_content_and_links_associations(tmp_path):
    output, accounting = _published(tmp_path)
    content = accounting["source_content"]

    assert content["blocks_seen"] == content["blocks_accounted"] == 6
    assert content["blocks_unaccounted"] == 0
    assert content["excluded"] == 1
    assert content["empty_pages"] == 1
    assert content["source_preserved"] == 1
    assert content["tables"] == 1
    assert content["formulas"] == 0

    exclusion = content["exclusions"][0]
    assert exclusion["kind"] == "running_header"
    assert exclusion["source_page"] == 3
    assert "running header" in exclusion["reason"].lower()

    figure = next(image for image in accounting["images"]
                  if image["kind"] == "image")
    assert figure["sha256"]
    assert figure["source_page"] == 1
    assert figure["caption_output_indexes"] == [1]
    assert figure["footnote_output_indexes"] == [2]

    table = next(image for image in accounting["images"]
                 if image["kind"] == "table")
    assert table["source_page"] == 3
    assert table["label"] == "Source-preserved table (untranslated)"
    assert table["caption_output_indexes"]
    identity = content["content_identity"]
    assert len(identity["paragraph_mapping_sha256"]) == 64
    assert identity["paragraph_count"] == content["paragraphs"]


def test_report_states_what_accounting_does_not_prove(tmp_path):
    _, accounting = _published(tmp_path)

    limitations = accounting["limitations"]
    assert limitations["recognition_accuracy_proven"] is False
    assert limitations["every_visible_word_translated"] is False
    assert any("does not prove recognition accuracy" in note.lower()
               for note in limitations["statements"])
    assert any("source-preserved" in note.lower()
               for note in limitations["statements"])
    assert accounting["claims"] == {
        "whole_book_coverage": True,
        "recognition_accuracy_proven": False,
        "every_visible_word_translated": False,
    }


def test_summary_exposes_coverage_and_stays_backward_compatible(tmp_path):
    output, accounting = _published(tmp_path)
    summary = read_accounting_summary(output)

    assert summary["coverage_complete"] is True
    assert summary["source_pages"] == 3
    assert summary["result_pages"] == 3
    assert summary["recognized_blocks"] == 6
    assert summary["accounted_blocks"] == 6
    assert summary["empty_pages"] == 1
    assert summary["excluded"] == 1
    assert summary["body_complete"] is True

    # An older v1 sidecar (no coverage fields) is still readable.
    legacy = {
        "schema_version": 1,
        "kind": "translated_pdf_accounting",
        "source": {"pages": 3},
        "recognition": {"pages": 3},
        "source_content": {"paragraphs": 4, "images": 1},
        "translation": {"failed_chunks": 0, "unfinished_chunks": 0,
                        "complete": True},
        "output": {"pages": 2, "bytes": output.stat().st_size},
    }
    _rewrite(output, legacy)
    legacy_summary = read_accounting_summary(output)
    assert legacy_summary["body_complete"] is True
    assert legacy_summary["source_pages"] == 3
    assert legacy_summary["coverage_complete"] is None
    assert legacy_summary["recognized_blocks"] is None


def test_summary_is_absent_when_the_output_no_longer_exists(tmp_path):
    output, _ = _published(tmp_path)
    output.unlink()

    assert read_accounting(output) is not None
    assert read_accounting_summary(output) is None


# ---------------------------------------------------------------------------
# Completion verdict: exactly the expected pages and blocks, or no completion
# ---------------------------------------------------------------------------


def test_a_whole_book_report_passes_the_completion_assessment(tmp_path):
    output, _ = _published(tmp_path)

    assessment = assess_pdf_completion(output)

    assert assessment.complete is True
    assert assessment.reason == ""


def test_a_missing_report_never_proves_completion(tmp_path):
    output = tmp_path / "missing-report.pdf"
    content = PdfPlainContent(
        paragraphs_text=["texte"], paragraphs_style=["normal"],
        paragraphs_format=[ParagraphFormat()], page_size=(600, 800),
        title="", author="", page_count=1)
    build_pdf(["FR: texte"], content, str(output), "French", "English")

    assessment = assess_pdf_completion(output)

    assert assessment.complete is False
    assert assessment.reason == "missing_report"


def test_a_missing_page_is_not_whole_book_completion(tmp_path):
    output, accounting = _published(tmp_path)
    accounting["coverage"]["pages"] = accounting["coverage"]["pages"][:2]
    accounting["coverage"]["mapped_source_pages"] = [1, 2]
    accounting["coverage"]["recognized_pages"] = 2
    accounting["coverage"]["complete"] = False
    _rewrite(output, accounting)

    assessment = assess_pdf_completion(output)

    assert assessment.complete is False
    assert assessment.reason == "coverage_incomplete"


def test_a_duplicate_page_mapping_is_not_whole_book_completion(tmp_path):
    output, accounting = _published(tmp_path)
    accounting["coverage"]["pages"][1]["source_page"] = 1
    accounting["coverage"]["mapped_source_pages"] = [1, 1, 3]
    accounting["coverage"]["complete"] = False
    _rewrite(output, accounting)

    assessment = assess_pdf_completion(output)

    assert assessment.complete is False
    assert assessment.reason == "coverage_incomplete"


def test_an_unaccounted_block_is_not_whole_book_completion(tmp_path):
    output, accounting = _published(tmp_path)
    accounting["source_content"]["blocks_accounted"] = 5
    accounting["source_content"]["blocks_unaccounted"] = 1
    accounting["coverage"]["accounted_blocks"] = 5
    accounting["coverage"]["unaccounted_blocks"] = 1
    accounting["coverage"]["complete"] = False
    _rewrite(output, accounting)

    assessment = assess_pdf_completion(output)

    assert assessment.complete is False
    assert assessment.reason == "coverage_incomplete"


def test_incomplete_body_translation_is_not_whole_book_completion(tmp_path):
    output, accounting = _published(tmp_path)
    accounting["translation"]["failed_chunks"] = 1
    accounting["translation"]["unfinished_chunks"] = 1
    accounting["translation"]["complete"] = False
    _rewrite(output, accounting)

    assessment = assess_pdf_completion(output)

    assert assessment.complete is False
    assert assessment.reason == "body_incomplete"


def test_a_report_for_different_output_bytes_is_stale(tmp_path):
    output, accounting = _published(tmp_path)
    accounting["output"]["sha256"] = "d" * 64
    _rewrite(output, accounting)

    assessment = assess_pdf_completion(output)

    assert assessment.complete is False
    assert assessment.reason == "output_mismatch"


def test_an_invalid_published_output_is_not_completion(tmp_path):
    output, _ = _published(tmp_path)
    output.write_bytes(b"not a pdf")

    assessment = assess_pdf_completion(output)

    assert assessment.complete is False
    assert assessment.reason == "output_invalid"


def test_the_completion_error_is_a_stable_localized_code():
    assert MineruCompletionInvalid.code == "mineru_completion_invalid"
