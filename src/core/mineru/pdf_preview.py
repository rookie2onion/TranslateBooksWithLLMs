"""Render a reconstruction as a real source-language PDF preview plus provenance.

The artifact is a reflowed reading copy: page count, positions and line breaks
may differ from the source. Pixel-identical layout is not a goal. The output
directory is written atomically and the cache is never modified.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from src.core.pdf import build_pdf

from .cache import MineruCache
from .export import (
    MineruExportError,
    atomic_path,
    ensure_output_outside_cache,
    write_json_atomic,
)
from .provenance import build_provenance
from .structure import adapt

# Only used for RTL detection; the preview reproduces the source text unchanged.
NEUTRAL_LANGUAGE = "en"


@dataclass(frozen=True)
class PdfPreviewResult:
    """Outcome of one offline PDF preview build."""

    pdf_path: Path
    provenance_path: Path
    page_count: int
    paragraph_count: int
    image_count: int
    text_chars: int
    review_required: bool


def build_pdf_preview(cache: MineruCache, output_dir: Path) -> PdfPreviewResult:
    """Build ``preview.pdf`` and ``preview.provenance.json`` from a validated cache."""
    output_dir = Path(output_dir)
    ensure_output_outside_cache(output_dir, cache.root)

    reconstruction = adapt(cache)
    content = reconstruction.to_plain_content()
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = output_dir / "preview.pdf"
    try:
        with atomic_path(pdf_path) as temporary:
            build_pdf(list(reconstruction.paragraphs), content, str(temporary),
                      NEUTRAL_LANGUAGE)
    except MineruExportError:
        raise
    except Exception as exc:
        raise MineruExportError(
            f"The PDF preview could not be rendered: {exc}") from exc

    stats = _pdf_stats(pdf_path)
    stats["paragraph_count"] = len(reconstruction.paragraphs)
    provenance_path = output_dir / "preview.provenance.json"
    write_json_atomic(provenance_path, build_provenance(
        cache, reconstruction, output_format="pdf", output_stats=stats))
    return PdfPreviewResult(
        pdf_path=pdf_path,
        provenance_path=provenance_path,
        page_count=stats["page_count"],
        paragraph_count=len(reconstruction.paragraphs),
        image_count=stats["image_count"],
        text_chars=stats["text_chars"],
        review_required=reconstruction.review_required,
    )


def _pdf_stats(pdf_path: Path) -> Dict[str, int]:
    import pymupdf

    with pymupdf.open(pdf_path) as document:
        return {
            "page_count": document.page_count,
            "text_chars": sum(len(page.get_text()) for page in document),
            "image_count": sum(len(page.get_images()) for page in document),
        }
