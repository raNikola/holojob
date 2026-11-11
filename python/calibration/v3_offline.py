#!/usr/bin/env python3
"""P1 Stage B, matcher stability slice 2: offline validation of the new rules on stored verdicts, and the slice 3 dry run. NO MODEL CALL.

    python python/calibration/v3_offline.py replay     # stored verdicts through the new aggregation: direction and size of the score changes
    python python/calibration/v3_offline.py estimate   # builds and scans the slice 3 requests (dev set, two identical readings), sends nothing

There is no `run` command: slice 3 is separate work and needs the owner's explicit approval. Prints counts and rates only.

What a replay can and cannot say. Stored verdicts come from the CURRENT prompt, so the replay measures the new AGGREGATION only (silence out of fit, two
readings). It cannot show what the tighter PARTIAL wording will do, because no stored field says whether a PARTIAL was "a named part" or "a related
subject". The two strict scenarios are therefore sensitivity bounds, not predictions: PARTIAL at strength 0-1 (only listed) as a proxy, and every PARTIAL.
Typed absence and levels are not in stored data at all, so they cannot be validated without a paid run, and levels not without labels.

READ WITH EVERY NUMBER: a small, purpose-chosen diagnostic sample, one labeller, not proof of reliability for all professions.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("cv_analysis", "llm", "job_scoring"):
    if str(ROOT / "python" / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / "python" / _sub))
if str(ROOT / "python") not in sys.path:
    sys.path.append(str(ROOT / "python"))

import ai_gate  # noqa: E402
import ai_selection  # noqa: E402
from competency_mapping import load_remap  # noqa: E402
from confirmed_facts import load as load_confirmed_facts  # noqa: E402
from evidence_index import build_candidate  # noqa: E402
from llm_client import service_tier_for  # noqa: E402
from match_engine import matcher  # noqa: E402
from match_engine.constants import IMPORTANCE_WEIGHT, STRENGTH_CREDIT  # noqa: E402
from match_engine.fit import fit_value  # noqa: E402
from redact import identity_of  # noqa: E402
from calibration import aggregation_preview as ap  # noqa: E402
from calibration import matcher_v3 as v3  # noqa: E402
from calibration.engine_sample import alias_unsafe_ids, sanitized  # noqa: E402
from calibration.eval_report import profile_sections  # noqa: E402
from calibration.eval_set import CAVEAT, STAGE_DIR, load as load_frozen  # noqa: E402
from calibration.matcher_cause_test import LEVEL, MEASURED_CHARS_PER_TOKEN, OUTPUT_BASE, OUTPUT_PER_REQUIREMENT, TARGET, UPPER_CHARS_PER_TOKEN, labelled_lines  # noqa: E402
from calibration.prelabel import owner_leaks  # noqa: E402
from calibration.report import spearman  # noqa: E402

PROFILE_PATH = ROOT / "data" / "profile" / "candidate-profile.json"
INTELLIGENCE_PATH = ROOT / "data" / "intelligence" / "candidate-intelligence.json"
MODES = ("production_like", "diagnostic")
LISTED_ONLY = 1  # strength 0-1: "only listed", the proxy for a PARTIAL the tighter wording might reject
NEW_SCHEMA_OUTPUT_FACTOR = 1.4  # assumed: no call with the new schema has been made
CACHED_INPUT_SHARE = 0.1  # OpenAI bills cached input at 10%; an identical repeat was 99.96% cached in slice 1
READINGS = 2
PROPOSED_CAP_USD = 0.15
# Competency memory M4 (spec section 7): what an unconfirmed must earns, as a share of the credit for described work.
PRIORS = (Fraction(3, 10), Fraction(1, 2), Fraction(7, 10))
PRIOR_BASE_STRENGTH = 3
CURRENT, SILENCE_OUT = "current formula", "silence out of fit"
HARD_LEVEL = {"no": 0, "partial": 1, "yes": 2}
TOP_N = 10
LOW_CONFIDENCE = 0.5


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def typed(req: dict) -> dict:
    """A stored verdict in the new vocabulary. Stored data holds no conflicting quote, so MISSING and UNKNOWN are both silence."""
    return {**req, "status": req["status"] if req["status"] in v3.POSITIVE else v3.NOT_EVIDENCED, "strength": req.get("strength") or 0}


def demote(req: dict, max_strength: int | None, to: str) -> dict:
    """A PARTIAL at or below `max_strength` (None = every PARTIAL) becomes `to`."""
    if req["status"] == v3.PARTIAL and (max_strength is None or (req.get("strength") or 0) <= max_strength):
        return {**req, "status": to, "strength": 0}
    return req


def _current(reqs: list[dict]) -> int | None:
    """The engine's own Fit formula on stored statuses, before caps. None when nothing is settled."""
    return fit_value(reqs) if any(r["status"] in ("MET", "PARTIAL", "MISSING") for r in reqs) else None


