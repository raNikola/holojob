#!/bin/sh
# The two test tiers. Called by scripts/git-hooks/pre-push (fast, or full when HOLOJOB_PUSH_TIER=full) and by hand.
#
#   sh scripts/test-tier.sh fast [SHA [BASE]]   lint, the tests related to what changed since BASE, the meta tests. No build, no slow tests.
#   sh scripts/test-tier.sh full [SHA]          lint, all Vitest, all pytest (slow ones too), production build.
#
# SHA defaults to HEAD, BASE (fast only) to where SHA left origin/main. The commit is exported and checked, not the working tree:
# a file left out of the commit passes in the working tree and still breaks what gets pushed.
# Environment: HOLOJOB_NODE_MODULES (default <repo>/node_modules), HOLOJOB_PYTHON (default <repo>/.venv/bin/python).
set -u

tier=${1:-}
case "$tier" in fast | full) ;; *) echo "usage: sh scripts/test-tier.sh fast|full [SHA [BASE]]" >&2; exit 2 ;; esac
sha=${2:-HEAD}
base=${3:-}

die() {
  echo "test-tier: $1" >&2
  exit 1
}

top=$(git rev-parse --show-toplevel 2>/dev/null) || die "cannot find the repository root"
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
sha=$(git -C "$top" rev-parse --verify "$sha^{commit}" 2>/dev/null) || die "unknown commit"
node_modules=${HOLOJOB_NODE_MODULES:-$top/node_modules}
python=${HOLOJOB_PYTHON:-$top/.venv/bin/python}
command -v podman >/dev/null 2>&1 || die "podman not found"
[ -d "$node_modules" ] || die "node_modules missing (see Tests in CLAUDE.md)"
[ -x "$python" ] || die ".venv/bin/python missing (see Tests in CLAUDE.md)"

work=$(mktemp -d) || die "cannot create a temp directory"
trap 'rm -rf "$work"' EXIT
trap 'exit 130' HUP INT TERM
tree="$work/tree"
mkdir "$tree"
# Committed modes whatever the caller's umask (the package runner's gate runs under the owner's umask 077).
sh "$top/scripts/export-tree.sh" "$top" "$sha" "$tree" || die "cannot export $sha"
# Git-ignored and generated from the profile; without it the scoring snapshot tests skip.
if [ -f "$top/data/engine-snapshot.json" ]; then
  mkdir -p "$tree/data"
  cp "$top/data/engine-snapshot.json" "$tree/data/"
fi

in_node() {
  podman run --rm --security-opt label=disable -e NPM_CONFIG_UPDATE_NOTIFIER=false \
    -v "$tree:/work" -v "$node_modules:/work/node_modules" -w /work \
    docker.io/library/node:20-bookworm "$@"
}

step() {
  name=$1
  shift
  started=$(date +%s)
  if "$@" >"$work/log" 2>&1 </dev/null; then
    printf 'test-tier: PASS %-12s %ss\n' "$name" "$(($(date +%s) - started))"
  else
    printf 'test-tier: FAIL %-12s %ss\n' "$name" "$(($(date +%s) - started))"
    tail -n 60 "$work/log"
    die "$name failed for $(printf %.7s "$sha")"
  fi
}

total_started=$(date +%s)

if [ "$tier" = full ]; then
  step lint in_node npm run lint
  step js-tests in_node npm run test:js
  # pytest.ini caps the workers at 4 (pytest-xdist); the slow tests run here.
  step pytest sh -c 'cd "$1" && "$2" -m pytest -m "not network" -q' sh "$tree" "$python"
  step build in_node npm run build
  echo "test-tier: full tier passed in $(($(date +%s) - total_started))s"
  exit 0
fi

# --- fast tier ---------------------------------------------------------------------------------------------------------------------
if [ -z "$base" ]; then
  base=$(git -C "$top" merge-base "$sha" refs/remotes/origin/main 2>/dev/null) || base=
fi
changed="$work/changed.txt"
: >"$changed"
if [ -n "$base" ] && git -C "$top" diff --name-only --no-renames "$base" "$sha" >"$changed" 2>/dev/null; then
  :
else
  base=
  echo "test-tier: cannot tell what this push changes (no common commit with origin/main): only the meta tests run" >&2
fi

# Lint: every ESLint rule here works on one file at a time, so the changed files are enough; the whole tree when the lint setup changed or the base is unknown.
if [ -z "$base" ] || grep -qE '^(eslint\.config\.js|package(-lock)?\.json)$' "$changed"; then
  step lint in_node npm run lint
else
  lint_files=$(grep -E '^(src|scripts)/.*\.(js|jsx|mjs|cjs)$' "$changed" | while read -r f; do [ -f "$tree/$f" ] && echo "$f"; done | tr '\n' ' ')
  if [ -n "$lint_files" ]; then
    # shellcheck disable=SC2086
    step lint-changed in_node npx eslint --no-warn-ignored $lint_files
  else
    echo "test-tier: SKIP lint         no linted file changed"
  fi
fi

"$python" "$tree/scripts/select-tests.py" --root "$tree" --changed "$changed" >"$work/selection.json" || die "select-tests.py failed"
sel() { "$python" -c 'import json,sys; d=json.load(open(sys.argv[1])); v=d[sys.argv[2]]; print("\n".join(v if isinstance(v, list) else []))' "$work/selection.json" "$1"; }
vitest_files=$(sel vitest | tr '\n' ' ')
pytest_files=$(sel pytest | tr '\n' ' ')

# shellcheck disable=SC2086
step vitest-related in_node npx vitest related $vitest_files --run --reporter=json --outputFile=/work/.vitest-related.json
# shellcheck disable=SC2086
step pytest-related sh -c 'cd "$1" && "$2" -m pytest -m "not network and not slow" -q $3' sh "$tree" "$python" "$pytest_files"

# What the fast tier covered, and what it could not map.
"$python" - "$work/selection.json" "$tree/.vitest-related.json" <<'PY'
import json, sys
sel = json.load(open(sys.argv[1]))
try:
    ran = {r["name"].split("/work/", 1)[-1] for r in json.load(open(sys.argv[2]))["testResults"]}
except (OSError, ValueError, KeyError):
    ran = set()
meta_v = set(sel["meta"]["vitest"])
extra_v = ran - meta_v
print(f"test-tier: fast tier ran {len(ran)} Vitest files ({len(extra_v)} beyond the {len(meta_v)} meta tests) and {len(sel['pytest'])} pytest files ({len(sel['pytest']) - len(sel['meta']['pytest'])} beyond the meta tests); slow tests and the build wait for the full tier")
notes = list(sel["notes"])
named_v = set(sel["vitest"]) - meta_v
if sel["vitest_source_inputs"] and not (extra_v - named_v):
    notes.append("no Vitest file imports " + ", ".join(sel["vitest_source_inputs"][:6]) + ": covered by the meta tests only")
for line in notes:
    print("test-tier: NOTE " + line)
PY
echo "test-tier: fast tier passed in $(($(date +%s) - total_started))s"
