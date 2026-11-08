#!/usr/bin/env python3
"""Manual acceptance checks for the Graphify adapter, run against the real repo.

    .venv/bin/python tools/graphify_adapter/validate.py imports

`imports` re-checks every import the adapter re-pointed or added, in separate
`python -I -S` processes that only call importlib.machinery.PathFinder.find_spec.
That finds a module's file without importing it, so no project module runs. A
submodule is looked up inside its package folder directly, so the parent package
is never imported either. Exit 0 only if every context agrees with the adapter.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
# Pytest's order after tests/python/conftest.py (each insert goes to position 0).
CONFTEST_DIRS = ["cv_analysis", "job_scoring", "resume_generator", "job_discovery", "llm", "job_import"]

FINDER = r"""
import json, sys
from importlib.machinery import PathFinder
out = []
for item in json.load(sys.stdin):
    try:
        spec = PathFinder.find_spec(item["name"], item["path"])
    except Exception as exc:  # report, never guess
        out.append({"error": type(exc).__name__})
        continue
    out.append({"origin": spec.origin if spec else None,
                "locations": list(spec.submodule_search_locations or []) if spec else None})
json.dump(out, sys.stdout)
"""


def load_adapter():
    spec = importlib.util.spec_from_file_location("holojob_graphify_adapter", HERE / "adapter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def find_specs(python: str, requests: list[dict]) -> list[dict]:
    """Look each {name, path} up in an isolated interpreter (-I: no cwd, no env; -S: no site)."""
    done = subprocess.run([python, "-I", "-S", "-c", FINDER], input=json.dumps(requests),
                          capture_output=True, text=True, timeout=120, check=True)
    return json.loads(done.stdout)


def site_dirs(root: Path) -> list[str]:
    return [str(p) for p in sorted((root / ".venv").glob("lib/python*/site-packages"))]


def contexts(root: Path, importer: str, repo_dirs: list[str]) -> dict[str, list[str]]:
    sites = site_dirs(root)
    pytest_path = [str(root / "python" / d) for d in CONFTEST_DIRS] + [str(root / "tests" / "python")] \
        + sites + [str(root / "python")]
    importer_dir = str((root / importer).parent)
    every = [str(root / d) if d else str(root) for d in repo_dirs]
    return {
        "pytest": pytest_path,
        "script": [importer_dir] + sites + pytest_path,
        "every repo folder": every + sites,
        "every repo folder, reversed": list(reversed(every)) + sites,
    }


def check_imports(root: Path, python: str) -> int:
    adapter = load_adapter()
    result = adapter.build(root, root / "graphify-out" / "graph.json", None)
    details = result["details"]["imports"]
    repo_dirs = sorted(result["resolver"].index.by_dir)
    requests, expected = [], []
    for where, module, path in details["resolved"] + details["added"]:
        importer = where.rsplit(":", 1)[0]
        parts = module.split(".")
        target = str((root / path).resolve())
        if len(parts) > 1:
            # A submodule is searched only in its package's folder, as the import system does once the
            # package is loaded; the package itself is checked by its own re-pointed edge.
            sub = root / path
            package_dir = sub.parent.parent if sub.name == "__init__.py" else sub.parent
            requests.append({"name": module, "path": [str(package_dir)]})
            expected.append((where, module, "every repo folder", target))
            continue
        for name, ctx in contexts(root, importer, repo_dirs).items():
            requests.append({"name": module, "path": ctx})
            expected.append((where, module, name, target))
    answers = find_specs(python, requests)
    failures, agreed = [], 0
    for (where, module, ctx, target), answer in zip(expected, answers):
        origin = answer.get("origin")
        if origin is None and ctx not in ("every repo folder", "every repo folder, reversed"):
            continue  # not on that context's path: the import would fail there, not load another file
        if origin is None or str(Path(origin).resolve()) != target:
            failures.append(f"{where} {module} [{ctx}]: adapter {target}, PathFinder {origin or answer}")
        else:
            agreed += 1
    unresolved = details["unresolved"]
    witnesses = []
    for where, module, reason in unresolved:
        importer = where.rsplit(":", 1)[0]
        ctx = contexts(root, importer, repo_dirs)
        found = find_specs(python, [{"name": module, "path": ctx["pytest"]}, {"name": module, "path": ctx["script"]}])
        origins = sorted({str(Path(f["origin"]).relative_to(root)) for f in found if f.get("origin")})
        witnesses.append(f"{where} {module}: pytest/script contexts load {origins} ({reason})")
    print(f"imports: {len(details['resolved'])} re-pointed, {len(details['added'])} submodule edges, "
          f"{len(unresolved)} unresolved; {agreed} context checks agree, {len(failures)} disagree")
    for line in witnesses:
        print("  unresolved:", line)
    for line in failures:
        print("  DISAGREE:", line)
    return 1 if failures else 0


def check_calls(root: Path) -> int:
    """Every S3 removal must be hand-labelled; also measure what each guard protects."""
    adapter = load_adapter()
    result = adapter.build(root, root / "graphify-out" / "graph.json", None)
    found = result["details"]["removals"]
    labels = json.loads((HERE / "validation" / "s3_removals.json").read_text(encoding="utf-8"))["labels"]
    by_key = {(x["where"], x["name"], x["target_file"]): x for x in labels}
    removed = {(x["where"], x["name"], x["target_file"]): x for x in found["removed"]}
    unlabelled = sorted(set(removed) - set(by_key))
    false_negatives = sorted(k for k in removed if k in by_key and by_key[k]["verdict"] != "wrong")
    stale = sorted(set(by_key) - set(removed))
    reasons = {}
    for item in found["removed"]:
        rule = item["reason"].split(" (")[0].split(",")[0]
        rule = "imported from a file that defines it" if rule.startswith("imported from python/") else rule
        reasons[rule] = reasons.get(rule, 0) + 1
    print(f"calls: {len(removed)} removed, {len(removed) - len(unlabelled) - len(false_negatives)} labelled wrong, "
          f"{len(false_negatives)} labelled correct (false negatives), {len(unlabelled)} unlabelled, {len(stale)} stale labels")
    for rule, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  rule '{rule}': {n} removed")
    # Guard sensitivity: what the binding rule alone would remove from edges a guard keeps.
    resolver = result["resolver"]
    sensitivity: dict[str, list] = {}
    for guard, source, line, name, target in found["guarded"]:
        wrong, why = adapter.binding_verdict(resolver, source, line, name, target)
        if wrong:
            sensitivity.setdefault(guard, []).append(f"{source}:{line} {name} -> {target}: {why}")
    for guard, items in sorted(sensitivity.items()):
        print(f"  guard '{guard}' protects {len(items)} edge(s) the binding rule alone would remove:")
        for line in items:
            print("    ", line)
    for key in unlabelled:
        print("  UNLABELLED:", key)
    for key in false_negatives:
        print("  FALSE NEGATIVE:", key)
    return 1 if unlabelled or false_negatives else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("check", choices=["imports", "calls"])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--python", default=None, help="interpreter for the isolated lookups (default .venv/bin/python)")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    python = args.python or str(root / ".venv" / "bin" / "python")
    if args.check == "imports":
        return check_imports(root, python)
    if args.check == "calls":
        return check_calls(root)
    return 2


if __name__ == "__main__":
    sys.exit(main())
