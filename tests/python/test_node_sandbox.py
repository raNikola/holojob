"""node-sandbox, the one node entry headless package sessions may call: it must accept only Vitest, ESLint or a node
script inside the package worktree, and always build the same closed container (no network, worktree read-write, real
data read-only). A wider helper would hand a session podman. Temp directories only; nothing is run."""
import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "scripts/node-sandbox"
_loader = importlib.machinery.SourceFileLoader("node_sandbox", str(SRC))
_spec = importlib.util.spec_from_loader("node_sandbox", _loader)
ns = importlib.util.module_from_spec(_spec)
sys.modules["node_sandbox"] = ns
_loader.exec_module(ns)


@pytest.fixture
def wt(tmp_path):
    root = tmp_path / "worktrees"
    w = root / "pkg-01-archive-history"
    for f in ("tests/js/allAds.test.js", "src/modules/jobs/allAds.js", "scripts/measure.mjs", "README.md"):
        (w / f).parent.mkdir(parents=True, exist_ok=True)
        (w / f).write_text("x")
    (tmp_path / "outside.test.js").write_text("x")
    return w


def test_fixed_container_shape(wt):
    cmd = ns.build(["vitest", "tests/js/allAds.test.js"], wt)
    assert cmd[:2] == ["podman", "run"]
    assert cmd[cmd.index("--network") + 1] == "none"
    assert f"{wt.resolve()}:/work" in cmd
    vols = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-v"]
    assert vols == [f"{wt.resolve()}:/work", f"{ns.DATA}:{ns.DATA}:ro", f"{ns.NODE_MODULES}:/work/node_modules:O"]
    mounts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--mount"]
    assert mounts == [f"type=tmpfs,destination={ns.DATA}/secrets,notmpcopyup"]   # the key file is never visible
    assert cmd[cmd.index(ns.IMAGE) + 1:] == ["npx", "vitest", "run", "tests/js/allAds.test.js"]


def test_allowed_invocations(wt):
    assert ns.build(["vitest", "tests/js/allAds.test.js", "--reporter=dot"], wt)[-5:] == \
        ["npx", "vitest", "run", "--reporter=dot", "tests/js/allAds.test.js"]
    assert ns.build(["lint"], wt)[-3:] == ["npm", "run", "lint"]
    assert ns.build(["lint", "src/modules/jobs/allAds.js"], wt)[-4:] == \
        ["npx", "eslint", "--no-warn-ignored", "src/modules/jobs/allAds.js"]
    assert ns.build(["node", "scripts/measure.mjs", "--days=14", "/srv/holojob/data/jobs/job_history.json"], wt)[-4:] == \
        ["node", "scripts/measure.mjs", "--days=14", "/srv/holojob/data/jobs/job_history.json"]


@pytest.mark.parametrize("argv", [
    [], ["sh", "-c", "id"], ["npm", "run", "build"], ["npx", "vitest"], ["podman", "ps"],
    ["vitest"],                                        # no file
    ["vitest", "--config", "x.js", "tests/js/allAds.test.js"],
    ["vitest", "tests/js/allAds.test.js", "--reporter=html"],
    ["vitest", "/etc/passwd"], ["vitest", "../outside.test.js"], ["vitest", "tests/js/../../../outside.test.js"],
    ["vitest", "src/modules/jobs/allAds.js"],          # not a test file
    ["vitest", "tests/js/missing.test.js"],
    ["lint", "--fix", "src/modules/jobs/allAds.js"], ["lint", "README.md"],
    ["node"], ["node", "-e", "process.exit(0)"], ["node", "README.md"], ["node", "/tmp/x.js"],
    ["node", "scripts/measure.mjs", "$(id)"], ["node", "scripts/measure.mjs", "a;b"],
])
def test_refused_invocations(wt, argv):
    with pytest.raises(ns.Refused):
        ns.build(argv, wt)


def test_symlink_out_of_the_worktree_is_refused(wt, tmp_path):
    os.symlink(tmp_path / "outside.test.js", wt / "tests/js/link.test.js")
    with pytest.raises(ns.Refused):
        ns.build(["vitest", "tests/js/link.test.js"], wt)


def test_only_from_a_package_worktree(wt, tmp_path):
    root = wt.parent
    assert ns.package_worktree(wt / "src", root) == wt.resolve()
    for cwd in (root, tmp_path, root.parent):
        with pytest.raises(ns.Refused):
            ns.package_worktree(cwd, root)
    other = root / "prune-tests"
    other.mkdir()
    with pytest.raises(ns.Refused):
        ns.package_worktree(other, root)
