#!/usr/bin/env python3
"""Manual Re-score of one kept ad (Wave 2 e). User-triggered; no model call, no network.

Registers the id (kept_ads), scores the ad from the job history ledger with the same score_jobs() a full run uses
(over the list, the hand-entered jobs and the other registered ads), and merges that one row into scored_jobs.json,
keeping its tailoredAssets. Prints one JSON line. Exit: 0 done, 2 bad id, 4 ad not in the ledger or no intelligence,
75 a run is active.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
for extra in (SCRIPT_DIR, ROOT / "python" / "job_import"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
# match_engine (imported by role_class) lives under python/. The route starts this file by path, so nothing else puts it on sys.path.
if str(ROOT / "python") not in sys.path:
    sys.path.append(str(ROOT / "python"))

import job_history  # noqa: E402
import kept_ads  # noqa: E402
import manual_jobs  # noqa: E402
import employer_refresh  # noqa: E402
import pasted_descriptions  # noqa: E402
import pipeline_lock  # noqa: E402
import ceilings  # noqa: E402
import role_class  # noqa: E402
from scorer import score_jobs  # noqa: E402


def run(job_id: str, *, intelligence: Path, jobs: Path, manual: Path, scored: Path, kept: Path,
        pasted: Path = pasted_descriptions.PASTED_PATH, paste_text: str | None = None,
        employer: Path | None = None) -> tuple[int, dict]:
    """`paste_text` (package 12): the owner's pasted ad text for this ad. It is stored, the ad is scored with it, and the id is
    NOT registered as kept (a paste is not a Keep). Exit 2 for a text the server will not take."""
    if not kept_ads.JOB_ID.match(job_id or ""):
        return 2, {"ok": False, "error": "invalid", "field": "jobId"}
    source = None
    if employer is not None:  # package 13: accept the proposal stored from the employer's page (the text never comes from the browser)
        paste_text, source = employer_refresh.proposal_text(job_id, employer), "employer"
        if paste_text is None:
            return 4, {"ok": False, "error": "no_proposal"}
    if paste_text is not None:
        try:
            pasted_descriptions.clean(paste_text)
        except pasted_descriptions.InvalidPaste as exc:
            return 2, {"ok": False, "error": "invalid", "field": exc.field}
    if not intelligence.exists():
        return 4, {"ok": False, "error": "no_intelligence"}
    ledger = job_history.load(job_history.ledger_path(jobs), read_only=True)
    if kept_ads.ledger_row(ledger, job_id) is None:
        return 4, {"ok": False, "error": "not_in_history"}
    lock = pipeline_lock.acquire()
    if lock is None:
        return 75, {"ok": False, "error": "run_active"}
    try:
        import import_job_url  # noqa: PLC0415

        before = pasted_descriptions.load(pasted).get(job_id)
        if paste_text is not None:
            pasted_descriptions.put(job_id, paste_text, pasted, source=source)
        else:
            kept_ads.add(job_id, kept)
        discovered = json.loads(jobs.read_text(encoding="utf-8")) if jobs.exists() else {"jobs": []}
        rows = discovered.get("jobs") if isinstance(discovered, dict) else discovered
        rows = manual_jobs.with_manual(list(rows or []), manual_jobs.load(manual))
        rows = kept_ads.with_kept(rows, job_history.ledger_path(jobs), kept)
        pasted_descriptions.apply(rows, pasted)
        import run_scoring  # noqa: PLC0415

        # The one Re-score path: cached judgements re-applied, a model call raises (run_scoring.local_enhancer).
        role_class.label(rows)  # before scoring (1.7)
        scored_rows = score_jobs(rows, json.loads(intelligence.read_text(encoding="utf-8")), run_scoring.local_enhancer(run_scoring.identity_of(run_scoring._load_profile())))
        row = next((r for r in scored_rows if r.get("jobId") == job_id), None)
        if row is None:
            if paste_text is not None:  # nothing was scored with it: put the earlier text back
                pasted_descriptions.restore(job_id, before, pasted)  # the exact earlier entry, history included
            return 4, {"ok": False, "error": "not_in_history"}
        role_class.ceiling([row])
        ceilings.stamp_engine_coverage([row], False)
        import_job_url.merge_into_scored([row], scored, meta_key="lastKeptRescoreAt")
        if employer is not None:
            employer_refresh.discard(job_id, employer)  # accepted: the proposal is now the overlay
        return 0, {"ok": True, "job": row}
    finally:
        lock.release()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Re-score one kept ad.")
    p.add_argument("--job-id", default="")
    p.add_argument("--intelligence", type=Path, default=ROOT / "data/intelligence/candidate-intelligence.json")
    p.add_argument("--jobs", type=Path, default=ROOT / "data/jobs/discovered_jobs.json")
    p.add_argument("--manual", type=Path, default=manual_jobs.MANUAL_PATH)
    p.add_argument("--scored", type=Path, default=ROOT / "data/jobs/scored_jobs.json")
    p.add_argument("--kept", type=Path, default=kept_ads.KEPT_PATH)
    p.add_argument("--pasted", type=Path, default=pasted_descriptions.PASTED_PATH)
    p.add_argument("--employer-proposals", type=Path, default=employer_refresh.PROPOSALS_PATH)
    p.add_argument("--accept-employer", action="store_true",
                   help="use the proposal stored for --job-id from the employer's page as its text (package 13); not kept")
    p.add_argument("--paste-stdin", action="store_true",
                   help="the pasted ad text for --job-id comes on stdin (never argv); it is stored and the ad re-scored with it, not kept")
    p.add_argument("--prune", metavar="ID,ID", default=None,
                   help="instead of scoring: drop every registered id not in this list (the kept ads and the ads with an application)")
    p.add_argument("--register", action="store_true",
                   help="with --prune: first register every id of the list that the ledger holds (the owner's ads: kept, with an application), so no run drops their rows")
    args = p.parse_args(argv)
    if args.prune is not None:
        keep = {i for i in args.prune.split(",") if i}
        registered = kept_ads.register_owner_ads(keep, job_history.ledger_path(args.jobs), args.kept) if args.register else None
        print(json.dumps({"ok": True, "dropped": kept_ads.prune(keep, args.kept), **({"registered": registered} if registered else {})}))
        return 0
    code, body = run(args.job_id, intelligence=args.intelligence, jobs=args.jobs, manual=args.manual, scored=args.scored, kept=args.kept,
                     pasted=args.pasted, paste_text=sys.stdin.read() if args.paste_stdin else None,
                     employer=args.employer_proposals if args.accept_employer else None)
    print(json.dumps(body))
    return code


if __name__ == "__main__":
    sys.exit(main())
