---
paths:
  - "python/resume_generator/**"
  - "python/cv_analysis/**"
---

# CV, tailoring and CV-analysis rules

- A CV states only what the profile and the CV text state. No default for anything: a part that cannot be read stays empty, `run_tailor.py` warns and records it under `tailoredAssets.warnings`.
- Education comes only from `resume.parsedData.education`; with none, the section is left out (`test_resume_education.py`). Summary and tagline are the candidate's own; rule-based tailoring writes no sentence of its own.
- `resume_parser.py` reads structure, never one person's CV: no employer, title, city or heading from any one CV (`test_resume_parser.py`).
- Layout is fixed by `HOLOJOB_GENERATION_CONTEXT.md` (styling fixed, words variable); keep the file name, code reads it by name.
- Privacy: CV analysis sends one CV only after the confirm dialog showed that exact redacted text and the provider (`redact.py` replaces name, e-mails, phones, links); `/api/ai/cv-analyze` refuses a body without `"confirm": true`. `analysis.verify` drops every item not found in the CV text.
- `llm_tailor.py` redacts everything it sends and fails closed on a leak (`redact.find_leaks`); it still has no confirm step (Phase 4, area 3). Do not widen what it sends.
- Fact gate (`provenance_checker.py`, `tests/python/test_fact_gate.py`): a model draft is rejected as a whole, and the run falls back to rule-based, when a claim does not trace to the profile facts. Covered: every number and unit metric, years of experience, capitalised names (employers, titles, schools, projects, technologies), subtitle wording, degrees and certifications. Not covered: lowercase invented technologies, a true fact reworded into a false one, tone. No override. Project-intelligence metrics count only if the profile states them. `dynamic` is a banned phrase.
- The Python language list (`profile_languages.py`) must stay in step with `src/utils/languages.js` (a test checks).

Detail: `docs/ARCHITECTURE.md` (My CVs, CV analysis, rule details).
