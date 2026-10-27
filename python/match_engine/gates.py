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
                      config (scorer.accepted_tracks); unknown when the profile
                      sets no family.

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
from scorer import accepted_tracks, track_has_evidence
from text_utils import normalize_text

from .verify import CONFIRMED_FACT_STRENGTH, _resolved

GATES = ("work_authorization", "location", "language", "salary_floor", "role_family")
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
    "Bosnian": r"bosnian|bosansk\w*",
    "Montenegrin": r"montenegrin|crnogorsk\w*",
    # "BCS" alone is the British Computer Society in a UK ad, so it counts only next to "language".
    "Serbo-Croatian": r"serbo[- ]?croatian|bcms|bhs|b/c/s|bcs(?= language| speaker)",
    "Macedonian": r"macedonian|makedonsk\w*",
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
    r"\b[abc][12]\b|poznavanj\w*|znanj\w*|tecn\w*|(?:required|mandatory|essential|must)\W+(?:\w+\W+){0,2}$"
)
# "required" must follow the language directly: "Spanish, where required" is about postings, not the hire.
_ASK_AFTER = (r"written|spoken|fluen\w*|proficien\w*|level|\b[abc][12]\b|jezik\w*|native|"
              r"^\W*(?:is\s+|are\s+)?(?:required|mandatory|essential)")
# A clause that calls the language a plus is a nice-to-have, not a gate.
_OPTIONAL = re.compile(
    r"\b(?:plus|advantage|bonus|nice to have|preferred|desirable|prednost|an asset|beneficial|ideally|optional)\b")
# "German or English", "English and/or Russian": any one of the named languages will do.
_ALTERNATIVE = re.compile(r"\b(?:or|and/or|ili)\b|/")
# Clauses are cut from the raw ad, before normalize_text collapses its line
# breaks and tags: one bullet is one clause, so a "preferred" in one bullet
# does not hide the language another bullet requires.
_CLAUSE_BREAK = re.compile(r"<[^>]+>|[.;!?\n\u2022]|\s[-*]\s")


def _clauses(description: str) -> list[str]:
    parts = _CLAUSE_BREAK.split(html.unescape(description or ""))
    return [c for c in (normalize_text(p) for p in parts) if c]


def _languages_in(text: str) -> set[str]:
    return {lang for lang, pattern in _NAME.items() if pattern.search(text)}


REQUIRED, OPTIONAL, MENTIONED = "required", "optional", "mentioned"


def _split_by_marker(clause: str) -> list[str]:
    """A clause cut at the commas where "a plus" starts or stops applying:
    "German is an advantage, fluent English required" is two statements."""
    parts = clause.split(", ")
    out = [parts[0]]
    for part in parts[1:]:
        if bool(_OPTIONAL.search(out[-1])) != bool(_OPTIONAL.search(part)):
            out.append(part)
        else:
            out[-1] += ", " + part
    return out


