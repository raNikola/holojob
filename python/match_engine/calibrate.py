#!/usr/bin/env python3
"""Run the engine over tests/fixtures/postings/ to set its constants (contract, Open points 1).

    .venv/bin/python python/match_engine/calibrate.py --judge --env-file .env
    .venv/bin/python python/match_engine/calibrate.py            # re-score from the cache, no calls

With --judge, each fixture goes through extraction (the ad only) and the
matcher (the ad plus the candidate's redacted evidence index, CLAUDE.md
"Privacy rules and exceptions") on the configured provider. Every model
answer is stored in data/cache/engine-calibration.json, so later runs score
the same answers under the current constants without calling anything.

--snapshot writes what tests/python/test_engine_snapshot.py pins (to
data/engine-snapshot.json, kept on the server like the cache): per
fixture, the verified requirements without any candidate text (no evidence
id, no evidence quote) and the five gate results.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))

import match_engine  # noqa: E402,F401  (puts job_scoring on the path)
from confirmed_facts import load as load_confirmed_facts  # noqa: E402
from enrich_jobs import _fingerprint, extract  # noqa: E402
from evidence_index import build_candidate  # noqa: E402
from job_fingerprint import job_fingerprint  # noqa: E402
import requirement_frames  # noqa: E402
from llm_client import active_provider, judge_model  # noqa: E402

from match_engine.constants import ENGINE_VERSION  # noqa: E402
from match_engine.fit import score  # noqa: E402
from match_engine.gates import gate_results  # noqa: E402
from match_engine.matcher import cache_key, match_posting  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "postings"
CACHE_PATH = ROOT / "data" / "cache" / "engine-calibration.json"
PROFILE_PATH = ROOT / "data" / "profile" / "candidate-profile.json"
INTELLIGENCE_PATH = ROOT / "data" / "intelligence" / "candidate-intelligence.json"
SNAPSHOT_FIELDS = ("id", "provisional", "text", "kind", "importance", "status", "quoteVerified", "strength")


def load_env_file(path: Path) -> None:
    """KEY=VALUE lines into the environment; a variable already set wins."""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _posting(job: dict) -> dict:
    return {
        "id": job["jobId"], "title": job.get("title") or "", "company": job.get("company") or "",
        "location": job.get("location") or "", "description": job.get("description") or "",
        "facts": job.get("llmFacts") or {},
    }


def run(args) -> list[dict]:
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.exists() else {}
    extractions, matches = cache.setdefault("extraction", {}), cache.setdefault("match", {})
    candidate = build_candidate(
        json.loads(PROFILE_PATH.read_text(encoding="utf-8")),
        json.loads(INTELLIGENCE_PATH.read_text(encoding="utf-8")),
        load_confirmed_facts(),
    )
    provider = args.provider or active_provider()
    model = args.model or judge_model(provider)
    frames = requirement_frames.load()
    rows = []
    for path in sorted(FIXTURES.glob("*.json")):
        job = json.loads(path.read_text(encoding="utf-8"))
        facts = extractions.get(path.name)
        if not facts or facts.get("_fingerprint") != _fingerprint(job):
            if not args.judge:
                rows.append({"fixture": path.name, "error": "not extracted yet; run with --judge"})
                continue
            facts = extractions[path.name] = extract(job, None, provider, requirement_frames.previous_for(frames, job))
            requirement_frames.remember(frames, job, facts)
        job["llmFacts"] = facts
        posting = _posting(job)

        key = cache_key(job_fingerprint(posting), candidate["profileVersion"])
        output = matches.get(key)
        if output is None:
            if not args.judge:
                rows.append({"fixture": path.name, "error": "not matched under this profile version; run with --judge"})
                continue
            outcome = match_posting(posting, candidate, confirmed=True, provider=provider, model=model, cache=matches)
            if outcome.output is None:
                rows.append({"fixture": path.name, "error": outcome.error})
                continue
            output = outcome.output
        gates = gate_results(job, candidate, output["gates"], output["requirements"])
        rows.append({"fixture": path.name, "title": job.get("title"), "roleTrack": facts.get("roleTrack"),
                     "requirements": output["requirements"], **score(output["requirements"], gates)})
    if args.judge:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
        requirement_frames.save(frames)
    return rows


def snapshot(rows: list[dict]) -> dict:
    return {
        row["fixture"]: {
            "requirements": [{k: r[k] for k in SNAPSHOT_FIELDS} for r in row["requirements"]],
            "gates": [{"gate": g["gate"], "result": g["result"]} for g in row["gates"]],
            "expected": {k: row[k] for k in ("fit", "confidence", "label", "bucket", "caps")},
        }
        for row in rows if "error" not in row
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--judge", action="store_true",
                   help="call the provider: sends each ad, and with it the redacted evidence index, to it")
    p.add_argument("--env-file", type=Path, default=None, help="read provider keys from this file (e.g. .env)")
    p.add_argument("--provider", default=None, help="HOLOJOB_LLM_PROVIDER when unset")
    p.add_argument("--model", default=None, help="matcher model; <PROVIDER>_JUDGE_MODEL when unset")
    p.add_argument("--snapshot", type=Path, default=None, help="write the test snapshot here")
    p.add_argument("--json", action="store_true", help="print every row as JSON")
    args = p.parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if args.judge:
        provider = args.provider or active_provider()
        print(f"judge: provider={provider} matcher model={args.model or judge_model(provider) or '(default)'}; "
              f"sends {len(list(FIXTURES.glob('*.json')))} ads and the redacted evidence index", file=sys.stderr)

    rows = run(args)
    print(f"engine {ENGINE_VERSION}")
    for row in rows:
        if "error" in row:
            print(f"{row['fixture']:18} ERROR {row['error']}")
            continue
        statuses = " ".join(f"{r['importance'][0]}:{r['status'][:3]}{r['strength']}{'v' if r['quoteVerified'] else ''}"
                            for r in row["requirements"])
        gates = "".join({"pass": "+", "unknown": "?", "fail": "x"}[g["result"]] for g in row["gates"])
        print(f"{row['fixture']:18} fit={row['fit']:3} conf={row['confidence']:.3f} {row['label']:10} "
              f"{row['bucket']:11} gates={gates} caps={','.join(row['caps']) or '-'} track={row['roleTrack']}\n"
              f"{'':18} {statuses}")
    if args.json:
        print(json.dumps([{k: v for k, v in r.items() if k != "requirements"} for r in rows], indent=1, ensure_ascii=False))
    if args.snapshot:
        args.snapshot.write_text(json.dumps(snapshot(rows), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"snapshot: {args.snapshot}")
    return 1 if any("error" in r for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
