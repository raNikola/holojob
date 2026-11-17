"""Professional Fit 2.0 on canonical competencies. SHADOW ONLY: nothing here reaches matchScore, a verdict, a priority or an order.

Plan and pre-registered rules: ~/holojob-eval/w3-plan.md (written before any measurement). Code only, no model.

Unit = a canonical competency id resolved by code from the line's own text (UnitResolver). The model's `competencyId`, a learned alias
that is pending or auto, the remap table and the row's stored `id` are never read, because each can carry a model pick. Lines
resolving to one id merge into one unit. A line that resolves to nothing is unmapped: display-only, no weight, no credit.

Two variants are computed side by side on every row (never mixed, never averaged):
  V0  Fit over the settled units (MET, PARTIAL, CONTRADICTED); NOT_EVIDENCED and UNKNOWN are in neither side (engine 0.3.0).
  V1  V0, plus each NOT_EVIDENCED specific must adds NOT_EVIDENCED_WEIGHT x the must weight to the denominator, with no credit.
      NOT_EVIDENCED_WEIGHT is PARTIAL_FACTOR (1/2), fixed before any measurement: an inferred absence counts less than a confirmed
      no (CONTRADICTED, weight 1), and the engine's one existing "half" constant adds no free parameter.
Confidence and Insufficient evidence are the same in both variants and cover competency units only (gates are eligibility, a
separate gate): confidence = verified weight / all non-generic unit weight.

A 2.0 number is never ranked with a 1.x number: rank() refuses a mixed list.
"""

from __future__ import annotations

import json
import re
from fractions import Fraction
from pathlib import Path

from requirement_ids import MAPPED_KINDS, assign_id

from . import competencies
from .constants import (ENGINE_VERSION, IMPORTANCE_WEIGHT, MAX_UNKNOWN_MUST_RATIO, MIN_CONFIDENCE, PARTIAL_FACTOR)
from .fit import SETTLED, credit, round_half_up
from .specificity import GENERIC_COMPETENCY_IDS
from .verify import CONTRADICTED, NOT_EVIDENCED

SCORING_VERSION = "2.0"
NOT_EVIDENCED_WEIGHT = PARTIAL_FACTOR  # V1's w, see the module docstring
ROOT = Path(__file__).resolve().parents[2]
LEARNED_ALIASES_PATH = ROOT / "data" / "competency-aliases.json"
_IMPORTANCE_RANK = {"must": 2, "preferred": 1, "nice": 0}

# Boilerplate wrapped around a requirement, stripped for one more alias try. Fixed before any measurement; a longer lead-in first.
LEAD_INS = (
    "proven track record of", "proven experience with", "proven experience in", "demonstrated experience with",
    "demonstrated experience in", "hands-on experience with", "hands on experience with", "working knowledge of",
    "experience with", "experience in", "experience of", "knowledge of", "understanding of", "familiarity with",
    "ability to", "strong", "solid", "good", "excellent", "proven", "demonstrated",
)
TRAIL_INS = ("skills", "experience", "ability", "abilities", "knowledge", "background")
_LEAD = re.compile(r"^(?:" + "|".join(re.escape(x) for x in LEAD_INS) + r")\s+")
_TRAIL = re.compile(r"\s+(?:" + "|".join(TRAIL_INS) + r")$")


