#!/usr/bin/env python3
"""Package 9: scoring pass speed, before and after (no model call, no network).

    base                                           copy python/ to SCRATCH/p9-base with changed files restored from HEAD
    run LABEL [--python-src DIR] [--scratch DIR]   one scoring pass on a COPY of the real data in a temp dir under
                                                   scratch; python code from DIR (default: this checkout's python/);
                                                   writes SCRATCH/p9-LABEL.json (scored rows) and prints rows and time
    compare A B                                    row-for-row comparison of two such files (ids and counts only)

Real data is read-only. Usage example (baseline code from `git archive HEAD python`):
    .venv/bin/python scripts/measure_package9.py run before --python-src logs/p9-base/python
    .venv/bin/python scripts/measure_package9.py run after
    .venv/bin/python scripts/measure_package9.py compare logs/p9-before.json logs/p9-after.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import measure_package2 as m2  # noqa: E402  (mirror() and the copy list)

# Fields that hold a run time and so differ between two passes of the same code.
VOLATILE = {"scoredAt", "generatedAt", "scoringRunAt", "updatedAt"}


def cmd_run(args) -> int:
    scratch = Path(args.scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    src = Path(args.python_src).resolve()
    with tempfile.TemporaryDirectory(prefix="holojob-p9-", dir=scratch) as t:
        tmp = Path(t)
        m2.ROOT = ROOT  # src/ and config/ come from this checkout
        m2.mirror(tmp)
        shutil.rmtree(tmp / "python")
        shutil.copytree(src, tmp / "python", ignore=shutil.ignore_patterns("__pycache__"))
        sys.path.insert(0, str(tmp / "python" / "job_scoring"))
        sys.path.append(str(tmp / "python"))
        import run_scoring  # imported from the copy: its ROOT is tmp

        assert Path(run_scoring.ROOT) == tmp, run_scoring.ROOT
        out = tmp / "scored.json"
        sys.argv = ["run_scoring.py", "--output", str(out)]
        ns = run_scoring.parse_args()
        t0 = time.time()
        code = run_scoring.score(ns)
        wall = time.time() - t0
        data = json.loads(out.read_text(encoding="utf-8"))
        rows = data.get("jobs") or []
        (scratch / f"p9-{args.label}.json").write_text(json.dumps(rows, sort_keys=True), encoding="utf-8")
        print(f"{args.label}: exit={code} rows={len(rows)} pass={wall:.1f}s")
    return 0


def cmd_base(args) -> int:
    """Copy python/ to SCRATCH/p9-base/python with every file that differs from HEAD restored to its HEAD content."""
    import subprocess

    dest = Path(args.scratch).resolve() / "p9-base" / "python"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ROOT / "python", dest, ignore=shutil.ignore_patterns("__pycache__"))
    changed = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", "python"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for rel in changed:
        blob = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT, capture_output=True, check=True).stdout
        (dest.parent / rel).write_bytes(blob)
    print(f"baseline python at {dest}; restored from HEAD: {len(changed)} files")
    return 0


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def cmd_compare(args) -> int:
    a, b = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (args.a, args.b))
    key = lambda r: str(r.get("jobId") or r.get("id"))  # noqa: E731
    ma, mb = {key(r): _strip(r) for r in a}, {key(r): _strip(r) for r in b}
    diff = sorted(k for k in ma.keys() & mb.keys() if ma[k] != mb[k])
    print(f"rows: {len(a)} vs {len(b)}; ids only in A: {len(ma.keys() - mb.keys())}, only in B: {len(mb.keys() - ma.keys())}; differing rows: {len(diff)}")
    for k in diff[:20]:
        fields = sorted(f for f in ma[k].keys() | mb[k].keys() if ma[k].get(f) != mb[k].get(f))
        print(f"  {k}: {fields}")
    return 0 if not diff and ma.keys() == mb.keys() else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("label")
    r.add_argument("--python-src", default=str(ROOT / "python"))
    r.add_argument("--scratch", default=str(ROOT / "logs"))
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    b = sub.add_parser("base")
    b.add_argument("--scratch", default=str(ROOT / "logs"))
    args = ap.parse_args(argv)
    return {"run": cmd_run, "compare": cmd_compare, "base": cmd_base}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
