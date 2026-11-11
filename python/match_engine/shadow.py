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
from datetime import date
from fractions import Fraction
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from job_fingerprint import job_fingerprint
from competency_mapping import load_remap
import row_state
from llm_client import GuardrailRefused, complete_json
import ai_gate  # noqa: E402 (on the path through llm_client)

from .constants import ENGINE_VERSION
from .evidence_select import mode_of
from .fit import score
from .gates import CHEAP_GATES, PASS, cheap_gate_report, gate_results
from .matcher import EVIDENCE_FIELDS, cache_key, match_posting, overlay_answers, posting_from_job

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "data" / "cache" / "engine.json"
SHADOW_ENV = "HOLOJOB_ENGINE_SHADOW"
# Off by default: per-ad evidence selection (evidence_select.py) changes what the matcher is sent.
SELECT_ENV = "HOLOJOB_ENGINE_EVIDENCE_SELECT"
# Off by default: the evidence index is sent without indentation and empty fields (matcher.compact_evidence).
COMPACT_ENV = "HOLOJOB_ENGINE_COMPACT_EVIDENCE"
# Section 7: at most 50 postings per run go to the model.
DEFAULT_LIMIT = 50
# What a judged run's confirm dialog lists for the matcher (CLAUDE.md, "Privacy rules and exceptions").
SENT = ["job ad", "its requirements", f"evidence index items ({', '.join(EVIDENCE_FIELDS)}), redacted"]
NEVER_SENT = ["work authorization", "locations", "languages", "salary", "confirmed facts and their notes",
              "name", "contacts", "links"]


def enabled(env=None) -> bool:
    source = env if env is not None else os.environ
    value = source.get(SHADOW_ENV)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def select_mode(env=None) -> str | None:
    """None (off, the default), "strict" or "focused" from HOLOJOB_ENGINE_EVIDENCE_SELECT."""
    return mode_of((env if env is not None else os.environ).get(SELECT_ENV))


def compact_enabled(env=None) -> bool:
    return str((env if env is not None else os.environ).get(COMPACT_ENV) or "").strip().lower() in {
        "1", "true", "yes", "on"}


def _key(job: dict):
    return job.get("jobId") or id(job)


def local_score(job: dict) -> int:
    """The Layer 1 score: matchScore before the fit judge's adjustment, whether or not a verdict is applied to it."""
    judged = job.get("llmFit")
    local = judged.get("localScore") if isinstance(judged, dict) else None
    return local if isinstance(local, int) and not isinstance(local, bool) else (job.get("matchScore") or 0)


def _posted(job: dict) -> int:
    """The posting date as a day number, 0 when the board gave none or it cannot be read."""
    try:
        return date.fromisoformat(str(job.get("datePosted") or "")[:10]).toordinal()
    except ValueError:
        return 0


