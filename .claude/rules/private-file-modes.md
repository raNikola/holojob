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
  Helpers: Node `PRIVATE_*_MODE`, `replaceFileAtomic(file, data, { mode })`, `copyToNewFile` (`scripts/atomic-file.js`); Python `write_text_atomic(path, text, new_file_mode)`, `make_private_dirs` (`python/job_scoring/atomic_write.py`). `data/jobs` and `data/cache` stay at default modes on purpose.
  Existing files: `scripts/tighten-data-permissions.sh` (dry run; `--apply` changes, owner runs it). The server runs as container root, which maps to the host owner; a non-root container user would lose access.