class UnitResolver:
    """Text -> canonical competency id by code: seed alias, reviewed learned alias, one dictionary term, then the same with
    boilerplate stripped. Never the model's pick."""

    def __init__(self, comps: list[dict], learned: dict | None = None):
        self.ids = {c["id"] for c in comps}
        self.seed = competencies.alias_index(comps)
        self.learned: dict[str, str] = {}
        for key, entry in (learned or {}).items():
            if not isinstance(entry, dict) or entry.get("status") != "reviewed":
                continue
            cid = entry.get("competencyId")
            demoted = {str(i) for i in entry.get("demotedIds") or []}
            if cid in self.ids and cid not in demoted:
                self.learned[key] = cid

    @classmethod
    def default(cls, family: str = "product", learned_path: Path | None = None) -> "UnitResolver":
        path = learned_path or LEARNED_ALIASES_PATH
        learned = None
        if path.exists():
            try:
                learned = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                learned = None
        return cls(competencies.load(family), learned if isinstance(learned, dict) else None)

    def _alias(self, key: str) -> tuple[str, str] | None:
        if key in self.seed:
            return self.seed[key], "alias"
        if key in self.learned:
            return self.learned[key], "learned"
        return None

    @staticmethod
    def variants(key: str) -> list[str]:
        """The alias key, then the key with a leading boilerplate phrase removed, a trailing one removed, and both."""
        out = [key]
        lead = _LEAD.sub("", key, count=1)
        trail = _TRAIL.sub("", key, count=1)
        both = _TRAIL.sub("", lead, count=1)
        for v in (lead, trail, both):
            if v and v not in out:
                out.append(v)
        return out

    def resolve(self, text: str | None, kind: str | None = None) -> tuple[str | None, str | None]:
        """(competency id, route) or (None, None). route: alias, learned, dictionary, alias-stripped."""
        if not isinstance(text, str) or not text.strip():
            return None, None
        key = competencies.alias_key(text)
        hit = self._alias(key)
        if hit:
            return hit
        if kind in MAPPED_KINDS:
            assigned = assign_id({"text": text, "kind": kind})
            if not assigned["provisional"]:
                return assigned["id"], "dictionary"
        for variant in self.variants(key)[1:]:
            hit = self._alias(variant)
            if hit:
                return hit[0], "alias-stripped"
        return None, None


def _line_credit(req: dict) -> Fraction:
    return credit(req) if req["status"] in ("MET", "PARTIAL") else Fraction(0)


def _normal_status(status: str | None) -> str:
    return NOT_EVIDENCED if status == "MISSING" else (status or "UNKNOWN")


def _chosen(lines: list[dict]) -> dict:
    """The merge rule: CONTRADICTED if any line is; else the best-credit MET/PARTIAL line; else NOT_EVIDENCED if any; else UNKNOWN."""
    for status in (CONTRADICTED,):
        hit = [r for r in lines if r["status"] == status]
        if hit:
            return hit[0]
    settled = [r for r in lines if r["status"] in ("MET", "PARTIAL")]
    if settled:
        return max(settled, key=lambda r: (_line_credit(r), r["status"] == "MET"))
    hit = [r for r in lines if r["status"] == NOT_EVIDENCED]
    return hit[0] if hit else lines[0]


def build_units(requirements: list[dict], resolver: UnitResolver, responsibilities: list[dict] | None = None) -> tuple[list[dict], list[dict]]:
    """(units sorted by id, unmapped lines in input order). Responsibilities merge into an asked id; a new id is a `nice` UNKNOWN unit."""
    by_id: dict[str, list[dict]] = {}
    sources: dict[str, set] = {}
    routes: dict[str, str] = {}
    unmapped = []
    for index, raw in enumerate(requirements or []):
        req = {**raw, "status": _normal_status(raw.get("status"))}
        cid, route = resolver.resolve(req.get("text"), req.get("kind"))
        if cid is None:
            unmapped.append({"index": index, "kind": req.get("kind"), "importance": req.get("importance"), "status": req["status"]})
            continue
        by_id.setdefault(cid, []).append(req)
        sources.setdefault(cid, set()).add("requirement")
        routes.setdefault(cid, route)
    extra: dict[str, dict] = {}
    for resp in responsibilities or []:
        cid, route = resolver.resolve(resp.get("text"), "skill")
        if cid is None:
            continue
        if cid in by_id:
            sources[cid].add("responsibility")
        elif cid not in extra:
            extra[cid] = {"kind": "skill", "importance": "nice", "status": "UNKNOWN", "strength": 0, "quoteVerified": False}
            sources[cid] = {"responsibility"}
            routes[cid] = route
    units = []
    for cid in sorted(set(by_id) | set(extra)):
        if cid in by_id:
            lines = by_id[cid]
            pick = _chosen(lines)
            importance = max((r.get("importance") or "nice" for r in lines), key=lambda i: _IMPORTANCE_RANK.get(i, -1))
            unit = {"kind": pick.get("kind"), "importance": importance, "status": pick["status"],
                    "strength": pick.get("strength") or 0, "quoteVerified": pick.get("quoteVerified") is True, "lines": len(lines)}
        else:
            unit = {**extra[cid], "lines": 0}
        units.append({"id": cid, **unit, "generic": cid in GENERIC_COMPETENCY_IDS, "sources": sorted(sources[cid]), "route": routes[cid]})
    return units, unmapped