class ShadowEngine:
    """Adds engineShadow to scored jobs; asks the matcher only when `judge` is True."""

    def __init__(self, candidate: dict, *, judge: bool, provider: str, model: str | None,
                 cache_path: Path | None = None, limit: int | None = DEFAULT_LIMIT,
                 complete=complete_json, workers: int = 4, identity: tuple[str, list[str]] | None = None,
                 select=None, compact=None, remap: dict[str, str] | None = None, memory=None):
        self.candidate = candidate
        self.memory = memory
        # redact.identity_of(profile), for the matcher's redaction; never sent.
        self.identity = identity
        self.judge = judge
        self.select = select_mode() if select is None else mode_of(select)
        self.compact = compact_enabled() if compact is None else bool(compact)
        # prov: id -> canonical id (data/requirement-remap.json), applied to every ad's requirements when read.
        self.remap = load_remap() if remap is None else remap
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
                       "closed": 0, "failed": 0, "excluded": 0, "refused": 0, "notActive": 0}
        # The AI budget gate refused a call: the rest of the run makes none (ai_gate.py).
        self.refusal: str | None = None
        # Ads the cheap gates ruled out of the send, by gate (an ad failing two counts in both).
        self.excluded: dict[str, int] = {g: 0 for g in CHEAP_GATES}
        self._excluded_keys: set = set()

    def _count(self, key: str) -> None:
        with self._lock:
            self.counts[key] += 1

    def _posting(self, job: dict) -> dict:
        return posting_from_job(job, self.remap)

    def _cache_key(self, posting: dict) -> str:
        return cache_key(job_fingerprint(posting), self.candidate["evidenceVersion"], self.select,
                         posting["facts"].get("requirements"))

    def plan(self, jobs: list[dict]) -> set:
        """The jobs a judged run may send: uncached, with requirements, open, no confirmed fail on a cheap gate, the top `limit`.

        Ranked on the local (Layer 1) score, never on a fit-judge adjustment; equal scores are
        ordered by relevance, not by position in the list: a passed location gate before an
        unknown one, then the smaller share of provisional requirements, then the newer posting, then the fingerprint.
        """
        eligible = []
        self.excluded = {g: 0 for g in CHEAP_GATES}
        self._excluded_keys = set()
        for job in jobs:
            posting = self._posting(job)
            if job.get("isClosed") or row_state.not_found(job) or not posting["facts"].get("requirements"):
                continue
            if self._cache_key(posting) in self._cache:
                continue
            failed, location = cheap_gate_report(job, self.candidate)
            if failed:
                # A confirmed fail on a gate decided from the stored ad: not worth a
                # call, and the next ad takes the place. Unknown never gets here.
                self._excluded_keys.add(_key(job))
                for gate in failed:
                    self.excluded[gate] += 1
                continue
            # Only an order among equal scores: nothing here changes a score or costs an ad anything.
            requirements = posting["facts"]["requirements"]
            ratio = Fraction(sum(1 for r in requirements if r.get("provisional")), len(requirements))
            eligible.append((-local_score(job), location != PASS, ratio, -_posted(job),
                             job_fingerprint(posting), str(_key(job)), _key(job)))
        eligible.sort()
        chosen = eligible if self.limit is None else eligible[: max(0, self.limit)]
        return {row[-1] for row in chosen}

    def _one(self, job: dict, send: set) -> dict | None:
        posting = self._posting(job)
        if job.get("isClosed"):
            self._count("closed")
            return None
        if not posting["facts"].get("requirements"):
            self._count("noRequirements")
            return None
        key = self._cache_key(posting)
        with self._lock:
            raw = self._cache.get(key)
        from_cache = raw is not None
        if raw is None:
            if not self.judge:
                self._count("uncached")
                return None
            if row_state.not_found(job):
                self._count("notActive")
                return None
            if _key(job) in self._excluded_keys:
                self._count("excluded")
                return None
            if _key(job) not in send:
                self._count("beyondLimit")
                return None
            if self.refusal:
                self._count("refused")
                return None
            fresh: dict[str, dict] = {}
            try:
                outcome = match_posting(posting, self.candidate, confirmed=True, provider=self.provider,
                                        model=self.model, complete=self._complete, cache=fresh, identity=self.identity,
                                        select=self.select, compact=self.compact)
            except GuardrailRefused as exc:
                with self._lock:
                    if self.refusal is None:
                        self.refusal = exc.reason
                        print(f"engine (shadow) stopped by the AI gate: {exc.reason}", file=sys.stderr, flush=True)
                self._count("refused")
                return None
            if outcome.output is None:
                print(f"engine (shadow) failed: {(job.get('title') or '?')[:45]}: {outcome.error}",
                      file=sys.stderr)
                self._count("failed")
                return {"engineVersion": ENGINE_VERSION, "error": outcome.error}
            raw = fresh[key]
            with self._lock:
                self._cache[key] = raw
        output = overlay_answers(raw, self.candidate)
        if self.memory is not None:
            with self._lock:
                self.memory.observe(posting, output)
        self._count("cached" if from_cache else "matched")
        if from_cache and self.judge:
            ai_gate.record_cache_hit(self.provider, self.model, feature="evidence-matcher", job_id=_key(job))
        gates = gate_results(job, self.candidate, output["gates"], output["requirements"])
        return {
            "engineVersion": ENGINE_VERSION,
            **{k: output[k] for k in ("promptVersion", "profileVersion", "evidenceVersion", "answersVersion",
                                      "adFingerprint", "cacheKey")},
            "requirements": output["requirements"],
            "cvCoverage": None,
            **score(output["requirements"], gates),
            "warnings": output.get("warnings") or [],
            "provider": output.get("provider"),
            "model": output.get("model"),
            "fromCache": from_cache,
            **({"staleReason": output["staleReason"]} if output.get("staleReason") else {}),
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
        sendable = [j for j in jobs if not j.get("isClosed") and not row_state.not_found(j) and self._posting(j)["facts"].get("requirements")]
        cached = sum(1 for j in sendable if self._cache_key(self._posting(j)) in self._cache)
        # Cached answers whose language list changed since: counted locally, nothing is re-sent for them.
        stale = sum(1 for j in sendable
                    if (raw := self._cache.get(self._cache_key(self._posting(j)))) is not None
                    and overlay_answers(raw, self.candidate).get("staleReason") == "languages")
        return {
            "enabled": True,
            "toSend": len(send),
            "staleLanguages": stale,
            "cached": cached,
            "beyondLimit": len(sendable) - cached - len(send) - len(self._excluded_keys),
            "excluded": dict(self.excluded),
            "limit": self.limit,
            "sent": SENT,
            "neverSent": NEVER_SENT,
        }

    def save(self) -> None:
        if self.memory is not None:
            self.memory.save()
        if not self.judge:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self.cache_path.write_text(json.dumps(self._cache, indent=1, ensure_ascii=False), encoding="utf-8")
