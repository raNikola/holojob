"""Private, self-cleaning temp directory for the measure scripts (a copy of real data must never be left behind).

    with private_tempdir("holojob-p9-", dir=scratch) as tmp: ...

- Removed on normal exit, on an exception, on SIGINT and on SIGTERM (SIGTERM is turned into SystemExit while inside).
- Created 700; call harden(tmp) after copying data into it (directories 700, files 600).
- At start, sweeps stale directories of the SAME prefix only. A directory is stale when nothing holds its flock
  (a killed process releases it), so another live process's directory is never touched; a directory without a lock
  file younger than a minute is skipped (its owner may be between mkdir and lock).
SIGKILL cannot be caught; the next start sweeps that leftover.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import shutil
import signal
import tempfile
import time
from pathlib import Path

LOCK_NAME = ".owner.lock"
GRACE_SECONDS = 60


def harden(root: Path) -> None:
    """chmod a copied tree: directories 700, files 600."""
    root = Path(root)
    for p in [root, *root.rglob("*")]:
        if p.is_symlink():
            continue
        os.chmod(p, 0o700 if p.is_dir() else 0o600)


def sweep_stale(prefix: str, parent: Path | None = None) -> list[str]:
    """Remove directories named <prefix>* under parent that no live process owns. Returns the removed names."""
    parent = Path(parent or tempfile.gettempdir())
    removed: list[str] = []
    if not parent.is_dir():
        return removed
    for d in parent.iterdir():
        if not d.name.startswith(prefix) or d.is_symlink() or not d.is_dir():
            continue
        lock = d / LOCK_NAME
        try:
            fd = os.open(lock, os.O_RDWR)
        except FileNotFoundError:
            if time.time() - d.stat().st_mtime < GRACE_SECONDS:
                continue
            fd = None
        except OSError:
            continue
        try:
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    continue  # a live process holds it
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
        finally:
            if fd is not None:
                os.close(fd)
    return removed


@contextlib.contextmanager
def private_tempdir(prefix: str, dir: Path | str | None = None):
    parent = Path(dir) if dir else Path(tempfile.gettempdir())
    parent.mkdir(parents=True, exist_ok=True)
    sweep_stale(prefix, parent)
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    os.chmod(path, 0o700)
    fd = os.open(path / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    old = {}

    def _raise(signum, _frame):
        raise SystemExit(128 + signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            old[sig] = signal.signal(sig, _raise)
        except ValueError:  # not the main thread: no handler, the finally still covers exceptions
            pass
    try:
        yield path
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
        shutil.rmtree(path, ignore_errors=True)
        os.close(fd)
