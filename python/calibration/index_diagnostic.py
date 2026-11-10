#!/usr/bin/env python3
"""P1 Stage B, S2 (free part): what is missing from the engine's evidence index, and why 11 verdicts may have been wrong.

    python python/calibration/index_diagnostic.py sources    # profile sources vs the 83-item index (counts only)
    python python/calibration/index_diagnostic.py classify   # the lines where the engine said MISSING / UNKNOWN but ran meets it
    python python/calibration/index_diagnostic.py estimate   # the proposed paid diagnostic, built and scanned but NEVER sent

There is no `run` command on purpose. The paid diagnostic needs the owner's explicit approval first, and is a separate piece of work.
Nothing here calls a model; every command prints counts, ids and kinds only, never ad, profile or CV text.

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
import json
import re
import sys
from collections import Counter
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
from llm_client import LlmUnavailable, service_tier_for  # noqa: E402
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
    prompts, asked = {}, {}
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
    leaks = {j: kinds for j, text in prompts.items() if (kinds := owner_leaks(text, profile))}
    return {"prompts": prompts, "asked": asked, "leaks": leaks, "evidenceItems": len(candidate["evidence"]), "idAliases": len(aliases)}


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
            "callsLeftToday": ai_gate._call_cap(settings.get("maxCallsDaily")) - t["today"]["paidCalls"]}


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
                  f"  budget: daily left ${b['dailyLeft']} of the $1 limit, monthly left ${b['monthlyLeft']}, paid calls left today {b['callsLeftToday']}",
                  f"  privacy scan: {len(r['prompts']) - len(r['leaks'])} of {len(r['prompts'])} requests pass" + (
                      "" if not r["leaks"] else "; FAILED kinds: " + "; ".join(sorted({k for ks in r['leaks'].values() for k in ks})))]
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=("sources", "classify", "estimate"))
    ap.add_argument("--out", type=Path, default=STAGE_DIR)
    args = ap.parse_args(argv)
    profile, intelligence = _load(PROFILE_PATH), _load(INTELLIGENCE_PATH)
    candidate = build_candidate(profile, intelligence, load_confirmed_facts())
    frozen, sample = load_frozen(args.out), _load(args.out / "must-sample.json")
    if args.command == "sources":
        print("\n".join(render_sources(inventory(profile, intelligence, candidate["evidence"], candidate["confirmedFacts"]), candidate["evidence"])))
    elif args.command == "classify":
        print("\n".join(render_classes(classify(profile, intelligence, candidate["evidence"], understated_lines(frozen, sample)))))
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
