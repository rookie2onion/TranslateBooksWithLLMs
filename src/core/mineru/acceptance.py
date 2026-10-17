"""Build the dual-format reconstruction acceptance package (issue #16).

The package collects the PDF and EPUB previews with their provenance, a contact
sheet of the source sample pages, a human-readable report and a machine-readable
check summary. Every check is automated and offline; reader rendering and visual
acceptance stay explicitly pending.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import unicodedata
import zipfile
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from xml.etree import ElementTree

from .cache import KNOWN_BLOCK_TYPES, MineruCache
from .epub_preview import image_resource_name
from .export import MineruExportError, ensure_output_outside_cache, write_json_atomic
from .structure import Reconstruction, adapt, apply_preview_decoration

SCHEMA_VERSION = 1
XHTML = "{http://www.w3.org/1999/xhtml}"
OPF = "{http://www.idpf.org/2007/opf}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_CONTENT_TYPES = tuple(sorted(
    KNOWN_BLOCK_TYPES - {"image", "table", "equation_interline"}))
_PRESERVED_KINDS = {"table": "table", "equation_interline": "formula"}
_PARAGRAPH_TAGS = {f"{XHTML}h1", f"{XHTML}h2", f"{XHTML}h3", f"{XHTML}p"}


@dataclass(frozen=True)
class Check:
    """One automated acceptance check."""

    id: str
    description: str
    status: str  # "pass" | "fail" | "pending" | "skip"
    detail: str


@dataclass(frozen=True)
class AcceptanceResult:
    """Outcome of one acceptance package build."""

    output_dir: Path
    report_path: Path
    checks_path: Path
    manifest_path: Path
    contact_sheet_path: Path
    passed: bool
    failures: Tuple[str, ...]
    pending: Tuple[str, ...]
    checks: Tuple[Check, ...]


def build_acceptance_package(cache: MineruCache, pdf_dir: Path, epub_dir: Path,
                             output_dir: Path) -> AcceptanceResult:
    """Collect both previews and run every offline check into one package."""
    pdf_dir, epub_dir, output_dir = Path(pdf_dir), Path(epub_dir), Path(output_dir)
    ensure_output_outside_cache(output_dir, cache.root)

    pdf_provenance = _read_provenance(pdf_dir / "preview.provenance.json")
    epub_provenance = _read_provenance(epub_dir / "preview.provenance.json")
    pdf_path, epub_path = pdf_dir / "preview.pdf", epub_dir / "preview.epub"
    for path in (pdf_path, epub_path):
        if not path.is_file():
            raise MineruExportError(f"Missing preview artifact: {path}")

    reconstruction = apply_preview_decoration(cache, adapt(cache))
    pdf_pages = _pdf_paragraph_pages(pdf_path, reconstruction.paragraphs)
    checks: List[Check] = []
    checks.append(_check_artifacts(pdf_path, epub_path))
    checks.append(_check_provenance_identity(cache, pdf_provenance, epub_provenance))
    checks.append(_check_cache_unmodified(cache, pdf_provenance, epub_provenance))
    checks.append(_check_block_accounting(pdf_provenance, epub_provenance))
    checks.append(_check_block_coverage(cache, pdf_provenance))
    checks.append(_check_format_consistency(pdf_provenance, epub_provenance))
    checks.append(_check_reading_order(cache, reconstruction, pdf_provenance,
                                       epub_path, pdf_pages))
    checks.append(_check_image_integrity(cache, pdf_provenance, epub_path))
    checks.append(_check_caption_association(cache, pdf_provenance))
    checks.append(_check_exclusions(pdf_provenance))
    checks.append(_check_page_mapping(cache, pdf_provenance))
    checks.append(_check_review_status(pdf_provenance, epub_provenance))
    checks.append(Check(id="reader_check", description="A reader application opened the artifacts",
                        status="pending",
                        detail="Not performed by the offline build; visual acceptance is a "
                               "separate human decision."))
    contact_sheet = _contact_sheet_path(output_dir)
    sheet_status, sheet_detail = _build_contact_sheet(cache, contact_sheet)
    checks.append(Check(id="contact_sheet", description="Local source-page contact sheet",
                        status=sheet_status, detail=sheet_detail))

    output_dir.mkdir(parents=True, exist_ok=True)
    _copy(pdf_path, output_dir / "pdf" / "preview.pdf")
    _copy(pdf_dir / "preview.provenance.json", output_dir / "pdf" / "preview.provenance.json")
    _copy(epub_path, output_dir / "epub" / "preview.epub")
    _copy(epub_dir / "preview.provenance.json", output_dir / "epub" / "preview.provenance.json")

    failures = tuple(check.id for check in checks if check.status == "fail")
    pending = tuple(check.id for check in checks if check.status == "pending")
    passed = not failures
    artifacts = _artifact_hashes(output_dir, exclude={"report.md", "checks.json",
                                                      "manifest.json"})
    report_path = output_dir / "report.md"
    report_path.write_text(_report(cache, reconstruction, checks, pdf_provenance,
                                   epub_provenance, artifacts, pdf_pages),
                           encoding="utf-8")
    manifest_path = output_dir / "manifest.json"
    write_json_atomic(manifest_path, {
        "schema_version": SCHEMA_VERSION,
        "generator": "src.core.mineru.acceptance",
        "files": artifacts,
    })
    checks_path = output_dir / "checks.json"
    write_json_atomic(checks_path, {
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if passed else "failed",
        "cache": {
            "root": str(cache.root),
            "source_sha256": cache.source_sha256,
            "sample_sha256": cache.sample_sha256,
            "sample_pages": list(cache.source_pages),
            "source_total_pages": cache.source_total_pages,
        },
        "checks": [{"id": check.id, "description": check.description,
                    "status": check.status, "detail": check.detail} for check in checks],
        "failures": list(failures),
        "pending": list(pending),
        "artifacts": artifacts,
        "limits": [
            f"{len(cache.source_pages)} of the source book's {cache.source_total_pages} "
            "pages are covered; whole-book order is not proven.",
            "The previews reproduce recognised content, not translation quality.",
            "Tables, formulas and image redrawing are outside this slice.",
            "No reader application was opened and no epubcheck run occurred.",
        ],
    })
    return AcceptanceResult(
        output_dir=output_dir,
        report_path=report_path,
        checks_path=checks_path,
        manifest_path=manifest_path,
        contact_sheet_path=contact_sheet,
        passed=passed,
        failures=failures,
        pending=pending,
        checks=tuple(checks),
    )


def _read_provenance(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise MineruExportError(f"Missing preview provenance: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _check_artifacts(pdf_path: Path, epub_path: Path) -> Check:
    missing = [str(path) for path in (pdf_path, epub_path) if path.stat().st_size == 0]
    return Check("artifacts_present", "Both preview artifacts exist and are non-empty",
                 "fail" if missing else "pass",
                 f"empty or missing: {', '.join(missing)}" if missing
                 else f"PDF {pdf_path.stat().st_size} bytes; EPUB {epub_path.stat().st_size} bytes")


def _check_provenance_identity(cache: MineruCache, pdf: Mapping[str, Any],
                               epub: Mapping[str, Any]) -> Check:
    problems = []
    for label, payload in (("pdf", pdf), ("epub", epub)):
        source = payload.get("source", {})
        if source.get("sample_sha256") != cache.sample_sha256:
            problems.append(f"{label} sample hash differs")
        if source.get("sha256") != cache.source_sha256:
            problems.append(f"{label} source hash differs")
        if list(source.get("sample_pages", [])) != list(cache.source_pages):
            problems.append(f"{label} sample pages differ")
        expected_format = "pdf" if label == "pdf" else "epub"
        if payload.get("artifact", {}).get("format") != expected_format:
            problems.append(f"{label} artifact format is not {expected_format}")
        if payload.get("artifact", {}).get("complete_book") is not False:
            problems.append(f"{label} claims a complete book")
    return Check("provenance_identity", "Both provenance files describe the accepted sample",
                 "fail" if problems else "pass",
                 "; ".join(problems) if problems else "source and sample identity match")


def _check_cache_unmodified(cache: MineruCache, pdf: Mapping[str, Any],
                            epub: Mapping[str, Any]) -> Check:
    recorded = pdf.get("source", {}).get("cache_fingerprints", {})
    problems = []
    if recorded != epub.get("source", {}).get("cache_fingerprints", {}):
        problems.append("the two provenance files record different cache fingerprints")
    for name, digest in recorded.items():
        path = cache.root / name
        if not path.is_file():
            problems.append(f"{name} is missing")
        elif _sha256(path) != digest:
            problems.append(f"{name} changed")
    return Check("cache_unmodified", "Cache files still match the recorded fingerprints",
                 "fail" if problems else "pass",
                 "; ".join(problems) if problems else f"{len(recorded)} cache files unchanged")


def _check_block_accounting(pdf: Mapping[str, Any], epub: Mapping[str, Any]) -> Check:
    problems = []
    for label, payload in (("pdf", pdf), ("epub", epub)):
        counts = payload.get("counts", {})
        if counts.get("blocks_accounted") != counts.get("blocks_seen"):
            problems.append(f"{label} accounts for {counts.get('blocks_accounted')} of "
                            f"{counts.get('blocks_seen')} blocks")
        if counts.get("blocks_unaccounted"):
            problems.append(f"{label} reports {counts['blocks_unaccounted']} unaccounted blocks")
    return Check("block_accounting", "Every recognised block is emitted, embedded or excluded",
                 "fail" if problems else "pass",
                 "; ".join(problems) if problems
                 else f"{pdf['counts']['blocks_seen']} blocks accounted for")


def _check_block_coverage(cache: MineruCache, pdf: Mapping[str, Any]) -> Check:
    seen: Dict[str, int] = {}
    for block in cache.blocks:
        seen[block.type] = seen.get(block.type, 0) + 1
    emitted: Dict[str, int] = {}
    for paragraph in pdf.get("paragraphs", []):
        kind = paragraph.get("source_type", "")
        if kind in _CONTENT_TYPES:
            emitted[kind] = emitted.get(kind, 0) + 1
    excluded: Dict[str, int] = {}
    for exclusion in pdf.get("exclusions", []):
        kind = exclusion.get("source_type", "")
        excluded[kind] = excluded.get(kind, 0) + 1
    problems = []
    rows = []
    for content_type in _CONTENT_TYPES:
        total = seen.get(content_type, 0)
        represented = emitted.get(content_type, 0) + excluded.get(content_type, 0)
        rows.append(f"{content_type} {represented}/{total}")
        if represented != total:
            problems.append(f"{content_type} represents {represented} of {total}")
    images = len([image for image in pdf.get("images", [])
                  if image.get("kind") == "image"])
    if images != seen.get("image", 0):
        problems.append(f"images {images}/{seen.get('image', 0)}")
    preserved = {kind: sum(1 for image in pdf.get("images", [])
                           if image.get("kind") == kind)
                 for kind in _PRESERVED_KINDS.values()}
    for block_type, kind in _PRESERVED_KINDS.items():
        total = seen.get(block_type, 0)
        represented = preserved.get(kind, 0)
        rows.append(f"{block_type} {represented}/{total}")
        if represented != total:
            problems.append(f"{block_type} represents {represented} of {total}")
    return Check("block_coverage", "Each recognised content type is represented or excluded",
                 "fail" if problems else "pass",
                 "; ".join(problems) if problems else ", ".join(rows))


def _check_format_consistency(pdf: Mapping[str, Any], epub: Mapping[str, Any]) -> Check:
    problems = []
    for key in ("blocks_seen", "blocks_accounted", "paragraphs", "images", "excluded"):
        if pdf.get("counts", {}).get(key) != epub.get("counts", {}).get(key):
            problems.append(f"counts.{key} differs")
    if pdf.get("page_map") != epub.get("page_map"):
        problems.append("page maps differ")
    return Check("format_consistency", "PDF and EPUB describe the same content and mapping",
                 "fail" if problems else "pass",
                 "; ".join(problems) if problems else "counts and page maps agree")


def _check_review_status(pdf: Mapping[str, Any], epub: Mapping[str, Any]) -> Check:
    flagged = [label for label, payload in (("PDF", pdf), ("EPUB", epub))
               if payload.get("review_required")]
    if flagged:
        return Check("review_status", "Structural review findings are resolved", "pending",
                     f"Review required in: {', '.join(flagged)}")
    return Check("review_status", "Structural review findings are resolved", "pass",
                 "No structural review findings")


def _check_reading_order(cache: MineruCache, reconstruction: Reconstruction,
                         pdf: Mapping[str, Any], epub_path: Path,
                         pdf_pages: Mapping[int, int]) -> Check:
    expected = [_normalise(text) for text in reconstruction.paragraphs]
    missing_pdf = [index for index in range(len(expected))
                   if expected[index] and index not in pdf_pages]
    epub_paragraphs = [_normalise(text) for text in _epub_paragraphs(epub_path)]
    epub_ok = epub_paragraphs == [text for text in expected if text]

    # Independent of the adapter: compare the model order with the raw block order.
    block_order: Dict[Tuple[Any, ...], int] = {}
    for position, block in enumerate(cache.blocks):
        if block.text.strip():
            block_order[(block.page_index, _bbox_key(block.bbox),
                         _sha256_text(block.text.strip()))] = position
    previous = -1
    regressions = []
    page_sequence = []
    for paragraph in pdf.get("paragraphs", []):
        key = (paragraph.get("sample_page"), _bbox_key(paragraph.get("bbox")),
               paragraph.get("text_sha256"))
        position = block_order.get(key)
        if position is not None:
            if position < previous:
                regressions.append(paragraph.get("output_index"))
            previous = position
        index = paragraph.get("output_index")
        if isinstance(index, int) and index in pdf_pages:
            page_sequence.append(pdf_pages[index])
    if page_sequence != sorted(page_sequence):
        regressions.append("PDF page sequence")

    problems = []
    if missing_pdf:
        problems.append(f"PDF does not contain paragraphs {missing_pdf[:5]}")
    if not epub_ok:
        problems.append("EPUB paragraph sequence differs")
    if regressions:
        problems.append(f"model order contradicts recognised block order: {regressions[:5]}")
    if problems:
        return Check("reading_order", "Rendered order matches the recognised block order",
                     "fail", "; ".join(problems))
    pages = sorted(pdf_pages.values())
    detail = (f"{len(expected)} paragraphs in order; EPUB sequence matches; "
              f"PDF pages {pages[0]}-{pages[-1]}" if pages
              else f"{len(expected)} paragraphs in order; EPUB sequence matches")
    return Check("reading_order", "Rendered order matches the recognised block order",
                 "pass", detail)


def _check_image_integrity(cache: MineruCache, pdf: Mapping[str, Any],
                           epub_path: Path) -> Check:
    problems = []
    for image in pdf.get("images", []):
        path = cache.root / str(image.get("image_path"))
        if not path.is_file():
            problems.append(f"{image.get('image_path')} missing from the cache")
        elif _sha256(path) != image.get("image_sha256"):
            problems.append(f"{image.get('image_path')} hash differs")
    if pdf.get("pdf", {}).get("image_count") != len(pdf.get("images", [])):
        problems.append("PDF image count differs from provenance")
    epub_images = _epub_image_files(epub_path)
    expected_names = {f"OEBPS/{image_resource_name(str(image.get('image_path')), str(image.get('image_sha256')))}"
                      for image in pdf.get("images", [])}
    if not expected_names.issubset(set(epub_images)):
        problems.append("EPUB is missing image resources")
    return Check("image_integrity", "Every image instance resolves to an unchanged local asset",
                 "fail" if problems else "pass",
                 "; ".join(problems) if problems
                 else f"{len(pdf.get('images', []))} image instances verified")


def _check_caption_association(cache: MineruCache, pdf: Mapping[str, Any]) -> Check:
    paragraphs = pdf.get("paragraphs", [])
    images = {(image.get("sample_page"), tuple(image.get("bbox") or [])): image
              for image in pdf.get("images", [])}
    problems = []
    captions = 0
    credits = 0
    for block in cache.blocks:
        if block.type != "image":
            continue
        image = images.get((block.page_index, tuple(block.bbox)))
        if image is None:
            problems.append(f"page {block.page_index} image has no provenance")
            continue
        anchor = image.get("anchor_index", -1)
        if block.image_caption:
            captions += 1
            if not _paragraph_after(paragraphs, block.page_index, anchor,
                                    "image_caption"):
                problems.append(f"page {block.page_index} caption is not attached")
        if block.image_footnote:
            credits += 1
            if not _paragraph_after(paragraphs, block.page_index, anchor,
                                    "image_footnote"):
                problems.append(f"page {block.page_index} image credit is not attached")
    detail = (f"{captions} caption run(s), {credits} image credit(s); "
              f"{len(images)} image instance(s) traced")
    return Check("caption_association", "Caption and credit runs follow their figure",
                 "fail" if problems else "pass",
                 "; ".join(problems) if problems else detail)


def _paragraph_after(paragraphs: Sequence[Mapping[str, Any]], sample_page: int,
                     anchor: int, source_type: str) -> bool:
    return any(paragraph.get("source_type") == source_type
               and paragraph.get("sample_page") == sample_page
               and anchor < int(paragraph.get("output_index", -1)) <= anchor + 3
               for paragraph in paragraphs)


def _check_exclusions(pdf: Mapping[str, Any]) -> Check:
    problems = []
    for exclusion in pdf.get("exclusions", []):
        if not str(exclusion.get("reason", "")).strip():
            problems.append(f"page {exclusion.get('sample_page')} exclusion has no reason")
    if len(pdf.get("exclusions", [])) != pdf.get("counts", {}).get("excluded"):
        problems.append("exclusion count differs from provenance counts")
    return Check("exclusions_justified", "Every excluded block has a recorded reason",
                 "fail" if problems else "pass",
                 "; ".join(problems) if problems
                 else f"{len(pdf.get('exclusions', []))} exclusions justified")


def _check_page_mapping(cache: MineruCache, pdf: Mapping[str, Any]) -> Check:
    page_map = pdf.get("page_map", [])
    pages = [entry.get("source_page") for entry in page_map]
    indices = [entry.get("sample_index") for entry in page_map]
    problems = []
    if pages != list(cache.source_pages):
        problems.append(f"source pages {pages} differ from {list(cache.source_pages)}")
    if indices != list(range(len(page_map))):
        problems.append("sample indices are not contiguous")
    return Check("source_page_mapping", "Sample indices map to the recorded source pages",
                 "fail" if problems else "pass",
                 "; ".join(problems) if problems else f"sample pages {pages}")


def _pdf_paragraph_pages(pdf_path: Path, paragraphs: Sequence[str]) -> Dict[int, int]:
    """Locate each paragraph's first occurrence and return its 1-based PDF page."""
    import pymupdf

    with pymupdf.open(pdf_path) as document:
        texts = [_normalise(page.get_text()) for page in document]
    offsets: List[int] = []
    position = 0
    for text in texts:
        offsets.append(position)
        position += len(text) + 1  # one joining space between pages
    full = " ".join(texts)
    pages: Dict[int, int] = {}
    cursor = 0
    for index, paragraph in enumerate(paragraphs):
        needle = _normalise(paragraph)
        if not needle:
            continue
        position = full.find(needle, cursor)
        if position < 0:
            continue
        pages[index] = bisect_right(offsets, position)
        cursor = position + len(needle)
    return pages


