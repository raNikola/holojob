"""Client for the public Workable job board (jobs.workable.com).

Workable serves its board as a SPA, but the data comes from a plain JSON
endpoint that needs no key:

    GET https://jobs.workable.com/api/v1/jobs?query=<text>&location=<place>

    {
      "totalSize": 18,
      "jobs": [ { id, title, company, location, locations, workplace,
                  employmentType, description, created, updated, url } ]
    }

The full description ships inside the list response, so unlike Infostud
there is no per-ad detail fetch. It arrives as HTML and is stripped here.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from providers.role_filter import role_drop_reason

API = "https://jobs.workable.com/api/v1/jobs"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _get_json(params: dict) -> dict:
    url = f"{API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en;q=0.9",
        },
    )
    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"Workable unreachable: {url}") from last_error


def _strip_html(markup: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup or "", flags=re.S | re.I)
    text = re.sub(r"</(p|div|li|h[1-6]|ul|ol)>", "\n", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _as_text(value) -> str:
    """Workable sends location and company as either a string or an object."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("name", "title", "city", "location", "label"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return found.strip()
        parts = [
            str(value.get(k)).strip()
            for k in ("city", "region", "country")
            if value.get(k)
        ]
        return ", ".join(parts)
    if isinstance(value, list) and value:
        return _as_text(value[0])
    return ""

def _location_text(row: dict) -> str:
    """Build a country-qualified location string.

    Workable sends {"city": "", "subregion": null, "countryName": "Serbia"}.
    Downstream geo filters match on the country, so it is always included;
    the "TELECOMMUTE" placeholder from the locations list is dropped.
    """
    raw = row.get("location")
    if isinstance(raw, dict):
        city = (raw.get("city") or "").strip()
        region = (raw.get("subregion") or "").strip() if raw.get("subregion") else ""
        country = (raw.get("countryName") or raw.get("country") or "").strip()
        parts = [part for part in (city, region, country) if part]
        if parts:
            return ", ".join(parts)

    text = _as_text(raw) or _as_text(row.get("locations"))
    if text and text.upper() != "TELECOMMUTE":
        return text
    return "Remote"

def _iso_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return str(value)[:10]


def search(query: str, location: str = "", limit: int = 100) -> list[dict]:
    params = {"query": query}
    if location:
        params["location"] = location
    payload = _get_json(params)
    jobs = payload.get("jobs") or []
    total = payload.get("totalSize")
    # The endpoint has returned everything in one response so far. If that
    # ever stops holding, this is where paging would go.
    if isinstance(total, int) and total > len(jobs):
        print(f"  note: Workable reported {total} but returned {len(jobs)}")
    return jobs[:limit]


def normalize(row: dict) -> dict:
    workplace = (_as_text(row.get("workplace")) or "").lower()
    location = _as_text(row.get("location")) or _as_text(row.get("locations"))
    description = _strip_html(row.get("description") or "")
    requirements = _strip_html(row.get("requirementsSection") or "")
    if requirements:
        description = f"{description}\n\n{requirements}".strip()

    return {
        "externalId": row.get("id"),  # Workable's own id; the canonical job has no slot for it (staging keeps it beside)
        "jobId": "",
        "provider": "workable",
        "source": "workable",
        "site": "workable",
        "title": (row.get("title") or "").strip(),
        "company": _as_text(row.get("company")),
        "location": _location_text(row),
        "jobUrl": row.get("url") or "",
        "description": description,
        "datePosted": _iso_date(row.get("created")),
        "isRemote": workplace == "remote",
        "workMode": workplace or "unknown",
        "employmentType": _as_text(row.get("employmentType")),
        "scrapedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def fetch_jobs(
    search_terms: tuple[str, ...],
    location: str = "Serbia",
    extra_terms: tuple[str, ...] = (),
    delay: float = 1.0,
    counts: dict | None = None,
    on_batch=None,
) -> list[dict]:
    """The relevant ads. `counts`, when given, receives "read": how many different ads came back before the role filter.
    `on_batch`, when given, is called after each search term with (term, the ads that term added, the ads it dropped as
    [(ad, reason, counted)]). An ad seen again under another term is a copy, not a second ad, and is not reported twice."""
    by_url: dict[str, dict] = {}
    read: set[str] = set()
    dropped_urls: set[str] = set()
    for term in search_terms:
        added = []
        dropped = []
        for row in search(term, location):
            job = normalize(row)
            first_sight = job["jobUrl"] not in read
            read.add(job["jobUrl"])
            if not job["jobUrl"]:
                # All rows without an address count as one entry in `read`, so only the first is counted.
                dropped.append((job, "no_url", first_sight))
                continue
            if job["jobUrl"] in by_url:
                continue
            reason = role_drop_reason(job["title"], "", extra_terms or search_terms)
            if reason is None:
                by_url[job["jobUrl"]] = job
                added.append(job)
            elif job["jobUrl"] not in dropped_urls:
                dropped_urls.add(job["jobUrl"])
                dropped.append((job, reason, True))
        if on_batch is not None:
            on_batch(term, added, dropped)
        time.sleep(delay)
    if counts is not None:
        counts["read"] = len(read)
    return list(by_url.values())


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        raise SystemExit("usage: python workable_client.py <country or location>")
    LOCATION = sys.argv[1]

    TERMS = (
        "Technical Product Manager",
        "Senior Product Manager",
        "Product Manager",
        "Product Lead",
        "Product Owner",
    )

    raw_first = search("Product Manager", LOCATION)
    if raw_first:
        print("raw location field:", json.dumps(raw_first[0].get("location"))[:200])
        print("raw company field :", json.dumps(raw_first[0].get("company"))[:200])
        print("raw workplace     :", json.dumps(raw_first[0].get("workplace"))[:200])
        print()

    matches = fetch_jobs(TERMS, LOCATION)
    print(f"relevant: {len(matches)}")
    for job in matches:
        print(f"  {job['title']}")
        print(f"     {job['company']} | {job['location']} | {job['workMode']}")
        print(f"     {job['jobUrl']}")
        print(f"     description: {len(job['description'])} chars")