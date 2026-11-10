"""P1 Stage B, S1: an OFFLINE preview of the new aggregation rules on stored engine results. Nothing here changes the engine.

It reads the requirement verdicts the engine stored (status, strength, importance, kind) and recomputes fit and confidence under
the owner's rules. It reuses the engine's own constants (strength credit, importance weights, partial factor, label thresholds) so a
difference is the rules' and not a new calibration.

Verdict vocabulary of the new rules (the stored matcher still says MET / PARTIAL / MISSING / UNKNOWN):

  MET, PARTIAL    positive evidence: the candidate's own text, verified by a quote. Earns credit by strength (PARTIAL half).
  CONTRADICTED    explicit evidence AGAINST the requirement. Affects fit: it counts in the denominator and earns nothing.
                  Three sources only: (1) a quoted evidence item that conflicts with the requirement; (2) the owner confirmed
                  "I do not have this"; (3) closed-world absence: the requirement's kind is one a profile lists completely when it
                  lists it at all (CLOSED_WORLD_KINDS: education, certification, language) AND the profile has a non-empty section
                  of that kind AND nothing in it satisfies the requirement. A missing mandatory licence or degree is this case.
                  The stored data holds no conflicting quote and no owner answer, so only (3) can be applied offline.
  NOT_EVIDENCED   silence: the profile says nothing about it (UNKNOWN), or the matcher inferred absence from open prose (MISSING on a
                  skill, experience, domain or other requirement, or on a closed-world kind whose profile section is empty).
                  It never lowers and never raises fit (it is outside numerator and denominator); it lowers confidence only, and
                  it is listed as an unconfirmed requirement with a question.
  MISSING         is retired as a scoring status: it is CONTRADICTED or NOT_EVIDENCED by the rule above.

Fit: weighted credit over MET, PARTIAL and CONTRADICTED, 100 x credit / weight, round half up; no estimate when nothing is settled.
Confidence: verified weight over the weight of everything asked (requirements and the five gates, a gate weighing as a must);
verified = MET or PARTIAL with a verified quote, or CONTRADICTED; a critical unconfirmed must weighs CRITICAL_WEIGHT_FACTOR times in
the denominator and earns nothing, so it pulls confidence down harder than an ordinary unconfirmed item.
Label: from fit with the engine's thresholds (Strong, Good, Partial, Weak). There is no Incomplete label: a flag says how many must
requirements are unconfirmed, and a CRITICAL unconfirmed must has its own rule (below).

Critical unconfirmed must: a must of a CRITICAL_KINDS kind (a binary prerequisite: education, certification, language) that is
NOT_EVIDENCED, which happens when the profile has no section of that kind. Rule: fit does not move; confidence counts it at
CRITICAL_WEIGHT_FACTOR; the bucket is held at "check_first" (never "apply") and its question goes first, until the owner answers.
"""

from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("job_scoring", "llm"):
    if str(ROOT / "python" / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / "python" / _sub))
if str(ROOT / "python") not in sys.path:
    sys.path.append(str(ROOT / "python"))

from match_engine.constants import (  # noqa: E402
    IMPORTANCE_WEIGHT, LABEL_GOOD_MIN, LABEL_PARTIAL_MIN, LABEL_STRONG_MIN, PARTIAL_FACTOR, STRENGTH_CREDIT,
)

MET, PARTIAL, CONTRADICTED, NOT_EVIDENCED = "MET", "PARTIAL", "CONTRADICTED", "NOT_EVIDENCED"
SCORED = (MET, PARTIAL, CONTRADICTED)
# Kinds a profile lists completely when it lists them at all. Candidates for data/config; universal, not profession-specific.
CLOSED_WORLD_KINDS = ("education", "certification", "language")
# Binary prerequisites whose silence is critical.
CRITICAL_KINDS = ("education", "certification", "language")
CRITICAL_WEIGHT_FACTOR = 2
GATE_WEIGHT = IMPORTANCE_WEIGHT["must"]


