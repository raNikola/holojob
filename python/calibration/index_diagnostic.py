#!/usr/bin/env python3
"""P1 Stage B, S2 (free part): what is missing from the engine's evidence index, and why 11 verdicts may have been wrong.

    python python/calibration/index_diagnostic.py sources    # profile sources vs the 83-item index (counts only)
    python python/calibration/index_diagnostic.py classify   # the lines where the engine said MISSING / UNKNOWN but ran meets it
    python python/calibration/index_diagnostic.py estimate   # the paid diagnostic, built and scanned but NEVER sent
    python python/calibration/index_diagnostic.py run --yes  # PAID; only after the owner's explicit approval; hard maximum $0.05
    python python/calibration/index_diagnostic.py analyse    # what the result shows (free: reads the stored results)

`sources`, `classify`, `estimate` and `analyse` call no model. `run` is refused without --yes, stops before any call on a scan hit or an
estimate over the cap, and counts every call (a matcher retry included) against the cap. Every command prints counts, ids and kinds only,
never ad, profile or CV text.

`classify` puts each line in exactly one class and uses (d) whenever the stored data cannot tell the cases apart:
  (a) the evidence exists in a source the index does not hold (summary, questionnaire answers, derived intelligence text)
  (b) the evidence exists in the index but the matcher missed it
  (c) the candidate has related, transferable evidence only (ran said "partly" and an indexed item shares one distinctive word)
  (d) insufficient evidence to conclude
It is a lexical triage on distinctive words (words common to many profile items are ignored; no word list). A line is (a) or (b) only
when at least two distinctive words of the requirement, and at least half of them, occur together in one single item. It cannot read
meaning, so most lines are expected to stay (d); that is the honest answer, not a failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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

import ai_gate  # noqa: E402
import ai_selection  # noqa: E402
from competency_mapping import load_remap  # noqa: E402
from confirmed_facts import load as load_confirmed_facts  # noqa: E402
from evidence_index import build_candidate, evidence_id  # noqa: E402
from job_fingerprint import job_fingerprint  # noqa: E402
from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic  # noqa: E402
from llm_client import GuardrailRefused, LlmUnavailable, complete_json, preflight, service_tier_for  # noqa: E402
from match_engine import matcher  # noqa: E402
from redact import identity_of, redact_cv_text  # noqa: E402
from text_utils import normalize_text  # noqa: E402
from calibration.engine_sample import (  # noqa: E402
    OUTPUT_BASE, OUTPUT_PER_REQUIREMENT, alias_unsafe_ids, sanitized, tokens_of,
)
from calibration.eval_set import STAGE_DIR, load as load_frozen  # noqa: E402
from calibration.prelabel import owner_leaks  # noqa: E402

PROFILE_PATH = ROOT / "data" / "profile" / "candidate-profile.json"
INTELLIGENCE_PATH = ROOT / "data" / "intelligence" / "candidate-intelligence.json"
GENERIC_SHARE = 0.15  # a word found in more than this share of all profile units says nothing distinctive
GENERIC_MIN_UNITS = 3
RESULTS_NAME = "index-diagnostic.json"
FEATURE = "evidence-matcher"
HARD_STOP_USD = 0.05  # the owner's cap for this one batch; a matcher retry counts against it
VARIANTS = ("control (existing index only)", "index + summary sentences")
MIN_SHARED, MIN_SHARE_OF_REQUIREMENT = 2, 0.5
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _strings(value) -> list[str]:
    return [str(v).strip() for v in value if str(v or "").strip()] if isinstance(value, list) else []


# --- sources ------------------------------------------------------------------------------------


def inventory(profile: dict, intelligence: dict, evidence: list[dict], confirmed: list) -> list[dict]:
    """The profile's sources against the index. Counts only; `decision` follows the owner's list of allowed sources."""
    parsed = ((profile.get("resume") or {}).get("parsedData")) or {}
    experience = intelligence.get("experienceMap") or {}
    indexed = Counter(e["source"] for e in evidence)
    answers = _strings([a.get("answer") for a in ((profile.get("questionnaire") or {}).get("answers") or []) if isinstance(a, dict)])
    derived = _strings([(intelligence.get("candidateSummary") or {}).get(k) for k in ("careerNarrative", "oneLinePitch", "positioningStatement")])
    detail = [d for d in parsed.get("experienceDetail") or [] if isinstance(d, dict)]
    bullets = sum(len(_strings(d.get("bullets"))) + (1 if isinstance(d.get("description"), str) and d["description"].strip() else 0) for d in detail)
    projects = len(_strings(parsed.get("projects"))) + len(_strings(experience.get("projectHighlights")))
    examples = sum(len(_strings(experience.get(k))) for k in ("ownershipExamples", "leadershipExamples", "businessImpactExamples"))
    repos = (profile.get("repositories") or {})
    rows = [
        {"source": "work history (bullets)", "entries": bullets, "inIndex": indexed["role"], "decision": "allowed (CV, work history)"},
        {"source": "skills, competencies, education, certifications", "entries": len(_strings(parsed.get("skills"))) + len(_strings(parsed.get("education")))
         + len(_strings(parsed.get("certifications"))), "inIndex": indexed["fact"], "decision": "allowed (CV)"},
        {"source": "summary text", "entries": len(SENTENCE_END.split(str(parsed.get("summary") or "").strip())) if str(parsed.get("summary") or "").strip() else 0,
         "chars": len(str(parsed.get("summary") or "")), "inIndex": 0, "decision": "allowed (CV); candidate for the diagnostic"},
        {"source": "projects (parsed or project highlights)", "entries": projects, "inIndex": indexed["project"],
         "decision": "allowed (projects); the profile holds none, so there is nothing to index"},
        {"source": "ownership / leadership / impact examples", "entries": examples, "inIndex": indexed["example"], "decision": "allowed; the profile holds none"},
        {"source": "questionnaire answers", "entries": len(answers), "inIndex": 0,
         "decision": "only answers the owner explicitly confirms; the store has no per-answer confirmed flag, so none qualifies yet"},
        {"source": "confirmed facts (owner answers to engine questions)", "entries": len(confirmed), "inIndex": 0,
         "decision": "allowed; used locally by the engine, never sent"},
        {"source": "GitHub", "entries": len(_strings(repos.get("githubLinks"))), "inIndex": 0,
         "decision": "extra evidence only, never a confirmation; the link is a personal link (never sent) and no analysed project content exists"},
        {"source": "other CVs in the library", "entries": max(0, len(profile.get("cvLibrary") or []) - 1), "inIndex": 0, "decision": "allowed (CV); none exist"},
        {"source": "derived intelligence text (narrative, pitch, positioning)", "entries": len(derived), "inIndex": 0,
         "decision": "not on the owner's list: text a model wrote about the CV, not the CV"},
    ]
    return rows


def render_sources(rows: list[dict], evidence: list[dict]) -> list[str]:
    lines = [f"evidence index: {len(evidence)} items by source {dict(Counter(e['source'] for e in evidence))}",
             "profile sources against the index (counts only):"]
    for r in rows:
        extra = f", {r['chars']} chars" if "chars" in r else ""
        lines.append(f"  {r['source']:58} entries {r['entries']:3}{extra}; in the index {r['inIndex']:3}; {r['decision']}")
    return lines


# --- classification of the understated lines -------------------------------------------------------


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#]{4,}", normalize_text(text or "")))


def generic_words(units: list[set[str]]) -> set[str]:
    """Words found in at least GENERIC_MIN_UNITS units and in more than GENERIC_SHARE of all of them say nothing distinctive and are
    dropped before matching. Derived from the data, no word list; the minimum count keeps a small profile from calling a one-off word common."""
    df = Counter(w for u in units for w in u)
    return {w for w, n in df.items() if n >= GENERIC_MIN_UNITS and n / max(1, len(units)) > GENERIC_SHARE}


def classify_line(req_tokens: set[str], indexed: list[set[str]], unindexed: list[tuple[str, set[str]]], ran_meets: str) -> tuple[str, str | None]:
    """(class, zone). Exactly one of "a", "b", "c", "d"."""
    need = max(MIN_SHARED, -(-len(req_tokens) // 2)) if req_tokens else 99
    strong_index = any(len(req_tokens & u) >= need and len(req_tokens & u) >= MIN_SHARED for u in indexed)
    strong_other = [zone for zone, u in unindexed if len(req_tokens & u) >= need and len(req_tokens & u) >= MIN_SHARED]
    if strong_index:
        return "b", "index"
    if strong_other:
        return "a", strong_other[0]
    if ran_meets == "partial" and any(len(req_tokens & u) == 1 for u in indexed):
        return "c", "index"
    return "d", None


def understated_lines(frozen: dict, sample: dict) -> list[dict]:
    """The real musts where the engine said MISSING or UNKNOWN and ran says yes or partly."""
    items = {i["itemId"]: i for i in sample["items"]}
    out = []
    for item_id, line in frozen["lines"].items():
        if line["probe"] or line["first"]["isMust"] != "yes":
            continue
        item = items[item_id]
        if item["verdict"]["status"] in ("MISSING", "UNKNOWN") and line["first"]["meets"] in ("yes", "partial"):
            out.append({"itemId": item_id, "item": item, "meets": line["first"]["meets"], "mode": line["mode"]})
    return out


def classify(profile: dict, intelligence: dict, evidence: list[dict], lines: list[dict]) -> list[dict]:
    parsed = ((profile.get("resume") or {}).get("parsedData")) or {}
    unindexed_raw = [("summary", s) for s in SENTENCE_END.split(str(parsed.get("summary") or "")) if s.strip()]
    unindexed_raw += [("questionnaire", str(a.get("answer") or "")) for a in ((profile.get("questionnaire") or {}).get("answers") or []) if isinstance(a, dict)]
    unindexed_raw += [("derived", t) for t in _strings([(intelligence.get("candidateSummary") or {}).get(k) for k in ("careerNarrative", "oneLinePitch", "positioningStatement")])]
    index_units = [tokens(e["text"]) for e in evidence]
    other_units = [(zone, tokens(text)) for zone, text in unindexed_raw]
    generic = generic_words(index_units + [u for _, u in other_units])
    index_units = [u - generic for u in index_units]
    other_units = [(z, u - generic) for z, u in other_units]
    return [{**line, **dict(zip(("class", "zone"), classify_line(tokens(line["item"]["text"]) - generic, index_units, other_units, line["meets"])))}
            for line in lines]


def render_classes(rows: list[dict]) -> list[str]:
    counts = Counter(r["class"] for r in rows)
    lines = [f"{len(rows)} lines where the engine said MISSING or UNKNOWN and ran meets it (yes {sum(1 for r in rows if r['meets'] == 'yes')}, "
             f"partly {sum(1 for r in rows if r['meets'] == 'partial')})",
             "classes: " + ", ".join(f"({c}) {counts.get(c, 0)}" for c in "abcd"),
             "  (a) evidence in an unindexed source  (b) in the index but missed  (c) transferable only  (d) cannot tell from the stored data"]
    for r in rows:
        lines.append(f"  {r['itemId']}  {r['mode']:15} {r['item']['kind']:10} engine {r['item']['verdict']['status']:8} ran {r['meets']:8} -> ({r['class']})"
                     + (f" {r['zone']}" if r["zone"] else ""))
    return lines


# --- the proposed paid diagnostic (never sent) ---------------------------------------------------------


def summary_items(profile: dict, identity) -> list[dict]:
    name, links = identity
    parsed = ((profile.get("resume") or {}).get("parsedData")) or {}
    out = []
    for sentence in SENTENCE_END.split(str(parsed.get("summary") or "").strip()):
        text, _ = redact_cv_text(sentence.strip(), name, links)
        if text:
            out.append({"id": evidence_id("summary", None, text), "source": "summary", "role": None, "start": None, "end": None, "text": text, "strength": 2})
    return out


def diagnostic_selection(frozen: dict, sample: dict) -> dict[str, set]:
    """{jobId: {requirement ids}}: real musts the engine understated: MISSING or UNKNOWN where ran meets it fully or partly,
    and PARTIAL where ran says yes."""
    items = {i["itemId"]: i for i in sample["items"]}
    chosen: dict[str, set] = {}
    for item_id, line in frozen["lines"].items():
        if line["probe"] or line["first"]["isMust"] != "yes":
            continue
        item, meets = items[item_id], line["first"]["meets"]
        if (item["verdict"]["status"] in ("MISSING", "UNKNOWN") and meets in ("yes", "partial")) or (item["verdict"]["status"] == "PARTIAL" and meets == "yes"):
            chosen.setdefault(item["jobId"], set()).add(item["reqId"])
    return chosen


class _Captured(LlmUnavailable):
    pass


def build_requests(out: Path, profile: dict, intelligence: dict, extra: list[dict], selection: dict[str, set]) -> dict:
    """One matcher prompt per ad, built exactly as the matcher builds it, for the selected requirements only. Nothing is sent."""
    ads = {i["jobId"]: i for i in _load(out / "review-items.json")["items"]}
    facts = _load(out / "enrichment-facts.json")["facts"]
    remap = load_remap(out / "requirement-remap.json")
    candidate = build_candidate(profile, intelligence, load_confirmed_facts())
    candidate = {**candidate, "evidence": candidate["evidence"] + extra}
    candidate, aliases = alias_unsafe_ids(candidate, profile)
    identity = identity_of(profile)
    prompts, asked, postings = {}, {}, {}
    for job_id, wanted in selection.items():
        job = {**sanitized(ads[job_id]), "llmFacts": facts[job_id]}
        posting = matcher.posting_from_job(job, remap)
        posting["facts"]["requirements"] = [r for r in posting["facts"]["requirements"] if r["id"] in wanted]
        captured = []

        def capture(prompt, schema=None, model=None, provider=None, _c=captured):
            _c.append(prompt)
            raise _Captured("dry run")

        matcher.match_posting(posting, candidate, confirmed=True, provider="openai", model=None, complete=capture, identity=identity)
        if captured:
            prompts[job_id] = captured[0]
            asked[job_id] = len(posting["facts"]["requirements"])
            postings[job_id] = posting
    leaks = {j: kinds for j, text in prompts.items() if (kinds := owner_leaks(text, profile))}
    return {"prompts": prompts, "asked": asked, "leaks": leaks, "evidenceItems": len(candidate["evidence"]), "idAliases": len(aliases),
            "postings": postings, "candidate": candidate, "identity": identity, "aliases": aliases}


def price_and_budget(prompts: dict, asked: dict) -> dict:
    selection = ai_selection.require()
    provider, model = selection["provider"], selection["model"]
    price = ai_gate.classify(provider, model, selection.get("baseUrl") or None, tier=service_tier_for(provider))
    in_tokens = sum(tokens_of(len(p)) for p in prompts.values())
    out_tokens = sum(OUTPUT_BASE + OUTPUT_PER_REQUIREMENT * asked[j] for j in prompts)
    cost = round(in_tokens * price["inputPerMTok"] / 1e6 + out_tokens * price["outputPerMTok"] / 1e6, 4) if price.get("priceKnown") else None
    settings = ai_gate.load_settings()
    t = ai_gate.totals(None, settings)
    return {"provider": provider, "model": model, "tier": price.get("tier"), "inputTokens": in_tokens, "outputTokens": out_tokens, "costUsd": cost,
            "priceIn": price.get("inputPerMTok"), "priceOut": price.get("outputPerMTok"),
            "dailyLeft": round(float(settings["dailyLimit"]) - t["today"]["cost"], 4), "monthlyLeft": round(float(settings["monthlyLimit"]) - t["thisMonth"]["cost"], 4),
            "callsLeftToday": None if ai_gate._call_cap(settings.get("maxCallsDaily")) is None else ai_gate._call_cap(settings.get("maxCallsDaily")) - t["today"]["paidCalls"]}


def render_estimate(selection: dict, variants: dict) -> list[str]:
    lines = [f"selection: {sum(len(v) for v in selection.values())} requirement lines in {len(selection)} ads (real musts the engine understated: MISSING or "
             "UNKNOWN where ran meets it fully or partly, PARTIAL where ran says yes)",
             "prompt: the existing evidence-matcher prompt (matcher.PROMPT, MATCH_PROMPT_VERSION unchanged), one call per ad, only the selected requirements asked",
             "NOT SENT. This is a dry run: every request below was built and scanned locally, and no model was called."]
    for name, v in variants.items():
        b, r = v["budget"], v["requests"]
        cost = f"${b['costUsd']:.4f}" if b["costUsd"] is not None else "unknown"
        lines += [f"\nvariant {name}: {len(r['prompts'])} calls, evidence items per call {r['evidenceItems']} ({r['idAliases']} hash ids aliased for the scan)",
                  f"  input tokens about {b['inputTokens']} (UPPER BOUND, 3 characters per token); output {b['outputTokens']} reserved (an assumption); "
                  f"estimated cost {cost} at ${b['priceIn']}/{b['priceOut']} per 1M tokens on {b['provider']}/{b['model']} ({b['tier']}), no cache discount",
                  f"  budget: daily left ${b['dailyLeft']} of the $1 limit, monthly left ${b['monthlyLeft']}, paid calls left today {'no limit set' if b['callsLeftToday'] is None else b['callsLeftToday']}",
                  f"  privacy scan: {len(r['prompts']) - len(r['leaks'])} of {len(r['prompts'])} requests pass" + (
                      "" if not r["leaks"] else "; FAILED kinds: " + "; ".join(sorted({k for ks in r['leaks'].values() for k in ks})))]
    total_calls = sum(len(v["requests"]["prompts"]) for v in variants.values())
    costs = [v["budget"]["costUsd"] for v in variants.values()]
    if None not in costs:
        lines.append(f"\nall variants together: {total_calls} calls, estimated ${sum(costs):.4f} (upper bound); hard maximum for the batch ${HARD_STOP_USD:.2f}"
                     f"; {'WITHIN the maximum' if sum(costs) <= HARD_STOP_USD else 'OVER the maximum: stop and ask'}")
    return lines


# --- the paid run (only after the owner's explicit approval) -------------------------------------------------


class ResultStore:
    """index-diagnostic.json: one entry per (variant, ad), written atomically after every call, so a stopped run keeps what it paid for."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data = {"version": 1, "variants": {}}
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("variants"), dict):
                self.data = loaded

    def done(self, variant: str, job_id: str, prompt_hash: str) -> bool:
        entry = (self.data["variants"].get(variant) or {}).get(job_id) or {}
        return entry.get("promptHash") == prompt_hash and bool(entry.get("requirements"))

    def put(self, variant: str, job_id: str, entry: dict) -> None:
        with self._lock:
            self.data["variants"].setdefault(variant, {})[job_id] = entry
            self.data["updatedAt"] = datetime.now(timezone.utc).isoformat()
            make_private_dirs(self.path.parent)
            write_text_atomic(self.path, json.dumps(self.data, indent=2, ensure_ascii=False), PRIVATE_FILE_MODE)


