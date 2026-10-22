# ATS Company Configs

Company board slugs for job discovery, built from this candidate's own
application history: companies that have actually hired for this profile,
on the three ATS platforms the `greenhouse`, `lever` and `ashby` providers
read (`python/job_discovery/providers/provider_registry.py`'s `"serbia"`
group). Not every company in the history is here -- a company is added
only once its ATS and board slug are confirmed against the live API; see
"How to find board slugs" below. Companies on other systems (Workable,
Jobvite, Recruitee, an in-house portal) are left out: Workable postings are
already covered by the `workable` provider's public board search, and the
rest have no provider in this repo.

## Files

| File | ATS | Format |
|------|-----|--------|
| `greenhouse.json` | Greenhouse | `[{ "company": "Stripe", "board": "stripe" }, ...]` |
| `lever.json` | Lever | `["figma", "netflix", ...]` |
| `ashby.json` | Ashby | `["cursor", "linear", ...]` |

## How to find board slugs

### Greenhouse
1. Open a company's careers page (e.g. `https://boards.greenhouse.io/stripe`)
2. The slug after `/boards/` is the `board` value
3. API: `https://boards-api.greenhouse.io/v1/boards/{board}/jobs`

### Lever
1. Open `https://jobs.lever.co/{company}`
2. `{company}` is the slug
3. API: `https://api.lever.co/v0/postings/{company}`
4. Some companies run on Lever's EU instance instead (`jobs.eu.lever.co`,
   `api.eu.lever.co`) and 404 on the main one. The provider tries both.

### Ashby
1. Open `https://jobs.ashbyhq.com/{slug}`
2. `{slug}` is the company identifier
3. API: `https://api.ashbyhq.com/posting-api/job-board/{slug}`

## Validate after editing

```bash
node scripts/validate-companies.js
```
