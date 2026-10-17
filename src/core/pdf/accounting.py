"""Validation and accounting for a generated translated PDF.

A translated PDF is publishable only after it passes :func:`validate_pdf_output`:
the file exists, opens, has at least one page, contains text, and carries neither
the preview notice nor the preview title suffix nor an invented author.

The accounting sidecar records what actually completed — source identity,
recognition identity and timing, content accounting, translation counters and the
output fingerprint — next to the finished book, outside the pruned working cache.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

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


@dataclass(frozen=True)
class PdfOutputStats:
    """Measured properties of a validated translated PDF."""

    page_count: int
    text_chars: int
    image_count: int
    bytes: int
    sha256: str


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

    source = getattr(recognition, "admitted", None)
    cache = getattr(recognition, "cache", None)
    source_view = getattr(recognition, "source", None)
    counts = dict(getattr(source_view, "counts", {}) or {})
    provenance = tuple(getattr(source_view, "provenance", ()) or ())
    captions = sum(1 for item in provenance if getattr(item, "kind", "") == "caption")
    footnotes = sum(1 for item in provenance if getattr(item, "kind", "") == "footnote")
    findings = [getattr(item, "code", "") for item in
                (getattr(source_view, "findings", ()) or ())]

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
        "source_content": {
            "blocks_seen": int(counts.get("blocks_seen", 0) or 0),
            "blocks_accounted": int(counts.get("blocks_accounted", 0) or 0),
            "blocks_unaccounted": int(counts.get("blocks_unaccounted", 0) or 0),
            "paragraphs": len(content.paragraphs_text),
            "images": sum(len(items) for items in content.images_by_paragraph.values()),
            "captions": captions,
            "footnotes": footnotes,
            "excluded": int(counts.get("excluded", 0) or 0),
            "review_required": bool(getattr(source_view, "review_required", False)),
            "findings": findings,
        },
        "translation": {
            "source_language": source_language,
            "target_language": target_language,
            "bilingual": bool(bilingual),
            "total_chunks": total,
            "completed_chunks": completed,
            "failed_chunks": failed,
            "fallback_used": int(stats.get("fallback_used") or 0),
            "unfinished_chunks": unfinished,
            "complete": failed == 0 and unfinished == 0,
        },
        "output": {
            "file_name": os.path.basename(output_filename),
            "bytes": output_stats.bytes,
            "sha256": output_stats.sha256,
            "pages": output_stats.page_count,
            "text_chars": output_stats.text_chars,
            "images": output_stats.image_count,
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
    """Compact, browser-safe description of what actually completed."""
    accounting = read_accounting(output_path)
    if accounting is None:
        return None
    source = accounting.get("source") or {}
    recognition = accounting.get("recognition") or {}
    content = accounting.get("source_content") or {}
    translation = accounting.get("translation") or {}
    output = accounting.get("output") or {}
    return {
        "source_pages": source.get("pages"),
        "result_pages": recognition.get("pages"),
        "paragraphs": content.get("paragraphs"),
        "images": content.get("images"),
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
    }


def _reject_preview_markers(*, title: str, author: str, text: str) -> None:
    haystack = f"{title}\n{author}\n{text}".casefold()
    for marker in _PREVIEW_TEXT_MARKERS:
        if marker in haystack:
            raise MineruOutputInvalid(
                "The generated PDF still carries preview-only text or metadata.")


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
