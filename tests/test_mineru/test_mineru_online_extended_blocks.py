"""Contract-shaped regressions for blocks observed in whole-book V2 results."""
import json

import pytest

from src.core.mineru.cache import MineruCacheError, load_cache
from src.core.mineru.structure import adapt
from tests.test_mineru.mineru_fixture import build_cache


def _reference_list():
    return {"type": "list", "bbox": [60, 80, 940, 300], "content": {
        "list_type": "reference_list", "list_items": [
            {"item_type": "text", "item_content": [
                {"type": "text", "content": "First reference."}]},
            {"item_type": "text", "item_content": [
                {"type": "text", "content": "Second "},
                {"type": "text", "content": "reference."}]},
        ]}}


def _cache(tmp_path, blocks):
    root = build_cache(tmp_path / "cache", pages=[{"blocks": [
        {"type": "paragraph", "text": "Fixture", "bbox": [60, 80, 940, 300]}
    ]}], source_pages=[1], total_pages=1)
    path = next(root.glob("*content_list_v2.json"))
    path.write_text(json.dumps([blocks]), encoding="utf-8")
    return root


def test_reference_items_and_aside_are_retained_in_order_and_accounted(tmp_path):
    root = _cache(tmp_path, [_reference_list(), {
        "type": "page_aside_text", "bbox": [10, 100, 50, 300],
        "content": {"page_aside_text_content": [
            {"type": "text", "content": "Substantive margin note."}]}}])
    source = adapt(load_cache(root))
    assert source.paragraphs == (
        "First reference.", "Second reference.", "Substantive margin note.")
    assert [item.source_type for item in source.provenance] == [
        "list", "list", "page_aside_text"]
    assert source.counts["blocks_accounted"] == source.counts["blocks_seen"] == 2
    assert not source.exclusions


def test_chart_preserves_image_and_translates_caption_note_and_recognized_text(tmp_path):
    root = _cache(tmp_path, [{"type": "chart", "bbox": [60, 80, 940, 600],
        "content": {"image_source": {"path": "images/fig1.png"},
                    "content": "Recognized chart text.",
                    "chart_caption": [{"type": "text", "content": "Chart caption."}],
                    "chart_footnote": [{"type": "text", "content": "Chart source."}]}}])
    source = adapt(load_cache(root))
    assert source.paragraphs == (
        "Chart caption.", "Chart source.", "Recognized chart text.")
    assert source.images_by_paragraph[-1][0].data == (root / "images/fig1.png").read_bytes()
    assert [item.source_type for item in source.provenance] == [
        "chart", "chart_caption", "chart_footnote", "chart_content"]
    assert source.counts["images"] == 1
    assert source.counts["blocks_accounted"] == 1


@pytest.mark.parametrize("change", [
    lambda content: content.update(list_type="unverified_list"),
    lambda content: content.update(list_items="not an array"),
    lambda content: content["list_items"][0].update(item_type="unverified_item"),
    lambda content: content["list_items"][0].pop("item_content"),
    lambda content: content["list_items"][0].update(item_content="not runs"),
    lambda content: content["list_items"][0]["item_content"][0].update(type="unknown_span"),
    lambda content: content["list_items"][0]["item_content"][0].update(type="equation_inline"),
])
def test_unverified_or_malformed_list_content_fails_closed(tmp_path, change):
    block = _reference_list()
    change(block["content"])
    with pytest.raises(MineruCacheError):
        load_cache(_cache(tmp_path, [block]))


def test_reference_list_obeys_block_text_budget(tmp_path, monkeypatch):
    import src.core.mineru.cache as cache_module

    root = _cache(tmp_path, [_reference_list()])
    monkeypatch.setattr(cache_module, "MAX_BLOCK_TEXT", 5)
    with pytest.raises(MineruCacheError, match="text exceeds"):
        load_cache(root)


def test_empty_reference_list_has_explicit_exclusion(tmp_path):
    block = _reference_list()
    block["content"]["list_items"] = []
    source = adapt(load_cache(_cache(tmp_path, [block])))
    assert source.counts["blocks_accounted"] == 1
    assert source.exclusions[0].kind == "empty_record"