def _epub_paragraphs(path: Path) -> List[str]:
    with zipfile.ZipFile(path) as archive:
        opf = ElementTree.fromstring(archive.read("OEBPS/content.opf"))
        manifest = {item.get("id"): item.get("href")
                    for item in opf.find(f"{OPF}manifest")}
        order = [ref.get("idref") for ref in opf.find(f"{OPF}spine")]
        texts = []
        for item_id in order:
            document = ElementTree.fromstring(archive.read(f"OEBPS/{manifest[item_id]}"))
            for element in document.iter():
                if element.tag in _PARAGRAPH_TAGS:
                    texts.append("".join(element.itertext()))
        return texts


def _epub_image_files(path: Path) -> List[str]:
    with zipfile.ZipFile(path) as archive:
        return [name for name in archive.namelist()
                if name.startswith("OEBPS/images/") and not name.endswith("/")]


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def _bbox_key(bbox: Any) -> Tuple[float, ...]:
    return tuple(round(float(value), 3) for value in (bbox or []))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _contact_sheet_path(output_dir: Path) -> Path:
    return output_dir / "contact-sheet.jpg"


def _build_contact_sheet(cache: MineruCache, destination: Path) -> Tuple[str, str]:
    source = _source_pdf(cache)
    if source is None:
        return "fail", "No sample PDF is available for the required contact sheet."
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        _render_contact_sheet(cache, source, destination)
    except Exception as exc:  # rendering must never fake success
        return "fail", f"Contact sheet rendering failed: {type(exc).__name__}"
    return "pass", f"{len(cache.source_pages)} source pages rendered from {source.name}"


