#!/usr/bin/env python3
"""Prepare a matcher-only run on an explicit list of ads, from their stored llmFacts. Free: no model call, nothing sent.

    python python/calibration/matcher_ids.py --ids IDS.json --out data/calibration/matcher-1

Reads the discovered-jobs view (read only) and copies the listed ads, with the llmFacts already stored on them, into
`review-items.json` and `enrichment-facts.json` in --out, the two files `engine_sample.py` reads. Then, from the same folder:

    python python/calibration/engine_sample.py estimate --out data/calibration/matcher-1 --max-usd 0.30
    python python/calibration/engine_sample.py run --yes --out data/calibration/matcher-1 --max-usd 0.30

`engine_sample.py` asks the evidence matcher (`match_posting`) only: through the AI budget gate with the manual confirm, after a
fail-closed scan for the owner's identifiers, one call per ad, resumable. It never runs the fit judge (llm_enhancer) and never
reads or writes matchScore, labels, priorities, scored_jobs.json, the production engine cache or the facts. Verdicts go to
engine-shadow.json in --out (mode 600), nothing else.

Ads without stored facts or without requirements are counted and left out; they are never extracted here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "python" / "job_scoring") not in sys.path:
    sys.path.insert(0, str(ROOT / "python" / "job_scoring"))
if str(ROOT / "python") not in sys.path:
    sys.path.append(str(ROOT / "python"))

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic  # noqa: E402
from calibration.enrich_sample import FACTS_NAME  # noqa: E402
from competency_mapping import load_remap  # noqa: E402

DEFAULT_JOBS = ROOT / "data" / "jobs" / "discovered_jobs.json"
DEFAULT_REMAP = ROOT / "data" / "requirement-remap.json"


def load_ids(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    ids = data.get("ids") if isinstance(data, dict) else data
    seen: dict[str, None] = {}
    for i in ids or []:
        if isinstance(i, str):
            seen.setdefault(i)
    return list(seen)


def prepare(ids: list[str], jobs_path: Path, out: Path, remap_path: Path | None = None) -> dict:
    """Write the two input files for engine_sample.py; return counts only."""
    payload = json.loads(jobs_path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs") if isinstance(payload, dict) else payload
    by_id = {j.get("jobId"): j for j in jobs or [] if isinstance(j, dict)}
    items, facts, no_facts, no_requirements, closed = [], {}, 0, 0, 0
    for job_id in ids:
        job = by_id.get(job_id)
        if job is None:
            continue
        llm = job.get("llmFacts")
        if not llm:
            no_facts += 1
            continue
        if not llm.get("requirements"):
            no_requirements += 1
            continue
        if job.get("isClosed"):
            closed += 1
        items.append({k: v for k, v in job.items() if k != "llmFacts"})
        facts[job_id] = llm
    make_private_dirs(out)
    write_text_atomic(out / "review-items.json", json.dumps({"version": 1, "items": items}, ensure_ascii=False), PRIVATE_FILE_MODE)
    write_text_atomic(out / FACTS_NAME, json.dumps({"version": 1, "facts": facts}, ensure_ascii=False), PRIVATE_FILE_MODE)
    # The production requirement remap, copied, so the ads' provisional ids read as they do in scoring (engine_sample reads it from --out).
    remap = load_remap(remap_path or DEFAULT_REMAP)
    write_text_atomic(out / "requirement-remap.json", json.dumps(remap, ensure_ascii=False, sort_keys=True), PRIVATE_FILE_MODE)
    return {"ids": len(ids), "found": sum(1 for i in ids if i in by_id), "prepared": len(items), "noFacts": no_facts,
            "noRequirements": no_requirements, "closedButPrepared": closed, "remapEntries": len(remap)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ids", type=Path, required=True)
    ap.add_argument("--jobs", type=Path, default=DEFAULT_JOBS)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    print(json.dumps(prepare(load_ids(args.ids), args.jobs, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
