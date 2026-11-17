"""Fit, confidence, label, counts, caps, bucket and questions.

Contract sections 5.1 and 5.3 to 5.5, computed in code from what verify.py
settled and the five gate results gates.py decided. No model.

Order: raw Fit from the requirements, then the caps (the lowest that applies),
then the label from the capped Fit, then the blocked-label limit. Gates never
move Fit; only the role-family gate's fail is also the role_family_mismatch
cap, because "the posting's role family differs" is that same fact.

Blocked-label rule (section 5.4 says a blocked posting is never Strong or
Good, without a formula): a Strong or Good label becomes Partial; Partial,
Weak and Incomplete stay as they are.

Rounding rule: every sum is an exact Fraction; Fit is 100 x credit / weight
rounded half up to an integer (48.5 -> 49, never banker's rounding), and the
reported confidence is rounded half up to 4 decimals. Thresholds compare the
exact values, so a rounded display never flips a label.
"""

from __future__ import annotations

from fractions import Fraction

from .constants import (
    IMPORTANCE_WEIGHT,
    LABEL_GOOD_MIN,
    LABEL_PARTIAL_MIN,
    LABEL_STRONG_MIN,
    MAX_UNKNOWN_MUST_RATIO,
    MIN_CONFIDENCE,
    PARTIAL_FACTOR,
    ROLE_MISMATCH_FIT_CAP,
    STRENGTH_CREDIT,
    UNVERIFIED_FIT_CAP,
)
from .gates import bucket_for
from .specificity import requirement_is_specific
from .verify import CONTRADICTED, NOT_EVIDENCED

# The statuses that enter the coverage denominator (section 4.1).
SETTLED = ("MET", "PARTIAL", CONTRADICTED)

QUESTION_TEMPLATES = {
    "skill": "Have you worked with {text}?",
    "experience": "Do you have this experience: {text}?",
    "domain": "Have you worked in {text}?",
    "education": "Do you have {text}?",
    "certification": "Do you hold {text}?",
    "language": "Do you speak {text}?",
    "other": "Does this apply to you: {text}?",
}

GATE_QUESTIONS = {
    "work_authorization": "Can you legally work where this job is based, or would you take a sponsored role?",
    "location": "Can you work from where this job is based?",
    "language": "Do you speak the languages this job needs?",
    "salary_floor": "What is the lowest monthly salary in EUR you would accept?",
    "role_family": "Is this the kind of role you are looking for?",
}


