#!/usr/bin/env python3
"""Package 14 measurement: how many LinkedIn detail requests (one `GET /jobs/view/<id>` per search card, jobspy 1.4.0) a deferred
fetch could skip, on the filters as they are after packages 3 and 4 (method of FREE_MEASUREMENTS section 3, counts only).

The unit is the unique ad seen in the latest scan day (the ledger and `filtered_ads.json` hold one row per ad; the staged run counted
one read per search card, so a card returned by two searches was read, and fetched, twice).
A request is avoidable only when the decision needs nothing from the detail page:
  - a known ad that the ledger holds with a full description (not thin, not due for a retry): nothing to learn from the page;
  - an ad whose title holds an `exclude` phrase: a hard drop on the title alone.
A title that misses the lists is NOT avoidable: since package 3 it goes to a free-text check on the description, and an empty text
never drops it, so the page is needed to decide.

No model call, no network, no write: real data is read-only. Output: counts only.
Usage: .venv/bin/python scripts/measure_package14.py [--day YYYY-MM-DD] [--thin N]
Pattern: scripts/measure_package3.py.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_package3 as m3  # noqa: E402  (sets HOLOJOB_AI_DIR and the import paths)

rf = m3.rf


def day(value) -> str:
    return str(value or "")[:10]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--day", help="scan day to replay (default: the latest lastSeen of a jobspy ad)")
    parser.add_argument("--thin", type=int, default=200, help="description length below which an ad counts as thin")
    args = parser.parse_args()

    ledger = m3._read("jobs/job_history.json").get("jobs") or {}
    filtered = m3._read("jobs/filtered_ads.json").get("ads") or {}
    jobspy_ledger = {k: v for k, v in ledger.items() if v.get("provider") == "jobspy"}
    jobspy_filtered = {k: v for k, v in filtered.items() if v.get("source") == "jobspy"}
    scan = args.day or max(day(v.get("lastSeen")) for v in jobspy_ledger.values())
    terms = m3.search_terms()
    print(f"scan day {scan}; thin = description under {args.thin} chars")

    rows = []  # (id, known, has_full_text, title)
    for job_id, entry in jobspy_ledger.items():
        if day(entry.get("lastSeen")) != scan:
            continue
        job = entry.get("job") or {}
        text = (job.get("description") or "").strip()
        rows.append((job_id, day(entry.get("firstSeen")) < scan, len(text) >= args.thin, job.get("title") or "", "ledger"))
    for ad_id, ad in jobspy_filtered.items():
        if day(ad.get("lastSeen")) != scan or ad_id in jobspy_ledger:
            continue
        # A dropped ad keeps no description (a drop never pins dedup): its page would be fetched again.
        rows.append((ad_id, day(ad.get("firstSeen")) < scan, False, ad.get("title") or "", "filtered"))

    total = len(rows)
    new = [r for r in rows if not r[1]]
    known = [r for r in rows if r[1]]
    known_full = [r for r in known if r[2]]
    known_dropped = [r for r in known if r[4] == "filtered"]
    known_thin = [r for r in known if r[4] == "ledger" and not r[2]]
    excluded = [r for r in rows if rf._title_decision(r[3], "", terms, None).reason
                and rf._title_decision(r[3], "", terms, None).reason.startswith("title_excluded")]
    excluded_only = [r for r in excluded if not (r[1] and r[2])]  # not already counted as a known ad with full text
    avoidable = len(known_full) + len(excluded_only)

    print(f"unique jobspy ads seen: {total} (ledger {sum(1 for r in rows if r[4] == 'ledger')}, filtered only {sum(1 for r in rows if r[4] == 'filtered')})")
    print(f"  new to the ledger and the filtered list: {len(new)}")
    print(f"  known: {len(known)} = with full text in the ledger {len(known_full)}, thin in the ledger {len(known_thin)}, "
          f"dropped earlier (no text kept) {len(known_dropped)}")
    print(f"  hard title drop (exclude phrase) now: {len(excluded)}, of them not already known-with-text {len(excluded_only)}")
    print(f"avoidable requests (unique ads): {avoidable} of {total} = {100 * avoidable / total:.0f}%")
    print(f"  known with full text alone: {len(known_full)} = {100 * len(known_full) / total:.0f}%")
    print(f"  title filter alone: {len(excluded_only)} = {100 * len(excluded_only) / total:.1f}%")
    print("by source of the ad: ", dict(Counter(r[4] for r in rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
