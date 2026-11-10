#!/usr/bin/env python3
"""P1 Stage A, step 8: draw the must-have precision sample from the engine results. Free and local; calls nothing.

    python python/calibration/must_sample.py [--out DIR] [--seed N]

Reads engine-shadow.json (the requirements the model marked, each with the engine's verdict), ran-labels.json (only the
owner's per-ad hard-requirements judgment, to find disagreements) and review-items.json (ad titles). Writes must-sample.json
into the same folder (directory 700, file 600, never committed). Prints counts only, never requirement or ad text.

The sample: 60 items the model marked "must", by kind quota, plus 10 probe items the model marked nice or preferred, shown
the same way so the owner cannot tell them apart. Inside each kind: items where the engine verdict disagrees with the
owner's ad-level label first (the owner said yes and the engine says MISSING or PARTIAL, or the owner said no and the
engine says MET), then agreeing controls, then the rest; production_like and diagnostic alternate, the smaller side first;
no ad gives more than MAX_PER_AD must items. Everything is ordered by a hash of the seed, so a re-run draws the same items.
The file keeps each stratum's pool size next to its sample size so the report can weight the result back to the pool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("job_scoring", "llm"):
    if str(ROOT / "python" / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / "python" / _sub))

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic  # noqa: E402

STAGE_DIR = ROOT / "data" / "calibration" / "stage-a"
SAMPLE_NAME = "must-sample.json"
SEED = 8
# The owner's quotas, rarest kind first so the scarce kinds get their ads before the per-ad cap bites.
QUOTAS = {"certification": 1, "education": 10, "domain": 10, "language": 6, "other": 8, "experience": 12, "skill": 13}
MAX_PER_AD = 3
PROBES = 10
MODES = ("production_like", "diagnostic")
CLASS_ORDER = {"disagree": 0, "control": 1, "neutral": 2}
FILL_ORDER = ("skill", "experience")  # where a kind's shortfall is made up


def _hash(*parts) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def classify(hard: str, status: str) -> str:
    """How an engine verdict sits against the owner's ad-level label. Only "yes" and "no" ads give a signal."""
    if (hard == "yes" and status in ("MISSING", "PARTIAL")) or (hard == "no" and status == "MET"):
        return "disagree"
    if (hard == "yes" and status == "MET") or (hard == "no" and status == "MISSING"):
        return "control"
    return "neutral"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def pool_of(ads: dict, labels: dict, seed: int) -> list[dict]:
    """Every requirement of every engine ad, with its mode, class and the engine's verdict."""
    rows = []
    for job_id, entry in ads.items():
        if job_id not in labels:
            continue
        hard = labels[job_id]["hardRequirements"]
        for req in (entry.get("output") or {}).get("requirements") or []:
            rows.append({
                "jobId": job_id, "reqId": req["id"], "mode": entry["mode"], "kind": req["kind"],
                "importance": req["importance"], "text": req["text"], "postingQuote": req.get("postingQuote"),
                "class": classify(hard, req["status"]) if req["importance"] == "must" else "neutral",
                "verdict": {"status": req["status"], "strength": req.get("strength"), "evidenceQuote": req.get("evidenceQuote")},
                "_order": _hash(seed, job_id, req["id"]),
            })
    return rows


def _take(queues: dict, picked_modes: Counter, per_ad: Counter, limit: int) -> list[dict]:
    """Up to `limit` items from the two mode queues: the side with fewer picks so far goes first, ties to production_like."""
    taken = []
    while len(taken) < limit:
        order = sorted((m for m in MODES if queues[m]), key=lambda m: (picked_modes[m], MODES.index(m)))
        if not order:
            break
        queue = queues[order[0]]
        row = queue.pop(0)
        if per_ad[row["jobId"]] >= MAX_PER_AD:
            continue
        per_ad[row["jobId"]] += 1
        picked_modes[row["mode"]] += 1
        taken.append(row)
    return taken


