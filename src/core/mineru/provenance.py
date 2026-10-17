"""Shared provenance document for reconstruction previews.

One schema serves every renderer: the artifact identity, engine and source
fingerprints, page map, block accounting, per-element provenance, exclusions and
findings are identical across formats; only the rendition-specific block and the
artifact ``format`` differ.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from .cache import MineruCache
from .structure import Reconstruction

SCHEMA_VERSION = 1
ARTIFACT_KIND = "mineru_online_reconstruction_preview"


def build_provenance(cache: MineruCache, reconstruction: Reconstruction, *,
                     output_format: str, output_stats: Mapping[str, Any]) -> Dict[str, Any]:
    """Build the provenance document for one rendered preview."""
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
            "format": output_format,
            "translated": False,
            "complete_book": False,
            "sample_page_count": len(cache.source_pages),
            "notice": reconstruction.notice,
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
        output_format: dict(output_stats),
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
        "reader_check": {
            "performed": False,
            "note": "The offline build does not open a reader application; visual "
                    "acceptance remains a separate human decision.",
        },
        "review_required": reconstruction.review_required,
    }
