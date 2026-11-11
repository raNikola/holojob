"""The matcher's verification: normalization, quotes, downgrade, confirmed facts, failures."""

import pytest

from llm_client import LlmRefused, LlmUnavailable
from match_engine.matcher import GATES, NotConfirmed, cache_key, match_posting
from match_engine.normalize import normalize, quote_in
from match_engine.verify import CONFIRMED_FACT_STRENGTH, apply_proposal, drop_unquoted

DESCRIPTION = (
    "We are hiring a Product Manager in Niš.\n\n"
    "Requirements:\n"
    "  * 5+ years   of product management experience\n"
    "  * Hands-on SQL for self-serve analytics\n"
    "  * Fluent English\n"
    "Fully remote within Serbia."
)

EVIDENCE = [
    {"id": "ev-a", "text": "Led roadmap ownership for a B2B SaaS platform used by 10 carriers.",
     "source": "role", "role": "PM — Acme", "start": "2024-04", "end": None, "strength": 4},
    {"id": "ev-b", "text": "SQL", "source": "fact", "role": None, "start": None, "end": None, "strength": 1},
]


def _req(rid, text, quote, importance="must", kind="skill"):
    return {"id": rid, "provisional": rid.startswith("prov:"), "text": text, "kind": kind,
            "importance": importance, "postingQuote": quote}


REQS = [
    _req("product-management", "5+ years of product management", "5+ years of product management experience",
         kind="experience"),
    _req("sql", "SQL", "Hands-on SQL"),
    _req("prov:aaaaaaaaaaaa", "Fluent English", "fluent english", kind="language"),
]


def _posting(requirements=REQS):
    return {"id": "job-1", "title": "Product Manager", "company": "Example", "location": "",
            "description": DESCRIPTION, "facts": {"requirements": requirements}}


def _candidate(facts=()):
    return {"profileVersion": "pv1", "evidenceVersion": "pv1", "answersVersion": "av1", "roleFamily": "product", "evidence": EVIDENCE,
            "confirmedFacts": list(facts), "gates": {}}


def _reply(*matches, gates=None):
    return {
        "matches": [dict(zip(("ref", "status", "evidence_id", "evidence_quote", "strength"), m)) for m in matches],
        "gates": gates or {g: {"quote": None} for g in GATES},
    }


