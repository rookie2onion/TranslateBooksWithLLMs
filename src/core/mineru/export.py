"""Shared artifact-writing helpers for reconstruction previews.

Both renderers write into a caller-chosen directory, refuse to touch the cache
and replace their outputs atomically.
"""

from __future__ import annotations

from pathlib import Path


class MineruExportError(ValueError):
    """The preview artifact cannot be written safely."""


def ensure_output_outside_cache(output_dir: Path, cache_root: Path) -> None:
    """Raise when the destination would overwrite or nest inside the cache."""
    if _is_inside(output_dir, cache_root):
        raise MineruExportError(
            f"Refusing to write preview output inside the cache directory {cache_root}.")


def _is_inside(candidate: Path, root: Path) -> bool:
    try:
        Path(candidate).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True
