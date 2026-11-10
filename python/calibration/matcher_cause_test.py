#!/usr/bin/env python3
"""P1 Stage B, matcher stability slice 1: why do verdicts change? The CURRENT matcher prompt on 12 dev ads, in five arms.

    python python/calibration/matcher_cause_test.py estimate    # builds and scans every request, sends nothing
    python python/calibration/matcher_cause_test.py run --yes   # PAID; only after the owner's explicit approval; hard maximum $0.20
    python python/calibration/matcher_cause_test.py analyse     # free: reads the stored results

Arms, all on the existing 83-item evidence index and the unchanged matcher (`matcher.match_posting`):
  full_1, full_2   the whole question set, the same input twice (pure repeat noise)
  shuffled         the same requirements and evidence in a seeded random order
  batched          the same requirements in calls of at most 6, in their original order
  medium           as full_1 with reasoning effort medium instead of the stored setting

Only ads of the dev split are used; the test split stays untouched. production_like and diagnostic are never pooled.
Every request is scanned for the owner's identifiers (fail closed) in the dry run and again before it leaves. Each call is checked
against the cap at its true worst case (input at 3 characters per token, the full output limit), on top of what the ledger shows was
really spent in this batch and what is still in flight; a matcher retry is a call like any other. Results go to matcher-cause-test.json,
after every call. Prints counts and rates only, never ad, profile or CV text.

READ WITH EVERY NUMBER: 12 ads, chosen for having the most labelled lines, and one labeller. Verdicts on one ad are not independent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("cv_analysis", "llm", "job_scoring"):
    if str(ROOT / "python" / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / "python" / _sub))
if str(ROOT / "python") not in sys.path:
    sys.path.append(str(ROOT / "python"))

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic  # noqa: E402
import ai_gate  # noqa: E402
import ai_selection  # noqa: E402
from competency_mapping import load_remap  # noqa: E402
from confirmed_facts import load as load_confirmed_facts  # noqa: E402
from evidence_index import build_candidate  # noqa: E402
from llm_client import GuardrailRefused, LlmUnavailable, complete_json, preflight, service_tier_for  # noqa: E402
from match_engine import matcher  # noqa: E402
from redact import identity_of  # noqa: E402
from calibration.engine_sample import alias_unsafe_ids, sanitized  # noqa: E402
from calibration.eval_set import CAVEAT, STAGE_DIR, load as load_frozen  # noqa: E402
from calibration.must_report import VERDICT_AS_MEETS, wilson  # noqa: E402
from calibration.prelabel import owner_leaks  # noqa: E402

PROFILE_PATH = ROOT / "data" / "profile" / "candidate-profile.json"
INTELLIGENCE_PATH = ROOT / "data" / "intelligence" / "candidate-intelligence.json"
RESULTS_NAME = "matcher-cause-test.json"
FEATURE = "evidence-matcher"
ARMS = ("full_1", "full_2", "shuffled", "batched", "medium")
MODES = ("production_like", "diagnostic")
SEED = 17
ADS_PER_MODE = 6
BATCH_SIZE = 6
MEDIUM_EFFORT = "medium"
HARD_STOP_USD = 0.20  # the owner's cap for this one batch
UPPER_CHARS_PER_TOKEN = 3.0  # over-counts on purpose
MEASURED_CHARS_PER_TOKEN = 3.49  # Step 7: 388,434 tokens at 3.0 against 333,522 measured
OUTPUT_PER_REQUIREMENT, OUTPUT_BASE = 80, 16  # the measured upper envelope of 41 full-set matcher calls
MEDIUM_OUTPUT_FACTOR = 3  # an assumption: no medium-effort call has been measured
LEVEL = {"MISSING": 0, "UNKNOWN": 0, "PARTIAL": 1, "MET": 2}  # silence and absence rank together
TARGET = {"yes": 2, "partial": 1, "no": 0}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(*parts) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def select_ads(frozen: dict, ads: dict, seed: int = SEED) -> dict[str, str]:
    """{jobId: mode}: per mode, the dev ads with the most labelled real musts, then the most "no" lines, then a seeded order."""
    real, no = Counter(), Counter()
    for line in frozen["lines"].values():
        if line["split"] == "dev" and not line["probe"] and line["first"]["isMust"] == "yes":
            real[line["jobId"]] += 1
            no[line["jobId"]] += line["first"]["meets"] == "no"
    chosen = {}
    for mode in MODES:
        ids = [j for j, e in ads.items() if e["mode"] == mode and (frozen["ads"].get(j) or {}).get("split") == "dev" and e["output"]["requirements"]]
        ids.sort(key=lambda j: (-real[j], -no[j], _hash(seed, j)))
        chosen.update({j: mode for j in ids[:ADS_PER_MODE]})
    return chosen


class _Captured(LlmUnavailable):
    pass


def _asked(prompt: str) -> int:
    return prompt.split("=== BEGIN REQUIREMENTS ===")[1].split("=== END REQUIREMENTS ===")[0].count('"ref"')


def _shuffled(items: list, seed_parts: tuple) -> list:
    out = list(items)
    random.Random(_hash(*seed_parts)).shuffle(out)
    return out


def build_calls(out: Path, profile: dict, intelligence: dict, chosen: dict[str, str]) -> dict:
    """Every request of every arm, built exactly as the matcher builds it. Nothing is sent."""
    ads = {i["jobId"]: i for i in _load(out / "review-items.json")["items"]}
    facts = _load(out / "enrichment-facts.json")["facts"]
    remap = load_remap(out / "requirement-remap.json")
    candidate, aliases = alias_unsafe_ids(build_candidate(profile, intelligence, load_confirmed_facts()), profile)
    identity = identity_of(profile)
    calls = []

    def add(arm: str, job_id: str, chunk: int, posting: dict, cand: dict) -> None:
        captured = []

        def capture(prompt, schema=None, model=None, provider=None):
            captured.append(prompt)
            raise _Captured("dry run")

        matcher.match_posting(posting, cand, confirmed=True, provider="openai", model=None, complete=capture, identity=identity)
        calls.append({"key": f"{arm}|{job_id}|{chunk}", "arm": arm, "jobId": job_id, "chunk": chunk, "posting": posting, "candidate": cand,
                      "prompt": captured[0], "asked": _asked(captured[0]), "hash": _hash(captured[0])})

    for job_id in chosen:
        job = {**sanitized(ads[job_id]), "llmFacts": facts[job_id]}
        posting = matcher.posting_from_job(job, remap)
        requirements = posting["facts"]["requirements"]
        with_reqs = lambda reqs: {**posting, "facts": {**posting["facts"], "requirements": reqs}}
        for arm in ("full_1", "full_2", "medium"):
            add(arm, job_id, 0, posting, candidate)
        reordered = {**candidate, "evidence": _shuffled(candidate["evidence"], (SEED, job_id, "evidence"))}
        add("shuffled", job_id, 0, with_reqs(_shuffled(requirements, (SEED, job_id, "requirements"))), reordered)
        for chunk, start in enumerate(range(0, len(requirements), BATCH_SIZE)):
            add("batched", job_id, chunk, with_reqs(requirements[start:start + BATCH_SIZE]), candidate)
    leaks = {c["key"]: kinds for c in calls if (kinds := owner_leaks(c["prompt"], profile))}
    return {"calls": calls, "leaks": leaks, "evidenceItems": len(candidate["evidence"]), "idAliases": len(aliases), "identity": identity}


def _price() -> dict:
    selection = ai_selection.require()
    provider, model = selection["provider"], selection["model"]
    price = ai_gate.classify(provider, model, selection.get("baseUrl") or None, tier=service_tier_for(provider))
    return {"provider": provider, "model": model, "tier": price.get("tier"), "known": bool(price.get("priceKnown")),
            "in": price.get("inputPerMTok"), "out": price.get("outputPerMTok")}


def _output_estimate(call: dict) -> int:
    tokens = OUTPUT_BASE + OUTPUT_PER_REQUIREMENT * call["asked"]
    return tokens * MEDIUM_OUTPUT_FACTOR if call["arm"] == "medium" else tokens


def estimate(calls: list[dict], price: dict) -> dict:
    """Per arm and in total: `expected` uses the measured characters per token, `upperBound` the deliberately low 3.0."""
    rows = {}
    for arm in ARMS:
        subset = [c for c in calls if c["arm"] == arm]
        chars = sum(len(c["prompt"]) for c in subset)
        out_tokens = sum(_output_estimate(c) for c in subset)
        rows[arm] = {"calls": len(subset), "inputUpper": round(chars / UPPER_CHARS_PER_TOKEN), "inputExpected": round(chars / MEASURED_CHARS_PER_TOKEN), "output": out_tokens}
    usd = lambda key: round((sum(r[key] for r in rows.values()) * price["in"] + sum(r["output"] for r in rows.values()) * price["out"]) / 1e6, 4)
    return {"arms": rows, "calls": len(calls), "upperBound": usd("inputUpper") if price["known"] else None, "expected": usd("inputExpected") if price["known"] else None}


def budget() -> dict:
    settings = ai_gate.load_settings()
    t = ai_gate.totals(None, settings)
    cap = ai_gate._call_cap(settings.get("maxCallsDaily"))
    return {"dailyLeft": round(float(settings["dailyLimit"]) - t["today"]["cost"], 4), "monthlyLeft": round(float(settings["monthlyLimit"]) - t["thisMonth"]["cost"], 4),
            "callsLeftToday": None if cap is None else cap - t["today"]["paidCalls"]}


def render_estimate(built: dict, chosen: dict, est: dict, price: dict, left: dict) -> list[str]:
    calls = built["calls"]
    lines = [f"NOT SENT: dry run. ads: {len(chosen)} ({dict(Counter(chosen.values()))}), dev split only; evidence items per call {built['evidenceItems']} ({built['idAliases']} hash ids aliased for the scan)",
             f"model: {price['provider']}/{price['model']} ({price['tier']}); prompt: the existing matcher prompt, unchanged"]
    for arm, r in est["arms"].items():
        lines.append(f"  {arm:9} calls {r['calls']:3}  input about {r['inputExpected']} (upper bound {r['inputUpper']})  output reserved {r['output']}")
    lines.append(f"output is the measured envelope {OUTPUT_BASE} + {OUTPUT_PER_REQUIREMENT} per requirement; the medium arm is assumed at {MEDIUM_OUTPUT_FACTOR}x, no medium call has been measured")
    if est["upperBound"] is None:
        lines.append("estimated cost: unknown (no price for this model)")
    else:
        lines.append(f"estimated cost: ${est['expected']:.4f} expected, ${est['upperBound']:.4f} upper bound, for {est['calls']} calls at ${price['in']}/{price['out']} per 1M tokens, no cache discount; "
                     f"hard maximum ${HARD_STOP_USD:.2f}: {'WITHIN' if est['upperBound'] <= HARD_STOP_USD else 'OVER, stop and ask'}")
    lines.append(f"budget: daily left ${left['dailyLeft']}, monthly left ${left['monthlyLeft']}, paid calls left today {'no limit set' if left['callsLeftToday'] is None else left['callsLeftToday']}")
    lines.append(f"privacy scan: {len(calls) - len(built['leaks'])} of {len(calls)} requests pass" + ("" if not built["leaks"] else "; FAILED kinds: " + "; ".join(sorted({k for ks in built["leaks"].values() for k in ks}))))
    return lines


class ResultStore:
    """matcher-cause-test.json: one entry per call, written atomically after each. The batch start stays, so a resumed run counts earlier spend."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data = {"version": 1, "batchStartedAt": None, "ads": {}, "calls": {}}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("calls"), dict):
                self.data = loaded

    def _write(self) -> None:
        make_private_dirs(self.path.parent)
        write_text_atomic(self.path, json.dumps(self.data, indent=1, ensure_ascii=False), PRIVATE_FILE_MODE)

    def start(self, chosen: dict) -> datetime:
        with self._lock:
            if not self.data["batchStartedAt"]:
                self.data["batchStartedAt"] = _now().isoformat()
            self.data["ads"] = chosen
            self._write()
            return datetime.fromisoformat(self.data["batchStartedAt"])

    def done(self, call: dict) -> bool:
        return (self.data["calls"].get(call["key"]) or {}).get("hash") == call["hash"]

    def put(self, call: dict, requirements: list[dict]) -> None:
        kept = [{k: r.get(k) for k in ("id", "status", "strength", "quoteVerified", "evidenceId")} for r in requirements]
        with self._lock:
            self.data["calls"][call["key"]] = {"arm": call["arm"], "jobId": call["jobId"], "chunk": call["chunk"], "hash": call["hash"], "at": _now().isoformat(), "requirements": kept}
            self._write()


