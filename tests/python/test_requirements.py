"""Requirements in the enrichment facts, and the ids code gives them."""

import hashlib

import pytest

from enrich_jobs import FACT_SCHEMA, IMPORTANCES, REQUIREMENT_KINDS, _coerce
from requirement_ids import (
    DICTIONARY,
    assign_id,
    canonical_id,
    dictionary_terms_in,
    normalize_requirement,
    provisional_id,
)

ITEM_SCHEMA = FACT_SCHEMA["schema"]["properties"]["requirements"]["items"]


def _req(text, kind="skill", importance="must", quote=None):
    return {"text": text, "kind": kind, "importance": importance, "posting_quote": quote or text}


# --- schema ---------------------------------------------------------------

def test_the_enums_are_the_contracts():
    assert REQUIREMENT_KINDS == {"skill", "experience", "domain", "education", "certification", "language", "other"}
    assert IMPORTANCES == {"must", "preferred", "nice"}


def test_the_schema_offers_exactly_those_enums():
    assert set(ITEM_SCHEMA["properties"]["kind"]["enum"]) == REQUIREMENT_KINDS
    assert set(ITEM_SCHEMA["properties"]["importance"]["enum"]) == IMPORTANCES


def test_strict_schema_requires_every_item_field():
    assert ITEM_SCHEMA["additionalProperties"] is False
    assert set(ITEM_SCHEMA["required"]) == set(ITEM_SCHEMA["properties"]) == {
        "text", "kind", "importance", "posting_quote", "previous_id", "qualifier",
    }
    assert "requirements" in FACT_SCHEMA["schema"]["required"]
    assert "must_haves" not in FACT_SCHEMA["schema"]["properties"]


def test_coerce_keeps_every_requirement_with_no_count_limit():
    raw = {"requirements": [_req(f"Skill {i}", importance="must" if i % 2 else "nice") for i in range(30)]}
    facts = _coerce(raw)
    assert len(facts["requirements"]) == 30
    assert len(facts["mustHaves"]) == 15
    assert len(facts["niceToHaves"]) == 15


def test_coerce_maps_an_unknown_kind_to_other_and_drops_an_unknown_importance():
    facts = _coerce({"requirements": [
        _req("Python", kind="tooling"),
        _req("Kotlin", importance="critical"),
        _req("", quote="something"),
        {"text": "No quote", "kind": "skill", "importance": "must", "posting_quote": ""},
        "not an object",
    ]})
    assert facts["requirements"] == [
        {"text": "Python", "kind": "other", "importance": "must", "postingQuote": "Python", "previousId": None, "qualifier": None},
    ]


def test_coerce_with_no_requirements_is_empty():
    facts = _coerce({})
    assert facts["requirements"] == [] and facts["mustHaves"] == [] and facts["niceToHaves"] == []


def test_preferred_and_nice_both_go_to_nice_to_haves():
    facts = _coerce({"requirements": [_req("A", importance="preferred"), _req("B", importance="nice"), _req("C")]})
    assert facts["mustHaves"] == ["C"]
    assert facts["niceToHaves"] == ["A", "B"]


# --- ids ------------------------------------------------------------------

def test_the_dictionary_is_read_from_the_shared_js_file():
    assert "PostgreSQL" in DICTIONARY and "C++" in DICTIONARY and "Node.js" in DICTIONARY
    assert len(DICTIONARY) == len(set(DICTIONARY))


def test_canonical_ids_are_unique_across_the_dictionary():
    ids = [canonical_id(t) for t in DICTIONARY]
    assert len(ids) == len(set(ids))
    assert canonical_id("C++") == "c-plus-plus"
    assert canonical_id("C#") == "c-sharp"
    assert canonical_id("Node.js") == "node-js"
    assert canonical_id("CI/CD") == "ci-cd"


def test_the_same_requirement_gets_the_same_id_twice():
    req = {"text": "Experience shipping LLM-powered features", "kind": "experience"}
    assert assign_id(req) == assign_id(dict(req))
    assert assign_id(req)["id"] == assign_id(req)["id"]


def test_provisional_id_is_the_contract_hash():
    text = "  Experience   shipping LLM-powered\tFeatures "
    normalized = "experience shipping llm-powered features"
    assert normalize_requirement(text) == normalized
    expected = "prov:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    assert provisional_id(text) == expected
    # Case and spacing do not change it; the words do.
    assert provisional_id("experience shipping LLM-powered features") == expected
    assert provisional_id("experience shipping LLM features") != expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("PostgreSQL", "postgresql"),
        ("Strong SQL skills", "sql"),
        ("Experience designing REST APIs", "rest-api"),
        ("React Native", "react-native"),
        ("Node.js.", "node-js"),
        ("Hands-on Kubernetes", "kubernetes"),
    ],
)
def test_a_known_dictionary_term_maps_to_its_canonical_id(text, expected):
    result = assign_id({"text": text, "kind": "skill"})
    assert result == {"text": text, "kind": "skill", "id": expected, "provisional": False}


def test_experience_with_a_skill_maps_to_that_skill():
    assert assign_id({"text": "5+ years of product management", "kind": "experience"})["id"] == "product-management"


@pytest.mark.parametrize(
    "text,kind",
    [
        ("Stakeholder management", "skill"),  # not in the dictionary
        ("React and Node.js", "skill"),  # two terms: which one?
        ("Willing to go the extra mile", "other"),
        ("Ability to go deep on technical topics", "skill"),  # "go", not Go
        ("AWS Certified Solutions Architect", "certification"),  # not AWS itself
        ("Fluent English", "language"),
    ],
)
def test_anything_else_gets_a_stable_provisional_id(text, kind):
    result = assign_id({"text": text, "kind": kind})
    assert result["provisional"] is True
    assert result["id"] == provisional_id(text)
    assert result["id"].startswith("prov:") and len(result["id"]) == len("prov:") + 12


def test_word_boundaries_hold():
    assert dictionary_terms_in("JavaScript") == ["JavaScript"]
    assert dictionary_terms_in("MySQL") == ["MySQL"]
    assert dictionary_terms_in("Go and Rust") == ["Go", "Rust"]
    assert dictionary_terms_in("go and rust") == []


def test_assign_id_does_not_change_its_input():
    req = {"text": "Python", "kind": "skill"}
    assign_id(req)
    assert req == {"text": "Python", "kind": "skill"}
