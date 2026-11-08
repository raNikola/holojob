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
- **Fast deploy (fish), lost on recreate unless the image is rebuilt:** frontend: build `dist` in a throwaway
  `node:20-bookworm` container (`--security-opt label=disable`), `podman exec holojob rm -rf /app/dist`,
  `podman cp dist holojob:/app/dist`. Python: `tar --exclude=__pycache__ -C python -cf - . | podman cp - holojob:/app/python`.
  Node `scripts/` or `src/`: the same with tar, then `podman restart holojob`. Exact commands in `docs/ARCHITECTURE.md`.

Detail: `docs/ARCHITECTURE.md` (Container gotchas).

## From Conventions

- The repo lives at `/srv/holojob`. The container is `holojob`.
- `./data` is bind-mounted to `/app/data`, so data edits need no copying.
  Code does: either `podman cp` for a quick test, or `podman-compose build`
  to make it permanent.
- Changing `.env` requires `podman-compose up -d --force-recreate`; a
  restart does not re-read it.
