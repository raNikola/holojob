"""The five gates, each pass, unknown or fail, decided in code (contract 5.4).

Every result comes from logic the current scorer already uses, so the engine
and matchScore read the same facts the same way:

  work_authorization  work_authorization.authorization_status, without the
                      candidate's location set (that is the location gate).
  location            the same status's OUTSIDE_ALLOWED, then
                      location_match.score_location_match's verdict.
  language            candidate.gates.languages against the languages the ad
                      requires, read in code from must-have language
                      requirements and from the ad's own sentences.
  salary_floor        salary.parse_monthly_eur and salary.below_minimum.
  role_family         the posting's llmFacts.roleTrack against the role-family
                      config (scorer.accepted_tracks).

The model's quote for a gate is carried for display and decides nothing.
Unknown is never fail: a gate fails only on a stated fact that rules the job
out, the way "unknown never caps" holds for matchScore.

`job` is the discovered job with its llmFacts, not the contract's `posting`:
the gates need fields the posting does not carry (salary, isRemote,
workMode, remoteEligibility, visaSponsorship).
"""

from __future__ import annotations

import html
import re

import work_authorization as wa
from dimensions import location_match as lm
from salary import below_minimum, parse_monthly_eur
from scorer import accepted_tracks
from text_utils import normalize_text

from .matcher import GATES

PASS, UNKNOWN, FAIL = "pass", "unknown", "fail"
_RANK = {PASS: 0, UNKNOWN: 1, FAIL: 2}

AUTHORIZATION_RESULTS = {
    wa.AUTHORIZED: PASS,
    wa.SPONSORED: PASS,
    wa.NEEDS_VISA_REFUSED: FAIL,
    # Silent on sponsorship: many employers sponsor when asked, so check first.
    wa.NEEDS_VISA_SILENT: UNKNOWN,
    wa.UNKNOWN: UNKNOWN,
}

# location_match's scores, read as a verdict. Only a confirmed onsite role
# away from the candidate's own cities fails; hybrid and an unknown work mode
# are worth checking, not ruling out.
LOCATION_RESULTS = {
    lm.REMOTE_PREFERRED: PASS,
    lm.REMOTE: PASS,
    lm.PREFERRED_PLACE: PASS,
    lm.RELOCATION_ACCEPTABLE: PASS,
    lm.HYBRID_ELSEWHERE: UNKNOWN,
    lm.UNKNOWN_LOCATION: UNKNOWN,
    lm.NOT_REMOTE_UNKNOWN_MODE: UNKNOWN,
    lm.COUNTRY_ONLY_UNKNOWN_MODE: UNKNOWN,
    lm.ONSITE_ELSEWHERE: FAIL,
}

# Spoken languages, matched on folded text (text_utils), English and Serbian
# spellings. A name the table does not know is not read at all.
LANGUAGES = {
    "English": r"english|englesk\w*",
    "Serbian": r"serbian|srpsk\w*",
    "Croatian": r"croatian|hrvatsk\w*",
    "German": r"german|deutsch|nemack\w*|njemack\w*",
    "French": r"french|francusk\w*",
    "Spanish": r"spanish|spansk\w*",
    "Italian": r"italian|italijansk\w*",
    "Russian": r"russian|rusk(?:i|og|om)\b",
    "Dutch": r"dutch|holandsk\w*",
    "Portuguese": r"portuguese|portugalsk\w*",
    "Hungarian": r"hungarian|madarsk\w*",
    "Romanian": r"romanian|rumunsk\w*",
    "Bulgarian": r"bulgarian|bugarsk\w*",
    "Greek": r"greek|grck\w*",
    "Turkish": r"turkish|tursk\w*",
    "Swedish": r"swedish|svedsk\w*",
    "Norwegian": r"norwegian|norvesk\w*",
    "Danish": r"danish|dansk\w*",
    "Finnish": r"finnish|finsk\w*",
    "Czech": r"czech|cesk\w*",
    "Arabic": r"arabic|arapsk\w*",
    "Chinese": r"chinese|mandarin|kinesk\w*",
    "Japanese": r"japanese|japansk\w*",
}
_NAME = {lang: re.compile(rf"\b(?:{pattern})\b") for lang, pattern in LANGUAGES.items()}

# A language counts as required only next to words that ask for it, within
# one clause: "fluency in spoken and written English", "upper-intermediate
# or higher level of English", "poznavanje engleskog jezika". A bare mention
# ("sharpen your English skills" in a benefits list) is not a requirement.
_ASK_BEFORE = (
    r"fluen\w*|proficien\w*|command of|knowledge of|level of|native|exceptional|excellent|"
    r"advanced|intermediate|written|spoken|communicat\w*|speak\w*|"
    r"\b[abc][12]\b|poznavanj\w*|znanj\w*|tecn\w*"
)
_ASK_AFTER = r"written|spoken|fluen\w*|proficien\w*|level|\b[abc][12]\b|jezik\w*"
# A clause that calls the language a plus is a nice-to-have, not a gate.
_OPTIONAL = re.compile(r"\b(?:plus|advantage|bonus|nice to have|preferred|desirable|prednost)\b")
# Clauses are cut from the raw ad, before normalize_text collapses its line
# breaks and tags: one bullet is one clause, so a "preferred" in one bullet
# does not hide the language another bullet requires.
_CLAUSE_BREAK = re.compile(r"<[^>]+>|[.;!?\n\u2022]|\s[-*]\s")


