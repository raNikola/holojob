#!/usr/bin/env python3
"""Import jobs into the dashboard from pasted URLs.

For each URL: fetch the page, extract the JD (schema.org JobPosting JSON-LD when
present, heuristics otherwise, Claude Code as a smart fallback parser), normalize
to the canonical job shape, append to discovered_jobs.json, score it against
candidate intelligence, and merge into scored_jobs.json WITHOUT touching other
jobs (preserves existing tailoredAssets).

With --job-json the job is given, not fetched: a hand-entered posting (Add job on the Jobs screen) is stored in
manual_jobs.json, scored together with the discovered jobs by the same score_jobs() a full run uses, and merged into
scored_jobs.json by the same merge. No URL fetch, no LLM, no network.

Prints a JSON summary to stdout for the Node wrapper.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python" / "llm"))
sys.path.insert(0, str(ROOT / "python" / "job_scoring"))

from atomic_write import write_text_atomic  # noqa: E402
import claude_code  # noqa: E402
import manual_jobs  # noqa: E402
import pipeline_lock  # noqa: E402
import view_guard  # noqa: E402
import safe_fetch  # noqa: E402
from scorer import score_jobs  # noqa: E402

DISCOVERED_PATH = ROOT / "data/jobs/discovered_jobs.json"
SCORED_PATH = ROOT / "data/jobs/scored_jobs.json"
INTELLIGENCE_PATH = ROOT / "data/intelligence/candidate-intelligence.json"

EXTRACT_PROMPT = """Extract the job posting from this web page text. Return ONLY a JSON \
object: {{"title": "", "company": "", "location": "", "employmentType": "", \
"salary": "", "isRemote": false, "description": "<the full job description text>"}}. \
Use empty strings for unknown fields. Do not invent information.

