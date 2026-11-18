"""Work authorization as a state beside the score, never inside it (Step 2, scoringVersion 1.5).

Per country, independent of willingness to relocate. States:

  authorized            the candidate's own profile lists a right to work in the ad's country
  sponsorship_offered   the ad offers a visa / permit, with a quote from the ad
  sponsorship_refused   the candidate needs a permit and the ad refuses to sponsor one (a refusing quote), or
                        requires an existing right to work in a country outside the authorized ones
  unknown ("Unconfirmed")  everything else: silence, an unread ad, an unknown country, a quote the ad does not hold

Rules:
- Nothing here lowers a score. scorer.py stores the state on the row; it never reads it back.
- A statement from the ad counts only with a quote, and the quote must be found in the ad's own text (`quote_in_text`).
  No quote, or a quote the ad does not hold, is unknown.
- Silence on visa is never a refusal. "Requires an existing right to work" with no sponsorship wording is blocked only
  when the ad's country is outside the authorized countries; with the country unknown it stays unknown.
- B2B / employer-of-record / contractor wording in the ad is a separate exception: when the candidate says B2B is
  available, a state that would be "refused" stays unknown. The wording is found by code in the ad text, so it is an ad
  quote by construction; no extraction fact is needed.
- No authorized countries in the profile means the whole check is dormant: `assess` returns None, no state, no badge.
"""

from __future__ import annotations

import html
import re

import work_authorization as wa
from geography import covers
from text_utils import normalize_text

AUTHORIZED = "authorized"
OFFERED = "sponsorship_offered"
REFUSED = "sponsorship_refused"
UNKNOWN = "unknown"
LABELS = {AUTHORIZED: "Authorized", OFFERED: "Sponsorship offered", REFUSED: "Sponsorship refused", UNKNOWN: "Unconfirmed"}

_MIN_PIECE = 8  # a quote fragment shorter than this proves nothing about the ad

_NEGATION = re.compile(r"\b(?:no|not|without|never|cannot|can't|don't|doesn't|won't)\b[^.;]{0,25}$")
_B2B_PATTERNS = [re.compile(p) for p in (
    r"\bb2b\b",
    r"\bbusiness[- ]to[- ]business\b",
    r"\bemployer[- ]of[- ]record\b",
    r"\beor\b",
    r"\b(?:independent[- ])?contractors?\s+(?:agreement|basis|arrangement|model|engagement|welcome|accepted|are\s+welcome|are\s+accepted)\b",
    r"\b(?:open|happy|available|possible)\s+(?:to|for)\s+(?:\w+\s+){0,3}contractors?\b",
    r"\bcontract(?:or)?\s+basis\b",
)]


def _quote_text(text) -> str:
    # Markdown emphasis ("***does not offer sponsorship***", "**not**" on its own line) is formatting, not words.
    plain = re.sub(r"\*+|_{2,}", " ", str(text or "")).replace("’", "'").replace("‘", "'")
    return normalize_text(plain)


def refusal_in_text(description) -> str | None:
    """The ad's own sentence that refuses sponsorship, a visa or a permit, or None.

    For an ad whose extraction did not mark the refusal. The sentence comes from the stored text, so it is verbatim by
    construction; the pattern is the one every other refusal uses (work_authorization.refuses_sponsorship).
    """
    plain = re.sub(r"\*+|_{2,}", " ", re.sub(r"<[^>]+>", " ", html.unescape(str(description or ""))))
    for part in re.split(r"\n\s*\n|(?<=[.!?])\s+", plain):
        sentence = " ".join(part.split())
        if 8 <= len(sentence) <= 400 and wa.refuses_sponsorship(sentence):
            return sentence
    return None


def quote_in_text(quote, description) -> bool:
    """True when the quote's words are in the ad's own text (case, tags, spacing and diacritics ignored).

    An ellipsis splits a quote into fragments that must each be found; a fragment under eight characters is not evidence.
    """
    ad = _quote_text(description)
    pieces = [p.strip() for p in re.split(r"\.{3}|…", _quote_text(quote)) if p.strip()]
    if not ad or not pieces:
        return False
    return all(len(p) >= _MIN_PIECE and p in ad for p in pieces)


