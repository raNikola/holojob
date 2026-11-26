Status: in-progress
<!-- First line, exactly one of: Status: done | Status: blocked | Status: needs-review. "done" only after the full tier
is green (headless: pytest green; the runner runs the full tier). This report is temporary and never committed:
final path /srv/holojob/.claude/package-runs/reports/NN-slug.md (git-ignored). It is reviewed by the owner and two
other reviewers. The permanent description of the feature goes into DECISIONS.md, ROADMAP.md and the feature md, in
the package commit. Counts, ids and public ad titles only: no private content. -->

# Package NN slug: one-line title

Branch `list-cleanup`, base `<sha>` (the previous package's recorded tip), package commit(s) `<sha>`.

## Result

Value first, a few lines: what the owner gets, and whether every point of the package in the plan is done.

## Changes

One block per change.

### Change 1: name

- **What:**
- **Why:**
- **Source:** benchmark file (path in `/home/ranikola/holojob-eval/benchmarks/...`), owner decision (date, where recorded), or own proposal.
- **Files and functions:** `path/file.py`: `function()`, ...
- **Behaviour before:**
- **Behaviour after:**

## Defaults taken

Every choice the plan left open.

| Choice | Source (benchmark file, standard, earlier owner decision) | How to undo |
|---|---|---|

## Deviations from benchmark

For each one: the benchmark file, what differs, and why. Write "None" if there are none.

## Measurements

Counts only, before and after, with the command that produced them.

| Measure | Before | After | Command |
|---|---|---|---|

## Tests and results

| Test (file or command) | What it proves | Result |
|---|---|---|

Full tier: command and result, or "run by the runner" in a headless run.

## Risks and what was not done

- **Risks:** what could break, and how it would show.
- **Not done:** what was not done, and why: out of scope, blocked, or left to the owner.

## Blocked or needs owner

The stop rule that was hit, or the decision needed with its options. Write "None" if there is nothing.

## Permanent docs updated

Which sections of DECISIONS.md, ROADMAP.md and the feature md the package commit changed.

## How the owner tests this

Exact fish commands, in order, with the expected result of each.

```fish
cd /srv/holojob
# 1. <step>        expected: <result>
```

## Commands for the owner

Fish, DS9: merge, build, up and rollback, exactly as typed.

```fish
cd /srv/holojob
# git merge --ff-only list-cleanup   (once the whole list is done and reviewed, from the branch the owner merges into)
podman-compose build
podman-compose up -d --force-recreate
# rollback: git switch <previous>; podman-compose build; podman-compose up -d --force-recreate
```