def _source_pdf(cache: MineruCache) -> Optional[Path]:
    candidates = [cache.root / "sample.pdf"]
    candidates.extend(sorted((cache.root / "result").glob("*_origin.pdf")))
    return next((path for path in candidates if path.is_file()), None)


def _render_contact_sheet(cache: MineruCache, source: Path, destination: Path) -> None:
    import pymupdf
    from PIL import Image, ImageDraw

    pages = []
    with pymupdf.open(source) as document:
        for index in range(min(document.page_count, len(cache.source_pages))):
            pixmap = document[index].get_pixmap(matrix=pymupdf.Matrix(0.6, 0.6),
                                                colorspace=pymupdf.csRGB, alpha=False)
            pages.append((cache.source_pages[index],
                          Image.frombytes("RGB", (pixmap.width, pixmap.height),
                                          pixmap.samples)))
    if not pages:
        raise ValueError("the sample PDF has no renderable page")
    width = max(image.width for _, image in pages)
    height = max(image.height for _, image in pages) + 24
    columns = min(3, len(pages))
    rows = (len(pages) + columns - 1) // columns
    sheet = Image.new("RGB", (width * columns, height * rows), "#eeeeee")
    draw = ImageDraw.Draw(sheet)
    for index, (source_page, image) in enumerate(pages):
        x, y = (index % columns) * width, (index // columns) * height
        draw.text((x + 8, y + 5), f"Source PDF page {source_page}", fill="black")
        sheet.paste(image, (x, y + 22))
    sheet.save(destination, format="JPEG", quality=85)


def _artifact_hashes(root: Path, exclude: Iterable[str]) -> Dict[str, str]:
    excluded = set(exclude)
    files: Dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        files[relative] = _sha256(path)
    return files


def _copy(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _report(cache: MineruCache, reconstruction: Reconstruction, checks: Sequence[Check],
            pdf: Mapping[str, Any], epub: Mapping[str, Any],
            artifacts: Mapping[str, str], pdf_pages: Mapping[int, int]) -> str:
    counts = pdf.get("counts", {})
    lines = [
        "# MinerU Online Reconstruction Acceptance Package",
        "",
        f"Sample: source PDF pages {_page_list(cache.source_pages)} "
        f"({len(cache.source_pages)} of {cache.source_total_pages} pages). "
        "Generated offline from the cached recognition result; no provider call, "
        "upload or translation LLM was used.",
        "",
        "This package proves transport, resource integrity, block accounting, "
        "rendering order and package structure. It does **not** prove translation "
        "quality, whole-book completeness, table/formula handling or image "
        "redrawing. Five sample pages cannot establish whole-book reading order.",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for check in checks:
        lines.append(f"| {check.id} | {check.status} | {_md(check.detail)} |")
    lines.extend([
        "",
        "## Content accounting",
        "",
        f"- Blocks seen: {counts.get('blocks_seen')}; accounted for: "
        f"{counts.get('blocks_accounted')}; unaccounted: {counts.get('blocks_unaccounted')}.",
        f"- Paragraphs: PDF {pdf.get('pdf', {}).get('paragraph_count')}, "
        f"EPUB {epub.get('epub', {}).get('paragraphs')}.",
        f"- Images: {counts.get('images')}; exclusions: {counts.get('excluded')}; "
        f"empty records: {counts.get('empty_records')}.",
        "",
        "## Page mapping",
        "",
        "Source pages, sample indices and reconstructed positions are distinct:",
        "",
        "| Sample index | Source PDF page | Model paragraph range | Reconstructed PDF page(s) |",
        "| --- | --- | --- | --- |",
    ])
    for entry in pdf.get("page_map", []):
        sample_index = entry.get("sample_index")
        indices = [item.get("output_index") for item in pdf.get("paragraphs", [])
                   if item.get("sample_page") == sample_index]
        span = f"{min(indices)}-{max(indices)}" if indices else "none"
        positions = sorted({pdf_pages[item.get("output_index")]
                            for item in pdf.get("paragraphs", [])
                            if item.get("sample_page") == sample_index
                            and item.get("output_index") in pdf_pages})
        position_span = f"{positions[0]}-{positions[-1]}" if positions else "none"
        lines.append(f"| {sample_index} | {entry.get('source_page')} | {span} | "
                     f"{position_span} |")

    lines.extend(["", "## Excluded content", "",
                  "| Source type | Text | Source page | Reason |",
                  "| --- | --- | --- | --- |"])
    for exclusion in pdf.get("exclusions", []):
        lines.append(f"| {exclusion.get('source_type')} | {_md(exclusion.get('text'))} | "
                     f"{exclusion.get('source_page')} | {_md(exclusion.get('reason'))} |")

    lines.extend(["", "## Findings", "",
                  "| Code | Severity | Page | Message |",
                  "| --- | --- | --- | --- |"])
    for finding in pdf.get("findings", []):
        lines.append(f"| {finding.get('code')} | {finding.get('severity')} | "
                     f"{finding.get('sample_page')} | {_md(finding.get('message'))} |")

    lines.extend(["", "## Images", "",
                  "| Cache path | Source page | SHA-256 (first 12) |",
                  "| --- | --- | --- |"])
    for image in pdf.get("images", []):
        lines.append(f"| {_md(image.get('image_path'))} | {image.get('source_page')} | "
                     f"{str(image.get('image_sha256'))[:12]} |")

    lines.extend([
        "",
        "## Human review",
        "",
        "- Reader-open check: **not performed**. The build does not open a reader "
        "application and did not run `epubcheck`.",
        "- Visual and semantic acceptance: **pending**. Inspect the PDF, open the "
        "EPUB in a reader, and compare expression preservation against the contact "
        "sheet and the source pages.",
        "- Automated checks are necessary but not sufficient: file size, word counts "
        "or successful rendering are not proof of fidelity.",
        "",
        "## Limitations",
        "",
        f"- The sample covers {len(cache.source_pages)} of the book's "
        f"{cache.source_total_pages} pages; whole-book reading order, completeness "
        "and translation quality are not established. The previews are not a "
        "complete book.",
        "- Reflowed layouts legitimately change page counts and line breaks; "
        "positional equality with the source is not required.",
        "- Tables, formulas and image redrawing are outside this slice.",
        "- The previews are untranslated; they identify themselves as partial previews.",
        "",
        "## Evidence files",
        "",
        "| File | SHA-256 |",
        "| --- | --- |",
    ])
    for name, digest in artifacts.items():
        lines.append(f"| {name} | {digest} |")
    lines.append("")
    return "\n".join(lines)


def _page_list(pages: Sequence[int]) -> str:
    if len(pages) == 1:
        return str(pages[0])
    return ", ".join(str(page) for page in pages[:-1]) + f" and {pages[-1]}"


def _md(value: Any) -> str:
    text = html.escape(str(value if value is not None else ""), quote=False)
    return text.replace("|", "\\|").replace("\n", " ")
