"""Render a reconstruction as a real source-language PDF preview plus provenance.

The artifact is a reflowed reading copy: page count, positions and line breaks
may differ from the source. Pixel-identical layout is not a goal. The output
directory is written atomically and the cache is never modified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from src.core.pdf import build_pdf

from .cache import MineruCache
from .structure import Reconstruction, adapt

SCHEMA_VERSION = 1
ARTIFACT_KIND = "mineru_online_reconstruction_preview"
# Only used for RTL detection; the preview reproduces the source text unchanged.
NEUTRAL_LANGUAGE = "en"


class MineruExportError(ValueError):
    """The preview artifact cannot be written safely."""


@dataclass(frozen=True)
class PreviewResult:
    """Outcome of one offline preview build."""

    pdf_path: Path
    provenance_path: Path
    page_count: int
    paragraph_count: int
    image_count: int
    text_chars: int
    review_required: bool


def build_preview(cache: MineruCache, output_dir: Path) -> PreviewResult:
    """Build ``preview.pdf`` and ``preview.provenance.json`` from a validated cache."""
    output_dir = Path(output_dir)
    if _is_inside(output_dir, cache.root):
        raise MineruExportError(
            f"Refusing to write preview output inside the cache directory {cache.root}.")

    reconstruction = adapt(cache)
    content = reconstruction.to_plain_content()
    output_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = output_dir / "preview.pdf"
    temporary = output_dir / "preview.pdf.part"
    try:
        build_pdf(list(reconstruction.paragraphs), content, str(temporary), NEUTRAL_LANGUAGE)
        temporary.replace(pdf_path)
    except MineruExportError:
        raise
    except Exception as exc:
        raise MineruExportError(
            f"The PDF preview could not be rendered: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()

    stats = _pdf_stats(pdf_path)
    provenance_path = output_dir / "preview.provenance.json"
    _write_json(provenance_path, _provenance(cache, reconstruction, stats))
    return PreviewResult(
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


def _provenance(cache: MineruCache, reconstruction: Reconstruction,
                stats: Dict[str, int]) -> Dict[str, Any]:
    paragraphs: List[Dict[str, Any]] = []
    images: List[Dict[str, Any]] = []
    for item in reconstruction.provenance:
        record = {
            "kind": item.kind,
            "source_type": item.source_type,
            "sample_page": item.sample_page,
            "source_page": item.source_page,
            "bbox": list(item.bbox) if item.bbox else None,
            "text_sha256": item.text_sha256,
        }
        if item.output_index is not None:
            record["output_index"] = item.output_index
            paragraphs.append(record)
        else:
            record["anchor_index"] = item.anchor_index
            record["image_path"] = item.image_path
            record["image_sha256"] = item.image_sha256
            images.append(record)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": {
            "kind": ARTIFACT_KIND,
            "format": "pdf",
            "translated": False,
            "complete_book": False,
            "sample_page_count": len(cache.source_pages),
            "notice": reconstruction.paragraphs[0] if reconstruction.paragraphs else "",
        },
        "engine": {
            "requested_model": "vlm",
            "returned_backend": cache.backend,
            "returned_version": cache.engine_version,
        },
        "source": {
            "path": cache.source_path,
            "sha256": cache.source_sha256,
            "total_pages": cache.source_total_pages,
            "sample_pages": list(cache.source_pages),
            "sample_sha256": cache.sample_sha256,
            "cache_fingerprints": dict(cache.fingerprints),
        },
        "page_map": [
            {"sample_index": page.sample_index, "source_page": page.source_page,
             "width_pt": page.width_pt, "height_pt": page.height_pt}
            for page in reconstruction.page_map
        ],
        "counts": dict(reconstruction.counts),
        "pdf": {
            "page_count": stats["page_count"],
            "text_chars": stats["text_chars"],
            "image_count": stats["image_count"],
            "paragraph_count": len(reconstruction.paragraphs),
        },
        "paragraphs": paragraphs,
        "images": images,
        "exclusions": [
            {"kind": item.kind, "source_type": item.source_type, "text": item.text,
             "sample_page": item.sample_page, "source_page": item.source_page,
             "bbox": list(item.bbox), "reason": item.reason}
            for item in reconstruction.exclusions
        ],
        "findings": [
            {"code": item.code, "message": item.message, "severity": item.severity,
             "sample_page": item.sample_page, "block_index": item.block_index}
            for item in reconstruction.findings
        ],
        "review_required": reconstruction.review_required,
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _is_inside(candidate: Path, root: Path) -> bool:
    try:
        Path(candidate).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True