def language_demands(job: dict, requirements: list[dict] | None = None) -> list[tuple[frozenset, str]]:
    """What the ad asks for in languages: [(alternatives, level)], level required, optional or mentioned.

    `alternatives` is the set of languages of which one is enough ("German or
    English"). A must-have language requirement is required, any other
    importance optional (the extraction says which). The ad's own clauses are
    read as well: a language next to words that ask for it is required unless
    the clause calls it a plus; a bare mention is only "mentioned" and
    settles nothing. Required wins over optional wins over mentioned.
    """
    demands: dict[frozenset, str] = {}

    def add(group, level):
        group = frozenset(group)
        rank = (MENTIONED, OPTIONAL, REQUIRED)
        if group and rank.index(level) >= rank.index(demands.get(group, MENTIONED)):
            demands[group] = level

    for req in requirements or []:
        if req.get("kind") == "language":
            named = _languages_in(normalize_text(f"{req.get('text') or ''} {req.get('postingQuote') or ''}"))
            if named:
                level = REQUIRED if req.get("importance") == "must" else OPTIONAL
                alt = _ALTERNATIVE.search(normalize_text(f"{req.get('text') or ''} {req.get('postingQuote') or ''}"))
                for group in ([named] if alt else [{lang} for lang in named]):
                    add(group, level)
    extracted = set().union(*demands) if demands else set()
    for clause in (part for c in _clauses(job.get("description") or "") for part in _split_by_marker(c)):
        optional = bool(_OPTIONAL.search(clause))
        asked = set()
        for lang, name in _NAME.items():
            for match in name.finditer(clause):
                before = clause[max(0, match.start() - 40):match.start()]
                after = clause[match.end():match.end() + 40]
                if re.search(_ASK_BEFORE, before) or re.search(_ASK_AFTER, after):
                    asked.add(lang)
        # The extraction already says how the ad treats a language it extracted; the clause is not read again.
        named = _languages_in(clause) - extracted
        asked &= named
        if len(named) > 1 and _ALTERNATIVE.search(clause) and asked:
            add(named, OPTIONAL if optional else REQUIRED)
            continue
        for lang in named:
            add({lang}, OPTIONAL if optional else (REQUIRED if lang in asked else MENTIONED))
    # An extracted requirement already says how the ad treats a language: drop its bare mentions.
    settled = set().union(*(g for g, level in demands.items() if level != MENTIONED)) if demands else set()
    return [(g, level) for g, level in demands.items() if level != MENTIONED or not (g <= settled)]


def required_languages(job: dict, requirements: list[dict] | None = None) -> set[str]:
    """Every language some required demand names (alternatives included)."""
    return set().union(*(g for g, level in language_demands(job, requirements) if level == REQUIRED), set())


# Languages that count as one for the candidate: speaking any member covers all of them, and
# `also` are covered too. Small on purpose; an entry is an owner decision (ENGINE_CONTRACT.md).
LANGUAGE_COVERAGE = (
    {"members": frozenset({"Serbian", "Croatian", "Bosnian", "Montenegrin", "Serbo-Croatian"}),
     "also": frozenset({"Macedonian"})},  # the owner states he understands Macedonian
)


def covered_languages(spoken: set[str]) -> set[str]:
    """The languages the list covers: those it names, plus a spoken one's close relatives."""
    covered = set(spoken)
    for group in LANGUAGE_COVERAGE:
        if spoken & group["members"]:
            covered |= group["members"] | group["also"]
    return covered


# Where a language requirement settled in code points for its evidence: the
# candidate's own language list, which is never sent to the provider.
LANGUAGES_EVIDENCE_ID = "gates.languages"


def _spoken(gates: dict) -> dict[str, str]:
    """Each language the candidate lists, by name, with the entry that names it ("English (fluent)")."""
    spoken = {}
    for entry in gates.get("languages") or []:
        for lang in _languages_in(normalize_text(entry)):
            spoken.setdefault(lang, entry)
    return spoken


