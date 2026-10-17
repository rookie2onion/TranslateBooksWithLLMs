"""Validation, whole-book accounting and completion assessment for a PDF.

A translated PDF is publishable only after it passes :func:`validate_pdf_output`:
the file exists, opens, has at least one page, contains text, and carries neither
the preview notice nor the preview title suffix nor an invented author.

The accounting sidecar records what actually completed — source identity,
recognition identity and timing, exact source-page mapping (including empty
recognized pages), recognized/retained/excluded block accounting, images and
their caption/note associations, source-preserved content, translation counters
and the output fingerprint — next to the finished book, outside the pruned
working cache.

:func:`assess_pdf_completion` is the honest completion gate: a published PDF is
only reported as a completed whole book when its durable report proves exact
source-page coverage, complete block accounting and a complete translated body.
The report also records what accounting does *not* prove: recognition accuracy
and translation of text inside source-preserved images.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from src.core.common.plain_text_checkpoint import paragraph_mapping_sha256
from src.core.mineru.errors import MineruOutputInvalid

from .content import PdfPlainContent

ACCOUNTING_KIND = "translated_pdf_accounting"
ACCOUNTING_SCHEMA_VERSION = 1
ACCOUNTING_SUFFIX = ".accounting.json"

# Preview-only markers that must never appear in a production rendition.
_PREVIEW_TEXT_MARKERS = (
    "untranslated mineru reconstruction preview",
    "untranslated mineru sample preview",
)

# The text fields a review limitation may carry; kept short because the report
# is a durable artifact next to the finished book.
_EXCLUSION_TEXT_LIMIT = 200


@dataclass(frozen=True)
class PdfOutputStats:
    """Measured properties of a validated translated PDF."""

    page_count: int
    text_chars: int
    image_count: int
    bytes: int
    sha256: str


@dataclass(frozen=True)
class PdfCompletionAssessment:
    """Whether a published PDF/report proves whole-book completion.

    ``complete`` is False for a missing/stale report, a structurally invalid
    output, incomplete page/block coverage or an unfinished translated body.
    ``reason`` is a stable machine-readable category and ``message`` is the
    English detail safe to surface (never a credential or a server path).
    """

    complete: bool
    reason: str = ""
    message: str = ""


def accounting_path_for(output_path: Path) -> Path:
    """Return the sidecar path that belongs to ``output_path``."""
    return Path(str(output_path) + ACCOUNTING_SUFFIX)


def validate_pdf_output(
    output_path: Path,
    *,
    expected_title: str = "",
    expected_author: str = "",
    expected_paragraphs: int = 0,
    min_text_chars: int = 1,
) -> PdfOutputStats:
    """Prove the generated PDF is a complete, preview-free rendition."""
    path = Path(output_path)
    if not path.is_file():
        raise MineruOutputInvalid("The translated PDF was not written.")
    size = path.stat().st_size
    if size <= 0:
        raise MineruOutputInvalid("The translated PDF is empty.")

    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - PyMuPDF is a project dependency
        raise MineruOutputInvalid("PDF support is not installed (missing pymupdf).") from exc

    document = None
    try:
        try:
            document = pymupdf.open(str(path), filetype="pdf")
        except Exception as exc:
            raise MineruOutputInvalid("The generated PDF cannot be opened.") from exc
        page_count = document.page_count
        if page_count < 1:
            raise MineruOutputInvalid("The generated PDF has no pages.")
        metadata = document.metadata or {}
        title = str(metadata.get("title") or "")
        author = str(metadata.get("author") or "")
        text = "".join(page.get_text() for page in document)
        image_count = sum(len(page.get_images()) for page in document)
    finally:
        if document is not None:
            try:
                document.close()
            except Exception:  # pragma: no cover - close errors are never fatal
                pass

    _reject_preview_markers(title=title, author=author, text=text)
    if expected_title and title != expected_title:
        raise MineruOutputInvalid(
            "The generated PDF metadata title does not match the translated book.")
    if author != expected_author:
        raise MineruOutputInvalid(
            "The generated PDF metadata carries an unexpected author.")
    if expected_paragraphs > 0 and len(text.strip()) < max(1, int(min_text_chars)):
        raise MineruOutputInvalid(
            "The generated PDF contains no translated text.")

    return PdfOutputStats(
        page_count=page_count,
        text_chars=len(text),
        image_count=image_count,
        bytes=size,
        sha256=_sha256_file(path),
    )


def build_accounting(
    *,
    recognition: Any,
    content: PdfPlainContent,
    translation_stats: Mapping[str, Any],
    output_stats: PdfOutputStats,
    output_filename: str,
    source_language: str,
    target_language: str,
    bilingual: bool,
    budget_seconds: float,
) -> Dict[str, Any]:
    """Build the durable report of one completed translated-PDF generation."""
    stats = dict(translation_stats or {})
    total = int(stats.get("total_chunks") or 0)
    completed = int(stats.get("completed_chunks") or 0)
    failed = int(stats.get("failed_chunks") or 0)
    unfinished = stats.get("unfinished_chunks")
    if unfinished is None:
        unfinished = max(0, total - completed)
    unfinished = int(unfinished or 0)
    body_complete = failed == 0 and unfinished == 0

    source = getattr(recognition, "admitted", None)
    cache = getattr(recognition, "cache", None)
    source_view = getattr(recognition, "source", None)
    counts = dict(getattr(source_view, "counts", {}) or {})
    provenance = tuple(getattr(source_view, "provenance", ()) or ())
    captions = sum(1 for item in provenance if getattr(item, "kind", "") == "caption")
    footnotes = sum(1 for item in provenance if getattr(item, "kind", "") == "footnote")
    findings = [getattr(item, "code", "") for item in
                (getattr(source_view, "findings", ()) or ())]

    # Ordinary figures and source-preserved table/formula images share the
    # anchored image list in the renderer; count them separately here and never
    # mix them into the translated-text or failed-chunk counters.
    images = [image for items in content.images_by_paragraph.values() for image in items]
    figure_count = sum(1 for image in images if not getattr(image, "label", ""))
    preserved_from_content = sum(1 for image in images
                                 if getattr(image, "label", ""))
    source_preserved = int(counts.get("source_preserved", preserved_from_content) or 0)
    tables = int(counts.get("tables", 0) or 0)
    formulas = int(counts.get("formulas", 0) or 0)

    coverage = _build_coverage(recognition, source_view, content)
    exclusions = _exclusion_records(source_view)
    image_records = _image_records(source_view)
    review_findings = _review_findings(source_view)
    review_required = bool(getattr(source_view, "review_required", False))
    identity = {
        "paragraph_count": len(content.paragraphs_text),
        "paragraph_mapping_sha256": paragraph_mapping_sha256(
            list(content.paragraphs_text)),
    }

    return {
        "schema_version": ACCOUNTING_SCHEMA_VERSION,
        "kind": ACCOUNTING_KIND,
        "generated_at": _now(),
        "source": {
            "file_name": getattr(source, "file_name", ""),
            "sha256": getattr(source, "sha256", ""),
            "bytes": int(getattr(source, "size_bytes", 0) or 0),
            "pages": int(getattr(source, "page_count", 0) or 0),
        },
        "recognition": {
            "provider": "mineru-online",
            "requested_model": "vlm",
            "returned_backend": getattr(cache, "backend", ""),
            "returned_version": getattr(cache, "engine_version", ""),
            "batch_id": getattr(recognition, "batch_id", ""),
            "result_zip_sha256": getattr(recognition, "result_zip_sha256", ""),
            "result_cache_sha256": getattr(recognition, "result_cache_sha256", ""),
            "pages": int(getattr(recognition, "page_count", 0) or 0),
            "reused_validated_result": bool(getattr(recognition, "reused", False)),
            "elapsed_seconds": round(float(getattr(recognition, "elapsed_seconds", 0.0) or 0.0), 3),
            "retries": int(getattr(recognition, "retries", 0) or 0),
            "remote_states": list(getattr(recognition, "remote_states", ()) or ()),
            "budget_seconds": float(budget_seconds),
        },
        "coverage": coverage,
        "source_content": {
            "blocks_seen": int(counts.get("blocks_seen", 0) or 0),
            "blocks_accounted": int(counts.get("blocks_accounted", 0) or 0),
            "blocks_unaccounted": int(counts.get("blocks_unaccounted", 0) or 0),
            "paragraphs": len(content.paragraphs_text),
            "images": figure_count,
            # Deliberately preserved source images, counted separately from both
            # translated text and failed translation chunks.
            "source_preserved": source_preserved,
            "tables": tables,
            "formulas": formulas,
            "captions": captions,
            "footnotes": footnotes,
            "excluded": int(counts.get("excluded", len(exclusions)) or 0),
            "empty_pages": len(coverage["empty_pages"]),
            "exclusions": exclusions,
            "content_identity": identity,
            "review_required": review_required,
            "review_findings": review_findings,
            "findings": findings,
        },
        "images": image_records,
        "translation": {
            "source_language": source_language,
            "target_language": target_language,
            "bilingual": bool(bilingual),
            "total_chunks": total,
            "completed_chunks": completed,
            "failed_chunks": failed,
            "fallback_used": int(stats.get("fallback_used") or 0),
            "unfinished_chunks": unfinished,
            "complete": body_complete,
        },
        "output": {
            "file_name": os.path.basename(output_filename),
            "bytes": output_stats.bytes,
            "sha256": output_stats.sha256,
            "pages": output_stats.page_count,
            "text_chars": output_stats.text_chars,
            "images": output_stats.image_count,
        },
        "claims": {
            "whole_book_coverage": coverage["complete"],
            "recognition_accuracy_proven": False,
            "every_visible_word_translated": False,
        },
        "limitations": {
            "recognition_accuracy_proven": False,
            "every_visible_word_translated": False,
            "review_required": review_required,
            "statements": [
                "The accounting proves exact source-page coverage, recognized "
                "block accounting and completion of the translated body for "
                "recognized text. It does not prove recognition accuracy.",
                "Text inside source-preserved images (tables, formulas and image "
                "pixels) remains untranslated.",
            ],
        },
    }


def write_accounting_sidecar(output_path: Path, accounting: Mapping[str, Any]) -> Path:
    """Write the sidecar atomically next to the finished book."""
    path = accounting_path_for(output_path)
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(dict(accounting), stream, ensure_ascii=False, indent=2)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:  # pragma: no cover - fsync support varies
                pass
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best-effort cleanup
            pass
    return path


def read_accounting(output_path: Path) -> Optional[Dict[str, Any]]:
    """Read the sidecar for a finished output, or None when there is none."""
    path = accounting_path_for(output_path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def read_accounting_summary(output_path: Path) -> Optional[Dict[str, Any]]:
    """Compact, browser-safe description of what actually completed.

    Returns None when the output itself is missing: a sidecar without its
    translated book must not be presented as a successful result. Older schema-1
    sidecars (written before whole-book coverage was recorded) remain readable;
    the coverage fields are then ``None`` instead of being invented.
    """
    if not Path(output_path).is_file():
        return None
    accounting = read_accounting(output_path)
    if accounting is None:
        return None
    source = accounting.get("source") or {}
    recognition = accounting.get("recognition") or {}
    content = accounting.get("source_content") or {}
    coverage = accounting.get("coverage") or {}
    translation = accounting.get("translation") or {}
    output = accounting.get("output") or {}
    limitations = accounting.get("limitations") or {}
    empty_pages = coverage.get("empty_pages")
    if isinstance(empty_pages, list):
        empty_pages = len(empty_pages)
    elif empty_pages is None:
        empty_pages = content.get("empty_pages")
    return {
        "source_pages": source.get("pages"),
        "result_pages": recognition.get("pages"),
        "paragraphs": content.get("paragraphs"),
        "images": content.get("images"),
        "source_preserved": content.get("source_preserved"),
        "tables": content.get("tables"),
        "formulas": content.get("formulas"),
        "captions": content.get("captions"),
        "footnotes": content.get("footnotes"),
        "excluded": content.get("excluded"),
        "failed_chunks": translation.get("failed_chunks"),
        "unfinished_chunks": translation.get("unfinished_chunks"),
        "body_complete": translation.get("complete"),
        "recognition_seconds": recognition.get("elapsed_seconds"),
        "reused_result": recognition.get("reused_validated_result"),
        "output_pages": output.get("pages"),
        "output_bytes": output.get("bytes"),
        # Whole-book coverage, added by issue #23. ``None`` means the report
        # predates it and therefore cannot prove completion on its own.
        "coverage_complete": coverage.get("complete"),
        "recognized_blocks": coverage.get("recognized_blocks"),
        "accounted_blocks": coverage.get("accounted_blocks"),
        "empty_pages": empty_pages,
        "limitations": list(limitations.get("statements") or ()),
    }


def assess_pdf_completion(output_path: Path) -> PdfCompletionAssessment:
    """Decide whether a published PDF/report proves whole-book completion."""
    path = Path(output_path)
    accounting = read_accounting(path)
    if accounting is None:
        return PdfCompletionAssessment(
            False, "missing_report",
            "No durable accounting report exists for the translated PDF.")
    if accounting.get("kind") != ACCOUNTING_KIND:
        return PdfCompletionAssessment(
            False, "missing_report",
            "The durable report is not a translated-PDF accounting report.")

    content = accounting.get("source_content") or {}
    translation = accounting.get("translation") or {}
    expected_paragraphs = int(content.get("paragraphs") or 0)
    try:
        output_stats = validate_pdf_output(
            path, expected_author="", expected_paragraphs=expected_paragraphs)
    except MineruOutputInvalid as exc:
        return PdfCompletionAssessment(False, "output_invalid", str(exc))

    output = accounting.get("output") or {}
    if (output.get("sha256") != output_stats.sha256
            or int(output.get("bytes") or -1) != output_stats.bytes):
        return PdfCompletionAssessment(
            False, "output_mismatch",
            "The accounting report does not describe the published PDF.")

    problem = _coverage_problem(accounting)
    if problem is not None:
        return PdfCompletionAssessment(False, "coverage_incomplete", problem)

    if translation.get("complete") is not True:
        return PdfCompletionAssessment(
            False, "body_incomplete",
            "The accounting report does not prove a complete translated body.")

    return PdfCompletionAssessment(True)


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------


def _build_coverage(recognition: Any, source_view: Any,
                    content: PdfPlainContent) -> Dict[str, Any]:
    """Per-source-page accounting, including empty recognized pages."""
    pages = _source_page_list(recognition, source_view)
    raw_blocks = getattr(getattr(recognition, "cache", None), "blocks", ())
    blocks = list(raw_blocks) if isinstance(raw_blocks, (list, tuple)) else []
    provenance = tuple(getattr(source_view, "provenance", ()) or ())
    exclusions = tuple(getattr(source_view, "exclusions", ()) or ())
    images_by_paragraph = getattr(source_view, "images_by_paragraph", {})
    assets = [asset for items in
              (images_by_paragraph.values()
               if isinstance(images_by_paragraph, Mapping) else ())
              for asset in (items if isinstance(items, (list, tuple)) else ())]
    counts = getattr(source_view, "counts", None)
    if not isinstance(counts, Mapping):
        counts = {}

    entries = []
    for page in pages:
        source_page = int(page["source_page"])
        sample_index = int(page["sample_index"])
        page_blocks = [block for block in blocks
                       if int(getattr(block, "page_index", -1)) == sample_index]
        page_exclusions = [item for item in exclusions
                           if getattr(item, "source_page", None) == source_page]
        page_assets = [asset for asset in assets
                       if getattr(asset, "source_page", None) == source_page]
        output_paragraphs = sum(
            1 for item in provenance
            if getattr(item, "source_page", None) == source_page
            and getattr(item, "output_index", None) is not None)
        recognized_blocks = len(page_blocks)
        excluded_blocks = len(page_exclusions)
        entries.append({
            "source_page": source_page,
            "result_page": sample_index + 1,
            "recognized_blocks": recognized_blocks,
            "output_paragraphs": output_paragraphs,
            "images": sum(1 for asset in page_assets
                          if getattr(asset, "kind", "image") == "image"),
            "source_preserved": sum(1 for asset in page_assets
                                    if getattr(asset, "kind", "image") != "image"),
            "excluded_blocks": excluded_blocks,
            "retained_blocks": max(0, recognized_blocks - excluded_blocks),
            "empty": recognized_blocks == 0,
        })

    admitted = getattr(recognition, "admitted", None)
    expected = int(getattr(admitted, "page_count", 0) or 0)
    recognized = int(getattr(recognition, "page_count", 0) or 0)
    mapped = [entry["source_page"] for entry in entries]
    duplicates = sorted({page for page in mapped if mapped.count(page) > 1})
    expected_pages = list(range(1, expected + 1))
    missing = [page for page in expected_pages if page not in set(mapped)]
    unexpected = sorted({page for page in mapped
                         if page < 1 or page > expected})

    blocks_seen = int(counts.get("blocks_seen", 0) or 0)
    blocks_accounted = int(counts.get("blocks_accounted", 0) or 0)
    blocks_unaccounted = int(
        counts.get("blocks_unaccounted", max(0, blocks_seen - blocks_accounted)) or 0)
    excluded = len(exclusions)
    empty_pages = [entry["source_page"] for entry in entries if entry["empty"]]

    complete = bool(
        expected >= 1
        and recognized == expected
        and len(entries) == expected
        and mapped == expected_pages
        and not duplicates
        and not missing
        and not unexpected
        and blocks_seen == blocks_accounted
        and blocks_unaccounted == 0
        and sum(entry["recognized_blocks"] for entry in entries) == blocks_seen
        and sum(entry["excluded_blocks"] for entry in entries) == excluded
        and int(content.page_count or 0) == expected
    )
    return {
        "expected_source_pages": expected,
        "recognized_pages": recognized,
        "result_pages": len(entries),
        "mapped_source_pages": mapped,
        "missing_source_pages": missing,
        "duplicate_source_pages": duplicates,
        "unexpected_source_pages": unexpected,
        "empty_pages": empty_pages,
        "pages": entries,
        "recognized_blocks": blocks_seen,
        "accounted_blocks": blocks_accounted,
        "unaccounted_blocks": blocks_unaccounted,
        "excluded_blocks": excluded,
        "retained_blocks": max(0, blocks_accounted - excluded),
        "complete": complete,
    }


def _source_page_list(recognition: Any, source_view: Any) -> Sequence[Dict[str, int]]:
    raw_page_map = getattr(source_view, "page_map", ())
    page_map = tuple(raw_page_map) if isinstance(raw_page_map, (list, tuple)) else ()
    pages = []
    for index, page in enumerate(page_map):
        pages.append({
            "sample_index": int(getattr(page, "sample_index", index)),
            "source_page": int(getattr(page, "source_page", index + 1)),
        })
    if pages:
        return pages
    # Minimal/legacy callers may not expose the page map. The admitted page
    # count is the only honest fallback, and the coverage verdict will still be
    # false unless every page carries block counts.
    admitted = getattr(recognition, "admitted", None)
    expected = int(getattr(admitted, "page_count", 0) or 0)
    return [{"sample_index": index, "source_page": index + 1}
            for index in range(expected)]


def _exclusion_records(source_view: Any) -> list[Dict[str, Any]]:
    records = []
    for item in (getattr(source_view, "exclusions", ()) or ()):
        text = str(getattr(item, "text", "") or "")
        records.append({
            "kind": getattr(item, "kind", ""),
            "source_type": getattr(item, "source_type", ""),
            "source_page": getattr(item, "source_page", None),
            "sample_page": getattr(item, "sample_page", None),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "text": text[:_EXCLUSION_TEXT_LIMIT],
            "reason": getattr(item, "reason", ""),
        })
    return records


def _image_records(source_view: Any) -> list[Dict[str, Any]]:
    """One record per recognized image instance, with its association links."""
    provenance = tuple(getattr(source_view, "provenance", ()) or ())
    records = []
    for anchor, assets in (getattr(source_view, "images_by_paragraph", {}) or {}).items():
        for asset in assets:
            block_index = getattr(asset, "block_index", -1)
            linked = [item for item in provenance
                      if getattr(item, "block_index", None) == block_index]
            records.append({
                "kind": getattr(asset, "kind", "image"),
                "label": getattr(asset, "label", ""),
                "sha256": getattr(asset, "sha256", ""),
                "source_page": getattr(asset, "source_page", None),
                "sample_page": getattr(asset, "sample_page", None),
                "anchor_index": anchor,
                "block_index": block_index,
                "width_pt": round(float(getattr(asset, "width_pt", 0.0) or 0.0), 3),
                "height_pt": round(float(getattr(asset, "height_pt", 0.0) or 0.0), 3),
                "caption_output_indexes": [
                    item.output_index for item in linked
                    if getattr(item, "kind", "") == "caption"
                    and getattr(item, "output_index", None) is not None],
                "footnote_output_indexes": [
                    item.output_index for item in linked
                    if getattr(item, "kind", "") == "footnote"
                    and getattr(item, "output_index", None) is not None],
            })
    return records


def _review_findings(source_view: Any) -> list[Dict[str, Any]]:
    raw_page_map = getattr(source_view, "page_map", ())
    page_map = {getattr(page, "sample_index", None): getattr(page, "source_page", None)
                for page in (raw_page_map
                             if isinstance(raw_page_map, (list, tuple)) else ())}
    records = []
    for item in (getattr(source_view, "findings", ()) or ()):
        sample_page = getattr(item, "sample_page", None)
        records.append({
            "code": getattr(item, "code", ""),
            "message": getattr(item, "message", ""),
            "severity": getattr(item, "severity", "info"),
            "source_page": page_map.get(sample_page),
            "block_index": getattr(item, "block_index", None),
        })
    return records


def _coverage_problem(accounting: Mapping[str, Any]) -> Optional[str]:
    """Return an English limitation when the report cannot prove coverage."""
    coverage = accounting.get("coverage")
    content = accounting.get("source_content") or {}
    source = accounting.get("source") or {}
    recognition = accounting.get("recognition") or {}
    if not isinstance(coverage, Mapping):
        return "The report does not record whole-book page coverage."
    if coverage.get("complete") is not True:
        return "The report does not establish complete whole-book coverage."

    expected = _as_int(coverage.get("expected_source_pages"))
    recognized = _as_int(coverage.get("recognized_pages"))
    pages = coverage.get("pages")
    if expected < 1 or not isinstance(pages, list):
        return "The report has no usable source-page mapping."
    if not (expected == recognized == len(pages)):
        return ("The recognized page count does not match the expected source "
                "page count.")
    if _as_int(source.get("pages")) != expected:
        return "The recorded source page count does not match the coverage."
    if _as_int(recognition.get("pages")) != expected:
        return "The recorded recognition page count does not match the coverage."

    mapped = [_as_int(page.get("source_page")) for page in pages
              if isinstance(page, Mapping)]
    if len(mapped) != expected:
        return "The source-page mapping is incomplete."
    if sorted(mapped) != list(range(1, expected + 1)):
        return ("The source-page mapping is missing, duplicated or outside the "
                "expected page range.")

    blocks_seen = _as_int(coverage.get("recognized_blocks"))
    blocks_accounted = _as_int(coverage.get("accounted_blocks"))
    blocks_unaccounted = _as_int(coverage.get("unaccounted_blocks"))
    if blocks_seen != _as_int(content.get("blocks_seen")):
        return "The report's block counts disagree with the recognized content."
    if blocks_seen != _as_int(content.get("blocks_accounted")):
        return "Not every recognized block is accounted for by retained output."
    if blocks_unaccounted != 0 or blocks_accounted != blocks_seen:
        return "The report leaves recognized blocks unaccounted."
    if _as_int(content.get("blocks_unaccounted")) != 0:
        return "The report lists unaccounted recognized blocks."
    page_blocks = sum(_as_int(entry.get("recognized_blocks"))
                      for entry in pages if isinstance(entry, Mapping))
    if page_blocks != blocks_seen:
        return "The per-page block accounting does not add up."

    exclusions = content.get("exclusions")
    excluded = _as_int(content.get("excluded"))
    if not isinstance(exclusions, list) or len(exclusions) != excluded:
        return "The report does not record every justified exclusion."
    if _as_int(coverage.get("excluded_blocks")) != excluded:
        return "The exclusion total does not match the justified exclusions."
    page_excluded = sum(_as_int(entry.get("excluded_blocks"))
                        for entry in pages if isinstance(entry, Mapping))
    if page_excluded != excluded:
        return "The per-page exclusion accounting does not add up."
    return None


def _reject_preview_markers(*, title: str, author: str, text: str) -> None:
    haystack = f"{title}\n{author}\n{text}".casefold()
    for marker in _PREVIEW_TEXT_MARKERS:
        if marker in haystack:
            raise MineruOutputInvalid(
                "The generated PDF still carries preview-only text or metadata.")


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
