Status: needs-review

# 00 package-runner: runner, data split and enforcement probes

## Result

The workflow is built: plan (`docs/redesign/PACKAGES_PLAN.md`), report template, and `scripts/run-package`. The runner runs one package per fresh headless session, in a throwaway clone with an allowlisted ad-data copy. Each session runs inside an outer bubblewrap, with Claude Code's Bash sandbox inside that. The runner sets the status from its own checks.

**No package has run.** The runner refuses every package until a probe run passes. The last probe run (2026-11-26) passed every check that needs no model. The session probes did not run: the API rejects the token in `~/.config/holojob-runner/oauth-token` (`401 Invalid bearer token`).

**Diagnosis (2026-11-26):** the token itself is invalid.
- The file is fine: mode 600, 92 bytes, no newline, no whitespace.
- The same token gets a 401 in three setups:
  - outside the sandbox with the host environment;
  - outside the sandbox with the runner's environment;
  - inside the outer sandbox.
- The owner's normal login answers the same minimal call.
- The content is malformed: one `#` (position 48) and no `sk-ant-oat01-` prefix. This looks like a partial paste.
- The runner now refuses a token file with characters a token cannot contain.

## Measured

**Data split** of `/srv/holojob/data` (owner decision 2026-11-26):
- 169 files are copied;
- 3,643 private files are not copied (57 roots);
- 6 git-tracked public files (examples, `.gitkeep`) come with the clone.

**Must-keep set:** 20 rated holdout-v1 ads, all 20 in the ledger, 19 with text. `data/derived/labelled-ads.json` holds ids and verdicts only.

**Probe run 5** (`~/holojob-packages/state/probes-*.json`):

| Check | Result |
|---|---|
| Private files visible in the outer sandbox (production and clone path, every private file) | PASS, 0 of 7,286 |
| Credential paths visible (token, `~/.claude/.credentials.json`, `.env`, `~/.ssh`, `~/.config/gh`, `/run/user/1000`, `claude-config`, `data/secrets`, `/srv/holojob/.git`, `~/.claude.json`) | PASS, 0 of 10 |
| Benchmarks read-only in the sandbox | PASS |
| Gate pytest sandbox has no network | PASS |
| Gate node container has no network | PASS |
| Must-keep set is 19 | PASS |
| Session setup: mode dontAsk, tools Bash/Edit/Glob/Grep/Read/Write only, no MCP server | PASS |
| No probe file reached the host | PASS |
| 178 session probes | NOT PROVEN: the session could not authenticate |

The 178 session probes cover:
- keys and credential files, through Bash and the Read tool;
- `/proc`, through the Read, Grep and Glob tools, in forms that return no file content;
- environment names and `/proc/*/environ`;
- the ssh-agent, gh, D-Bus and keyring;
- push (local, ssh, https, raw TCP);
- podman, its socket, podman-compose and systemd;
- the provider hosts, including with `dangerouslyDisableSandbox`;
- outside directories;
- every private root at its production and clone path;
- writes to production data, the repo, home, the benchmarks, `.git/config` and `.claude/`;
- a session that changes the clone's git control files (config, commondir, config.worktree, info/attributes) is blocked, and the runner runs no git command on that clone;
- 9 controls that must succeed.

**Data split for your review.**

Copied (ad data and settings, `AD_DATA_ALLOW` in `scripts/run_package.py`):
- `jobs/`: `discovered_jobs.json`, `job_history.json`, `filtered_ads.json`, `normalized_jobs.json`, `raw_jobs.csv`, `scored_jobs.json`, `rescored_kept.json`, `pipeline_last_run.json`, `job-state.json` and `staging/`.
- `ai/settings.json` and `ai/usage-ledger.jsonl`.
- `config/sources.json` and `config/ai-settings.json`.
- `analytics/runs/`.
- `cache/engine.json` and `cache/requirement-frames.json`.

