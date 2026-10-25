# Changelog

All notable changes to Holojob are documented here. Entries before the fork are Career OS history.

## [Unreleased] - Holojob

### Added

- Project renamed to **Holojob** and moved to the private repo `raNikola/holojob`; Career OS stays as the `upstream` remote (fetch only).
- Redesign documents: `docs/VISION.md`, `docs/GOALS.md`, `docs/ROADMAP.md`, `docs/redesign/DECISIONS.md`, `docs/redesign/PHASE0_AUDIT.md`, `docs/redesign/data-shapes.md`.
- Posting fixtures in `tests/fixtures/postings/` for the Phase 1 stability test.
- `AUTHORS.md`.

### Changed

- README rewritten for Holojob; the old Career OS README was folded into it (troubleshooting) and removed.
- `package.json`: name `holojob`, author, repository, `private: true` (no accidental npm publish).

### Removed

- Third-party peer chat data (`data/chat/`) from the tracked files.
- Upstream leftovers: `run.sh`, `run.bat`, root `setup.sh`, `scripts/setup.sh`, `scripts/setup-jobspy.sh`, `.github/` (CI, issue and PR templates), `CONTRIBUTING.md`, `SECURITY.md` (its data-handling and LinkedIn guidance moved into the README), Vite template assets, `python/job_discovery/run_jobspy.py`, `scripts/generate-roles.js` and the `@sparring/tech-roles-library` dependency.
- The legacy company lists in `python/job_discovery/config/` and the fallback in `providers/config_paths.py`; the providers read only `companies/`. None of its companies were carried over into `companies/` (the owner decided to keep that folder to the application history only).
- `data/jobs/.pipeline.lock` is no longer tracked (git-ignored).

### Fixed

- The favicon link in `index.html` pointed at a missing `/vite.svg`; it now uses `/favicon.svg`.

### Inherited before the fork (DS9 customizations of Career OS)

- Serbian discovery group (LinkedIn via JobSpy, Infostud, Workable, Greenhouse, Lever, Ashby), job history ledger, LLM enrichment of ads into facts, work-authorization caps, opt-in fit judgement, salary flag, CV library and verified CV analysis. See CLAUDE.md.

## [1.0.0] - 2026-06-10

### Added

- **Career OS** open-source release under AGPL-3.0
- Unified local API server (`scripts/api-handler.js` + `scripts/local-server.js`)
- One-command setup: `npm run setup`
- Production start: `npm run start` (build + Express server)
- Docker Compose support with persistent `data/` volume
- Anonymized demo data in `data/examples/` with "Load demo data" in Settings
- GitHub Actions CI: lint, build, mock discovery + scoring smoke test
- Contributor docs: CONTRIBUTING.md, SECURITY.md, issue/PR templates

### Changed

- Replaced `import.meta.env.DEV` gates with `/api/pipeline/health` probe — production mode has full pipeline access
- README rewritten for OSS quick start
- Branding updated to Career OS

### Security

- Scrubbed personal data from repository
- Expanded `.gitignore` for runtime data paths
- Added `.env.example` template
