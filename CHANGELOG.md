# Changelog

All notable changes to Holojob are documented here. Entries before the fork are Career OS history.

## [Unreleased] - Holojob

### Added

- Project renamed to **Holojob** and moved to the private repo `raNikola/holojob`; Career OS stays as the `upstream` remote (fetch only).
- Redesign documents: `docs/VISION.md`, `docs/GOALS.md`, `docs/ROADMAP.md`, `docs/redesign/DECISIONS.md`, `docs/redesign/PHASE0_AUDIT.md`, `docs/redesign/data-shapes.md`.
- Posting fixtures in `tests/fixtures/postings/` for the Phase 1 stability test.
- `AUTHORS.md`.

### Changed

- README rewritten for Holojob; the Career OS README is kept in `docs/career-os/README.md`.
- `package.json`: name `holojob`, author, repository, `private: true` (no accidental npm publish).

### Removed

- Third-party peer chat data (`data/chat/`) from the tracked files.

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
