#!/usr/bin/env python3
"""P1 Stage B, matcher stability slice 3: the experimental matcher (matcher_v3.py) on the dev set, two identical readings. CALIBRATION ONLY.

    python python/calibration/v3_run.py run --yes   # PAID; only after the owner's explicit approval; hard maximum $0.15
    python python/calibration/v3_run.py analyse     # free: reads the stored results

24 dev ads, full question set per ad, low reasoning effort, no batching; reading 1 finishes before reading 2 starts. The production engine and its prompts
are not touched. Every request is scanned for the owner's identifiers (fail closed), before the run and again before it leaves. Each call is checked against
the cap at its true worst case, on top of real spend in this batch and calls in flight (the guard of matcher_cause_test.py). Any gate refusal, scan hit or
error stops the batch. Results go to matcher-v3-run.json after every call. Prints counts and rates only, never ad, profile or CV text.

READ WITH EVERY NUMBER: 12 ads per mode, one labeller, verdicts on one ad are not independent. Not proof of reliability for all professions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
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
from llm_client import GuardrailRefused, LlmRefused, LlmUnavailable, complete_json, preflight  # noqa: E402
from match_engine.fit import fit_value  # noqa: E402
from calibration import aggregation_preview as ap  # noqa: E402
from calibration import matcher_cause_test as mc  # noqa: E402
from calibration import matcher_v3 as v3  # noqa: E402
from calibration import v3_offline as off  # noqa: E402
from calibration.eval_set import CAVEAT, STAGE_DIR, load as load_frozen  # noqa: E402
from calibration.must_report import wilson  # noqa: E402
from calibration.report import spearman  # noqa: E402

RESULTS_NAME = "matcher-v3-run.json"
FEATURE = mc.FEATURE
HARD_STOP_USD = 0.15  # the owner's cap for this one batch
READINGS = (1, 2)
EFFORT = "low"
MODES = ("production_like", "diagnostic")
KEPT = ("id", "kind", "importance", "status", "rawStatus", "strength", "quoteVerified", "evidenceId", "evidenceQuote", "requirementLevel", "candidateLevel", "closedWorldAbsent", "ownerConfirmedAbsent", "unanswered")
OLD_VOCABULARY = {v3.NOT_EVIDENCED: "UNKNOWN", v3.CONTRADICTED: "MISSING"}  # silence and contradiction are one level, as in slice 1


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ResultStore:
    """matcher-v3-run.json: one entry per (reading, ad), written atomically after each call."""

    def __init__(self, path: Path):
        self.path, self._lock = path, threading.Lock()
        self.data = {"version": 1, "promptId": v3.PROMPT_ID, "batchStartedAt": None, "ads": {}, "calls": {}}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("calls"), dict):
                self.data = loaded

    def _write(self) -> None:
        make_private_dirs(self.path.parent)
        write_text_atomic(self.path, json.dumps(self.data, indent=1, ensure_ascii=False), PRIVATE_FILE_MODE)

    def start(self, chosen: dict) -> datetime:
        with self._lock:
            self.data["batchStartedAt"] = self.data["batchStartedAt"] or _now()
            self.data["ads"] = chosen
            self._write()
            return datetime.fromisoformat(self.data["batchStartedAt"])

    def done(self, key: str, prompt_hash: str) -> bool:
        return (self.data["calls"].get(key) or {}).get("hash") == prompt_hash

    def put(self, key: str, reading: int, job_id: str, prompt_hash: str, requirements: dict) -> None:
        with self._lock:
            self.data["calls"][key] = {"reading": reading, "jobId": job_id, "hash": prompt_hash, "at": _now(),
                                       "requirements": {i: {k: r.get(k) for k in KEPT} for i, r in requirements.items()}}
            self._write()


def with_raw_status(prepared: dict, raw, verified: dict) -> dict:
    """The verified verdicts plus what the model proposed before the quote check (None for a line settled in code or left unanswered)."""
    proposals = v3.check_reply(raw)
    proposed = {req["id"]: (proposals.get(ref) or {}).get("status") for ref, req in prepared["asked"]}
    return {i: {**r, "rawStatus": proposed.get(i)} for i, r in verified.items()}


def run(out: Path, profile: dict, intelligence: dict, frozen: dict, workers: int = 4, complete=complete_json) -> dict:
    """The approved batch. Stops before any call on a scan hit, a setting that is not low effort, or an estimate over the cap; during it on a refusal, a hit or an error."""
    chosen = off.dev_ads(frozen, _load(out / "engine-shadow.json")["ads"])
    built = off.build_requests(out, profile, intelligence, chosen)
    if built["leaks"]:
        return {"stopped": "privacy scan found owner identifiers; nothing was sent", "asked": 0}
    selection = ai_selection.require()
    if (selection.get("reasoningEffort") or ai_selection.DEFAULTS["reasoningEffort"]) != EFFORT:
        return {"stopped": f"reasoning effort is not {EFFORT}; nothing was sent", "asked": 0}
    price = off.price_now()
    if price["in"] is None or price["out"] is None:
        return {"stopped": "no price for this model; nothing was sent", "asked": 0}
    est = off.estimate(built["requests"], price)
    if est["upperBound"] > HARD_STOP_USD:
        return {"stopped": f"estimate ${est['upperBound']:.4f} is over the hard maximum ${HARD_STOP_USD:.2f}; nothing was sent", "asked": 0}
    store = ResultStore(out / RESULTS_NAME)
    hashes = {j: hashlib.sha256(r["prompt"].encode("utf-8")).hexdigest() for j, r in built["requests"].items()}
    work = [(n, j) for n in READINGS for j in built["requests"] if not store.done(f"{n}|{j}", hashes[j])]
    if not work:
        return {"stopped": None, "asked": 0, "ok": 0, "failed": 0, "refused": 0, "modelCalls": 0, "retries": 0}
    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    with ai_gate.context(feature=FEATURE):
        decision = preflight(max(len(built["requests"][j]["prompt"]) for _, j in work), price["provider"], price["model"])
    if not decision.allowed:
        ai_gate.record_refused(decision, skipped=len(work))
        return {"stopped": f"AI gate refused: {decision.reason}", "asked": 0}
    guard = mc.SpendGuard(HARD_STOP_USD, store.start(chosen), price, ai_selection.REASONING_MIN_COMPLETION_TOKENS)
    stop = threading.Event()
    counts = {"ok": 0, "failed": 0, "refused": 0}
    reason = {"text": None}

    def halt(text: str) -> None:
        reason["text"] = reason["text"] or text
        stop.set()

    def ask(prompt: str, job_id: str):
        if off.owner_leaks(prompt, profile):  # again, on the exact text about to leave
            raise GuardrailRefused("privacy scan hit on an outgoing request")
        worst = guard.reserve(prompt)
        try:
            with ai_gate.context(feature=FEATURE, job_id=job_id):
                return complete(prompt, schema=v3.SCHEMA, model=price["model"], provider=price["provider"])
        finally:
            guard.release(worst)

    def one(reading: int, job_id: str) -> str:
        if stop.is_set():
            return "refused"
        prepared = built["requests"][job_id]
        for attempt in (1, 2):  # the matcher's own rule: one retry for a reply that is not JSON or not the schema
            try:
                raw = ask(prepared["prompt"], job_id)
                verified = v3.read_reply(prepared, raw, built["candidate"])
                store.put(f"{reading}|{job_id}", reading, job_id, hashes[job_id], with_raw_status(prepared, raw, verified))
                return "ok"
            except GuardrailRefused as exc:
                halt(str(exc) or "AI gate refused a call")
                return "refused"
            except (LlmRefused, ValueError):
                if attempt == 2:
                    halt("a call failed: the reply was not usable after one retry")
                    return "failed"
            except LlmUnavailable:
                halt("a call failed: the provider was unavailable")
                return "failed"
        raise AssertionError("unreachable")

    for reading in READINGS:  # the first reading finishes first, so the identical second one can find it in the prompt cache
        subset = [(n, j) for n, j in work if n == reading]
        if stop.is_set():
            counts["refused"] += len(subset)
            continue
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for future in as_completed([pool.submit(one, n, j) for n, j in subset]):
                counts[future.result()] += 1
    return {"stopped": reason["text"], "asked": len(work), **counts, "modelCalls": guard.calls, "retries": max(0, guard.calls - counts["ok"] - counts["failed"])}


# --- reading the result (free: stored files only) -------------------------------------------------------------


def stored_readings(doc: dict) -> dict:
    """{reading: {jobId: {requirement id: requirement}}}."""
    out = {n: {} for n in READINGS}
    for entry in doc["calls"].values():
        out[entry["reading"]][entry["jobId"]] = entry["requirements"]
    return out


def as_statuses(reading: dict) -> dict:
    """{jobId: {id: status}} in the vocabulary slice 1 was measured in, so the numbers compare."""
    return {j: {i: OLD_VOCABULARY.get(r["status"], r["status"]) for i, r in reqs.items()} for j, reqs in reading.items()}


def transitions(old: dict, new: dict, ids: list[str]) -> dict:
    """Old verdict to new verdict: where the old PARTIALs went, and what became PARTIAL."""
    pairs = Counter((old[j][i], new[j][i]) for j in ids for i in old.get(j, {}) if i in new.get(j, {}))
    partial_n = sum(n for (a, _), n in pairs.items() if a == "PARTIAL")
    return {"oldPartial": partial_n, "oldPartialBecame": {b: n for (a, b), n in sorted(pairs.items()) if a == "PARTIAL"},
            "newPartial": sum(n for (_, b), n in pairs.items() if b == v3.PARTIAL), "newPartialFrom": {a: n for (a, b), n in sorted(pairs.items()) if b == v3.PARTIAL},
            "n": sum(pairs.values())}


def stable_old_partials(first: dict, second: dict, new1: dict, new2: dict, ids: list[str]) -> dict:
    """On ads read twice under the old prompt: lines PARTIAL both times (so not just noise), and where both new readings put them."""
    became, n = Counter(), 0
    reference = Counter()
    for j in ids:
        for i, status in first.get(j, {}).items():
            other = second.get(j, {}).get(i)
            if other is None:
                continue
            if status == "PARTIAL":
                reference["stayed PARTIAL" if other == "PARTIAL" else "left PARTIAL"] += 1
            if status == other == "PARTIAL" and i in new1.get(j, {}) and i in new2.get(j, {}):
                n += 1
                became[" / ".join(sorted({new1[j][i], new2[j][i]}))] += 1
    return {"n": n, "newVerdicts": dict(became), "oldRepeatReference": dict(reference)}


def contradictions(first: dict, second: dict, merged: dict, ids: list[str], lines: list[dict]) -> dict:
    """How CONTRADICTED was used: proposed, surviving the quote check, confirmed by both readings, and against the owner's answers."""
    all_reqs = [r for reading in (first, second) for j in ids for r in reading.get(j, {}).values()]
    final = [(j, i) for j in ids for i, r in merged.get(j, {}).items() if r["status"] == v3.CONTRADICTED]
    labels = {(line["jobId"], line["reqId"]): line["meets"] for line in lines}
    on_labelled = [labels[key] for key in final if key in labels]
    one_sided = sum(1 for j in ids for r in merged.get(j, {}).values() if r.get("flagReason") == "CONTRADICTED in one reading only")
    return {"readings": len(all_reqs), "proposed": sum(r.get("rawStatus") == v3.CONTRADICTED for r in all_reqs), "verified": sum(r["status"] == v3.CONTRADICTED for r in all_reqs),
            "finalBothReadings": len(final), "oneReadingOnly": one_sided, "finalKinds": dict(Counter(merged[j][i]["kind"] for j, i in final)),
            "finalOnLabelledLines": len(on_labelled), "ownerAnswersThere": dict(Counter(on_labelled)), "ownerSaysRight (no)": on_labelled.count("no"), "ownerSaysWrong (yes or partly)": sum(a in ("yes", "partial") for a in on_labelled),
            "finalWithoutOwnerLabel": len(final) - len(on_labelled)}


