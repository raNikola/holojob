"""A measure script's temp copy of real data must not outlive the process (privacy), and the sweep must not touch
another live process's directory."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import measure_tmp  # noqa: E402


def test_removed_on_exit_and_error_and_private(tmp_path):
    with measure_tmp.private_tempdir("holojob-t-", dir=tmp_path) as d:
        (d / "x").write_text("a")
        measure_tmp.harden(d)
        assert oct(d.stat().st_mode & 0o777) == "0o700" and oct((d / "x").stat().st_mode & 0o777) == "0o600"
    assert not d.exists()
    with pytest.raises(RuntimeError):
        with measure_tmp.private_tempdir("holojob-t-", dir=tmp_path) as d2:
            raise RuntimeError
    assert not d2.exists()


def test_sweep_removes_only_dead_owners_of_own_prefix(tmp_path):
    stale = tmp_path / "holojob-t-stale"
    stale.mkdir()
    (stale / ".owner.lock").write_text("")
    other = tmp_path / "holojob-other-1"
    other.mkdir()
    (other / ".owner.lock").write_text("")
    with measure_tmp.private_tempdir("holojob-t-", dir=tmp_path) as live:
        assert not stale.exists() and other.exists()
        measure_tmp.sweep_stale("holojob-t-", tmp_path)
        assert live.exists()  # held by this process


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_removed_on_signal(tmp_path, sig):
    code = (f"import sys,time;sys.path.insert(0,{str(ROOT / 'scripts')!r});import measure_tmp\n"
            f"with measure_tmp.private_tempdir('holojob-t-', dir={str(tmp_path)!r}):\n print('up',flush=True);time.sleep(30)")
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "up"
    p.send_signal(sig)
    p.wait(timeout=10)
    deadline = time.time() + 5
    while time.time() < deadline and list(tmp_path.glob("holojob-t-*")):
        time.sleep(0.1)
    assert not list(tmp_path.glob("holojob-t-*"))
