"""Validation and loading of a cached MinerU online result.

The loader accepts only the documented probe cache shape and fails with an
actionable error instead of rendering a partial artifact. Every file it reads is
fingerprinted so later stages can prove the cache was not modified.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Mapping, Tuple

from src.utils.hashing import sha256_file

KNOWN_BLOCK_TYPES = frozenset(
    {"title", "paragraph", "image", "table", "equation_interline",
     "page_header", "page_footnote", "page_number"}
)

# MinerU 3.4.4 V2 contract values for a table block (the online service reported
# `_version_name: 3.4.4`). Both are preserved as the supplied source image; the
# HTML body is validated but never rendered, so no semantic/editable table is
# promised.
KNOWN_TABLE_TYPES = frozenset({"simple_table", "complex_table"})

# V2 text runs are either text or an inline formula. Inline formulas have no
# verified preservation path in this application (there is no isolated image and
# translating LaTeX as prose is not safe), so they fail closed intentionally.
TEXT_SPAN_TYPE = "text"
INLINE_FORMULA_SPAN_TYPE = "equation_inline"

# MinerU V2 boxes are normalised against a 1000 x 1000 square, not the page size.
NORMALISED_SIZE = 1000.0

MAX_BLOCKS = 20_000
MAX_BLOCK_TEXT = 100_000
MAX_TOTAL_TEXT = 2_000_000
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000

# Recognised image formats: suffix -> the format name PdfImage accepts.
IMAGE_FORMATS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}


class MineruCacheError(ValueError):
    """The cached MinerU result cannot be used for reconstruction."""


class MineruUnsupportedContentError(MineruCacheError):
    """The result has a contracted shape whose preservation path is unverified.

    Unknown shapes stay plain :class:`MineruCacheError` (fail closed as an
    invalid result). This subclass is for a recognised construct that the
    application deliberately does not claim to handle — currently an inline
    formula run or a non-LaTeX formula variant.
    """


@dataclass(frozen=True)
class PageInfo:
    """One recognised sample page and the source PDF page it came from."""

    sample_index: int
    source_page: int
    width_pt: float
    height_pt: float


@dataclass(frozen=True)
class CachedBlock:
    """One recognised block, in sample reading order and source-page points."""

    index: int
    page_index: int
    type: str
    bbox: Tuple[float, float, float, float]
    text: str = ""
    level: int | None = None
    image_path: Path | None = None
    image_caption: Tuple[str, ...] = ()
    image_footnote: Tuple[str, ...] = ()
    # V2 `table` content (MinerU 3.4.4 contract; the supplied image is used).
    table_caption: Tuple[str, ...] = ()
    table_footnote: Tuple[str, ...] = ()
    table_type: str = ""
    table_nest_level: int = 0
    # V2 `equation_interline` content: the supplied image is used, the LaTeX
    # text is retained for provenance only.
    math_content: str = ""
    math_type: str = ""


@dataclass(frozen=True)
class MineruCache:
    """A validated MinerU probe cache."""

    root: Path
    pages: Tuple[PageInfo, ...]
    blocks: Tuple[CachedBlock, ...]
    source_pages: Tuple[int, ...]
    source_total_pages: int
    source_path: str
    source_sha256: str
    sample_sha256: str
    backend: str
    engine_version: str
    fingerprints: Mapping[str, str] = field(default_factory=dict)


def load_cache(root: Path) -> MineruCache:
    """Load and validate a cached MinerU result; raise MineruCacheError on any gap."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise MineruCacheError(f"Cache directory not found: {root}")
    # A probe run directory keeps MinerU's extracted files under result/.
    assets = root / "result" if (root / "result" / "layout.json").is_file() else root

    info = _read_json(root / "sample-info.json", "sample-info.json")
    layout = _read_json(assets / "layout.json", "layout.json")
    v2_paths = sorted(assets.glob("*content_list_v2.json"))
    if len(v2_paths) != 1:
        raise MineruCacheError(
            f"Expected exactly one *content_list_v2.json in {assets}, found {len(v2_paths)}."
        )
    v2 = _read_json(v2_paths[0], v2_paths[0].name)

    source_pages = _source_pages(info)
    total_pages = _positive_int(info.get("source_total_pages"), "source_total_pages")
    if max(source_pages) > total_pages:
        raise MineruCacheError(
            "sample-info.json maps a sample page beyond source_total_pages."
        )
    source_sha256 = _sha256_hex(info.get("source_sha256"), "source_sha256")
    sample_sha256 = _sha256_hex(info.get("sample_sha256"), "sample_sha256")
    source_path = info.get("source_path")
    if not isinstance(source_path, str) or not source_path:
        raise MineruCacheError("sample-info.json has no source_path string.")

    pdf_info = layout.get("pdf_info")
    if not isinstance(pdf_info, list) or not pdf_info:
        raise MineruCacheError("layout.json has no non-empty pdf_info list.")
    if len(pdf_info) != len(source_pages):
        raise MineruCacheError(
            f"layout.json describes {len(pdf_info)} pages but sample-info.json maps "
            f"{len(source_pages)} source pages."
        )
    if not isinstance(v2, list) or len(v2) != len(pdf_info):
        raise MineruCacheError(
            f"The V2 content list has {len(v2) if isinstance(v2, list) else 'no'} page "
            f"groups but layout.json describes {len(pdf_info)} pages."
        )

    pages = tuple(_page_info(index, entry, source_pages) for index, entry in enumerate(pdf_info))
    blocks, fingerprints = _blocks(root, assets, v2, pages)
    _fingerprint(root / "sample-info.json", root, fingerprints)
    _fingerprint(assets / "layout.json", root, fingerprints)
    _fingerprint(v2_paths[0], root, fingerprints)

    backend = layout.get("_backend")
    version = layout.get("_version_name")
    return MineruCache(
        root=root,
        pages=pages,
        blocks=blocks,
        source_pages=tuple(source_pages),
        source_total_pages=total_pages,
        source_path=source_path,
        source_sha256=source_sha256,
        sample_sha256=sample_sha256,
        backend=backend if isinstance(backend, str) else "",
        engine_version=version if isinstance(version, str) else "",
        fingerprints=dict(sorted(fingerprints.items())),
    )


