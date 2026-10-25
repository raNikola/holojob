"""Code's half of matching: check every quote, then fix status and strength.

Contract section 5.2. The model proposes; nothing here trusts the proposal
further than the quotes it can show. A status is only ever lowered here.
"""

from __future__ import annotations

from .normalize import quote_in

STATUSES = ("MET", "PARTIAL", "MISSING", "UNKNOWN")
# One step down for a MET or PARTIAL whose evidence quote does not check out.
DOWNGRADE = {"MET": "PARTIAL", "PARTIAL": "UNKNOWN"}
CLAIM_STRENGTH = 1
# What a confirmed "yes" is credited at. The user's own answer is not an
# outcome with a number, but it is more than a listed skill. Calibrated with the
# other constants in step 5 (ENGINE_CONTRACT.md, Open points 1).
CONFIRMED_FACT_STRENGTH = 3


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


def apply_confirmed_fact(req: dict, fact: dict, evidence_by_id: dict[str, dict]) -> dict:
    """A user's answer settles the requirement; the model is not asked about it."""
    if fact["has"]:
        evidence_id = fact.get("evidenceId") if fact.get("evidenceId") in evidence_by_id else None
        return _resolved(req, "MET", evidence_id, None, True, CONFIRMED_FACT_STRENGTH)
    return _resolved(req, "MISSING", None, None, True, 0)


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
