"""Accounting and rendering of source-preserved table/formula content (#22).

Seams under test:
- ``src.core.pdf.builder.build_pdf`` — embeds the supplied source image, renders
  the untranslated label, and never redraws table cells or formula LaTeX as text.
- ``src.core.pdf.accounting`` — separates source-preserved blocks from figures,
  translated paragraphs and failed translation chunks in the durable sidecar and
  the browser-safe summary.

The adapter and loader are the real ones; the document is a synthetic V2 cache.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pymupdf
from PIL import Image

from src.core.mineru.cache import load_cache
from src.core.mineru.structure import PRESERVED_LABELS, adapt
from src.core.pdf.accounting import (
    ACCOUNTING_SCHEMA_VERSION,
    build_accounting,
    read_accounting_summary,
    validate_pdf_output,
    write_accounting_sidecar,
)
from src.core.pdf.builder import build_pdf
from tests.test_mineru.mineru_fixture import build_cache, equation_block, table_block


def _pages():
    return [
        {"blocks": [
            table_block("images/table1.png", [60, 80, 940, 300],
                        caption="Table 1: Revenue",
                        footnote="Source: annual report",
                        html="<table><tr><td>CONFIDENTIAL CELL TEXT</td></tr></table>",
                        color=(10, 80, 160)),
            {"type": "paragraph", "text": "Intro paragraph.",
             "bbox": [60, 340, 540, 400]},
            {"type": "image", "path": "images/fig1.png",
             "bbox": [60, 420, 540, 600],
             "caption": [{"type": "text", "content": "A figure caption"}]},
        ]},
        {"blocks": [
            {"type": "paragraph", "text": "Before the formula.",
             "bbox": [60, 80, 540, 140]},
            equation_block("images/eq1.png", [200, 180, 800, 260],
                           math="E = mc^2", color=(200, 40, 40)),
            {"type": "paragraph", "text": "After the formula.",
             "bbox": [60, 300, 540, 360]},
        ]},
    ]


def _source(tmp_path: Path):
    cache = load_cache(build_cache(tmp_path / "cache", pages=_pages(),
                                   source_pages=[1, 2]))
    return cache, adapt(cache)


def _render(tmp_path: Path, source) -> Path:
    content = source.to_plain_content()
    translated = [f"FR: {text}" for text in content.paragraphs_text]
    output = tmp_path / "book (French).pdf"
    build_pdf(translated, content, str(output), "French", "English")
    return output


def _pdf_text(path: Path) -> str:
    with pymupdf.open(path) as document:
        return " ".join(" ".join(page.get_text() for page in document).split())


def _pixel(document, xref: int) -> tuple[int, int, int]:
    extracted = document.extract_image(xref)
    with Image.open(io.BytesIO(extracted["image"])) as image:
        image = image.convert("RGB")
        return image.getpixel((image.width // 2, image.height // 2))


def _recognition(cache, source):
    return SimpleNamespace(
        admitted=SimpleNamespace(file_name="source.pdf", sha256="a" * 64,
                                 size_bytes=1234, page_count=2),
        cache=cache,
        source=source,
        batch_id="batch-abc123",
        result_zip_sha256="b" * 64,
        result_cache_sha256="c" * 64,
        page_count=2,
        elapsed_seconds=12.5,
        retries=0,
        remote_states=("pending", "done"),
        reused=False,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_preserved_blocks_are_embedded_as_supplied_images_with_untranslated_labels(tmp_path):
    cache, source = _source(tmp_path)
    output = _render(tmp_path, source)
    text = _pdf_text(output)

    # Independent captions and notes are translated normally.
    assert "FR: Table 1: Revenue" in text
    assert "FR: Source: annual report" in text
    assert "FR: Intro paragraph." in text
    assert "FR: Before the formula." in text
    assert "FR: After the formula." in text

    # Every source-preserved block is visibly identified as untranslated, and
    # that identification is never sent through the translator.
    assert PRESERVED_LABELS["table"] in text
    assert PRESERVED_LABELS["formula"] in text
    assert f"FR: {PRESERVED_LABELS['table']}" not in text
    assert f"FR: {PRESERVED_LABELS['formula']}" not in text

    # No pixel text is redrawn and no semantic/editable table is promised.
    assert "CONFIDENTIAL CELL TEXT" not in text
    assert "E = mc^2" not in text


def test_the_original_image_pixels_survive_in_the_pdf(tmp_path):
    cache, source = _source(tmp_path)
    output = _render(tmp_path, source)

    with pymupdf.open(output) as document:
        xrefs = [item["xref"] for page in document
                 for item in page.get_image_info(xrefs=True)]
        assert len(xrefs) == 3
        colours = {_pixel(document, xref) for xref in xrefs}
        assert colours == {(10, 80, 160), (200, 30, 30), (200, 40, 40)}


def test_a_leading_preserved_block_stays_before_the_first_body_paragraph(tmp_path):
    cache, source = _source(tmp_path)
    output = _render(tmp_path, source)
    text = _pdf_text(output)

    assert text.index(PRESERVED_LABELS["table"]) < text.index("FR: Intro paragraph.")
    assert text.index(PRESERVED_LABELS["table"]) < text.index(
        "FR: Table 1: Revenue")


def test_an_ordinary_translated_book_without_preserved_content_has_no_labels(tmp_path):
    pages = [{"blocks": [
        {"type": "paragraph", "text": "Only text.", "bbox": [60, 80, 540, 140]},
        {"type": "image", "path": "images/fig1.png", "bbox": [60, 160, 540, 400]},
    ]}]
    cache = load_cache(build_cache(tmp_path / "cache", pages=pages, source_pages=[1]))
    source = adapt(cache)
    output = _render(tmp_path, source)
    text = _pdf_text(output)

    assert "FR: Only text." in text
    assert "Source-preserved" not in text
    assert source.counts["source_preserved"] == 0


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------


def test_accounting_counts_source_preserved_content_separately(tmp_path):
    cache, source = _source(tmp_path)
    output = _render(tmp_path, source)
    content = source.to_plain_content()
    output_stats = validate_pdf_output(
        output, expected_title=content.title, expected_author="",
        expected_paragraphs=len(content.paragraphs_text))

    accounting = build_accounting(
        recognition=_recognition(cache, source), content=content,
        translation_stats={"total_chunks": 4, "completed_chunks": 3,
                           "failed_chunks": 1, "fallback_used": 0},
        output_stats=output_stats, output_filename=output.name,
        source_language="English", target_language="French", bilingual=False,
        budget_seconds=300,
    )

    assert accounting["schema_version"] == ACCOUNTING_SCHEMA_VERSION == 1
    source_content = accounting["source_content"]
    assert source_content["paragraphs"] == 6
    assert source_content["images"] == 1
    assert source_content["source_preserved"] == 2
    assert source_content["tables"] == 1
    assert source_content["formulas"] == 1
    assert source_content["captions"] == 2
    assert source_content["footnotes"] == 1

    translation = accounting["translation"]
    assert translation["failed_chunks"] == 1
    assert translation["unfinished_chunks"] == 1
    assert translation["complete"] is False
    # The policy counters never absorb translation failures, and vice versa.
    assert source_content["source_preserved"] != translation["failed_chunks"]


def test_the_summary_exposes_the_separated_counts_to_the_task_workflow(tmp_path):
    cache, source = _source(tmp_path)
    output = _render(tmp_path, source)
    content = source.to_plain_content()
    output_stats = validate_pdf_output(
        output, expected_title=content.title, expected_author="",
        expected_paragraphs=len(content.paragraphs_text))
    accounting = build_accounting(
        recognition=_recognition(cache, source), content=content,
        translation_stats={"total_chunks": 2, "completed_chunks": 2,
                           "failed_chunks": 0},
        output_stats=output_stats, output_filename=output.name,
        source_language="English", target_language="French", bilingual=False,
        budget_seconds=300,
    )

    sidecar = write_accounting_sidecar(output, accounting)
    assert json.loads(sidecar.read_text(encoding="utf-8"))["kind"] == (
        "translated_pdf_accounting")

    summary = read_accounting_summary(output)
    assert summary["source_preserved"] == 2
    assert summary["tables"] == 1
    assert summary["formulas"] == 1
    assert summary["images"] == 1
    assert summary["failed_chunks"] == 0
    assert summary["body_complete"] is True
