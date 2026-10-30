"""Client for Joberty (joberty.com), a Serbian and regional IT job board.

Joberty has no documented API. Its site calls a public JSON backend that needs
no key, and this client makes the same anonymous GET requests, nothing else:

    GET /api/v1/jobs?page=<n>&pageSize=<n>&sort=created&domains=<domain>
        {"items": [...], "totalElements": n, "totalPage": n}   page is 0-based
    GET /api/v1/jobs/<id>
        one ad: `text` is the full HTML description, `applyUrl` the real apply link
    GET /api/v1/jobs/filters-all
        [{"type": "CITY", "filters": [{"value": "Belgrade (Serbia)", "count": 28}, ...]}, ...]

Every item carries a base64 logo of about 19 kB (a detail adds a cover image of
about 40 kB), so a listing is always filtered by domain first, and the images are
dropped as soon as a response is parsed.

Because the API is undocumented and Joberty's terms have not been checked, the
client is deliberately light: a normal User-Agent, one request at a time with a
pause between them, at most MAX_LISTING_PAGES listing pages and MAX_DETAILS ad
details per run. It sends nothing about the candidate. It never raises to its
caller: a failure is logged and an empty result returned.
"""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

BASE = "https://backend.joberty.com"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_DOMAINS = ("Product Management",)
DEFAULT_PAGE_SIZE = 50
MAX_LISTING_PAGES = 3
MAX_DETAILS = 25
TIMEOUT = 30
RETRIES = 2  # after the first attempt
BACKOFF = 3.0  # seconds, times the attempt number
MIN_GAP, MAX_GAP = 1.5, 2.0  # seconds between two requests
IMAGE_FIELDS = ("logo", "coverImage")

_sleep = time.sleep  # the tests replace these two
_monotonic = time.monotonic
_last_request: float | None = None


class JobertyError(RuntimeError):
    """A request that failed for good (after its retries, or one that is not worth retrying)."""


def _pace() -> None:
    """Wait so that two requests are never closer than a random 1.5 to 2 seconds."""
    global _last_request
    if _last_request is not None:
        wait = random.uniform(MIN_GAP, MAX_GAP) - (_monotonic() - _last_request)
        if wait > 0:
            _sleep(wait)
    _last_request = _monotonic()


def _get_json(path: str, params: dict | None = None):
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    last_error: Exception | None = None
    for attempt in range(RETRIES + 1):
        _pace()
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500:
                raise JobertyError(f"Joberty answered {exc.code}: {path}") from exc
            last_error = exc
        except (urllib.error.URLError, OSError) as exc:  # timeouts are OSErrors
            last_error = exc
        except ValueError as exc:
            raise JobertyError(f"Joberty sent invalid JSON: {path}") from exc
        if attempt < RETRIES:
            _sleep(BACKOFF * (attempt + 1))
    raise JobertyError(f"Joberty unreachable: {path}") from last_error


def _without_images(row: dict) -> dict:
    return {key: value for key, value in row.items() if key not in IMAGE_FIELDS}


def fetch_listing(domains=DEFAULT_DOMAINS, page_size: int = DEFAULT_PAGE_SIZE) -> list[dict]:
    """Ads of the given domain(s), newest first, at most MAX_LISTING_PAGES pages.

    Only a single domain has been exercised against the live API. On a failure
    the pages already read are kept and the rest is skipped.
    """
    items: list[dict] = []
    try:
        for page in range(MAX_LISTING_PAGES):
            data = _get_json(
                "/api/v1/jobs",
                {
                    "page": page,
                    "pageSize": page_size,
                    "sort": "created",
                    "domains": ",".join(domains),
                },
            )
            rows = data.get("items") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise JobertyError("Joberty listing has no items list -- the API likely changed")
            items.extend(_without_images(row) for row in rows if isinstance(row, dict))
            total_pages = data.get("totalPage")
            if not rows or not isinstance(total_pages, int) or page + 1 >= total_pages:
                break
    except JobertyError as exc:
        logger.warning("Joberty listing stopped: %s", exc)
    return items


def fetch_detail(job_id: int | str) -> dict:
    """The full ad, or {} when it cannot be read."""
    try:
        data = _get_json(f"/api/v1/jobs/{job_id}")
    except JobertyError as exc:
        logger.warning("Joberty ad %s skipped: %s", job_id, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("Joberty ad %s skipped: unexpected response", job_id)
        return {}
    return _without_images(data)


def fetch_cities() -> list[str]:
    """The place names Joberty lists ads under ("Belgrade (Serbia)", "Croatia", ...), or []."""
    try:
        data = _get_json("/api/v1/jobs/filters-all")
    except JobertyError as exc:
        logger.warning("Joberty facets unavailable: %s", exc)
        return []
    for group in data if isinstance(data, list) else []:
        if isinstance(group, dict) and group.get("type") == "CITY":
            return [
                f["value"].strip()
                for f in group.get("filters") or []
                if isinstance(f, dict) and isinstance(f.get("value"), str) and f["value"].strip()
            ]
    logger.warning("Joberty facets have no CITY group -- the API likely changed")
    return []
