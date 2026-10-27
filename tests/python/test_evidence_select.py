"""Per-ad evidence selection (fictional candidate): what stays, what goes, and that quotes still verify."""

import copy

import pytest

from match_engine import shadow
from match_engine.evidence_select import FOCUSED_VERSION, SELECTION_VERSION, keywords, select_evidence
from match_engine.matcher import GATES, cache_key, match_posting


def item(n, source, text, role=None):
    return {"id": f"ev-{n}", "source": source, "role": role, "start": "2020-01" if role else None, "end": None,
            "text": text, "strength": 3 if source == "role" else 1}


EVIDENCE = [
    item(1, "role", "Led the migration of the billing platform to Postgres and SQL views", "PM — Acme"),
    item(2, "role", "Ran sprint planning with the Kotlin mobile squad", "PM — Acme"),
    item(3, "role", "Negotiated vendor contracts for the warehouse", "Ops lead — Brick"),
    item(4, "role", "Organized the annual customer conference", "Ops lead — Brick"),
    item(5, "example", "Coached two juniors through their first launch"),
    item(6, "fact", "Figma"),
    item(7, "fact", "Jira"),
]


def req(text, rid="prov:aaaaaaaaaaaa", quote=None, kind="skill"):
    return {"id": rid, "provisional": rid.startswith("prov:"), "text": text, "kind": kind, "importance": "must",
            "postingQuote": quote or text}


def ids(items):
    return [i["id"] for i in items]


def test_an_item_that_overlaps_a_requirement_is_kept():
    sent, dropped = select_evidence(EVIDENCE, [req("Hands-on SQL analytics")])
    assert "ev-1" in ids(sent) and "ev-1" not in dropped


def test_keywords_match_across_word_forms_and_accents():
    assert keywords("Managing vendors") & keywords("vendor management")
    assert keywords("Niš roadmap") & keywords("roadmaps in Nis")


def test_the_core_stays_one_item_per_role_and_the_facts():
    sent, dropped = select_evidence(EVIDENCE, [req("Kubernetes certification")])
    assert ids(sent) == ["ev-1", "ev-3", "ev-6", "ev-7"]  # first item of each role + facts
    assert dropped == ["ev-2", "ev-4", "ev-5"]


def test_facts_can_be_left_to_overlap_only():
    sent, dropped = select_evidence(EVIDENCE, [req("Figma prototyping")], keep_facts=False)
    assert "ev-6" in ids(sent) and "ev-7" in dropped


def test_nothing_is_rewritten():
    before = copy.deepcopy(EVIDENCE)
    sent, _ = select_evidence(EVIDENCE, [req("SQL")])
    assert EVIDENCE == before and all(s in EVIDENCE for s in sent)
    assert [s["text"] for s in sent] == [e["text"] for e in EVIDENCE if e in sent]


def test_a_competency_id_counts_as_a_keyword():
    sent, dropped = select_evidence(EVIDENCE, [req("Experience", rid="vendor-management", quote="Experience")])
    assert "ev-3" in ids(sent)


def test_focused_mode_ignores_a_word_every_item_has_unless_nothing_else_is_left():
    common = [item(n, "role", f"Owned the product {w}", f"PM — Co{n}") for n, w in enumerate(["billing", "search", "onboarding", "pricing"], 1)]
    strict, _ = select_evidence(common, [req("Own the product search")])
    focused, dropped = select_evidence(common, [req("Own the product search")], focused=True)
    assert len(strict) == 4  # "product" overlaps everywhere
    # "product" is in every item, so only the item that also has "search" overlaps; the rest are role-core items
    assert ids(focused) == ids(common)  # each is the first item of its own role, so the core keeps them
    only_product, dropped = select_evidence(common + [item(9, "example", "Owned the product catalogue")],
                                            [req("Own the product search")], focused=True)
    assert "ev-9" in dropped
    generic, dropped = select_evidence(common + [item(9, "example", "Owned the product catalogue")],
                                       [req("product")], focused=True)
    assert "ev-9" not in dropped  # a requirement with no other keyword falls back to all its words


# --- through the matcher ---------------------------------------------------------------

def posting(reqs, description="We want SQL and vendor negotiation."):
    return {"id": "job-1", "title": "PM", "company": "X", "location": "", "description": description,
            "facts": {"requirements": reqs}}


def candidate(profile_version="pv1"):
    return {"profileVersion": profile_version, "roleFamily": "product", "evidence": EVIDENCE, "confirmedFacts": [],
            "gates": {}}


class Fake:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.prompts.append(prompt)
        return self.reply


def reply(*matches):
    return {"matches": [dict(zip(("ref", "status", "evidence_id", "evidence_quote", "strength"), m)) for m in matches],
            "gates": {g: {"quote": None} for g in GATES}}


def test_selection_sends_fewer_items_and_a_citation_of_an_unsent_item_still_verifies():
    reqs = [req("SQL analytics", rid="prov:bbbbbbbbbbbb", quote="SQL")]
    reqs[0]["importance"] = "must"
    full, sel = Fake(reply(("r1", "MET", "ev-1", "SQL views", 3))), Fake(reply(("r1", "MET", "ev-5", "first launch", 3)))
    a = match_posting(posting(reqs), candidate(), confirmed=True, provider="t", complete=full)
    b = match_posting(posting(reqs), candidate(), confirmed=True, provider="t", complete=sel, select=True)
    assert "ev-5" in full.prompts[0] and "ev-5" not in sel.prompts[0] and "ev-1" in sel.prompts[0]
    assert a.output["requirements"][0]["quoteVerified"] is True
    # The id of an item that was not sent still resolves in the verifier (the full index is kept).
    assert b.output["requirements"][0]["quoteVerified"] is True and b.output["requirements"][0]["evidenceId"] == "ev-5"


def test_quotes_stay_verbatim_in_the_prompt():
    fake = Fake(reply(("r1", "MET", "ev-1", "SQL views", 3)))
    match_posting(posting([req("SQL", rid="prov:cccccccccccc")]), candidate(), confirmed=True, provider="t",
                  complete=fake, select=True)
    assert "Led the migration of the billing platform to Postgres and SQL views" in fake.prompts[0]


def test_off_is_the_default_and_changes_nothing():
    fake = Fake(reply(("r1", "UNKNOWN", None, None, 0)))
    match_posting(posting([req("Kubernetes", rid="prov:dddddddddddd")]), candidate(), confirmed=True, provider="t",
                  complete=fake)
    assert all(i["id"] in fake.prompts[0] for i in EVIDENCE)


def test_cache_key_is_unchanged_off_and_versioned_on():
    assert cache_key("ad", "pv") == cache_key("ad", "pv", None) == cache_key("ad", "pv", False)
    assert not cache_key("ad", "pv").endswith(SELECTION_VERSION)
    strict, focused = cache_key("ad", "pv", True), cache_key("ad", "pv", "focused")
    assert strict.endswith(f":{SELECTION_VERSION}") and focused.endswith(f":{FOCUSED_VERSION}")
    assert len({cache_key("ad", "pv"), strict, focused}) == 3
    # The full evidence version stays in the key: a CV change invalidates every entry.
    assert cache_key("ad", "pv1", True) != cache_key("ad", "pv2", True)


@pytest.mark.parametrize("value,mode", [(None, None), ("", None), ("0", None), ("1", "strict"), ("on", "strict"),
                                        ("focused", "focused")])
def test_the_flag_is_off_unless_set(value, mode):
    assert shadow.select_mode({shadow.SELECT_ENV: value} if value is not None else {}) == mode