def against_merged(merged: dict, lines: list[dict]) -> dict:
    """The joined verdict against the owner's answers, and whether the flag finds the wrong ones."""
    level = {v3.MET: 2, v3.PARTIAL: 1}
    pairs = [(line, merged[line["jobId"]][line["reqId"]]) for line in lines if line["meets"] in mc.TARGET and line["reqId"] in merged.get(line["jobId"], {})]
    wrong = [(line, r) for line, r in pairs if level.get(r["status"], 0) != mc.TARGET[line["meets"]]]
    return {"n": len(pairs), "sameLevel": len(pairs) - len(wrong), "understated": sum(level.get(r["status"], 0) < mc.TARGET[line["meets"]] for line, r in pairs),
            "overstated": sum(level.get(r["status"], 0) > mc.TARGET[line["meets"]] for line, r in pairs), "wrong": len(wrong), "wrongFlagged": sum(bool(r.get("flagged")) for _, r in wrong),
            "rightFlagged": sum(bool(r.get("flagged")) for line, r in pairs if level.get(r["status"], 0) == mc.TARGET[line["meets"]]),
            "ranNoLines": sum(line["meets"] == "no" for line, _ in pairs), "ranNoButCredited": sum(line["meets"] == "no" and level.get(r["status"], 0) > 0 for line, r in pairs)}


