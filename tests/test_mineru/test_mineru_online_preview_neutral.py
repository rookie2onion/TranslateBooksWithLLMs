"""Preview-neutral source adaptation for the translated-book workflow (issue #19).

Seams under test:
- ``src.core.mineru.structure.adapt`` — canonical, preview-neutral source content.
- ``src.core.mineru.pdf_preview.build_pdf_preview`` and
  ``src.core.mineru.epub_preview.build_epub_preview`` — the existing preview
  artifacts, which must keep the preview notice and preview-only metadata.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from src.core.mineru.cache import load_cache
from src.core.mineru.epub_preview import build_epub_preview
from src.core.mineru.pdf_preview import build_pdf_preview
from src.core.mineru.structure import adapt
from tests.test_mineru.mineru_fixture import build_cache, default_pages

XHTML = "{http://www.w3.org/1999/xhtml}"
_BLOCK_TAGS = {f"{XHTML}h1", f"{XHTML}h2", f"{XHTML}h3", f"{XHTML}p"}


def _epub_block_texts(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            (name for name in archive.namelist() if name.startswith("OEBPS/text-")),
            key=lambda name: int(name.rsplit("-", 1)[1].split(".")[0]))
        documents = [ElementTree.fromstring(archive.read(name)) for name in names]
    return ["".join(element.itertext())
            for document in documents
            for element in document.iter()
            if element.tag in _BLOCK_TAGS]


def _load(tmp_path: Path, **kwargs):
    return load_cache(build_cache(tmp_path / "cache", **kwargs))


def test_adapt_returns_preview_neutral_source_content(tmp_path):
    source = adapt(_load(tmp_path, source_pages=[1, 19]))

    assert source.paragraphs[0] == "SAMPLE BOOK"
    assert source.styles[0] == "heading1"
    assert source.paragraphs[1] == "Ada Lovelace"
    assert "Untranslated MinerU reconstruction preview" not in "\n".join(source.paragraphs)
    assert source.title == "SAMPLE BOOK"
    assert source.counts["paragraphs"] == len(source.paragraphs) == 5

    first = source.provenance[0]
    assert (first.kind, first.output_index) == ("heading", 0)
    assert all(item.kind != "notice" for item in source.provenance)


def test_source_conversion_does_not_invent_an_author_or_preview_title(tmp_path):
    pages = default_pages()
    pages[0]["blocks"].insert(
        0, {"type": "paragraph", "text": "Grace Hopper", "bbox": [60, 40, 400, 60]})
    source = adapt(_load(tmp_path, pages=pages, source_pages=[1, 19]))

    content = source.to_plain_content()

    assert content.title == "SAMPLE BOOK"
    assert content.author == ""
    assert content.paragraphs_text == list(source.paragraphs)
    assert content.paragraphs_text[0] == "Grace Hopper"
    assert content.paragraphs_style == list(source.styles)
    assert content.paragraphs_format == list(source.formats)
    assert content.page_count == 2
    assert content.images_by_paragraph[2][0].data.startswith(b"\x89PNG")


def test_source_view_keeps_a_leading_image_before_the_first_text_paragraph(tmp_path):
    pages = default_pages()
    pages[0]["blocks"].insert(0, {
        "type": "image", "path": "images/fig2.jpg", "bbox": [60, 20, 940, 200],
        "caption": [{"type": "text", "content": "Frontispiece"}],
        "footnote": [{"type": "text", "content": "Frontispiece credit."}],
    })
    source = adapt(_load(tmp_path, pages=pages, source_pages=[1, 19]))

    assert source.paragraphs[0] == "Frontispiece"
    assert source.formats[0].italic is True
    assert source.paragraphs[1] == "Frontispiece credit."
    assert source.paragraphs[2] == "SAMPLE BOOK"
    assert source.styles[2] == "heading1"
    assert list(source.images_by_paragraph) == [-1, 3, 4]

    leading = source.images_by_paragraph[-1][0]
    assert leading.ext == "jpeg"
    assert (leading.source_page, leading.sample_page) == (1, 0)
    content = source.to_plain_content()
    assert content.images_by_paragraph[-1][0].ext == "jpeg"
    assert content.images_by_paragraph[-1][0].data.startswith(b"\xff\xd8")

    image_record = next(item for item in source.provenance
                        if item.kind == "image" and item.anchor_index == -1)
    assert image_record.image_path == "images/fig2.jpg"
    assert image_record.source_page == 1
    caption_record = next(item for item in source.provenance if item.kind == "caption")
    assert (caption_record.output_index, caption_record.source_type) == (0, "image_caption")
    assert any(item.kind == "footnote" and item.source_type == "page_footnote"
               for item in source.provenance)


def test_preview_artifacts_are_the_decorated_neutral_view(tmp_path):
    cache = _load(tmp_path, source_pages=[1, 19])
    source = adapt(cache)

    pdf = build_pdf_preview(cache, tmp_path / "pdf")
    epub = build_epub_preview(cache, tmp_path / "epub")

    provenance = json.loads(pdf.provenance_path.read_text(encoding="utf-8"))
    notice = provenance["artifact"]["notice"]
    assert notice.startswith("Untranslated MinerU reconstruction preview")
    assert provenance["counts"]["paragraphs"] == len(source.paragraphs) + 1
    assert provenance["counts"]["images"] == sum(
        len(assets) for assets in source.images_by_paragraph.values())

    paragraph_records = provenance["paragraphs"]
    neutral_paragraphs = [item for item in source.provenance
                          if item.output_index is not None]
    assert len(paragraph_records) == len(neutral_paragraphs) + 1
    assert (paragraph_records[0]["kind"], paragraph_records[0]["output_index"]) == (
        "notice", 0)
    for decorated, neutral in zip(paragraph_records[1:], neutral_paragraphs):
        assert decorated["kind"] == neutral.kind
        assert decorated["output_index"] == neutral.output_index + 1
        assert decorated["text_sha256"] == neutral.text_sha256
        assert decorated["source_page"] == neutral.source_page

    neutral_anchors = sorted(source.images_by_paragraph)
    assert [record["anchor_index"] for record in provenance["images"]] == [
        anchor + 1 for anchor in neutral_anchors]
    for decorated, anchor in zip(provenance["images"], neutral_anchors):
        assert decorated["image_sha256"] == source.images_by_paragraph[anchor][0].sha256

    assert _epub_block_texts(epub.epub_path) == [notice, *source.paragraphs]


def test_preview_metadata_keeps_the_suffix_and_inferred_author(tmp_path):
    import pymupdf

    pages = default_pages()
    pages[0]["blocks"].insert(
        0, {"type": "paragraph", "text": "Grace Hopper", "bbox": [60, 40, 400, 60]})
    cache = _load(tmp_path, pages=pages, source_pages=[1, 19])
    source = adapt(cache)
    assert source.to_plain_content().author == ""

    result = build_pdf_preview(cache, tmp_path / "pdf")

    with pymupdf.open(result.pdf_path) as document:
        assert document.metadata["author"] == "Grace Hopper"
        assert document.metadata["title"] == (
            "SAMPLE BOOK — untranslated MinerU sample preview")


def test_preview_outputs_are_stable_for_the_same_cache(tmp_path):
    import pymupdf

    cache = _load(tmp_path, source_pages=[1, 19])

    first = build_pdf_preview(cache, tmp_path / "first")
    second = build_pdf_preview(cache, tmp_path / "second")
    first_epub = build_epub_preview(cache, tmp_path / "first-epub")
    second_epub = build_epub_preview(cache, tmp_path / "second-epub")

    assert first_epub.epub_path.read_bytes() == second_epub.epub_path.read_bytes()
    assert first.provenance_path.read_bytes() == second.provenance_path.read_bytes()
    assert first_epub.provenance_path.read_bytes() == \
        second_epub.provenance_path.read_bytes()

    def snapshot(path: Path) -> tuple:
        with pymupdf.open(path) as document:
            return (document.metadata["title"], document.metadata["author"],
                    document.page_count,
                    [page.get_text() for page in document],
                    [len(page.get_images()) for page in document])

    assert snapshot(first.pdf_path) == snapshot(second.pdf_path)
