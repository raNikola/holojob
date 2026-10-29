#!/usr/bin/env python3
"""Run the engine 3 times over tests/fixtures/postings/ and report the drift (ROADMAP.md Phase 1, Stability).

    .venv/bin/python python/match_engine/stability.py --judge --env-file .env
    .venv/bin/python python/match_engine/stability.py            # report from the cache, no calls

Each run reads every fixture afresh: extraction (the ad only) and the
matcher (the ad plus the candidate's redacted evidence index, CLAUDE.md
"Privacy rules and exceptions") on the configured provider, then Fit and
gates in code. With --matcher-only the three runs share the extraction
calibrate.py cached, so only the matcher's drift is measured.

A fixture's runs go in order, and each extraction gets the previous run's
requirement frame (requirement_frames.py), as a repeated app run gets the
last one: run 1 reads the ad cold, runs 2 and 3 are asked to keep its ids.
The frames live in the stability cache, not in data/cache/requirement-frames.json,
so a test run neither reads nor changes the app's.

Every run's raw answers are stored in data/cache/engine-stability.json as
they arrive. A later --judge run fills only what is missing (a failed or
interrupted call), so it never repeats a call that succeeded; --fresh
discards the stored runs of the chosen mode first.

Reported per fixture and overall, as ROADMAP.md defines them:
  overlap  share of requirement ids present in all runs (of all ids seen)
  flips    share of those shared requirements whose status differs between runs
  spread   max minus min Fit
No tolerance is asserted here; the thresholds are printed for comparison.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))

from match_engine.calibrate import (  # noqa: E402
    CACHE_PATH as CALIBRATION_CACHE,
    FIXTURES,
    INTELLIGENCE_PATH,
    PROFILE_PATH,
    load_env_file,
)
from confirmed_facts import load as load_confirmed_facts  # noqa: E402
from enrich_jobs import _fingerprint, extract  # noqa: E402
from evidence_index import build_candidate  # noqa: E402
from redact import identity_of  # noqa: E402
import requirement_frames  # noqa: E402
import llm_client  # noqa: E402
from llm_client import active_provider, judge_model  # noqa: E402

from match_engine.constants import ENGINE_VERSION  # noqa: E402
from match_engine.fit import score  # noqa: E402
from match_engine.gates import gate_results  # noqa: E402
from match_engine.matcher import match_posting, posting_from_job  # noqa: E402

CACHE_PATH = ROOT / "data" / "cache" / "engine-stability.json"
RUNS = 3
# ROADMAP.md, Phase 1 acceptance: Stability.
MIN_OVERLAP = Fraction(9, 10)
MAX_FLIPS = Fraction(1, 20)
MAX_SPREAD = 5


# --- the metrics ---------------------------------------------------------------------

def keyed(requirements: list[dict]) -> dict[str, dict]:
    """Requirements by id; a repeated id in one run gets #2, #3 so neither hides the other."""
    out = {}
    for req in requirements:
        key, n = req["id"], 1
        while key in out:
            n += 1
            key = f"{req['id']}#{n}"
        out[key] = req
    return out


def drift(runs: list[dict]) -> dict:
    """Overlap, flips and spread over the scored runs of one fixture.

    Each run is {"requirements": [...], "fit": int, "label": str, "bucket": str}.
    """
    by_run = [keyed(r["requirements"]) for r in runs]
    seen = set().union(*by_run) if by_run else set()
    shared = set.intersection(*(set(k) for k in by_run)) if by_run else set()
    flipped = []
    for rid in sorted(shared):
        values = [(k[rid]["status"], k[rid]["strength"]) for k in by_run]
        if len({status for status, _ in values}) > 1:
            flipped.append({"id": rid, "text": by_run[0][rid].get("text"), "values": values})
    partial = [
        {"id": rid, "text": next(k[rid] for k in by_run if rid in k).get("text"),
         "runs": [i + 1 for i, k in enumerate(by_run) if rid in k]}
        for rid in sorted(seen - shared)
    ]
    fits = [r["fit"] for r in runs]
    return {
        "seen": len(seen), "shared": len(shared), "flipped": flipped, "notInAll": partial,
        "overlap": Fraction(len(shared), len(seen)) if seen else None,
        "flips": Fraction(len(flipped), len(shared)) if shared else None,
        "spread": max(fits) - min(fits) if fits else None,
    }


