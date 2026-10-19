"""Validation of the downloaded recognition result (issue #20).

Seam under test: ``build_online_result`` — turn the provider's result archive
into the existing validated cache + neutral source content. The cache loader and
the structural adapter are the real ones; only the bytes are synthetic.

The result must match the admitted source identity and cover every expected
source page; anything else is an explicit failure, never a partial book.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from src.core.mineru.admission import admit_pdf_source
from src.core.mineru.errors import MineruResultInvalid
from src.core.mineru.result import build_online_result
from src.core.mineru.structure import adapt
from tests.test_mineru.online_fixtures import (
    build_source_pdf,
    paragraph_block,
    result_zip_bytes,
)


def _admitted(tmp_path, pages=3):
    source = build_source_pdf(tmp_path / "source.pdf", pages=pages)
    return admit_pdf_source(source, authorized=True, token="test-token")


def _write_zip(tmp_path, data: bytes, name: str = "result.zip"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_result_archive_becomes_the_validated_source_content(tmp_path):
    admitted = _admitted(tmp_path, pages=3)
    archive = _write_zip(tmp_path, result_zip_bytes(page_count=3))

    result = build_online_result(archive, work_dir=tmp_path / "work", admitted=admitted)

    assert result.page_count == 3
    assert result.cache.source_sha256 == admitted.sha256
    assert result.cache.source_total_pages == 3
    assert result.cache.source_pages == (1, 2, 3)
    assert result.cache.fingerprints
    assert len(result.zip_sha256) == 64
    assert len(result.cache_sha256) == 64

    source = adapt(result.cache)
    assert source.paragraphs[0] == "SAMPLE BOOK"
    assert source.title == "SAMPLE BOOK"
    assert "Figure 1: a caption" in source.paragraphs
    assert any(asset.ext == "png" for assets in source.images_by_paragraph.values()
               for asset in assets)
    # The neutral view is what translation consumes; no preview decoration exists.
    assert all("preview" not in paragraph.lower() for paragraph in source.paragraphs)


def test_result_identity_is_stable_for_the_same_archive(tmp_path):
    admitted = _admitted(tmp_path, pages=2)
    data = result_zip_bytes(page_count=2)

    first = build_online_result(_write_zip(tmp_path, data, "a.zip"),
                                work_dir=tmp_path / "a", admitted=admitted)
    second = build_online_result(_write_zip(tmp_path, data, "b.zip"),
                                 work_dir=tmp_path / "b", admitted=admitted)

    assert first.zip_sha256 == second.zip_sha256
    assert first.cache_sha256 == second.cache_sha256


def test_incomplete_page_coverage_is_rejected(tmp_path):
    admitted = _admitted(tmp_path, pages=3)
    archive = _write_zip(tmp_path, result_zip_bytes(page_count=3, layout_page_count=2))

    with pytest.raises(MineruResultInvalid) as raised:
        build_online_result(archive, work_dir=tmp_path / "work", admitted=admitted)

    assert "page" in str(raised.value).lower()


def test_a_result_for_a_different_page_count_is_rejected(tmp_path):
    admitted = _admitted(tmp_path, pages=3)
    archive = _write_zip(tmp_path, result_zip_bytes(page_count=4))

    with pytest.raises(MineruResultInvalid):
        build_online_result(archive, work_dir=tmp_path / "work", admitted=admitted)


def test_zip_slip_members_are_rejected(tmp_path):
    admitted = _admitted(tmp_path, pages=1)
    archive = _write_zip(
        tmp_path,
        result_zip_bytes(page_count=1, extra_members={"../escape.json": b"{}"}),
    )

    with pytest.raises(MineruResultInvalid) as raised:
        build_online_result(archive, work_dir=tmp_path / "work", admitted=admitted)

    assert "archive" in str(raised.value).lower()
    assert not (tmp_path / "escape.json").exists()


def test_symbolic_link_members_are_rejected(tmp_path):
    admitted = _admitted(tmp_path, pages=1)
    archive = _write_zip(
        tmp_path,
        result_zip_bytes(page_count=1, symlink_member="images/link.png"),
    )

    with pytest.raises(MineruResultInvalid):
        build_online_result(archive, work_dir=tmp_path / "work", admitted=admitted)


def test_an_oversized_archive_is_rejected(tmp_path):
    admitted = _admitted(tmp_path, pages=1)
    archive = _write_zip(
        tmp_path,
        result_zip_bytes(page_count=1, extra_members={"big.bin": b"0" * 4096}),
    )

    with pytest.raises(MineruResultInvalid):
        build_online_result(archive, work_dir=tmp_path / "work", admitted=admitted,
                            max_expanded_bytes=1024)


def test_too_many_archive_members_are_rejected(tmp_path):
    admitted = _admitted(tmp_path, pages=1)
    archive = _write_zip(
        tmp_path,
        result_zip_bytes(page_count=1, extra_members={
            "a.json": b"{}", "b.json": b"{}", "c.json": b"{}"}),
    )

    with pytest.raises(MineruResultInvalid):
        build_online_result(archive, work_dir=tmp_path / "work", admitted=admitted,
                            max_members=3)


def test_a_missing_layout_file_is_rejected(tmp_path):
    admitted = _admitted(tmp_path, pages=1)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("sample_content_list_v2.json", "[]")
    path = _write_zip(tmp_path, buffer.getvalue())

    with pytest.raises(MineruResultInvalid):
        build_online_result(path, work_dir=tmp_path / "work", admitted=admitted)


def test_duplicate_content_lists_are_rejected(tmp_path):
    admitted = _admitted(tmp_path, pages=1)
    archive = _write_zip(
        tmp_path,
        result_zip_bytes(page_count=1, extra_members={"second_content_list_v2.json": b"[]"}),
    )

    with pytest.raises(MineruResultInvalid):
        build_online_result(archive, work_dir=tmp_path / "work", admitted=admitted)


def test_an_image_path_escaping_the_result_is_rejected(tmp_path):
    admitted = _admitted(tmp_path, pages=1)
    pages = [[
        {"type": "paragraph", "text": "Hello", "bbox": [10, 10, 200, 50]},
        {"type": "image", "path": "../outside.png", "bbox": [10, 60, 200, 200]},
    ]]
    archive = _write_zip(tmp_path, result_zip_bytes(page_count=1, pages=pages))

    with pytest.raises(MineruResultInvalid) as raised:
        build_online_result(archive, work_dir=tmp_path / "work", admitted=admitted)

    assert "escapes" in str(raised.value).lower()


def test_an_unsupported_block_type_fails_explicitly(tmp_path):
    admitted = _admitted(tmp_path, pages=1)
    pages = [[{
        "type": "unknown_block",
        "text": "unsupported block",
        "bbox": [10, 10, 200, 200],
    }]]
    archive = _write_zip(tmp_path, result_zip_bytes(page_count=1, pages=pages))

    with pytest.raises(MineruResultInvalid) as raised:
        build_online_result(archive, work_dir=tmp_path / "work", admitted=admitted)

    assert "unknown_block" in str(raised.value)


def test_an_inline_formula_paragraph_is_preserved_from_the_admitted_pdf(tmp_path):
    admitted = _admitted(tmp_path, pages=1)
    pages = [[paragraph_block(
        "Energy is conserved.",
        [60, 80, 540, 140],
        spans=[
            {"type": "text", "content": "Energy is conserved: "},
            {"type": "equation_inline", "content": "E = mc^2"},
        ],
    )]]
    archive = _write_zip(tmp_path, result_zip_bytes(page_count=1, pages=pages))

    result = build_online_result(archive, work_dir=tmp_path / "work", admitted=admitted)
    source = adapt(result.cache)
    assert not source.paragraphs
    assert source.counts["source_preserved"] == source.counts["formulas"] == 1
    assert source.counts["blocks_accounted"] == 1
    assert "paragraph with inline formula (untranslated)" in source.images_by_paragraph[-1][0].label
    assert source.findings[0].code == "inline_formula_paragraph_preserved"
