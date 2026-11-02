"""One way to replace a data file whole, shared by every writer of data/jobs/*.json."""

from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> None:
    """Temp file next to the target, then rename: a crash leaves the old file or the new one, never half of one.

    A rename would give the file the temp file's mode, so an existing file's mode is carried over.
    """
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