def level_fields(first: dict, second: dict, merged: dict, ids: list[str]) -> dict:
    """UNVALIDATED: how often the level fields were filled, whether the two readings agreed, and how many MET lines they downgraded."""
    both = [(first[j][i], second[j][i]) for j in ids for i in first.get(j, {}) if i in second.get(j, {})]
    required = [(a, b) for a, b in both if a.get("requirementLevel") or b.get("requirementLevel")]
    shown = [(a, b) for a, b in both if a.get("candidateLevel") or b.get("candidateLevel")]
    return {"requirements": len(both), "requirementLevelSet": len(required), "requirementLevelAgrees": sum(a.get("requirementLevel") == b.get("requirementLevel") for a, b in required),
            "candidateLevelSet": len(shown), "candidateLevelAgrees": sum(a.get("candidateLevel") == b.get("candidateLevel") for a, b in shown),
            "downgraded": sum(bool(r.get("levelDowngraded")) for j in ids for r in merged.get(j, {}).values())}


def fit_view(reqs: dict, gates: dict, owner: dict, ids: list[str]) -> dict:
    """Fit and confidence of the joined verdicts, reported apart, with rank agreement against the owner's overall level."""
    pv = {j: ap.preview(list(reqs[j].values()), gates.get(j) or [], {}) for j in ids}
    known = [j for j in ids if pv[j]["fit"] is not None]
    rho = spearman([float(owner[j]) for j in known], [float(pv[j]["fit"]) for j in known]) if len(known) >= 3 else None
    return {"n": len(known), "noEstimate": len(ids) - len(known), "medianFit": statistics.median(pv[j]["fit"] for j in known) if known else None,
            "medianConfidence": round(statistics.median(pv[j]["confidence"] for j in ids), 2) if ids else None, "labels": dict(Counter(pv[j]["label"] for j in known)),
            "spearman": None if rho is None else round(rho, 2)}


