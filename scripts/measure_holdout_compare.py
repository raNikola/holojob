#!/usr/bin/env python3
"""Holdout comparison v1: the owner's 20 ratings against the system's Re-score. Read-only, no model call.

    .venv/bin/python scripts/measure_holdout_compare.py --data-dir /home/ranikola/holojob-eval/holdout-scratch-data

Steps (the method of the stopped run, unchanged):
  1. Fact coverage: each holdout ad is read / stale / absent for its exact text. More than --max-not-read (5) not_read stops the run
     before any metric is computed.
  2. A Re-score of --data-dir (measure_common.rescore: run_scoring.score with the model call stubbed out, output in a temp dir). Ads the
     job list does not hold are scored from the ledger like a kept ad.
  3. The criterion in the ratings file's "Success criterion" section, applied as written; counts out of 20; Kendall tau-b, informational.
  4. The report, mode 600.

The criterion is read from the ratings file at run time; its status line is printed as found (if it still says "PROPOSAL, not yet
approved", the report says so). Nothing under --data-dir or the real data dir is written. "Professional Fit" is taken as the row's
final matchScore (after caps); the dimension score before any cap is shown beside it, informational.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_common as mc  # noqa: E402

RATINGS = mc.EVAL_DIR / "holdout-ratings-v1-2026-11-17.md"
IDS = mc.EVAL_DIR / "holdout-ids.json"
REPORT = mc.EVAL_DIR / "holdout-comparison-v1.md"
ELIGIBLE = {"authorized", "sponsored"}
VERDICT_ORDER = {"apply": 3, "maybe": 2, "skip": 1}
TOP_N = 6


# --- the ratings file ---------------------------------------------------------------------------------------------

def parse_ratings(text: str) -> tuple[list[dict], dict]:
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 6 and cells[0].isdigit() and re.fullmatch(r"[0-9a-f]{16}", cells[2]):
            rows.append({"rank": int(cells[0]), "verdict": cells[1], "id": cells[2], "name": cells[3], "driver": cells[4], "reason": cells[5]})
    section = re.search(r"^## Success criterion\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    body = section.group(1).strip() if section else ""
    status = next((l.strip() for l in body.splitlines() if l.strip()), "")
    items = {int(m.group(1)): m.group(2).strip() for m in re.finditer(r"^(\d+)\.\s+(.*?)(?=^\d+\.\s|\Z)", body, re.S | re.M)}
    return rows, {"text": body, "status": status, "items": items}


def fit_skip_ids(criterion2: str, rows: list[dict]) -> list[str]:
    """The skip ads criterion 2 names in its parentheses, matched on the first word of the company among the skip rows."""
    names = re.search(r"\(([^)]*)\)", criterion2)
    if not names:
        raise ValueError("criterion 2 names no ads in parentheses")
    out = []
    for token in (t.strip() for t in names.group(1).split(",")):
        first = token.split()[0].lower()
        hits = [r["id"] for r in rows if r["verdict"] == "skip" and r["name"].lower().startswith(first)]
        if len(hits) != 1:
            raise ValueError(f"criterion 2 name {token!r} matches {len(hits)} skip rows")
        out.append(hits[0])
    return out


def elig_barriers(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(stated, unconfirmed) among the ELIG-tagged rows, from the rater's own reason text."""
    stated, unconfirmed = [], []
    for r in rows:
        if "ELIG" not in r["driver"]:
            continue
        reason = r["reason"].lower()
        if re.search(r"likely|uncertain|unclear|only if|feasible", reason):
            unconfirmed.append(r)
        elif re.search(r"excluded|unavailable|mandatory|clearance|on-site|refused|required", reason):
            stated.append(r)
    return stated, unconfirmed


# --- step 1 and 2 -------------------------------------------------------------------------------------------------

def read_state(row: dict) -> str:
    from job_fingerprint import job_fingerprint
    facts = row.get("llmFacts")
    if not facts:
        return "absent"
    return "read" if facts.get("_fingerprint") == job_fingerprint(row) else "stale"


def coverage(data_dir: Path, ids: list[str]) -> dict:
    """read / stale / absent per id, from the scratch data dir's own stored rows. No scoring."""
    import job_history
    doc = json.loads((data_dir / "jobs" / "discovered_jobs.json").read_text(encoding="utf-8"))
    view = {j.get("jobId"): j for j in (doc.get("jobs") if isinstance(doc, dict) else doc) or []}
    ledger = job_history.load(job_history.ledger_path(data_dir / "jobs" / "discovered_jobs.json"), read_only=True)
    out = {}
    for i in ids:
        if i in view:
            out[i] = read_state(view[i])
            continue
        entry = (ledger.get("jobs") or {}).get(i) or {}
        job = entry.get("job")
        out[i] = "missing" if not isinstance(job, dict) else read_state({**job, "jobId": i})
    return out