class SpendGuard:
    """Refuses a call unless real spend in this batch, plus every call in flight, plus this call at its true worst case fits under the cap."""

    def __init__(self, cap: float, started_at: datetime, price: dict, max_output_tokens: int):
        self.cap, self.started_at, self.price, self.max_output = cap, started_at, price, max_output_tokens
        self.process_started = _now()
        self.in_flight, self.calls, self._lock = 0.0, 0, threading.Lock()

    def worst(self, prompt: str) -> float:
        return (len(prompt) / UPPER_CHARS_PER_TOKEN * self.price["in"] + self.max_output * self.price["out"]) / 1e6

    def actual(self) -> float:
        """Billed cost of this batch's finished calls, from the ledger; a call an earlier process never finished counts at its estimate."""
        rows = ai_gate.read_ledger()
        results = {r.get("id"): r for r in rows if r.get("type") == "result"}
        total = 0.0
        for row in rows:
            if row.get("type") != "call" or row.get("feature") != FEATURE or row.get("decision") != "allowed":
                continue
            when = datetime.fromisoformat(row["ts"])
            if when < self.started_at:
                continue
            result = results.get(row.get("id"))
            if result:
                total += float(result.get("cost") or 0)
            elif when < self.process_started:
                total += float(row.get("cost") or 0)
        return total

    def reserve(self, prompt: str) -> float:
        worst = self.worst(prompt)
        with self._lock:
            if self.actual() + self.in_flight + worst > self.cap:
                raise GuardrailRefused(f"the next call could pass the ${self.cap:.2f} cap")
            self.in_flight += worst
            self.calls += 1
        return worst

    def release(self, worst: float) -> None:
        with self._lock:
            self.in_flight -= worst


