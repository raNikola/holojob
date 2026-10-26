"""The engine in shadow mode, next to matchScore in a scoring run (ENGINE_CONTRACT.md section 7).

Off unless HOLOJOB_ENGINE_SHADOW is set (1, true, yes or on). When on,
run_scoring.py hands every scored job to ShadowEngine.apply(), which adds
`engineShadow` (the contract's output, plus where it came from) and changes
nothing else: matchScore, label, priority, sort order and filters are read
from fields this never writes.

Model calls. Extraction (requirements[] with their ids and frames) is
enrich_jobs.py's, already on the job's llmFacts; this adds the matcher, one
call per posting. The matcher sends candidate evidence, so it is asked only
in a judged run (`--judge`, the UI's confirm dialog), at most `limit`
postings per run, the highest matchScore first (section 7). Every other run
re-applies the matcher answers cached in data/cache/engine.json and calls
nothing. Gates, Fit, confidence and label are code, so they are recomputed
from those answers on every run under the current constants.

A failed call leaves the job without a Fit (`engineShadow.error`) and is not
cached; a job without requirements, or a closed one, is not sent.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from job_fingerprint import job_fingerprint
from llm_client import complete_json

from .constants import ENGINE_VERSION
from .fit import score
from .gates import CHEAP_GATES, cheap_gate_failures, gate_results
from .matcher import EVIDENCE_FIELDS, cache_key, match_posting, posting_from_job

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "data" / "cache" / "engine.json"
SHADOW_ENV = "HOLOJOB_ENGINE_SHADOW"
# Section 7: at most 50 postings per run go to the model.
DEFAULT_LIMIT = 50
# What a judged run's confirm dialog lists for the matcher (CLAUDE.md, "Privacy rules and exceptions").
SENT = ["job ad", "its requirements", f"evidence index items ({', '.join(EVIDENCE_FIELDS)}), redacted"]
NEVER_SENT = ["work authorization", "locations", "languages", "salary", "confirmed facts and their notes",
              "name", "contacts", "links"]


def enabled(env=None) -> bool:
    return str((env if env is not None else os.environ).get(SHADOW_ENV) or "").strip().lower() in {
        "1", "true", "yes", "on"}


def _key(job: dict):
    return job.get("jobId") or id(job)


class ShadowEngine:
    """Adds engineShadow to scored jobs; asks the matcher only when `judge` is True."""

    def __init__(self, candidate: dict, *, judge: bool, provider: str, model: str | None,
                 cache_path: Path | None = None, limit: int | None = DEFAULT_LIMIT,
                 complete=complete_json, workers: int = 4, identity: tuple[str, list[str]] | None = None):
        self.candidate = candidate
        # redact.identity_of(profile), for the matcher's redaction; never sent.
        self.identity = identity
        self.judge = judge
        self.provider = provider
        self.model = model
        self.cache_path = cache_path or CACHE_PATH
        self.limit = limit
        self.workers = workers
        self._complete = complete
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = (
            json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.exists() else {})
        self.counts = {"matched": 0, "cached": 0, "uncached": 0, "beyondLimit": 0, "noRequirements": 0,
                       "closed": 0, "failed": 0, "excluded": 0}
        # Ads the cheap gates ruled out of the send, by gate (an ad failing two counts in both).
        self.excluded: dict[str, int] = {g: 0 for g in CHEAP_GATES}
        self._excluded_keys: set = set()

    def _count(self, key: str) -> None:
        with self._lock:
            self.counts[key] += 1

    def _cache_key(self, posting: dict) -> str:
        return cache_key(job_fingerprint(posting), self.candidate["profileVersion"])

    def plan(self, jobs: list[dict]) -> set:
        """The jobs a judged run may send: uncached, with requirements, open, no confirmed fail on a cheap gate, the top `limit` by matchScore."""
        eligible = []
        self.excluded = {g: 0 for g in CHEAP_GATES}
        self._excluded_keys = set()
        for index, job in enumerate(jobs):
            posting = posting_from_job(job)
            if job.get("isClosed") or not posting["facts"].get("requirements"):
                continue
            if self._cache_key(posting) in self._cache:
                continue
            failed = cheap_gate_failures(job, self.candidate)
            if failed:
                # A confirmed fail on a gate decided from the stored ad: not worth a
                # call, and the next ad takes the place. Unknown never gets here.
                self._excluded_keys.add(_key(job))
                for gate in failed:
                    self.excluded[gate] += 1
                continue
            eligible.append((-(job.get("matchScore") or 0), index, _key(job)))
        eligible.sort()
        chosen = eligible if self.limit is None else eligible[: max(0, self.limit)]
        return {key for _, _, key in chosen}

    def _one(self, job: dict, send: set) -> dict | None:
        posting = posting_from_job(job)
        if job.get("isClosed"):
            self._count("closed")
            return None
        if not posting["facts"].get("requirements"):
            self._count("noRequirements")
            return None
        key = self._cache_key(posting)
        with self._lock:
            output = self._cache.get(key)
        from_cache = output is not None
        if output is None:
            if not self.judge:
                self._count("uncached")
                return None
            if _key(job) in self._excluded_keys:
                self._count("excluded")
                return None
            if _key(job) not in send:
                self._count("beyondLimit")
                return None
            outcome = match_posting(posting, self.candidate, confirmed=True, provider=self.provider,
                                    model=self.model, complete=self._complete, identity=self.identity)
            if outcome.output is None:
                print(f"engine (shadow) failed: {(job.get('title') or '?')[:45]}: {outcome.error}",
                      file=sys.stderr)
                self._count("failed")
                return {"engineVersion": ENGINE_VERSION, "error": outcome.error}
            output = outcome.output
            with self._lock:
                self._cache[key] = output
        self._count("cached" if from_cache else "matched")
        gates = gate_results(job, self.candidate, output["gates"], output["requirements"])
        return {
            "engineVersion": ENGINE_VERSION,
            **{k: output[k] for k in ("promptVersion", "profileVersion", "adFingerprint", "cacheKey")},
            "requirements": output["requirements"],
            "cvCoverage": None,
            **score(output["requirements"], gates),
            "warnings": output.get("warnings") or [],
            "provider": output.get("provider"),
            "model": output.get("model"),
            "fromCache": from_cache,
        }

    def apply(self, jobs: list[dict]) -> list[dict]:
        """The same jobs, in the same order, each with engineShadow where there is an output."""
        send = self.plan(jobs) if self.judge else set()
        if self.judge:
            print(f"engine (shadow): excluded before the send by a confirmed gate fail: "
                  + ", ".join(f"{g} {n}" for g, n in self.excluded.items())
                  + f" ({len(self._excluded_keys)} ads)", flush=True)
        with ThreadPoolExecutor(max_workers=max(1, self.workers)) as pool:
            results = list(pool.map(lambda job: self._one(job, send), jobs))
        return [{**job, "engineShadow": shadow} if shadow else job for job, shadow in zip(jobs, results)]

    def preview(self, jobs: list[dict]) -> dict:
        """What a judged run would send for the engine, counted without calling anything."""
        send = self.plan(jobs)
        sendable = [j for j in jobs if not j.get("isClosed") and posting_from_job(j)["facts"].get("requirements")]
        cached = sum(1 for j in sendable if self._cache_key(posting_from_job(j)) in self._cache)
        return {
            "enabled": True,
            "toSend": len(send),
            "cached": cached,
            "beyondLimit": len(sendable) - cached - len(send) - len(self._excluded_keys),
            "excluded": dict(self.excluded),
            "limit": self.limit,
            "sent": SENT,
            "neverSent": NEVER_SENT,
        }

    def save(self) -> None:
        if not self.judge:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self.cache_path.write_text(json.dumps(self._cache, indent=1, ensure_ascii=False), encoding="utf-8")
