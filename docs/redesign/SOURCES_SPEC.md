# Sources spec - job sources as user configuration

**Draft, for the roadmap phase "3b" in [../ROADMAP.md](../ROADMAP.md).** Implements
[DECISIONS.md](DECISIONS.md) principle 16 (job sources are user configuration, not code) with principle 15
(server-side master for new stores). No code exists yet.

## Goal

A **Settings > Sources** screen where the owner manages job boards and watched companies without code changes:
switch a board on or off, paste a company's careers or board link to watch it, see whether it works, remove it. Today
the active set is whatever the hard-coded `serbia` provider group and the repo's `companies/*.json` say.

## Reference (study, do not copy)

[applypack/applypack](https://github.com/applypack/applypack) solved the same problem. We read it as a reference
under the porting rule in DECISIONS.md: we design our own version for our stack (Python providers, a Node API, React
settings) and do not copy its TypeScript.

| ApplyPack source | What it does well | What we do differently, and why |
|---|---|---|
| `src/text-utils.ts` `extractAtsToken` | One pure function turns a careers or board URL into an ATS type and slug, with one pattern per vendor (including the vendor's API URL form), generic subdomains excluded and case kept where the vendor's API is case-sensitive. | Same idea, but only for the ATSs we have providers for: Greenhouse, Lever, Ashby and Workable. We add them one at a time with the provider, not twelve up front. |
| `src/web/add-company.ts` | People paste what they copy, a link, so the add form reads the link before treating the input as a slug. The link wins over the dropdown, and a link that names no board is a careers page, not an error. | We have no vendor dropdown: the user pastes a link or a slug and we detect. A link that matches no known ATS is rejected with a clear message in the first version, since careers-page watching is later. |
| `src/ats-probe.ts` | A live check against the vendor's public endpoint returns "works, N jobs" or a precise failure. It separates a dead token (a 4xx) from rate limits and outages, which say nothing about the slug. | They keep a second HTTP layer for probing. We reuse our discovery providers for it (below), so a probe and a real run can never disagree about what a board returns. We keep the dead-token versus transient distinction. |
| `src/web/source-groups.ts` | Groups sources by kind (vendor boards that need a company row, aggregators that need none, the user's own feeds) and shows each with the install's real counts ("12 companies, 3 active"). | We show boards and companies as two lists, not three families, because we have no user feeds. We keep the counts and the rule that a vendor board with no company row fetches nothing. |
| ADR 0034, keyed sources | A source that needs a credential is gated until the key is pasted; keys are stored with the other secrets, masked, and redacted from every log and error. The vendor's terms are implemented in code (attribution, rate limits). | Phase later. We take the rules (gate until keyed, mask, redact errors, honour the vendor's rate limits) but store keys in `data/config/` server-side, never in the browser. |
| ADR 0036, careers-page watch | Never render a site; read only what it publishes for machines: the ATS behind the page, then a feed; at the bottom a page-text hash that only says "changed". Measured on twenty real companies: a board URL is not always a live board (Ashby's API is per-organisation opt-in), and guessed feed paths find blogs. | Phase later, same ladder and the same refusal to run a headless browser. The finding that matters now: **a recognised URL is not a working board, so every add is probed before it is saved as active.** |

## Design

### a. Job boards

Every discovery provider in `provider_registry.py` is listed with:

- an on/off switch (the owner's active set);
- the job count of its last run and the time of that run;
- its last error, if any;
- whether it needs a key (none do today; the column exists for later keyed sources).

This replaces the hard-coded `serbia` default: the active set is the user's, and `serbia` is only the seed for
migration. Boards that need a company list (Greenhouse, Lever, Ashby) show their company count and fetch nothing while
the list is empty. Boards that search by term (LinkedIn through JobSpy, Infostud, Workable) need no list.

### b. Companies

1. The owner pastes a careers page or board URL (or a bare slug and picks the ATS).
2. A pure parser detects ATS and slug: Greenhouse (`boards.greenhouse.io/<slug>`, `job-boards.greenhouse.io/<slug>`,
   the embed form), Lever (`jobs.lever.co/<slug>` and the EU host `jobs.eu.lever.co`), Ashby
   (`jobs.ashbyhq.com/<slug>`, the posting-API form). Slugs are lower-cased except where the vendor is case-sensitive.
3. The company is **probed live through the existing provider**: the provider's single-company fetch is exposed
   (today it is a private method that swallows errors) and returns jobs plus a typed failure. There is no second HTTP
   layer. The screen shows the open job count, or the failure.
4. Failures are told apart: a 404 or 4xx on a lookup means a dead slug (not saved as active); a timeout, 429 or 5xx
   says nothing about the slug (saved, marked "could not verify", retried by re-probe).
5. Per-company switch, remove, and re-probe at any time. A company with zero open jobs is valid and stays.

Workable has no per-company mode in our client today (`workable_client.py` searches the public job index by term), so
company watching covers Greenhouse, Lever and Ashby first. Workable companies are an addition once its client can list
one account's jobs.

### c. Later

- **Careers-page change watch**, following ApplyPack's ADR 0036: ATS behind the page, then a published feed, then a
  text hash that reports "changed" and never claims to know the jobs. No headless browser.
- **Keyed sources** (for example Adzuna), following ADR 0034: gated until the key is pasted, stored server-side,
  masked in the UI, redacted from logs and errors, with the vendor's terms implemented as code.

## Storage

`data/config/sources.json`, private and git-ignored like the rest of `data/`. The server is the master; the browser
holds no copy in `localStorage` (principle 15), and the API reads and writes the file. Discovery reads the same file.

```json
{
  "version": 1,
  "updatedAt": "2026-10-25T12:00:00Z",
  "boards": {
    "jobspy":     { "active": true,  "lastRun": { "at": "2026-10-25T03:00:00Z", "jobs": 112, "error": null } },
    "infostud":   { "active": true,  "lastRun": null },
    "greenhouse": { "active": true,  "lastRun": null }
  },
  "companies": [
    {
      "id": "greenhouse:jetbrains",
      "ats": "greenhouse",
      "slug": "jetbrains",
      "name": "JetBrains",
      "active": true,
      "addedAt": "2026-10-25T12:00:00Z",
      "probe": { "at": "2026-10-25T12:00:00Z", "ok": true, "openJobs": 54, "error": null }
    }
  ],
  "keys": {}
}
```

| Field | Meaning |
|---|---|
| `version` | Integer shape version. A newer file than the code understands is refused, never rewritten. |
| `boards.<provider>` | One entry per provider name in `provider_registry.py`. `active` is the owner's switch. A provider missing from the file is inactive. |
| `boards.<provider>.lastRun` | `{ at, jobs, error }` of the last discovery run that used it; null before the first. Written by discovery. |
| `companies[]` | Watched companies. `id` is `<ats>:<slug>` and unique. `ats` is `greenhouse`, `lever` or `ashby`. `name` is a display name (the slug when unknown). |
| `companies[].probe` | The last live check: `ok`, `openJobs`, `error` with a kind (`dead_slug`, `unverified`), and when. |
| `keys` | Reserved for keyed sources; empty until then. Never returned to the browser unmasked and never logged. |

Writes are atomic (write a temp file, rename) and go through one function so the API and discovery cannot corrupt each
other. The file lives under `./data`, which is bind-mounted into the container, so it survives rebuilds.

## Migration

On the first run after the upgrade, if `data/config/sources.json` does not exist, it is created from:

- `companies/greenhouse.json`, `lever.json` and `ashby.json` (each entry becomes an active company, unprobed);
- the current default provider group: the six providers of `serbia` start active, all others inactive.

After that the repo's `companies/*.json` and the group definitions are **not read at runtime**; the files stay in git
only as the seed (and may be removed once the seed is no longer needed). Migration never overwrites an existing
`sources.json`.

## Discovery

- Discovery reads only active boards and, for the company-list providers, only active companies from
  `sources.json`.
- The CLI `--providers` flag still overrides the active set for one run (for example `--providers jobspy`), and does
  not change the file.
- With an empty active set, discovery stops with a message that says to enable a board in Settings > Sources; there is
  no fallback group.
- After a run, discovery writes each board's `lastRun`.

## Tests

- URL parsing per ATS: every supported URL form, a bare slug, trailing paths and query strings, upper-case hosts, the
  EU Lever host, generic or empty slugs, and URLs that match no ATS.
- Probe: success with a count (including zero), 404 as dead slug, 429, timeout and 5xx as unverified, malformed JSON.
- Migration: seeds from the repo files and the default group, is idempotent, and never overwrites an existing file;
  a newer `version` is refused.
- Discovery respects the switches: an inactive board and an inactive company are skipped, `--providers` overrides for
  one run, an empty active set stops with the message, and `lastRun` is written.
- No runtime read of `companies/*.json` after migration (a test fails if a provider opens the repo file).
- API: add, switch, remove and re-probe through the routes, with keys masked.

## Acceptance

1. Adding a company from a pasted URL works end to end: parse, live probe, shown with its open job count, included in
   the next discovery run.
2. Turning a board off removes it from the next run.
3. No source list in git is read as runtime config.
4. The standard `npm run discover:jobs` uses the owner's active set, not a hard-coded group.