def score_rows(data_dir: Path, ids: list[str]) -> dict:
    doc = mc.rescore(data_dir)
    rows = {j["jobId"]: j for j in doc["jobs"]}
    missing = [i for i in ids if i not in rows]
    if missing:
        for j in mc.rescore(data_dir, extra_ids=set(missing))["jobs"]:
            if j["jobId"] in missing:
                rows[j["jobId"]] = j
    return {"scoringVersion": doc["meta"].get("scoringVersion"), "rows": {i: rows.get(i) for i in ids}}


def summarize(row: dict | None) -> dict | None:
    if row is None:
        return None
    fired, binding = mc.caps_of(row)
    bd = row.get("scoreBreakdown") or {}
    weight = sum(v["weight"] for v in bd.values()) or 100
    auth = mc.auth_of(row)
    return {"title": None if row.get("manualEntry") else row.get("title"), "score": row.get("matchScore"),
            "uncapped": round(sum(v["raw"] * v["weight"] for v in bd.values()) / weight) if bd else None,
            "band": mc.band_of(row), "fired": sorted(fired), "binding": sorted(binding),
            "authStatus": auth.get("status"), "authBasis": auth.get("basis")}


# --- step 3: the metrics ------------------------------------------------------------------------------------------

def position(scores: dict, i: str) -> tuple[int, int]:
    """(best, worst) 1-based position of ad i by score, ties both ways: best counts ties as behind it, worst as ahead."""
    s = scores[i]
    higher = sum(1 for j, v in scores.items() if v > s)
    tied = sum(1 for j, v in scores.items() if v == s and j != i)
    return higher + 1, higher + 1 + tied


def kendall_tau_b(xs: list, ys: list) -> float | None:
    conc = disc = tx = ty = 0
    for a in range(len(xs)):
        for b in range(a + 1, len(xs)):
            dx, dy = xs[a] - xs[b], ys[a] - ys[b]
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                tx += 1
            elif dy == 0:
                ty += 1
            elif (dx > 0) == (dy > 0):
                conc += 1
            else:
                disc += 1
    denom = ((conc + disc + tx) * (conc + disc + ty)) ** 0.5
    return round((conc - disc) / denom, 3) if denom else None


def metrics(ratings: list[dict], criterion: dict, summ: dict) -> dict:
    scores = {r["id"]: (summ[r["id"]]["score"] if summ[r["id"]] else None) for r in ratings}
    if any(v is None for v in scores.values()):
        raise ValueError("a holdout ad has no score")
    n = len(ratings)
    applies = [r for r in ratings if r["verdict"] == "apply"]
    pos = {r["id"]: position(scores, r["id"]) for r in applies}
    c1_strict = [i for i, (b, w) in pos.items() if w <= TOP_N]
    c1_best = [i for i, (b, w) in pos.items() if b <= TOP_N]
    fit_ids = fit_skip_ids(criterion["items"][2], ratings)
    min_apply = min(scores[r["id"]] for r in applies)
    above = [i for i in fit_ids if scores[i] > min_apply]
    tied = [i for i in fit_ids if scores[i] == min_apply]
    c2_pairs_above = [(f, r["id"]) for f in fit_ids for r in applies if scores[f] > scores[r["id"]]]
    stated, unconfirmed = elig_barriers(ratings)
    shown_ok = [r["id"] for r in stated if summ[r["id"]]["authStatus"] in ELIGIBLE]
    # Language barrier is a cap of its own, so a language-required ad is not "shown eligible" if the language cap fired.
    lang_ok = [r["id"] for r in stated if "language" in r["reason"].lower() and "language" not in summ[r["id"]]["fired"]]
    c3_violations = sorted(set(shown_ok) | set(lang_ok))
    tau = kendall_tau_b([scores[r["id"]] for r in ratings], [VERDICT_ORDER[r["verdict"]] for r in ratings])
    return {"n": n, "applyIds": [r["id"] for r in applies], "applyPositions": pos, "c1Strict": c1_strict, "c1Optimistic": c1_best,
            "fitSkipIds": fit_ids, "minApplyScore": min_apply, "c2Above": above, "c2Tied": tied, "c2PairsAbove": c2_pairs_above,
            "statedBarrier": [r["id"] for r in stated], "unconfirmedBarrier": [r["id"] for r in unconfirmed],
            "c3Violations": c3_violations, "tau": tau,
            "scoreCounts": mc.tally(scores.values())}


# --- step 4: the report -------------------------------------------------------------------------------------------

