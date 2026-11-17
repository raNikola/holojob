"""Code's half of matching: check every quote, then fix status and strength.

Contract section 5.2. The model proposes; nothing here trusts the proposal
further than the quotes it can show. A status is only ever lowered here.
"""

from __future__ import annotations

from .fact_links import fact_for
from .normalize import quote_in

# What the model may propose (and what a cached raw answer holds). The engine's output says CONTRADICTED / NOT_EVIDENCED
# instead of MISSING: see output_status().
STATUSES = ("MET", "PARTIAL", "MISSING", "UNKNOWN")
CONTRADICTED, NOT_EVIDENCED = "CONTRADICTED", "NOT_EVIDENCED"
# Output statuses. Only CONTRADICTED counts as unmet; NOT_EVIDENCED (the evidence says nothing for it) and UNKNOWN move nothing.
OUTPUT_STATUSES = ("MET", "PARTIAL", CONTRADICTED, NOT_EVIDENCED, "UNKNOWN")
# One step down for a MET or PARTIAL whose evidence quote does not check out.
DOWNGRADE = {"MET": "PARTIAL", "PARTIAL": "UNKNOWN"}
CLAIM_STRENGTH = 1
# What a confirmed "yes" is credited at. The user's own answer is not an
# outcome with a number, but it is more than a listed skill. Calibrated with the
# other constants in step 5 (ENGINE_CONTRACT.md, Open points 1).
CONFIRMED_FACT_STRENGTH = 3
# The one translation of a fact's outcome into a path's status names. Production
# has used the same two words since engine 0.3.0 (before: MISSING / UNKNOWN).
VOCABULARY = {
    "production": {"contradicted": "CONTRADICTED", "not_evidenced": "NOT_EVIDENCED"},
    "stage_b": {"contradicted": "CONTRADICTED", "not_evidenced": "NOT_EVIDENCED"},
}


def output_status(status: str | None) -> str | None:
    """A model or stored status as the engine reports it: a bare MISSING is an absence the model inferred (no
    conflicting quote), so NOT_EVIDENCED. A contradiction comes only from code: a confirmed "no", a language the
    profile's list settles."""
    return NOT_EVIDENCED if status == "MISSING" else status


def drop_unquoted(requirements: list[dict], description: str) -> tuple[list[dict], list[str]]:
    """Requirements whose postingQuote the ad really contains, and a warning per dropped one.

    The engine does not score what the ad does not say: a missing or
    unfound quote drops the requirement before the model sees it.
    """
    kept, warnings = [], []
    for req in requirements:
        if quote_in(req.get("postingQuote"), description):
            kept.append(req)
        else:
            warnings.append(
                f"dropped requirement {req.get('id')!r} ({req.get('text')!r}): "
                f"postingQuote not found in the ad: {req.get('postingQuote')!r}"
            )
    return kept, warnings


def _resolved(req: dict, status: str, evidence_id, quote, verified: bool, strength: int) -> dict:
    return {
        **req,
        "status": status,
        "evidenceId": evidence_id,
        "evidenceQuote": quote,
        "quoteVerified": verified,
        "strength": strength,
    }


def _years(qualifier: dict | None) -> int | None:
    return qualifier["value"] if qualifier and qualifier.get("kind") == "years" else None


def apply_confirmed_fact(req: dict, fact: dict, evidence_by_id: dict[str, dict], vocabulary: str = "production") -> dict | None:
    """The requirement as the user's answer settles it (spec 4.4), or None when the matcher's verdict stands."""
    answer = fact["answer"]
    if answer == "no":
        return _resolved(req, VOCABULARY[vocabulary]["contradicted"], None, None, True, 0)
    if answer not in ("yes", "partly"):
        return None
    asked, confirmed = _years(req.get("qualifier")), _years(fact.get("qualifier"))
    if asked is not None and confirmed is None:
        return None
    below_level = asked is not None and confirmed < asked
    status = "PARTIAL" if answer == "partly" or below_level else "MET"
    evidence_id = fact.get("evidenceId") if fact.get("evidenceId") in evidence_by_id else None
    settled = _resolved(req, status, evidence_id, None, True, CONFIRMED_FACT_STRENGTH)
    if answer == "yes" and below_level:
        settled["levelReason"] = f"{confirmed} year{'' if confirmed == 1 else 's'} confirmed, ad asks {asked}+"
    return settled


def resolve_fact(req: dict, candidate: dict, evidence_by_id: dict[str, dict]) -> dict | None:
    """The requirement as the candidate's confirmed answer settles it, or None when the matcher's verdict stands."""
    fact = fact_for(req, candidate)
    return apply_confirmed_fact(req, fact, evidence_by_id) if fact else None


def apply_proposal(req: dict, proposal: dict, evidence_by_id: dict[str, dict]) -> tuple[dict, str | None]:
    """(the requirement with its verified status, a warning or None).

    MET/PARTIAL keep their status only when evidenceQuote is in the text of
    evidenceId. Otherwise MET becomes PARTIAL at claim strength and PARTIAL
    becomes UNKNOWN. A verified strength is never above the item's own
    (section 4.3). MISSING and UNKNOWN carry no evidence.
    """
    status = proposal["status"]
    if status in ("MISSING", "UNKNOWN"):
        return _resolved(req, status, None, None, False, 0), None

    item = evidence_by_id.get(proposal.get("evidenceId"))
    quote = proposal.get("evidenceQuote")
    proposed = proposal["strength"]

    if item and quote_in(quote, item["text"]):
        return _resolved(req, status, item["id"], quote, True, min(proposed, item["strength"])), None

    lowered = DOWNGRADE[status]
    warning = (
        f"requirement {req['id']!r}: {status} lowered to {lowered}, evidence quote "
        f"{quote!r} not found in {proposal.get('evidenceId')!r}"
    )
    if lowered == "UNKNOWN":
        return _resolved(req, "UNKNOWN", None, None, False, 0), warning
    return (
        _resolved(
            req, lowered, item["id"] if item else None, quote if (quote or "").strip() else None, False,
            min(proposed, CLAIM_STRENGTH),
        ),
        warning,
    )
