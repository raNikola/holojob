Status: done
<!-- First line is parsed by scripts/run_package.py. One of: done | blocked | needs-review. The runner overrides it when its own checks fail. -->

# NN slug: one-line title

## Result

Value first: what the owner gets, in a few lines.

## Measured

Counts only. No private ad content, no candidate data. Before/after where the package changes something.

| Measure | Before | After |
|---|---|---|

## Defaults taken

One row per choice the plan left open.

| Choice | Source (benchmark file, standard, earlier owner decision) | How to undo |
|---|---|---|

## Deviations from benchmark

Each deviation: benchmark file, what differs, why.

## Blocked or needs owner

The stop rule hit, or the decision needed, with the options. "None" when empty.

## Commands for the owner

Fish, DS9. Build, up, deploy and rollback, exactly as typed.

```fish
cd /srv/holojob
# git fetch / merge of pkg/NN-slug as the owner decides
podman-compose build
podman-compose up -d --force-recreate
# rollback:
# git switch main; podman-compose build; podman-compose up -d --force-recreate
```
