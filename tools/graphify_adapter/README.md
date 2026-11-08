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

`validate.py` runs the manual acceptance checks against the real repo (`imports`, `calls`, `doclinks`). It is the only
part that starts a process: an isolated `python -I -S` that looks module files up with
`importlib.machinery.PathFinder.find_spec`, which finds files without importing them.

## Removal

Delete `tools/graphify_adapter/`, `tests/python/test_graphify_adapter_*.py`, `tests/python/graphify_adapter_fixtures.py`
and `graphify-out/holojob/`. Nothing else depends on it. The passes are removable one by one:

- **Python imports:** temporary. Remove when the report's "Python imports" section shows 0 re-pointed imports on a
  fresh `graphify update .` after a Graphify upgrade (upstream issue: configurable Python import roots).
- **Proven-wrong inferred edges, views, doc links:** until Graphify offers an equivalent.