PAGE TEXT:
{text}"""


def _job_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _clean_html_text(value: str) -> str:
    text = BeautifulSoup(html_lib.unescape(value or ""), "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def _from_json_ld(soup: BeautifulSoup) -> dict | None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in candidates:
            if not isinstance(item, dict) or item.get("@type") not in ("JobPosting", ["JobPosting"]):
                continue
            org = item.get("hiringOrganization") or {}
            loc = item.get("jobLocation") or {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            addr = (loc.get("address") or {}) if isinstance(loc, dict) else {}
            location = ", ".join(filter(None, [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry") if isinstance(addr.get("addressCountry"), str) else None]))
            salary = ""
            base = item.get("baseSalary") or {}
            if isinstance(base, dict):
                val = base.get("value") or {}
                if isinstance(val, dict) and (val.get("minValue") or val.get("value")):
                    salary = f"{val.get('minValue') or val.get('value')}-{val.get('maxValue') or ''} {base.get('currency') or ''}".strip("- ")
            return {
                "title": _clean_html_text(item.get("title") or ""),
                "company": _clean_html_text(org.get("name") or "" if isinstance(org, dict) else str(org)),
                "location": location,
                "description": _clean_html_text(item.get("description") or ""),
                "datePosted": item.get("datePosted") or "",
                "employmentType": str(item.get("employmentType") or "").lower(),
                "salary": salary,
                "isRemote": bool(item.get("jobLocationType") == "TELECOMMUTE"),
            }
    return None


ATS_ORG_PATTERNS = [
    r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)",
    r"jobs\.lever\.co/([\w-]+)",
    r"jobs\.ashbyhq\.com/([\w-]+)",
    r"([\w-]+)\.breezy\.hr",
    r"apply\.workable\.com/([\w-]+)",
    r"([\w-]+)\.bamboohr\.com",
    r"jobs\.smartrecruiters\.com/([\w-]+)",
]


def _company_from_url(url: str) -> str:
    for pat in ATS_ORG_PATTERNS:
        m = re.search(pat, url, re.I)
        if m:
            return m.group(1).replace("-", " ").title()
    return ""


def _heuristic(soup: BeautifulSoup) -> dict:
    title = ""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"]
    elif soup.title:
        title = soup.title.get_text()
    company = ""
    site_name = soup.find("meta", property="og:site_name")
    if site_name and site_name.get("content"):
        company = site_name["content"]
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    body_text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
    return {
        "title": _clean_html_text(title)[:150],
        "company": _clean_html_text(company)[:100],
        "location": "",
        "description": body_text[:12000],
        "datePosted": "",
        "employmentType": "",
        "salary": "",
        "isRemote": False,
    }


def _needs_llm(parsed: dict) -> bool:
    return not parsed.get("title") or not parsed.get("company") or len(parsed.get("description") or "") < 200


def extract_job(url: str, use_llm: bool) -> tuple[dict | None, str]:
    # The same limited fetcher as Fill from ad: public http(s) hosts only, checked redirects, size and time limits.
    try:
        page = safe_fetch.fetch_page(url)
    except safe_fetch.FetchRefused as exc:
        return None, f"fetch failed: {exc.message}"

    soup = BeautifulSoup(page.html, "html.parser")
    from_ld = _from_json_ld(soup)
    parsed = from_ld or _heuristic(soup)

    if not from_ld:
        # Job-board listing pages (e.g. "Current openings at X") are not postings.
        page_sample = parsed.get("description", "")[:2000].lower()
        if re.search(r"current openings|\d+\s+jobs\b|all open positions", page_sample):
            return None, "this looks like a job listing page — paste the direct posting URL"

    if _needs_llm(parsed) and use_llm:
        page_text = re.sub(r"\s+", " ", BeautifulSoup(page.html, "html.parser").get_text(" "))[:8000]
        with claude_code.ai_gate.context(feature="job-import"):
            llm, err = claude_code.complete_json(EXTRACT_PROMPT.format(text=page_text), timeout=180)
        if llm:
            for key in ("title", "company", "location", "employmentType", "salary", "description"):
                if llm.get(key) and not parsed.get(key):
                    parsed[key] = llm[key]
            if len(llm.get("description") or "") > len(parsed.get("description") or ""):
                parsed["description"] = llm["description"]
            parsed["isRemote"] = bool(llm.get("isRemote", parsed.get("isRemote")))
        else:
            print(f"  llm extraction skipped: {err}", file=sys.stderr)

    if not parsed.get("company"):
        parsed["company"] = _company_from_url(url)

    if not parsed.get("title") and not parsed.get("description"):
        return None, "could not extract a job posting from this page"

    confidence = "high" if from_ld else ("medium" if parsed.get("company") else "low")
    now = datetime.now(timezone.utc).isoformat()
    return {
        "jobId": _job_id(url),
        "importConfidence": confidence,
        "provider": "manual",
        "source": "url-import",
        "title": parsed.get("title") or "Untitled role",
        "company": parsed.get("company") or "",
        "location": parsed.get("location") or "",
        "site": re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0]),
        "jobUrl": url,
        "datePosted": parsed.get("datePosted") or "",
        "salary": parsed.get("salary") or "",
        "employmentType": parsed.get("employmentType") or "",
        "isRemote": bool(parsed.get("isRemote")),
        "searchTerm": "",
        "searchLocation": "",
        "scrapedAt": now,
        "status": "new",
        "description": parsed.get("description") or "",
    }, ""


def _load_doc(path: Path) -> dict:
    if path.exists():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and isinstance(doc.get("jobs"), list):
                return doc
        except json.JSONDecodeError:
            pass
    return {"meta": {}, "jobs": []}


def merge_into_scored(scored_new: list[dict], scored_path: Path, *, keep=("tailoredAssets",), meta_key="lastUrlImportAt") -> None:
    """Merge freshly scored jobs into scored_jobs.json by jobId, touching no other row. `keep` fields of an existing row survive."""
    scored_doc = _load_doc(scored_path)
    scored_by_id = {j.get("jobId"): j for j in scored_doc["jobs"]}
    for job in scored_new:
        existing = scored_by_id.get(job["jobId"]) or {}
        for field in keep:
            if existing.get(field):
                job[field] = existing[field]
        scored_by_id[job["jobId"]] = job
    scored_doc["jobs"] = list(scored_by_id.values())
    scored_doc.setdefault("meta", {})["jobCount"] = len(scored_doc["jobs"])
    scored_doc["meta"][meta_key] = datetime.now(timezone.utc).isoformat()
    scored_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(scored_path, json.dumps(scored_doc, indent=2))


def _read_job_json(source: str):
    """The JSON from a file, or from stdin for "-" (a payload never travels in argv)."""
    return json.loads(sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8"))


def _fail(code: int, **summary) -> int:
    print(json.dumps({"ok": False, **summary}))
    return code


def _ok(**summary) -> int:
    print(json.dumps({"ok": True, **summary}))
    return 0


def _check_only(items, args) -> int:
    """Writes nothing: whether each job's address is already in the discovered, scored or manual files (exit 3 names it)."""
    lists = [_load_doc(args.discovered)["jobs"], _load_doc(args.scored)["jobs"], manual_jobs.load(args.manual)]
    for item in items:
        try:
            job = manual_jobs.sanitize(item, require_description=False)
        except manual_jobs.InvalidJob as exc:
            return _fail(2, error="invalid", field=exc.field)
        clash = manual_jobs.find_clash(job["jobId"], job.get("jobUrl"), *lists)
        if clash:
            return _fail(3, error="duplicate", existing=clash)
    return _ok(checked=len(items))


