#!/usr/bin/env python3
"""Package B: build the measurement report. Read-only; no behaviour change; no provider call.

    .venv/bin/python scripts/measure_package_b.py [--data-dir DIR] [--out PATH] [--snapshot PATH] [--ids45 PATH]

Runs items 1-3 (baseline snapshot, re-score impact of the stored file against this tree, gate confusion), prints the variance
script's cost estimate for the 45 labelled ads (item 4: the estimate only, nothing is called), and writes
/home/ranikola/holojob-eval/package-b-report.md plus the frozen snapshot package-b-snapshot.json (both mode 600).
A fingerprint (size and mtime, no content) of the data files before and after shows nothing under data/ moved.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_baseline as mb  # noqa: E402
import measure_common as mc  # noqa: E402
import measure_extraction_variance as mv  # noqa: E402
import measure_gate_confusion as mg  # noqa: E402
import measure_rescore_impact as mi  # noqa: E402


def variance_section(data_dir: Path, ids: list[str], runs: int = 5) -> list[str]:
    out = ["## 4. Extraction variance (written and dry-run tested; NOT executed)", "",
           "`scripts/measure_extraction_variance.py` runs the extraction N times per ad and reports the per-field flip rate. It prints its "
           "estimate first and calls nothing without `--confirm`. Not run in Package B: the owner runs it.", ""]
    try:
        os.environ.setdefault("HOLOJOB_CONFIG_DIR", str(data_dir / "config"))  # the selected provider/model, read only
        jobs, missing = mv.load_jobs(data_dir, ids)
        import competency_mapping
        intelligence = json.loads((data_dir / "intelligence" / "candidate-intelligence.json").read_text(encoding="utf-8"))
        est = mv.estimate(jobs, runs, None, None, None, competency_mapping.load_mapper(intelligence.get("roleFamily") or None))
    except Exception as exc:  # the estimate is information; its failure must not stop the report
        return out + [f"Estimate unavailable: {type(exc).__name__}: {str(exc)[:160]}", ""]
    if not est.get("priceKnown"):
        return out + ["Estimate unavailable: the selected provider/model has no known price, so the gate would refuse the run.", ""]
    out += [f"Estimate for the {len(jobs)} labelled ads that can be read ({len(missing)} not found), {runs} passes each, provider/model "
            f"{est['provider']}/{est['model']}: **{est['calls']} calls**, about {est['inputTokensTypical']:,} input tokens, "
            f"input-only floor ${est['inputOnlyUsd']:.2f}, worst case ${est['worstCaseUsd']:.2f}.", "",
            "Command (write the ids file first; `--previous-frames none` measures the model's own variance):", "",
            "```", ".venv/bin/python scripts/measure_extraction_variance.py --ids IDS.json --runs 5 --max-usd 1.50 --confirm \\",
            "    --out /home/ranikola/holojob-eval/package-b-variance.json", "```", ""]
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-dir", type=Path, default=None)
    p.add_argument("--out", type=Path, default=mc.REPORT_PATH)
    p.add_argument("--snapshot", type=Path, default=mc.SNAPSHOT_PATH)
    args = p.parse_args(argv)
    data_dir = args.data_dir or mc.default_data_dir()

    before = mc.data_fingerprint(data_dir)
    baseline = mb.build(data_dir)  # stored file + a Re-score of this tree
    mc.write_private(args.snapshot, json.dumps({k: baseline[k] for k in ("stamp", "rows", "titles")}, indent=1, sort_keys=True))

    stored_doc = mc.load_scored(data_dir / "jobs" / "scored_jobs.json")
    stored_rows = mc.snapshot_rows(stored_doc["jobs"])
    impact = mi.compare(stored_rows, baseline["rows"])
    drift = mi.input_drift(mc.meta_stamp(stored_doc["meta"]), baseline["stamp"]["currentRun"])

    frozen = json.loads((data_dir / "calibration" / "stage-a" / "eval-set.json").read_text(encoding="utf-8"))
    gate_doc = mc.rescore(data_dir, extra_ids=set(frozen["ads"]))
    gate = mg.build(frozen, {j["jobId"]: j for j in gate_doc["jobs"]}, mg.load_candidate(data_dir))

    after = mc.data_fingerprint(data_dir)
    moved = mc.fingerprint_changes(before, after)

    stamp = baseline["stamp"]
    report = [f"# Package B: measurement baseline", "",
              f"Commit `{stamp['commit']}`, scoringVersion {stamp['scoringVersion']}, {stamp['takenAt']}. Read-only: no scoring, settings, prompt or "
              "vocabulary was changed and no provider was called. Output is counts, ids and public ad titles only.", "",
              "**Reading note.** The stored `scored_jobs.json` was written by an older scorer (see section 1), so the \"stored\" column and the "
              "section 2 differences are what a Re-score of this commit would change on the owner's screen, not noise.", ""]
    report += mb.render(baseline)
    report += mi.render(impact, baseline["titles"], drift, "## 2. Re-score impact: stored file vs a Re-score of this tree")
    report += mg.render(gate)
    report += variance_section(data_dir, sorted(frozen["ads"]))
    report += ["## 5. No model call in the Re-score path", "",
               "`tests/python/test_package_b_measure.py` runs the same `run_scoring.score()` the measurement uses with the provider call, `requests`, "
               "`subprocess` and sockets patched to fail, with the shadow engine on and off, and checks statically that the measurement scripts import no "
               "extraction or provider entry point.", "",
               "## 6. Did anything under data/ change?", "",
               f"Fingerprint (size + mtime, no content) of {len(before)} files in jobs, profile, intelligence, cache, config, ai, calibration/stage-a, "
               f"applications, before and after: **{'no change' if not moved else 'CHANGED: ' + ', '.join(moved)}**.", ""]
    mc.write_private(args.out, "\n".join(report))
    print(f"report: {args.out}\nsnapshot: {args.snapshot}\ndata fingerprint: {'unchanged' if not moved else 'CHANGED ' + str(moved)}")
    return 0 if not moved else 1


if __name__ == "__main__":
    raise SystemExit(main())
