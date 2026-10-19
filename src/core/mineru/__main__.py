"""Offline command: build source-language previews from a MinerU cache.

Usage::

    python -m src.core.mineru --cache data/mineru-online/probe-001 \
        --output-dir data/mineru-online/recon-001 --format pdf
    python -m src.core.mineru --cache data/mineru-online/probe-001 \
        --output-dir data/mineru-online/recon-001-epub --format epub --language de

The command never uploads, never calls a translation LLM and never modifies the
cache. It backs the reconstruction acceptance slices (issues #14, #15 and #16).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Union

from .acceptance import build_acceptance_package
from .cache import MineruCache, MineruCacheError, load_cache
from .epub_preview import (
    DEFAULT_LANGUAGE,
    EpubPreviewResult,
    build_epub_preview,
    build_original_epub,
)
from .export import MineruExportError, ensure_output_outside_cache
from .local_result import load_local_result
from .pdf_preview import PdfPreviewResult, build_pdf_preview

Summary = dict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.core.mineru",
        description="Export a local MinerU result as an original-language EPUB, or "
                    "reconstruct a cached sample preview. No network access, no translation.",
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input", type=Path,
                        help="Local MinerU JSON or result directory for original-language EPUB export.")
    inputs.add_argument("--cache", type=Path,
                        help="Authorized cached MinerU result directory.")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="Directory for artifacts and report, outside the input directory.")
    parser.add_argument("--format", choices=("pdf", "epub", "both"), default=None,
                        help="Default: epub for local input, pdf for cache previews.")
    parser.add_argument("--language", default=DEFAULT_LANGUAGE,
                        help="BCP-47 source language for EPUB metadata (default: und).")
    parser.add_argument("--title", default=None,
                        help="Explicit title override for EPUB metadata.")
    parser.add_argument("--source-pdf", type=Path, default=None,
                        help="Original PDF, verified against the bundle's unique *_origin.pdf.")
    parser.add_argument("--json", action="store_true",
                        help="Print the summary as one JSON object.")
    args = parser.parse_args(argv)
    args.format = args.format or ("epub" if args.input is not None else "pdf")
    if args.input is not None and args.format != "epub":
        parser.error("Local --input exports EPUB only; --cache supports preview formats.")
    result: Union[EpubPreviewResult, PdfPreviewResult]

    try:
        if args.input is not None:
            input_root = args.input if args.input.is_dir() else args.input.parent
            ensure_output_outside_cache(args.output_dir, input_root)
            args.output_dir.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(prefix=".mineru-", dir=args.output_dir) as working:
                cache = load_local_result(args.input, source_pdf=args.source_pdf,
                                          working_dir=Path(working).resolve())
                result = build_original_epub(cache, args.output_dir,
                                             language=args.language, title=args.title)
            summary = {"execution": "passed", "epub": str(result.epub_path),
                       "report": str(result.provenance_path), "translated": False}
            print(json.dumps(summary) if args.json else
                  f"Wrote {result.epub_path}\nReport: {result.provenance_path}")
            return 0
        cache = load_cache(args.cache, source_pdf=args.source_pdf)
        if args.format == "both":
            return _build_both(cache, args)
        if args.format == "epub":
            result = build_epub_preview(
                cache, args.output_dir, language=args.language, title=args.title)
        else:
            result = build_pdf_preview(cache, args.output_dir)
    except (MineruCacheError, MineruExportError, OSError) as exc:
        print(f"Reconstruction failed: {exc}", file=sys.stderr)
        return 1

    summary = _summary(cache, args.format, result)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(_message(args.format, result))
        print(f"Provenance: {summary['provenance']}")
        print("Untranslated partial-book preview; the cache was not modified.")
        if args.format == "epub":
            print("Reader-open check: not performed (visual acceptance is a human step).")
        if summary["review_required"]:
            print("REVIEW REQUIRED: see the findings in the provenance file.")
    return 0


def _build_both(cache: MineruCache, args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    pdf = build_pdf_preview(cache, output_dir / "pdf")
    epub = build_epub_preview(cache, output_dir / "epub", language=args.language,
                              title=args.title)
    package = build_acceptance_package(cache, output_dir / "pdf", output_dir / "epub",
                                       output_dir)
    summary = {
        "execution": "passed" if package.passed else "failed",
        "format": "both",
        "translated": False,
        "complete_book": False,
        "sample_pages": list(cache.source_pages),
        "source_total_pages": cache.source_total_pages,
        "package": str(output_dir),
        "report": str(package.report_path),
        "checks": str(package.checks_path),
        "pdf_pages": pdf.page_count,
        "epub_sections": epub.section_count,
        "paragraph_count": pdf.paragraph_count,
        "image_count": pdf.image_count,
        "failures": list(package.failures),
        "pending": list(package.pending),
        "reader_check_performed": False,
        "review_required": pdf.review_required or epub.review_required,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        state = "passed" if package.passed else "FAILED"
        print(f"Acceptance package: {output_dir} ({state})")
        print(f"Report: {package.report_path}")
        print(f"Checks: {package.checks_path}")
        print("Untranslated partial-book previews; the cache was not modified.")
        print("Reader-open check and human visual acceptance remain pending.")
        if package.pending:
            print("Pending checks: " + ", ".join(package.pending))
        if package.failures:
            print("Failed checks: " + ", ".join(package.failures))
    return 0 if package.passed else 1


def _summary(cache: MineruCache, output_format: str,
             result: Union[EpubPreviewResult, PdfPreviewResult]) -> Summary:
    summary: Summary = {
        "execution": "passed",
        "format": output_format,
        "translated": False,
        "complete_book": False,
        "sample_pages": list(cache.source_pages),
        "source_total_pages": cache.source_total_pages,
        "provenance": str(result.provenance_path),
        "paragraph_count": result.paragraph_count,
        "image_count": result.image_count,
        "review_required": result.review_required,
    }
    if output_format == "epub":
        assert isinstance(result, EpubPreviewResult)
        summary.update({
            "epub": str(result.epub_path),
            "sections": result.section_count,
            "language": result.language,
            "reader_check_performed": False,
        })
    else:
        assert isinstance(result, PdfPreviewResult)
        summary.update({
            "pdf": str(result.pdf_path),
            "page_count": result.page_count,
            "text_chars": result.text_chars,
        })
    return summary


def _message(output_format: str,
             result: Union[EpubPreviewResult, PdfPreviewResult]) -> str:
    if output_format == "epub":
        assert isinstance(result, EpubPreviewResult)
        return (f"Wrote {result.epub_path} ({result.section_count} section(s), "
                f"{result.paragraph_count} paragraphs, {result.image_count} image(s)).")
    assert isinstance(result, PdfPreviewResult)
    return (f"Wrote {result.pdf_path} ({result.page_count} page(s), "
            f"{result.paragraph_count} paragraphs, {result.image_count} image(s)).")


if __name__ == "__main__":
    raise SystemExit(main())
