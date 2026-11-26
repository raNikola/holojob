"""The gate tree keeps the committed file modes whatever the caller's umask (runner gate red on 2026-11-26: the
package runner ran under umask 077, tar dropped the group/other exec bits, the git-hook tests failed)."""
import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export-tree.sh"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_export_keeps_committed_modes_under_a_restrictive_umask(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "hook.sh").write_text("#!/bin/sh\n")
    (repo / "hook.sh").chmod(0o755)
    (repo / "sub").mkdir()
    (repo / "sub" / "plain.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "c")
    dest = tmp_path / "tree"
    dest.mkdir()
    subprocess.run(["sh", "-c", 'umask 077 && exec sh "$0" "$@"', str(SCRIPT), str(repo), "HEAD", str(dest)],
                   check=True, capture_output=True, text=True)
    assert stat.S_IMODE(os.stat(dest / "hook.sh").st_mode) == 0o755
    assert stat.S_IMODE(os.stat(dest / "sub" / "plain.txt").st_mode) == 0o644
    assert stat.S_IMODE(os.stat(dest / "sub").st_mode) == 0o755
