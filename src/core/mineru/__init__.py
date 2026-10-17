"""Offline reconstruction of a cached MinerU online recognition result.

The cache is the authorized probe output: ``sample-info.json``, ``layout.json``,
one V2 content list and the local image assets. Reconstruction is entirely
offline: it never performs network I/O, never calls a translation LLM and never
mutates the cache. One structural adaptation feeds two renderers: reflowed PDF
(issue #14) and EPUB 3 (issue #15).
"""

from .cache import CachedBlock, MineruCache, MineruCacheError, PageInfo, load_cache
from .epub_preview import EpubPreviewResult, build_epub_preview
from .export import MineruExportError
from .pdf_preview import PdfPreviewResult, build_pdf_preview
from .structure import (
    Exclusion,
    Finding,
    ImageAsset,
    Provenance,
    Reconstruction,
    SourceContent,
    adapt,
    apply_preview_decoration,
)

__all__ = [
    "CachedBlock",
    "EpubPreviewResult",
    "Exclusion",
    "Finding",
    "ImageAsset",
    "MineruCache",
    "MineruCacheError",
    "MineruExportError",
    "PageInfo",
    "PdfPreviewResult",
    "Provenance",
    "Reconstruction",
    "SourceContent",
    "adapt",
    "apply_preview_decoration",
    "build_epub_preview",
    "build_pdf_preview",
    "load_cache",
]
