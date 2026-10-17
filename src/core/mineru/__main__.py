"""Offline command: build source-language previews from a MinerU cache.

Usage::

    python -m src.core.mineru --cache data/mineru-online/probe-001 \
        --output-dir data/mineru-online/recon-001 --format pdf
    python -m src.core.mineru --cache data/mineru-online/probe-001 \
        --output-dir data/mineru-online/recon-001-epub --format epub --language de

The command never uploads, never calls a translation LLM and never modifies the
cache. It backs the reconstruction acceptance slices (issues #14 and #15).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Union

from .cache import MineruCache, MineruCacheError, load_cache
from .epub_preview import DEFAULT_LANGUAGE, EpubPreviewResult, build_epub_preview
from .export import MineruExportError
from .pdf_preview import PdfPreviewResult, build_pdf_preview

Summary = dict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.core.mineru",
        description="Reconstruct a cached MinerU online result as a source-language "
                    "preview. No network access, no translation.",
    )
    parser.add_argument("--cache", required=True, type=Path,
                        help="Authorized cached MinerU result directory.")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="Directory for preview.pdf or preview.epub plus provenance.")
    parser.add_argument("--format", choices=("pdf", "epub"), default="pdf",
                        help="Output format (default: pdf).")
    parser.add_argument("--language", default=DEFAULT_LANGUAGE,
                        help="BCP-47 source language for EPUB metadata (default: und).")
    parser.add_argument("--title", default=None,
                        help="Explicit title override for EPUB metadata.")
    parser.add_argument("--json", action="store_true",
                        help="Print the summary as one JSON object.")
    args = parser.parse_args(argv)

    try:
        cache = load_cache(args.cache)
        if args.format == "epub":
            result: Union[EpubPreviewResult, PdfPreviewResult] = build_epub_preview(
                cache, args.output_dir, language=args.language, title=args.title)
        else:
            result = build_pdf_preview(cache, args.output_dir)
    except (MineruCacheError, MineruExportError) as exc:
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
