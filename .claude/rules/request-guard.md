---
paths:
  - "scripts/request-guard.js"
  - "scripts/read-body.js"
  - "scripts/api-handler.js"
  - "scripts/secret-mask.js"
  - "scripts/secret-paths.js"
  - "scripts/backup-handler.js"
  - "docker-compose.yml"
  - "tests/js/composePorts.test.js"
---

# Request guard (`/api`)

Every `/api` request passes `scripts/request-guard.js` first (`handleApiRoutes` in `api-handler.js`, used by the
production server and the Vite dev middleware): POST / PUT / PATCH need `Content-Type: application/json` (a DELETE only
when it has a body); the two binary uploads take their own type (`POST /api/cvs` PDF, `POST /api/backup/import` zip);
an `Origin` header must be an allowed origin; wrong type 415, wrong origin or host 403. It is not authentication.

- **Setting:** `HOLOJOB_ALLOWED_ORIGINS` in `.env`, comma separated, scheme optional and ignored, for example
  `https://holojob.void,http://localhost:3073`. With a list, the Origin AND the request's Host (or the proxy's
  `X-Forwarded-Host`) must be on it, which also stops DNS rebinding; reaching the app by another name (a LAN IP) then
  gets 403 until that name is added. With no list, an Origin must equal the request Host (same origin) and Host is not checked.
  A `.env` change needs `podman-compose up -d --force-recreate`.
- **Body limits:** `scripts/read-body.js` is the one reader of `/api` bodies: `MAX_JSON_BODY_BYTES` (1 MB) by default, `MAX_LARGE_BODY_BYTES` (25 MB) for the backup routes and the routes that post the whole job list (`/api/jobs/manual/sync`, `/api/applications/migrate` and its preview); some routes pass a limit of their own (secrets, settings, sources, CV upload, profile import). Past the limit it answers 413 itself.
  If a real backup restore fails with "Request body too large", raise `MAX_LARGE_BODY_BYTES`.
- Credentials are masked in error bodies, SSE errors, ledger reasons and console output by `scripts/secret-mask.js`
  (`sk-`/`AIza` keys, `key=` / `token=` query values, Authorization, `li_at`, long tokens). Backup export and restore use
  one exclusion list, `scripts/secret-paths.js`; a restore with `..` or an absolute path in the archive is refused whole.
- **No login (owner-accepted, DECISIONS.md 2026-10-29):** no application login and no Caddy `basic_auth`; access is the home LAN, and
  remote access only through Tailscale. Add the Tailscale hostname to `HOLOJOB_ALLOWED_ORIGINS` if it is used. Revisit if the app is
  ever exposed outside the LAN or Tailscale.
- **Bind:** `docker-compose.yml` publishes `127.0.0.1:3073:5173`, loopback only; other devices go through the reverse
  proxy (Caddy `holojob.void` -> `127.0.0.1:3073`). `tests/js/composePorts.test.js` fails if a port is published on all
  interfaces. Inside the container the app still listens on 0.0.0.0:5173, as podman's forwarding needs.
- Plan, approved decisions and step order (1 network / API protection, 2 AI keys, 3 `li_at`,
  4 AI settings, 5 profile / intelligence / jobs migration, 6 browser AI confirm dialog), with the pre-migration
  checklist: `docs/redesign/BROWSER_STORAGE_POLICY.md`. Browser keys outside its allowlist are not added.
