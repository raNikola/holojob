"""Professional Fit 2.1 on stable signals. SHADOW ONLY: nothing here reaches matchScore, a verdict, a priority or an order.

Plan, cue lists and pre-registered rules: ~/holojob-eval/w4-plan.md (with amendment A1), written before any measurement. Code only, no model.

A block of SEPARATE signals, not a blended number (the blend is an open decision, w4-pending-rule.md):
  requirements  one Fit over the union of dictionary-skill units and domain units (Fit 2.0 formula, weights 3/2/1), in three variants:
                V0 NOT_EVIDENCED has no effect; V1 every NOT_EVIDENCED must adds half its weight (PARTIAL_FACTOR) to the denominator, no credit;
                V2 that half weight on NOT_EVIDENCED musts of kind domain only (skill musts as V0). The certification clause of V2 is a no-op:
                certification lines are requirement sentences, display-only gaps (no weight).
  domain        the kind:domain units alone (V0, V1; V1 = V2 there), reported apart from Role Fit and from the skill part.
  role          Role Fit from the responsibilities' role mix (role_mix.py). Not available without responsibility text; the title tier is
                never a substitute, and roleTrack / titleTier are `auxiliary` fields: stored, shown, never a cap, never read by Role Fit.
  responsibilities  matcher statuses of the responsibilities (units keyed r:<hash of the quote>, importance nice), when an answer is given.
Dictionary skills only (the skills dictionary, `assign_id`, non-provisional); every other requirement sentence is a display-only gap.
Confidence and Insufficient evidence are the Fit 2.0 values, unchanged (units only, gates out). Eligibility stays a separate gate.

A 2.1 number is never ranked with a 1.x or 2.0 number: rank() refuses a list in which any row is not scoringVersion 2.1.
"""

from __future__ import annotations

import hashlib
import re
from fractions import Fraction

from requirement_ids import assign_id

from .constants import ENGINE_VERSION, PARTIAL_FACTOR
from .fit import SETTLED, credit, round_half_up
from .fit2 import UnitResolver, _chosen, _normal_status, _weight, fit2
from .role_mix import role_mix
from .verify import NOT_EVIDENCED

SCORING_VERSION = "2.1"
NOT_EVIDENCED_WEIGHT = PARTIAL_FACTOR  # the half of V1 and V2, the engine's one existing "half"
VARIANTS = ("v0", "v1", "v2")
SIGNALS = ("requirements", "domain", "role", "responsibilities")
_IMPORTANCE_RANK = {"must": 2, "preferred": 1, "nice": 0}


def quote_key(text: str | None, prefix: str) -> str | None:
    norm = " ".join(re.sub(r"[^\w]+", " ", (text or "").lower()).split())
    return f"{prefix}:" + hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12] if norm else None


def _unit_from(lines: list[dict], key: str, kind: str, source: str) -> dict:
    pick = _chosen(lines)
    importance = max((r.get("importance") or "nice" for r in lines), key=lambda i: _IMPORTANCE_RANK.get(i, -1))
    from .specificity import GENERIC_COMPETENCY_IDS
    return {"id": key, "kind": kind, "importance": importance, "status": pick["status"], "strength": pick.get("strength") or 0,
            "quoteVerified": pick.get("quoteVerified") is True, "lines": len(lines), "generic": key in GENERIC_COMPETENCY_IDS,
            "source": source}


def build_units(requirements: list[dict] | None) -> tuple[list[dict], list[dict], list[dict]]:
    """(skill units, domain units, gaps). Skill = a kind-skill line with one dictionary term (assign_id, called directly so a line whose
    text is also an alias is still found). Domain = a kind-domain line: the dictionary id when it has one, else the quote hash.
    Everything else is a gap: {index, kind, importance, status}, display-only."""
    skills: dict[str, list[dict]] = {}
    domains: dict[str, list[dict]] = {}
    gaps = []
    for index, raw in enumerate(requirements or []):
        req = {**raw, "status": _normal_status(raw.get("status"))}
        kind = req.get("kind")
        if kind == "skill":
            got = assign_id({"text": req.get("text"), "kind": "skill"})
            if not got["provisional"]:
                skills.setdefault(got["id"], []).append(req)
                continue
        elif kind == "domain":
            got = assign_id({"text": req.get("text"), "kind": "domain"})
            key = got["id"] if not got["provisional"] else quote_key(req.get("postingQuote") or req.get("text"), "q")
            if key:
                domains.setdefault(key, []).append(req)
                continue
        gaps.append({"index": index, "kind": kind, "importance": req.get("importance"), "status": req["status"]})
    return ([_unit_from(v, k, "skill", "dictionary") for k, v in sorted(skills.items())],
            [_unit_from(v, k, "domain", "domain") for k, v in sorted(domains.items())], gaps)


