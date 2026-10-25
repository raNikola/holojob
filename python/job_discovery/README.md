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

Provider groups: `all`, `ats`, `remote`, `startup`, `serbia`.

## Notes

- Scraping depends on network access and job board rate limits.
- LinkedIn may fail or rate-limit; the other providers continue. Serbia is not supported by Indeed or Glassdoor, so the `serbia` group uses LinkedIn only through JobSpy.
- **Indeed / Glassdoor:** pass an exact country name via `--country` (e.g. `USA`, `UK`). The adapter sets JobSpy `country_indeed` accordingly. Use `--locations` for city narrowing. Remote locations use `is_remote=True` with country scoping only.
