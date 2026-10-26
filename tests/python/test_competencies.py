"""The product competency seed and the validator that guards every list."""

import copy
import re

from match_engine import competencies
from match_engine.competencies import alias_index, alias_key, load, validate

DICTIONARY = ["Product Management", "SQL", "Node.js"]


def comp(cid, aliases=None, **fields):
    return {"id": cid, "definition": f"{cid} counts; its neighbour does not.", "kind": "skill",
            "aliases": aliases if aliases is not None else [cid.replace("-", " ")], **fields}


def problems(*comps, dictionary=DICTIONARY):
    return validate(list(comps), dictionary)


def test_alias_key_is_the_one_comparison_form():
    assert alias_key("  Bachelor’s   Degree. ") == "bachelor's degree"
    assert alias_key("Niš") == "nis"
    assert alias_key("A/B Tests;") == "a/b tests"
    assert alias_key(None) == ""
    # Only that: no modifier is stripped.
    assert alias_key("Strong Communication Skills") == "strong communication skills"


def test_the_product_seed_is_valid():
    seed = load("product")
    assert 60 <= len(seed) <= 120
    assert validate(seed) == []


def test_the_seed_stays_generic():
    text = (competencies.COMPETENCIES_DIR / "product.json").read_text(encoding="utf-8")
    assert not re.search(r"\b\d", text), "no counts or years in the seed"
    for definition in (c["definition"] for c in load("product")):
        assert "\n" not in definition and "not" in definition, "a definition says what counts and what does not"


def test_an_unknown_family_has_no_list():
    assert load("astronaut") == []


def test_alias_index_maps_each_alias_to_its_competency():
    index = alias_index([comp("a-one", ["alpha", "beta"]), comp("b-two", ["gamma"])])
    assert index == {"alpha": "a-one", "beta": "a-one", "gamma": "b-two"}


def test_a_sound_list_has_no_problems():
    assert problems(comp("a-one"), comp("b-two", parent="a-one")) == []


def test_duplicate_and_malformed_ids():
    assert any("duplicate id" in p for p in problems(comp("a-one"), comp("a-one", ["other"])))
    for bad in ["A-One", "a_one", "a--one", "-a", "", None, 3]:
        assert any("kebab-case" in p for p in problems(comp(bad, ["x"]))), bad


def test_definition_and_kind_and_aliases_are_required():
    assert any("definition" in p for p in problems({**comp("a-one"), "definition": "  "}))
    assert any("definition" in p for p in problems({**comp("a-one"), "definition": "two\nlines"}))
    assert any("kind" in p for p in problems({**comp("a-one"), "kind": "hobby"}))
    assert any("at least one alias" in p for p in problems(comp("a-one", [])))


def test_parent_must_exist_and_not_loop():
    assert any("does not exist" in p for p in problems(comp("a-one", parent="ghost")))
    assert any("loops" in p for p in problems(comp("a-one", parent="a-one")))
    loop = problems(comp("a-one", ["x"], parent="b-two"), comp("b-two", ["y"], parent="a-one"))
    assert any("loops" in p for p in loop)


def test_an_alias_belongs_to_exactly_one_competency_after_normalization():
    clash = problems(comp("a-one", ["strong team"]), comp("b-two", ["strong team"]))
    assert any("belongs to both" in p for p in clash)
    assert any("listed twice" in p for p in problems(comp("a-one", ["x", "x"])))


def test_an_alias_must_already_be_normalized():
    for raw in ["Strong Team", "bachelor’s degree", " x", "x."]:
        assert any("not normalized" in p for p in problems(comp("a-one", [raw]))), raw


def test_no_collision_with_the_skills_dictionary():
    assert any("dictionary's id" in p for p in problems(comp("sql", ["structured queries"])))
    assert any("dictionary's id" in p for p in problems(comp("node-js", ["server runtime"])))
    assert any("dictionary term" in p for p in problems(comp("a-one", ["sql"])))
    # An alias that merely contains a term would duplicate the dictionary's job.
    assert any("contains" in p for p in problems(comp("a-one", ["technical product management"])))
    assert problems(comp("a-one", ["technical product manager"])) == []


def test_the_real_dictionary_is_what_validate_uses_by_default():
    bad = [comp("a-one", ["python scripting"])]
    assert any("contains" in p for p in validate(bad))


def test_validate_does_not_mutate_its_input():
    comps = [comp("a-one"), comp("b-two", parent="a-one")]
    before = copy.deepcopy(comps)
    validate(comps, DICTIONARY)
    assert comps == before