def draw(ads: dict, labels: dict, titles: dict, seed: int = SEED) -> dict:
    pool = pool_of(ads, labels, seed)
    musts = [r for r in pool if r["importance"] == "must"]
    per_ad, picked_modes, chosen = Counter(), Counter(), []
    queues_by_kind = {}
    for kind in QUOTAS:
        rows = sorted((r for r in musts if r["kind"] == kind), key=lambda r: (CLASS_ORDER[r["class"]], r["_order"]))
        queues_by_kind[kind] = {m: [r for r in rows if r["mode"] == m] for m in MODES}
    shortfall = 0
    for kind, quota in QUOTAS.items():
        got = _take(queues_by_kind[kind], picked_modes, per_ad, quota)
        chosen += got
        shortfall += quota - len(got)
    shortfall_start = shortfall
    for kind in FILL_ORDER:  # a kind that ran out (the per-ad cap, or too few in the pool) is made up from the big kinds
        if shortfall <= 0:
            break
        got = _take(queues_by_kind[kind], picked_modes, per_ad, shortfall)
        chosen += got
        shortfall -= len(got)
    probes, probe_ads, probe_modes = [], set(), Counter()
    others = sorted((r for r in pool if r["importance"] != "must"), key=lambda r: r["_order"])
    for row in others:
        if len(probes) >= PROBES:
            break
        if row["jobId"] in probe_ads or probe_modes[row["mode"]] >= PROBES // 2:
            continue
        probe_ads.add(row["jobId"])
        probe_modes[row["mode"]] += 1
        probes.append(row)
    entries = [{**r, "probe": False} for r in chosen] + [{**r, "probe": True} for r in probes]
    entries.sort(key=lambda r: _hash(seed, "display", r["jobId"], r["reqId"]))  # the owner sees one mixed order
    items = []
    for n, r in enumerate(entries, start=1):
        r = {k: v for k, v in r.items() if k != "_order"}
        items.append({"itemId": f"i{n:02d}", **r, "title": titles.get(r["jobId"], {}).get("title"),
                      "company": titles.get(r["jobId"], {}).get("company")})
    strata = []
    for kind in QUOTAS:
        for mode in MODES:
            for cls in CLASS_ORDER:
                size = sum(1 for r in musts if (r["kind"], r["mode"], r["class"]) == (kind, mode, cls))
                took = sum(1 for r in chosen if (r["kind"], r["mode"], r["class"]) == (kind, mode, cls))
                if size:
                    strata.append({"kind": kind, "mode": mode, "class": cls, "pool": size, "sampled": took})
    return {
        "version": 1, "seed": seed, "createdAt": datetime.now(timezone.utc).isoformat(), "quotas": QUOTAS, "maxPerAd": MAX_PER_AD,
        "engineAds": len(ads), "mustPool": len(musts), "shortfallMadeUp": shortfall_start - shortfall,
        "strata": strata, "items": items,
    }


def counts(sample: dict) -> dict:
    items = sample["items"]
    musts = [i for i in items if not i["probe"]]
    return {
        "mustItems": len(musts), "probeItems": len(items) - len(musts),
        "mustByKind": dict(Counter(i["kind"] for i in musts)), "mustByMode": dict(Counter(i["mode"] for i in musts)),
        "probeByMode": dict(Counter(i["mode"] for i in items if i["probe"])),
        "mustByClass": dict(Counter(i["class"] for i in musts)), "adsCovered": len({i["jobId"] for i in items}),
        "maxItemsFromOneAd": max(Counter(i["jobId"] for i in musts).values(), default=0), "mustPool": sample["mustPool"],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=STAGE_DIR)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args(argv)
    ads = _load(args.out / "engine-shadow.json")["ads"]
    labels = _load(args.out / "ran-labels.json")["labels"]
    review = _load(args.out / "review-items.json")["items"]
    titles = {i["jobId"]: {"title": i.get("title"), "company": i.get("company")} for i in review}
    sample = draw(ads, labels, titles, args.seed)
    make_private_dirs(args.out)
    write_text_atomic(args.out / SAMPLE_NAME, json.dumps(sample, indent=2, ensure_ascii=False), PRIVATE_FILE_MODE)
    print(json.dumps(counts(sample), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