def _new(reqs: list[dict]) -> int | None:
    return ap.fit_of([typed(r) for r in reqs], {})


SCENARIOS = {
    "typed (silence out of fit)": _new,
    "typed + stored MISSING on education/certification/language as CONTRADICTED": None,  # needs the profile sections, set in replay
    "new rules + strict proxy (PARTIAL at strength 0-1 out of fit)": lambda rs: ap.fit_of([demote(typed(r), LISTED_ONLY, v3.NOT_EVIDENCED) for r in rs], {}),
    "new rules + strict bound (every PARTIAL out of fit)": lambda rs: ap.fit_of([demote(typed(r), None, v3.NOT_EVIDENCED) for r in rs], {}),
    "CURRENT formula + strict proxy (PARTIAL at strength 0-1 scored as MISSING)": lambda rs: _current([demote(r, LISTED_ONLY, "MISSING") for r in rs]),
    "CURRENT formula + strict bound (every PARTIAL scored as MISSING)": lambda rs: _current([demote(r, None, "MISSING") for r in rs]),
}


def fit_with_prior(reqs: list[dict], prior: Fraction, critical_at_prior: bool = True) -> int | None:
    """Fit before caps with a NOT_EVIDENCED must in the denominator, earning prior x the credit of strength 3. Other silence stays out; a critical
    unconfirmed must earns the prior or nothing. No profile sections are passed, so closed-world absence is NOT_EVIDENCED (owner decision A1)."""
    num = den = Fraction(0)
    for req in reqs:
        status = ap.typed_status(req, {})
        weight = IMPORTANCE_WEIGHT[req["importance"]]
        if status != v3.NOT_EVIDENCED:
            den += weight
            num += ap._credit(req, status) * weight
        elif req["importance"] == "must":
            den += weight
            if critical_at_prior or not ap.is_critical(req, status):
                num += prior * STRENGTH_CREDIT[PRIOR_BASE_STRENGTH] * weight
    return ap._round_half_up(100 * num / den) if den else None


def prior_variants() -> dict:
    variants = {SILENCE_OUT: _new}
    for prior in PRIORS:
        for at_prior in (True, False):
            variants[f"prior {prior}, critical must at {'the prior' if at_prior else '0'}"] = lambda rs, p=prior, a=at_prior: fit_with_prior(rs, p, a)
    return variants


