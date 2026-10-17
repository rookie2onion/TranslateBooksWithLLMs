"""Offline reconstruction of a cached MinerU online sample (issue #14).

Seams under test:
- A: ``src.core.mineru.cache.load_cache`` — cache validation and provenance binding.
- B: ``src.core.mineru.structure.adapt`` — content model, reading order, exclusions.
- C: ``src.core.mineru.pdf_preview.build_pdf_preview`` — real PDF plus provenance sidecar.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

from src.core.mineru.cache import MineruCacheError, load_cache
from src.core.mineru.pdf_preview import MineruExportError, build_pdf_preview
from src.core.mineru.structure import adapt
from tests.test_mineru.mineru_fixture import (
    SAMPLE_SHA256,
    SOURCE_SHA256,
    build_cache,
    default_pages,
    tree_fingerprint,
)


def _load(tmp_path: Path, **kwargs):
    return load_cache(build_cache(tmp_path / "cache", **kwargs))


def _edit_v2(root: Path, mutate) -> None:
    path = next(root.glob("*content_list_v2.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_cache_returns_pages_blocks_and_fingerprints(tmp_path):
    cache = _load(tmp_path, source_pages=[1, 19])

    assert [page.source_page for page in cache.pages] == [1, 19]
    assert [page.sample_index for page in cache.pages] == [0, 1]
    assert [(page.width_pt, page.height_pt) for page in cache.pages] == [(600.0, 800.0)] * 2
    assert cache.source_total_pages == 198
    assert cache.source_sha256 == SOURCE_SHA256
    assert cache.sample_sha256 == SAMPLE_SHA256

    assert [block.type for block in cache.blocks] == [
        "title", "paragraph", "image",
        "page_header", "paragraph", "paragraph", "image", "page_footnote", "page_number",
    ]
    first = cache.blocks[0]
    assert first.text == "SAMPLE BOOK"
    assert first.level == 1
    # V2 boxes are normalised to 0..1000; the cache exposes source-page points.
    assert first.bbox == pytest.approx((36.0, 64.0, 564.0, 112.0))

    image = cache.blocks[2]
    assert image.image_path is not None
    assert image.image_path.relative_to(cache.root).as_posix() == "images/fig1.png"
    assert cache.blocks[6].image_caption == ("Figure 1: a caption",)
    assert set(cache.fingerprints) == {
        "layout.json", "abc_content_list_v2.json", "sample-info.json",
        "images/fig1.png", "images/fig2.jpg",
    }


def test_load_cache_rejects_missing_layout(tmp_path):
    root = build_cache(tmp_path / "cache")
    (root / "layout.json").unlink()

    with pytest.raises(MineruCacheError, match="layout.json"):
        load_cache(root)


def test_load_cache_rejects_missing_image_file(tmp_path):
    root = build_cache(tmp_path / "cache")
    (root / "images" / "fig1.png").unlink()

    with pytest.raises(MineruCacheError, match="fig1.png"):
        load_cache(root)


def test_load_cache_rejects_image_path_escape(tmp_path):
    root = build_cache(tmp_path / "cache")
    _edit_v2(root, lambda pages: pages[0][2]["content"]["image_source"].update(
        path="../outside.png"))

    with pytest.raises(MineruCacheError, match="escapes the cache directory"):
        load_cache(root)


def test_load_cache_rejects_page_mapping_mismatch(tmp_path):
    root = build_cache(tmp_path / "cache", source_pages=[1])

    with pytest.raises(MineruCacheError, match="maps 1 source pages"):
        load_cache(root)


def test_load_cache_rejects_unsupported_block_type(tmp_path):
    root = build_cache(tmp_path / "cache")
    _edit_v2(root, lambda pages: pages[0][0].update(type="table"))

    with pytest.raises(MineruCacheError, match="unsupported type 'table'"):
        load_cache(root)


def test_adapt_preserves_order_roles_and_excludes_running_matter(tmp_path):
    reconstruction = adapt(_load(tmp_path, source_pages=[1, 19]))

    assert reconstruction.paragraphs[0].startswith(
        "Untranslated MinerU reconstruction preview")
    assert reconstruction.styles[1] == "heading1"
    assert reconstruction.paragraphs[1] == "SAMPLE BOOK"
    assert reconstruction.paragraphs[2] == "Ada Lovelace"
    assert list(reconstruction.images_by_paragraph) == [2, 3]

    body = reconstruction.paragraphs.index("The first body paragraph.")
    assert reconstruction.paragraphs[body + 1] == "Figure 1: a caption"
    assert reconstruction.formats[body + 1].italic is True
    assert "A substantive footnote." in reconstruction.paragraphs

    excluded = {item.text: item.reason for item in reconstruction.exclusions}
    assert "running header" in excluded["Chapter One"]
    assert "1 occurrence(s) in this sample" in excluded["Chapter One"]
    assert "19" in excluded
    assert any(item.kind == "empty_record" for item in reconstruction.exclusions)

    heading = next(item for item in reconstruction.provenance if item.kind == "heading")
    assert (heading.sample_page, heading.source_page) == (0, 1)
    body_index = reconstruction.paragraphs.index("The first body paragraph.")
    body_provenance = next(item for item in reconstruction.provenance
                           if item.output_index == body_index)
    assert body_provenance.source_page == 19
    assert body_provenance.source_type == "paragraph"


def test_adapt_keeps_numeric_top_band_paragraph_with_finding(tmp_path):
    pages = default_pages()
    pages[1]["blocks"].insert(
        0, {"type": "paragraph", "text": "7", "bbox": [80, 40, 110, 60]})

    reconstruction = adapt(_load(tmp_path, pages=pages, source_pages=[1, 19]))

    assert "7" in reconstruction.paragraphs
    finding = next(item for item in reconstruction.findings
                   if item.code == "possible_page_number")
    assert finding.sample_page == 1
    assert reconstruction.review_required is False


def test_adapt_exposes_image_assets_and_their_footnote(tmp_path):
    pages = default_pages()
    pages[1]["blocks"][3]["footnote"] = [{"type": "text", "content": "Image credit."}]

    reconstruction = adapt(_load(tmp_path, pages=pages, source_pages=[1, 19]))

    asset = reconstruction.images_by_paragraph[2][0]
    assert asset.data.startswith(b"\x89PNG")
    assert asset.ext == "png"
    assert (asset.width_pt, asset.height_pt) == pytest.approx((528.0, 320.0))
    assert "Image credit." in reconstruction.paragraphs
    assert reconstruction.counts["images"] == 2


def test_adapt_retains_recognised_image_text(tmp_path):
    pages = default_pages()
    pages[0]["blocks"][2]["text"] = "Text recognised inside the figure."

    reconstruction = adapt(_load(tmp_path, pages=pages, source_pages=[1, 19]))

    assert "Text recognised inside the figure." in reconstruction.paragraphs
    assert any(item.code == "image_content_retained" for item in reconstruction.findings)


def test_adapt_accounts_for_empty_running_blocks(tmp_path):
    pages = default_pages()
    pages[1]["blocks"].append(
        {"type": "page_number", "text": "", "bbox": [60, 500, 90, 520]})

    reconstruction = adapt(_load(tmp_path, pages=pages, source_pages=[1, 19]))

    assert reconstruction.counts["blocks_accounted"] == reconstruction.counts["blocks_seen"]
    assert reconstruction.counts["blocks_unaccounted"] == 0
    assert any(item.kind == "empty_record" and item.source_type == "page_number"
               for item in reconstruction.exclusions)


def test_adapt_maps_pages_and_counts_blocks(tmp_path):
    cache = _load(tmp_path, source_pages=[1, 19])

    reconstruction = adapt(cache)

    assert [page.source_page for page in reconstruction.page_map] == [1, 19]
    assert reconstruction.counts["blocks_seen"] == len(cache.blocks)
    assert reconstruction.counts["blocks_accounted"] == len(cache.blocks)
    assert reconstruction.counts["blocks_unaccounted"] == 0
    assert reconstruction.counts["images"] == 2
    assert reconstruction.counts["excluded"] == len(reconstruction.exclusions)


def test_build_pdf_preview_writes_pdf_and_provenance(tmp_path):
    import pymupdf

    cache = _load(tmp_path, source_pages=[1, 19])

    result = build_pdf_preview(cache, tmp_path / "out")

    assert result.pdf_path.is_file() and result.pdf_path.stat().st_size > 0
    assert result.provenance_path.is_file()
    with pymupdf.open(result.pdf_path) as document:
        assert document.page_count >= 1
        # The serif font applies typographic ligatures; normalise them for comparison.
        text = unicodedata.normalize("NFKC", "\n".join(page.get_text() for page in document))
        images = sum(len(page.get_images()) for page in document)
        assert document.metadata["title"].endswith("untranslated MinerU sample preview")
    assert "Untranslated MinerU reconstruction preview" in text
    assert "SAMPLE BOOK" in text
    assert "The first body paragraph." in text
    assert "Figure 1: a caption" in text
    assert "A substantive footnote." in text
    assert "Chapter One" not in text
    assert "not a complete book" in text
    assert images >= 2

    provenance = json.loads(result.provenance_path.read_text(encoding="utf-8"))
    assert provenance["schema_version"] == 1
    assert provenance["artifact"]["translated"] is False
    assert provenance["artifact"]["complete_book"] is False
    assert provenance["counts"]["blocks_seen"] == 9
    assert provenance["counts"]["blocks_accounted"] == 9
    assert [page["source_page"] for page in provenance["page_map"]] == [1, 19]
    assert "Chapter One" in [item["text"] for item in provenance["exclusions"]]
    assert provenance["source"]["sample_sha256"] == SAMPLE_SHA256
    assert result.page_count == provenance["pdf"]["page_count"]
    image_record = provenance["images"][0]
    assert image_record["image_path"] == "images/fig1.png"
    assert len(image_record["image_sha256"]) == 64


def test_build_pdf_preview_never_opens_a_network_socket(tmp_path, monkeypatch):
    import socket

    def _refuse(*args, **kwargs):
        raise AssertionError("reconstruction attempted network access")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    cache = _load(tmp_path, source_pages=[1, 19])

    result = build_pdf_preview(cache, tmp_path / "out")

    assert result.pdf_path.is_file()


def test_build_pdf_preview_leaves_the_cache_byte_identical(tmp_path):
    root = build_cache(tmp_path / "cache", source_pages=[1, 19])
    before = tree_fingerprint(root)
    cache = load_cache(root)

    build_pdf_preview(cache, tmp_path / "out")

    assert tree_fingerprint(root) == before


def test_build_pdf_preview_refuses_to_write_inside_the_cache(tmp_path):
    cache = _load(tmp_path, source_pages=[1, 19])

    with pytest.raises(MineruExportError, match="inside the cache"):
        build_pdf_preview(cache, cache.root / "out")


def test_build_pdf_preview_flags_review_when_structure_is_suspect(tmp_path):
    pages = default_pages()
    pages[1]["blocks"][0]["bbox"] = [600, 400, 900, 420]  # header in the body area
    cache = _load(tmp_path, pages=pages, source_pages=[1, 19])

    result = build_pdf_preview(cache, tmp_path / "out")

    provenance = json.loads(result.provenance_path.read_text(encoding="utf-8"))
    assert result.review_required is True
    assert provenance["review_required"] is True
    codes = [finding["code"] for finding in provenance["findings"]]
    assert "header_outside_top_margin" in codes
