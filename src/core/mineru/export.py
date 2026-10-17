"""Shared artifact-writing helpers for reconstruction previews.

Both renderers write into a caller-chosen directory, refuse to touch the cache
and replace their outputs atomically.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator


class MineruExportError(ValueError):
    """The preview artifact cannot be written safely."""


def ensure_output_outside_cache(output_dir: Path, cache_root: Path) -> None:
    """Raise when the destination would overwrite or nest inside the cache."""
    if _is_inside(output_dir, cache_root):
        raise MineruExportError(
            f"Refusing to write preview output inside the cache directory {cache_root}.")


@contextmanager
def atomic_path(path: Path) -> Iterator[Path]:
    """Yield a sibling temporary path; replace ``path`` with it on success."""
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        yield temporary
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    with atomic_path(path) as temporary:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                             encoding="utf-8")


def _is_inside(candidate: Path, root: Path) -> bool:
    try:
        Path(candidate).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True
