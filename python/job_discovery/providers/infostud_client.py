"""Client for Infostud (poslovi.infostud.com), Serbia's largest job board.

Infostud runs on Next.js: the job list ships as JSON inside
<script id="__NEXT_DATA__">, so neither a browser nor HTML parsing is needed.

API contract, established empirically on 2026-10-21:

    GET /oglasi-za-posao?category[0]=<id>&category[1]=<id>&page=<n>

    __NEXT_DATA__.props.pageProps.initialSearchResults
        .totalPrimaryItems   total number of results
        .jobs.primary        list of jobs, 30 per page
        .page                echo of the requested page number

Free-text `q` is deliberately not used. Infostud ORs the query words and
ranks loosely, so "Product Lead" returns warehouse operators and PCB
engineers. We pull whole categories instead and filter locally on title.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from providers.role_filter import is_relevant_role, role_drop_reason

BASE = "https://poslovi.infostud.com/oglasi-za-posao"
PAGE_SIZE = 30
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Category id -> label, kept for readable logs.
CATEGORIES = {
    5: "IT",
    1: "management (mid)",
    22: "management (senior)",
    29: "telecommunications",
    48: "marketing",
    58: "banking",
}
DEFAULT_CATEGORIES = tuple(CATEGORIES)

def _get(url: str, retries: int = 3, backoff: float = 2.0) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "sr,en;q=0.8"},
    )
    last_error = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"Infostud unreachable: {url}") from last_error


def _next_data(html: str) -> dict:
    marker = html.find("__NEXT_DATA__")
    if marker < 0:
        raise ValueError("__NEXT_DATA__ not found -- the site layout likely changed")
    start = html.find(">", marker) + 1
    end = html.find("</script>", start)
    return json.loads(html[start:end])


def _search_results(html: str) -> dict:
    data = _next_data(html)
    return (
        data.get("props", {})
        .get("pageProps", {})
        .get("initialSearchResults", {})
    ) or {}


def _page_url(categories, page: int) -> str:
    params = [(f"category[{i}]", str(c)) for i, c in enumerate(categories)]
    if page > 1:
        params.append(("page", str(page)))
    return f"{BASE}?{urllib.parse.urlencode(params)}"


def _iso_date(value: str | None) -> str | None:
    """Convert Infostud's '20.10.2026' into '2026-10-20'."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date().isoformat()
    except ValueError:
        return None


def fetch_raw(categories=DEFAULT_CATEGORIES, max_pages: int = 40, delay: float = 1.5, facts: dict | None = None):
    """Page through the given categories. Returns (raw rows, reported total).

    `facts`, when given, receives how the read ended (Wave 4, c), for the completeness proof: `pages` read, `capHit` (the page cap
    stopped it before the reported total), `clampHit` (a page held no new id), `emptyEnd` (an empty page ended it) and `reachedTotal`.
    """
    seen: dict[int, dict] = {}
    page = 1
    total = None
    end = {"pages": 0, "capHit": False, "clampHit": False, "emptyEnd": False, "reachedTotal": False}

    while page <= max_pages:
        results = _search_results(_get(_page_url(categories, page)))
        end["pages"] = page
        if total is None:
            total = results.get("totalPrimaryItems") or 0
        rows = (results.get("jobs") or {}).get("primary") or []
        if not rows:
            end["emptyEnd"] = True
            break

        fresh = 0
        for row in rows:
            job_id = row.get("id")
            if job_id is not None and job_id not in seen:
                seen[job_id] = row
                fresh += 1

        # Guard: if the server clamps back to the same page, stop rather
        # than loop until max_pages.
        if fresh == 0:
            end["clampHit"] = True
            break
        if len(seen) >= total:
            end["reachedTotal"] = True
            break

        page += 1
        time.sleep(delay)
    else:
        end["capHit"] = True

    if facts is not None:
        facts.update(end)
    return list(seen.values()), total or 0

def _tag_names(raw_tags) -> list[str]:
    """itTags arrives as plain strings; tolerate dicts in case that changes."""
    names = []
    for tag in raw_tags or []:
        if isinstance(tag, str):
            name = tag.strip()
        elif isinstance(tag, dict):
            name = (tag.get("name") or "").strip()
        else:
            name = ""
        if name:
            names.append(name)
    return names

