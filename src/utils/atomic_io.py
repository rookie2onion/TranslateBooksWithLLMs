"""Atomic file and JSON writing shared by persistence and artifact writers.

Every writer follows the same shape: write a sibling ``.part`` file, flush it,
then replace the destination in one step. A crash mid-write can therefore leave
a temporary file behind, never a truncated or half-valid destination.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping


@contextmanager
def atomic_path(path: Path) -> Iterator[Path]:
    """Yield a sibling temporary path; replace ``path`` with it on success."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        yield temporary
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:  # pragma: no cover - best-effort cleanup
            pass


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write ``payload`` as UTF-8 JSON and publish it atomically."""
    with atomic_path(path) as temporary:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(dict(payload), stream, ensure_ascii=False, indent=2)
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:  # pragma: no cover - fsync support varies
                pass