def run(out: Path, profile: dict, intelligence: dict, frozen: dict, sample: dict, workers: int = 4, complete=complete_json) -> dict:
    """The approved diagnostic: control and summary variants, one call per ad each. Stops before any call on a scan hit or an estimate over
    HARD_STOP_USD; counts every call, a matcher retry included, at its worst-case cost against the cap; resumes from the store."""
    selection = diagnostic_selection(frozen, sample)
    identity = identity_of(profile)
    variants = {}
    for name, extra in zip(VARIANTS, ([], summary_items(profile, identity))):
        requests = build_requests(out, profile, intelligence, extra, selection)
        variants[name] = {"requests": requests, "budget": price_and_budget(requests["prompts"], requests["asked"])}
    if any(v["requests"]["leaks"] for v in variants.values()):
        return {"stopped": "privacy scan found owner identifiers; nothing was sent", "asked": 0}
    costs = [v["budget"]["costUsd"] for v in variants.values()]
    if None in costs:
        return {"stopped": "no price for this model; nothing was sent", "asked": 0}
    if sum(costs) > HARD_STOP_USD:
        return {"stopped": f"estimate ${sum(costs):.4f} is over the hard maximum ${HARD_STOP_USD:.2f}; nothing was sent", "asked": 0}
    store = ResultStore(out / RESULTS_NAME)
    work = []
    for name, v in variants.items():
        for job_id, prompt in v["requests"]["prompts"].items():
            if not store.done(name, job_id, hashlib.sha256(prompt.encode("utf-8")).hexdigest()):
                work.append((name, job_id))
    if not work:
        return {"stopped": None, "asked": 0, "ok": 0, "failed": 0, "refused": 0, "modelCalls": 0, "retries": 0}
    selection_ai = ai_selection.require()
    provider, model = selection_ai["provider"], selection_ai["model"]
    price = variants[VARIANTS[0]]["budget"]
    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    longest = max(len(variants[n]["requests"]["prompts"][j]) for n, j in work)
    with ai_gate.context(feature=FEATURE):
        decision = preflight(longest, provider, model)
    if not decision.allowed:
        ai_gate.record_refused(decision, skipped=len(work))
        return {"stopped": f"AI gate refused: {decision.reason}", "asked": 0}
    stop, lock = threading.Event(), threading.Lock()
    spent = {"calls": 0, "usd": 0.0, "reason": None}
    counts = {"ok": 0, "failed": 0, "refused": 0}

    def one(variant: str, job_id: str) -> str:
        if stop.is_set():
            return "refused"
        req = variants[variant]["requests"]

        def guarded(prompt, schema=None, model=None, provider=None):
            if owner_leaks(prompt, profile):  # again, on the exact text about to leave
                stop.set()
                spent["reason"] = "privacy scan hit on an outgoing request"
                raise GuardrailRefused(spent["reason"])
            worst = (tokens_of(len(prompt)) * price["priceIn"] + (OUTPUT_BASE + OUTPUT_PER_REQUIREMENT * req["asked"][job_id]) * price["priceOut"]) / 1e6
            with lock:
                if spent["usd"] + worst > HARD_STOP_USD:
                    stop.set()
                    spent["reason"] = f"the next call could pass the ${HARD_STOP_USD:.2f} cap"
                    raise GuardrailRefused(spent["reason"])
                spent["usd"] += worst
                spent["calls"] += 1
            return complete(prompt, schema=schema, model=model, provider=provider)

        try:
            outcome = matcher.match_posting(req["postings"][job_id], req["candidate"], confirmed=True, provider=provider, model=model,
                                            complete=guarded, identity=req["identity"])
        except GuardrailRefused:
            stop.set()
            return "refused"
        if outcome.output is None:
            return "failed"
        store.put(variant, job_id, {"promptHash": hashlib.sha256(req["prompts"][job_id].encode("utf-8")).hexdigest(), "at": datetime.now(timezone.utc).isoformat(),
                                    "requirements": outcome.output["requirements"], "evidenceIdAliases": req["aliases"], "extraEvidenceIds": [e["id"] for e in req["candidate"]["evidence"] if e["source"] not in ("role", "fact")]})
        return "ok"

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for future in as_completed([pool.submit(one, v, j) for v, j in work]):
            counts[future.result()] += 1
    return {"stopped": spent["reason"], "asked": len(work), **counts, "modelCalls": spent["calls"],
            "retries": max(0, spent["calls"] - counts["ok"] - counts["failed"])}