def _page_info(index: int, entry: Any, source_pages: list[int]) -> PageInfo:
    if not isinstance(entry, dict):
        raise MineruCacheError(f"layout.json page {index} is not an object.")
    if entry.get("page_idx") != index:
        raise MineruCacheError(
            f"layout.json page {index} reports page_idx {entry.get('page_idx')!r}."
        )
    size = entry.get("page_size")
    if (not isinstance(size, (list, tuple)) or len(size) != 2
            or not all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0
                       for value in size)):
        raise MineruCacheError(f"layout.json page {index} has no usable page_size.")
    return PageInfo(sample_index=index, source_page=source_pages[index],
                    width_pt=float(size[0]), height_pt=float(size[1]))


def _blocks(root: Path, assets: Path, v2: list, pages: Tuple[PageInfo, ...]
            ) -> Tuple[Tuple[CachedBlock, ...], Dict[str, str]]:
    blocks: list[CachedBlock] = []
    fingerprints: Dict[str, str] = {}
    total_text = 0
    for page_index, page in enumerate(v2):
        if not isinstance(page, list):
            raise MineruCacheError(f"V2 page group {page_index} is not a list.")
        for entry in page:
            if len(blocks) >= MAX_BLOCKS:
                raise MineruCacheError(f"The cache exceeds {MAX_BLOCKS} recognised blocks.")
            block = _cached_block(root, assets, page_index, pages[page_index], entry,
                                  len(blocks), fingerprints)
            total_text += _text_length(block)
            if total_text > MAX_TOTAL_TEXT:
                raise MineruCacheError("The cache exceeds the reconstruction text budget.")
            blocks.append(block)
    return tuple(blocks), fingerprints


def _text_length(block: CachedBlock) -> int:
    """Every retained text character, including captions and formula source."""
    return (len(block.text) + len(block.math_content)
            + sum(len(part) for part in block.table_caption)
            + sum(len(part) for part in block.table_footnote))