def _original(root):
    from src.utils.hashing import sha256_file

    pdf = root / "sample.pdf"
    path = root / "sample-info.json"
    info = json.loads(path.read_text())
    info["sample_sha256"] = sha256_file(pdf)
    path.write_text(json.dumps(info))
    return pdf


def _inline():
    return {"type": "paragraph", "bbox": [0, 0, 1000, 500], "content": {
        "paragraph_content": [{"type": "text", "content": "Entire paragraph: "},
                              {"type": "equation_inline", "content": "E=mc^2"}]}}


def test_source_crop_is_fingerprinted_and_detects_tampering(tmp_path):
    root = _cache(tmp_path, [_inline()])
    original = _original(root)
    first = load_cache(root, source_pdf=original)
    second = load_cache(root, source_pdf=original)
    assert first.fingerprints == second.fingerprints
    block = first.blocks[0]
    assert block.preservation_reason == "inline_formula_paragraph"
    assert block.image_path.relative_to(root).as_posix() in first.fingerprints
    block.image_path.write_bytes(b"tampered")
    with pytest.raises(MineruCacheError, match="does not match the original"):
        load_cache(root, source_pdf=original)


def test_source_crop_requires_matching_original_fingerprint(tmp_path):
    root = _cache(tmp_path, [_inline()])
    with pytest.raises(MineruCacheError, match="fingerprint"):
        load_cache(root, source_pdf=root / "sample.pdf")


def test_table_directory_placeholder_is_cropped_but_missing_file_is_rejected(tmp_path):
    block = {"type": "table", "bbox": [60, 80, 940, 600], "content": {
        "image_source": {"path": "images/"}, "html": "<table></table>",
        "table_type": "simple_table", "table_nest_level": 1,
        "table_caption": [], "table_footnote": []}}
    root = _cache(tmp_path, [block])
    original = _original(root)
    source = adapt(load_cache(root, source_pdf=original))
    assert source.counts["tables"] == source.counts["source_preserved"] == 1
    assert source.findings[0].code == "table_source_crop"
    block["content"]["image_source"]["path"] = "images/missing.png"
    next(root.glob("*content_list_v2.json")).write_text(json.dumps([[block]]))
    with pytest.raises(MineruCacheError, match="missing image"):
        load_cache(root, source_pdf=original)


def test_malformed_inline_formula_is_not_hidden_by_source_crop(tmp_path):
    block = _inline()
    block["content"]["paragraph_content"][1]["content"] = {"unexpected": "object"}
    root = _cache(tmp_path, [block])
    with pytest.raises(MineruCacheError, match="invalid inline-formula"):
        load_cache(root, source_pdf=_original(root))


def test_source_crop_respects_displayed_page_rotation(tmp_path):
    import pymupdf
    from PIL import Image

    root = _cache(tmp_path, [_inline()])
    original = root / "sample.pdf"
    with pymupdf.open(original) as document:
        page = document[0]
        page.draw_rect(pymupdf.Rect(0, 0, page.rect.width / 2, page.rect.height / 2),
                       color=None, fill=(1, 0, 0))
        page.set_rotation(90)
        size = [page.rect.width, page.rect.height]
        document.saveIncr()
    layout_path = root / "layout.json"
    layout = json.loads(layout_path.read_text())
    layout["pdf_info"][0]["page_size"] = size
    layout_path.write_text(json.dumps(layout))
    block = load_cache(root, source_pdf=_original(root)).blocks[0]
    with Image.open(block.image_path) as crop:
        assert crop.size == (int(size[0] * 2), int(size[1]))
        assert crop.getpixel((crop.width - 2, 2)) == (255, 0, 0)
        assert crop.getpixel((2, 2)) == (255, 255, 255)


def test_source_crop_refuses_excessive_raster_size(tmp_path, monkeypatch):
    import src.core.mineru.cache as cache_module

    root = _cache(tmp_path, [_inline()])
    original = _original(root)
    monkeypatch.setattr(cache_module, "MAX_IMAGE_PIXELS", 1)
    with pytest.raises(MineruCacheError, match="pixel budget"):
        load_cache(root, source_pdf=original)
