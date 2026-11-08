# Graphify adapter

A small post-processing step for the local Graphify graph. Decisions: `docs/DECISIONS.md`, "Graph tooling".

```fish
cd /srv/holojob; and graphify update .; and .venv/bin/python tools/graphify_adapter/adapter.py build
```

`graphify update .` is AST only (no LLM). The adapter reads `graphify-out/graph.json` and never writes it. Its output
goes to `graphify-out/holojob/` (git-ignored): `index.json` (the corrected graph), `architecture.json`, `test-deps.json`
and `report.md`. Query the output with `--graph`, for example
`graphify affected "ai_gate.py" --graph graphify-out/holojob/test-deps.json`.

Standard library only. No network, no subprocess, no model call, and no project module is imported or executed.
Each edge it changes or adds has `_origin: "adapter"` and a `provenance`. Every other edge and node is checked to be
unchanged; if that fails, or the graph is not from the pinned Graphify version (0.9.103, schema 1), it writes nothing
and exits 3.

## Passes

1. **Python imports (S2).** A stub import is re-pointed only when exactly one module or package of that name exists
   across every repo folder, the installed packages (`.venv`) and the standard library, so it is the same file in every
   run context. `sys_path_review.json` lists each `sys.path` change in the repo, reviewed by hand; a new one refuses the
   build until it is reviewed (`adapter.py import-state` lists them).
2. **Proven-wrong inferred edges (S3).** An INFERRED Python call edge is removed only when the source has no import edge
   to the target file, never names it, and binds the name at that line to something else. `--no-remove` reports instead.
3. **Doc-to-code links (S5).** Backticked exact repo- or doc-relative paths of one code file; rebuilt every run.
4. **Views (S4).** `architecture.json` (production code and docs; no tests, design-system preset, tools or stubs) and
   `test-deps.json` (production and test code, static edges only). `report.md` also lists which production modules tests
   reach statically (not runtime coverage).

`report.md` states code-graph, doc-link and semantic-doc freshness separately; "current" only when checked.
Graphify writes a `cache/last_query_stamp` next to whatever file `--graph` points to; it is harmless.

## Checks (manual, against the real repo)

```fish
.venv/bin/python tools/graphify_adapter/validate.py imports   # isolated PathFinder lookups, no project code runs
.venv/bin/python tools/graphify_adapter/validate.py calls     # every removal hand-labelled; guard sensitivity
.venv/bin/python tools/graphify_adapter/validate.py doclinks  # precision >= 98% (Wilson 95% lower bound), n >= 200
bash tools/graphify_adapter/zero_token_check.sh                # S6: the cycle in a throwaway copy, offline, no keys
```

`validate.py` is the only part that starts a process: an isolated `python -I -S` that only calls
`importlib.machinery.PathFinder.find_spec`, which finds files without importing them. The labels it compares against
are in `validation/`; a new removal or link must be labelled there. Unit tests: `tests/python/test_graphify_adapter_*.py`.

## Removal

Delete `tools/graphify_adapter/`, `tests/python/test_graphify_adapter_*.py`, `tests/python/graphify_adapter_fixtures.py`
and `graphify-out/holojob/`. Nothing else depends on it. The passes are removable one by one:

- **Python imports:** temporary. Remove when the report's "Python imports" section shows 0 re-pointed imports on a
  fresh `graphify update .` after a Graphify upgrade (upstream issue: configurable Python import roots).
- **Proven-wrong inferred edges, views, doc links:** until Graphify offers an equivalent.
