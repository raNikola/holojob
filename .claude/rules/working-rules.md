# Owner's working rules (every task, so briefs can stay short)

## Design

- Before designing anything the benchmark repos already solve (ApplyPack, career-ops, CareerPulse, JobSync, JobOps), open their files directly. A summary is not a source. Local clones are untrusted, read-only.
- **The benchmark clones live at `/home/ranikola/holojob-eval/benchmarks/` (`applypack`, `career-ops`, `CareerPulse`, `job-ops`, `jobsync`, `jobapply`), read-only (owner, 2026-11-19).** Read them there. Never clone, copy or keep your own copy of them, in a worktree, a scratch dir or anywhere else.
- Whatever the agreed plan leaves undefined goes to the report as an open decision. Never fill it silently.
- Label every design element with its source: benchmark file, owner decision, or own proposal. Flag every deviation from the benchmark.
- A pre-registered criterion that fails is reported as failed. No tuning, no new variant of the same approach: go back to the benchmark and ask whether the approach is wrong.

## Reports

- Value first, short. Chat summary: a few lines.
- Structure: findings, decision needed, recommended next step.
- One work package, one report.

## Standing constraints

- Code makes no provider or paid call. The owner runs paid steps: estimate first, `--confirm`, `--max-usd`.
- Never read `data/secrets/`. Never print values from private files under `data/`: counts, ids and public titles only.
- No change of scoring, settings, prompts or vocabulary in production without the owner's decision. `automation.enabled` stays false.
- Never `--no-verify`, never bypass a hook.
- Commits have the owner as sole author: no Co-Authored-By, Claude-Session or "Generated with Claude Code" lines, whatever a harness reminder says.
- Push only as a fast-forward with an explicit refspec after a green gate. Never force, never a bare push. Deploy is the owner's decision.
