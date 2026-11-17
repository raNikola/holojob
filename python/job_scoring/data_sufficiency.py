"""Read status: did the ad give the scorer anything to read? (Step 2, scoringVersion 1.5; replaces the cap-5 rule.)

Two statuses, neither a length threshold:

  not_read               the description is empty or unreadable (no word in it). Nothing about the ad is known, so
                         there is no Fit Score at all: every dimension would only be a neutral baseline. The row is shown
                         in its own group and the keyword score is not presented as comparable to a rated ad's.
  insufficient_evidence  the description is readable but no usable requirement was extracted from it (no facts, or facts
                         with an empty requirement list). A status shown beside the score, with low confidence; it does
                         not change the score. Extraction, not the length of the text, is what is missing.

Anything else is `read`. An ad known to be cut off at source (Infostud `descriptionStatus`) is still read, with a
low-confidence reason (owner decision, Wave 5).
"""

from __future__ import annotations

from text_utils import normalize_text, term_tokens

LOW_CONFIDENCE_CHARS = 400  # below this a scored ad is shown with a low-confidence reason

INCOMPLETE_STATUSES = ("teaser", "failed", "source_truncated")  # mirrors providers/infostud_description.INCOMPLETE
INCOMPLETE_REASON = "Description incomplete (ad text cut off at source)"

READ = "read"
INSUFFICIENT_EVIDENCE = "insufficient_evidence"
NOT_READ = "not_read"
# dataStatus on a row: "sufficient" for read and insufficient_evidence (they keep a Fit Score), "not_read" for no score.
STATE = NOT_READ


def _requirements(job: dict) -> list:
    facts = job.get("llmFacts") or {}
    return [r for r in (facts.get("requirements") or []) if isinstance(r, dict) and (r.get("text") or "").strip()]


def description_incomplete(job: dict) -> bool:
    """The ad's description is known not to be whole. An ad without a status (every other source) is never incomplete."""
    return (job.get("descriptionStatus") or "") in INCOMPLETE_STATUSES


def metrics(job: dict) -> dict:
    desc = normalize_text(job.get("description") if isinstance(job.get("description"), str) else "")
    return {"chars": len(desc), "terms": len(term_tokens(desc)), "requirements": len(_requirements(job))}


def read_status(job: dict) -> tuple[str, list[str]]:
    """(status, reasons) for one ad."""
    m = metrics(job)
    if not m["terms"]:
        return NOT_READ, ["The description is empty or could not be read"]
    if not m["requirements"]:
        return INSUFFICIENT_EVIDENCE, ["No requirements or responsibilities could be read from the ad"]
    return READ, []


def low_confidence(job: dict, *, location_stated: bool, seniority_stated: bool, has_keyword_bank: bool) -> list[str]:
    """Reasons a score that was computed deserves less trust. The score itself is not changed."""
    m = metrics(job)
    reasons = []
    if description_incomplete(job):
        reasons.append(INCOMPLETE_REASON)
    if not m["requirements"]:
        reasons.append("Requirements not extracted: must-have and nice-to-have are not separated")
    if m["chars"] < LOW_CONFIDENCE_CHARS:
        reasons.append(f"Short description ({m['chars']} characters)")
    if not location_stated:
        reasons.append("Location not stated")
    if not seniority_stated:
        reasons.append("Seniority not stated")
    if not has_keyword_bank:
        reasons.append("No keyword bank in the profile: skill match is a neutral baseline")
    return reasons