def prior_rows(verdicts: dict, baseline: dict, gates: dict, ads: dict) -> dict:
    """Every variant on one mode's verdicts, against the current formula on the Step 7 verdicts of the same ads. Rank agreement with both owner labels."""
    baseline = {j: baseline[j] for j in verdicts}
    overall = {j: ads[j]["overall"] for j in verdicts}
    hard = {j: HARD_LEVEL[ads[j]["hardRequirements"]] for j in verdicts if ads[j].get("hardRequirements") in HARD_LEVEL}
    confidence = {j: float(ap.confidence_of(verdicts[j], gates[j], {})) for j in verdicts}
    rows = {}
    for name, fits in {CURRENT: baseline, **{n: {j: fn(verdicts[j]) for j in verdicts} for n, fn in prior_variants().items()}}.items():
        e = effect(baseline, fits, overall)
        known = [j for j in hard if fits[j] is not None and baseline[j] is not None]
        rho_hard = spearman([float(hard[j]) for j in known], [float(fits[j]) for j in known]) if len(known) >= 3 else None
        top = sorted((j for j in fits if fits[j] is not None), key=lambda j: (-fits[j], j))[:TOP_N]
        rows[name] = {"n": e["n"], "spearmanOverall": e["spearman"], "spearmanHard": None if rho_hard is None else round(rho_hard, 2), "medianFit": e["medianFit"], "meanDelta": e["meanDelta"],
                      "medianDelta": e["medianDelta"], "top": len(top), "lowConfidenceInTop": sum(confidence[j] < LOW_CONFIDENCE for j in top)}
    return {"ads": len(verdicts), "hardLabels": dict(Counter(hard.values())), "rows": rows}


def joined_slice3(doc: dict) -> dict:
    """{jobId: [requirement]} of the slice 3 run: its two identical readings joined by the Stage B rule."""
    read = {1: {}, 2: {}}
    for entry in doc["calls"].values():
        read[entry["reading"]][entry["jobId"]] = entry["requirements"]
    return {j: list(v3.aggregate_two(read[1][j], read[2][j]).values()) for j in doc["ads"] if j in read[1] and j in read[2]}


def effect(base: dict, new: dict, owner: dict) -> dict:
    """One scenario against the baseline, over the ads where both have a number. Size and direction of the change, labels, rank agreement."""
    ids = [j for j in base if base[j] is not None and new.get(j) is not None]
    deltas = [new[j] - base[j] for j in ids]
    rho = spearman([float(owner[j]) for j in ids], [float(new[j]) for j in ids]) if len(ids) >= 3 else None
    return {"n": len(ids), "noEstimate": sum(1 for j in base if new.get(j) is None), "medianFit": statistics.median(new[j] for j in ids) if ids else None,
            "meanDelta": round(statistics.mean(deltas), 1) if deltas else None, "medianDelta": statistics.median(deltas) if deltas else None, "minDelta": min(deltas, default=None), "maxDelta": max(deltas, default=None),
            "up": sum(d > 0 for d in deltas), "down": sum(d < 0 for d in deltas), "same": sum(d == 0 for d in deltas),
            "labels": dict(Counter(ap.label_for(new[j]) for j in ids)), "spearman": None if rho is None else round(rho, 2)}


def median_confidence(reqs_by_ad: dict, gates_by_ad: dict, change=lambda r: r) -> float | None:
    """Median confidence with the stored verdicts in the new vocabulary, after `change`. Fit and confidence are reported apart."""
    values = [float(ap.confidence_of([change(typed(r)) for r in reqs], gates_by_ad[j], {})) for j, reqs in reqs_by_ad.items()]
    return round(statistics.median(values), 2) if values else None


def partial_at_risk(requirements: list[dict], lines: list[dict], by_ad: dict) -> dict:
    """How many stored PARTIALs the strict proxy touches, overall and on the owner's labelled real musts."""
    partial = [r for r in requirements if r["status"] == v3.PARTIAL]
    at_risk = [r for r in partial if (r.get("strength") or 0) <= LISTED_ONLY]
    labelled = [(line, by_ad.get(line["jobId"], {}).get(line["reqId"])) for line in lines]
    on_partial = [(line, r) for line, r in labelled if r and r["status"] == v3.PARTIAL]
    return {"requirements": len(requirements), "partial": len(partial), "partialStrength01": len(at_risk), "partialStrengths": dict(sorted(Counter(r.get("strength") for r in partial).items())),
            "labelledPartial": dict(Counter(line["meets"] for line, _ in on_partial)),
            "labelledPartialStrength01": dict(Counter(line["meets"] for line, r in on_partial if (r.get("strength") or 0) <= LISTED_ONLY))}