def typed_status(req: dict, sections: dict[str, int]) -> str:
    """The new status of one stored requirement. `sections` = how many entries the profile has per closed-world kind."""
    status = req["status"]
    if status in (MET, PARTIAL, CONTRADICTED):  # a CONTRADICTED comes from matcher_v3, already checked in code
        return status
    if status == "MISSING" and req["kind"] in CLOSED_WORLD_KINDS and sections.get(req["kind"], 0) > 0:
        return CONTRADICTED
    return NOT_EVIDENCED  # UNKNOWN, and MISSING inferred from open prose or from an empty section


def _round_half_up(value: Fraction) -> int:
    return int((value * 2 + 1) // 2)


def _credit(req: dict, status: str) -> Fraction:
    if status == MET:
        return STRENGTH_CREDIT[req["strength"]]
    if status == PARTIAL:
        return STRENGTH_CREDIT[req["strength"]] * PARTIAL_FACTOR
    return Fraction(0)


def is_critical(req: dict, status: str) -> bool:
    return req["importance"] == "must" and status == NOT_EVIDENCED and req["kind"] in CRITICAL_KINDS


def fit_of(requirements: list[dict], sections: dict, silence: str = "outside") -> int | None:
    """Fit under the new rules. `silence` is for comparison only: "outside" is the rule; "zero" counts NOT_EVIDENCED as no credit and
    "full" as full credit, which gives the floor and the ceiling of the range, never a shown score."""
    num = den = Fraction(0)
    for req in requirements:
        status = typed_status(req, sections)
        weight = IMPORTANCE_WEIGHT[req["importance"]]
        if status == NOT_EVIDENCED:
            if silence == "outside":
                continue
            den += weight
            num += weight if silence == "full" else 0
            continue
        den += weight
        num += _credit(req, status) * weight
    return _round_half_up(100 * num / den) if den else None


def confidence_of(requirements: list[dict], gates: list[dict], sections: dict) -> Fraction:
    total = verified = Fraction(0)
    for req in requirements:
        status = typed_status(req, sections)
        weight = IMPORTANCE_WEIGHT[req["importance"]] * (CRITICAL_WEIGHT_FACTOR if is_critical(req, status) else 1)
        total += weight
        if status in SCORED:
            verified += weight
    for gate in gates:
        total += GATE_WEIGHT
        if gate["result"] != "unknown":
            verified += GATE_WEIGHT
    return verified / total if total else Fraction(0)


def label_for(fit: int | None) -> str:
    if fit is None:
        return "No estimate"
    if fit >= LABEL_STRONG_MIN:
        return "Strong"
    if fit >= LABEL_GOOD_MIN:
        return "Good"
    if fit >= LABEL_PARTIAL_MIN:
        return "Partial"
    return "Weak"


def preview(requirements: list[dict], gates: list[dict], sections: dict, bucket: str = "apply") -> dict:
    """Fit, confidence, label, range, flags and bucket for one posting, from stored verdicts."""
    typed = [(r, typed_status(r, sections)) for r in requirements]
    unconfirmed = [r for r, s in typed if s == NOT_EVIDENCED]
    unconfirmed_musts = [r for r in unconfirmed if r["importance"] == "must"]
    critical = [r for r, s in typed if is_critical(r, s)]
    fit = fit_of(requirements, sections)
    return {
        "fit": fit, "label": label_for(fit), "confidence": float(confidence_of(requirements, gates, sections)),
        "fitRange": [fit_of(requirements, sections, "zero"), fit_of(requirements, sections, "full")],
        "contradicted": sum(1 for _, s in typed if s == CONTRADICTED), "notEvidenced": len(unconfirmed),
        "unconfirmedMusts": len(unconfirmed_musts), "criticalUnconfirmed": len(critical),
        "flag": f"unconfirmed: {len(unconfirmed_musts)} must requirements" if unconfirmed_musts else None,
        "bucket": "check_first" if critical and bucket == "apply" else bucket,
    }
