---
paths:
  - "Dockerfile"
  - "docker-compose.yml"
  - ".dockerignore"
  - "requirements.txt"
  - "scripts/setup-job-discovery.sh"
  - ".env*"
  - "scripts/local-server.js"
---

# Container, builds and deploy

- Bare `python` in the container is the venv (`/app/.venv`, via `ENV PATH` in the
  Dockerfile); images built before that line need a rebuild.
- The image carries no tests (`tests/` is not copied, no `pytest`). Run the checks outside it, as in Tests below.
- **Builds:** dependencies are layered before code, so a code-only `podman-compose build` takes about 10 s; pip and the
  Playwright browsers rerun only when `requirements.txt` or `scripts/setup-job-discovery.sh` changes. `.dockerignore`
  allows only `data/examples` from `data/`. Never remove those lines.
- **Deploy is an image rebuild from a tagged, pushed commit. Never hot-patch the running container** (no `podman cp`, no edits inside it; owner
  decision 2026-11-18): tag the running image as rollback, `env HOLOJOB_COMMIT=<sha> podman-compose build` (context = a clean export of the
  commit, e.g. `git archive`), tag the new image, `podman-compose up -d --force-recreate --no-build`, check health / counts / ledger, roll back to the
  rollback tag on any failure. Exact steps: `docs/ARCHITECTURE.md` "Deploy".

- **Source offer (AGPL-3.0 section 13):** the app links to the source tree at the commit baked into the build (Settings > General,
  and the sidebar). Build with `env HOLOJOB_COMMIT=(git rev-parse HEAD) podman-compose build`. Only deploy a commit that is
  pushed to `origin`, and build only from a clean, pushed tree, so the link points at what runs (a rebuild bakes it in; a hot patch would not). The repo must be
  readable by the users of the deployed service before it serves anyone but the owner.

Detail: `docs/ARCHITECTURE.md` (Container gotchas).

## From Conventions

- The repo lives at `/srv/holojob`. The container is `holojob`.
- `./data` is bind-mounted to `/app/data`, so data edits need no copying.
  Code does: `podman-compose build` and a recreate (never `podman cp`).
- Changing `.env` requires `podman-compose up -d --force-recreate`; a
  restart does not re-read it.
