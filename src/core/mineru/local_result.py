"""Admit local MinerU layout results without online probe metadata."""

from __future__ import annotations

import math
import re
from pathlib import Path, PurePosixPath
from typing import Any

from src.utils.hashing import sha256_file

from .cache import (
    MAX_BLOCKS,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_TOTAL_TEXT,
    CachedBlock,
    MineruCache,
    MineruCacheError,
    PageInfo,
    SourceRegion,
    _clip,
    _image_path,
    _page_info,
    _read_json,
    _source_crop,
    _verify_image,
)

RegionGroups = dict[tuple[int, int], tuple[dict, tuple[SourceRegion, ...]]]

_TEXT_TYPES = {"text": "paragraph", "title": "title", "header": "page_header",
               "footer": "page_footer", "page_number": "page_number",
               "page_footnote": "page_footnote", "aside_text": "page_aside_text"}
_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def _has_invalid_xml_text(value: Any) -> bool:
    if isinstance(value, dict):
        return any((isinstance(item, str) and bool(_INVALID_XML.search(item))) if key == "content"
                   else _has_invalid_xml_text(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_has_invalid_xml_text(item) for item in value)
    return False


def load_local_result(path: Path, *, source_pdf: Path | None = None,
                       working_dir: Path | None = None) -> MineruCache:
    """Normalize one authoritative layout layer into the shared source model."""
    path = Path(path).resolve()
    layout_path = path / "layout.json" if path.is_dir() else path
    root = layout_path.parent
    layout = _read_json(layout_path, layout_path.name)
    entries = layout.get("pdf_info") if isinstance(layout, dict) else None
    if not isinstance(entries, list) or not entries:
        raise MineruCacheError("Local layout has no non-empty pdf_info list.")
    source_pages = list(range(1, len(entries) + 1))
    pages = tuple(_page_info(i, entry, source_pages) for i, entry in enumerate(entries))
    fingerprints = {layout_path.name: sha256_file(layout_path)}
    source_pdf = _source_pdf(root, source_pdf, pages)
    source_hash = sha256_file(source_pdf) if source_pdf else ""
    region_groups = _region_groups(root, pages, fingerprints)
    blocks: list[CachedBlock] = []
    for page, entry in zip(pages, entries):
        # Parallel representations are alternatives, never additional content.
        layer = entry.get("para_blocks")
        if layer is None:
            layer = entry.get("preproc_blocks")
        discarded = entry.get("discarded_blocks", [])
        if not isinstance(layer, list) or not isinstance(discarded, list):
            raise MineruCacheError(f"Local page {page.source_page} has invalid block lists.")
        for record in [*layer, *discarded]:
            where = f"Local page {page.source_page} block {len(blocks)}"
            blocks.append(_block(record, page, len(blocks), root, fingerprints, where,
                                 source_pdf=source_pdf, working_dir=working_dir,
                                 region_groups=region_groups, pages=pages))
            if len(blocks) > MAX_BLOCKS:
                raise MineruCacheError("Local result exceeds the recognized block budget.")
    if sum(len(b.text) for b in blocks) > MAX_TOTAL_TEXT:
        raise MineruCacheError("Local result exceeds the recognized text budget.")
    if source_pdf and sha256_file(source_pdf) != source_hash:
        raise MineruCacheError("The source PDF changed during reconstruction.")
    return MineruCache(
        root=root, pages=pages, blocks=tuple(blocks), source_pages=tuple(source_pages),
        source_total_pages=len(pages), source_path="", source_sha256=source_hash,
        sample_sha256=fingerprints[layout_path.name], backend=str(layout.get("_backend", "")),
        engine_version=str(layout.get("_version_name", "")), fingerprints=fingerprints,
        generated_root=working_dir)


def _source_pdf(root: Path, explicit: Path | None,
                pages: tuple[PageInfo, ...]) -> Path | None:
    """Admit a bundle's unique original, checking overrides against its hash."""
    import pymupdf

    candidates = sorted(root.glob("*_origin.pdf"))
    if len(candidates) > 1:
        raise MineruCacheError("Ambiguous bundle: multiple original PDFs.")
    if explicit is None and not candidates:
        return None
    if not candidates:
        raise MineruCacheError(
            "Cannot verify this PDF against the result: no bundled *_origin.pdf exists.")
    source = candidates[0].resolve()
    if explicit is not None:
        explicit = Path(explicit).resolve()
        if sha256_file(explicit) != sha256_file(source):
            raise MineruCacheError("Source PDF fingerprint differs from the bundled original.")
    try:
        with pymupdf.open(source) as document:
            if len(document) != len(pages):
                raise MineruCacheError("Source PDF page count differs from the layout.")
            for page, original in zip(pages, document):
                ratio = page.width_pt / page.height_pt
                if abs(original.rect.width / original.rect.height - ratio) > 0.01 * ratio:
                    raise MineruCacheError(
                        f"Source PDF geometry differs on page {page.source_page}.")
    except (RuntimeError, ValueError) as exc:
        if isinstance(exc, MineruCacheError):
            raise
        raise MineruCacheError(f"Cannot read the bundled original PDF: {exc}") from exc
    return source


def _bounds(record: dict, page: PageInfo, where: str) -> tuple[float, float, float, float]:
    from .cache import _bbox

    box = record.get("bbox")
    if not isinstance(box, list) or len(box) != 4:
        raise MineruCacheError(f"{where} has no four-value bbox.")
    if any(type(value) not in {int, float} or not math.isfinite(value) for value in box):
        raise MineruCacheError(f"{where} has invalid bbox coordinates.")
    # Layout coordinates are page points, unlike normalized V2 coordinates.
    try:
        normalized = [box[i] / (page.width_pt if i % 2 == 0 else page.height_pt) * 1000
                      for i in range(4)]
    except (TypeError, ZeroDivisionError) as exc:
        raise MineruCacheError(f"{where} has invalid bbox coordinates.") from exc
    return _bbox(normalized, page, where)


def _text(record: dict, where: str) -> str:
    parts = []
    for line in _lines(record, where):
        text = []
        for span in line["spans"]:
            if span.get("type") != "text":
                raise MineruCacheError(f"{where} has an unsupported text span.")
            text.append(_clip(span.get("content"), where))
        parts.append("".join(text))
    return _clip(" ".join(parts), where)


def _lines(record: dict, where: str) -> list[dict]:
    lines = record.get("lines", [])
    if not isinstance(lines, list):
        raise MineruCacheError(f"{where} has invalid lines.")
    for line in lines:
        if not isinstance(line, dict) or not isinstance(line.get("spans"), list):
            raise MineruCacheError(f"{where} has invalid spans.")
        if any(not isinstance(span, dict) for span in line["spans"]):
            raise MineruCacheError(f"{where} has a non-object span.")
    return lines


def _asset(root: Path, value: Any, fingerprints: dict, where: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise MineruCacheError(f"{where} has an invalid image path.")
    rel = PurePosixPath(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise MineruCacheError(f"{where} image path escapes the result directory.")
    candidate = root / value
    if len(rel.parts) == 1 and not candidate.is_file():
        candidate = root / "images" / value
    if not candidate.resolve().is_relative_to(root):
        raise MineruCacheError(f"{where} image path escapes the result directory.")
    if not candidate.is_file():
        raise FileNotFoundError(f"{where} references missing image {value!r}.")
    return _image_path(root, root, candidate.relative_to(root).as_posix(), where, fingerprints)


def _block(record: Any, page: PageInfo, index: int, root: Path,
           fingerprints: dict, where: str, *, source_pdf: Path | None,
           working_dir: Path | None, region_groups: RegionGroups,
           pages: tuple[PageInfo, ...]) -> CachedBlock:
    if not isinstance(record, dict):
        raise MineruCacheError(f"{where} is not an object.")
    kind = record.get("type")
    if not isinstance(kind, str):
        raise MineruCacheError(f"{where} has no block type string.")
    where += f" ({kind})"
    bbox = _bounds(record, page, where)
    if _has_invalid_xml_text(record):
        known_type = _TEXT_TYPES.get(kind, {"ref_text": "list", "image": "image",
                                          "chart": "chart", "table": "table"}.get(kind))
        if known_type is None:
            raise MineruCacheError(f"{where} has unsupported essential content.")
        path, regions = _crop_record(record, page, bbox, index, source_pdf, working_dir,
                                    fingerprints, where, region_groups, pages)
        return CachedBlock(index=index, page_index=page.sample_index, type=known_type,
                           bbox=bbox, image_path=path, preservation_reason="xml_control_character",
                           source_regions=regions)
    spans = [s for line in _lines(record, where) for s in line["spans"]]
    if any(s.get("type") == "inline_equation" for s in spans):
        if kind not in {"text", "ref_text"} or any(
                s.get("type") not in {"text", "inline_equation"} for s in spans):
            raise MineruCacheError(f"{where} has unsupported formula-containing content.")
        path, regions = _crop_record(record, page, bbox, index, source_pdf, working_dir,
                                    fingerprints, where, region_groups, pages)
        return CachedBlock(index=index, page_index=page.sample_index, type="paragraph",
                           bbox=bbox, image_path=path,
                           preservation_reason="inline_formula_paragraph", source_regions=regions)
    if kind in _TEXT_TYPES:
        level = record.get("level")
        if kind == "title" and level is not None and (
                type(level) is not int or not 1 <= level <= 6):
            raise MineruCacheError(f"{where} has an invalid heading level.")
        return CachedBlock(index=index, page_index=page.sample_index, type=_TEXT_TYPES[kind],
                           bbox=bbox, text=_text(record, where), level=level)
    if kind == "ref_text":
        text = _text(record, where)
        return CachedBlock(index=index, page_index=page.sample_index, type="list", bbox=bbox,
                           text=text, list_items=(text,), list_kind="reference")
    if kind in {"image", "chart", "table", "interline_equation"}:
        if kind == "interline_equation":
            paths = [s.get("image_path") for s in spans if s.get("image_path")]
            path = (_asset(root, paths[0], fingerprints, where) if len(paths) == 1 else
                    _crop(source_pdf, working_dir, page, bbox, index, fingerprints, where))
            return CachedBlock(index=index, page_index=page.sample_index,
                               type="equation_interline", bbox=bbox, image_path=path,
                               preservation_reason="formula_source_image")
        children = record.get("blocks", [])
        if not isinstance(children, list) or any(not isinstance(b, dict) for b in children):
            raise MineruCacheError(f"{where} has invalid visual children.")
        bodies = [b for b in children if b.get("type") == f"{kind}_body"]
        allowed = {f"{kind}_body", f"{kind}_caption", f"{kind}_footnote"}
        if len(bodies) != 1 or any(b.get("type") not in allowed for b in children):
            raise MineruCacheError(f"{where} has unsupported visual children.")
        body = bodies[0]
        body_spans = [s for line in _lines(body, where) for s in line["spans"]]
        if any(s.get("type") not in {"image", "table", "chart"} for s in body_spans):
            raise MineruCacheError(f"{where} has unsupported visual spans.")
        paths = [s.get("image_path") for s in body_spans]
        reason = ""
        if len(paths) == 1 and paths[0]:
            try:
                image_path = _asset(root, paths[0], fingerprints, where)
            except FileNotFoundError:
                image_path = _crop(source_pdf, working_dir, page, _bounds(body, page, where),
                                   index, fingerprints, where)
                reason = "table_missing_image" if kind == "table" else "image_missing_asset"
        elif len(paths) <= 1:
            image_path = _crop(source_pdf, working_dir, page, _bounds(body, page, where),
                               index, fingerprints, where)
            reason = "table_missing_image" if kind == "table" else "image_missing_asset"
        else:
            raise MineruCacheError(f"{where} has no unique source image.")
        captions = tuple(_text(b, where) for b in children if b.get("type") == f"{kind}_caption")
        notes = tuple(_text(b, where) for b in children if b.get("type") == f"{kind}_footnote")
        if kind == "table":
            return CachedBlock(index=index, page_index=page.sample_index, type=kind, bbox=bbox,
                               image_path=image_path, table_caption=captions,
                               table_footnote=notes, preservation_reason=reason)
        return CachedBlock(index=index, page_index=page.sample_index, type=kind, bbox=bbox,
                           image_path=image_path, image_caption=captions, image_footnote=notes,
                           preservation_reason=reason)
    raise MineruCacheError(f"{where} has unsupported essential content.")


def _crop(source_pdf: Path | None, working_dir: Path | None, page: PageInfo,
          bbox: tuple[float, float, float, float], index: int, fingerprints: dict,
          where: str) -> Path:
    if source_pdf is None or working_dir is None:
        raise MineruCacheError(f"{where} needs a source image or verified original PDF crop.")
    generated: dict[str, str] = {}
    path = _source_crop(working_dir, working_dir, source_pdf, page, bbox, index, where, generated)
    fingerprints.update({"generated/" + key: value for key, value in generated.items()})
    return path


def _region_groups(root: Path, pages: tuple[PageInfo, ...], fingerprints: dict) -> RegionGroups:
    """Index MinerU's physical rectangles by the shared merged-block identity."""
    path = root / "block_list.json"
    if not path.is_file():
        return {}
    data = _read_json(path, path.name)
    pdf_data = data.get("pdfData") if isinstance(data, dict) else None
    if not isinstance(pdf_data, list) or len(pdf_data) != len(pages):
        raise MineruCacheError("block_list.json page groups differ from the layout.")
    groups: dict[str, list[tuple[int, dict]]] = {}
    for page_index, records in enumerate(pdf_data):
        if not isinstance(records, list):
            raise MineruCacheError("block_list.json has invalid page records.")
        for record in records:
            if (not isinstance(record, dict) or not isinstance(record.get("id"), str)
                    or type(record.get("index")) is not int):
                raise MineruCacheError("block_list.json has invalid physical block identities.")
            groups.setdefault(record["id"], []).append((page_index, record))
    result: RegionGroups = {}
    for group in groups.values():
        regions = tuple(SourceRegion(p, _bounds(r, pages[p], "Physical source region"))
                        for p, r in group)
        for page_index, record in group:
            key = (page_index, record["index"])
            if key in result:
                raise MineruCacheError("block_list.json repeats a source-page block index.")
            result[key] = (record, regions)
    fingerprints[path.name] = sha256_file(path)
    return result


def _needs_regions(record: Any, bbox: tuple[float, float, float, float]) -> bool:
    if isinstance(record, dict):
        if record.get("cross_page") is True:
            return True
        box = record.get("bbox")
        if isinstance(box, list) and len(box) == 4:
            if any(type(v) not in {int, float} or not math.isfinite(v) for v in box):
                raise MineruCacheError("Merged source content has invalid span geometry.")
            if box[0] < bbox[0] - 2 or box[1] < bbox[1] - 2 or box[2] > bbox[2] + 2 or box[3] > bbox[3] + 2:
                return True
        return any(_needs_regions(value, bbox) for value in record.values())
    return isinstance(record, list) and any(_needs_regions(value, bbox) for value in record)


def _crop_record(record: dict, page: PageInfo, bbox: tuple[float, float, float, float],
                 index: int, source_pdf: Path | None, working_dir: Path | None,
                 fingerprints: dict, where: str, region_groups: RegionGroups,
                 pages: tuple[PageInfo, ...]) -> tuple[Path, tuple[SourceRegion, ...]]:
    from PIL import Image

    from src.utils.atomic_io import atomic_path

    regions: tuple[SourceRegion, ...] = (SourceRegion(page.sample_index, bbox),)
    if record.get("type") in {"image", "chart", "table"} and record.get("blocks"):
        # MinerU may place the caption in a different column, outside the image
        # parent's bbox. Preserve the associated children, not the intervening page.
        children = record["blocks"]
        if not isinstance(children, list) or any(not isinstance(c, dict) for c in children):
            raise MineruCacheError(f"{where} has invalid visual source regions.")
        regions = tuple(SourceRegion(page.sample_index, _bounds(child, page, where))
                        for child in children)
        _check_region_coverage(record, page.sample_index, regions, where)
    elif _needs_regions(record, bbox):
        physical_index = record.get("index")
        if not isinstance(physical_index, int) or isinstance(physical_index, bool):
            raise MineruCacheError(f"{where} has no usable physical source block index.")
        match = region_groups.get((page.sample_index, physical_index))
        if match is None:
            raise MineruCacheError(f"{where} needs verified physical regions for merged content.")
        physical, regions = match
        if physical.get("type") != record.get("type") or physical.get("bbox") != record.get("bbox"):
            raise MineruCacheError(f"{where} physical source mapping differs from layout.")
        if record.get("type") in {"text", "ref_text"}:
            # MinerU's companion text removes line-end hyphens. Ignore them only
            # for correspondence checks; never rewrite the exported wording.
            recognized = "".join(_text(record, where).split()).replace("-", "")
            if not isinstance(physical.get("text"), str):
                raise MineruCacheError(f"{where} physical source mapping has no text.")
            companion = "".join(physical["text"].split()).replace("-", "")
            if recognized != companion:
                raise MineruCacheError(f"{where} merged text differs from physical source mapping.")
        _check_region_coverage(record, page.sample_index, regions, where)
    if len(regions) == 1:
        region = regions[0]
        return (_crop(source_pdf, working_dir, pages[region.page_index], region.bbox,
                      index, fingerprints, where), regions)
    if source_pdf is None or working_dir is None:
        raise MineruCacheError(f"{where} needs the original PDF for merged source regions.")
    paths = []
    for ordinal, region in enumerate(regions):
        # Separate working directories avoid collisions for two columns on one page.
        region_dir = working_dir / f"block-{index}-region-{ordinal}"
        paths.append(_crop(source_pdf, region_dir, pages[region.page_index], region.bbox,
                           index, {}, where))
    images = [Image.open(path) for path in paths]
    try:
        width = max(image.width for image in images)
        height = sum(image.height for image in images) + 8 * (len(images) - 1)
        if width * height > MAX_IMAGE_PIXELS:
            raise MineruCacheError(f"{where} merged source image exceeds the pixel budget.")
        target = working_dir / f"merged-block-{index}.png"
        with Image.new("RGB", (width, height), "white") as combined:
            y = 0
            for image in images:
                combined.paste(image, (0, y))
                y += image.height + 8
            with atomic_path(target) as temporary:
                combined.save(temporary, format="PNG")
        _verify_image(target, where)
        if target.stat().st_size > MAX_IMAGE_BYTES:
            raise MineruCacheError(f"{where} merged source image exceeds the byte budget.")
        fingerprints["generated/" + target.name] = sha256_file(target)
        return target, regions
    finally:
        for image in images:
            image.close()


def _check_region_coverage(record: Any, origin: int,
                           regions: tuple[SourceRegion, ...], where: str) -> None:
    """A merged text span must belong to an admitted rectangle on the right page."""
    if isinstance(record, dict):
        for span in record.get("spans", []):
            box = span.get("bbox")
            if not isinstance(box, list) or len(box) != 4:
                if span.get("cross_page") is True:
                    raise MineruCacheError(f"{where} has cross-page text without source geometry.")
                continue
            foreign = span.get("cross_page") is True
            if not any((region.page_index != origin if foreign else region.page_index == origin)
                       and box[0] >= region.bbox[0] - 2 and box[1] >= region.bbox[1] - 2
                       and box[2] <= region.bbox[2] + 2 and box[3] <= region.bbox[3] + 2
                       for region in regions):
                raise MineruCacheError(f"{where} has text outside its mapped source regions.")
        for value in record.values():
            _check_region_coverage(value, origin, regions, where)
    elif isinstance(record, list):
        for value in record:
            _check_region_coverage(value, origin, regions, where)
