"""Loader and adapter coverage for source-preserved table/formula content (#22).

Seams under test:
- ``src.core.mineru.cache.load_cache`` — the V2 contract shapes for
  ``table`` and ``equation_interline`` blocks, their supplied source images and
  fingerprints.
- ``src.core.mineru.structure.adapt`` — reading position, caption/footnote
  association, provenance, separated counters and the untranslated label that
  reaches the shared PDF content model.

Contract evidence
-----------------
The online service answered with ``_version_name: 3.4.4`` (observed in the
authorized probe recorded by issue #20). Its V2 content list is rendered by
``mineru/backend/vlm/vlm_middle_json_mkcontent.py:make_blocks_to_content_list_v2``
in MinerU 3.4.4:

- ``{"type": "table", "content": {"image_source": {"path": ...},
  "table_caption": [spans], "table_footnote": [spans], "html": str,
  "table_type": "simple_table" | "complex_table", "table_nest_level": int}}``
- ``{"type": "equation_interline", "content": {"math_content": str,
  "math_type": "latex", "image_source": {"path": ...}}}``
- inline formulas are ``equation_inline`` runs inside a text block's span list.

The same release's ``mineru/utils/enum_class.py:ContentTypeV2`` names those
values.  The unsupported shapes below (unknown block types, unknown run types,
non-LaTeX formula variants, inline formula runs without a verified preservation
path) stay fail-closed rather than becoming an accept-anything parser.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core.mineru.cache import MineruCacheError, load_cache
from src.core.mineru.structure import PRESERVED_LABELS, adapt, apply_preview_decoration
from tests.test_mineru.mineru_fixture import (
    build_cache,
    default_pages,
    equation_block,
    table_block,
)


def _load(tmp_path: Path, pages, *, source_pages=None, total_pages=198):
    source_pages = source_pages or list(range(1, len(pages) + 1))
    root = build_cache(tmp_path / "cache", pages=pages, source_pages=source_pages,
                       total_pages=total_pages)
    return load_cache(root)


def _edit_v2(root: Path, mutate) -> None:
    path = next(root.glob("*content_list_v2.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def _table_page(**kwargs):
    return {"blocks": [table_block(
        "images/table1.png", [60, 80, 940, 400],
        caption="Table 1: Revenue", footnote="Source: annual report",
        html="<table><tr><td>CONFIDENTIAL CELL TEXT</td></tr></table>",
        **kwargs)]}


def _mixed_pages():
    """A leading table, ordinary text, an interline formula and a figure."""
    return [
        {"blocks": [
            table_block("images/table1.png", [60, 80, 940, 300],
                        caption="Table 1: Revenue",
                        footnote="Source: annual report",
                        html="<table><tr><td>CONFIDENTIAL CELL TEXT</td></tr></table>",
                        color=(10, 80, 160)),
            {"type": "paragraph", "text": "Intro paragraph.",
             "bbox": [60, 340, 540, 400]},
        ]},
        {"blocks": [
            {"type": "paragraph", "text": "Before the formula.",
             "bbox": [60, 80, 540, 140]},
            equation_block("images/eq1.png", [200, 180, 800, 260],
                           math="E = mc^2", color=(200, 40, 40)),
            {"type": "paragraph", "text": "After the formula.",
             "bbox": [60, 300, 540, 360]},
            {"type": "image", "path": "images/fig1.png",
             "bbox": [60, 400, 540, 600],
             "caption": [{"type": "text", "content": "A figure caption"}]},
        ]},
    ]


# ---------------------------------------------------------------------------
# Loader: the verified V2 table/formula contract
# ---------------------------------------------------------------------------


def test_a_v2_table_block_loads_its_supplied_image_caption_and_footnote(tmp_path):
    cache = _load(tmp_path, [_table_page()])

    block = cache.blocks[0]
    assert block.type == "table"
    assert block.image_path is not None
    assert block.image_path.name == "table1.png"
    assert block.table_caption == ("Table 1: Revenue",)
    assert block.table_footnote == ("Source: annual report",)
    assert block.table_type == "simple_table"
    assert block.table_nest_level == 1
    assert block.text == ""
    assert "images/table1.png" in cache.fingerprints


def test_a_v2_interline_equation_loads_its_supplied_image_and_latex(tmp_path):
    pages = [{"blocks": [equation_block(
        "images/eq1.png", [200, 180, 800, 260], math="E = mc^2")]}]
    cache = _load(tmp_path, pages)

    block = cache.blocks[0]
    assert block.type == "equation_interline"
    assert block.image_path is not None and block.image_path.name == "eq1.png"
    assert block.math_content == "E = mc^2"
    assert block.math_type == "latex"
    assert "images/eq1.png" in cache.fingerprints


def test_a_complex_table_is_still_preserved_as_its_supplied_image(tmp_path):
    pages = [_table_page(table_type="complex_table", nest_level=2)]
    cache = _load(tmp_path, pages)

    block = cache.blocks[0]
    assert block.table_type == "complex_table"
    assert block.table_nest_level == 2
    assert block.image_path is not None


def test_a_table_without_the_contracted_html_key_fails_explicitly(tmp_path):
    root = build_cache(tmp_path / "cache", pages=[_table_page()],
                       source_pages=[1])
    _edit_v2(root, lambda pages: pages[0][0]["content"].pop("html"))

    with pytest.raises(MineruCacheError, match="html"):
        load_cache(root)


def test_a_formula_with_an_unverified_math_type_fails_explicitly(tmp_path):
    root = build_cache(tmp_path / "cache", pages=[{"blocks": [equation_block(
        "images/eq1.png", [200, 180, 800, 260], math_type="mathml")]}],
        source_pages=[1])

    with pytest.raises(MineruCacheError, match="math_type"):
        load_cache(root)


# ---------------------------------------------------------------------------
# Loader: asset and geometry bounds stay enforced
# ---------------------------------------------------------------------------


def test_an_absent_supplied_asset_fails_instead_of_cropping_speculatively(tmp_path):
    root = build_cache(tmp_path / "cache", pages=[_table_page()], source_pages=[1])
    (root / "images" / "table1.png").unlink()

    with pytest.raises(MineruCacheError, match="missing image"):
        load_cache(root)


def test_a_preserved_block_without_any_supplied_asset_fails_explicitly(tmp_path):
    root = build_cache(tmp_path / "cache", pages=[_table_page()], source_pages=[1])
    _edit_v2(root, lambda pages: pages[0][0]["content"].pop("image_source"))

    with pytest.raises(MineruCacheError, match="image_source"):
        load_cache(root)


def test_degenerate_preserved_bounds_fail_explicitly(tmp_path):
    root = build_cache(
        tmp_path / "cache",
        pages=[{"blocks": [table_block("images/table1.png", [100, 100, 100, 300])]}],
        source_pages=[1],
    )

    with pytest.raises(MineruCacheError, match="empty|bounds"):
        load_cache(root)


def test_preserved_bounds_outside_the_normalised_square_fail_explicitly(tmp_path):
    root = build_cache(
        tmp_path / "cache",
        pages=[{"blocks": [table_block("images/table1.png", [0, 0, 1001, 500])]}],
        source_pages=[1],
    )

    with pytest.raises(MineruCacheError, match="outside the normalised"):
        load_cache(root)


def test_a_preserved_asset_with_an_unsupported_extension_fails_explicitly(tmp_path):
    root = build_cache(
        tmp_path / "cache",
        pages=[{"blocks": [table_block("images/table1.webp", [60, 80, 940, 400])]}],
        source_pages=[1],
    )

    with pytest.raises(MineruCacheError, match="unsupported extension"):
        load_cache(root)


def test_a_preserved_asset_path_escaping_the_cache_fails_explicitly(tmp_path):
    root = build_cache(
        tmp_path / "cache",
        pages=[{"blocks": [table_block("../outside.png", [60, 80, 940, 400])]}],
        source_pages=[1],
    )

    with pytest.raises(MineruCacheError, match="escapes the cache directory"):
        load_cache(root)


# ---------------------------------------------------------------------------
# Loader: unknown structures stay fail-closed
# ---------------------------------------------------------------------------


def test_an_unknown_block_type_still_fails_closed(tmp_path):
    pages = default_pages()
    pages[0]["blocks"].append({"type": "unknown_block", "text": "", "bbox": [60, 60, 300, 300]})

    with pytest.raises(MineruCacheError, match="unsupported type 'unknown_block'"):
        _load(tmp_path, pages)


def test_an_inline_formula_run_fails_explicitly_as_unsupported(tmp_path):
    pages = [{"blocks": [
        {"type": "paragraph", "text": "Energy is conserved.",
         "bbox": [60, 80, 540, 140]},
    ]}]
    root = build_cache(tmp_path / "cache", pages=pages, source_pages=[1])
    _edit_v2(root, lambda pages: pages[0][0]["content"].update(
        paragraph_content=[
            {"type": "text", "content": "Energy is conserved: "},
            {"type": "equation_inline", "content": "E = mc^2"},
        ]))

    with pytest.raises(MineruCacheError, match="inline formula"):
        load_cache(root)


def test_an_inline_formula_in_a_table_caption_fails_explicitly(tmp_path):
    root = build_cache(tmp_path / "cache", pages=[_table_page()], source_pages=[1])
    _edit_v2(root, lambda pages: pages[0][0]["content"].update(
        table_caption=[{"type": "equation_inline", "content": "x = 1"}]))

    with pytest.raises(MineruCacheError, match="inline formula"):
        load_cache(root)


def test_an_unknown_span_type_fails_closed(tmp_path):
    root = build_cache(tmp_path / "cache", pages=[_table_page()], source_pages=[1])
    _edit_v2(root, lambda pages: pages[0][0]["content"].update(
        table_caption=[{"type": "md", "content": "**bold**"}]))

    with pytest.raises(MineruCacheError, match="unsupported span type"):
        load_cache(root)


# ---------------------------------------------------------------------------
# Adapter: reading position, associations, provenance and counters
# ---------------------------------------------------------------------------


def test_preserved_blocks_keep_their_reading_position_before_and_between_text(tmp_path):
    source = adapt(_load(tmp_path, _mixed_pages(), source_pages=[1, 19]))

    # Leading table: its anchored image precedes every paragraph (-1), and its
    # caption/footnote are emitted into the reading order right after it.
    assert source.paragraphs[0] == "Table 1: Revenue"
    assert source.paragraphs[1] == "Source: annual report"
    assert source.paragraphs[2] == "Intro paragraph."
    assert list(source.images_by_paragraph) == [-1, 3, 4]

    leading = source.images_by_paragraph[-1][0]
    assert leading.kind == "table"
    assert leading.to_pdf_image().label == PRESERVED_LABELS["table"]

    before_formula = source.paragraphs.index("Before the formula.")
    assert source.paragraphs[before_formula + 1] == "After the formula."
    formula = source.images_by_paragraph[before_formula][0]
    assert formula.kind == "formula"
    assert formula.to_pdf_image().label == PRESERVED_LABELS["formula"]


def test_table_caption_and_footnote_keep_their_association_and_provenance(tmp_path):
    source = adapt(_load(tmp_path, _mixed_pages(), source_pages=[1, 19]))

    caption = source.provenance[1]
    assert (caption.kind, caption.source_type) == ("caption", "table_caption")
    footnote = source.provenance[2]
    assert (footnote.kind, footnote.source_type) == ("footnote", "table_footnote")

    table_record = next(item for item in source.provenance if item.kind == "table")
    assert table_record.anchor_index == -1
    assert table_record.image_path == "images/table1.png"
    assert len(table_record.image_sha256 or "") == 64
    assert table_record.source_page == 1


def test_preserved_blocks_map_to_their_source_page(tmp_path):
    source = adapt(_load(tmp_path, _mixed_pages(), source_pages=[1, 19]))

    table = next(item for item in source.provenance if item.kind == "table")
    formula = next(item for item in source.provenance if item.kind == "formula")
    assert (table.sample_page, table.source_page) == (0, 1)
    assert (formula.sample_page, formula.source_page) == (1, 19)
    assert source.images_by_paragraph[-1][0].source_page == 1
    assert source.images_by_paragraph[3][0].source_page == 19


def test_repeated_asset_instances_stay_at_every_reading_position(tmp_path):
    pages = [
        {"blocks": [
            {"type": "paragraph", "text": "First.", "bbox": [60, 60, 540, 100]},
            table_block("images/shared.png", [60, 120, 540, 300]),
        ]},
        {"blocks": [
            {"type": "paragraph", "text": "Second.", "bbox": [60, 60, 540, 100]},
            table_block("images/shared.png", [60, 120, 540, 300]),
        ]},
    ]
    cache = _load(tmp_path, pages, source_pages=[1, 19])
    source = adapt(cache)

    occurrences = [asset for assets in source.images_by_paragraph.values()
                   for asset in assets if asset.kind == "table"]
    assert len(occurrences) == 2
    assert len({asset.sha256 for asset in occurrences}) == 1
    assert [key for key in source.images_by_paragraph] == [0, 1]
    assert sum(1 for key in cache.fingerprints if key == "images/shared.png") == 1


def test_counts_separate_source_preserved_content_from_images_and_paragraphs(tmp_path):
    source = adapt(_load(tmp_path, _mixed_pages(), source_pages=[1, 19]))

    assert source.counts["paragraphs"] == len(source.paragraphs) == 6
    assert source.counts["images"] == 1
    assert source.counts["source_preserved"] == 2
    assert source.counts["tables"] == 1
    assert source.counts["formulas"] == 1
    assert source.counts["blocks_seen"] == source.counts["blocks_accounted"] == 6
    assert source.counts["blocks_unaccounted"] == 0


def test_the_shared_content_model_carries_the_untranslated_label(tmp_path):
    source = adapt(_load(tmp_path, _mixed_pages(), source_pages=[1, 19]))
    content = source.to_plain_content()

    leading = content.images_by_paragraph[-1][0]
    assert leading.label == PRESERVED_LABELS["table"]
    assert leading.data.startswith(b"\x89PNG")
    formula_anchor = max(key for key in content.images_by_paragraph
                         if content.images_by_paragraph[key][0].label
                         == PRESERVED_LABELS["formula"])
    assert content.images_by_paragraph[formula_anchor][0].label == \
        PRESERVED_LABELS["formula"]
    figure = next(image for images in content.images_by_paragraph.values()
                  for image in images if image.label == "")
    assert figure.ext == "png"


def test_preview_decoration_shifts_preserved_anchors_without_dropping_them(tmp_path):
    cache = _load(tmp_path, _mixed_pages(), source_pages=[1, 19])
    source = adapt(cache)
    decorated = apply_preview_decoration(cache, source)

    assert list(decorated.images_by_paragraph) == [0, 4, 5]
    table = decorated.images_by_paragraph[0][0]
    assert table.kind == "table"
    assert table.to_pdf_image().label == PRESERVED_LABELS["table"]
    table_record = next(item for item in decorated.provenance if item.kind == "table")
    assert table_record.anchor_index == 0


def test_preview_renderers_and_acceptance_support_preserved_assets(tmp_path):
    from src.core.mineru.acceptance import build_acceptance_package
    from src.core.mineru.epub_preview import build_epub_preview
    from src.core.mineru.pdf_preview import build_pdf_preview

    cache = _load(tmp_path, _mixed_pages(), source_pages=[1, 19])
    pdf = build_pdf_preview(cache, tmp_path / "pdf")
    build_epub_preview(cache, tmp_path / "epub", title="Preserved content sample")

    payload = json.loads(pdf.provenance_path.read_text(encoding="utf-8"))
    assert payload["counts"]["source_preserved"] == 2
    assert payload["counts"]["tables"] == 1
    assert payload["counts"]["formulas"] == 1
    kinds = [record["kind"] for record in payload["images"]]
    assert "table" in kinds and "formula" in kinds
    assert any(record["image_path"] == "images/table1.png"
               for record in payload["images"])

    package = build_acceptance_package(cache, tmp_path / "pdf", tmp_path / "epub",
                                       tmp_path / "package")
    assert package.passed is True, package.failures
