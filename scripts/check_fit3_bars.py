#!/usr/bin/env python3
"""W5 pre-registered bars B1-B5 (~/holojob-eval/w5-plan.md, A1.7), computed offline from stored passes. NO model call, NO provider, writes nothing.

    .venv/bin/python scripts/check_fit3_bars.py --pass1 classification.json --pass2 classification-pass2.json --labels ~/holojob-eval/w5-labels.json

--scratch DIR   default /home/ranikola/holojob-eval/holdout-scratch-data: the ad text (jobs/discovered_jobs.json) and the intelligence copy are read from it.
--ids FILE      the ads read for holdout v1 (default holdout-ids-18.json); --denominator N (default 20) is the holdout size, an ad that has no text counts as not evaluable.
--pass1 / --pass2  files under <scratch>/fit3/ (a classification, or a store merged with the matcher answers by merge_fit3_answers.py). B1-B4 need only the
                replies; B5 needs `answers` (UNKNOWN units put an ad into the Insufficient group, so B5 is then "not evaluable" or fails honestly).
--labels FILE   the owner's labels, kept OUTSIDE the repo: {"apply": [ad ids or company substrings], "fitSkip": [...], "expectTarget": [...], "expectOther": [...]}.
                An id is matched exactly, a substring case-insensitively against the company. An APPLY ad with no text (Monzo) is a miss (A2.1).

A failed bar is reported as failed. A bar that cannot be computed is "not evaluable", never a pass. Console: counts, ad ids and public company names.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_fit3 as m3  # noqa: E402

TOP = 6
MAX_FLIPS, MIN_MEDIAN_OVERLAP, MIN_CORE_SHARE, MAX_MISSING_QUOTES = 2, 0.80, 0.90, 0.25
NOT_AVAILABLE = "not available"


def load_ads(scratch: Path, ids: list[str]) -> dict[str, dict]:
    """{id: {"posting", "facts"}} for the ads that have text, read as measure_fit3 reads them (the list, then the history ledger)."""
    import measure_extraction_variance as mv
    rows, _missing = mv.load_jobs(scratch, ids)
    return {r["jobId"]: {"posting": m3.posting_of(r), "facts": r.get("llmFacts") or {}} for r in rows if (r.get("description") or "").strip()}


def anchored_pass(doc: dict, ads: dict[str, dict]) -> dict[str, dict]:
    """{id: {"anchored", "answers"}} for each ad that has a stored classification in this pass."""
    from match_engine import fit3
    roles, comps = fit3.load_roles(), fit3.closed_competencies()
    entries = doc.get("entries") or {}
    out = {}
    for i, ad in ads.items():
        entry = entries.get(fit3.classification_key(ad["posting"], roles, comps))
        if isinstance(entry, dict) and isinstance(entry.get("reply"), dict):
            p = ad["posting"]
            out[i] = {"anchored": fit3.anchor(entry["reply"], p["description"], roles, comps, p["title"]), "answers": entry.get("answers")}
    return out


def role_class(a: dict) -> str:
    return a["anchored"]["role"].get("class") or NOT_AVAILABLE


def core_ids(a: dict) -> set[str]:
    return {m["id"] for m in a["anchored"]["competencies"] if m["mark"] == "core" and m["quote"]}


def match_company(ads: dict[str, dict], needle: str) -> list[str]:
    """A label is an ad id (exact) or a company substring, case-insensitive. An id that has no text in the scratch view matches nothing."""
    return [i for i, ad in ads.items() if needle == i or (needle not in ads and needle.lower() in (ad["posting"]["company"] or "").lower())]


def b1(p1, p2, denominator):
    both = sorted(set(p1) & set(p2))
    flips = [i for i in both if role_class(p1[i]) != role_class(p2[i])]
    return {"flips": len(flips), "flipIds": flips, "compared": len(both), "of": denominator, "bar": f"<= {MAX_FLIPS}",
            "verdict": "PASS" if len(flips) <= MAX_FLIPS and len(both) else "FAIL" if flips else "NOT EVALUABLE"}


def b2(passes, ads, labels):
    rows, evaluable, ok = [], True, True
    for expect, names in (("target", labels.get("expectTarget") or []), ("other", labels.get("expectOther") or [])):
        for name in names:
            ids = match_company(ads, name)
            if not ids:
                evaluable = False
                rows.append({"company": name, "expect": expect, "classes": "no ad text"})
                continue
            for i in ids:
                classes = [role_class(p[i]) if i in p else NOT_AVAILABLE for p in passes]
                rows.append({"company": name, "id": i, "expect": expect, "classes": classes})
                if NOT_AVAILABLE in classes:
                    evaluable = False
                ok = ok and all(c == expect for c in classes)
    return {"rows": rows, "verdict": "NOT EVALUABLE" if not evaluable else "PASS" if ok else "FAIL"}


def b3(p1, p2, ads_with_text):
    both = sorted(set(p1) & set(p2))
    overlaps, both_empty = [], 0
    for i in both:
        a, b = core_ids(p1[i]), core_ids(p2[i])
        if not a and not b:
            both_empty += 1
            continue
        overlaps.append(len(a & b) / len(a | b))
    median = statistics.median(overlaps) if overlaps else None
    shares = [sum(1 for i in p if core_ids(p[i])) / ads_with_text if ads_with_text else None for p in (p1, p2)]
    ok = median is not None and median >= MIN_MEDIAN_OVERLAP and all(s is not None and s >= MIN_CORE_SHARE for s in shares)
    return {"medianOverlap": None if median is None else round(median, 4), "bothEmptyLeftOut": both_empty, "adsCompared": len(both),
            "shareWithCore": [None if s is None else round(s, 4) for s in shares], "bar": f"median >= {MIN_MEDIAN_OVERLAP} and share >= {MIN_CORE_SHARE}",
            "verdict": "NOT EVALUABLE" if median is None else "PASS" if ok else "FAIL"}


def b4(passes):
    rows = []
    for p in passes:
        marks = sum(a["anchored"].get("modelMarks") or 0 for a in p.values())
        sec, core = (sum(a["anchored"]["dropped"].get(k, 0) for a in p.values()) for k in ("unquoted", "coreDemoted"))
        share = (sec + core) / marks if marks else None
        rows.append({"modelMarks": marks, "secondaryDropped": sec, "coreDemoted": core, "share": None if share is None else round(share, 4)})
    verdict = "NOT EVALUABLE" if any(r["share"] is None for r in rows) else "PASS" if all(r["share"] <= MAX_MISSING_QUOTES for r in rows) else "FAIL"
    return {"passes": rows, "bar": f"<= {MAX_MISSING_QUOTES}", "verdict": verdict}


def b5(p, ads, labels, candidate_industries, candidate_level):
    """PRELIMINARY. V0 and V1 side by side; neither is selected. A2.1: an APPLY ad in the insufficient group is a miss for criterion 1 and is left out of
    the criterion-2 pairs. A2.2: a pass with no matcher answers is NOT EVALUABLE."""
    from match_engine import fit3
    from match_engine.fit3_industry import ad_industries
    apply_ids = {n: match_company(ads, n) for n in labels.get("apply") or []}
    skip_ids = [i for n in labels.get("fitSkip") or [] for i in match_company(ads, n)]
    rows = [{"id": i, "fit3": fit3.fit3(a["anchored"], a["answers"], ad_industries(ads[i]["posting"], ads[i]["facts"]), candidate_industries,
                                       ad_level=ads[i]["facts"].get("seniority"), candidate_level=candidate_level)} for i, a in p.items()]
    out = {"applyLabels": len(apply_ids), "applyWithText": sum(1 for v in apply_ids.values() if v), "adsRanked": len(rows)}
    if not any(r["fit3"]["requirements"]["coreCounts"]["answered"] for r in rows):
        return {**out, "verdict": "NOT EVALUABLE", "why": "this pass carries no matcher answers"}
    for variant in fit3.VARIANTS:
        ranked = fit3.rank(rows, variant)
        order = [r["id"] for r in ranked["ranked"]]
        keys = {r["id"]: fit3.order_key(r["fit3"], variant) for r in ranked["ranked"]}
        applies = [i for ids in apply_ids.values() for i in ids]
        pairable = [a for a in applies if a in keys]  # an APPLY ad in the insufficient group (or without text) is out of the pairs
        top = sum(1 for i in applies if i in order[:TOP])
        above = [s for s in skip_ids if s in keys and any(keys[s] <= keys[a] for a in pairable if a != s)]
        crit1 = top >= 3
        out[variant] = {"applyInTop6": top, "of": len(apply_ids), "applyInsufficientOrNoText": len(apply_ids) - len(pairable),
                        "fitSkipAboveApply": above, "rankedGroup": len(order), "insufficientGroup": len(ranked["insufficient"]),
                        "criterion1": crit1, "criterion2": not above,
                        "verdict": "PASS (PRELIMINARY)" if crit1 and not above else "FAIL (PRELIMINARY)"}
    out["verdict"] = "see v0 / v1, none selected"
    return out


def evaluate(ads, passes, labels, candidate_industries, candidate_level, denominator):
    p1, p2 = passes[0], passes[1] if len(passes) > 1 else {}
    result = {"adsWithText": len(ads), "denominator": denominator,
              "B1": b1(p1, p2, denominator) if p2 else {"verdict": "NOT EVALUABLE", "why": "one pass only"},
              "B2": b2(passes, ads, labels),
              "B3": b3(p1, p2, len(ads)) if p2 else {"verdict": "NOT EVALUABLE", "why": "one pass only"},
              "B4": b4(passes)}
    result["B5"] = [b5(p, ads, labels, candidate_industries, candidate_level) for p in passes]
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--scratch", type=Path, default=m3.DEFAULT_SCRATCH)
    p.add_argument("--ids", type=Path, default=m3.DEFAULT_IDS)
    p.add_argument("--denominator", type=int, default=20)
    p.add_argument("--pass1", required=True)
    p.add_argument("--pass2", default=None)
    p.add_argument("--labels", type=Path, required=True)
    args = p.parse_args(argv)
    from match_engine.fit3_industry import candidate_industries
    ids = json.loads(args.ids.read_text(encoding="utf-8"))
    ids = list(dict.fromkeys(i for i in (ids.get("ids") if isinstance(ids, dict) else ids) or [] if isinstance(i, str)))
    ads = load_ads(args.scratch, ids)
    docs = [json.loads((args.scratch / m3.OUT_DIR / n).read_text(encoding="utf-8")) for n in (args.pass1, args.pass2) if n]
    passes = [anchored_pass(d, ads) for d in docs]
    labels = json.loads(args.labels.read_text(encoding="utf-8"))
    intel = json.loads((args.scratch / "intelligence" / "candidate-intelligence.json").read_text(encoding="utf-8"))
    level = str((intel.get("candidateSummary") or {}).get("seniorityLevel") or "").strip().lower()
    print(json.dumps(evaluate(ads, passes, labels, candidate_industries(intel), level or None, args.denominator), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
