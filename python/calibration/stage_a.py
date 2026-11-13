#!/usr/bin/env python3
"""P1 Stage A: freeze the scoring inputs, re-score the frozen copy, diff, and draw the review sample.

Everything lives under data/calibration/stage-a/ (directories 700, files 600, never committed). Production files are
only read: `freeze` copies them, `rescore` runs run_scoring.py on the copy with its own lock file, `diff` compares two
files of the copy. Output is counts, ids and public ad titles; no ad, profile or CV text is printed.

    python python/calibration/stage_a.py freeze | rescore | diff | sample [--out DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("job_scoring", "llm"):
    if str(ROOT / "python" / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / "python" / _sub))

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic  # noqa: E402
from text_utils import normalize_text  # noqa: E402
import pipeline_lock  # noqa: E402

DATA = ROOT / "data"
STAGE_DIR = DATA / "calibration" / "stage-a"

# What run_scoring.py reads from data/jobs (the ledger sits beside the jobs file by name), and the intelligence.
JOB_INPUTS = ("discovered_jobs.json", "job_history.json", "manual_jobs.json", "rescored_kept.json")
INTELLIGENCE = "candidate-intelligence.json"
# Files whose change can change a score, for the "was it the data or the logic" question.
SCORING_CODE = ("python/job_scoring", "python/match_engine", "src/data")

FUNCTION = ("yes", "partial", "no")
HARD_REQS = ("yes", "partial", "no", "unknown")
OVERALL = (0, 1, 2, 3)  # 0 irrelevant, 1 weak, 2 relevant, 3 strong
SAMPLE_SIZE = 45
# The seven postings reviewed with the owner plus BoatBooker. Public titles and companies only; they are always in the sample.
CASES = [
    {"name": "construction-project-manager", "company": r"General Construction", "title": r"menad|Rukovodilac gra"},
    {"name": "porta-rai-project-director", "company": r"Porta Rai", "title": r"Project Director"},
    {"name": "mpg-account-executive", "company": r"MPG", "title": r"Account Executive"},
    {"name": "bambi-digital-platform-lead", "company": r"Bambi", "title": r"Lider digitalne"},
    {"name": "enel-site-manager", "company": r"Enel", "title": r"Rukovodilac gradili"},
    {"name": "cyrillic-product-owner", "company": r"Cyrillic", "title": r"Product Owner"},
    {"name": "raiffeisen-product-manager", "company": r"Raiffeisen", "title": r"Product Manager"},
    {"name": "boatbooker-product-manager", "company": r"FishingBooker|BoatBooker", "title": r"Product Manager"},
]
# What the review screen may show of an ad. Never a score, label, cap, reason or engine field.
REVIEW_FIELDS = ("jobId", "title", "company", "location", "site", "jobUrl", "description")

_SR_WORDS = set("i u za na je se od sa koji kao ili da su kroz rad posla iskustvo znanje poslovi".split())
_EN_WORDS = set("the and of to in for with you we our will are is on as experience work".split())


# --- small helpers ------------------------------------------------------------


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _write_private(path: Path, text: str) -> None:
    make_private_dirs(path.parent)
    write_text_atomic(path, text, PRIVATE_FILE_MODE)


def _copy_private(src: Path, dst: Path) -> None:
    _write_private(dst, src.read_text(encoding="utf-8"))


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def language_of(text: str) -> str:
    """'sr' or 'en' by the share of common function words; a rough label for stratifying, not for scoring."""
    words = re.findall(r"[a-zšđčćž]+", (text or "").lower())
    total = len(words) or 1
    sr = sum(w in _SR_WORDS for w in words) / total
    en = sum(w in _EN_WORDS for w in words) / total
    return "sr" if sr > en else "en"


def cap_type(row: dict) -> str:
    """Which cap shaped the score, read from the reason lines the scorer wrote."""
    for text in row.get("reasons") or []:
        if text.startswith("Capped:"):
            if "title matches no" in text:
                return "title"
            if "the ad describes" in text:
                return "track"
            if "the ad requires" in text:
                return "language"
            return "authorization"
        if text.startswith("Red flag"):
            return "red_flag"
    return "none"


def _rows(payload) -> list[dict]:
    rows = payload.get("jobs") if isinstance(payload, dict) else payload
    return [r for r in rows if isinstance(r, dict)]


# --- step 1: freeze ---------------------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()


def freeze(out: Path = STAGE_DIR, data: Path = DATA, lock: Path | None = None) -> dict:
    """Copy the pre-re-score baseline and every scoring input; write a manifest with hashes. Run once."""
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        raise SystemExit(f"already frozen: {manifest_path} (the baseline is never overwritten)")
    held = pipeline_lock.acquire(path=lock or pipeline_lock.lock_path())
    if held is None:
        raise SystemExit(pipeline_lock.BUSY_MESSAGE)
    try:
        jobs = data / "jobs"
        baseline_src = jobs / "scored_jobs.json"
        copies, missing = {}, []
        for name in JOB_INPUTS:
            (copies.__setitem__(f"inputs/{name}", jobs / name) if (jobs / name).exists() else missing.append(name))
        copies[f"inputs/{INTELLIGENCE}"] = data / "intelligence" / INTELLIGENCE
        copies["baseline/scored_jobs.json"] = baseline_src
        files = {}
        for rel, src in copies.items():
            _copy_private(src, out / rel)
            files[rel] = {"sha256": _sha(src), "copySha256": _sha(out / rel), "bytes": src.stat().st_size}
    finally:
        held.release()
    baseline_meta = _load(baseline_src).get("meta") or {}
    intelligence_meta = (_load(data / "intelligence" / INTELLIGENCE).get("meta") or {})
    generated = baseline_meta.get("generatedAt")
    manifest = {
        "frozenAt": _now(),
        "files": files,
        "missingOptionalInputs": missing,
        "baseline": {k: baseline_meta.get(k) for k in ("generatedAt", "sourceRunId", "intelligenceGeneratedAt",
                                                       "scoringVersion", "jobCount", "summary")},
        "intelligenceAtFreeze": {"generatedAt": intelligence_meta.get("generatedAt"),
                                 "fileModified": datetime.fromtimestamp(
                                     (data / "intelligence" / INTELLIGENCE).stat().st_mtime, timezone.utc).isoformat()},
    }
    try:
        manifest["git"] = {"head": _git("rev-parse", "--short", "HEAD")}
        if generated:
            base = _git("rev-list", "-1", f"--before={generated}", "HEAD")
            changed = _git("diff", "--name-only", base, "HEAD", "--", *SCORING_CODE).splitlines()
            manifest["git"].update(baselineCommit=base[:7], scoringCodeChangedSinceBaseline=changed)
    except (subprocess.CalledProcessError, FileNotFoundError):
        manifest["git"] = {"error": "git unavailable"}
    _write_private(manifest_path, json.dumps(manifest, indent=2))
    return manifest


# --- step 2: isolated re-score -------------------------------------------------


def rescore(out: Path = STAGE_DIR) -> int:
    """run_scoring.py on the frozen copy only: own lock file, own output, shadow engine and judge off."""
    inputs = out / "inputs"
    manifest = _load(out / "manifest.json")
    before = {name: _sha(inputs / name) for name in JOB_INPUTS if (inputs / name).exists()}
    target = out / "rescored" / "scored_jobs.json"
    make_private_dirs(target.parent)
    cmd = [sys.executable, str(ROOT / "python" / "job_scoring" / "run_scoring.py"),
           "--jobs", str(inputs / "discovered_jobs.json"), "--manual", str(inputs / "manual_jobs.json"),
           "--kept", str(inputs / "rescored_kept.json"), "--intelligence", str(inputs / INTELLIGENCE),
           "--output", str(target)]
    env = {k: v for k, v in os.environ.items() if k != "HOLOJOB_ENGINE_SHADOW"}
    env["HOLOJOB_PIPELINE_LOCK"] = str(out / ".pipeline.lock")
    done = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=ROOT)
    after = {name: _sha(inputs / name) for name in before}
    if (out / ".pipeline.lock").exists():
        os.chmod(out / ".pipeline.lock", PRIVATE_FILE_MODE)  # the lock file is created with the process default
    result = {
        "ranAt": _now(), "exitCode": done.returncode,
        # run_scoring prints counts only; kept to the last lines in case of an error.
        "stdoutTail": done.stdout.strip().splitlines()[-5:], "stderrTail": done.stderr.strip().splitlines()[-5:],
        "frozenInputsChangedByTheRun": sorted(n for n in before if before[n] != after[n]),
    }
    manifest["rescore"] = result
    _write_private(out / "manifest.json", json.dumps(manifest, indent=2))
    if target.exists():
        os.chmod(target, PRIVATE_FILE_MODE)
    return done.returncode


# --- step 3: diff ----------------------------------------------------------------


DIMENSIONS = ("roleMatch", "skillMatch", "industryMatch", "experienceMatch", "locationMatch", "cultureMatch")


def _raw(row: dict, dim: str):
    return ((row.get("scoreBreakdown") or {}).get(dim) or {}).get("raw")


def diff_scores(before: list[dict], after: list[dict]) -> dict:
    """Per-job difference of two scored lists, by id. Counts and ids; titles are the public ad titles."""
    b = {r["jobId"]: r for r in before if r.get("jobId")}
    a = {r["jobId"]: r for r in after if r.get("jobId")}
    changed = []
    for job_id in sorted(set(b) & set(a)):
        x, y = b[job_id], a[job_id]
        dims = {d: [_raw(x, d), _raw(y, d)] for d in DIMENSIONS if _raw(x, d) != _raw(y, d)}
        moved = (x.get("matchScore") != y.get("matchScore") or x.get("matchLabel") != y.get("matchLabel")
                 or x.get("priority") != y.get("priority") or cap_type(x) != cap_type(y) or dims)
        if moved:
            changed.append({"jobId": job_id, "title": y.get("title"),
                            "score": [x.get("matchScore"), y.get("matchScore")],
                            "label": [x.get("matchLabel"), y.get("matchLabel")],
                            "priority": [x.get("priority"), y.get("priority")],
                            "cap": [cap_type(x), cap_type(y)], "dimensions": dims})
    return {
        "before": len(b), "after": len(a), "common": len(set(b) & set(a)),
        "onlyBefore": sorted(set(b) - set(a)), "onlyAfter": sorted(set(a) - set(b)),
        "changed": changed, "unchanged": len(set(b) & set(a)) - len(changed),
        "labelChanges": sum(c["label"][0] != c["label"][1] for c in changed),
        "dimensionChanges": dict(Counter(d for c in changed for d in c["dimensions"])),
        "scoreDeltas": dict(Counter((c["score"][1] or 0) - (c["score"][0] or 0) for c in changed)),
    }


def diff(out: Path = STAGE_DIR) -> dict:
    manifest = _load(out / "manifest.json")
    result = diff_scores(_rows(_load(out / "baseline" / "scored_jobs.json")),
                         _rows(_load(out / "rescored" / "scored_jobs.json")))
    code = (manifest.get("git") or {}).get("scoringCodeChangedSinceBaseline")
    result["attribution"] = {
        "intelligenceAtBaseline": (manifest.get("baseline") or {}).get("intelligenceGeneratedAt"),
        "intelligenceAtFreeze": (manifest.get("intelligenceAtFreeze") or {}).get("generatedAt"),
        "scoringCodeChangedSinceBaseline": code,
        "reading": ("no score, label, priority, cap or dimension differs: the re-score reproduces the baseline, so "
                    "stale inputs did not move any score" if not result["changed"] and not result["onlyBefore"]
                    and not result["onlyAfter"] else
                    "no scoring code changed since the baseline run, so every difference comes from changed inputs "
                    "(intelligence or job data)" if code == [] else
                    "files under the scoring folders changed since the baseline run (listed): inspect whether they "
                    "affect scoring before attributing a difference to logic" if code else
                    "unknown (git data missing)"),
    }
    _write_private(out / "diff.json", json.dumps(result, indent=2))
    return result


# --- step 4: sample and sheet -------------------------------------------------------


def resolve_cases(rows: list[dict], cases=CASES) -> tuple[dict, list[str]]:
    """{case name: jobId} and the names that match no row. A case matches company and title; on a tie the best score wins."""
    found, missing = {}, []
    for case in cases:
        hits = [r for r in rows if re.search(case["company"], r.get("company") or "", re.I)
                and re.search(case["title"], r.get("title") or "", re.I)]
        if hits:
            found[case["name"]] = max(hits, key=lambda r: r.get("matchScore") or 0)["jobId"]
        else:
            missing.append(case["name"])
    return found, missing


def _features(row: dict) -> dict:
    return {"band": row.get("matchLabel"), "cap": cap_type(row), "lang": language_of(row.get("description") or ""),
            "provider": row.get("provider")}


def draw_sample(rows: list[dict], size: int, seed: int, cases: dict[str, str]) -> list[dict]:
    """The cases first, then open ads one by one, each time the one whose band, cap, language and provider are the
    least covered so far (seeded tie-break). Closed ads and ads without a title are never drawn."""
    by_id = {r["jobId"]: r for r in rows}
    chosen = [by_id[j] for j in cases.values() if j in by_id]
    taken = {r["jobId"] for r in chosen}
    seen = Counter((k, v) for r in chosen for k, v in _features(r).items())
    pool = [r for r in rows if r["jobId"] not in taken and not r.get("isClosed") and r.get("title")]
    rng = random.Random(seed)
    rng.shuffle(pool)
    while len(chosen) < size and pool:
        best = max(pool, key=lambda r: sum(1 / (1 + seen[(k, v)]) for k, v in _features(r).items()))
        pool.remove(best)
        chosen.append(best)
        seen.update(_features(best).items())
    return chosen


def match_key(row: dict) -> str:
    """Title and company, folded: the same ad can hold two ids, so a holdout excludes by this as well as by id."""
    return f"{normalize_text(row.get('title') or '')}|{normalize_text(row.get('company') or '')}"


def sample(out: Path = STAGE_DIR, size: int = SAMPLE_SIZE, seed: int = 20261110) -> dict:
    """The review sample. The draw is sequential, so a larger size keeps every ad of a smaller one (30 -> 45)."""
    rows = _rows(_load(out / "rescored" / "scored_jobs.json"))
    cases, missing = resolve_cases(rows)
    chosen = draw_sample(rows, size, seed, cases)
    by_id = {r["jobId"]: r for r in chosen}
    order = [r["jobId"] for r in chosen]
    shown = list(order)
    random.Random(seed + 1).shuffle(shown)  # the review does not group the known cases
    items = [{k: by_id[j].get(k) or "" for k in REVIEW_FIELDS} for j in shown]
    _write_private(out / "review-items.json", json.dumps({"version": 1, "items": items}, indent=2))
    summary = {
        "size": len(chosen), "seed": seed, "casesFound": cases, "casesMissing": missing,
        "strata": {key: dict(Counter(_features(r)[key] for r in chosen)) for key in ("band", "cap", "lang", "provider")},
    }
    # Holdout rule: a later holdout is drawn from ads first seen after the freeze and excludes all of these.
    exclusions = {"jobIds": sorted(order), "matchKeys": sorted({match_key(r) for r in chosen})}
    _write_private(out / "sample.json", json.dumps(
        {**summary, "drawOrder": order, "jobIds": shown, "holdoutExclusions": exclusions}, indent=2))
    return summary


# --- command line -------------------------------------------------------------------


def _print_diff(result: dict) -> None:
    print(f"jobs: baseline {result['before']}, re-score {result['after']}, common {result['common']}, "
          f"only in baseline {len(result['onlyBefore'])}, only in re-score {len(result['onlyAfter'])}")
    print(f"changed: {len(result['changed'])}, unchanged: {result['unchanged']}, label changes: {result['labelChanges']}")
    print(f"dimensions that moved: {result['dimensionChanges']}; score deltas: {result['scoreDeltas']}")
    print(f"attribution: {result['attribution']['reading']}")
    print(f"intelligence: baseline {result['attribution']['intelligenceAtBaseline']}, "
          f"freeze {result['attribution']['intelligenceAtFreeze']}")
    for c in result["changed"][:40]:
        print(f"  {c['jobId'][:12]} | {(c['title'] or '')[:55]} | {c['score'][0]}->{c['score'][1]} "
              f"{c['label'][0]}->{c['label'][1]} cap {c['cap'][0]}->{c['cap'][1]} dims {sorted(c['dimensions'])}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("command", choices=("freeze", "rescore", "diff", "sample"))
    p.add_argument("--out", type=Path, default=STAGE_DIR)
    p.add_argument("--size", type=int, default=SAMPLE_SIZE)
    args = p.parse_args(argv)
    if args.command == "freeze":
        m = freeze(args.out)
        print(f"frozen {len(m['files'])} files to {args.out}; baseline generated {m['baseline']['generatedAt']}, "
              f"jobs {m['baseline']['jobCount']}; scoring code changed since baseline: "
              f"{(m.get('git') or {}).get('scoringCodeChangedSinceBaseline')}")
        return 0
    if args.command == "rescore":
        code = rescore(args.out)
        m = _load(args.out / "manifest.json")["rescore"]
        print(f"re-score exit {code}; frozen inputs changed by the run: {m['frozenInputsChangedByTheRun']}")
        print("\n".join(m["stdoutTail"]))
        return code
    if args.command == "diff":
        _print_diff(diff(args.out))
        return 0
    s = sample(args.out, args.size)
    print(f"sample {s['size']} ads; cases found {len(s['casesFound'])}, missing {s['casesMissing']}; strata {s['strata']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
