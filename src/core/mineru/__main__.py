"""Offline command: build a source-language PDF preview from a MinerU cache.

Usage::

    python -m src.core.mineru --cache data/mineru-online/probe-001 \
        --output-dir data/mineru-online/recon-001

The command never uploads, never calls a translation LLM and never modifies the
cache. It exists for the reconstruction acceptance slice (issue #14).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cache import MineruCacheError, load_cache
from .pdf_preview import MineruExportError, build_preview


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.core.mineru",
        description="Reconstruct a cached MinerU online result as a source-language "
                    "PDF preview. No network access, no translation.",
    )
    parser.add_argument("--cache", required=True, type=Path,
                        help="Authorized cached MinerU result directory.")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="Directory for preview.pdf and preview.provenance.json.")
    parser.add_argument("--json", action="store_true",
                        help="Print the summary as one JSON object.")
    args = parser.parse_args(argv)

    try:
        cache = load_cache(args.cache)
        result = build_preview(cache, args.output_dir)
    except (MineruCacheError, MineruExportError) as exc:
        print(f"Reconstruction failed: {exc}", file=sys.stderr)
        return 1

    summary = {
        "execution": "passed",
        "translated": False,
        "complete_book": False,
        "sample_pages": list(cache.source_pages),
        "source_total_pages": cache.source_total_pages,
        "pdf": str(result.pdf_path),
        "provenance": str(result.provenance_path),
        "page_count": result.page_count,
        "paragraph_count": result.paragraph_count,
        "image_count": result.image_count,
        "text_chars": result.text_chars,
        "review_required": result.review_required,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(f"Wrote {result.pdf_path} ({result.page_count} page(s), "
              f"{result.paragraph_count} paragraphs, {result.image_count} image(s)).")
        print(f"Provenance: {result.provenance_path}")
        print("Untranslated partial-book preview; the cache was not modified.")
        if result.review_required:
            print("REVIEW REQUIRED: see the findings in the provenance file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