# --- reading the result (free: stored files only) -------------------------------------------------------------

ORDER = {"MISSING": 0, "UNKNOWN": 0, "PARTIAL": 1, "MET": 2}  # silence and absence rank together, below partial, below met
TARGET = {"yes": 2, "partial": 1}  # ran's answer as the verdict level it points at
GROUPS = ("understated (MISSING/UNKNOWN where ran meets it)", "PARTIAL where ran said yes")


def _move(before: str, after: str, target: int) -> str:
    """toward / away / unchanged / sideways (the verdict changed but is no nearer or farther from ran's answer)."""
    if before == after:
        return "unchanged"
    b, a = abs(ORDER[before] - target), abs(ORDER[after] - target)
    return "toward" if a < b else "away" if a > b else "sideways"


def analyse(out: Path, frozen: dict, sample: dict) -> dict:
    """Per line: the Step 7 verdict, the control verdict and the summary verdict, against ran's answer. Counts and rates only."""
    results = (_load(out / RESULTS_NAME) if (out / RESULTS_NAME).exists() else {"variants": {}})["variants"]
    items = {i["itemId"]: i for i in sample["items"]}
    selection = diagnostic_selection(frozen, sample)
    rows = []
    for item_id, line in frozen["lines"].items():
        item = items[item_id]
        if item["reqId"] not in selection.get(item["jobId"], set()) or line["probe"] or line["first"]["isMust"] != "yes":
            continue
        stored = item["verdict"]["status"]
        group = GROUPS[1] if stored == "PARTIAL" else GROUPS[0]
        row = {"itemId": item_id, "group": group, "mode": line["mode"], "kind": item["kind"], "ran": line["first"]["meets"], "step7": stored}
        for name, key in zip(VARIANTS, ("control", "summary")):
            entry = (results.get(name) or {}).get(item["jobId"]) or {}
            match = next((r for r in entry.get("requirements") or [] if r["id"] == item["reqId"]), None)
            row[key] = match["status"] if match else None
            row[key + "Evidence"] = (match or {}).get("evidenceId")
        rows.append(row)
    extra_ids = {i for entry in (results.get(VARIANTS[1]) or {}).values() for i in entry.get("extraEvidenceIds") or []}

    def tally(subset, a, b, label):
        pairs = [(r, _move(r[a], r[b], TARGET[r["ran"]])) for r in subset if r[a] and r[b]]
        c = Counter(m for _, m in pairs)
        return {"n": len(pairs), "toward": c["toward"], "away": c["away"], "sideways": c["sideways"], "unchanged": c["unchanged"], "comparison": label}

    report = {"lines": len(rows), "groups": {}, "notRun": sum(1 for r in rows if r["control"] is None or r["summary"] is None)}
    for group in (None, *GROUPS):
        subset = [r for r in rows if group is None or r["group"] == group]
        key = group or "all 17"
        report["groups"][key] = {
            "n": len(subset),
            "step7 vs control (same evidence, same ad; only the other requirements differ)": tally(subset, "step7", "control", "noise"),
            "control vs summary (what the summary changes)": tally(subset, "control", "summary", "summary"),
            "step7 vs summary (total movement)": tally(subset, "step7", "summary", "total"),
            "control matches ran (MET for yes, PARTIAL for partly)": sum(1 for r in subset if r["control"] and ORDER[r["control"]] == TARGET[r["ran"]]),
            "summary matches ran": sum(1 for r in subset if r["summary"] and ORDER[r["summary"]] == TARGET[r["ran"]]),
            "step7 matches ran": sum(1 for r in subset if ORDER[r["step7"]] == TARGET[r["ran"]]),
        }
    report["summaryCitedByAnsweredLines"] = sum(1 for r in rows if r["summaryEvidence"] in extra_ids)
    report["verdictCounts"] = {k: dict(Counter(r[k] for r in rows)) for k in ("step7", "control", "summary")}
    report["rows"] = rows
    return report


