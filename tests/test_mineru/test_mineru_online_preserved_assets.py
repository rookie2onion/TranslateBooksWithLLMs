"""Asset, geometry and fingerprint bounds for source-preserved content (#22).

The application prefers the provider's supplied source image. It does not crop
speculatively from the source PDF: without a supplied asset (or with unusable
geometry), the result fails explicitly and no book is published. The cache
fingerprint also covers every preserved asset, so a validated result cannot be
silently attached to different bytes.

Seams under test: ``build_online_result`` and ``load_validated_result`` with the
real cache loader; only the archive bytes are synthetic.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from src.core.mineru.admission import admit_pdf_source
from src.core.mineru.cache import load_cache
from src.core.mineru.errors import MineruResultInvalid
from src.core.mineru.result import (
    build_online_result,
    cache_fingerprint,
    load_validated_result,
)
from tests.test_mineru.online_fixtures import (
    build_source_pdf,
    equation_block,
    result_zip_bytes,
    table_block,
)

V2_MEMBER = "sample_content_list_v2.json"


def _admitted(tmp_path: Path, pages: int = 1):
    source = build_source_pdf(tmp_path / "source.pdf", pages=pages)
    return admit_pdf_source(source, authorized=True, token="test-token")


def _write(tmp_path: Path, data: bytes, name: str = "result.zip") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _edit_v2(data: bytes, mutate) -> bytes:
    """Rewrite the content-list member of a synthetic result archive."""
    source = zipfile.ZipFile(io.BytesIO(data))
    buffer = io.BytesIO()
    with source, zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == V2_MEMBER:
                pages = json.loads(payload.decode("utf-8"))
                mutate(pages)
                payload = json.dumps(pages, ensure_ascii=False).encode("utf-8")
            target.writestr(info, payload)
    return buffer.getvalue()


def test_a_preserved_block_without_a_supplied_asset_is_not_cropped_from_the_pdf(tmp_path):
    """The fingerprint-matched source PDF is present, but cropping is not used.

    Without the provider's supplied table image the extraction would be
    speculative, so it fails explicitly instead of publishing a cropped guess.
    """
    admitted = _admitted(tmp_path)
    pages = [[table_block("images/table1.png", [60, 80, 940, 300],
                          caption="Table 1: Revenue")]]
    data = _edit_v2(result_zip_bytes(page_count=1, pages=pages),
                    lambda pages: pages[0][0]["content"].pop("image_source"))

    with pytest.raises(MineruResultInvalid) as raised:
        build_online_result(_write(tmp_path, data), work_dir=tmp_path / "work",
                            admitted=admitted)

    assert "image_source" in str(raised.value)
    assert not (tmp_path / "work" / "result" / "preview.pdf").exists()


def test_degenerate_supplied_geometry_is_rejected_by_the_real_result_path(tmp_path):
    admitted = _admitted(tmp_path)
    pages = [[table_block("images/table1.png", [100, 100, 100, 300])]]
    data = result_zip_bytes(page_count=1, pages=pages)

    with pytest.raises(MineruResultInvalid) as raised:
        build_online_result(_write(tmp_path, data), work_dir=tmp_path / "work",
                            admitted=admitted)

    assert "bounds" in str(raised.value).lower()


def test_a_result_bound_to_another_source_is_rejected(tmp_path):
    first = _admitted(tmp_path, pages=1)
    second_source = build_source_pdf(tmp_path / "other.pdf", pages=1)
    second = admit_pdf_source(second_source, authorized=True, token="test-token")
    assert first.sha256 != second.sha256

    pages = [[equation_block("images/eq1.png", [200, 180, 800, 260])]]
    result = build_online_result(
        _write(tmp_path, result_zip_bytes(page_count=1, pages=pages)),
        work_dir=tmp_path / "work", admitted=first)

    with pytest.raises(MineruResultInvalid) as raised:
        load_validated_result(
            result.root, admitted=second,
            expected_zip_sha256=result.zip_sha256,
            expected_cache_sha256=result.cache_sha256)

    assert "different source document" in str(raised.value)


def test_preserved_asset_bytes_are_part_of_the_validated_identity(tmp_path):
    admitted = _admitted(tmp_path)
    pages = [[table_block("images/table1.png", [60, 80, 940, 300])]]
    result = build_online_result(
        _write(tmp_path, result_zip_bytes(page_count=1, pages=pages)),
        work_dir=tmp_path / "work", admitted=admitted)
    validated_identity = result.cache_sha256
    assert validated_identity == cache_fingerprint(load_cache(result.root))

    # Replace the supplied table image with different (still valid) bytes.
    from tests.test_mineru.mineru_fixture import _png_bytes

    (result.root / "images" / "table1.png").write_bytes(
        _png_bytes(90, 70, (1, 2, 3)))
    assert cache_fingerprint(load_cache(result.root)) != validated_identity

    with pytest.raises(MineruResultInvalid) as raised:
        load_validated_result(
            result.root, admitted=admitted,
            expected_zip_sha256=result.zip_sha256,
            expected_cache_sha256=validated_identity)

    assert "validated identity" in str(raised.value)
