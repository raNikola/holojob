#!/usr/bin/env bash
# S6: prove that a normal cycle (`graphify update` + adapter build) spends no LLM tokens.
#
# Runs in a throwaway copy (the tracked files plus a copy of graphify-out/); the real
# repo is only read. The cycle runs with no network (unshare -rn), an empty
# environment (no API keys) and a PATH that holds only `graphify` (no `claude`).
# Passes when Graphify's token counter (cost.json) and the semantic layer are
# unchanged, the AST layer and the doc links did update, and the real repo is
# byte-identical afterwards.  Usage (bash or fish):  bash tools/graphify_adapter/zero_token_check.sh
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PY="$ROOT/.venv/bin/python"
GRAPHIFY=$(command -v graphify)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/graphify-zero-token.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
COPY="$WORK/repo"
mkdir -p "$COPY" "$WORK/bin" "$WORK/home"
ln -s "$GRAPHIFY" "$WORK/bin/graphify"

fingerprint() { (cd "$ROOT" && find graphify-out docs CLAUDE.md -type f -print0 | sort -z | xargs -0 sha256sum); }
fingerprint > "$WORK/real-before"

(cd "$ROOT" && git ls-files -z | rsync -a --from0 --files-from=- ./ "$COPY/")
cp -a "$ROOT/graphify-out" "$COPY/graphify-out"
rm -rf "$COPY/graphify-out/holojob"
printf '%s' "$COPY" > "$COPY/graphify-out/.graphify_root"
ln -s "$ROOT/.venv" "$COPY/.venv"

snapshot() {
  "$PY" - "$COPY" <<'EOF'
import json, sys
c = sys.argv[1]
g = json.load(open(f"{c}/graphify-out/graph.json"))
cost = json.load(open(f"{c}/graphify-out/cost.json"))
semantic = [n for n in g["nodes"] if n.get("_origin") == "semantic"]
print(json.dumps({"input_tokens": cost["total_input_tokens"], "output_tokens": cost["total_output_tokens"],
                  "llm_runs": len(cost["runs"]), "semantic_nodes": len(semantic),
                  "semantic_roadmap": sum(1 for n in semantic if n.get("source_file") == "docs/ROADMAP.md"),
                  "probe_node": any("zero_token_probe" in n["id"] for n in g["nodes"])}))
EOF
}
snapshot > "$WORK/before.json"

# A feature-cycle edit: a volatile doc and a code file.
printf '\nZero-token probe: `python/job_scoring/salary.py`.\n' >> "$COPY/docs/ROADMAP.md"
printf '\n\ndef _zero_token_probe():\n    return 1\n' >> "$COPY/python/job_scoring/salary.py"

isolated() { (cd "$COPY" && unshare -rn env -i HOME="$WORK/home" PATH="$WORK/bin" LANG=C.UTF-8 GRAPHIFY_NO_TIPS=1 "$@"); }
isolated graphify update "$COPY" > "$WORK/update.log" 2>&1 || { cat "$WORK/update.log"; echo "FAIL: graphify update"; exit 1; }
isolated "$COPY/.venv/bin/python" "$COPY/tools/graphify_adapter/adapter.py" build --root "$COPY"
snapshot > "$WORK/after.json"

"$PY" - "$WORK" "$COPY" <<'EOF'
import json, sys
work, copy = sys.argv[1:]
before, after = (json.load(open(f"{work}/{n}.json")) for n in ("before", "after"))
index = json.load(open(f"{copy}/graphify-out/holojob/index.json"))
linked = any(e.get("provenance") == "doc-path" and e["source_file"] == "docs/ROADMAP.md"
             and "salary" in e["target"] for e in index["links"])
checks = {
    "LLM token counter unchanged": all(before[k] == after[k] for k in ("input_tokens", "output_tokens", "llm_runs")),
    "semantic layer unchanged": before["semantic_nodes"] == after["semantic_nodes"]
                                and before["semantic_roadmap"] == after["semantic_roadmap"],
    "AST layer updated (probe function found)": after["probe_node"] and not before["probe_node"],
    "doc link rebuilt (ROADMAP -> salary.py)": linked,
}
for name, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + name)
print("before", before)
print("after ", after)
sys.exit(0 if all(checks.values()) else 1)
EOF

fingerprint > "$WORK/real-after"
if cmp -s "$WORK/real-before" "$WORK/real-after"; then
  echo "PASS real repo graphify-out/, docs/ and CLAUDE.md byte-identical"
else
  echo "FAIL the real repo changed"; exit 1
fi