def analyse(out: Path, frozen: dict, sample: dict) -> dict:
    doc, engine = _load(out / RESULTS_NAME), _load(out / "engine-shadow.json")["ads"]
    chosen = doc["ads"]
    read = stored_readings(doc)
    first, second = as_statuses(read[1]), as_statuses(read[2])
    merged = {j: v3.aggregate_two(read[1][j], read[2][j]) for j in chosen if j in read[1] and j in read[2]}
    step7 = {j: {r["id"]: r["status"] for r in engine[j]["output"]["requirements"]} for j in chosen}
    owner = {j: frozen["ads"][j]["overall"] for j in chosen}
    lines = mc.labelled_lines(frozen, sample, chosen)
    cause = _load(out / mc.RESULTS_NAME) if (out / mc.RESULTS_NAME).exists() else None
    old_read = mc.readings(cause, engine, cause["ads"]) if cause else None
    final_status = {j: {i: r["status"] for i, r in reqs.items()} for j, reqs in merged.items()}
    report = {"ads": len(chosen), "calls": len(doc["calls"]), "modes": {}}
    for mode in MODES:
        ids = [j for j, m in chosen.items() if m == mode and j in merged]
        subset = [line for line in lines if line["mode"] == mode]
        slice1_ids = [j for j in ids if cause and cause["ads"].get(j) == mode]
        queues = [v3.flag_queue(merged[j]) for j in ids]
        total = sum(len(merged[j]) for j in ids)
        gates = {j: engine[j].get("gates") or [] for j in ids}
        base = {j: fit_value(engine[j]["output"]["requirements"]) for j in ids}
        known = [j for j in ids if base[j] is not None]
        base_rho = spearman([float(owner[j]) for j in known], [float(base[j]) for j in known]) if len(known) >= 3 else None
        entry = {
            "ads": len(ids), "labelledLines": len(subset),
            "noise": mc.compare(first, second, ids), "boundaries": mc.boundaries(first, second, ids, {j: {i: r["kind"] for i, r in read[1][j].items()} for j in ids}),
            "noiseOnSlice1Ads": mc.compare(first, second, slice1_ids),
            "slice1Noise": mc.compare(old_read["full_1"], old_read["full_2"], slice1_ids) if old_read else None,
            "partialFromStep7ToReading1": transitions(step7, {j: {i: r["status"] for i, r in read[1][j].items()} for j in ids}, ids),
            "partialFromStep7ToJoined": transitions(step7, final_status, ids),
            "stablePartialOnSlice1Ads": stable_old_partials(old_read["full_1"], old_read["full_2"], {j: {i: r["status"] for i, r in read[1][j].items()} for j in slice1_ids}, {j: {i: r["status"] for i, r in read[2][j].items()} for j in slice1_ids}, slice1_ids) if old_read else None,
            "contradicted": contradictions(read[1], read[2], merged, ids, subset),
            "accuracy": {"step7": mc.against_ran(step7, subset), "reading1": mc.against_ran(first, subset), "reading2": mc.against_ran(second, subset), "joined": against_merged(merged, subset)},
            "flags": {"requirements": total, "flagged": sum(q["flagged"] for q in queues), "flaggedShare": round(sum(q["flagged"] for q in queues) / total, 3) if total else None,
                      "reasons": dict(Counter(r["flagReason"] for j in ids for r in merged[j].values() if r.get("flagged"))), "shown": sum(len(q["queue"]) for q in queues), "adsWithQueue": sum(1 for q in queues if q["queue"]), "overflow": sum(q["overflow"] for q in queues)},
            "levels": level_fields(read[1], read[2], merged, ids), "statusesJoined": dict(Counter(r["status"] for j in ids for r in merged[j].values())),
            "closedWorldAbsent": sum(bool(r.get("closedWorldAbsent")) for j in ids for r in merged[j].values()),
            "fitCurrentFormula": {"n": len(known), "medianFit": statistics.median(base[j] for j in known) if known else None, "spearman": None if base_rho is None else round(base_rho, 2)},
            "fitJoined": fit_view(merged, gates, owner, ids),
        }
        report["modes"][mode] = entry
    return report


