# Cutover to the Holojob folder, container and hostname

Temporary document: it names the old folder, container and host on purpose, and is deleted in the second rename stage.
Commands are for fish. Nothing here is run by Claude; the owner runs it. Values in `.env` are never printed below.

| | Old | New |
|---|---|---|
| Folder | `/srv/holojob` | `/srv/holojob` |
| Container | `holojob` | `holojob` |
| Image | `localhost/holojob_holojob:latest` | `localhost/holojob:latest` |
| Host (Caddy) | `holojob.void` | `holojob.void` |
| Port | `127.0.0.1:3073` | `127.0.0.1:3073` (unchanged, so Caddy's upstream stays) |

Data compatibility: the rename changes no data file, folder name or data format. The only new text in `data/` is the
`app` field of newly exported backups. The old code reads the new data and the new code reads the old data, so rollback is a
plain copy of `data/` back. If other work that changes data formats is deployed in between, it is not a pure rename any more:
roll back only before the new format has been written, or restore from the pre-cutover backup.

## 0. Before anything (no downtime)

1. Full safety copies, outside the repo: Settings > Backup / restore > download; Settings > Job statuses > export; a copy of `data/`
   and `.env` (for example `rsync -a /srv/holojob/data/ ~/holojob-precutover/data/` and `cp /srv/holojob/.env ~/holojob-precutover/`).
2. Check things I cannot see from the repo: your own backup scripts, cron or timers (`crontab -l`, `systemctl --user list-timers`),
   rsync jobs, the Caddy config, the DNS record source for `.void`, Tailscale serve config, bookmarks. Anything that names the old folder,
   the old host, `holojob-backup-*` file names or the old container must change in step 5.
3. Check how the container comes back after a reboot: `systemctl is-enabled podman-restart.service` (and `--user`). The compose
   project label `podman-compose@holojob.service` is only a label here; no such unit exists on this host.

## 1. Prepare the new folder (old service keeps running)

```fish
git clone /srv/holojob /srv/holojob -b rename-holojob      # or main, once the branch is merged
cd /srv/holojob
cp /srv/holojob/.env .env
cp -a /srv/holojob/claude-config claude-config
rsync -a /srv/holojob/data/ data/                            # a COPY: the old data stays untouched
sed -i 's/^HOLOJOB_ALLOWED_ORIGINS=/HOLOJOB_ALLOWED_ORIGINS=/; s/^HOLOJOB_ENGINE_SHADOW=/HOLOJOB_ENGINE_SHADOW=/; /^HOLOJOB_LLM_PROVIDER=/d' .env
```

Then edit `.env` by hand: the allowed origins must list the NEW host and, during the transition, the old one:
`https://holojob.void`, `https://holojob.void`, `http://localhost:3073` (comma separated, as before). Without a list the
Host check is off. Then:

```fish
python3.12 -m venv .venv; and .venv/bin/pip install -r requirements.txt     # a copied venv would keep the old path in its scripts
env HOLOJOB_COMMIT=(git rev-parse HEAD) podman-compose build
```

## 2. Validate the new container against the copy (different port, old service still up)

```fish
podman run --rm -d --name holojob-validate -p 127.0.0.1:3083:5173 \
  -v /srv/holojob/data:/app/data:Z -v /srv/holojob/claude-config:/root/.claude:Z \
  --env-file /srv/holojob/.env -e PORT=5173 -e CLAUDE_AUTO_LOGIN=0 -e HOME=/root \
  -e HOLOJOB_ALLOWED_ORIGINS=http://localhost:3083,http://127.0.0.1:3083 localhost/holojob:latest
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3083/api/config                      # 200
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example' http://127.0.0.1:3083/api/config  # 403: the Host check is on
podman logs holojob-validate | grep -c 'is not set'                                              # 0
```

Open `http://localhost:3083` and click through Jobs, Applications, Settings (the "About and source code" link shows the
commit). Do not run discovery or AI actions here: they would write into the COPY, which is fine, but spend money. Then
`podman stop holojob-validate`. The new folder's `data/` is overwritten in step 4, so nothing done here is kept.

## 3. Caddy and DNS (still no downtime)

Add a `holojob.void` site block with the same settings as the `holojob.void` block, pointing at `127.0.0.1:3073`, and a DNS
record for it. Keep the old block: after the cutover both hosts reach the same container, so the browser data stored under the
old origin stays readable until you move it.

## 4. The switch (short downtime)

```fish
cd /srv/holojob; and podman-compose down
rsync -a --delete /srv/holojob/data/ /srv/holojob/data/
rsync -ani --checksum /srv/holojob/data/ /srv/holojob/data/          # prints nothing when the copy is identical
cd /srv/holojob; and podman-compose up -d
podman ps --format '{{.Names}} {{.Ports}}'                              # holojob 127.0.0.1:3073->5173/tcp
curl -sk -o /dev/null -w '%{http_code}\n' https://holojob.void/api/config            # 200
curl -s  -o /dev/null -w '%{http_code}\n' -H 'Host: evil.example' http://127.0.0.1:3073/api/config   # 403
podman logs holojob | grep -c 'is not set'                              # 0
```

Then in the browser, on `https://holojob.void`: if the profile, intelligence or jobs list is empty (the browser still keeps
some of them per origin until the server migration is complete), restore from the backup zip and import the job-status export
from step 0. The old origin still has the originals until you clear its site data (step 5).

## Rollback (data stays compatible)

```fish
cd /srv/holojob; and podman-compose down
rsync -a --delete /srv/holojob/data/ /srv/holojob/data/      # carry what the new instance wrote
cd /srv/holojob; and podman-compose up -d                      # the old image is untouched
```

If the new instance has not written anything yet, skip the rsync. Keep the pre-cutover copy from step 0 until the soak period is over.

## 5. After a few days of normal use

1. Remove the `holojob.void` Caddy block and DNS record; drop `https://holojob.void` from `HOLOJOB_ALLOWED_ORIGINS`; recreate the
   container (`podman-compose up -d --force-recreate`). Clear site data for the old origin in the browser.
2. Update the outside-the-repo items found in step 0.2.
3. `mv /srv/holojob /srv/holojob.retired`; delete it, the old image (`podman rmi localhost/holojob_holojob:latest`) and the
   old rollback image tag only after you are sure. Retag a rollback image you want to keep under a new name.
4. In `/srv/holojob`: `graphify update .` and `.venv/bin/python tools/graphify_adapter/adapter.py build`; start Claude Code sessions there.
5. Tell Claude "cutover verified": the second stage removes the temporary reads of the old setting names, updates the folder
   path in the docs and deletes this file.
