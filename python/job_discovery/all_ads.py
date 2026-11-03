#!/usr/bin/env python3
"""What GET /api/jobs/all serves: every ad known, one slim row each, with a class and a reason (slice S5e2).

    all_ads.py --root ROOT    prints the answer as JSON; exit 0, or 3 with {"ok": false, "message"} when the ledger cannot be read

It reads job_history.json and filtered_ads.json and writes nothing. Stdlib only and no job module, so the route starts it fast.
It never reads discovered_jobs.json: a class comes only from what the ledger entry itself says, so regenerating the view or
enrichment rewriting it cannot change one. No time is compared to decide a class (`lastImport.at`, `meta.generatedAt`, `lastSeen`).

The classes, first match wins (`classify`):

    found         lastRunId == lastImport.runId                 the last import found it
    closed        closedAt                                      its own mark
    stale         staleSince                                    its own mark; nothing writes it until S5f
    absent        absentSince                                   its own mark: a board proven complete did not list it
    held          heldRunId == lastImport.runId                 its source or board could say nothing in the last import
    older_key     seenUnder differs from the current search     out of the search that ran
    unclassified  its source was not part of the last import    nothing searched for it, so its absence says nothing
    absent        seenUnder equals the current search           the search ran and did not return it
    unclassified  any mark needed above is missing              never a guess

The current search is the `seenUnder` of the rows the last import found: `apply_run` writes the run's key on each of them, so no new
ledger field is needed and a ledger from before works. `lastImport.marksNotFound` is not read: `heldRunId` is older than that flag.

Documented fallback, `unclassified`: with no `lastImport.runId`, or when the last import found no row (or rows under two keys), or an
entry with no `seenUnder`, nothing can tell held, absent and older_key apart. Such a row says so instead of getting a status it may
not have. A class proven by the entry's own mark (closed, stale, absent) still holds.

The search key does not hold the list of sources, so a source turned off leaves its rows under the current key. `absent` therefore
also needs the row's source in `lastImport.meta.providers`. A source that failed or was skipped is in that list and its rows are held,
which comes first. With no such list nothing can say the source ran, so the row is unclassified too. older_key needs no list: its
key alone shows the search that found it is not the one that ran.

Filtered ads come from filtered_ads.json. An ad the ledger holds shows once, from the ledger, whatever its `inLedger` mark says. One
with no title or no web address is left out and only counted: it stays in the file as a diagnostic. An ad dropped because its
full text was not read (`INCOMPLETE`) is `filtered_incomplete`.

No row has a score: `matchScore` is always null, and S5e3 shows "Not scored" unless the browser's stored row has one.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

CLASSES = ("found", "held", "absent", "closed", "older_key", "stale", "filtered", "filtered_incomplete", "unclassified")
INCOMPLETE = {"detail_cap", "no_detail_text"}
EXIT_UNREADABLE = 3
_URL = re.compile(r"^https?://[^\s/]+\S*$")
FILTER_REASONS = {
    "title_not_matched": "Title didn't match",
    "search_terms_not_matched": "Search terms didn't match",
    "location_not_matched": "Location didn't match",
    "country_not_matched": "Country didn't match",
    "not_listed": "Not listed on the company's board",
    "no_detail_text": "Full ad text could not be read",
    "detail_cap": "Full ad text not read: over the limit for one run",
}


class LedgerUnreadable(Exception):
    pass


def current_key(ledger: dict) -> str | None:
    """The search of the last import: the one key on the rows it found. None when that cannot be said."""
    run_id = (ledger.get("lastImport") or {}).get("runId")
    if not run_id:
        return None
    keys = {entry.get("seenUnder") for entry in ledger["jobs"].values() if isinstance(entry, dict) and entry.get("lastRunId") == run_id}
    if len(keys) != 1:
        return None
    return next(iter(keys)) or None


def run_providers(ledger: dict) -> set | None:
    """The sources of the last import, or None when the ledger does not say."""
    providers = ((ledger.get("lastImport") or {}).get("meta") or {}).get("providers")
    return set(providers) if isinstance(providers, list) else None


def _source_left_out(entry: dict, providers: set | None) -> bool:
    """The last import says which sources it had, and this row's is not one of them."""
    return providers is not None and entry.get("provider") not in providers