def normalize(row: dict) -> dict:
    """Map an Infostud row onto the job shape the rest of the pipeline uses."""
    url = row.get("url") or ""
    summary = ((row.get("jobSummary") or {}).get("summary") or "").strip()
    snippet = (row.get("textAdSnippet") or "").strip()
    description = "\n\n".join(part for part in (summary, snippet) if part)

    # Infostud stores location as "Beograd", "Beograd | Hibrid" or
    # "Srbija | Terenski rad". Downstream filters match on country, so the
    # country is appended here rather than inferred later.
    raw_location = (row.get("location") or "").strip()
    city = raw_location.split("|")[0].strip()
    if not city or city.lower() in ("srbija", "serbia", "rad od kuće", "rad od kuce"):
        location = "Serbia"
    else:
        location = f"{city}, Serbia"

    is_remote = bool(row.get("workFromHome"))
    if is_remote:
        work_mode = "remote"
    elif row.get("hybridWork"):
        work_mode = "hybrid"
    elif row.get("fieldwork"):
        work_mode = "fieldwork"
    else:
        work_mode = "onsite"

    return {
        "externalId": row.get("id"),  # Infostud's own number; the canonical job has no slot for it (staging keeps it beside)
        "jobId": hashlib.sha1(url.encode("utf-8")).hexdigest()[:16],
        "provider": "infostud",
        "source": "infostud",
        "site": "infostud",
        "title": (row.get("title") or "").strip(),
        "company": (row.get("companyName") or "").strip(),
        "location": location,
        "jobUrl": url,
        "description": description,
        "datePosted": _iso_date(row.get("onlineViewDate")),
        "expiresAt": _iso_date(row.get("expirationDate")),
        "isRemote": is_remote,
        "workMode": work_mode,
        "salary": row.get("salary"),
        "category": (row.get("primaryCategory") or {}).get("name"),
        "standardizedPosition": (row.get("standardizedPosition") or {}).get("name"),
        "tags": _tag_names(row.get("itTags")),
        "scrapedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def enrich(job: dict, delay: float = 1.0) -> dict:
    """Replace the summary with the full JobPosting JSON-LD description.

    Costs one request per job, so this runs only for jobs that already
    passed is_relevant_role().
    """
    url = job.get("jobUrl")
    if not url:
        return job

    try:
        html = _get(url)
    except RuntimeError:
        return job

    position = 0
    while True:
        marker = html.find("application/ld+json", position)
        if marker < 0:
            break
        start = html.find(">", marker) + 1
        end = html.find("</script>", start)
        position = end + 1
        try:
            parsed = json.loads(html[start:end])
        except json.JSONDecodeError:
            continue
        for item in parsed if isinstance(parsed, list) else [parsed]:
            if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                continue
            full = (item.get("description") or "").strip()
            if len(full) > len(job.get("description") or ""):
                job["description"] = full
            job["employmentType"] = item.get("employmentType")
            job["benefits"] = item.get("jobBenefits") or []

    time.sleep(delay)
    return job


def fetch_jobs(
    categories=DEFAULT_CATEGORIES,
    enrich_matches: bool = True,
    extra_terms: tuple[str, ...] = (),
    counts: dict | None = None,
    on_job=None,
    on_drop=None,
) -> list[dict]:
    """The relevant ads. `counts`, when given, receives "read" (ads fetched before the role filter) and "reported" (the total the site says its search has).
    `on_job`, when given, is called with each relevant ad as soon as it is complete (after its full description is read),
    so a caller can keep it before the next, slow request.
    `on_drop`, when given, is called once with [(ad, reason)] for the ads the role filter dropped (see role_drop_reason),
    before any description is read."""
    facts: dict = {}
    raw, reported = fetch_raw(categories, facts=facts)
    jobs = [normalize(row) for row in raw]
    if counts is not None:
        counts["read"] = len(jobs)
        counts["reported"] = reported
        counts["facts"] = facts
    matches = []
    dropped = []
    for job in jobs:
        reason = role_drop_reason(job.get("title", ""), job.get("standardizedPosition") or "", extra_terms)
        if reason is None:
            matches.append(job)
        else:
            dropped.append((job, reason))
    if on_drop is not None and dropped:
        on_drop(dropped)
    if enrich_matches:
        done = []
        for job in matches:
            done.append(enrich(job))
            if on_job is not None:
                on_job(done[-1])
        matches = done
    elif on_job is not None:
        for job in matches:
            on_job(job)
    return matches


if __name__ == "__main__":
    raw_rows, reported_total = fetch_raw()
    all_jobs = [normalize(row) for row in raw_rows]
    relevant = [
        job for job in all_jobs
        if is_relevant_role(job.get("title", ""), job.get("standardizedPosition") or "")
    ]

    print(f"categories : {', '.join(CATEGORIES[c] for c in DEFAULT_CATEGORIES)}")
    print(f"reported   : {reported_total}")
    print(f"fetched    : {len(all_jobs)}")
    print(f"relevant   : {len(relevant)}")
    print()
    for job in relevant:
        print(f"  {job['title']}")
        print(f"     {job['company']} | {job['location']} | {job['workMode']}")
        print(f"     position={job['standardizedPosition']} category={job['category']}")
        print(f"     {job['jobUrl']}")