def render_analysis(report: dict) -> list[str]:
    lines = [f"diagnostic of the CURRENT matcher on {report['lines']} lines ({report['notRun']} not run); the profile has no structured projects, so this does NOT measure "
             "the value of a complete profile. Small n: read each rate with its n.",
             "verdict levels: MISSING and UNKNOWN rank together below PARTIAL below MET; ran's yes points at MET, partly at PARTIAL",
             f"verdict counts: {report['verdictCounts']}",
             f"lines where the summary variant cited a summary sentence as its evidence: {report['summaryCitedByAnsweredLines']} of {report['lines']}"]
    for group, g in report["groups"].items():
        lines.append(f"\n{group}: n {g['n']}")
        lines.append(f"  matches ran's answer exactly: Step 7 {g['step7 matches ran']}/{g['n']}, control {g['control matches ran (MET for yes, PARTIAL for partly)']}/{g['n']}, "
                     f"summary {g['summary matches ran']}/{g['n']}")
        for key in ("step7 vs control (same evidence, same ad; only the other requirements differ)", "control vs summary (what the summary changes)", "step7 vs summary (total movement)"):
            t = g[key]
            lines.append(f"  {key}: n {t['n']}: toward ran {t['toward']}, away {t['away']}, sideways {t['sideways']}, unchanged {t['unchanged']}")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=("sources", "classify", "estimate", "run", "analyse"))
    ap.add_argument("--out", type=Path, default=STAGE_DIR)
    ap.add_argument("--yes", action="store_true", help="make the paid calls (run only); needs the owner's explicit approval")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args(argv)
    if args.command == "run" and not args.yes:
        print("nothing sent: `run` makes paid calls and needs --yes after the owner's explicit approval; use `estimate` first")
        return 0
    profile, intelligence = _load(PROFILE_PATH), _load(INTELLIGENCE_PATH)
    candidate = build_candidate(profile, intelligence, load_confirmed_facts())
    frozen, sample = load_frozen(args.out), _load(args.out / "must-sample.json")
    if args.command == "sources":
        print("\n".join(render_sources(inventory(profile, intelligence, candidate["evidence"], candidate["confirmedFacts"]), candidate["evidence"])))
    elif args.command == "classify":
        print("\n".join(render_classes(classify(profile, intelligence, candidate["evidence"], understated_lines(frozen, sample)))))
    elif args.command == "analyse":
        print("\n".join(render_analysis(analyse(args.out, frozen, sample))))
    elif args.command == "run":
        result = run(args.out, profile, intelligence, frozen, sample, args.workers)
        print(json.dumps(result))
        return 1 if result.get("stopped") else 0
    else:
        selection = diagnostic_selection(frozen, sample)
        identity = identity_of(profile)
        variants = {}
        for name, extra in (("control (existing index only)", []), ("index + summary sentences", summary_items(profile, identity))):
            requests = build_requests(args.out, profile, intelligence, extra, selection)
            variants[name] = {"requests": requests, "budget": price_and_budget(requests["prompts"], requests["asked"])}
        print("\n".join(render_estimate(selection, variants)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