def stored_reading(calls: dict, arm: str, engine: dict) -> dict:
    """{jobId: {requirement id: requirement}} of one stored arm of the cause test, in the new vocabulary."""
    out = {}
    for entry in calls.values():
        if entry["arm"] != arm:
            continue
        base = {r["id"]: r for r in engine[entry["jobId"]]["output"]["requirements"]}
        for r in entry["requirements"]:
            out.setdefault(entry["jobId"], {})[r["id"]] = {**typed({**base[r["id"]], **r}), "requirementLevel": None, "candidateLevel": None}
    return out


def two_reading_replay(calls: dict, engine: dict, ads: dict, owner: dict, lines: list[dict]) -> dict:
    """The stored identical pair (full_1, full_2) through the new aggregation and queue, against the current formula on full_1."""
    first, second = stored_reading(calls, "full_1", engine), stored_reading(calls, "full_2", engine)
    raw = {}
    for entry in calls.values():
        if entry["arm"] == "full_1":
            base = {r["id"]: r for r in engine[entry["jobId"]]["output"]["requirements"]}
            raw.setdefault(entry["jobId"], []).extend({**base[r["id"]], **r} for r in entry["requirements"])
    report = {}
    for mode in MODES:
        ids = [j for j, m in ads.items() if m == mode]
        merged = {j: v3.aggregate_two(first[j], second[j]) for j in ids}
        base = {j: _current(raw[j]) for j in ids}
        fit = {j: ap.fit_of(list(merged[j].values()), {}) for j in ids}
        strict = {j: ap.fit_of([demote(r, LISTED_ONLY, v3.NOT_EVIDENCED) for r in merged[j].values()], {}) for j in ids}
        queues = {j: v3.flag_queue(merged[j]) for j in ids}
        shown = {(j, r["id"]) for j, q in queues.items() for r in q["queue"]}
        subset = [line for line in lines if line["mode"] == mode and line["meets"] in TARGET and line["reqId"] in merged.get(line["jobId"], {})]
        level = lambda line: {v3.MET: 2, v3.PARTIAL: 1}.get(merged[line["jobId"]][line["reqId"]]["status"], 0)
        wrong = [line for line in subset if level(line) != TARGET[line["meets"]]]
        total = sum(len(m) for m in merged.values())
        report[mode] = {
            "ads": len(ids), "requirements": total, "flagged": sum(q["flagged"] for q in queues.values()), "flaggedShare": round(sum(q["flagged"] for q in queues.values()) / total, 3) if total else None,
            "adsWithQueue": sum(1 for q in queues.values() if q["queue"]), "shownInQueue": sum(len(q["queue"]) for q in queues.values()), "overflow": sum(q["overflow"] for q in queues.values()),
            "reasons": dict(Counter(r["flagReason"] for m in merged.values() for r in m.values() if r.get("flagged"))),
            "statuses": dict(Counter(r["status"] for m in merged.values() for r in m.values())),
            "aggregationEffect": effect(base, fit, {j: owner[j] for j in ids}), "strictProxyEffect": effect(base, strict, {j: owner[j] for j in ids}),
            "labelled": len(subset), "wrong": len(wrong), "wrongInQueue": sum((line["jobId"], line["reqId"]) in shown for line in wrong),
            "wrongFlaggedAnywhere": sum(bool(merged[line["jobId"]][line["reqId"]].get("flagged")) for line in wrong),
        }
    return report