def b2b_wording(description) -> str | None:
    """A short stretch of the ad that accepts B2B / employer-of-record / contractor work, or None."""
    ad = _quote_text(description)
    for pattern in _B2B_PATTERNS:
        for match in pattern.finditer(ad):
            if not _NEGATION.search(ad[max(0, match.start() - 40):match.start()]):
                return ad[max(0, match.start() - 30):match.end() + 30].strip()
    return None


def _result(state: str, country: str, reason: str, *, quote: str | None = None, kind: str, basis: str, b2b: bool = False) -> dict:
    return {"state": state, "label": LABELS[state], "country": country, "reason": reason, "quote": quote, "kind": kind,
            "basis": basis, "b2b": b2b}


def assess(job: dict, prefs: dict) -> dict | None:
    """The eligibility of one job for the candidate, or None when the profile lists no authorized country (dormant)."""
    holds = wa._holds(prefs)
    if not holds:
        return None
    facts = job.get("llmFacts") or {}
    basis = wa.AD_READ if facts else wa.NOT_READ
    found = wa.resolve_places(job, prefs)
    restricted, place = found["restricted"], found["place"]
    if not restricted:
        return _result(UNKNOWN, place, "the ad does not pin the job to a country, so the right to work was not checked",
                       kind="no_country", basis=basis)
    covered = [p for p in restricted if any(covers(right, p) for right in holds)]
    if covered:
        return _result(AUTHORIZED, covered[0], f"your profile lists a right to work in {covered[0]}", kind="profile", basis=basis)
    if not facts:
        return _result(UNKNOWN, place, f"needs a work permit for {place}; the ad was not read, so sponsorship is unverified",
                       kind="not_read", basis=basis)

    description = job.get("description")
    sponsorship = facts.get("visaSponsorship") or "not_mentioned"
    evidence = str(facts.get("visaEvidence") or "").strip()
    quoted = bool(evidence) and quote_in_text(evidence, description)
    open_to_sponsorship = bool((prefs.get("workAuthorization") or {}).get("openToSponsorship"))
    b2b_ok = bool((prefs.get("workAuthorization") or {}).get("b2bAvailable"))

    def blocked(reason: str, kind: str, quote: str = evidence) -> dict:
        wording = b2b_wording(description) if b2b_ok else None
        if wording:
            return _result(UNKNOWN, place, f"{reason}; the ad also accepts B2B or contractor work", quote=wording, kind="b2b_exception",
                           basis=basis, b2b=True)
        return _result(REFUSED, place, reason, quote=quote, kind=kind, basis=basis)

    if sponsorship == "offered" and quoted:
        if open_to_sponsorship:
            return _result(OFFERED, place, f"needs a work permit for {place}; the ad offers sponsorship", quote=evidence,
                           kind="offered", basis=basis)
        return blocked(f"needs a work permit for {place}; the ad offers sponsorship and you are not open to sponsored roles",
                       "not_open_to_sponsorship")
    if sponsorship == "not_offered" and quoted:
        if wa.refuses_sponsorship(evidence):
            return blocked(f"needs a work permit for {place} and the ad does not sponsor one", "refused")
        return blocked(f"requires an existing right to work, and {place} is outside your authorized countries", "right_to_work_required")
    if sponsorship != "offered" and not (quoted and wa.refuses_sponsorship(evidence)):
        # The extraction marked no refusal (silent, or a quote that is no refusal): the ad's own words may still hold one.
        sentence = refusal_in_text(description)
        if sentence:
            return blocked(f"needs a work permit for {place} and the ad does not sponsor one", "refused_in_text", sentence)
    if evidence and not quoted:
        return _result(UNKNOWN, place, "the ad's visa quote is not found in its text, so it was not used", kind="quote_not_in_ad", basis=basis)
    return _result(UNKNOWN, place, f"needs a work permit for {place}; the ad does not mention sponsorship", kind="silent", basis=basis)
