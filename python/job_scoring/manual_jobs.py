"""Jobs the owner typed in by hand, kept apart from discovery.

Discovery rewrites discovered_jobs.json from scratch and scoring rebuilds scored_jobs.json from it, so a job that
lives only in either file is lost at the next run. A manual job therefore has its own input file,
data/jobs/manual_jobs.json, which no discovery code writes; run_scoring.py and import_job_url.py merge it into the
jobs they score.

Only the fields scoring reads cross into Python (SCORING_FIELDS). The owner's notes and extra links stay in the
browser: `sanitize` drops anything else without echoing it, so it cannot reach a file, a log line or an error.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[2]
MANUAL_PATH = ROOT / "data" / "jobs" / "manual_jobs.json"

JOB_ID = re.compile(r"^manual-[0-9a-f-]{36}$")
MAX_TEXT = 200_000

# What scoring and the job list need. Keep in step with SCORING_FIELDS in src/modules/jobs/manualJob.js.
SCORING_FIELDS = (
    "jobId", "title", "company", "description", "jobUrl", "location", "salary", "site", "provider",
    "manualEntry", "sourceChoice", "status", "createdAt", "firstSeen", "lastSeen", "scrapedAt",
)
REQUIRED = ("jobId", "title", "company", "description")
REQUIRED_WITHOUT_DESCRIPTION = ("jobId", "title", "company")
SOURCES = ("LinkedIn", "Company site", "Referral", "Other")


class InvalidJob(ValueError):
    """A manual job the server will not take. `field` names the problem; the value is never quoted."""

    def __init__(self, field: str):
        super().__init__(field)
        self.field = field


def normalize_url(raw) -> str | None:
    """http(s) only, lowercase host, no default port, userinfo, query, fragment or trailing slash; dot segments resolved.

    The same rule as normalizeJobUrl in src/modules/jobs/manualJob.js; tests/fixtures/url-normalisation.json is run by both.
    """
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parts = urlsplit(text)
        scheme = parts.scheme.lower()
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if scheme not in ("http", "https") or not host:
        return None
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    netloc = host if port in (None, {"http": 80, "https": 443}[scheme]) else f"{host}:{port}"
    resolved: list[str] = []
    for segment in parts.path.split("/"):
        if segment == "..":
            if len(resolved) > 1:
                resolved.pop()
        elif segment != ".":
            resolved.append(segment)
    path = re.sub(r"/+$", "", quote("/".join(resolved), safe="/%:@!$&'()*+,;=-._~"))
    return f"{scheme}://{netloc}{path}"


# Query parameters that say where a visitor came from, not which posting it is.
TRACKING_PARAMS = {"ref", "refid", "trackingid", "source", "gclid", "fbclid"}


def identity_url(raw) -> str | None:
    """`normalize_url` that keeps the query parameters which identify a posting (?gh_jid=, ?currentJobId=, ?jk=).

    The add-time duplicate check strips the whole query, as asked, and shows the clash to the owner. Anything that
    drops a row silently uses this key instead: a board that tells postings apart by query string must not collapse
    to one job. Tracking parameters (utm_*, ref, refId, trackingId, source, gclid, fbclid) are removed, the rest sorted.
    """
    base = normalize_url(raw)
    if not base:
        return None
    pairs = [
        (k, v) for k, v in parse_qsl(urlsplit(str(raw).strip()).query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    return f"{base}?{urlencode(sorted(pairs))}" if pairs else base


def sanitize(payload, *, now: str | None = None, require_description: bool = True) -> dict:
    """The manual job as stored: SCORING_FIELDS only, strings trimmed, the server's own flags set. Raises InvalidJob.

    A job is stored and scored only with its description (scoring a title alone would rank it on nothing); the
    write-nothing duplicate check passes `require_description=False`.
    """
    if not isinstance(payload, dict):
        raise InvalidJob("job")
    stamp = now or datetime.now(timezone.utc).isoformat()
    job: dict = {}
    for field in SCORING_FIELDS:
        value = payload.get(field)
        if value is None:
            continue
        if field == "manualEntry":
            continue
        if not isinstance(value, str):
            raise InvalidJob(field)
        value = value.strip()
        if len(value) > MAX_TEXT:
            raise InvalidJob(field)
        job[field] = value
    for field in REQUIRED if require_description else REQUIRED_WITHOUT_DESCRIPTION:
        if not job.get(field):
            raise InvalidJob(field)
    if not JOB_ID.match(job["jobId"]):
        raise InvalidJob("jobId")
    if job.get("jobUrl") and not normalize_url(job["jobUrl"]):
        raise InvalidJob("jobUrl")
    # An old "Source" select value stays as it was; a job without one gets none (no invented "Other").
    if job.get("sourceChoice") not in SOURCES:
        job.pop("sourceChoice", None)
    job.setdefault("location", "")
    job.setdefault("jobUrl", "")
    job.setdefault("site", "")
    if not job["site"] and job["jobUrl"]:
        job["site"] = (urlsplit(job["jobUrl"]).hostname or "").removeprefix("www.")
    for field in ("createdAt", "firstSeen", "lastSeen", "scrapedAt"):
        job.setdefault(field, stamp)
    job["provider"] = "manual"
    job["manualEntry"] = True
    job["status"] = "new"
    return job


def load(path: Path = MANUAL_PATH) -> list[dict]:
    """The stored manual jobs; a missing or unreadable file is no jobs."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    return [j for j in jobs if isinstance(j, dict) and j.get("jobId")] if isinstance(jobs, list) else []


def save(jobs: list[dict], path: Path = MANUAL_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"jobs": jobs}, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def upsert(jobs: list[dict], stored: list[dict]) -> list[dict]:
    """`stored` with each of `jobs` added, or replacing the row with its id (its first-seen and created dates stay)."""
    by_id = {j["jobId"]: j for j in stored}
    for job in jobs:
        before = by_id.get(job["jobId"]) or {}
        merged = {**job}
        for kept in ("createdAt", "firstSeen"):
            if before.get(kept):
                merged[kept] = before[kept]
        by_id[job["jobId"]] = merged
    return list(by_id.values())


def find_clash(job_id: str, url: str, *lists: list[dict]) -> dict | None:
    """A job in any of the lists with the same identity URL and another id, or None. The same id is a retry, not a clash.

    The identity URL, like the silent paths: ?gh_jid=-style parameters tell postings apart, tracking ones do not.
    """
    key = identity_url(url)
    if not key:
        return None
    for jobs in lists:
        for other in jobs or []:
            if other.get("jobId") != job_id and identity_url(other.get("jobUrl")) == key:
                return {"jobId": other.get("jobId"), "title": other.get("title") or "", "company": other.get("company") or ""}
    return None


def with_manual(jobs: list[dict], manual: list[dict]) -> list[dict]:
    """`jobs` plus the manual jobs. A row with a manual job's id, or its identity URL, is dropped: the manual one wins."""
    ids = {m["jobId"] for m in manual}
    urls = {u for u in (identity_url(m.get("jobUrl")) for m in manual) if u}
    kept = [j for j in jobs if j.get("jobId") not in ids and identity_url(j.get("jobUrl")) not in urls]
    return kept + [dict(m) for m in manual]


def mark_missing_facts(job: dict) -> None:
    """A job scored without the ad facts (enrichment never ran) is marked, as run_scoring.py marks it."""
    if not (job.get("llmFacts") or {}).get("_fingerprint"):
        job["aiEnrichment"] = "missing"