def _weight(unit: dict) -> Fraction:
    return Fraction(0) if unit["generic"] else IMPORTANCE_WEIGHT[unit["importance"]]


def _fit(units: list[dict], *, not_evidenced_weight: Fraction) -> int | None:
    """None when nothing carries weight."""
    settled = [u for u in units if u["status"] in SETTLED]
    weight = sum((_weight(u) for u in settled), Fraction(0))
    earned = sum((credit(u) * _weight(u) for u in settled), Fraction(0))
    if not_evidenced_weight:
        weight += sum((not_evidenced_weight * _weight(u) for u in units
                       if u["status"] == NOT_EVIDENCED and u["importance"] == "must"), Fraction(0))
    if not weight or not any(_weight(u) for u in settled):
        return None
    return int(round_half_up(100 * earned / weight))


def _verified(unit: dict) -> bool:
    return unit["status"] == CONTRADICTED or (unit["status"] in ("MET", "PARTIAL") and unit["quoteVerified"])


def fit2(requirements: list[dict], resolver: UnitResolver, responsibilities: list[dict] | None = None) -> dict:
    """The Fit 2.0 block of one posting, from its engine requirements (each with text, kind, importance, status, strength, quoteVerified)."""
    units, unmapped = build_units(requirements, resolver, responsibilities)
    total = sum((_weight(u) for u in units), Fraction(0))
    confidence = sum((_weight(u) for u in units if _verified(u)), Fraction(0)) / total if total else Fraction(0)
    musts = [u for u in units if u["importance"] == "must" and not u["generic"]]
    not_judged = sum(u["status"] in ("UNKNOWN", NOT_EVIDENCED) for u in musts)
    ratio = Fraction(not_judged, len(musts)) if musts else Fraction(0)
    v0 = _fit(units, not_evidenced_weight=Fraction(0))
    reasons = []
    if v0 is None:
        reasons.append("nothing settled")
    if confidence < MIN_CONFIDENCE:
        reasons.append("low confidence")
    if ratio > MAX_UNKNOWN_MUST_RATIO:
        reasons.append("too many musts not judged")
    unmapped_musts = sum(1 for u in unmapped if u["importance"] == "must")
    must_total = len(musts) + unmapped_musts
    return {
        "scoringVersion": SCORING_VERSION,
        "engineVersion": ENGINE_VERSION,
        "v0": {"fit": v0},
        "v1": {"fit": _fit(units, not_evidenced_weight=NOT_EVIDENCED_WEIGHT), "notEvidencedWeight": str(NOT_EVIDENCED_WEIGHT)},
        "confidence": float(round_half_up(confidence, 4)),
        "insufficientEvidence": bool(reasons),
        "insufficientReasons": reasons,
        "units": units,
        "unmapped": unmapped,
        "counts": {
            "units": len(units), "generic": sum(u["generic"] for u in units), "mustUnits": len(musts),
            "unmapped": len(unmapped), "unmappedMusts": unmapped_musts,
            "unmappedMustShare": round(unmapped_musts / must_total, 4) if must_total else None,
        },
    }


class MixedScoringVersions(ValueError):
    """A rank list held a 2.0 number and something else."""


def rank(rows: list[dict], variant: str = "v0") -> list[dict]:
    """Rows (each {"id", "fit2": {...}}) best first by the variant's Fit, id as the tie-break; a row without a number goes last.
    Refuses a list in which any row is not scoringVersion 2.0: a 1.x number is never in a 2.0 rank list."""
    for row in rows:
        block = row.get("fit2")
        if not isinstance(block, dict) or block.get("scoringVersion") != SCORING_VERSION:
            raise MixedScoringVersions(f"row {row.get('id')!r} is not a scoringVersion {SCORING_VERSION} row")
    return sorted(rows, key=lambda r: (r["fit2"][variant]["fit"] is None, -(r["fit2"][variant]["fit"] or 0), str(r.get("id"))))
