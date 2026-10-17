"""Structural adaptation of a validated MinerU cache into renderable content.

``adapt`` builds the canonical, preview-neutral source view. That view is what
the translated-book workflow consumes: it starts at the first recognised
paragraph and contains no preview notice, title suffix or inferred author.
``apply_preview_decoration`` adds those preview-only elements exactly at the
preview boundary, so the existing artifacts keep their established content while
the translation-facing view stays clean.

The adapter follows the recognised reading order, keeps headings, paragraphs,
figure captions and substantive footnotes, and excludes only running matter it
can justify (typed headers and page numbers in the top margin). Every recognised
block is accounted for: it is emitted, embedded as an image, or listed in
``exclusions`` with a reason.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Set, Tuple

from src.core.pdf.content import ParagraphFormat, PdfImage, PdfPlainContent

from .cache import IMAGE_FORMATS, CachedBlock, MineruCache, PageInfo

TOP_BAND_RATIO = 0.12
PAGE_NUMBER_MAX_DIGITS = 3
RUNNING_HEADER_MAX_CHARS = 200
_ROMAN_NUMERAL = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
_TERMINAL_PUNCTUATION = (".", "!", "?")
_NOTICE_KIND = "notice"
_HEADING_STYLES = {1: "heading1", 2: "heading2"}


@dataclass(frozen=True)
class ImageAsset:
    """A recognised figure with its bytes and source-page placement."""

    path: Path
    sample_page: int
    source_page: int
    bbox: Tuple[float, float, float, float]
    data: bytes
    ext: str
    width_pt: float
    height_pt: float
    sha256: str

    def to_pdf_image(self) -> PdfImage:
        return PdfImage(data=self.data, ext=self.ext,
                        width_pt=self.width_pt, height_pt=self.height_pt)


@dataclass(frozen=True)
class Provenance:
    """Where one output element came from."""

    kind: str
    source_type: str
    sample_page: Optional[int]
    source_page: Optional[int]
    bbox: Optional[Tuple[float, float, float, float]]
    text_sha256: str
    output_index: Optional[int] = None
    anchor_index: Optional[int] = None
    image_path: Optional[str] = None
    image_sha256: Optional[str] = None


@dataclass(frozen=True)
class Exclusion:
    """A recognised block deliberately left out, with its justification."""

    kind: str
    source_type: str
    text: str
    sample_page: int
    source_page: int
    bbox: Tuple[float, float, float, float]
    reason: str


@dataclass(frozen=True)
class Finding:
    """A limitation or review signal a reader must know about."""

    code: str
    message: str
    sample_page: Optional[int] = None
    block_index: Optional[int] = None
    severity: str = "info"  # "info" | "review"


@dataclass(frozen=True)
class SourceContent:
    """Canonical source-order document without preview decoration.

    This is the view the translated-book workflow consumes: the first paragraph
    is the first recognised paragraph, the title is the recognised title only,
    and no inferred author or preview notice is attached.
    """

    title: str
    page_size: Tuple[float, float]
    paragraphs: Tuple[str, ...]
    styles: Tuple[str, ...]
    formats: Tuple[ParagraphFormat, ...]
    images_by_paragraph: Mapping[int, Tuple[ImageAsset, ...]]
    provenance: Tuple[Provenance, ...]
    exclusions: Tuple[Exclusion, ...]
    findings: Tuple[Finding, ...]
    page_map: Tuple[PageInfo, ...]
    counts: Mapping[str, int]
    review_required: bool


@dataclass(frozen=True)
class Reconstruction:
    """Preview-ready document: neutral source content plus preview decoration.

    The preview notice paragraph is index 0, the title carries the preview
    suffix through :attr:`preview_title`, and ``author`` may hold the
    convenience inference previews have always exposed. Nothing here is part of
    the canonical source view.
    """

    title: str
    author: str
    notice: str
    page_size: Tuple[float, float]
    paragraphs: Tuple[str, ...]
    styles: Tuple[str, ...]
    formats: Tuple[ParagraphFormat, ...]
    images_by_paragraph: Mapping[int, Tuple[ImageAsset, ...]]
    provenance: Tuple[Provenance, ...]
    exclusions: Tuple[Exclusion, ...]
    findings: Tuple[Finding, ...]
    page_map: Tuple[PageInfo, ...]
    counts: Mapping[str, int]
    review_required: bool

    @property
    def preview_title(self) -> str:
        """Identifying document title for any preview artifact."""
        if self.title:
            return f"{self.title} — untranslated MinerU sample preview"
        return "Untranslated MinerU sample preview"

    def to_plain_content(self) -> PdfPlainContent:
        """Convert to the existing PDF content model."""
        images = {anchor: [asset.to_pdf_image() for asset in assets]
                  for anchor, assets in self.images_by_paragraph.items()}
        return PdfPlainContent(
            paragraphs_text=list(self.paragraphs),
            paragraphs_style=list(self.styles),
            images_by_paragraph=images,
            page_size=self.page_size,
            title=self.preview_title,
            author=self.author,
            page_count=len(self.page_map),
            paragraphs_format=list(self.formats),
        )


def adapt(cache: MineruCache) -> SourceContent:
    """Build the canonical, preview-neutral source-order document."""
    paragraphs: List[str] = []
    styles: List[str] = []
    formats: List[ParagraphFormat] = []
    provenance: List[Provenance] = []
    exclusions: List[Exclusion] = []
    findings: List[Finding] = []
    images: Dict[int, List[ImageAsset]] = {}
    accounted: Set[int] = set()

    def emit(text: str, kind: str, style: str, fmt: ParagraphFormat,
             block: Optional[CachedBlock] = None, source_type: str = "") -> None:
        index = len(paragraphs)
        paragraphs.append(text)
        styles.append(style)
        formats.append(fmt)
        if block is not None:
            accounted.add(block.index)
        provenance.append(Provenance(
            kind=kind,
            source_type=source_type or (block.type if block else "generated"),
            sample_page=block.page_index if block else None,
            source_page=(cache.pages[block.page_index].source_page if block else None),
            bbox=block.bbox if block else None,
            text_sha256=_sha256_text(text),
            output_index=index,
        ))

    def exclude(block: CachedBlock, kind: str, reason: str) -> None:
        page = cache.pages[block.page_index]
        exclusions.append(Exclusion(
            kind=kind, source_type=block.type, text=block.text.strip(),
            sample_page=block.page_index, source_page=page.source_page,
            bbox=block.bbox, reason=reason))
        accounted.add(block.index)

    def running_matter(block: CachedBlock, text: str, *, kind: str, label: str,
                       code: str) -> None:
        page = cache.pages[block.page_index]
        if not text:
            exclude(block, "empty_record", "empty recognition record (no text)")
            return
        if _in_top_band(block, page) and _looks_like_running_text(text, label):
            occurrences = sum(1 for other in cache.blocks
                              if other.type == block.type and other.text.strip() == text)
            exclude(block, kind,
                    f"running {label} in the top margin ({len(text)} characters, "
                    f"{occurrences} occurrence(s) in this sample)")
            return
        emit(text, "paragraph", "normal", ParagraphFormat(), block)
        findings.append(Finding(
            code=code,
            message=f"A {label} block does not look like running matter; it is "
                    f"retained as a paragraph for review.",
            sample_page=block.page_index, block_index=block.index, severity="review"))

    first_title = _first_level_one_title(cache)
    for block in cache.blocks:
        page = cache.pages[block.page_index]
        text = block.text.strip()

        if block.type == "title":
            if not text:
                exclude(block, "empty_title", "empty recognition record")
                continue
            level = min(block.level or 1, 3)
            emit(text, "heading", _HEADING_STYLES.get(level, "heading3"),
                 ParagraphFormat(), block)

        elif block.type == "paragraph":
            if not text:
                exclude(block, "empty_record",
                        "empty recognition record (no text)")
                continue
            if _looks_like_page_number(block, page):
                findings.append(Finding(
                    code="possible_page_number",
                    message="Numeric top-margin paragraph retained as text; it may be a "
                            "running page number the recogniser classified as a paragraph.",
                    sample_page=block.page_index, block_index=block.index))
            emit(text, "paragraph", "normal", ParagraphFormat(), block)

        elif block.type == "image":
            asset = _image_asset(block, page, cache.root)
            anchor = len(paragraphs) - 1
            images.setdefault(anchor, []).append(asset)
            accounted.add(block.index)
            provenance.append(Provenance(
                kind="image", source_type="image", sample_page=block.page_index,
                source_page=page.source_page, bbox=block.bbox,
                text_sha256=_sha256_text(""), anchor_index=anchor,
                image_path=block.image_path.relative_to(cache.root).as_posix(),
                image_sha256=asset.sha256))
            caption = " ".join(part.strip() for part in block.image_caption if part.strip())
            if caption:
                emit(caption, "caption", "normal", ParagraphFormat(italic=True),
                     block, source_type="image_caption")
            credit = " ".join(part.strip() for part in block.image_footnote if part.strip())
            if credit:
                emit(credit, "footnote", "normal", ParagraphFormat(italic=True),
                     block, source_type="image_footnote")
            if text:
                emit(text, "paragraph", "normal", ParagraphFormat(), block,
                     source_type="image_content")
                findings.append(Finding(
                    code="image_content_retained",
                    message="Recognised image text was retained as a paragraph after "
                            "the figure.",
                    sample_page=block.page_index, block_index=block.index))

        elif block.type == "page_footnote":
            if not text:
                exclude(block, "empty_record",
                        "empty recognition record (no text)")
                continue
            emit(text, "footnote", "normal", ParagraphFormat(italic=True), block)
            findings.append(Finding(
                code="footnote_retained",
                message="MinerU classified this block as a page footnote; it is retained "
                        "as substantive text because captions are sometimes classified "
                        "this way.",
                sample_page=block.page_index, block_index=block.index))

        elif block.type == "page_header":
            running_matter(block, text, kind="running_header", label="header",
                           code="header_outside_top_margin")

        elif block.type == "page_number":
            running_matter(block, text, kind="running_page_number", label="page number",
                           code="page_number_outside_top_margin")

    unaccounted = [block for block in cache.blocks if block.index not in accounted]
    for block in unaccounted:
        findings.append(Finding(
            code="unaccounted_block",
            message="This recognised block reached neither output nor an exclusion.",
            sample_page=block.page_index, block_index=block.index, severity="review"))

    counts = {
        "blocks_seen": len(cache.blocks),
        "blocks_accounted": len(accounted),
        "blocks_unaccounted": len(unaccounted),
        "paragraphs": len(paragraphs),
        "images": sum(len(assets) for assets in images.values()),
        "excluded": len(exclusions),
        "empty_records": sum(1 for item in exclusions if item.kind == "empty_record"),
        "findings": len(findings),
        "review_findings": sum(1 for item in findings if item.severity == "review"),
    }
    first_page = cache.pages[0]
    return SourceContent(
        title=first_title.text.strip() if first_title else "",
        page_size=(first_page.width_pt, first_page.height_pt),
        paragraphs=tuple(paragraphs),
        styles=tuple(styles),
        formats=tuple(formats),
        images_by_paragraph={anchor: tuple(assets) for anchor, assets in images.items()},
        provenance=tuple(provenance),
        exclusions=tuple(exclusions),
        findings=tuple(findings),
        page_map=cache.pages,
        counts=counts,
        review_required=any(item.severity == "review" for item in findings),
    )


def apply_preview_decoration(cache: MineruCache,
                             source: SourceContent) -> Reconstruction:
    """Add the preview-only notice paragraph and metadata to a source view.

    The notice becomes paragraph 0, so every source paragraph index and image
    anchor shifts by one. The inferred author stays a preview convenience and is
    never attached to the canonical source view.
    """
    notice = _notice_text(cache)
    paragraphs = (notice,) + source.paragraphs
    styles = ("normal",) + source.styles
    formats = (ParagraphFormat(italic=True),) + source.formats
    images = {anchor + 1: assets
              for anchor, assets in source.images_by_paragraph.items()}
    provenance = (_notice_provenance(notice),) + tuple(
        _shift_preview_provenance(item) for item in source.provenance)
    counts = dict(source.counts)
    counts["paragraphs"] = len(paragraphs)
    first_title = _first_level_one_title(cache)
    return Reconstruction(
        title=source.title,
        author=_author_before_title(cache, first_title),
        notice=notice,
        page_size=source.page_size,
        paragraphs=paragraphs,
        styles=styles,
        formats=formats,
        images_by_paragraph=images,
        provenance=provenance,
        exclusions=source.exclusions,
        findings=source.findings,
        page_map=source.page_map,
        counts=counts,
        review_required=source.review_required,
    )


def _notice_provenance(notice: str) -> Provenance:
    return Provenance(
        kind=_NOTICE_KIND,
        source_type="generated",
        sample_page=None,
        source_page=None,
        bbox=None,
        text_sha256=_sha256_text(notice),
        output_index=0,
    )


def _shift_preview_provenance(item: Provenance) -> Provenance:
    """Shift one neutral source record to its decorated preview position."""
    if item.output_index is not None:
        return replace(item, output_index=item.output_index + 1)
    anchor = item.anchor_index
    return replace(item, anchor_index=None if anchor is None else anchor + 1)


def _first_level_one_title(cache: MineruCache) -> Optional[CachedBlock]:
    return next((block for block in cache.blocks
                 if block.type == "title" and (block.level or 1) == 1
                 and block.text.strip()), None)


def _notice_text(cache: MineruCache) -> str:
    return (f"Untranslated MinerU reconstruction preview — source pages "
            f"{_page_list(cache.source_pages)} ({len(cache.source_pages)} of "
            f"{cache.source_total_pages} pages). Reflowed layout; not a complete book "
            f"and not a translation.")


def _page_list(pages: Tuple[int, ...]) -> str:
    if len(pages) == 1:
        return str(pages[0])
    return ", ".join(str(page) for page in pages[:-1]) + f" and {pages[-1]}"


def _author_before_title(cache: MineruCache, first_title: Optional[CachedBlock]) -> str:
    """Infer the author from the first non-empty paragraph before the title on its page."""
    if first_title is None:
        return ""
    for block in cache.blocks:
        if block.index == first_title.index:
            break
        if block.page_index != first_title.page_index:
            continue
        if block.type == "paragraph" and block.text.strip():
            return block.text.strip()
    return ""


def _image_asset(block: CachedBlock, page: PageInfo, root: Path) -> ImageAsset:
    assert block.image_path is not None
    x0, y0, x1, y1 = block.bbox
    data = block.image_path.read_bytes()
    return ImageAsset(
        path=block.image_path,
        sample_page=block.page_index,
        source_page=page.source_page,
        bbox=block.bbox,
        data=data,
        ext=IMAGE_FORMATS[block.image_path.suffix.lower()],
        width_pt=x1 - x0,
        height_pt=y1 - y0,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _in_top_band(block: CachedBlock, page: PageInfo) -> bool:
    return block.bbox[3] <= TOP_BAND_RATIO * page.height_pt


def _looks_like_page_number(block: CachedBlock, page: PageInfo) -> bool:
    text = block.text.strip()
    return (_is_page_number_text(text) and _in_top_band(block, page))


def _looks_like_running_text(text: str, label: str) -> bool:
    if label == "page number":
        return _is_page_number_text(text)
    return (len(text) <= RUNNING_HEADER_MAX_CHARS
            and not text.endswith(_TERMINAL_PUNCTUATION))


def _is_page_number_text(text: str) -> bool:
    candidate = text.strip()
    if not candidate.isascii():
        return False
    if candidate.isdigit():
        return len(candidate) <= PAGE_NUMBER_MAX_DIGITS
    return bool(_ROMAN_NUMERAL.fullmatch(candidate))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
