#!/usr/bin/env python3
"""Local curation report for the competency seed. No model call.

Reads the extracted requirements (data/cache/requirement-frames.json), groups
the provisional ones by their alias key, and for each frequent group shows the
number of ads, example wordings and the closest competency of the family's
list, or marks it "new candidate". Also prints the baseline: how many
provisional requirements an exact alias match resolves. Counts only on
stdout; the groups go to a file under data/ (gitignored), never a tracked path.

Alias keys: competencies.alias_key (match_engine.normalize, typographic
apostrophes straightened, trailing .,;: dropped). Closeness is difflib's
ratio against every alias, at or above NEAR_THRESHOLD.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "python") not in sys.path:
    sys.path.append(str(ROOT / "python"))

from match_engine import competencies  # noqa: E402 (puts job_scoring on the path)
import requirement_frames  # noqa: E402
from requirement_ids import PROVISIONAL_PREFIX  # noqa: E402

NEAR_THRESHOLD = 0.85
DEFAULT_MIN_ADS = 2
EXAMPLES_PER_GROUP = 3
DATA_DIR = ROOT / "data"
DEFAULT_OUT = DATA_DIR / "competency-report.json"


def provisional_groups(frames: dict) -> dict[str, dict]:
    """alias key -> {"ads": set of ad keys, "occurrences": int, "wordings": Counter, "kinds": Counter}."""
    groups: dict[str, dict] = {}
    for ad, requirements in frames.items():
        for r in requirements:
            if not str(r.get("id", "")).startswith(PROVISIONAL_PREFIX):
                continue
            key = competencies.alias_key(r.get("text"))
            if not key:
                continue
            g = groups.setdefault(key, {"ads": set(), "occurrences": 0, "wordings": Counter(), "kinds": Counter()})
            g["ads"].add(ad)
            g["occurrences"] += 1
            g["wordings"][str(r.get("text")).strip()] += 1
            g["kinds"][r.get("kind")] += 1
    return groups


def baseline(groups: dict[str, dict], index: dict[str, str]) -> dict[str, int]:
    """Counts of provisional requirements an exact alias match resolves."""
    ads_all, ads_hit = set(), set()
    out = Counter()
    for key, g in groups.items():
        hit = key in index
        out["occurrences"] += g["occurrences"]
        out["distinctTexts"] += 1
        ads_all |= g["ads"]
        if hit:
            out["occurrencesResolved"] += g["occurrences"]
            out["distinctTextsResolved"] += 1
            ads_hit |= g["ads"]
    out["ads"] = len(ads_all)
    out["adsWithAResolved"] = len(ads_hit)
    return {k: out[k] for k in ("occurrences", "occurrencesResolved", "distinctTexts", "distinctTextsResolved", "ads", "adsWithAResolved")}


def closest(key: str, index: dict[str, str]) -> dict | None:
    """The competency whose alias is most like the key, or None below NEAR_THRESHOLD."""
    best_alias, best = None, 0.0
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(key)
    for alias in index:
        matcher.set_seq1(alias)
        if matcher.real_quick_ratio() <= best or matcher.quick_ratio() <= best:
            continue
        ratio = matcher.ratio()
        if ratio > best:
            best_alias, best = alias, ratio
    if best_alias is None or best < NEAR_THRESHOLD:
        return None
    return {"competency": index[best_alias], "alias": best_alias, "similarity": round(best, 3)}


def build_report(frames: dict, comps: list[dict], min_ads: int = DEFAULT_MIN_ADS) -> dict:
    index = competencies.alias_index(comps)
    groups = provisional_groups(frames)
    rows = []
    for key, g in groups.items():
        if len(g["ads"]) < min_ads:
            continue
        if key in index:
            status, near = "alias", {"competency": index[key], "alias": key, "similarity": 1.0}
        else:
            near = closest(key, index)
            status = "near" if near else "new candidate"
        rows.append({
            "text": key,
            "ads": len(g["ads"]),
            "occurrences": g["occurrences"],
            "kind": g["kinds"].most_common(1)[0][0],
            "examples": [w for w, _ in g["wordings"].most_common(EXAMPLES_PER_GROUP)],
            "status": status,
            "closest": near,
        })
    rows.sort(key=lambda r: (-r["ads"], r["text"]))
    return {"minAds": min_ads, "baseline": baseline(groups, index), "groups": rows}


def checked_out_path(path: Path) -> Path:
    """The report is written under data/ only; data/ is where untracked files live."""
    resolved = path.resolve()
    if DATA_DIR.resolve() not in resolved.parents:
        raise SystemExit(f"refusing to write the report outside {DATA_DIR}: {path}")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--family", default="product")
    parser.add_argument("--min-ads", type=int, default=DEFAULT_MIN_ADS, help="smallest group (in ads) to list")
    parser.add_argument("--frames", type=Path, default=None, help="requirement frames file (default: the server's)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    comps = competencies.load(args.family)
    problems = competencies.validate(comps)
    if not comps or problems:
        print(f"competency list '{args.family}' is not usable:", *(problems or ["no list"]), sep="\n  ", file=sys.stderr)
        return 1
    out = checked_out_path(args.out)
    report = build_report(requirement_frames.load(args.frames), comps, args.min_ads)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    b = report["baseline"]
    by_status = Counter(r["status"] for r in report["groups"])
    print(f"competencies: {len(comps)} ({args.family})")
    print(f"provisional requirements resolved by exact alias: {b['occurrencesResolved']} of {b['occurrences']}")
    print(f"distinct provisional texts resolved: {b['distinctTextsResolved']} of {b['distinctTexts']}")
    print(f"ads with at least one resolved: {b['adsWithAResolved']} of {b['ads']}")
    print(f"groups listed (in >= {args.min_ads} ads): {len(report['groups'])}", dict(by_status))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
