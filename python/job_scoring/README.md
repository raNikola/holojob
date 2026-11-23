# Job Scoring

Deterministic job scoring against `candidate-intelligence.json`.

## Run

```bash
podman exec holojob python python/job_scoring/run_scoring.py
```

or `podman exec holojob npm run score:jobs`. The opt-in fit judgement (`--judge`) sends data to the configured provider; see [CLAUDE.md](../../CLAUDE.md) for its privacy rules.

## Input / output

- Input: `data/intelligence/candidate-intelligence.json`, `data/jobs/discovered_jobs.json`
- Output: `data/jobs/scored_jobs.json`

## Steps in this folder

| Script | What it does | Paid |
|---|---|---|
| `run_scoring.py` | Deterministic scoring (scoring 1.7); `--judge` is the opt-in fit judgement; a re-score backs up the old `scored_jobs.json` first | judge only |
| `enrich_jobs.py` | Reads each ad into facts (`llmFacts`, the "reading"); never sees the candidate | yes, limited |
| `classify_new.py` | Fit 3 role class for ads with none (`data/cache/fit3.json`) | yes, limited |
| `engine_missing.py` | Engine answers for ads that pass the gates and have none (sends a redacted evidence index) | yes, limited |
| `extract_ledger_ads.py` | Owner-run extraction for ads only the ledger holds | yes, `--max-usd --confirm` |
| `rescore_kept.py`, `kept_ads.py` | Score kept and applied ads that are not in the latest run | no |

The paid steps take their limits from Settings > AI budget (`run_budget.py`); no limit is in code. A manual Re-scrape (`python/run_rescrape.py`) runs
them in order under one run budget; the full pipeline runs classification too. Details: [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md), "Re-scrape".

## Weights

Uses `scoringWeights` from intelligence (default 25/25/20/15/10/5: roleMatch, skillMatch, locationMatch, experienceMatch, industryMatch, cultureMatch). The defaults are read from `src/data/scoringWeights.json`, shared with the UI; a missing or malformed key falls back to them.
