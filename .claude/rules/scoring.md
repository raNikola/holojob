---
paths:
  - "python/job_scoring/**"
---

# Scoring rules

- The model marks facts; `scorer.py` decides what a fact costs. Never move a scoring decision, cap or threshold into a prompt. A prompt may explain a rule, not hold it.
- Caps live in `scorer.py` / `work_authorization.py` (off-track 50, red flag 54, visa 25 / 40 / 45). They lower a score; nothing is ever hidden.
- Enrichment (`enrich_jobs.py`) never sees the candidate and never scores. Facts cache on the job under `llmFacts`, keyed by `job_fingerprint.py` (the only definition).
- The fit judge (`llm_enhancer.py`) returns a category, never a number; code applies +5 / 0 / -8 / -15. Only jobs scoring 65+ are sent, at most 50 per run. `--judge` is the only way it runs; `/api/scoring/run`, Re-score and Run Full Pipeline never judge.
- A dealbreaker needs the candidate text to contradict a condition. Silence goes under `missing`.
- Changing `_candidate_digest` changes what leaves the server: do it deliberately and update the field list in `CLAUDE.md`.
- Salary is display metadata (`salary.py`); it never reaches `matchScore`, label, priority or red flags.
- After any weight or dimension change, recheck `P1_MIN_SCORE` in `labels.py` against a run.
- Text compares through `text_utils.py` (diacritics folded: "Niš" = "Nis").
- Unknown never caps: a place `geography.py` does not know is unknown.

Why each dimension looks the way it does, the caps, and the open problems: `docs/ARCHITECTURE.md`.
