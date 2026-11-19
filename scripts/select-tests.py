#!/usr/bin/env python3
"""Map the files a push changes to the tests that can notice (the fast pre-push tier). Standard library only.

    select-tests.py --root TREE --changed FILE_WITH_PATHS     (one repo-relative path per line)

Prints one JSON object:
  vitest   inputs for `vitest related`: changed JS files plus the test files named below
  pytest   test files to run
  meta     the always-run guard tests (also inside vitest / pytest)
  notes    lines for the owner: what could not be mapped and what to do about it

Mapping, most specific first:
  * a changed test file runs itself;
  * JS under src/ and scripts/: `vitest related` follows the import graph, so nothing is guessed here;
  * Python under python/: the modules that import it (transitively) and the tests that import any of them;
  * any other file (JSON fixtures, a runner script a test spawns, a compose file): the tests whose text names its path or file name.
A change that no rule reaches, or a change to the shared test setup, falls back to the meta tests and says so.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# The small source-scanning tests: they read the source tree or the repo's own config and must hold whatever changed.
META_VITEST = [
    "tests/js/browserStorageAllowlist.test.js",
    "tests/js/dataPermissions.test.js",
    "tests/js/requestGuard.test.js",
    "tests/js/composePorts.test.js",
    "tests/js/gitHooks.test.js",
    "tests/js/realDataGuard.test.js",
    "tests/js/importWizardSource.test.js",
]
META_PYTEST = [
    "tests/python/test_real_data_guard.py",
    "tests/python/test_application_store_isolation.py",
    "tests/python/test_import_privacy.py",
]
# Shared test setup: a change here can alter any test, so the fast tier cannot say which.
GLOBAL_FILES = {
    "tests/python/conftest.py", "tests/python/real_data_guard.py", "pytest.ini", "requirements.txt",
    "vitest.config.js", "package.json", "package-lock.json",
    "tests/js/setup/findingsRoot.js", "tests/js/setup/realDataGuard.js", "tests/js/setup/realDataFingerprint.js",
    "scripts/select-tests.py", "scripts/test-tier.sh",
}
IGNORED_PREFIXES = ("docs/", ".claude/", "graphify-out/", ".github/")
IGNORED_SUFFIXES = (".md", ".txt", ".example")

IMPORT = re.compile(r"^[ \t]*(?:from[ \t]+([\w.]+)[ \t]+import[ \t]+([^\n#]+)|import[ \t]+([\w., \t]+))", re.M)
PY_MENTION = re.compile(r"\b(\w+)\.py\b")


def tokens_of_imports(text: str) -> set[str]:
    out: set[str] = set()
    for m in IMPORT.finditer(text):
        modules = [m.group(1)] if m.group(1) else [x.split(" as ")[0].strip() for x in m.group(3).split(",")]
        for module in modules:
            out.update(p for p in module.split(".") if p)
        if m.group(2):
            out.update(re.findall(r"\w+", m.group(2).replace(" as ", " ")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--changed", required=True)
    args = ap.parse_args()
    root = Path(args.root)
    changed = [l.strip() for l in Path(args.changed).read_text().splitlines() if l.strip()]
    notes: list[str] = []
    meta_v = [f for f in META_VITEST if (root / f).exists()]
    meta_p = [f for f in META_PYTEST if (root / f).exists()]

    live = [f for f in changed if not f.startswith(IGNORED_PREFIXES) and not f.endswith(IGNORED_SUFFIXES) and (root / f).exists()]
    removed = [f for f in changed if f not in live and not f.startswith(IGNORED_PREFIXES) and not f.endswith(IGNORED_SUFFIXES)]
    glob = [f for f in live if f in GLOBAL_FILES]
    if glob:
        notes.append("shared test setup or config changed (" + ", ".join(glob) + "): the fast tier cannot say which tests it affects; only the meta tests run. Run the full tier: sh scripts/test-tier.sh full")
    if removed:
        notes.append("deleted or renamed, not mapped: " + ", ".join(removed[:8]) + (" ..." if len(removed) > 8 else ""))
    if not live and not removed:
        notes.append("only docs / notes changed: no test can notice, only the meta tests run")

    mapped_to_tests: dict[str, bool] = {}
    vitest_inputs: set[str] = set()
    py_tests: set[str] = set()

    py_test_files = sorted(p.relative_to(root).as_posix() for p in (root / "tests/python").glob("test_*.py"))
    js_test_files = sorted(p.relative_to(root).as_posix() for p in (root / "tests/js").glob("*.test.js"))
    text_cache: dict[str, str] = {}

    def text(rel: str) -> str:
        if rel not in text_cache:
            text_cache[rel] = (root / rel).read_text(errors="replace")
        return text_cache[rel]

    # Python module graph: stem -> files; file -> import tokens.
    py_src = [p.relative_to(root).as_posix() for p in (root / "python").rglob("*.py") if "__pycache__" not in p.parts] if (root / "python").exists() else []
    stems: dict[str, set[str]] = {}
    for f in py_src:
        stems.setdefault(Path(f).stem, set()).add(f)
        if Path(f).stem == "__init__":
            stems.setdefault(Path(f).parent.name, set()).add(f)
    deps: dict[str, set[str]] = {}
    for f in py_src:
        toks = tokens_of_imports(text(f)) | set(PY_MENTION.findall(text(f)))
        deps[f] = {t for t in toks if t in stems}

    for f in [x for x in live if x not in GLOBAL_FILES]:
        if f.startswith("tests/python/") and f.endswith(".py"):
            if Path(f).name.startswith("test_"):
                py_tests.add(f); mapped_to_tests[f] = True
            else:  # a helper next to the tests: the tests that import it
                stem = Path(f).stem
                hit = [t for t in py_test_files if stem in tokens_of_imports(text(t))]
                py_tests.update(hit); mapped_to_tests[f] = bool(hit)
            continue
        if f.startswith("tests/js/") and f.endswith(".js"):
            vitest_inputs.add(f); mapped_to_tests[f] = True  # a test file runs itself; a helper or fixture is followed by the import graph
            continue
        if f.startswith(("src/", "scripts/")) and f.endswith((".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")):
            vitest_inputs.add(f)
            mapped_to_tests[f] = None  # decided after vitest ran (see test-tier.sh)
        if f in py_src:
            stem = Path(f).stem if Path(f).stem != "__init__" else Path(f).parent.name
            closure = {stem}
            grew = True
            while grew:
                grew = False
                for g, tok in deps.items():
                    gs = Path(g).stem if Path(g).stem != "__init__" else Path(g).parent.name
                    if gs not in closure and tok & closure:
                        closure.add(gs); grew = True
            hit = [t for t in py_test_files if tokens_of_imports(text(t)) & closure or re.search(r"\b" + re.escape(Path(f).name) + r"\b", text(t))]
            py_tests.update(hit)
            jshit = [t for t in js_test_files if Path(f).name in text(t)]
            vitest_inputs.update(jshit)
            mapped_to_tests[f] = bool(hit or jshit)
            continue
        # Any other file: tests that name its path or file name.
        name = Path(f).name
        hit_p = [t for t in py_test_files if f in text(t) or name in text(t)]
        hit_j = [t for t in js_test_files if f in text(t) or name in text(t)]
        py_tests.update(hit_p); vitest_inputs.update(hit_j)
        if f in mapped_to_tests:  # a src/scripts JS file: vitest's import graph decides; a mention only adds
            if hit_p or hit_j:
                mapped_to_tests[f] = True
        else:
            mapped_to_tests[f] = bool(hit_p or hit_j)

    for f, ok in mapped_to_tests.items():
        if ok is False:
            notes.append(f"no test refers to {f}: it is covered by the meta tests only")

    out = {
        "vitest": sorted(vitest_inputs | set(meta_v)),
        "vitest_source_inputs": sorted(f for f in vitest_inputs if f.startswith(("src/", "scripts/"))),
        "pytest": sorted(py_tests | set(meta_p)),
        "meta": {"vitest": meta_v, "pytest": meta_p},
        "notes": notes,
    }
    json.dump(out, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