def render(meta: dict, cov: dict, ratings: list[dict], summ: dict, m: dict | None, criterion: dict, stopped: bool) -> list[str]:
    head = "STOPPED at step 1 (fact coverage)" if stopped else "complete"
    out = [f"# Holdout comparison v1 — {head}", "",
           f"Date: {meta['date']}. Read-only; no production code change, no provider call by this script. Tree: commit {meta['commit']}, "
           f"scoringVersion {meta.get('scoringVersion') or 'not computed'}. Data dir compared: `{meta['dataDir']}`.", ""]
    states = mc.tally(cov.values())
    not_read = sum(v for k, v in states.items() if k != "read")
    out += ["## Step 1: fact coverage", "", f"Facts for the exact ad text: {dict(states)}. **not_read = {not_read} of {len(cov)}** "
            f"(limit {meta['maxNotRead']}; a read ad counts as read, not as not_read).", ""]
    if stopped:
        out += [f"More than {meta['maxNotRead']} ads are not_read: no metric was computed.", ""]
        return out
    out += ["## Criterion (as found in the ratings file)", "", f"Status line: _{criterion['status']}_", "", criterion["text"], "",
            "## Per ad", "", "| rank | verdict | id | name | score | before caps | band | binding cap | visa status / basis | facts |", "|---|---|---|---|---:|---:|---|---|---|---|"]
    for r in ratings:
        s = summ[r["id"]]
        out.append(f"| {r['rank']} | {r['verdict']} | `{r['id']}` | {r['name']} | {s['score']} | {s['uncapped']} | {s['band']} | "
                   f"{', '.join(s['binding']) or '-'} | {s['authStatus']} / {s['authBasis']} | {cov[r['id']]} |")
    n = m["n"]
    out += ["", "## Results (counts out of 20)", "",
            f"1. APPLY ads in the system's top {TOP_N}: **{len(m['c1Strict'])} of {len(m['applyIds'])}** counting ties against the ad "
            f"(**{len(m['c1Optimistic'])}** counting ties in its favour). Positions (best-worst): "
            + ", ".join(f"`{i}` {b}-{w}" for i, (b, w) in m["applyPositions"].items()) + ".",
            f"2. FIT-driven SKIP ads ({len(m['fitSkipIds'])}) scoring above the lowest APPLY ad ({m['minApplyScore']}): **{len(m['c2Above'])}** "
            f"{m['c2Above'] or ''}; tied with it: {len(m['c2Tied'])} {m['c2Tied'] or ''}; SKIP-above-APPLY pairs: {len(m['c2PairsAbove'])}.",
            f"3. Ads with a stated ELIG barrier ({len(m['statedBarrier'])}) shown as eligible: **{len(m['c3Violations'])}** {m['c3Violations'] or ''}. "
            f"Unconfirmed-barrier ads ({len(m['unconfirmedBarrier'])}): {m['unconfirmedBarrier']} (\"unconfirmed\" is the correct state for them; their status is in the table).",
            f"4. Kendall tau-b, score against verdict (apply 3 / maybe 2 / skip 1), informational: {m['tau']}. Distinct score values: {m['scoreCounts']}.", "",
            f"Ads: {n}. Method note: \"Professional Fit\" is read as the final matchScore; ties are reported both ways; the stated/unconfirmed "
            "barrier split is derived from the wording of the owner's reason text (visible in the ratings file). No threshold or tuning is suggested.", ""]
    return out


def git_commit() -> str:
    return mc.git_stamp()["commit"]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-dir", type=Path, required=True)
    p.add_argument("--ratings", type=Path, default=RATINGS)
    p.add_argument("--ids", type=Path, default=IDS)
    p.add_argument("--out", type=Path, default=REPORT)
    p.add_argument("--max-not-read", type=int, default=5)
    p.add_argument("--date", default=None)
    args = p.parse_args(argv)

    import datetime
    data_dir = args.data_dir
    if data_dir.resolve() == mc.default_data_dir().resolve():
        print("--data-dir must be the scratch copy, not the real data dir", file=sys.stderr)
        return 2
    ratings, criterion = parse_ratings(args.ratings.read_text(encoding="utf-8"))
    ids = [i for i in json.loads(args.ids.read_text(encoding="utf-8"))["ids"]]
    if sorted(r["id"] for r in ratings) != sorted(ids) or len(ids) != 20:
        print(f"the ratings file ({len(ratings)} rows) and the id list ({len(ids)}) do not agree on 20 ads", file=sys.stderr)
        return 2
    if not criterion["items"]:
        print("no Success criterion section in the ratings file", file=sys.stderr)
        return 2
    data_dir = args.data_dir
    meta = {"date": args.date or datetime.date.today().isoformat(), "commit": git_commit(), "dataDir": str(data_dir),
            "maxNotRead": args.max_not_read}
    before = mc.data_fingerprint(data_dir)
    cov = coverage(data_dir, ids)
    not_read = sum(1 for v in cov.values() if v != "read")
    stopped = not_read > args.max_not_read
    summ, m = {}, None
    if not stopped:
        scored = score_rows(data_dir, ids)
        meta["scoringVersion"] = scored["scoringVersion"]
        summ = {i: summarize(scored["rows"][i]) for i in ids}
        m = metrics(ratings, criterion, summ)
    text = "\n".join(render(meta, cov, ratings, summ, m, criterion, stopped))
    changed = mc.fingerprint_changes(before, mc.data_fingerprint(data_dir))
    text += f"\n## Unchanged\n\nThe compared data dir's fingerprint before vs after: {'no change' if not changed else changed}.\n"
    mc.write_private(args.out, text)
    print(text)
    return 1 if stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