def _pct(c: dict) -> str:
    return f"{c['changedLevel']}/{c['n']} = {c['rate']} {wilson(c['changedLevel'], c['n'])}; up {c['up']} down {c['down']}; status differs {c['statusDiffers']}; ads with a change {c['adsWithChange']}/{c['ads']}"


def render_analysis(report: dict) -> list[str]:
    out = [f"matcher v3, slice 3: {report['ads']} dev ads, {report['calls']} calls. CAVEAT: {CAVEAT}",
           "Verdicts on one ad are not independent, so intervals are too narrow. A change = a different verdict level (NOT_EVIDENCED and CONTRADICTED are one level, below PARTIAL, below MET)."]
    for mode in MODES:
        m = report["modes"][mode]
        out.append(f"\n== {mode.upper()}: {m['ads']} ads, {m['labelledLines']} labelled real-must lines" + ("" if mode == MODES[0] else "  [DIAGNOSTIC ONLY]"))
        out.append(f"  repeat noise, all ads: {_pct(m['noise'])}; boundaries {m['boundaries']['pairs']}; kinds {m['boundaries']['kinds']}")
        out.append(f"  repeat noise, on the slice 1 ads only: {_pct(m['noiseOnSlice1Ads'])}")
        if m["slice1Noise"]:
            out.append(f"  slice 1 (old prompt), same ads: {_pct(m['slice1Noise'])}")
        for key, title in (("partialFromStep7ToReading1", "PARTIAL, Step 7 (old prompt) to reading 1"), ("partialFromStep7ToJoined", "PARTIAL, Step 7 to the joined verdict")):
            t = m[key]
            out.append(f"  {title}: of {t['n']} requirements, old PARTIAL {t['oldPartial']} became {t['oldPartialBecame']}; new PARTIAL {t['newPartial']} came from {t['newPartialFrom']}")
        if m["stablePartialOnSlice1Ads"]:
            s = m["stablePartialOnSlice1Ads"]
            out.append(f"  old PARTIAL in both slice 1 readings, n {s['n']}: new verdicts (both readings) {s['newVerdicts']}; old-prompt repeat for reference {s['oldRepeatReference']}")
        c = m["contradicted"]
        out.append(f"  CONTRADICTED over {c['readings']} line readings: proposed {c['proposed']}, kept by the quote check {c['verified']}; both readings {c['finalBothReadings']}, one reading only {c['oneReadingOnly']}; kinds {c['finalKinds']}")
        out.append(f"    on labelled lines {c['finalOnLabelledLines']}: your answers {c['ownerAnswersThere']}; right {c['ownerSaysRight (no)']}, wrong {c['ownerSaysWrong (yes or partly)']}; without a label of yours {c['finalWithoutOwnerLabel']}")
        out.append("  against your answers (accuracy, not consistency; same level, of n):")
        for arm, a in m["accuracy"].items():
            flag = f"; wrong {a['wrong']}, flagged {a['wrongFlagged']}, right but flagged {a['rightFlagged']}" if arm == "joined" else ""
            out.append(f"    {arm:9} {a['sameLevel']}/{a['n']}; understated {a['understated']}, overstated {a['overstated']}; you said no but credited {a['ranNoButCredited']}/{a['ranNoLines']}{flag}")
        f = m["flags"]
        out.append(f"  flagged {f['flagged']}/{f['requirements']} = {f['flaggedShare']}; reasons {f['reasons']}; queue {f['shown']} shown on {f['adsWithQueue']} ads, {f['overflow']} not shown")
        lv = m["levels"]
        out.append(f"  levels (UNVALIDATED), of {lv['requirements']} requirements: requirement level set {lv['requirementLevelSet']}, same in both readings {lv['requirementLevelAgrees']}; candidate level set {lv['candidateLevelSet']}, same in both {lv['candidateLevelAgrees']}; MET downgraded {lv['downgraded']}")
        out.append(f"  joined verdicts {m['statusesJoined']}; closed-world absent {m['closedWorldAbsent']}")
        out.append(f"  fit: current formula on Step 7 {m['fitCurrentFormula']}; joined verdicts {m['fitJoined']}")
    return out


def main(argv=None) -> int:
    ap_ = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap_.add_argument("command", choices=("run", "analyse"))
    ap_.add_argument("--out", type=Path, default=STAGE_DIR)
    ap_.add_argument("--yes", action="store_true", help="make the paid calls (run only); needs the owner's explicit approval")
    ap_.add_argument("--workers", type=int, default=4)
    args = ap_.parse_args(argv)
    if args.command == "run" and not args.yes:
        print("nothing sent: `run` makes paid calls and needs --yes after the owner's explicit approval")
        return 0
    frozen = load_frozen(args.out)
    if args.command == "analyse":
        print("\n".join(render_analysis(analyse(args.out, frozen, _load(args.out / "must-sample.json")))))
        return 0
    result = run(args.out, _load(off.PROFILE_PATH), _load(off.INTELLIGENCE_PATH), frozen, args.workers)
    print(json.dumps(result))
    return 1 if result.get("stopped") else 0


if __name__ == "__main__":
    raise SystemExit(main())