Private, not copied (anything not on the allowlist is private by default):
- **Candidate data:** `profile`, `profile.bak-20261104-160550`, `applications`, `resumes`, `intelligence`, `interviews`, `outreach`, `chat`.
- **Labels and calibration:** `calibration`.
- **Keys and backups:** `secrets`, `backups`.
- **Profile-derived:** `audits`, `ai/findings`, `analytics/skill_gap.json`, `engine-snapshot.json`, `profile-enrichment.json`, `requirement-remap.json`, `competency-*` (8 files and 3 scratch dirs), `competencies-review.md`.
- **Fit and CV caches:** `cache/llm_fit.json`, `cache/fit3.json` (and 3 `.bak`), `cache/cv_analysis.json`, `cache/competency-evidence.json`, `cache/engine-calibration.json`, `cache/engine-stability.json`, `cache/repos`.
- **Owner-only:** `jobs/manual_jobs.json` (notes, extra links, source URL).
- **Not needed:** `.bak` copies of `discovered_jobs`, `job_history`, `scored_jobs` and `cache/engine.json`; lock files; `discovery-test.log`.

Please check two items:
- `jobs/scored_jobs.json`: its match reasons are derived from the profile.
- `jobs/job-state.json`: your Saved/Rejected statuses.

Package 1 needs both. Move either to private by deleting its line in `AD_DATA_ALLOW`.

## Defaults taken

| Choice | Source | How to undo |
|---|---|---|
| Throwaway `git clone --no-hardlinks` per package, remote removed, fetched back by the runner | Own proposal: a worktree's commits write `/srv/holojob/.git` | `prepare_workspace` in `scripts/run_package.py` |
| Outer bubblewrap around the whole `claude` process | Own proposal: the docs say the Claude Code sandbox covers Bash only, not Read or Edit | `bwrap_argv` |
| `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=0`; the token kept out of Bash by `sandbox.credentials` deny | Observed: with the scrub on, Claude Code 2.1.331 forces mode `default`, even with `--allowedTools` | `session_env` |
| Gate = full tier in podman `--network none` (node) and bubblewrap without network (pytest) | Own proposal: the gate runs code the session wrote | `run_gate` |
| node copied out of the local `node:20-bookworm` image into `~/holojob-packages/tools/node` | Own proposal: no podman inside the sandbox | `node_tools` |
| The 19 labelled ads = holdout-v1 rated ads with text | `~/holojob-eval/w5-benchmark-ranking.md` ("the 19 rated ads with text"); the repo files name 45 labelled ads | `build_labelled`, `MUST_KEEP_COUNT` |
| `maxTurns` 400; needs 4→3 and 6→2 | Own proposal; inferred from the plan's order | Package table |
| First base `main` (`--base`) | Standard | `--base` |
| graphify mounted read-only (`~/.local/share/uv`) | CLAUDE.md asks for graphify | `bwrap_argv` |

## Deviations from benchmark

None. No benchmark has a headless package runner. The design follows the official Claude Code docs: headless, settings, sandboxing, permissions and settings-reference, read 2026-11-25.

## Blocked or needs owner

1. **Renew the runner token** (commands below), then run the probes. Packages stay refused until a probe run passes.
2. **Review the data split above.**

**What cannot be enforced technically, and stays manual or a written rule:**
- The session reads the ad-data copy it needs. "Counts only, no private ad content in reports" is a prompt rule.
- The `claude` process itself sends its context to the Anthropic API.
- Bash deny rules (`git push`, `podman`, …) are prefix rules that `sh -c` can bypass. They are a second line only. The probes run without them, so they prove the mount and sandbox layers underneath.

## Commands for the owner

```fish
claude setup-token                       # prints a token starting with sk-ant-oat01-
read -s tok; printf %s $tok > ~/.config/holojob-runner/oauth-token; chmod 600 ~/.config/holojob-runner/oauth-token; set -e tok
cd /srv/holojob/.claude/worktrees/prune-tests; scripts/run-package --probe
# after a PASSED probe run:
scripts/run-package 1 --base package-runner
# rollback of a package: git branch -D pkg/01-archive-history; rm ~/holojob-packages/state/01.json
```
