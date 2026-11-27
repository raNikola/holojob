---
paths:
  - "scripts/atomic-file.js"
  - "python/job_scoring/atomic_write.py"
  - "scripts/*store*.js"
  - "scripts/save-*.js"
  - "scripts/backup-handler.js"
  - "scripts/tighten-data-permissions.sh"
  - "scripts/profile-reset.js"
  - "python/llm/ai_gate.py"
  - "python/llm/ai_selection.py"
---

# Private data file modes

Moved verbatim from CLAUDE.md Conventions. New writers of private data use these helpers.

- File modes: private folders are `data/profile`, `applications`, `ai`, `config`, `backups`, `intelligence`, `outreach`, `interviews`, `analytics`, `resumes`, `profile.bak-*`. Writers create new files 600 and new directories 700; an existing file keeps its mode and nothing is chmodded at startup.
  Helpers: Node `PRIVATE_*_MODE`, `replaceFileAtomic(file, data, { mode })`, `copyToNewFile` (`scripts/atomic-file.js`); Python `write_text_atomic(path, text, new_file_mode)`, `make_private_dirs` (`python/job_scoring/atomic_write.py`). Since package 15 the job, cache and audit writers (`data/jobs`, `data/cache`, `data/audits`) also write private files through `write_private_text`: 600 files in 700 folders, and a wider existing file is narrowed on its next write. Narrowing files nobody writes again is the owner's command (`scripts/tighten-data-permissions.sh --apply`).
  Before a write that changes the profile, intelligence or enrichment file, the old version is copied to `data/backups/auto/<file>/` (`scripts/auto-backup.js`, `python/job_scoring/auto_backup.py`; last 10; no write without it). `scored_jobs.json` is copied there only before a re-score (`event="rescore"`, `-pre-rescore` names, last 3); no other writer of it backs it up. A new writer of those files calls them (`docs/ARCHITECTURE.md`, "Automatic backups and the save guard").
  Existing files: `scripts/tighten-data-permissions.sh` (dry run; `--apply` changes, owner runs it). The server runs as container root, which maps to the host owner; a non-root container user would lose access.

