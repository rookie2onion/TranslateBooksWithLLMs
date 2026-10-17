"""Preview-neutral source adaptation for the translated-book workflow (issue #19).

Seams under test:
- ``src.core.mineru.structure.adapt`` — canonical, preview-neutral source content.
- ``src.core.mineru.pdf_preview.build_pdf_preview`` and
  ``src.core.mineru.epub_preview.build_epub_preview`` — the existing preview
  artifacts, which must keep the preview notice and preview-only metadata.
"""

from __future__ import annotations

from pathlib import Path

from src.core.mineru.cache import load_cache
from src.core.mineru.structure import adapt
from tests.test_mineru.mineru_fixture import build_cache


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
