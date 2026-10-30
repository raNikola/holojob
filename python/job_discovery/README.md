# Job Discovery

Python pipeline that discovers jobs from the search strategy in the candidate intelligence, through several providers (JobSpy for LinkedIn, Infostud, Workable, Greenhouse, Lever, Ashby and others).

## Prerequisites

- Python 3.12 (3.11 works; the pinned pandas has no wheel for 3.15)
- Node.js at the project root

## Input

Save exported intelligence to:

```
data/intelligence/candidate-intelligence.json
```

Required fields: `searchStrategy.jobSpySearchTerms`, `searchStrategy.locationFilters`, `searchStrategy.remoteFilters`.

## Output

```
data/jobs/discovered_jobs.json
data/jobs/job_history.json
```

The Jobs screen reads `discovered_jobs.json` after scoring.

## Multi-provider discovery

Setup (venv, requirements, Playwright):

```bash
npm run setup:jobs
source .venv/bin/activate
```

Run multi-provider discovery:

```bash
python python/job_discovery/run_discovery.py --providers serbia
python python/job_discovery/run_discovery.py --providers ats
python python/job_discovery/run_discovery.py --providers all --country <country>
python python/job_discovery/run_discovery.py --providers jobspy,greenhouse,lever
```

The country comes from `--country`, else from `searchStrategy.country` or
`jobFitPreferences.country` in the candidate intelligence. With neither, discovery
stops and says so; there is no default country.

Provider groups: `all`, `ats`, `remote`, `startup`, `serbia`. `--providers` also takes a comma list that mixes groups and names (`serbia,joberty`).

## Joberty (opt-in)

`joberty` reads Joberty (joberty.com), a Serbian and regional IT board, through the JSON backend its own site
calls (`https://backend.joberty.com/api/v1/jobs`, product-management domain only). It is in **no** provider group, so
no default run touches it:

```bash
python python/job_discovery/run_discovery.py --providers serbia,joberty   # the standard run plus Joberty
python python/job_discovery/run_discovery.py --providers joberty
```

On the Jobs screen the "Include Joberty (Serbian IT board)" box next to "Re-scrape jobs" adds it (off by default, remembered
in the browser).

- **The API is undocumented** and can change without notice. The client fails soft: any error is logged and the source
  returns nothing, the other providers carry on.
- **Terms caveat:** Joberty's terms have not been reviewed for this use. The owner's note points to sections 7 and 8 of them;
  read those before turning the box on. Nothing about the candidate is ever sent: anonymous GETs only.
- **Polite by design:** a normal User-Agent, 30 s timeout, 1.5 to 2 s between requests, two retries with backoff on 429 / 5xx,
  at most 3 listing pages and 25 ad details per run. Ads the job-history ledger already holds with a real description are
  not fetched again; ads over the cap wait for the next run.
- **Countries** come from Joberty's own place facet (`filters-all`); for a country it does not list, the source returns nothing
  and logs it. Role matching is on the title (`is_relevant_role`); the board's domain tag only narrows the listing.
- Not closed when they disappear (only the ATS providers list every open posting). `salary`, `datePosted` and
  `employmentType` stay empty; `seniority`, `domains`, `technologies`, `applyUrl`, `expiresAt` and `externalId` (`joberty:<id>`)
  are kept as extra fields. A company's trailing country ("Fivetran Serbia") is ignored in the title + company duplicate key.

## Notes

- Scraping depends on network access and job board rate limits.
- LinkedIn may fail or rate-limit; the other providers continue. Serbia is not supported by Indeed or Glassdoor, so the `serbia` group uses LinkedIn only through JobSpy.
- **Indeed / Glassdoor:** pass an exact country name via `--country` (e.g. `USA`, `UK`). The adapter sets JobSpy `country_indeed` accordingly. Use `--locations` for city narrowing. Remote locations use `is_remote=True` with country scoping only.