def replay(out: Path, frozen: dict, sample: dict, sections: dict | None = None) -> dict:
    engine = _load(out / "engine-shadow.json")["ads"]
    sections = profile_sections() if sections is None else sections
    owner = {j: a["overall"] for j, a in frozen["ads"].items()}
    scenarios = {**SCENARIOS, "typed + stored MISSING on education/certification/language as CONTRADICTED": lambda rs: ap.fit_of(rs, sections)}
    chosen = {j: e["mode"] for j, e in engine.items() if j in owner}
    all_lines = labelled_lines(frozen, sample, chosen)
    report = {"modes": {}}
    for mode in MODES:
        ids = [j for j, m in chosen.items() if m == mode]
        reqs = {j: engine[j]["output"]["requirements"] for j in ids}
        base = {j: _current(reqs[j]) for j in ids}
        base_rho = spearman([float(owner[j]) for j in ids if base[j] is not None], [float(base[j]) for j in ids if base[j] is not None])
        gates = {j: engine[j].get("gates") or [] for j in ids}
        report["modes"][mode] = {
            "confidence": {"typed": median_confidence(reqs, gates), "strict proxy": median_confidence(reqs, gates, lambda r: demote(r, LISTED_ONLY, v3.NOT_EVIDENCED)),
                           "strict bound": median_confidence(reqs, gates, lambda r: demote(r, None, v3.NOT_EVIDENCED)),
                           "engine as stored": round(statistics.median(float(engine[j]["confidence"]) for j in ids if "confidence" in engine[j]), 2) if any("confidence" in engine[j] for j in ids) else None},
            "ads": len(ids), "currentMedian": statistics.median(v for v in base.values() if v is not None), "currentSpearman": None if base_rho is None else round(base_rho, 2), "currentLabels": dict(Counter(ap.label_for(v) for v in base.values() if v is not None)),
            "scenarios": {name: effect(base, {j: fn(reqs[j]) for j in ids}, owner) for name, fn in scenarios.items()},
            "partialAtRisk": partial_at_risk([r for j in ids for r in reqs[j]], [line for line in all_lines if line["mode"] == mode], {j: {r["id"]: r for r in reqs[j]} for j in ids}),
        }
    cause = out / "matcher-cause-test.json"
    if cause.exists():
        doc = _load(cause)
        report["twoReadings"] = two_reading_replay(doc["calls"], engine, doc["ads"], owner, labelled_lines(frozen, sample, doc["ads"]))
    gates = {j: e.get("gates") or [] for j, e in engine.items()}
    step7 = {j: e["output"]["requirements"] for j, e in engine.items() if j in owner}
    baseline = {j: _current(reqs) for j, reqs in step7.items()}
    of_mode = lambda mode, verdicts: {j: reqs for j, reqs in verdicts.items() if chosen[j] == mode}
    report["priors"] = {"Step 7 verdicts": {m: prior_rows(of_mode(m, step7), baseline, gates, frozen["ads"]) for m in MODES}}
    run3 = out / "matcher-v3-run.json"
    if run3.exists():
        joined = joined_slice3(_load(run3))
        report["priors"]["slice 3 joined verdicts"] = {m: prior_rows(of_mode(m, joined), baseline, gates, frozen["ads"]) for m in MODES}
    return report


