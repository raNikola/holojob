# Job Discovery (Module 3)

Python pipeline that uses [JobSpy](https://github.com/speedyapply/JobSpy) to discover jobs from Module 2 search strategy.

## Prerequisites

- Python 3.10+
- Node.js project root at `job-automation-dashboard`

## Setup

From project root:

```bash
npm run setup:jobspy
```

Or manually:

```bash
bash scripts/setup-jobspy.sh
source .venv/bin/activate
```

## Input

Save exported intelligence to:

```
data/intelligence/candidate-intelligence.json
```

Required fields: `searchStrategy.jobSpySearchTerms`, `searchStrategy.locationFilters`, `searchStrategy.remoteFilters`.

## Run discovery

```bash
source .venv/bin/activate
python python/job_discovery/run_jobspy.py
```

## Output

```
data/jobs/raw_jobs.csv
data/jobs/normalized_jobs.json
data/jobs/discovered_jobs.json
```

Import `discovered_jobs.json` in the React Job Discovery dashboard.

## Module 3.1 — Multi-Provider Discovery

Setup (JobSpy + Playwright):

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

The existing JobSpy-only runner is unchanged:

```bash
python python/job_discovery/run_jobspy.py --country <country> --locations "<city>, <country>" "Remote"
```

## Notes

- Scraping depends on network access and job board rate limits.
- LinkedIn may fail individually; Indeed/Glassdoor/Google continue.
- **Indeed / Glassdoor:** pass an exact country name via `--country` (e.g. `USA`, `UK`). The adapter sets JobSpy `country_indeed` accordingly. Use `--locations` for city narrowing. Remote locations use `is_remote=True` with country scoping only.