class _MediumEffort:
    """For the medium arm only: the supported selection file, copied to a private temp directory with one setting changed."""

    def __enter__(self):
        self.previous = os.environ.get("HOLOJOB_AI_SELECTION")
        doc = json.loads(ai_selection.selection_path().read_text(encoding="utf-8"))
        self.directory = tempfile.mkdtemp(prefix="holojob-effort-")
        path = Path(self.directory) / "ai-settings.json"
        write_text_atomic(path, json.dumps({**doc, "reasoningEffort": MEDIUM_EFFORT}), PRIVATE_FILE_MODE)
        os.environ["HOLOJOB_AI_SELECTION"] = str(path)
        return self

    def __exit__(self, *exc):
        if self.previous is None:
            os.environ.pop("HOLOJOB_AI_SELECTION", None)
        else:
            os.environ["HOLOJOB_AI_SELECTION"] = self.previous
        shutil.rmtree(self.directory, ignore_errors=True)


def run(out: Path, profile: dict, intelligence: dict, frozen: dict, workers: int = 4, complete=complete_json) -> dict:
    """The approved batch. Stops before any call on a scan hit or an estimate over the cap, and during it on a refusal, a scan hit or an error."""
    chosen = select_ads(frozen, _load(out / "engine-shadow.json")["ads"])
    built = build_calls(out, profile, intelligence, chosen)
    if built["leaks"]:
        return {"stopped": "privacy scan found owner identifiers; nothing was sent", "asked": 0}
    price = _price()
    est = estimate(built["calls"], price)
    if est["upperBound"] is None:
        return {"stopped": "no price for this model; nothing was sent", "asked": 0}
    if est["upperBound"] > HARD_STOP_USD:
        return {"stopped": f"estimate ${est['upperBound']:.4f} is over the hard maximum ${HARD_STOP_USD:.2f}; nothing was sent", "asked": 0}
    store = ResultStore(out / RESULTS_NAME)
    work = [c for c in built["calls"] if not store.done(c)]
    if not work:
        return {"stopped": None, "asked": 0, "ok": 0, "failed": 0, "refused": 0, "modelCalls": 0, "retries": 0}
    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    with ai_gate.context(feature=FEATURE):
        decision = preflight(max(len(c["prompt"]) for c in work), price["provider"], price["model"])
    if not decision.allowed:
        ai_gate.record_refused(decision, skipped=len(work))
        return {"stopped": f"AI gate refused: {decision.reason}", "asked": 0}
    guard = SpendGuard(HARD_STOP_USD, store.start(chosen), price, ai_selection.REASONING_MIN_COMPLETION_TOKENS)
    stop = threading.Event()
    counts = {"ok": 0, "failed": 0, "refused": 0}
    reason = {"text": None}

    def halt(text: str) -> None:
        reason["text"] = reason["text"] or text
        stop.set()

    def one(call: dict) -> str:
        if stop.is_set():
            return "refused"

        def guarded(prompt, schema=None, model=None, provider=None):
            if owner_leaks(prompt, profile):  # again, on the exact text about to leave
                raise GuardrailRefused("privacy scan hit on an outgoing request")
            worst = guard.reserve(prompt)
            try:
                return complete(prompt, schema=schema, model=model, provider=provider)
            finally:
                guard.release(worst)

        try:
            outcome = matcher.match_posting(call["posting"], call["candidate"], confirmed=True, provider=price["provider"], model=price["model"],
                                            complete=guarded, identity=built["identity"])
        except GuardrailRefused as exc:
            halt(str(exc) or "AI gate refused a call")
            return "refused"
        if outcome.output is None:
            halt("a call failed: no engine output for it")
            return "failed"
        store.put(call, outcome.output["requirements"])
        return "ok"

    def run_arm(subset: list[dict]) -> None:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for future in as_completed([pool.submit(one, c) for c in subset]):
                counts[future.result()] += 1

    for arm in ARMS:  # one arm at a time: the medium arm changes a process-wide setting
        subset = [c for c in work if c["arm"] == arm]
        if not subset or stop.is_set():
            counts["refused"] += len(subset)
            continue
        if arm == "medium":
            with _MediumEffort():
                run_arm(subset)
        else:
            run_arm(subset)
    return {"stopped": reason["text"], "asked": len(work), **counts, "modelCalls": guard.calls, "retries": max(0, guard.calls - counts["ok"] - counts["failed"])}


