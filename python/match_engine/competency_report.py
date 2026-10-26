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
SHOWN_THRESHOLD = 0.5  # the candidates file shows a closest competency from this similarity up
DEFAULT_MIN_ADS = 2
EXAMPLES_PER_GROUP = 3
DATA_DIR = ROOT / "data"
DEFAULT_OUT = DATA_DIR / "competency-report.json"
REVIEW_OUT = DATA_DIR / "competencies-review.md"
CANDIDATES_OUT = DATA_DIR / "competency-candidates.md"
CANDIDATE_LIMIT = 40


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


def closest(key: str, index: dict[str, str], threshold: float = NEAR_THRESHOLD) -> dict | None:
    """The competency whose alias is most like the key, or None below the threshold."""
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
    if best_alias is None or best < threshold:
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


def review_markdown(comps: list[dict], family: str) -> str:
    """The list as Markdown for the owner's review, in seed order. Nothing from ads or the profile."""
    aliases = sum(len(c.get("aliases", [])) for c in comps)
    lines = [f"# Competency review: {family}", "", f"{len(comps)} competencies, {aliases} aliases.", ""]
    for c in comps:
        lines += [f"## {c['id']}", "", f"- Kind: {c['kind']}"]
        if c.get("parent"):
            lines.append(f"- Parent: {c['parent']}")
        lines += [f"- Definition: {c['definition']}", "- Aliases:"]
        lines += [f"  - {a}" for a in c.get("aliases", [])]
        lines.append("")
    return "\n".join(lines)


def candidate_rows(frames: dict, comps: list[dict], limit: int = CANDIDATE_LIMIT) -> list[dict]:
    """The `limit` most frequent groups (by ads) no alias and no near alias covers, each with its closest competency if any."""
    index = competencies.alias_index(comps)
    ranked = sorted(provisional_groups(frames).items(), key=lambda kv: (-len(kv[1]["ads"]), kv[0]))
    rows = []
    for key, g in ranked:
        if key in index:
            continue
        near = closest(key, index, SHOWN_THRESHOLD)
        if near and near["similarity"] >= NEAR_THRESHOLD:
            continue
        rows.append({"text": key, "ads": len(g["ads"]), "examples": [w for w, _ in g["wordings"].most_common(EXAMPLES_PER_GROUP)], "closest": near})
        if len(rows) == limit:
            break
    return rows


def candidates_markdown(rows: list[dict]) -> str:
    """Ad wordings only, nothing from the profile."""
    lines = ["# Competency candidates", "", f"{len(rows)} groups with no alias and no close alias, most frequent first.", ""]
    for r in rows:
        lines += [f"## {r['text']}", "", f"- Ads: {r['ads']}", "- Examples:"]
        lines += [f"  - {w}" for w in r["examples"]]
        near = r["closest"]
        lines.append(f"- Closest: {near['competency']} (alias {near['alias']!r}, {near['similarity']})" if near else "- Closest: none")
        lines.append("")
    return "\n".join(lines)


def write_candidates(frames: dict, comps: list[dict], out: Path = CANDIDATES_OUT, limit: int = CANDIDATE_LIMIT) -> Path:
    """Validate the list and write the candidates file under data/ (SystemExit otherwise)."""
    problems = competencies.validate(comps)
    if not comps or problems:
        raise SystemExit("\n  ".join(["competency list is not usable:", *(problems or ["no list"])]))
    path = checked_out_path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(candidates_markdown(candidate_rows(frames, comps, limit)), encoding="utf-8")
    return path


def write_review(family: str, out: Path = REVIEW_OUT) -> Path:
    """Validate the family's list and write its review file under data/ (SystemExit otherwise)."""
    comps = competencies.load(family)
    problems = competencies.validate(comps)
    if not comps or problems:
        raise SystemExit("\n  ".join([f"competency list '{family}' is not usable:", *(problems or ["no list"])]))
    path = checked_out_path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(review_markdown(comps, family), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--family", default="product")
    parser.add_argument("--min-ads", type=int, default=DEFAULT_MIN_ADS, help="smallest group (in ads) to list")
    parser.add_argument("--frames", type=Path, default=None, help="requirement frames file (default: the server's)")
    parser.add_argument("--out", type=Path, default=None, help="output file under data/")
    parser.add_argument("--candidates", action="store_true", help="write the most frequent new-candidate groups instead of the report")
    parser.add_argument("--review", action="store_true", help="write the Markdown review of the list instead of the report")
    args = parser.parse_args(argv)

    if args.review:
        path = write_review(args.family, args.out or REVIEW_OUT)
        print(f"review: {path}")
        return 0
    if args.candidates:
        path = write_candidates(requirement_frames.load(args.frames), competencies.load(args.family), args.out or CANDIDATES_OUT)
        print(f"candidates: {path}")
        return 0
    args.out = args.out or DEFAULT_OUT

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
