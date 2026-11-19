"""Blocking facts: what makes an ad one the candidate cannot take (Step 2b, scoringVersion 1.5, no score change).

A blocked ad keeps its Fit number and stays visible; only the verdict (Apply / priority) reads this. Each blocker is a fact
the profile already expresses:

  sponsorship_refused  eligibility.py state "sponsorship_refused" (a refusing quote found in the ad, or a right to work required outside
                       the authorized countries; B2B wording keeps it unknown)
  language             the ad REQUIRES a language the profile's declared list does not cover, AND the extraction's postingQuote for that
                       demand is found in the ad's own description. Anything less is "unconfirmed": a flag beside the score, never Blocked
                       (Step 2c). With no declared language list the check is dormant: every required language shows as unconfirmed.
                       The extraction carries no required proficiency level, so only presence on the list is compared.
  location             the ad names a place outside the profile's allowedLocations, or states a geography outside them
  security_clearance   the ad REQUIRES a security clearance (security / TS-SCI / top secret / secret / public trust / NATO secret clearance)
                       or a US citizenship / "U.S. person" status (scoringVersion 1.6, owner brief 2026-11-18). Evidence is verbatim: a must-have
                       requirement whose postingQuote is found in the ad, or a sentence of the ad text; in both the sentence must say it is required (DEMAND wording), not be softened
                       (`softened`, Step 2d) and not negated ("no clearance required"). A bare mention ("Security clearance.", a benefits line)
                       is `clearance_unconfirmed`: a flag beside the score, never Blocked. The profile holds no clearance field, so no one is exempt.

Location is a state: "in" / "outside" / "unknown" (None when the profile sets no allowedLocations: dormant). A bare "Remote" with no
country is not country evidence: unknown, never "in", never "outside". The profile has no on-site exclusion field of its own;
allowedLocations is its only place list, so a place outside it is the only location fact used.
"""

from __future__ import annotations

import html
import re

import eligibility
import work_authorization as wa
from geography import REMOTE, covers

IN, OUTSIDE, UNKNOWN = "in", "outside", "unknown"


def location_state(job: dict, prefs: dict) -> dict | None:
    """{"state": in|outside|unknown, "reason"} against allowedLocations, or None when the profile sets none."""
    found = wa.resolve_places(job, prefs)
    allowed, restricted, loc, remote = found["allowed"], found["restricted"], found["location"], found["remote"]
    if not allowed:
        return None
    countries = [a for a in allowed if a != REMOTE]
    if loc and loc["state"] == "fail":
        return {"state": OUTSIDE, "reason": loc["reason"]}
    if restricted:
        if any(covers(a, p) for a in countries for p in restricted):
            return {"state": IN, "reason": f"{found['place']} is inside the locations you will take a job in"}
        if not (remote and REMOTE in allowed):
            return {"state": OUTSIDE, "reason": f"{found['place']} is outside the locations you will take a job in"}
        return {"state": UNKNOWN, "reason": f"remote, limited to {found['place']}: the ad does not say a hire may live in your places"}
    if loc and loc["state"] == "pass":
        return {"state": IN, "reason": loc["reason"]}
    return {"state": UNKNOWN, "reason": "the ad names no country, so the location was not checked"}


UNCONFIRMED_NO_LIST = "no_declared_languages"
UNCONFIRMED_NO_QUOTE = "no_quote"  # the extraction holds no must-have quote for it (read from the ad's clauses, or unread)
UNCONFIRMED_QUOTE_NOT_IN_AD = "quote_not_in_ad"
UNCONFIRMED_SOFTENED = "softened"  # the ad's own words make the language optional (a plus, preferred ...): the must-have mark is wrong

# Wording that makes a demand optional (Step 2d). Checked on the quote and on the few words beside it in the same clause.
SOFTENING = re.compile(
    r"\b(?:nice[- ]to[- ]have|(?:a|an|big|strong|real|definite|major)\s+plus|preferred|preferably|advantages?|advantageous|bonus|"
    r"desirable|beneficial|helpful|ideally|optional|an\s+asset|not\s+(?:required|necessary|mandatory))\b",
    re.I,
)
_SOFT_REACH = 40  # characters read before and after the quote
_CLAUSE_EDGE = re.compile(r"[.;\n]|\*\s")


