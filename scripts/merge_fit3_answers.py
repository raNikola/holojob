#!/usr/bin/env python3
"""W5 layer (b): put the matcher's answers over the Fit 3 competency rows into the stored classification. NO model call, NO provider, offline.

    .venv/bin/python scripts/merge_fit3_answers.py                       # reads the defaults below, writes <scratch>/fit3/store.json

--scratch DIR          default /home/ranikola/holojob-eval/holdout-scratch-data (refused if it is, or sits inside, the real data dir)
--classification NAME  a file under <scratch>/fit3/ made by measure_fit3.py (default classification.json)
--matcher DIR          the measure_holdout_matcher.py --fit3 output (default <scratch>/matcher-fit3): review-items.json and engine-shadow.json
--out NAME             the file written under <scratch>/fit3/ (default store.json); an existing file is never overwritten

The matcher result is keyed by ad id; the classification by `fit3.classification_key`, recomputed here from the ad in review-items.json. An entry
gets `answers` = the matcher rows of its ad (id = competency id); an ad the matcher did not answer keeps `answers: null` and its competencies stay
UNKNOWN. The output has the `data/cache/fit3.json` shape; the owner copies it there (mode 600). Counts only on the console.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_common as mc  # noqa: E402
import measure_fit3 as m3  # noqa: E402


def merge(classification: dict, items: list[dict], results: dict) -> tuple[dict, dict]:
    """(store document, counts). `results` = engine-shadow.json["ads"]."""
    from match_engine import fit3
    roles, comps = fit3.load_roles(), fit3.closed_competencies()
    entries = dict(classification.get("entries") or {})
    counts = {"entries": len(entries), "ads": len(items), "withAnswers": 0, "noClassification": 0, "noMatcherResult": 0, "rowsWithoutId": 0}
    for item in items:
        key = fit3.classification_key(m3.posting_of(item), roles, comps)
        entry = entries.get(key)
        if not isinstance(entry, dict):
            counts["noClassification"] += 1
            continue
        rows = ((results.get(item["jobId"]) or {}).get("output") or {}).get("requirements")
        if not isinstance(rows, list) or not rows:
            counts["noMatcherResult"] += 1
            continue
        counts["rowsWithoutId"] += sum(1 for r in rows if not isinstance(r, dict) or not r.get("id"))
        entries[key] = {**entry, "answers": [r for r in rows if isinstance(r, dict) and r.get("id")]}
        counts["withAnswers"] += 1
    return {"version": 1, "promptVersion": classification.get("promptVersion"), "entries": entries}, counts


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--scratch", type=Path, default=m3.DEFAULT_SCRATCH)
    p.add_argument("--classification", default=m3.OUT_NAME)
    p.add_argument("--matcher", type=Path, default=None)
    p.add_argument("--out", default="store.json")
    p.add_argument("--data-dir", type=Path, default=None)
    p.add_argument("--candidate", type=Path, default=None, help="a Fit 3 candidate directory (prompt, prompt version, competency wording); default the repo prompt")
    args = p.parse_args(argv)
    if args.candidate:
        from match_engine import fit3 as _fit3
        _fit3.use_candidate(args.candidate)
    real = Path(args.data_dir or mc.default_data_dir()).resolve()
    scratch = args.scratch.resolve()
    if scratch == real or real in scratch.parents:
        print("the scratch dir is, or sits inside, the real data dir: refused", file=sys.stderr)
        return 2
    for name in (args.classification, args.out):
        if Path(name).name != name or not name.endswith(".json"):
            print("file names must be plain *.json names", file=sys.stderr)
            return 2
    out_path = scratch / m3.OUT_DIR / args.out
    if out_path.exists():
        print(f"{out_path} exists: refusing to overwrite", file=sys.stderr)
        return 2
    matcher_dir = (args.matcher or scratch / "matcher-fit3").resolve()
    try:
        classification = json.loads((scratch / m3.OUT_DIR / args.classification).read_text(encoding="utf-8"))
        items = json.loads((matcher_dir / "review-items.json").read_text(encoding="utf-8"))["items"]
        results = json.loads((matcher_dir / "engine-shadow.json").read_text(encoding="utf-8")).get("ads") or {}
    except (OSError, ValueError, KeyError) as exc:
        print(f"cannot read the inputs: {type(exc).__name__}", file=sys.stderr)
        return 1
    store, counts = merge(classification, items, results)
    mc.write_private(out_path, json.dumps(store, ensure_ascii=False))
    print(json.dumps({"counts": counts, "wrote": str(out_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