def classify(entry: dict, run_id: str | None, key: str | None, providers: set | None) -> str:
    """Exactly one class for a ledger entry. Pure: only the entry, the last import's id, its search and its sources."""
    if run_id and entry.get("lastRunId") == run_id:
        return "found"
    if entry.get("closedAt"):
        return "closed"
    if entry.get("staleSince"):
        return "stale"
    if entry.get("absentSince"):
        return "absent"
    if not run_id:
        return "unclassified"
    if entry.get("heldRunId") == run_id:
        return "held"
    seen_under = entry.get("seenUnder")
    if not seen_under or not key:
        return "unclassified"
    if seen_under != key:
        return "older_key"
    if providers is None or _source_left_out(entry, providers):
        return "unclassified"
    return "absent"


def classify_filtered(record: dict) -> str | None:
    """`filtered`, `filtered_incomplete`, or None for a record with no title or no web address, which is not shown."""
    title, url = record.get("title"), record.get("url")
    if not (isinstance(title, str) and title.strip() and isinstance(url, str) and _URL.match(url.strip())):
        return None
    return "filtered_incomplete" if record.get("reason") in INCOMPLETE else "filtered"


def _day(value) -> str:
    return str(value)[:10] if value else "unknown"


def ledger_reason(kind: str, entry: dict, listed_elsewhere: bool = False, source_left_out: bool = False) -> str:
    seen = _day(entry.get("lastSeen"))
    if kind == "found":
        return "Found by the latest run"
    if kind == "closed":
        checks = entry.get("absentRuns") or 0
        day = _day(entry.get("closedAt"))
        return f"Not on the company's board in {checks} complete checks, closed {day}" if checks >= 2 else f"No longer listed since {day}"
    if kind == "stale":
        return f"Not seen for a long time. Last seen {seen}"
    if kind == "held":
        return f"Its source or board could not say in the latest run. Last seen {seen}"
    if kind == "older_key":
        return f"From an earlier search; the search settings have changed. Last seen {seen}"
    if kind == "absent":
        if entry.get("absentSince"):
            return f"Not on the company's board in a complete check on {_day(entry['absentSince'])}. Last seen {seen}"
        if listed_elsewhere:
            return f"Still listed under another copy of this ad. Last seen {seen}"
        return f"Not returned by the latest search. Last seen {seen}"
    if source_left_out:
        return "Its source was not part of the latest run"
    return f"Not enough information to say. Last seen {seen}"


def filtered_reason(kind: str, code) -> str:
    code = str(code or "unknown")
    if code.startswith("title_excluded:"):
        text = f"Excluded title: {code.split(':', 1)[1]}"
    else:
        text = FILTER_REASONS.get(code, code)
    return f"Incomplete: {text}" if kind == "filtered_incomplete" else f"Filtered out: {text}"


def _row(job_id, kind, reason, reason_code, origin, title, company, location, url, provider, site, is_remote, posted, first, last, closed, absent) -> dict:
    return {
        "jobId": job_id, "title": title, "company": company, "location": location, "jobUrl": url, "provider": provider, "site": site,
        "isRemote": is_remote, "datePosted": posted, "firstSeen": first, "lastSeen": last, "closedAt": closed, "absentSince": absent,
        "class": kind, "reason": reason, "reasonCode": reason_code, "from": origin, "matchScore": None,
    }