def delete_manual_job(args) -> int:
    """Remove one hand-entered job from manual_jobs.json and scored_jobs.json. Exit 0 ok, 6 not a hand-entered job.

    Only the row with this id goes; every other row is written back as read. A scored row that is not a hand-entered job
    (no manual flag, not in manual_jobs.json) is refused, so a discovered ad can never be deleted through here.
    The caller has already checked the application store; this only edits the two job files.
    """
    job_id = args.delete_job
    stored = manual_jobs.load(args.manual)
    scored_doc = _load_doc(args.scored)
    in_manual = any(j.get("jobId") == job_id for j in stored)
    scored_rows = [j for j in scored_doc["jobs"] if j.get("jobId") == job_id]
    if not in_manual and any(not (j.get("manualEntry") or j.get("provider") == "manual") for j in scored_rows):
        return _fail(6, error="not_manual")
    # Remembered by id, so a stale browser tab that syncs or scores it again stores nothing.
    manual_jobs.save(manual_jobs.remove(stored, job_id), args.manual, deleted=manual_jobs.load_deleted(args.manual) | {job_id})
    if scored_rows:
        scored_doc["jobs"] = [j for j in scored_doc["jobs"] if j.get("jobId") != job_id]
        scored_doc.setdefault("meta", {})["jobCount"] = len(scored_doc["jobs"])
        write_text_atomic(args.scored, json.dumps(scored_doc, indent=2))
    return _ok(removed={"manual": int(in_manual), "scored": len(scored_rows)})


def run_job_json(args) -> int:
    """Store, score and merge hand-entered jobs. Exit 0 ok, 2 invalid, 3 duplicate URL, 4 no intelligence, 5 scoring failed, 7 deleted job.

    Nothing printed or logged carries a field value except through the scored record itself: errors name a field only.
    """
    try:
        payload = _read_job_json(args.job_json)
    except (OSError, ValueError):
        return _fail(2, error="invalid", field="json")
    batch = isinstance(payload, list)
    items = payload if batch else [payload]
    if args.discovered.exists():
        view_guard.ensure_or_exit(args.discovered, view_guard.job_history.ledger_path(args.discovered))
    if args.check_only:
        return _check_only(items, args)

    discovered_jobs = _load_doc(args.discovered)["jobs"]
    scored_jobs = _load_doc(args.scored)["jobs"]
    stored = manual_jobs.load(args.manual)

    deleted = manual_jobs.load_deleted(args.manual)
    accepted, skipped = [], []
    for item in items:
        try:
            job = manual_jobs.sanitize(item)
        except manual_jobs.InvalidJob as exc:
            if not batch:
                return _fail(2, error="invalid", field=exc.field)
            skipped.append({"error": "invalid", "field": exc.field})
            continue
        if job["jobId"] in deleted:
            if not batch:
                return _fail(7, error="deleted")
            skipped.append({"jobId": job["jobId"], "error": "deleted"})
            continue
        clash = manual_jobs.find_clash(job["jobId"], job.get("jobUrl"), discovered_jobs, scored_jobs, stored, accepted)
        if clash:
            if not batch:
                return _fail(3, error="duplicate", existing=clash)
            skipped.append({"jobId": job["jobId"], "error": "duplicate", "existing": clash})
            continue
        accepted.append(job)

    if not accepted:
        return _fail(2, error="invalid", skipped=skipped) if skipped else _fail(2, error="invalid", field="job")

    # Saved before scoring: a scoring failure leaves the job where every later run, and a retry, finds it.
    stored = manual_jobs.upsert(accepted, stored)
    manual_jobs.save(stored, args.manual)
    ids = {j["jobId"] for j in accepted}
    for job_id in sorted(ids):
        print(f"manual job stored: {job_id}", file=sys.stderr)

    if args.store_only:
        return _ok(stored=sorted(ids), skipped=skipped)

    try:
        if not args.intelligence.exists():
            return _fail(4, error="no_intelligence", saved=sorted(ids))
        intelligence = json.loads(args.intelligence.read_text(encoding="utf-8"))
        # The corpus a full run scores (term rarity is measured over it), so the row equals the one Re-score writes.
        corpus = manual_jobs.with_manual(discovered_jobs, stored)
        scored = [j for j in score_jobs([dict(j) for j in corpus], intelligence) if j.get("jobId") in ids]
        for job in scored:
            manual_jobs.mark_missing_facts(job)
        merge_into_scored(scored, args.scored, keep=("tailoredAssets", "status"), meta_key="lastManualJobAt")
    except Exception as exc:  # the message may quote job text; only the class is reported
        return _fail(5, error="scoring_failed", detail=type(exc).__name__, saved=sorted(ids))

    return _ok(jobs=scored, skipped=skipped)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import jobs from URLs, or score hand-entered jobs.")
    parser.add_argument("--url", action="append", default=[], help="Job posting URL (repeatable)")
    parser.add_argument("--no-llm", action="store_true", help="Skip Claude Code extraction fallback")
    parser.add_argument("--job-json", metavar="FILE|-", help="Hand-entered job(s) as JSON, from a file or stdin; nothing is fetched")
    parser.add_argument("--check-only", action="store_true",
                        help="with --job-json: only report whether the address is already in your jobs; nothing is written")
    parser.add_argument("--store-only", action="store_true",
                        help="with --job-json: store the jobs in manual_jobs.json and stop; the next scoring run scores them")
    parser.add_argument("--delete-job", metavar="JOB_ID",
                        help="remove this hand-entered job from manual_jobs.json and scored_jobs.json (the caller checks the tracker)")
    parser.add_argument("--discovered", type=Path, default=DISCOVERED_PATH)
    parser.add_argument("--scored", type=Path, default=SCORED_PATH)
    parser.add_argument("--manual", type=Path, default=manual_jobs.MANUAL_PATH)
    parser.add_argument("--intelligence", type=Path, default=INTELLIGENCE_PATH)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.job_json and args.check_only:  # writes nothing, so it can answer during a run
        return run_job_json(args)
    # These replace scored_jobs.json from a copy read earlier, and a run replaces it whole: one must wait for the other.
    # A hand-entered job stays saved in the browser, unscored, with its "Score now" retry (DECISIONS.md, Activity slice 2a).
    lock = pipeline_lock.acquire()
    if lock is None:
        print(pipeline_lock.BUSY_MESSAGE, file=sys.stderr)
        return pipeline_lock.EXIT_LOCKED
    try:
        if args.delete_job:
            return delete_manual_job(args)
        return import_locked(args)
    finally:
        lock.release()