def _clauses(description: str) -> list[str]:
    parts = _CLAUSE_BREAK.split(html.unescape(description or ""))
    return [c for c in (normalize_text(p) for p in parts) if c]


def _languages_in(text: str) -> set[str]:
    return {lang for lang, pattern in _NAME.items() if pattern.search(text)}


def required_languages(job: dict, requirements: list[dict] | None = None) -> set[str]:
    """Languages the ad requires: must-have language requirements, then the ad's own clauses."""
    found = set()
    for req in requirements or []:
        if req.get("kind") == "language" and req.get("importance") == "must":
            found |= _languages_in(normalize_text(f"{req.get('text') or ''} {req.get('postingQuote') or ''}"))
    for clause in _clauses(job.get("description") or ""):
        if _OPTIONAL.search(clause):
            continue
        for lang, name in _NAME.items():
            for match in name.finditer(clause):
                before = clause[max(0, match.start() - 40):match.start()]
                after = clause[match.end():match.end() + 40]
                if re.search(_ASK_BEFORE, before) or re.search(_ASK_AFTER, after):
                    found.add(lang)
    return found


def _prefs(gates: dict) -> dict:
    """candidate.gates in the jobFitPreferences shape the existing modules read."""
    return {
        "workAuthorization": gates.get("workAuthorization") or {},
        "allowedLocations": gates.get("allowedLocations") or [],
        "preferredLocations": gates.get("preferredLocations") or [],
        "remotePreference": gates.get("remotePreference") or "",
        "relocation": gates.get("relocation") or "none",
        "country": gates.get("country") or "",
    }


def work_authorization_result(job: dict, gates: dict) -> str:
    prefs = {**_prefs(gates), "allowedLocations": []}
    return AUTHORIZATION_RESULTS[wa.authorization_status(job, prefs)["status"]]


def location_result(job: dict, gates: dict) -> str:
    prefs = _prefs(gates)
    if wa.authorization_status(job, prefs)["status"] == wa.OUTSIDE_ALLOWED:
        return FAIL
    score, _ = lm.score_location_match(job, {"jobFitPreferences": prefs})
    result = LOCATION_RESULTS[score]
    # "Elsewhere" means away from the cities the candidate named; with none
    # named, nothing is known to be elsewhere.
    if result == FAIL and not _commute_places(prefs):
        return UNKNOWN
    return result


def _commute_places(prefs: dict) -> list[str]:
    """The cities location_match treats as places to commute to (countries never are)."""
    named = [normalize_text(p) for p in prefs["preferredLocations"]]
    return [p for p in named if p and p != "remote" and not lm.country_of_name(p)]


def language_result(job: dict, gates: dict, requirements: list[dict] | None = None) -> str:
    """Unknown when the ad states no language or the candidate lists none; fail on one they do not speak.

    Only the language is compared, not the level: a stated level is read
    neither from the ad nor from "English (fluent)".
    """
    required = required_languages(job, requirements)
    spoken = set().union(*(_languages_in(normalize_text(s)) for s in gates.get("languages") or []))
    if not required or not spoken:
        return UNKNOWN
    return PASS if required <= spoken else FAIL


def salary_floor_result(job: dict, gates: dict) -> str:
    """Unknown without a floor; fail only when even the top of a readable range is under it."""
    floor = gates.get("minSalaryEur")
    if floor is None:
        return UNKNOWN
    below = below_minimum(parse_monthly_eur(job.get("salary")), floor)
    return FAIL if below else PASS


def role_family_result(job: dict, role_family: str | None) -> str:
    """The posting's role track against the tracks the candidate's family accepts.

    A null family uses scorer.py's transition family, as matchScore does,
    until the profile carries one (contract 1.1).
    """
    track = (job.get("llmFacts") or {}).get("roleTrack")
    if not track:
        return UNKNOWN
    _, tracks = accepted_tracks({"roleFamily": role_family})
    return PASS if track in tracks else FAIL


def gate_results(job: dict, candidate: dict, quotes=None, requirements: list[dict] | None = None) -> list[dict]:
    """All five gates in contract order, each {gate, result, quote}.

    `quotes` is the matcher's gates[] ({gate, quote}) or a dict by gate name;
    a gate it does not cover gets a null quote.
    """
    if isinstance(quotes, list):
        quotes = {q.get("gate"): q.get("quote") for q in quotes if isinstance(q, dict)}
    quotes = quotes or {}
    gates = candidate.get("gates") or {}
    results = {
        "work_authorization": work_authorization_result(job, gates),
        "location": location_result(job, gates),
        "language": language_result(job, gates, requirements),
        "salary_floor": salary_floor_result(job, gates),
        "role_family": role_family_result(job, candidate.get("roleFamily")),
    }
    return [{"gate": gate, "result": results[gate], "quote": quotes.get(gate)} for gate in GATES]


def bucket_for(gates: list[dict]) -> str:
    """Any fail: blocked; else any unknown: check_first; else apply (contract 5.4)."""
    worst = max((_RANK[g["result"]] for g in gates), default=_RANK[PASS])
    return {0: "apply", 1: "check_first", 2: "blocked"}[worst]