def _plain(text) -> str:
    return re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(text or ""))).replace("’", "'"))


def softened(quote, description) -> str | None:
    """The softening word that makes the quoted demand optional, or None. Reads the quote and up to 40 characters either side of it,
    stopping at a sentence end, a line break or a bullet, so a "Nice to Have" heading or a "plus" on another line is not read into it.
    """
    q = _plain(quote).strip()
    hit = SOFTENING.search(q)
    if hit:
        return hit.group(0)
    ad, pos = _plain(description), -1
    piece = re.split(r"\.{3}|…", q)[0].strip()
    if piece:
        pos = ad.lower().find(piece.lower())
    if pos < 0:
        return None
    before = ad[max(0, pos - _SOFT_REACH):pos]
    edges = list(_CLAUSE_EDGE.finditer(before))
    before = before[edges[-1].end():] if edges else before
    after = ad[pos + len(piece):pos + len(piece) + _SOFT_REACH]
    edge = _CLAUSE_EDGE.search(after)
    after = after[:edge.start()] if edge else after
    hit = SOFTENING.search(before) or SOFTENING.search(after)
    return hit.group(0) if hit else None


def language_state(job: dict, intelligence: dict) -> dict:
    """{"blocking": [names], "unconfirmed": [{"language", "why"}], "listDeclared": bool} for the languages the ad requires.

    A required demand the declared list does not cover (close relatives count; an "A or B" group is covered by one) is blocking
    only when a must-have language requirement of the extraction names it with a postingQuote found in the ad's description
    (eligibility.quote_in_text). Otherwise unconfirmed: a demand read from the ad's clauses has no quote, an unread ad has no
    extraction, and an empty list declares nothing. An ad whose text cannot be read (gates.language_text_readable) says nothing.
    """
    from match_engine import gates as g

    declared = [str(x) for x in intelligence.get("languages") or []]
    spoken = set(g._spoken({"languages": declared}))
    out = {"blocking": [], "unconfirmed": [], "listDeclared": bool(spoken)}
    if not g.language_text_readable(job):
        return out
    requirements = (job.get("llmFacts") or {}).get("requirements") or None
    covered = g.covered_languages(spoken)
    quotes = g.must_language_quotes(requirements)
    description = job.get("description") or ""
    for group, level in g.language_demands(job, requirements):
        if level != g.REQUIRED or group & covered:
            continue
        name = " or ".join(sorted(group))
        if not spoken:
            out["unconfirmed"].append({"language": name, "why": UNCONFIRMED_NO_LIST})
        elif any(eligibility.quote_in_text(q, description) for q in quotes.get(group, [])):
            if any(softened(q, description) for q in quotes[group] if eligibility.quote_in_text(q, description)):
                out["unconfirmed"].append({"language": name, "why": UNCONFIRMED_SOFTENED})
            else:
                out["blocking"].append(name)
        else:
            why = UNCONFIRMED_QUOTE_NOT_IN_AD if quotes.get(group) else UNCONFIRMED_NO_QUOTE
            out["unconfirmed"].append({"language": name, "why": why})
    out["blocking"].sort()
    out["unconfirmed"].sort(key=lambda u: u["language"])
    return out


# What counts as a clearance or a US-status demand. A bare "clearance" or "citizenship" is not enough: "clearance sale", "EU citizenship".
CLEARANCE = re.compile(
    r"\b(?:(?:top[- ]secret|secret|public[- ]trust|nato[- ]secret|ts/sci)(?:\s+security)?\s+clearance|security\s+clearance|ts/sci|top[- ]secret|"
    r"(?:u\.?s\.?|united\s+states)\s+(?:citizen(?:ship)?|national|person)s?|citizen(?:ship)?\s+of\s+the\s+(?:u\.?s\.?|united\s+states)|"
    r"(?:citizen|national)s?\s+of\s+the\s+(?:u\.?s\.?|united\s+states))\b",
    re.I,
)
_CLEARANCE_NEGATION = re.compile(r"\b(?:no|not|without|never|neither|nor)\b[^.;\n]{0,25}$", re.I)
_CLEARANCE_NEGATION_AFTER = re.compile(r"^[^.;\n]{0,25}\b(?:not\s+(?:required|needed|necessary)|isn't\s+required|is\s+not\s+a\s+requirement)\b", re.I)
# The sentence must SAY the ad requires it. A bare "Security clearance." or a benefits-list line is a mention, not a demand (owner rule 2026-11-19).
DEMAND = re.compile(
    r"\b(?:requires?|required|requiring|requirements?|must|mandatory|need(?:s|ed)?|essential|prerequisite|obtain|hold(?:ing)?|possess(?:ion)?|"
    r"eligib(?:le|ility)|ability\s+to|able\s+to|strictly|necessary)\b",
    re.I,
)
_SENTENCES = re.compile(r"\n\s*\n|(?<=[.!?])\s+|\s*\*\s+|\n")