def build(ledger: dict | None, store: dict | None, filtered_state: str = "ok") -> dict:
    """The answer, from a ledger and a filtered store (None: none). A whitelist of fields, so no description can be in it. Pure."""
    ledger = ledger if ledger is not None else {"jobs": {}}
    run_id = (ledger.get("lastImport") or {}).get("runId") or None
    key = current_key(ledger)
    providers = run_providers(ledger)
    counts = {name: 0 for name in CLASSES}
    rows = []
    no_ad = elsewhere = left_out = 0
    found_roles = {e.get("roleKey") for e in ledger["jobs"].values() if isinstance(e, dict) and run_id and e.get("lastRunId") == run_id and e.get("roleKey")}
    for job_id, entry in ledger["jobs"].items():
        job = entry.get("job") if isinstance(entry, dict) else None
        if not isinstance(job, dict):
            no_ad += 1
            continue
        kind = classify(entry, run_id, key, providers)
        counts[kind] += 1
        listed_elsewhere = kind == "absent" and not entry.get("absentSince") and entry.get("roleKey") in found_roles
        elsewhere += listed_elsewhere
        source_left_out = kind == "unclassified" and _source_left_out(entry, providers)
        left_out += source_left_out
        rows.append(_row(job_id, kind, ledger_reason(kind, entry, listed_elsewhere, source_left_out), None, "ledger", job.get("title"), job.get("company"), job.get("location"), job.get("jobUrl"),
                         entry.get("provider") or job.get("provider"), job.get("site"), job.get("isRemote"), job.get("datePosted"),
                         entry.get("firstSeen"), entry.get("lastSeen"), entry.get("closedAt"), entry.get("absentSince")))
    also_in_ledger = not_shown = 0
    for job_id, record in ((store or {}).get("ads") or {}).items():
        if job_id in ledger["jobs"]:
            also_in_ledger += 1
            continue
        kind = classify_filtered(record)
        if kind is None:
            not_shown += 1
            continue
        counts[kind] += 1
        code = record.get("reason")
        rows.append(_row(job_id, kind, filtered_reason(kind, code), code, "filtered", record["title"].strip(), record.get("company"), record.get("location"), record["url"].strip(),
                         record.get("source"), None, None, None, record.get("firstSeen"), record.get("lastSeen"), None, None))
    return {
        "ok": True,
        "meta": {
            "ledgerGeneration": ledger.get("generation"), "lastImportRunId": run_id, "currentSearchKey": key, "filteredFile": filtered_state,
            "counts": counts, "total": len(rows),
            "diagnostics": {"ledgerEntriesWithoutAd": no_ad, "absentListedElsewhere": elsewhere, "sourceNotInLatestRun": left_out, "filteredAlsoInLedger": also_in_ledger, "filteredWithoutTitleOrUrl": not_shown},
        },
        "rows": rows,
    }


def read_ledger(path: Path) -> dict | None:
    """None when there is no file: an empty state. Raises LedgerUnreadable when it is there and cannot be used."""
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise LedgerUnreadable(f"The job history {path.name} cannot be read ({type(exc).__name__}), so the list of all ads was not made.") from exc
    if not isinstance(ledger, dict) or not isinstance(ledger.get("jobs"), dict):
        raise LedgerUnreadable(f"The job history {path.name} holds no job list, so the list of all ads was not made.")
    return ledger


def read_filtered(path: Path) -> tuple[dict | None, str]:
    """The store and what happened: `ok`, `missing` (no backfill or import yet) or `unreadable`. The ledger's rows do not depend on it."""
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError):
        return None, "unreadable"
    if not isinstance(store, dict) or store.get("version") != 1 or not isinstance(store.get("ads"), dict):
        return None, "unreadable"
    return store, "ok"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    jobs = args.root / "data" / "jobs"
    try:
        ledger = read_ledger(jobs / "job_history.json")
    except LedgerUnreadable as exc:
        print(json.dumps({"ok": False, "message": str(exc)}))
        return EXIT_UNREADABLE
    store, state = read_filtered(jobs / "filtered_ads.json")
    print(json.dumps(build(ledger, store, state)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