def _cached_block(root: Path, assets: Path, page_index: int, page: PageInfo, entry: Any,
                  index: int, fingerprints: Dict[str, str]) -> CachedBlock:
    where = f"V2 page {page_index} block {index}"
    if not isinstance(entry, dict):
        raise MineruCacheError(f"{where} is not an object.")
    kind = entry.get("type")
    if kind not in KNOWN_BLOCK_TYPES:
        raise MineruCacheError(f"{where} has unsupported type {kind!r}.")
    bbox = _bbox(entry.get("bbox"), page, where)
    content = entry.get("content")
    if not isinstance(content, dict):
        raise MineruCacheError(f"{where} has no content object.")

    if kind == "image":
        source = content.get("image_source")
        if not isinstance(source, dict):
            raise MineruCacheError(f"{where} has no image_source object.")
        image_path = _image_path(root, assets, source.get("path"), where, fingerprints)
        caption = _runs(content.get("image_caption"), f"{where} image_caption")
        footnote = _runs(content.get("image_footnote"), f"{where} image_footnote")
        return CachedBlock(index=index, page_index=page_index, type=kind, bbox=bbox,
                           text=_clip(content.get("content", "") or "", where),
                           image_path=image_path, image_caption=caption,
                           image_footnote=footnote)

    if kind == "table":
        return _table_block(root, assets, page_index, index, bbox, content,
                            where, fingerprints)

    if kind == "equation_interline":
        return _equation_block(root, assets, page_index, index, bbox, content,
                               where, fingerprints)

    key = {"title": "title_content", "paragraph": "paragraph_content",
           "page_footnote": "page_footnote_content",
           "page_header": "page_header_content",
           "page_number": "page_number_content"}[kind]
    text = "".join(_runs(content.get(key), f"{where} {key}"))
    level = content.get("level") if kind == "title" else None
    if level is not None and (not isinstance(level, int) or isinstance(level, bool) or level < 1):
        raise MineruCacheError(f"{where} has an invalid title level {level!r}.")
    return CachedBlock(index=index, page_index=page_index, type=kind, bbox=bbox, text=text,
                       level=level)


def _table_block(root: Path, assets: Path, page_index: int, index: int,
                 bbox: Tuple[float, float, float, float], content: Mapping[str, Any],
                 where: str, fingerprints: Dict[str, str]) -> CachedBlock:
    """Validate one contracted ``table`` block and keep its supplied source image."""
    where = f"{where} table"
    _require_non_empty_bounds(bbox, where)
    source = content.get("image_source")
    if not isinstance(source, dict):
        raise MineruCacheError(f"{where} has no image_source object.")
    image_path = _image_path(root, assets, source.get("path"), where, fingerprints)
    caption = _runs(content.get("table_caption"), f"{where} table_caption")
    footnote = _runs(content.get("table_footnote"), f"{where} table_footnote")
    # The HTML body is part of the verified contract but is never rendered:
    # source-image preservation does not promise an editable/semantic table.
    _clip(_require_string(content, "html", where), where)
    table_type = content.get("table_type")
    if table_type not in KNOWN_TABLE_TYPES:
        raise MineruCacheError(f"{where} has an unsupported table_type {table_type!r}.")
    nest_level = content.get("table_nest_level")
    if (not isinstance(nest_level, int) or isinstance(nest_level, bool)
            or nest_level < 1):
        raise MineruCacheError(
            f"{where} has an invalid table_nest_level {nest_level!r}.")
    return CachedBlock(index=index, page_index=page_index, type="table", bbox=bbox,
                       image_path=image_path, table_caption=caption,
                       table_footnote=footnote, table_type=table_type,
                       table_nest_level=nest_level)


def _equation_block(root: Path, assets: Path, page_index: int, index: int,
                    bbox: Tuple[float, float, float, float],
                    content: Mapping[str, Any], where: str,
                    fingerprints: Dict[str, str]) -> CachedBlock:
    """Validate one contracted ``equation_interline`` block."""
    where = f"{where} formula"
    _require_non_empty_bounds(bbox, where)
    source = content.get("image_source")
    if not isinstance(source, dict):
        raise MineruCacheError(f"{where} has no image_source object.")
    image_path = _image_path(root, assets, source.get("path"), where, fingerprints)
    math_content = _clip(_require_string(content, "math_content", where), where)
    math_type = content.get("math_type")
    if math_type != "latex":
        raise MineruUnsupportedContentError(
            f"{where} has an unverified math_type {math_type!r}; only the "
            f"contracted 'latex' representation is preserved.")
    return CachedBlock(index=index, page_index=page_index,
                       type="equation_interline", bbox=bbox,
                       image_path=image_path, math_content=math_content,
                       math_type=math_type)


def _require_string(content: Mapping[str, Any], key: str, where: str) -> str:
    value = content.get(key)
    if not isinstance(value, str):
        raise MineruCacheError(f"{where} has no {key} string.")
    return value


def _require_non_empty_bounds(bbox: Tuple[float, float, float, float],
                              where: str) -> None:
    """A preserved source image must have finite, non-empty page geometry."""
    x0, y0, x1, y1 = bbox
    if not all(math.isfinite(value) for value in bbox) or x1 <= x0 or y1 <= y0:
        raise MineruCacheError(
            f"{where} has empty bounds {bbox!r}; a source image cannot be "
            f"placed without finite, non-empty geometry.")


