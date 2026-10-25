# Resume Tailoring

Truth-only tailored resumes from profile + intelligence + scored job.

Resumes are built from the **canonical structure in `profile.resume.rawText`** (your uploaded PDF text): About Me, Professional Experience with bullets, categorized Skills, and Education. Job-specific keywords from `matchedSkills` are woven into the summary and skill ordering while preserving your original experience bullets.

Output HTML/PDF uses a Calibri-style layout matching a one-page professional resume (centered name, section headers, two-column skills table).

## Run

```bash
source .venv/bin/activate
python python/resume_generator/run_tailor.py --job-id <jobId>
python python/resume_generator/run_tailor.py --priority P1 --limit 5
python python/resume_generator/run_tailor.py --job-id <jobId> --no-llm   # rule-based only, no model call
```

## Output

In `data/resumes/{jobId}/`: `tailored_resume.md`, `tailored_resume.html`, `cover_letter.md`, and the spec-named files `<Name>_<Company>_<Role>_Resume.pdf` / `.docx` / `.json` and `..._CoverLetter.pdf` (naming from `CAREER_OS_GENERATION_CONTEXT.md` Part 6).

Paths stored in `tailoredAssets` on each job in `scored_jobs.json`.