def render_replay(report: dict) -> list[str]:
    lines = [f"OFFLINE REPLAY of stored verdicts (current prompt), no model call. CAVEAT: {CAVEAT}",
             "Fit is before the engine's caps. The strict scenarios are sensitivity bounds on the tighter PARTIAL, not predictions: stored data cannot say which PARTIALs it would reject."]
    fmt = lambda e: (f"n {e['n']} (no estimate {e['noEstimate']}): median fit {e['medianFit']}; change mean {e['meanDelta']} median {e['medianDelta']} range {e['minDelta']}..{e['maxDelta']}; up {e['up']} down {e['down']} same {e['same']}; "
                     f"labels {e['labels']}; Spearman vs ran {e['spearman']}")
    for mode in MODES:
        m = report["modes"][mode]
        lines.append(f"\n== {mode.upper()}: {m['ads']} ads, stored Step 7 verdicts" + ("" if mode == MODES[0] else "  [DIAGNOSTIC ONLY]"))
        lines.append(f"  current formula: median fit {m['currentMedian']}; labels {m['currentLabels']}; Spearman vs ran {m['currentSpearman']}")
        for name, e in m["scenarios"].items():
            lines.append(f"  {name}: {fmt(e)}")
        lines.append(f"  median confidence: {m['confidence']}")
        p = m["partialAtRisk"]
        lines.append(f"  PARTIAL: {p['partial']} of {p['requirements']} requirements; strengths {p['partialStrengths']}; at strength 0-1: {p['partialStrength01']}")
        lines.append(f"  on your labelled real musts, PARTIAL lines by your answer {p['labelledPartial']}; of those at strength 0-1 {p['labelledPartialStrength01']}")
    for mode, t in report.get("twoReadings", {}).items():
        lines.append(f"\n-- two identical stored readings (full_1 + full_2), {mode}: {t['ads']} ads, {t['requirements']} requirements" + ("" if mode == MODES[0] else "  [DIAGNOSTIC ONLY]"))
        lines.append(f"  flagged {t['flagged']} = {t['flaggedShare']}; reasons {t['reasons']}; statuses {t['statuses']}")
        lines.append(f"  queue (at most {v3.QUEUE_LIMIT} per ad, musts first): {t['shownInQueue']} shown on {t['adsWithQueue']} ads, {t['overflow']} more flagged but not shown")
        lines.append(f"  aggregation against the current formula: {fmt(t['aggregationEffect'])}")
        lines.append(f"  + strict proxy: {fmt(t['strictProxyEffect'])}")
        lines.append(f"  on {t['labelled']} labelled lines: wrong {t['wrong']}, flagged {t['wrongFlaggedAnywhere']}, inside the queue {t['wrongInQueue']}. Lines both readings got wrong are not flagged.")
    for data, modes in report.get("priors", {}).items():
        for mode in MODES:
            m = modes[mode]
            lines.append(f"\n== PRIOR VARIANTS, {data}, {mode.upper()}: {m['ads']} ads; hardRequirements labels {m['hardLabels']} (0 no, 1 partial, 2 yes: heavy ties)" + ("" if mode == MODES[0] else "  [DIAGNOSTIC ONLY]"))
            for name, r in m["rows"].items():
                lines.append(f"  {name}: n {r['n']}; Spearman overall {r['spearmanOverall']}, hardRequirements {r['spearmanHard']}; median fit {r['medianFit']}; change mean {r['meanDelta']} median {r['medianDelta']}; confidence under {LOW_CONFIDENCE} in top {r['top']}: {r['lowConfidenceInTop']}")
    return lines


# --- the slice 3 dry run -------------------------------------------------------------------------------------


def dev_ads(frozen: dict, engine: dict) -> dict:
    return {j: e["mode"] for j, e in engine.items() if (frozen["ads"].get(j) or {}).get("split") == "dev" and e["output"]["requirements"]}


def build_requests(out: Path, profile: dict, intelligence: dict, chosen: dict) -> dict:
    """One prompt per ad, the same for both readings. Nothing is sent."""
    ads = {i["jobId"]: i for i in _load(out / "review-items.json")["items"]}
    facts = _load(out / "enrichment-facts.json")["facts"]
    remap = load_remap(out / "requirement-remap.json")
    candidate, aliases = alias_unsafe_ids(build_candidate(profile, intelligence, load_confirmed_facts()), profile)
    identity = identity_of(profile)
    requests = {}
    for job_id in chosen:
        posting = matcher.posting_from_job({**sanitized(ads[job_id]), "llmFacts": facts[job_id]}, remap)
        requests[job_id] = v3.prepare(posting, candidate, identity)
    leaks = {j: kinds for j, r in requests.items() if (kinds := owner_leaks(r["prompt"], profile))}
    return {"requests": requests, "leaks": leaks, "evidenceItems": len(candidate["evidence"]), "idAliases": len(aliases), "candidate": candidate}