def round_half_up(value: Fraction, places: int = 0) -> Fraction:
    scale = 10 ** places
    return Fraction((value * scale * 2 + 1) // 2, scale)


def credit(req: dict) -> Fraction:
    """What one settled requirement earns, before its weight."""
    if req["status"] == "MET":
        return STRENGTH_CREDIT[req["strength"]]
    if req["status"] == "PARTIAL":
        return STRENGTH_CREDIT[req["strength"]] * PARTIAL_FACTOR
    return Fraction(0)


def _weight(req: dict) -> Fraction:
    """The importance weight; 0 for a generic requirement (specificity.py, decision Q3)."""
    return IMPORTANCE_WEIGHT[req["importance"]] if requirement_is_specific(req) else Fraction(0)


def _not_judged(req: dict) -> bool:
    """UNKNOWN and NOT_EVIDENCED: nothing found for it, and nothing is held against the candidate."""
    return req["status"] in ("UNKNOWN", NOT_EVIDENCED)


def normalized(requirements: list[dict]) -> list[dict]:
    """A stored output of an engine before 0.3.0 says MISSING for what is now NOT_EVIDENCED (an inferred absence)."""
    return [{**r, "status": NOT_EVIDENCED} if r["status"] == "MISSING" else r for r in requirements]


def fit_value(requirements: list[dict]) -> int:
    """Weighted credit of MET, PARTIAL and CONTRADICTED over their weight; UNKNOWN and NOT_EVIDENCED are in neither. 0 when none."""
    settled = [r for r in requirements if r["status"] in SETTLED]
    weight = sum((_weight(r) for r in settled), Fraction(0))
    if not weight:
        return 0
    earned = sum((credit(r) * _weight(r) for r in settled), Fraction(0))
    return int(round_half_up(100 * earned / weight))


def caps_for(requirements: list[dict], gates: list[dict]) -> list[str]:
    """Every cap whose condition holds, in the contract's enum order (section 5.5).

    Listed when it applies, whether or not it moved this Fit: gate_blocked
    never moves Fit, and a cap above a low Fit still says where the ceiling is.
    """
    failed = {g["gate"] for g in gates if g["result"] == "fail"}
    caps = []
    if "role_family" in failed:
        caps.append("role_family_mismatch")
    if failed:
        caps.append("gate_blocked")
    if not any(r.get("quoteVerified") is True for r in requirements):
        caps.append("no_verified_evidence")
    return caps


CAP_CEILINGS = {"role_family_mismatch": ROLE_MISMATCH_FIT_CAP, "no_verified_evidence": UNVERIFIED_FIT_CAP}


def capped_fit(fit: int, caps: list[str]) -> int:
    """Fit held to the lowest ceiling among the caps that have one."""
    return min([fit] + [CAP_CEILINGS[c] for c in caps if c in CAP_CEILINGS])


def _verified(req: dict) -> bool:
    """A status that rests on something checked: a quoted MET/PARTIAL, or a CONTRADICTED (settled in code, needs no quote)."""
    if req["status"] == CONTRADICTED:
        return True
    return req["status"] in ("MET", "PARTIAL") and req.get("quoteVerified") is True


def confidence_value(requirements: list[dict], gates: list[dict]) -> Fraction:
    """Weight of verified statuses over the weight of everything judged; 0 when there is nothing.

    Each gate weighs as a must and counts as settled when its result is pass
    or fail; an unknown gate adds weight and no credit (section 5.3).
    """
    gate_weight = IMPORTANCE_WEIGHT["must"]
    total = sum((_weight(r) for r in requirements), Fraction(0)) + gate_weight * len(gates)
    if not total:
        return Fraction(0)
    settled = sum((_weight(r) for r in requirements if _verified(r)), Fraction(0))
    settled += gate_weight * sum(g["result"] != "unknown" for g in gates)
    return settled / total


def counts_of(requirements: list[dict], gates: list[dict]) -> dict:
    musts = [r for r in requirements if r["importance"] == "must"]
    preferred = [r for r in requirements if r["importance"] == "preferred"]
    return {
        "mustMet": sum(r["status"] == "MET" for r in musts),
        "mustTotal": len(musts),
        "preferredMet": sum(r["status"] == "MET" for r in preferred),
        "preferredTotal": len(preferred),
        "unknown": sum(_not_judged(r) for r in requirements),
        "notEvidenced": sum(r["status"] == NOT_EVIDENCED for r in requirements),
        "blockers": sum(r["status"] == CONTRADICTED for r in musts) + sum(g["result"] == "fail" for g in gates),
    }


def questions_for(requirements: list[dict], gates: list[dict]) -> list[dict]:
    """One templated question per UNKNOWN requirement in requirement order, then one per unknown gate."""
    return [
        {
            "competencyId": r["id"],
            "question": QUESTION_TEMPLATES.get(r["kind"], QUESTION_TEMPLATES["other"]).format(text=r["text"].rstrip(".?! ")),
        }
        for r in requirements
        if _not_judged(r)
    ] + [
        {"competencyId": g["gate"], "question": GATE_QUESTIONS[g["gate"]]}
        for g in gates
        if g["result"] == "unknown"
    ]


def incomplete(requirements: list[dict], confidence: Fraction, counts: dict) -> bool:
    """Section 5.3's two thresholds, plus section 5.1: nothing settled at all is always Incomplete."""
    if not any(r["status"] in SETTLED and _weight(r) for r in requirements):
        return True
    if confidence < MIN_CONFIDENCE:
        return True
    # Generic musts weigh 0 and stay out of both sides of the ratio.
    musts = [r for r in requirements if r["importance"] == "must" and _weight(r)]
    unknown_musts = sum(_not_judged(r) for r in musts)
    ratio = Fraction(unknown_musts, len(musts)) if musts else Fraction(0)
    return ratio > MAX_UNKNOWN_MUST_RATIO


def label_for(fit: int) -> str:
    if fit >= LABEL_STRONG_MIN:
        return "Strong"
    if fit >= LABEL_GOOD_MIN:
        return "Good"
    if fit >= LABEL_PARTIAL_MIN:
        return "Partial"
    return "Weak"


def label_text(label: str, questions: list[dict]) -> str:
    """What the UI shows: the label, or "Incomplete - answer N questions" (section 5.3)."""
    return f"Incomplete - answer {len(questions)} questions" if label == "Incomplete" else label


def score(requirements: list[dict], gates: list[dict]) -> dict:
    """Fit, confidence, label, bucket, caps, counts and questions for one posting.

    `requirements` is match_engine output's requirements[] (each with id, text,
    kind, importance, status, quoteVerified, strength); `gates` is
    gates.gate_results(), all five. `label` is the contract's enum;
    `labelText` is its display form.
    """
    requirements = normalized(requirements)
    counts = counts_of(requirements, gates)
    questions = questions_for(requirements, gates)
    caps = caps_for(requirements, gates)
    fit = capped_fit(fit_value(requirements), caps)
    confidence = confidence_value(requirements, gates)
    bucket = bucket_for(gates)
    label = "Incomplete" if incomplete(requirements, confidence, counts) else label_for(fit)
    if bucket == "blocked" and label in ("Strong", "Good"):
        label = "Partial"
    return {
        "fit": fit,
        "confidence": float(round_half_up(confidence, 4)),
        "label": label,
        "labelText": label_text(label, questions),
        "bucket": bucket,
        "caps": caps,
        "gates": gates,
        "counts": counts,
        "questions": questions,
    }
