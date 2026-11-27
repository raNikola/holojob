"""The writers of data/jobs and data/cache files leave private files: 600, new folders 700, even over an older 644 file."""

import stat

import pytest

import atomic_write
import job_history
import kept_ads
import manual_jobs
import requirement_frames


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


WRITERS = {
    "ledger": lambda p: job_history.save(p, job_history.empty_ledger()),
    "manual": lambda p: manual_jobs.save([], p),
    "kept": lambda p: kept_ads._save({}, p),
    "frames": lambda p: requirement_frames.save({}, p),
    "helper": lambda p: atomic_write.write_private_text(p, "{}"),
}


@pytest.mark.parametrize("name", sorted(WRITERS))
def test_rewrite_stays_private_even_from_644(tmp_path, name):
    target = tmp_path / "newdir" / "file.json"
    WRITERS[name](target)
    assert _mode(target) == 0o600
    assert _mode(target.parent) == 0o700
    target.chmod(0o644)
    WRITERS[name](target)
    assert _mode(target) == 0o600
    WRITERS[name](target)
    assert _mode(target) == 0o600


def test_plain_write_text_atomic_still_keeps_an_existing_mode(tmp_path):
    target = tmp_path / "f.json"
    target.write_text("a")
    target.chmod(0o644)
    atomic_write.write_text_atomic(target, "b", 0o600)
    assert _mode(target) == 0o644