def overall(per_fixture: list[dict]) -> dict:
    seen = sum(d["seen"] for d in per_fixture)
    shared = sum(d["shared"] for d in per_fixture)
    flipped = sum(len(d["flipped"]) for d in per_fixture)
    spreads = [d["spread"] for d in per_fixture if d["spread"] is not None]
    return {
        "overlap": Fraction(shared, seen) if seen else None,
        "flips": Fraction(flipped, shared) if shared else None,
        "spread": max(spreads) if spreads else None,
    }


# --- the runs ------------------------------------------------------------------------

def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def run(args) -> tuple[dict, dict]:
    """Fill the stored runs (with --judge) and return them with the candidate."""
    mode = "matcher-only" if args.matcher_only else "full"
    store = _load(CACHE_PATH)
    runs = store.setdefault(mode, [])
    frames = store.setdefault("frames", {}).setdefault(mode, {})
    if args.fresh and args.judge:
        runs.clear()
        frames.clear()
    while len(runs) < RUNS:
        runs.append({})
    profile = _load(PROFILE_PATH)
    candidate = build_candidate(profile, _load(INTELLIGENCE_PATH), load_confirmed_facts())
    identity = identity_of(profile)
    shared_extraction = _load(CALIBRATION_CACHE).get("extraction", {}) if args.matcher_only else {}
    provider = args.provider or active_provider()
    model = args.model or judge_model(provider)
    jobs = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(FIXTURES.glob("*.json"))}

    lock = threading.Lock()

    def save():
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(store, indent=1, ensure_ascii=False), encoding="utf-8")

    def one(index: int, name: str):
        job = jobs[name]
        entry = runs[index].get(name)
        if entry and "match" in entry:
            return
        facts = None
        try:
            if args.matcher_only:
                facts = shared_extraction.get(name)
                if not facts or facts.get("_fingerprint") != _fingerprint(job):
                    raise RuntimeError("no cached extraction; run calibrate.py --judge first")
            else:
                facts = (entry or {}).get("extraction")
                if not facts:
                    facts = extract(job, None, provider, requirement_frames.previous_for(frames, job))
                    with lock:
                        requirement_frames.remember(frames, job, facts)
            # A fresh cache per call: each run asks the matcher again.
            outcome = match_posting(posting_from_job({**job, "llmFacts": facts}), candidate,
                                    confirmed=True, provider=provider, model=model, cache=None, identity=identity)
            result = {"extraction": facts}
            if outcome.output is None:  # kept with its extraction; the matcher is retried next time
                result["error"] = outcome.error
            else:
                result["match"] = outcome.output
        except Exception as exc:  # recorded and retried next time, never fatal to the other calls
            # The extraction is kept when only the matcher failed, so a retry does not repeat it.
            result = {**({"extraction": facts} if facts else {}), "error": str(exc)}
        with lock:
            runs[index][name] = result
            save()
        print(f"run {index + 1} {name}: {'ERROR ' + result['error'] if 'error' in result else 'ok'}",
              file=sys.stderr, flush=True)

    if args.judge:
        todo = [(i, n) for i in range(RUNS) for n in jobs if "match" not in (runs[i].get(n) or {})]

        def fixture(name: str):
            for i, n in todo:  # in run order: run 2 extracts with run 1's frame
                if n == name:
                    one(i, n)
        print(f"judge: provider={provider} matcher model={model or '(default)'} mode={mode}; "
              f"{len(todo)} fixture runs to call ({'matcher' if args.matcher_only else 'extraction + matcher'} each), "
              f"each sends the ad and the redacted evidence index", file=sys.stderr, flush=True)
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            list(pool.map(fixture, sorted({n for _, n in todo})))
    return {"mode": mode, "runs": runs, "jobs": jobs}, candidate


