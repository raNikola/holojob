#!/usr/bin/env python3
"""Audit the competency mapping on a small sample of already-extracted ads.

    .venv/bin/python python/match_engine/competency_audit.py --ads 30 --env-file .env --yes

Runs the real extraction path (enrich_jobs.extract, current prompt, the family's
competency list) twice on N randomly chosen ads. Both runs start from the same
copies of the live frames, learned aliases and remap table and write only into
a scratch directory under data/, never into the live files, so the two runs
measure the model's noise and not each other's state. The ads go to the
configured provider (the extraction call never sees the candidate); without
--yes the tool only prints how many calls it would make.

Prints counts only. The owner's review file, data/competency-audit.md
(gitignored), holds ad wordings and the list's own definitions, nothing from
the profile: section A for model-picked mappings, section B for requirements
that stayed provisional.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))

from match_engine import competency_report  # noqa: E402 (puts job_scoring on the path)
from match_engine import competencies  # noqa: E402
from match_engine.calibrate import load_env_file  # noqa: E402
import competency_mapping  # noqa: E402
import enrich_jobs  # noqa: E402
import requirement_frames  # noqa: E402
from llm_client import LlmRefused, LlmUnavailable  # noqa: E402

DEFAULT_ADS = 30
DEFAULT_SEED = 1
SECTION_A_LIMIT = 100
SECTION_B_LIMIT = 40
SCRATCH_NAME = "competency-audit-scratch"
AUDIT_NAME = "competency-audit.md"
ROUTES = ("frame", "alias", "dictionary", "model", "provisional")


def scratch_dir() -> Path:
    return competency_report.DATA_DIR / SCRATCH_NAME


def audit_path() -> Path:
    return competency_report.DATA_DIR / AUDIT_NAME


def looks_compound(text: str) -> bool:
    """True when the wording seems to name more than one thing: " and ", " or ", "/" or a comma list."""
    padded = f" {' '.join(str(text).lower().split())} "
    return any(mark in padded for mark in (" and ", " or ", "/", ","))


def sample_ads(jobs: list[dict], n: int, seed: int) -> list[dict]:
    """N already-extracted ads, chosen by the seed, in file order."""
    pool = [(i, j) for i, j in enumerate(jobs) if ((j.get("llmFacts") or {}).get("requirements"))]
    chosen = sorted(random.Random(seed).sample(pool, min(n, len(pool))), key=lambda t: t[0])
    return [j for _, j in chosen]


def run_once(ads: list[dict], comps: list[dict], directory: Path, live_frames: dict, model, provider, workers: int) -> dict:
    """One extraction pass over the ads with state copied into `directory`; returns {"ads", "mapper", "failed"}."""
    directory.mkdir(parents=True, exist_ok=True)
    aliases, remap = directory / "competency-aliases.json", directory / "requirement-remap.json"
    for live, copy in ((competency_mapping.ALIASES_PATH, aliases), (competency_mapping.REMAP_PATH, remap)):
        if live.exists():
            shutil.copyfile(live, copy)
    mapper = competency_mapping.Mapper(comps, aliases, remap)
    frames = json.loads(json.dumps(live_frames))
    requirement_frames.apply_remap(frames, mapper.remap)

    def one(job):
        previous = requirement_frames.previous_for(frames, job, mapper.remap)
        return enrich_jobs.extract(job, model, provider, previous, mapper=mapper)

    results, failed = {}, 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [(job, pool.submit(one, job)) for job in ads]
        for job, future in futures:
            try:
                facts = future.result()
            except (LlmUnavailable, LlmRefused) as exc:
                print(f"    failed: {exc}", file=sys.stderr)
                failed += 1
                continue
            results[requirement_frames.frame_key(job)] = facts
            requirement_frames.remember(frames, job, facts)
    mapper.save()
    requirement_frames.apply_remap(frames, mapper.remap)
    requirement_frames.save(frames, directory / "requirement-frames.json")
    (directory / "requirements.json").write_text(
        json.dumps({k: v["requirements"] for k, v in results.items()}, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"ads": results, "mapper": mapper, "failed": failed}


def run_counts(run: dict) -> dict:
    """Counts only: requirements, routes, model picks by outcome, requirements left provisional."""
    reqs = [r for facts in run["ads"].values() for r in facts["requirements"]]
    stats, routes = run["mapper"].stats, run["mapper"].routes
    return {
        "requirements": len(reqs),
        "routes": {r: routes[r] for r in ROUTES},
        "picks": {
            "accepted": stats["accepted"], "none": stats["none"],
            "rejected: not on the list": stats["rejected: not on the list"],
            "rejected: kind differs": stats["rejected: kind differs"],
        },
        "stillProvisional": sum(1 for r in reqs if r.get("provisional")),
        "failedAds": run["failed"],
    }


def by_text(run: dict) -> dict[tuple[str, str], dict]:
    """(ad, alias key of the text) -> requirement."""
    return {
        (ad, competencies.alias_key(r["text"])): r
        for ad, facts in run["ads"].items() for r in facts["requirements"]
    }


def stability(first: dict, second: dict) -> dict:
    """Over the requirements both runs state in the same words: same id, and agreement on mapped (canonical) or not."""
    a, b = by_text(first), by_text(second)
    both = a.keys() & b.keys()
    same = sum(1 for k in both if a[k]["id"] == b[k]["id"])
    mapped_disagree = sum(1 for k in both if bool(a[k].get("provisional")) != bool(b[k].get("provisional")))
    total = len(a.keys() | b.keys())
    return {
        "paired": len(both), "unpaired": total - len(both),
        "sameId": same, "mappedDisagree": mapped_disagree,
        "sameIdShare": same / len(both) if both else None,
        "mappedDisagreeShare": mapped_disagree / len(both) if both else None,
    }


def audit_markdown(run: dict, comps: list[dict], seed: int) -> str:
    """Two numbered sections for the owner; ad wordings and the list's own definitions only."""
    rng = random.Random(seed)
    by_id = {c["id"]: c for c in comps}
    index = competencies.alias_index(comps)

    picks, seen = [], set()
    for text, cid in run["mapper"].picks:
        key = competencies.alias_key(text)
        if key not in seen:
            seen.add(key)
            picks.append((text, cid))
    picks = rng.sample(picks, min(SECTION_A_LIMIT, len(picks)))

    open_, seen = [], set()
    for facts in run["ads"].values():
        for r in facts["requirements"]:
            key = competencies.alias_key(r["text"])
            if r.get("provisional") and key not in seen:
                seen.add(key)
                open_.append(r["text"])
    open_ = rng.sample(open_, min(SECTION_B_LIMIT, len(open_)))

    lines = ["# Competency mapping audit", "",
             "## A. Model-picked mappings (accepted in run 1)", "",
             "Mark each as correct or wrong. A compound requirement should not have been mapped.", ""]
    for n, (text, cid) in enumerate(picks, 1):
        flag = " **COMPOUND?**" if looks_compound(text) else ""
        lines += [f"{n}. {text}{flag}", f"   - Picked: {cid}", f"   - Definition: {by_id[cid]['definition']}", ""]
    if not picks:
        lines += ["No model pick was accepted.", ""]
    lines += ["## B. Left provisional or NONE (run 1)", "",
              "Mark any that one of the listed competencies should have covered.", ""]
    for n, text in enumerate(open_, 1):
        near = competency_report.closest(competencies.alias_key(text), index, 0.0)
        closest = f"{near['competency']} ({near['similarity']})" if near else "none"
        lines += [f"{n}. {text}", f"   - Closest: {closest}", ""]
    if not open_:
        lines += ["Nothing stayed provisional.", ""]
    return "\n".join(lines)


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def print_counts(counts: list[dict], stable: dict) -> None:
    for n, c in enumerate(counts, 1):
        print(f"run {n}: {c['requirements']} requirements ({c['failedAds']} ads failed)")
        print("  ids by route:", ", ".join(f"{r} {c['routes'][r]}" for r in ROUTES))
        print("  model picks:", ", ".join(f"{k} {v}" for k, v in c["picks"].items()))
        print(f"  still provisional (including those kept from a previous frame): {c['stillProvisional']}")
    print(f"stability over {stable['paired']} requirements stated in the same words in both runs"
          f" ({stable['unpaired']} stated in only one):")
    print(f"  same id in both runs: {stable['sameId']} ({_pct(stable['sameIdShare'])})")
    print(f"  runs disagree about mapped vs not mapped: {stable['mappedDisagree']} ({_pct(stable['mappedDisagreeShare'])})")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--ads", type=int, default=DEFAULT_ADS, help="ads to sample")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--family", default=None, help="role family (default: the profile's)")
    p.add_argument("--jobs", type=Path, default=enrich_jobs.JOBS_PATH)
    p.add_argument("--yes", action="store_true", help="make the calls; without it only the cost note is printed")
    p.add_argument("--env-file", type=Path, default=None, help="read provider keys from this file (e.g. .env)")
    p.add_argument("--provider", default=None, help="CAREER_OS_LLM_PROVIDER when unset")
    p.add_argument("--model", default=None)
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args(argv)

    family = args.family or enrich_jobs._role_family(enrich_jobs.INTELLIGENCE_PATH)
    comps = competencies.load(family) if family else []
    problems = competencies.validate(comps) if comps else ["no competency list for the role family"]
    if problems:
        print("cannot audit:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    scratch = competency_report.checked_out_path(scratch_dir())
    out = competency_report.checked_out_path(audit_path())

    payload = json.loads(args.jobs.read_text(encoding="utf-8"))
    jobs = payload.get("jobs") if isinstance(payload, dict) else payload
    ads = sample_ads(jobs or [], args.ads, args.seed)
    calls = 2 * len(ads)
    print(f"{len(ads)} ads sampled (seed {args.seed}), family {family}: {calls} extraction calls "
          f"to the configured provider, each with the ad and the {len(comps)}-competency list.")
    if not args.yes:
        print("nothing sent; add --yes to run.")
        return 0
    if not ads:
        print("no already-extracted ads to sample", file=sys.stderr)
        return 1
    if args.env_file:
        load_env_file(args.env_file)

    shutil.rmtree(scratch, ignore_errors=True)
    live_frames = requirement_frames.load()
    runs = [run_once(ads, comps, scratch / f"run{n}", live_frames, args.model, args.provider, args.workers) for n in (1, 2)]
    print_counts([run_counts(r) for r in runs], stability(*runs))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(audit_markdown(runs[0], comps, args.seed), encoding="utf-8")
    print(f"audit file: {out}\nscratch: {scratch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
