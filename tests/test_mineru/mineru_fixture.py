"""Synthetic MinerU online cache fixtures for reconstruction tests.

The real probe cache stays private under ``data/``. These helpers write a
minimal but contract-shaped cache (layout.json, one V2 content list,
sample-info.json and local images) so reconstruction can be tested offline.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image

PAGE_WIDTH = 600
PAGE_HEIGHT = 800
SOURCE_SHA256 = "a" * 64
SAMPLE_SHA256 = "b" * 64


def _png_bytes(width: int = 40, height: int = 30) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_bytes(width: int = 40, height: int = 30) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (30, 30, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


def default_pages() -> list[dict]:
    """Two sample pages mirroring the shapes observed in the real cache."""
    return [
        {
            "blocks": [
                {"type": "title", "level": 1, "text": "SAMPLE BOOK",
                 "bbox": [60, 80, 940, 140]},
                {"type": "paragraph", "text": "Ada Lovelace",
                 "bbox": [60, 160, 400, 190]},
                {"type": "image", "path": "images/fig1.png", "bbox": [60, 300, 940, 700]},
            ]
        },
        {
            "blocks": [
                {"type": "page_header", "text": "Chapter One", "bbox": [600, 40, 900, 60]},
                {"type": "paragraph", "text": "The first body paragraph.",
                 "bbox": [60, 120, 540, 200]},
                {"type": "paragraph", "text": "", "bbox": [60, 210, 540, 220]},
                {"type": "image", "path": "images/fig2.jpg", "bbox": [600, 120, 940, 400],
                 "caption": [{"type": "text", "content": "Figure 1: a caption"}]},
                {"type": "page_footnote", "text": "A substantive footnote.",
                 "bbox": [60, 700, 540, 740]},
                {"type": "page_number", "text": "19", "bbox": [860, 40, 890, 60]},
            ]
        },
    ]


def _points(bbox: list[float]) -> list[float]:
    return [bbox[0] * PAGE_WIDTH / 1000, bbox[1] * PAGE_HEIGHT / 1000,
            bbox[2] * PAGE_WIDTH / 1000, bbox[3] * PAGE_HEIGHT / 1000]


def _v2_block(spec: dict) -> dict:
    kind = spec["type"]
    bbox = spec["bbox"]
    if kind == "title":
        return {"type": "title", "bbox": bbox,
                "content": {"title_content": [{"type": "text", "content": spec["text"]}],
                            "level": spec.get("level", 1)}}
    if kind == "paragraph":
        return {"type": "paragraph", "bbox": bbox,
                "content": {"paragraph_content": [{"type": "text", "content": spec["text"]}]}}
    if kind == "image":
        return {"type": "image", "bbox": bbox,
                "content": {"image_source": {"path": spec["path"]},
                            "content": spec.get("text", ""),
                            "image_caption": spec.get("caption", []),
                            "image_footnote": spec.get("footnote", [])}}
    payload = {"type": "text", "content": spec["text"]}
    key = {"page_footnote": "page_footnote_content",
           "page_header": "page_header_content",
           "page_number": "page_number_content"}[kind]
    return {"type": kind, "bbox": bbox, "content": {key: [payload]}}


def _layout_block(spec: dict, index: int) -> dict:
    points = _points(spec["bbox"])
    if spec["type"] == "image":
        return {"type": "image", "bbox": points, "index": index, "lines": []}
    text = spec["text"]
    block = {"type": "title" if spec["type"] == "title" else "text",
             "bbox": points, "index": index,
             "lines": [{"bbox": points, "spans": [{"bbox": points, "type": "text",
                                                    "content": text}]}]}
    if spec["type"] == "title":
        block["level"] = spec.get("level", 1)
    return block


def _sample_pdf_bytes(page_count: int) -> bytes:
    import pymupdf

    document = pymupdf.open()
    try:
        for number in range(1, page_count + 1):
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            page.insert_text((60, 80), f"Source page {number}", fontsize=18)
        return document.tobytes()
    finally:
        document.close()


def build_cache(root: Path, pages: list[dict] | None = None,
                source_pages: list[int] | None = None,
                total_pages: int = 198) -> Path:
    """Write a synthetic MinerU cache under ``root`` and return it."""
    pages = default_pages() if pages is None else pages
    source_pages = list(range(1, len(pages) + 1)) if source_pages is None else source_pages
    root.mkdir(parents=True, exist_ok=True)
    (root / "images").mkdir(exist_ok=True)
    (root / "images" / "fig1.png").write_bytes(_png_bytes())
    (root / "images" / "fig2.jpg").write_bytes(_jpeg_bytes())
    (root / "sample.pdf").write_bytes(_sample_pdf_bytes(len(pages)))

    v2 = [[_v2_block(spec) for spec in page["blocks"]] for page in pages]
    (root / "abc_content_list_v2.json").write_text(
        json.dumps(v2, ensure_ascii=False, indent=2), encoding="utf-8")

    layout_pages = []
    for index, page in enumerate(pages):
        kept = [_layout_block(spec, i) for i, spec in enumerate(page["blocks"])
                if spec["type"] in ("title", "paragraph", "image")]
        discarded = [_layout_block(spec, i) for i, spec in enumerate(page["blocks"])
                     if spec["type"] in ("page_header", "page_footnote", "page_number")]
        layout_pages.append({
            "page_idx": index,
            "page_size": [PAGE_WIDTH, PAGE_HEIGHT],
            "preproc_blocks": kept,
            "discarded_blocks": discarded,
            "para_blocks": kept,
        })
    layout = {"pdf_info": layout_pages, "_backend": "hybrid", "_version_name": "3.4.4",
              "_ocr_enable": True}
    (root / "layout.json").write_text(json.dumps(layout, ensure_ascii=False, indent=2),
                                      encoding="utf-8")

    info = {
        "source_path": "C:/private/source.pdf",
        "source_sha256": SOURCE_SHA256,
        "source_total_pages": total_pages,
        "source_pages": source_pages,
        "sample_sha256": SAMPLE_SHA256,
        "page_stats": [],
        "translation_llm_called": False,
    }
    (root / "sample-info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return root


def tree_fingerprint(root: Path) -> dict[str, str]:
    """Return sha256 of every file under ``root`` (relative posix path -> hex)."""
    result = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result