# --- reading the result (free: stored files only) -------------------------------------------------------------


def readings(doc: dict, engine: dict, chosen: dict) -> dict:
    """{arm: {jobId: {requirement id: status}}}, batched chunks merged; "step7" is the stored full call of an earlier day."""
    out = {arm: {} for arm in ARMS}
    for entry in doc["calls"].values():
        out[entry["arm"]].setdefault(entry["jobId"], {}).update({r["id"]: r["status"] for r in entry["requirements"]})
    out["step7"] = {j: {r["id"]: r["status"] for r in engine[j]["output"]["requirements"]} for j in chosen if j in engine}
    return out


def compare(a: dict, b: dict, ids: list[str]) -> dict:
    """Two readings of the same requirements on the given ads. `changed` counts a different verdict level (MISSING and UNKNOWN are one level)."""
    n = same_status = up = down = 0
    ads_changed = set()
    for job_id in ids:
        for req_id, status in (a.get(job_id) or {}).items():
            other = (b.get(job_id) or {}).get(req_id)
            if other is None:
                continue
            n += 1
            same_status += status == other
            if LEVEL[other] != LEVEL[status]:
                ads_changed.add(job_id)
                up += LEVEL[other] > LEVEL[status]
                down += LEVEL[other] < LEVEL[status]
    changed = up + down
    return {"n": n, "changedLevel": changed, "rate": round(changed / n, 3) if n else None, "wilson95": wilson(changed, n), "up": up, "down": down,
            "statusDiffers": n - same_status, "adsWithChange": len(ads_changed), "ads": len(ids)}


