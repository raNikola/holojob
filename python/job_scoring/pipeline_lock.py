"""The one lock over everything that replaces the job files: discovery, scoring, the pipeline, a manual add.

An flock on data/jobs/.pipeline.lock (HOLOJOB_PIPELINE_LOCK moves it; tests set it). The kernel drops it with its last
holder, so a kill or a crash cannot leave it stuck. A holder that runs a step hands the lock down: `pass_fds` keeps the
open file in the child and child_env() says which descriptor it is. A killed parent then does not free the lock while
its orphaned step still writes.

Stdlib only: Node starts run_rescrape.py for each status question, and that must not import pandas.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FD_ENV = "HOLOJOB_PIPELINE_LOCK_FD"
EXIT_LOCKED = 75  # EX_TEMPFAIL: cron can retry later, and Node answers 409
BUSY_MESSAGE = "A job run is in progress (Re-scrape, scoring or pipeline); nothing started. Try again when it has finished."


def lock_path() -> Path:
    return Path(os.environ.get("HOLOJOB_PIPELINE_LOCK") or ROOT / "data" / "jobs" / ".pipeline.lock")


class Lock:
    def __init__(self, fd: int):
        self.fd = fd

    def child_env(self) -> dict:
        """The environment for a step started with pass_fds=(lock.fd,)."""
        return {**os.environ, FD_ENV: str(self.fd)}

    def release(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)  # closes this process's hold; a step still running keeps the lock until it ends
            self.fd = -1


def _take(fd: int, wait: bool = False) -> bool:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        return True
    except BlockingIOError:
        return False


def _handed_down(path: Path) -> Lock | None:
    """The lock a parent handed to this process. The number alone proves nothing: it must be this file, and flock must agree."""
    raw = os.environ.pop(FD_ENV, None)  # not for this process's own children
    if raw is None:
        return None
    try:
        fd = int(raw)
        held, wanted = os.fstat(fd), os.stat(path)
    except (ValueError, OSError):
        return None
    if (held.st_dev, held.st_ino) != (wanted.st_dev, wanted.st_ino) or not _take(fd):
        return None
    os.set_inheritable(fd, False)
    return Lock(fd)


def acquire(wait: bool = False, path: Path | None = None) -> Lock | None:
    """The lock, or None when another process holds it. With `wait`, blocks until that process lets go, which can be a whole run.
    `path` names another lock file (a restore under a different root, tests); default is lock_path()."""
    path = path or lock_path()
    handed = _handed_down(path)
    if handed:
        return handed
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o644)
    if _take(fd, wait):
        return Lock(fd)
    os.close(fd)
    return None