def _fit(units: list[dict], *, half_kinds: tuple[str, ...]) -> int | None:
    """Fit over the settled units; each NOT_EVIDENCED must of a kind in `half_kinds` adds half its weight to the denominator. None when nothing carries weight."""
    settled = [u for u in units if u["status"] in SETTLED]
    weight = sum((_weight(u) for u in settled), Fraction(0))
    earned = sum((credit(u) * _weight(u) for u in settled), Fraction(0))
    weight += sum((NOT_EVIDENCED_WEIGHT * _weight(u) for u in units
                   if u["status"] == NOT_EVIDENCED and u["importance"] == "must" and u["kind"] in half_kinds), Fraction(0))
    if not weight or not any(_weight(u) for u in settled):
        return None
    return int(round_half_up(100 * earned / weight))


def _counts(units: list[dict]) -> dict:
    out: dict = {"units": len(units), "mustUnits": sum(u["importance"] == "must" for u in units)}
    for status in ("MET", "PARTIAL", "CONTRADICTED", NOT_EVIDENCED, "UNKNOWN"):
        out[status] = sum(u["status"] == status for u in units)
    return out


def responsibility_units(answers: list[dict] | None) -> list[dict]:
    """Matcher answers for the responsibilities (rows with postingQuote, status, strength, quoteVerified) as units keyed r:<hash of the
    quote>, importance nice. Two rows with one quote are one unit."""
    by_key: dict[str, list[dict]] = {}
    for raw in answers or []:
        key = quote_key(raw.get("postingQuote"), "r")
        if key:
            by_key.setdefault(key, []).append({**raw, "status": _normal_status(raw.get("status")), "importance": "nice"})
    return [_unit_from(v, k, "responsibility", "responsibility") for k, v in sorted(by_key.items())]


def fit21(requirements: list[dict], resolver: UnitResolver, responsibilities: list[dict] | None = None,
          responsibility_answers: list[dict] | None = None, auxiliary: dict | None = None) -> dict:
    """The Fit 2.1 block of one posting. `responsibilities` = the extract-7 list (text, postingQuote); `responsibility_answers` = matcher rows over them."""
    skills, domains, gaps = build_units(requirements)
    both = skills + domains
    base = fit2(requirements, resolver, responsibilities)  # confidence and Insufficient evidence: the Fit 2.0 values, unchanged
    resp_units = responsibility_units(responsibility_answers)
    role = role_mix(responsibilities)
    gap_counts: dict = {}
    for g in gaps:
        key = f"{g['kind']}:{g['importance']}"
        gap_counts[key] = gap_counts.get(key, 0) + 1
    return {
        "scoringVersion": SCORING_VERSION,
        "engineVersion": ENGINE_VERSION,
        "requirements": {
            "v0": _fit(both, half_kinds=()), "v1": _fit(both, half_kinds=("skill", "domain")), "v2": _fit(both, half_kinds=("domain",)),
            "notEvidencedWeight": str(NOT_EVIDENCED_WEIGHT), "counts": _counts(both), "units": both,
        },
        "domain": {"v0": _fit(domains, half_kinds=()), "v1": _fit(domains, half_kinds=("domain",)),
                   "contradictedMusts": sum(u["status"] == "CONTRADICTED" and u["importance"] == "must" for u in domains),
                   "counts": _counts(domains)},
        "role": role,
        "responsibilities": {"fit": _fit(resp_units, half_kinds=()), "counts": _counts(resp_units), "units": resp_units},
        "auxiliary": {"titleTier": (auxiliary or {}).get("titleTier"), "roleTrack": (auxiliary or {}).get("roleTrack"),
                      "roleMatchScore": (auxiliary or {}).get("roleMatchScore")},
        "gaps": {"count": len(gaps), "byKindImportance": gap_counts},
        "confidence": base["confidence"],
        "insufficientEvidence": base["insufficientEvidence"],
        "insufficientReasons": base["insufficientReasons"],
    }


class MixedScoringVersions(ValueError):
    """A rank list held a 2.1 number and something else."""


def signal_value(block: dict, signal: str, variant: str = "v0") -> int | None:
    if signal == "requirements":
        return block["requirements"][variant]
    if signal == "domain":
        return block["domain"]["v1" if variant in ("v1", "v2") else "v0"]
    if signal == "role":
        return block["role"]["roleFit"] if block["role"]["available"] else None
    if signal == "responsibilities":
        return block["responsibilities"]["fit"]
    raise ValueError(f"unknown signal {signal!r}")


def rank(rows: list[dict], signal: str = "requirements", variant: str = "v0") -> list[dict]:
    """Rows (each {"id", "fit21": {...}}) best first by one signal, id as the tie-break; a row without a number goes last.
    Refuses a list in which any row is not scoringVersion 2.1."""
    for row in rows:
        block = row.get("fit21")
        if not isinstance(block, dict) or block.get("scoringVersion") != SCORING_VERSION:
            raise MixedScoringVersions(f"row {row.get('id')!r} is not a scoringVersion {SCORING_VERSION} row")
    def value(r):
        return signal_value(r["fit21"], signal, variant)
    return sorted(rows, key=lambda r: (value(r) is None, -(value(r) or 0), str(r.get("id"))))