def boundaries(a: dict, b: dict, ids: list[str], kinds: dict) -> dict:
    """Where two readings differ: which verdict boundary, and on which requirement kinds and importance."""
    pair, kind = Counter(), Counter()
    for job_id in ids:
        for req_id, status in (a.get(job_id) or {}).items():
            other = (b.get(job_id) or {}).get(req_id)
            if other is None or LEVEL[other] == LEVEL[status]:
                continue
            low, high = sorted((LEVEL[status], LEVEL[other]))
            pair[("silence", "PARTIAL", "MET")[low] + " / " + ("silence", "PARTIAL", "MET")[high]] += 1
            kind[kinds.get(job_id, {}).get(req_id, "?")] += 1
    return {"pairs": dict(pair), "kinds": dict(kind)}


def stability(read: dict, ids: list[str], arms: tuple) -> dict:
    """Across all the given readings of the same input: requirements that never changed level, and those seen at both a positive level and silence."""
    n = stable = both = 0
    for job_id in ids:
        for req_id in (read[arms[0]].get(job_id) or {}):
            seen = [(read[arm].get(job_id) or {}).get(req_id) for arm in arms]
            if None in seen:
                continue
            levels = {LEVEL[s] for s in seen}
            n += 1
            stable += len(levels) == 1
            both += 0 in levels and bool(levels & {1, 2})
    return {"n": n, "sameLevelInAll": stable, "share": round(stable / n, 3) if n else None, "silenceAndPositiveBothSeen": both}