def scored(state: dict, candidate: dict) -> dict[str, list[dict]]:
    """Per fixture, each run's requirements, Fit, label and bucket, or its error."""
    out = {}
    for name, job in state["jobs"].items():
        rows = []
        for run_entry in state["runs"]:
            entry = run_entry.get(name) or {"error": "not run yet; run with --judge"}
            if "match" not in entry:
                rows.append({"error": entry.get("error") or "no output"})
                continue
            output = entry["match"]
            gates = gate_results({**job, "llmFacts": entry["extraction"]}, candidate, output["gates"],
                                 output["requirements"])
            result = score(output["requirements"], gates)
            rows.append({"requirements": output["requirements"], "profileVersion": output["profileVersion"],
                         **{k: result[k] for k in ("fit", "confidence", "label", "bucket", "caps")}})
        out[name] = rows
    return out


# --- the report ----------------------------------------------------------------------

def _pct(value) -> str:
    return "  -  " if value is None else f"{float(value) * 100:5.1f}%"


def report(state: dict, results: dict[str, list[dict]]) -> int:
    print(f"engine {ENGINE_VERSION}, mode {state['mode']}, {RUNS} runs")
    versions = {r["profileVersion"] for rows in results.values() for r in rows if "error" not in r}
    if len(versions) > 1:
        print(f"WARNING: runs under {len(versions)} profile versions; the profile changed between runs")
    print(f"\n{'fixture':18} " + " ".join(f"{'run ' + str(i + 1):26}" for i in range(RUNS))
          + f" {'overlap':>7} {'flips':>7} {'spread':>6}")
    per_fixture, details, incomplete = [], [], False
    for name, rows in results.items():
        cells = []
        for r in rows:
            cells.append(f"{'ERROR':26}" if "error" in r else f"{r['fit']:3} {r['label']:10} {r['bucket']:11}")
        ok = [r for r in rows if "error" not in r]
        if len(ok) < RUNS:
            incomplete = True
            print(f"{name:18} " + " ".join(cells))
            for i, r in enumerate(rows):
                if "error" in r:
                    print(f"{'':18} run {i + 1}: {r['error']}")
            continue
        d = drift(ok)
        per_fixture.append(d)
        details.append((name, d))
        print(f"{name:18} " + " ".join(cells) + f" {_pct(d['overlap'])} {_pct(d['flips'])} {d['spread']:6}")

    if per_fixture:
        o = overall(per_fixture)
        print(f"\noverall over {len(per_fixture)} fixtures: overlap {_pct(o['overlap']).strip()} "
              f"(target >= {_pct(MIN_OVERLAP).strip()}), flips {_pct(o['flips']).strip()} "
              f"(target <= {_pct(MAX_FLIPS).strip()}), max spread {o['spread']} (target <= {MAX_SPREAD})")

    print("\nstatus flips (status, strength per run):")
    any_flip = False
    for name, d in details:
        for f in d["flipped"]:
            any_flip = True
            values = "  ".join(f"{s}{n}" for s, n in f["values"])
            print(f"  {name:18} {f['id']:34} {values}   {(f['text'] or '')[:70]}")
    if not any_flip:
        print("  none")

    print("\nrequirement ids not in every run (extraction drift):")
    any_partial = False
    for name, d in details:
        for p in d["notInAll"]:
            any_partial = True
            print(f"  {name:18} runs {','.join(map(str, p['runs'])):5} {p['id']:34} {(p['text'] or '')[:70]}")
    if not any_partial:
        print("  none")
    return 1 if incomplete else 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--judge", action="store_true",
                   help="call the provider: sends each ad, and with it the redacted evidence index, to it")
    p.add_argument("--env-file", type=Path, default=None, help="read provider keys from this file (e.g. .env)")
    p.add_argument("--provider", default=None, help="the provider selected in Settings when unset")
    p.add_argument("--model", default=None, help="matcher model; <PROVIDER>_JUDGE_MODEL when unset")
    p.add_argument("--matcher-only", action="store_true",
                   help="reuse calibrate.py's cached extraction in all runs; measures the matcher alone")
    p.add_argument("--fresh", action="store_true", help="with --judge: discard this mode's stored runs first")
    p.add_argument("--workers", type=int, default=4, help="fixtures run in parallel (each one's runs in order)")
    args = p.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    state, candidate = run(args)
    code = report(state, scored(state, candidate))
    if llm_client._REJECTED:
        dropped = ", ".join(f"{model} {setting}" for _, model, setting in sorted(llm_client._REJECTED))
        print(f"\nmodel settings the provider rejected, so left out of this run's calls: {dropped}")
    return code


if __name__ == "__main__":
    sys.exit(main())