def import_locked(args) -> int:
    # Decided before anything that could reach the network or a model is looked at.
    if args.job_json:
        return run_job_json(args)

    urls = [u.strip() for u in args.url if u.strip()]
    if not urls:
        print("No URLs given (use --url or --job-json)", file=sys.stderr)
        return 1

    use_llm = not args.no_llm and claude_code.is_available()
    imported, errors = [], []
    for url in urls:
        print(f"Importing {url} ...", file=sys.stderr)
        job, err = extract_job(url, use_llm)
        if job is None:
            errors.append({"url": url, "error": err})
            continue
        # The same address as a hand-entered job is that job, not a second one.
        clash = manual_jobs.find_clash(
            job["jobId"], job.get("jobUrl"), _load_doc(args.discovered)["jobs"], _load_doc(args.scored)["jobs"], manual_jobs.load(args.manual)
        )
        if clash:
            errors.append({"url": url, "error": f"already in your jobs: {clash['title'] or clash['jobId']}"})
        else:
            imported.append(job)

    if imported:
        # Append to discovered jobs (dedupe by jobId, re-import refreshes the entry)
        discovered = _load_doc(args.discovered)
        by_id = {j.get("jobId"): j for j in discovered["jobs"]}
        for job in imported:
            by_id[job["jobId"]] = {**by_id.get(job["jobId"], {}), **job}
        discovered["jobs"] = list(by_id.values())
        discovered.setdefault("meta", {})["lastUrlImportAt"] = datetime.now(timezone.utc).isoformat()
        args.discovered.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(args.discovered, json.dumps(discovered, indent=2))

        # Score only the new jobs and merge into scored_jobs.json (preserves tailoredAssets)
        if args.intelligence.exists():
            intelligence = json.loads(args.intelligence.read_text(encoding="utf-8"))
            merge_into_scored(score_jobs([dict(j) for j in imported], intelligence), args.scored)
        else:
            print("No candidate intelligence; imported without scoring", file=sys.stderr)

    print(json.dumps({
        "imported": [{"jobId": j["jobId"], "title": j["title"], "company": j["company"]} for j in imported],
        "errors": errors,
    }))
    return 0 if imported else 1


if __name__ == "__main__":
    raise SystemExit(main())