def aggregate(a: str, b: str) -> tuple[str, bool]:
    """Two readings to one verdict, by the accepted rule: (status, flagged). Two silences agree; positive against silence stays out of fit."""
    if a == b or (LEVEL[a] == 0 and LEVEL[b] == 0):
        return a, False
    if LEVEL[a] > 0 and LEVEL[b] > 0:
        return "PARTIAL", True
    return "UNKNOWN", True


def labelled_lines(frozen: dict, sample: dict, chosen: dict) -> list[dict]:
    items = {i["itemId"]: i for i in sample["items"]}
    return [{"jobId": line["jobId"], "reqId": items[item_id]["reqId"], "mode": line["mode"], "meets": line["first"]["meets"]}
            for item_id, line in frozen["lines"].items()
            if line["jobId"] in chosen and not line["probe"] and line["first"]["isMust"] == "yes"]


def against_ran(reading: dict, lines: list[dict]) -> dict:
    """One reading against ran's answers. Accuracy, which agreement between readings does not show."""
    pairs = [(line, (reading.get(line["jobId"]) or {}).get(line["reqId"])) for line in lines if line["meets"] in TARGET]
    pairs = [(line, s) for line, s in pairs if s]
    no_lines = [(line, s) for line, s in pairs if line["meets"] == "no"]
    return {"n": len(pairs), "exact": sum(VERDICT_AS_MEETS[s] == line["meets"] for line, s in pairs),
            "sameLevel": sum(LEVEL[s] == TARGET[line["meets"]] for line, s in pairs),
            "understated": sum(LEVEL[s] < TARGET[line["meets"]] for line, s in pairs), "overstated": sum(LEVEL[s] > TARGET[line["meets"]] for line, s in pairs),
            "ranNoLines": len(no_lines), "ranNoButCredited": sum(LEVEL[s] > 0 for _, s in no_lines)}


def two_readings(a: dict, b: dict, ids: list[str], lines: list[dict]) -> dict:
    """The accepted rule applied to two stored readings: how much is flagged, and whether the flag finds the wrong verdicts."""
    total = flagged = 0
    final = {}
    for job_id in ids:
        for req_id, status in (a.get(job_id) or {}).items():
            other = (b.get(job_id) or {}).get(req_id)
            if other is None:
                continue
            verdict, flag = aggregate(status, other)
            final[(job_id, req_id)] = (verdict, flag)
            total += 1
            flagged += flag
    judged = [(line, final[(line["jobId"], line["reqId"])]) for line in lines if (line["jobId"], line["reqId"]) in final and line["meets"] in TARGET]
    wrong = [(line, v) for line, v in judged if LEVEL[v[0]] != TARGET[line["meets"]]]
    return {"requirements": total, "flagged": flagged, "flaggedShare": round(flagged / total, 3) if total else None, "labelled": len(judged), "wrong": len(wrong),
            "wrongFlagged": sum(v[1] for _, v in wrong), "rightFlagged": sum(v[1] for line, v in judged if LEVEL[v[0]] == TARGET[line["meets"]])}


COMPARISONS = (("pure repeat: full_1 vs full_2 (same input twice)", "full_1", "full_2"),
               ("across days: step7 vs full_1 (same input, earlier run)", "step7", "full_1"),
               ("order: full_1 vs shuffled", "full_1", "shuffled"), ("order: full_2 vs shuffled", "full_2", "shuffled"),
               ("question-set size: full_1 vs batched", "full_1", "batched"), ("question-set size: full_2 vs batched", "full_2", "batched"),
               ("effort: full_1 vs medium", "full_1", "medium"), ("effort: full_2 vs medium", "full_2", "medium"))