class Fake:
    """A complete_json stand-in that returns (or raises) the given replies in turn."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.prompts.append(prompt)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _run(fake, posting=None, candidate=None, cache=None):
    return match_posting(posting or _posting(), candidate or _candidate(), confirmed=True,
                         provider="test", complete=fake, cache=cache)


# --- normalization --------------------------------------------------------------

@pytest.mark.parametrize(
    "a,b",
    [
        ("Niš", "nis"),
        ("Đorđe ŽIVKOVIĆ", "djordje zivkovic".replace("dj", "d")),  # text_utils folds đ to d
        ("  roadmap\n\townership  ", "roadmap ownership"),
        ("ＳＱＬ", "sql"),  # NFKC: full-width letters
        ("ﬁnance", "finance"),  # NFKC: the fi ligature
        ("STRASSE", "strasse"),
    ],
)
def test_normalize(a, b):
    assert normalize(a) == normalize(b)


def test_quote_in():
    assert quote_in("ROADMAP   ownership", EVIDENCE[0]["text"])
    assert not quote_in("roadmap ownership for a B2C", EVIDENCE[0]["text"])
    assert not quote_in("", EVIDENCE[0]["text"])
    assert not quote_in(None, EVIDENCE[0]["text"])


# --- postingQuote ---------------------------------------------------------------

def test_a_requirement_whose_posting_quote_is_not_in_the_ad_is_dropped():
    reqs = REQS + [_req("kubernetes", "Kubernetes", "Kubernetes in production"), _req("prov:bbbbbbbbbbbb", "X", "")]
    kept, warnings = drop_unquoted(reqs, DESCRIPTION)
    assert [r["id"] for r in kept] == ["product-management", "sql", "prov:aaaaaaaaaaaa"]
    assert len(warnings) == 2 and "kubernetes" in warnings[0] and "prov:bbbbbbbbbbbb" in warnings[1]


def test_a_dropped_requirement_never_reaches_the_model_or_the_output():
    fake = Fake(_reply(("r1", "UNKNOWN", None, None, 0)))
    outcome = _run(fake, posting=_posting([_req("kubernetes", "Kubernetes", "Kubernetes in production"),
                                           REQS[2]]))
    assert "Kubernetes" not in fake.prompts[0].split("=== BEGIN REQUIREMENTS ===")[1].split("=== END")[0]
    assert [r["id"] for r in outcome.output["requirements"]] == ["prov:aaaaaaaaaaaa"]
    assert any("kubernetes" in w for w in outcome.warnings)


# --- downgrade rule -------------------------------------------------------------

BY_ID = {e["id"]: e for e in EVIDENCE}
REQ = REQS[0]
GOOD = "roadmap ownership for a B2B SaaS platform"
BAD = "owned the roadmap for twelve products"


def _apply(status, evidence_id, quote, strength):
    return apply_proposal(REQ, {"status": status, "evidenceId": evidence_id, "evidenceQuote": quote,
                                "strength": strength}, BY_ID)[0]


def _key(r):
    return r["status"], r["evidenceId"], r["evidenceQuote"], r["quoteVerified"], r["strength"]


@pytest.mark.parametrize(
    "proposal,expected",
    [
        # MET + good quote: kept, strength never above the item's own.
        (("MET", "ev-a", GOOD, 4), ("MET", "ev-a", GOOD, True, 4)),
        (("MET", "ev-b", "SQL", 4), ("MET", "ev-b", "SQL", True, 1)),
        # MET + no quote / empty quote / bad quote / quote from another item / unknown item: PARTIAL at claim strength.
        (("MET", "ev-a", None, 4), ("PARTIAL", "ev-a", None, False, 1)),
        (("MET", "ev-a", "   ", 4), ("PARTIAL", "ev-a", None, False, 1)),
        (("MET", "ev-a", BAD, 3), ("PARTIAL", "ev-a", BAD, False, 1)),
        (("MET", "ev-b", GOOD, 3), ("PARTIAL", "ev-b", GOOD, False, 1)),
        (("MET", "ev-zzz", GOOD, 3), ("PARTIAL", None, GOOD, False, 1)),
        (("MET", "ev-a", None, 0), ("PARTIAL", "ev-a", None, False, 0)),  # the cap never raises
        # PARTIAL + good quote: kept.
        (("PARTIAL", "ev-a", GOOD, 2), ("PARTIAL", "ev-a", GOOD, True, 2)),
        # PARTIAL + no quote / bad quote: UNKNOWN, no evidence.
        (("PARTIAL", "ev-a", None, 2), ("UNKNOWN", None, None, False, 0)),
        (("PARTIAL", "ev-a", BAD, 2), ("UNKNOWN", None, None, False, 0)),
        # MISSING needs no quote, whatever comes with it.
        (("MISSING", None, None, 0), ("MISSING", None, None, False, 0)),
        (("MISSING", "ev-a", GOOD, 4), ("MISSING", None, None, False, 0)),
        (("MISSING", "ev-a", BAD, 2), ("MISSING", None, None, False, 0)),
        # UNKNOWN is never raised by a quote.
        (("UNKNOWN", "ev-a", GOOD, 4), ("UNKNOWN", None, None, False, 0)),
    ],
)
def test_downgrade_rule(proposal, expected):
    assert _key(_apply(*proposal)) == expected


def test_a_downgrade_is_reported():
    _, warning = apply_proposal(REQ, {"status": "MET", "evidenceId": "ev-a", "evidenceQuote": BAD, "strength": 3}, BY_ID)
    assert "MET lowered to PARTIAL" in warning


# --- confirmed facts ------------------------------------------------------------

def test_confirmed_facts_override_the_model_and_are_still_asked():
    facts = [{"competencyId": "sql", "has": True, "note": ""},
             {"competencyId": "prov:aaaaaaaaaaaa", "has": False, "note": "B1 only"}]
    # The model claims the opposite for everything; a fact's requirement is still asked, the answer wins in code.
    fake = Fake(_reply(("r1", "MET", "ev-a", GOOD, 4), ("r2", "MISSING", None, None, 0),
                       ("r3", "MET", "ev-a", GOOD, 4)))
    outcome = _run(fake, candidate=_candidate(facts))
    asked = fake.prompts[0].split("=== BEGIN REQUIREMENTS ===")[1].split("=== END")[0]
    assert '"r1"' in asked and "SQL" in asked and "Fluent English" not in asked
    by_id = {r["id"]: r for r in outcome.output["requirements"]}
    assert _key(by_id["sql"]) == ("MET", None, None, True, CONFIRMED_FACT_STRENGTH)
    assert _key(by_id["prov:aaaaaaaaaaaa"]) == ("MISSING", None, None, True, 0)
    assert _key(by_id["product-management"]) == ("MET", "ev-a", GOOD, True, 4)
    # Output keeps the ad's requirement order.
    assert list(by_id) == ["product-management", "sql", "prov:aaaaaaaaaaaa"]


# --- the whole call -------------------------------------------------------------

def test_a_full_match_with_gate_quotes_passed_through():
    gates = {g: {"quote": None} for g in GATES}
    gates["location"] = {"quote": "Fully remote within Serbia."}
    fake = Fake(_reply(("r1", "MET", "ev-a", GOOD, 4), ("r2", "PARTIAL", "ev-b", "SQL", 2),
                       ("r3", "UNKNOWN", None, None, 0), gates=gates))
    cache = {}
    outcome = _run(fake, cache=cache)
    assert outcome.error is None
    assert [r["status"] for r in outcome.output["requirements"]] == ["MET", "PARTIAL", "UNKNOWN"]
    assert outcome.output["requirements"][1]["strength"] == 1  # the item is a claim
    assert {"gate": "location", "quote": "Fully remote within Serbia."} in outcome.output["gates"]
    assert [g["gate"] for g in outcome.output["gates"]] == list(GATES)
    assert list(cache) == [outcome.output["cacheKey"]]
    # A second run is a cache hit: no call.
    assert _run(Fake(), cache=cache).output == outcome.output


def test_an_omitted_or_malformed_answer_drops_only_that_requirement():
    # The third requirement as kind "other", so the matcher is asked about it (a language one is settled in code).
    asked = REQS[:2] + [{**REQS[2], "kind": "other"}]
    fake = Fake(_reply(("r1", "MET", "ev-a", GOOD, 4), ("r2", "PROBABLY", None, None, 1)))
    outcome = _run(fake, posting=_posting(asked))
    assert [r["id"] for r in outcome.output["requirements"]] == ["product-management"]
    assert sum("no usable answer" in w for w in outcome.warnings) == 2


@pytest.mark.parametrize(
    "replies",
    [
        [LlmUnavailable("timed out after 90s")],  # provider error or timeout: not retried here
        [LlmRefused("no JSON object in reply"), LlmRefused("no JSON object in reply")],  # malformed twice
        [{"matches": "nope"}, {"gates": {}}],  # schema violation twice
        [{"matches": []}, LlmRefused("no JSON object in reply")],
    ],
)
def test_a_failed_call_returns_no_output_and_caches_nothing(replies):
    cache = {}
    fake = Fake(*replies)
    outcome = _run(fake, cache=cache)
    assert outcome.output is None
    assert outcome.error.startswith("no engine output for this posting")
    assert cache == {}
    assert fake.replies == []  # exactly the calls expected: one, or one plus one retry


def test_one_retry_recovers_a_malformed_reply():
    fake = Fake(LlmRefused("no JSON object in reply"), _reply(("r1", "UNKNOWN", None, None, 0),
                                                               ("r2", "UNKNOWN", None, None, 0),
                                                               ("r3", "UNKNOWN", None, None, 0)))
    assert _run(fake).output is not None


def test_the_matcher_refuses_to_run_unconfirmed():
    fake = Fake()
    with pytest.raises(NotConfirmed):
        match_posting(_posting(), _candidate(), confirmed=False, provider="test", complete=fake)
    with pytest.raises(NotConfirmed):
        match_posting(_posting(), _candidate(), confirmed="yes", provider="test", complete=fake)
    assert fake.prompts == []


def test_the_prompt_carries_no_identifier_and_no_gate_data():
    evidence = EVIDENCE + [{"id": "ev-c", "text": "Contact ana@example.com, +381 64 123 4567, github.com/ana",
                            "source": "example", "role": None, "start": None, "end": None, "strength": 2}]
    candidate = {**_candidate(), "evidence": evidence,
                 "gates": {"minSalaryEur": 4321, "allowedLocations": ["Zanzibar"], "languages": ["Klingon"]},
                 "confirmedFacts": [{"competencyId": "nothing-asked", "has": True, "note": "secret note"}]}
    fake = Fake(_reply())
    _run(fake, candidate=candidate)
    prompt = fake.prompts[0]
    for leak in ("ana@example.com", "123 4567", "github.com/ana", "4321", "Zanzibar", "Klingon", "secret note", "pv1"):
        assert leak not in prompt


def test_the_cache_key_is_ad_profile_and_prompt():
    assert cache_key("ad", "pv").startswith("ad:pv:extract-")


# --- language requirements settled in code ------------------------------------------

def _language_candidate(languages, evidence=EVIDENCE):
    return {**_candidate(), "gates": {"languages": languages}, "evidence": evidence}


def test_a_spoken_language_is_met_without_asking_the_model():
    fake = Fake(_reply(("r1", "MET", "ev-a", GOOD, 4), ("r2", "PARTIAL", "ev-b", "SQL", 1)))
    outcome = _run(fake, candidate=_language_candidate(["Serbian (native)", "English (fluent)"]))
    english = next(r for r in outcome.output["requirements"] if r["kind"] == "language")
    assert (english["status"], english["quoteVerified"], english["evidenceQuote"]) == ("MET", True, "English (fluent)")
    assert english["evidenceId"] == "gates.languages" and english["strength"] == CONFIRMED_FACT_STRENGTH
    # Not asked: the prompt carries r1 and r2 only, and none of the candidate's languages.
    assert '"r3"' not in fake.prompts[0] and "Fluent English" not in fake.prompts[0].split("END JOB AD")[1]
    assert "Serbian (native)" not in fake.prompts[0]


def _language(outcome):
    return next(r for r in outcome.output["requirements"] if r["kind"] == "language")


def _lang_posting(text, importance="must"):
    posting = _posting(REQS[:2] + [_req("prov:aaaaaaaaaaaa", text, text.lower(), importance=importance, kind="language")])
    return {**posting, "description": DESCRIPTION + f"\n  * {text}"}


def _lang_run(text, languages, importance="must", evidence=EVIDENCE):
    fake = Fake(_reply(("r1", "MET", "ev-a", GOOD, 4), ("r2", "MISSING", None, None, 0),
                       ("r3", "PARTIAL", "ev-c", "Ran workshops in English", 3)))
    return fake, _run(fake, posting=_lang_posting(text, importance), candidate=_language_candidate(languages, evidence))


def test_a_required_language_the_list_does_not_cover_is_missing():
    fake, outcome = _lang_run("Fluent Russian", ["Serbian (native)", "English (fluent)"])
    assert (_language(outcome)["status"], _language(outcome)["evidenceId"]) == ("MISSING", None)
    assert '"r3"' not in fake.prompts[0]


@pytest.mark.parametrize("text", ["Croatian", "Bosnian", "Serbo-Croatian", "Macedonian"])
def test_a_relative_of_a_spoken_language_is_met(text):
    _, outcome = _lang_run(f"Fluent {text}", ["Serbian (native)"])
    assert (_language(outcome)["status"], _language(outcome)["quoteVerified"]) == ("MET", True)
    assert _language(outcome)["evidenceQuote"] == "Serbian (native)"


def test_alternatives_are_met_when_one_is_covered():
    assert _lang_run("German or English", ["English (fluent)"])[1].output["requirements"][2]["status"] == "MET"
    assert _lang_run("German or French", ["English (fluent)"])[1].output["requirements"][2]["status"] == "MISSING"


def test_an_optional_language_not_covered_is_missing_like_any_optional_requirement():
    _, outcome = _lang_run("German is a plus", ["English (fluent)"], importance="nice")
    assert _language(outcome)["status"] == "MISSING" and _language(outcome)["importance"] == "nice"


EVIDENCE_EN = EVIDENCE + [{"id": "ev-c", "text": "Ran workshops in English for UK clients.", "source": "role",
                           "role": "PM — Acme", "start": None, "end": None, "strength": 3}]


def test_an_optional_language_the_evidence_mentions_goes_to_the_model():
    fake, outcome = _lang_run("English is a plus", ["German (C1)"], importance="nice", evidence=EVIDENCE_EN)
    assert '"r3"' in fake.prompts[0] and _language(outcome)["status"] == "PARTIAL"


def test_a_must_have_language_the_evidence_mentions_is_a_reported_conflict_not_a_choice():
    fake, outcome = _lang_run("Fluent English", ["German (C1)"], evidence=EVIDENCE_EN)
    assert '"r3"' not in fake.prompts[0] and _language(outcome)["status"] == "MISSING"
    assert "conflict" not in _language(outcome)
    assert any("must-have" in w and "English" in w for w in outcome.warnings)


def test_no_listed_languages_leaves_a_language_requirement_unknown():
    outcome = _run(Fake(_reply(("r1", "MET", "ev-a", GOOD, 4), ("r2", "MISSING", None, None, 0))),
                   candidate=_language_candidate([]))
    assert next(r for r in outcome.output["requirements"] if r["kind"] == "language")["status"] == "UNKNOWN"


def test_a_language_requirement_naming_no_known_language_goes_to_the_model():
    reqs = REQS[:2] + [_req("prov:bbbbbbbbbbbb", "The local language", "Fully remote within Serbia", kind="language")]
    fake = Fake(_reply(("r1", "MET", "ev-a", GOOD, 4), ("r2", "MISSING", None, None, 0), ("r3", "UNKNOWN", None, None, 0)))
    _run(fake, posting=_posting(reqs), candidate=_language_candidate(["English (fluent)"]))
    assert '"r3"' in fake.prompts[0]


def test_a_confirmed_fact_outranks_the_language_list():
    fact = {"competencyId": "prov:aaaaaaaaaaaa", "has": False, "note": ""}
    candidate = {**_language_candidate(["English (fluent)"]), "confirmedFacts": [fact]}
    outcome = _run(Fake(_reply(("r1", "MET", "ev-a", GOOD, 4), ("r2", "MISSING", None, None, 0))), candidate=candidate)
    assert next(r for r in outcome.output["requirements"] if r["kind"] == "language")["status"] == "MISSING"


def test_the_prompt_draws_the_missing_unknown_line_from_the_contract():
    from match_engine.matcher import PROMPT
    assert "Silence is UNKNOWN, never MISSING" not in PROMPT
    assert "covers the requirement's topic and does not" in PROMPT
    assert "no cloud platform appears" in PROMPT and "MISSING." in PROMPT