def estimate(requests: dict, price: dict) -> dict:
    """Per reading and in total. `upperBound`: 3 characters per token, no cache discount, the output envelope times the assumed schema factor."""
    chars = sum(len(r["prompt"]) for r in requests.values())
    output = round(sum((OUTPUT_BASE + OUTPUT_PER_REQUIREMENT * len(r["asked"])) * NEW_SCHEMA_OUTPUT_FACTOR for r in requests.values()))
    upper_in, expected_in = round(chars / UPPER_CHARS_PER_TOKEN), round(chars / MEASURED_CHARS_PER_TOKEN)
    out_usd = output * price["out"] / 1e6
    return {"ads": len(requests), "calls": len(requests) * READINGS, "inputPerReadingExpected": expected_in, "inputPerReadingUpper": upper_in, "outputPerReadingReserved": output,
            "expected": round(expected_in * price["in"] / 1e6 * (1 + CACHED_INPUT_SHARE) + out_usd * READINGS, 4),
            "upperBound": round(upper_in * price["in"] / 1e6 * READINGS + out_usd * READINGS, 4)}


def render_estimate(built: dict, chosen: dict, est: dict, price: dict) -> list[str]:
    settings = ai_gate.load_settings()
    t = ai_gate.totals(None, settings)
    n = len(built["requests"])
    return [f"NOT SENT: dry run. Slice 3: dev set, {n} ads {dict(Counter(chosen.values()))}, two identical readings, {est['calls']} calls; prompt {v3.PROMPT_ID}; evidence items per call {built['evidenceItems']} ({built['idAliases']} hash ids aliased for the scan)",
            f"model: {price['provider']}/{price['model']} ({price['tier']}), low reasoning effort, full question set per ad, no batching",
            f"per reading: input about {est['inputPerReadingExpected']} tokens (upper bound {est['inputPerReadingUpper']}); output reserved {est['outputPerReadingReserved']} (measured envelope times an assumed {NEW_SCHEMA_OUTPUT_FACTOR}x for the new fields)",
            f"estimated cost: ${est['expected']:.4f} expected (second reading's input at the cached price, as measured in slice 1), ${est['upperBound']:.4f} upper bound (no cache) at ${price['in']}/{price['out']} per 1M tokens",
            f"proposed hard cap: ${PROPOSED_CAP_USD:.2f}: upper bound is {'WITHIN' if est['upperBound'] <= PROPOSED_CAP_USD else 'OVER'} it",
            f"budget: daily left ${round(float(settings['dailyLimit']) - t['today']['cost'], 4)}, monthly left ${round(float(settings['monthlyLimit']) - t['thisMonth']['cost'], 4)}",
            f"privacy scan: {n - len(built['leaks'])} of {n} prompts pass (each prompt is sent twice, identical)" + ("" if not built["leaks"] else "; FAILED kinds: " + "; ".join(sorted({k for ks in built["leaks"].values() for k in ks})))]


def price_now() -> dict:
    selection = ai_selection.require()
    provider, model = selection["provider"], selection["model"]
    price = ai_gate.classify(provider, model, selection.get("baseUrl") or None, tier=service_tier_for(provider))
    return {"provider": provider, "model": model, "tier": price.get("tier"), "in": price.get("inputPerMTok"), "out": price.get("outputPerMTok")}


def main(argv=None) -> int:
    ap_ = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap_.add_argument("command", choices=("replay", "estimate"))
    ap_.add_argument("--out", type=Path, default=STAGE_DIR)
    args = ap_.parse_args(argv)
    frozen = load_frozen(args.out)
    if args.command == "replay":
        print("\n".join(render_replay(replay(args.out, frozen, _load(args.out / "must-sample.json")))))
        return 0
    chosen = dev_ads(frozen, _load(args.out / "engine-shadow.json")["ads"])
    built = build_requests(args.out, _load(PROFILE_PATH), _load(INTELLIGENCE_PATH), chosen)
    price = price_now()
    print("\n".join(render_estimate(built, chosen, estimate(built["requests"], price), price)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