def analyse(out: Path, frozen: dict, sample: dict) -> dict:
    doc, engine = _load(out / RESULTS_NAME), _load(out / "engine-shadow.json")["ads"]
    chosen = doc["ads"]
    read = readings(doc, engine, chosen)
    lines = labelled_lines(frozen, sample, chosen)
    kinds = {j: {r["id"]: r["kind"] for r in engine[j]["output"]["requirements"]} for j in chosen if j in engine}
    report = {"ads": len(chosen), "calls": len(doc["calls"]), "modes": {}}
    for mode in MODES:
        ids = [j for j, m in chosen.items() if m == mode]
        subset = [line for line in lines if line["mode"] == mode]
        report["modes"][mode] = {"ads": len(ids), "labelledLines": len(subset),
                                 "comparisons": {name: compare(read[a], read[b], ids) for name, a, b in COMPARISONS},
                                 "repeatBoundaries": boundaries(read["full_1"], read["full_2"], ids, kinds),
                                 "stabilityAcrossLowEffortFullReadings": stability(read, ids, ("step7", "full_1", "full_2", "shuffled")),
                                 "againstRan": {arm: against_ran(read[arm], subset) for arm in ("step7", *ARMS)},
                                 "twoReadings": two_readings(read["full_1"], read["shuffled"], ids, subset)}
    return report


def render_analysis(report: dict) -> list[str]:
    out = [f"matcher cause test, current prompt: {report['ads']} dev ads, {report['calls']} calls. CAVEAT: {CAVEAT}",
           "These ads were chosen for having the most labelled lines; verdicts on one ad are not independent, so intervals are too narrow.",
           "A change = a different verdict level (MISSING and UNKNOWN are one level, below PARTIAL, below MET). up/down = the second reading is higher/lower."]
    for mode in MODES:
        m = report["modes"][mode]
        out.append(f"\n== {mode.upper()}: {m['ads']} ads, {m['labelledLines']} labelled real-must lines" + ("" if mode == MODES[0] else "  [DIAGNOSTIC ONLY]"))
        for name, c in m["comparisons"].items():
            out.append(f"  {name}: changed {c['changedLevel']}/{c['n']} = {c['rate']} {c['wilson95']}; up {c['up']} down {c['down']}; status differs {c['statusDiffers']}; ads with a change {c['adsWithChange']}/{c['ads']}")
        b, st = m["repeatBoundaries"], m["stabilityAcrossLowEffortFullReadings"]
        out.append(f"  pure repeat, where the changes sit: boundaries {b['pairs']}; kinds {b['kinds']}")
        out.append(f"  across the four low-effort full readings (step7, full_1, full_2, shuffled): same level in all {st['sameLevelInAll']}/{st['n']} = {st['share']}; seen as both silence and positive {st['silenceAndPositiveBothSeen']}")
        out.append("  against ran's answers (accuracy, not consistency):")
        for arm, a in m["againstRan"].items():
            out.append(f"    {arm:9} n {a['n']}: exact {a['exact']}, same level {a['sameLevel']}, understated {a['understated']}, overstated {a['overstated']}; ran said no but credited {a['ranNoButCredited']}/{a['ranNoLines']}")
        t = m["twoReadings"]
        out.append(f"  two readings (full_1 + shuffled, accepted rule): flagged {t['flagged']}/{t['requirements']} = {t['flaggedShare']}; on {t['labelled']} labelled lines: wrong {t['wrong']}, of which flagged {t['wrongFlagged']}; right but flagged {t['rightFlagged']}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=("estimate", "run", "analyse"))
    ap.add_argument("--out", type=Path, default=STAGE_DIR)
    ap.add_argument("--yes", action="store_true", help="make the paid calls (run only); needs the owner's explicit approval")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    if args.command == "run" and not args.yes:
        print("nothing sent: `run` makes paid calls and needs --yes after the owner's explicit approval; use `estimate` first")
        return 0
    frozen = load_frozen(args.out)
    if args.command == "analyse":
        print("\n".join(render_analysis(analyse(args.out, frozen, _load(args.out / "must-sample.json")))))
        return 0
    profile, intelligence = _load(PROFILE_PATH), _load(INTELLIGENCE_PATH)
    if args.command == "estimate":
        chosen = select_ads(frozen, _load(args.out / "engine-shadow.json")["ads"])
        built = build_calls(args.out, profile, intelligence, chosen)
        price = _price()
        print("\n".join(render_estimate(built, chosen, estimate(built["calls"], price), price, budget())))
        return 0
    result = run(args.out, profile, intelligence, frozen, args.workers)
    print(json.dumps(result))
    return 1 if result.get("stopped") else 0


if __name__ == "__main__":
    raise SystemExit(main())