def settle_language(req: dict, candidate: dict) -> dict | None:
    """A kind-language requirement resolved in code, or None to leave it to the matcher.

    The spoken-languages list is closed: a language is covered when it is on
    the list or a close relative of a listed one (covered_languages). The
    language name only, not the level. MET when the requirement is covered
    (every language it names, or any one of them when they are alternatives),
    credited as the candidate's own statement (CONFIRMED_FACT_STRENGTH).
    Not covered: MISSING, whatever the importance; a CV item that mentions
    the language hands an optional requirement to the matcher as before, and
    for a must-have it is a conflict (the gate fails the ad) that is reported
    in `conflict`, not decided. UNKNOWN when the candidate lists no languages
    at all. A requirement that names no language the table knows goes to the
    matcher.
    """
    if req.get("kind") != "language":
        return None
    text = normalize_text(f"{req.get('text') or ''} {req.get('postingQuote') or ''}")
    named = _languages_in(text)
    if not named:
        return None
    gates = candidate.get("gates") or {}
    if not gates.get("languages"):
        return _resolved(req, "UNKNOWN", None, None, False, 0)
    spoken = _spoken(gates)
    covered = covered_languages(set(spoken))
    ok = bool(named & covered) if _ALTERNATIVE.search(text) else named <= covered
    if ok:
        entries = {spoken[lang] for lang in spoken if named & covered_languages({lang})}
        return _resolved(req, "MET", LANGUAGES_EVIDENCE_ID, "; ".join(sorted(entries)), True, CONFIRMED_FACT_STRENGTH)
    lacking = named - covered
    mentioned = set().union(*(_languages_in(normalize_text(e.get("text") or "")) for e in candidate.get("evidence") or []))
    if lacking & mentioned:
        if req.get("importance") != "must":
            return None
        missing = _resolved(req, "MISSING", None, None, False, 0)
        missing["conflict"] = (f"language requirement {req.get('id')!r} is must-have and not covered by the profile's "
                               f"languages, but a CV item mentions {', '.join(sorted(lacking & mentioned))}")
        return missing
    return _resolved(req, "MISSING", None, None, False, 0)


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
    """Fail outside the allowed places; unknown when a remote ad does not say Serbia is included; pass when it does."""
    prefs = _prefs(gates)
    authorization = wa.authorization_status(job, prefs)
    if authorization["status"] == wa.OUTSIDE_ALLOWED:
        return FAIL
    state = (authorization.get("location") or {}).get("state")
    if state == "unknown":
        return UNKNOWN
    if state == "pass":
        return PASS
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
    """Fail on a required language the closed list does not cover; unknown when nothing is settled.

    Required means the extraction marks it must-have or the ad's clause asks
    for it ("fluent", "required", "native"). Covered means on the candidate's
    list or a close relative of a listed language (covered_languages); of
    alternatives ("German or English") one is enough. A preferred or plus
    language never fails, and a bare mention settles nothing. Unknown also
    when the candidate lists no languages. Only the language is compared,
    not the level.
    """
    spoken = set(_spoken(gates))
    required = [alternatives for alternatives, level in language_demands(job, requirements) if level == REQUIRED]
    if not required or not spoken:
        return UNKNOWN
    covered = covered_languages(spoken)
    return PASS if all(group & covered for group in required) else FAIL


def salary_floor_result(job: dict, gates: dict) -> str:
    """Unknown without a floor; fail only when even the top of a readable range is under it."""
    floor = gates.get("minSalaryEur")
    if floor is None:
        return UNKNOWN
    below = below_minimum(parse_monthly_eur(job.get("salary")), floor)
    return FAIL if below else PASS


def role_family_result(job: dict, role_family: str | None) -> str:
    """The posting's role track against the tracks the candidate's family accepts.

    Unknown when the profile sets no family, the ad's track was not read, or
    the track is "other" or has no evidence quote: nothing is assumed in any
    of those cases (scorer.track_is_off_track).
    """
    facts = job.get("llmFacts") or {}
    track = facts.get("roleTrack")
    if not track or not role_family or not track_has_evidence(facts):
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


# The gates that need only what is stored with the ad (its text, llmFacts and
# the candidate's profile): a fail here is known before any model call.
CHEAP_GATES = ("language", "work_authorization", "location", "role_family")


def cheap_gate_failures(job: dict, candidate: dict) -> list[str]:
    """The CHEAP_GATES that fail for this ad, from the existing gate functions; unknown never fails."""
    reqs = (job.get("llmFacts") or {}).get("requirements")
    failed = {g["gate"] for g in gate_results(job, candidate, None, reqs) if g["result"] == FAIL}
    return [g for g in CHEAP_GATES if g in failed]


def bucket_for(gates: list[dict]) -> str:
    """Any fail: blocked; else any unknown: check_first; else apply (contract 5.4)."""
    worst = max((_RANK[g["result"]] for g in gates), default=_RANK[PASS])
    return {0: "apply", 1: "check_first", 2: "blocked"}[worst]
