"""One way to replace a data file whole, shared by every writer of data/jobs/*.json."""

from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path


PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700


def make_private_dirs(path: Path) -> None:
    """Create `path` and its missing parents as 700 (mkdir's mode skips the parents). An existing folder keeps its mode."""
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for folder in reversed(missing):
        folder.mkdir(mode=PRIVATE_DIR_MODE, exist_ok=True)


def write_text_atomic(path: Path, text: str, new_file_mode: int | None = None, force_mode: bool = False) -> None:
    """Temp file next to the target, then rename: a crash leaves the old file or the new one, never half of one.

    A rename would give the file the temp file's mode, so an existing file's mode is carried over. A new file gets
    new_file_mode, else the process default. With force_mode, new_file_mode also replaces the mode of an existing file
    (a 644 file becomes 600 on its next write). The temp file has its mode before any byte is written.
    """
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        keep_existing = path.exists() and not (force_mode and new_file_mode is not None)
        mode = stat.S_IMODE(path.stat().st_mode) if keep_existing else new_file_mode
        with open(tmp, "w", encoding="utf-8") as handle:
            if mode is not None:
                os.chmod(tmp, mode)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_private_text(path: Path, text: str) -> None:
    """Replace `path` whole as a private file: missing folders 700, the file 600 even when it was wider before."""
    path = Path(path)
    make_private_dirs(path.parent)
    write_text_atomic(path, text, PRIVATE_FILE_MODE, force_mode=True)
