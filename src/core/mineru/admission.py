"""Admission of a PDF source for MinerU online recognition.

This is the single gate between "the reader selected/uploaded a document" and
"the document may be sent to a third party". It runs before any provider
request and enforces, in order: explicit task authorization, configured
credentials, a readable non-encrypted PDF, the recognition byte ceiling and the
recognition page ceiling.

The effective Web byte ceiling stays the existing 100 MiB upload limit; the
200,000,000-byte recognition ceiling documented here is the provider-facing one.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .errors import (
    MineruAuthorizationRequired,
    MineruByteLimit,
    MineruPageLimit,
    MineruPdfEncrypted,
    MineruPdfUnreadable,
    MineruTokenMissing,
)

# Documented MinerU standard-service ceiling: at most 200 pages and 200 MB.
MAX_PAGES = 200
MAX_BYTES = 200_000_000

# The five-minute local budget of one recognition attempt or continuation.
RECOGNITION_BUDGET_SECONDS = 300

_ENCRYPTED_MESSAGE = (
    "This PDF is password-protected. Remove the password and try again."
)


@dataclass(frozen=True)
class AdmittedSource:
    """A source PDF accepted for online recognition."""

    path: Path
    file_name: str
    size_bytes: int
    page_count: int
    sha256: str


def admit_pdf_source(
    file_path: Optional[str],
    *,
    authorized: bool,
    token: Optional[str],
    max_pages: int = MAX_PAGES,
    max_bytes: int = MAX_BYTES,
) -> AdmittedSource:
    """Validate a PDF for online recognition, or raise a typed :class:`MineruError`.

    Args:
        file_path: Path to the source PDF (already confined to the uploads
            directory by the caller when it came from a request).
        authorized: The task's explicit upload authorization. Missing consent
            never defaults to permission.
        token: MinerU account token resolved from the existing environment
            mechanism by the caller (never persisted or forwarded).
        max_pages: Recognition page ceiling (defaults to the documented 200).
        max_bytes: Recognition byte ceiling (defaults to 200,000,000).

    Returns:
        The admitted identity: path, file name, size, page count and SHA-256.
    """
    if not authorized:
        raise MineruAuthorizationRequired(
            "Uploading this PDF to MinerU requires explicit authorization for "
            "this task."
        )
    if not (token or "").strip():
        raise MineruTokenMissing(
            "No MinerU token is configured. Set MINERU_API_TOKEN in the "
            "environment before translating a PDF."
        )
    if file_path is None or not str(file_path).strip():
        raise MineruPdfUnreadable("The PDF source file is missing.")

    path = Path(file_path)
    if not path.is_file():
        raise MineruPdfUnreadable("The PDF source file does not exist.")

    size_bytes = path.stat().st_size
    if size_bytes <= 0:
        raise MineruPdfUnreadable("The PDF source file is empty.")
    if size_bytes > max_bytes:
        raise MineruByteLimit(
            f"The PDF is too large for online recognition "
            f"({size_bytes:,} bytes; maximum {max_bytes:,} bytes).",
            limits={"max_pages": max_pages, "max_bytes": max_bytes},
        )

    admitted = describe_pdf(path)
    if admitted.page_count > max_pages:
        raise MineruPageLimit(
            f"The PDF has too many pages for online recognition "
            f"({admitted.page_count} pages; maximum {max_pages}).",
            limits={"max_pages": max_pages, "max_bytes": max_bytes},
        )
    return admitted


def describe_pdf(file_path: Path) -> AdmittedSource:
    """Read a PDF's local identity (size, page count, SHA-256) without limits.

    Used to recognize a source and to verify a previously validated result is
    still bound to the same bytes. Authorization/configuration are the caller's
    concern; this function only proves the file is a readable, unencrypted PDF.
    """
    path = Path(file_path)
    if not path.is_file():
        raise MineruPdfUnreadable("The PDF source file does not exist.")
    size_bytes = path.stat().st_size
    if size_bytes <= 0:
        raise MineruPdfUnreadable("The PDF source file is empty.")
    return AdmittedSource(
        path=path,
        file_name=path.name,
        size_bytes=size_bytes,
        page_count=_read_page_count(path),
        sha256=_sha256_file(path),
    )


def _read_page_count(path: Path) -> int:
    """Open the PDF just enough to prove it is readable, unencrypted and non-empty."""
    try:
        import pymupdf
    except ImportError as exc:  # pragma: no cover - PyMuPDF is a project dependency
        raise MineruPdfUnreadable("PDF support is not installed (missing pymupdf).") from exc

    document = None
    try:
        try:
            document = pymupdf.open(str(path), filetype="pdf")
        except Exception as exc:
            raise MineruPdfUnreadable(
                f"{path.name} cannot be read as a PDF."
            ) from exc
        if document.needs_pass:
            raise MineruPdfEncrypted(_ENCRYPTED_MESSAGE)
        page_count = document.page_count
    finally:
        if document is not None:
            try:
                document.close()
            except Exception:  # pragma: no cover - close errors are never fatal here
                pass

    if page_count < 1:
        raise MineruPdfUnreadable(f"{path.name} has no pages.")
    return page_count


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