def _runs(value: Any, where: str) -> Tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise MineruCacheError(f"{where} is not a list of text runs.")
    parts = []
    for run in value:
        if not isinstance(run, dict):
            raise MineruCacheError(f"{where} contains a run that is not an object.")
        span_type = run.get("type")
        if span_type == INLINE_FORMULA_SPAN_TYPE:
            raise MineruUnsupportedContentError(
                f"{where} contains an inline formula (equation_inline) run. "
                f"Inline formula preservation is not verified in this "
                f"application, and discarding the run silently would be "
                f"dishonest; the document is refused instead.")
        if span_type != TEXT_SPAN_TYPE:
            raise MineruCacheError(
                f"{where} contains unsupported span type {span_type!r}.")
        if not isinstance(run.get("content"), str):
            raise MineruCacheError(f"{where} contains a text run without string content.")
        parts.append(run["content"])
    return tuple(parts)


def _clip(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise MineruCacheError(f"{where} has non-string text content.")
    if len(value) > MAX_BLOCK_TEXT:
        raise MineruCacheError(f"{where} text exceeds {MAX_BLOCK_TEXT} characters.")
    return value


def _bbox(value: Any, page: PageInfo, where: str) -> Tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise MineruCacheError(f"{where} has no four-value bbox.")
    if not all(isinstance(item, (int, float)) and not isinstance(item, bool)
               and math.isfinite(item) and 0 <= item <= NORMALISED_SIZE for item in value):
        raise MineruCacheError(f"{where} has a bbox outside the normalised 0..1000 square.")
    x0, y0, x1, y1 = (float(item) for item in value)
    if x1 < x0 or y1 < y0:
        raise MineruCacheError(f"{where} has an inverted bbox.")
    return (x0 * page.width_pt / NORMALISED_SIZE, y0 * page.height_pt / NORMALISED_SIZE,
            x1 * page.width_pt / NORMALISED_SIZE, y1 * page.height_pt / NORMALISED_SIZE)


def _image_path(root: Path, assets: Path, value: Any, where: str,
                fingerprints: Dict[str, str]) -> Path:
    if not isinstance(value, str) or not value:
        raise MineruCacheError(f"{where} has no image_source path.")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise MineruCacheError(f"{where} image path {value!r} escapes the cache directory.")
    path = assets.joinpath(*relative.parts)
    if not path.is_file():
        raise MineruCacheError(f"{where} references missing image {value!r}.")
    if path.suffix.lower() not in IMAGE_FORMATS:
        raise MineruCacheError(
            f"{where} image {value!r} has unsupported extension {path.suffix!r}."
        )
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise MineruCacheError(f"{where} image {value!r} exceeds the size budget.")
    _verify_image(path, where)
    _fingerprint(path, root, fingerprints)
    return path


def _verify_image(path: Path, where: str) -> None:
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(path) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise MineruCacheError(f"{where} image {path.name!r} exceeds the pixel budget.")
            image.verify()
    except MineruCacheError:
        raise
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise MineruCacheError(f"{where} image {path.name!r} is not decodable.") from exc


def _source_pages(info: Mapping[str, Any]) -> list[int]:
    value = info.get("source_pages")
    if not isinstance(value, list) or not value:
        raise MineruCacheError("sample-info.json has no non-empty source_pages list.")
    pages = []
    for item in value:
        pages.append(_positive_int(item, "source_pages entry"))
    if len(set(pages)) != len(pages):
        raise MineruCacheError("sample-info.json repeats a source page.")
    return pages


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise MineruCacheError(f"sample-info.json {label} is not a positive integer.")
    return value


def _sha256_hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
            char not in "0123456789abcdefABCDEF" for char in value):
        raise MineruCacheError(f"sample-info.json {label} is not a SHA-256 hex digest.")
    return value.lower()


def _read_json(path: Path, label: str) -> Any:
    if not path.is_file():
        raise MineruCacheError(f"Required cache file is missing: {label}.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MineruCacheError(f"{label} is not valid UTF-8 JSON.") from exc


def _key(path: Path, root: Path) -> str:
    """Stable cache-relative fingerprint key (the run dir may wrap a result/ dir)."""
    return path.relative_to(root).as_posix()


def _fingerprint(path: Path, root: Path, fingerprints: Dict[str, str]) -> None:
    key = _key(path, root)
    if key not in fingerprints:
        fingerprints[key] = sha256_file(path)