def _mention(sentence: str, description) -> bool:
    """True when the sentence names a clearance / US status that nothing negates and the ad does not soften (a mention, not yet a demand)."""
    plain = _plain(sentence)
    for hit in CLEARANCE.finditer(plain):
        if _CLEARANCE_NEGATION.search(plain[:hit.start()]) or _CLEARANCE_NEGATION_AFTER.search(plain[hit.end():]):
            continue
        return not softened(plain, description)
    return False


def _demanded(sentence: str, description) -> bool:
    """True when the sentence REQUIRES a clearance / US status: a mention, in demand wording."""
    return _mention(sentence, description) and bool(DEMAND.search(_plain(sentence)))


def clearance_state(job: dict) -> dict | None:
    """{"kind": "security_clearance", "quote", "basis"} when the ad requires a clearance or US status, else None.

    Reads (1) the extraction's must-have requirements: the postingQuote must be found in the ad (eligibility.quote_in_text), (2) the ad's own
    sentences, for an extraction that marked nothing. The quote is always text of the ad, so it is verbatim by construction.
    """
    description = job.get("description") or ""
    for req in (job.get("llmFacts") or {}).get("requirements") or []:
        quote = str((req or {}).get("postingQuote") or "") if isinstance(req, dict) else ""
        if (req or {}).get("importance") == "must" and quote and CLEARANCE.search(_plain(quote)) \
                and eligibility.quote_in_text(quote, description) and _demanded(quote, description):
            return {"kind": "security_clearance", "quote": quote[:300], "basis": "requirement"}
    for part in _SENTENCES.split(re.sub(r"\*+|_{2,}", " ", _plain(description))):
        sentence = " ".join(part.split())
        if 8 <= len(sentence) <= 600 and CLEARANCE.search(sentence) and _demanded(sentence, description):
            return {"kind": "security_clearance", "quote": sentence[:300], "basis": "ad_text"}
    return None


def clearance_unconfirmed(job: dict) -> dict | None:
    """{"quote"} when the ad mentions a clearance / US status without saying it is required (a bare "Security clearance.", a benefits line).

    A flag beside the score, never Blocked. None when the mention is a blocker (clearance_state) or the ad has none.
    """
    if clearance_state(job):
        return None
    description = job.get("description") or ""
    for req in (job.get("llmFacts") or {}).get("requirements") or []:
        quote = str((req or {}).get("postingQuote") or "") if isinstance(req, dict) else ""
        if (req or {}).get("importance") == "must" and quote and CLEARANCE.search(_plain(quote)) \
                and eligibility.quote_in_text(quote, description) and _mention(quote, description):
            return {"quote": quote[:300]}
    for part in _SENTENCES.split(re.sub(r"\*+|_{2,}", " ", _plain(description))):
        sentence = " ".join(part.split())
        if 8 <= len(sentence) <= 600 and CLEARANCE.search(sentence) and _mention(sentence, description):
            return {"quote": sentence[:300]}
    return None


def blockers(eligible: dict | None, language_names: list[str], location: dict | None, clearance: dict | None = None) -> list[dict]:
    """The blocking facts of one ad as [{"kind", "text"}]; [] when none."""
    out = []
    if eligible and eligible["state"] == eligibility.REFUSED:
        out.append({"kind": "sponsorship_refused", "text": eligible["reason"]})
    if language_names:
        out.append({"kind": "language", "text": f"the ad requires {' and '.join(language_names)}, which your profile does not list"})
    if location and location["state"] == OUTSIDE:
        out.append({"kind": "location", "text": location["reason"]})
    if clearance:
        out.append({"kind": "security_clearance", "text": f"the ad requires a security clearance or US status: \"{clearance['quote']}\""})
    return out
