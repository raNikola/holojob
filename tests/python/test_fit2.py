"""W3: Professional Fit 2.0 (shadow). Units by code, merge rule, V0/V1, confidence, ranking guard. No model, no network."""

from fractions import Fraction

import pytest

from match_engine import fit2 as f2
from match_engine.fit import fit_value
from match_engine.shadow import ShadowEngine

COMPS = [
    {"id": "roadmapping", "definition": "d", "kind": "skill", "aliases": ["product roadmapping", "roadmapping"]},
    {"id": "stakeholder-management", "definition": "d", "kind": "skill", "aliases": ["stakeholder management"]},
    {"id": "communication", "definition": "d", "kind": "skill", "aliases": ["communication"]},
    {"id": "agile-delivery", "definition": "d", "kind": "skill", "aliases": ["agile delivery"]},
]
_n = iter(range(1, 10_000))


def line(text, status="MET", importance="must", kind="skill", strength=None, verified=None, **extra):
    strength = {"MET": 4, "PARTIAL": 2}.get(status, 0) if strength is None else strength
    return {"id": f"x{next(_n)}", "provisional": True, "text": text, "kind": kind, "importance": importance, "status": status,
            "strength": strength, "quoteVerified": status in ("MET", "PARTIAL") if verified is None else verified, **extra}


def resolver(learned=None):
    return f2.UnitResolver(COMPS, learned)


# ---- the resolver: code only ----

def test_resolves_seed_alias_dictionary_term_and_stripped_boilerplate():
    r = resolver()
    assert r.resolve("Product Roadmapping.", "skill") == ("roadmapping", "alias")
    assert r.resolve("Experience with stakeholder management", "experience") == ("stakeholder-management", "alias-stripped")
    assert r.resolve("Strong communication skills", "skill") == ("communication", "alias-stripped")
    cid, route = r.resolve("Hands-on SQL", "skill")
    assert (cid, route) == ("sql", "dictionary")
    assert r.resolve("something nobody maps", "skill") == (None, None)
    assert r.resolve(None) == (None, None) and r.resolve("  ") == (None, None)


def test_the_stored_id_and_the_models_pick_are_never_read():
    r = resolver()
    req = line("something nobody maps", competencyId="roadmapping", id="roadmapping", provisional=False)
    block = f2.fit2([req], r)
    assert block["units"] == [] and block["counts"]["unmapped"] == 1


def test_only_reviewed_learned_aliases_count():
    learned = {"owner reviewed wording": {"competencyId": "roadmapping", "status": "reviewed"},
               "model picked wording": {"competencyId": "roadmapping", "status": "pending"},
               "auto grouped wording": {"competencyId": "roadmapping", "status": "auto"},
               "rejected wording": {"competencyId": "roadmapping", "status": "reviewed", "demotedIds": ["roadmapping"]},
               "unknown id wording": {"competencyId": "nope", "status": "reviewed"}}
    r = resolver(learned)
    assert r.resolve("owner reviewed wording")[0] == "roadmapping"
    for text in ("model picked wording", "auto grouped wording", "rejected wording", "unknown id wording"):
        assert r.resolve(text) == (None, None)


# ---- merge rule ----

def only_unit(requirements, **kw):
    units, _ = f2.build_units(requirements, resolver(), **kw)
    assert len(units) == 1
    return units[0]


def test_lines_resolving_to_one_id_merge_with_max_importance():
    u = only_unit([line("roadmapping", "PARTIAL", "nice"), line("product roadmapping", "MET", "must")])
    assert u["lines"] == 2 and u["importance"] == "must" and u["status"] == "MET"


def test_merge_status_order():
    assert only_unit([line("roadmapping", "MET"), line("product roadmapping", "CONTRADICTED")])["status"] == "CONTRADICTED"
    assert only_unit([line("roadmapping", "PARTIAL", strength=3), line("product roadmapping", "MET", strength=1)])["strength"] == 3
    assert only_unit([line("roadmapping", "UNKNOWN"), line("product roadmapping", "NOT_EVIDENCED")])["status"] == "NOT_EVIDENCED"
    assert only_unit([line("roadmapping", "UNKNOWN")])["status"] == "UNKNOWN"
    assert only_unit([line("roadmapping", "MISSING")])["status"] == "NOT_EVIDENCED"


def test_responsibilities_merge_into_an_asked_id_or_add_an_unknown_nice_unit():
    units, _ = f2.build_units([line("roadmapping")], resolver(),
                              [{"text": "product roadmapping"}, {"text": "agile delivery"}, {"text": "unmappable duty"}])
    by = {u["id"]: u for u in units}
    assert by["roadmapping"]["sources"] == ["requirement", "responsibility"]
    assert (by["agile-delivery"]["status"], by["agile-delivery"]["importance"], by["agile-delivery"]["sources"]) == ("UNKNOWN", "nice", ["responsibility"])
    assert len(units) == 2


# ---- the numbers ----

def test_v0_equals_the_1x_formula_on_the_same_units_and_generic_weighs_nothing():
    reqs = [line("roadmapping", "MET"), line("stakeholder management", "PARTIAL"), line("communication", "CONTRADICTED"),
            line("agile delivery", "NOT_EVIDENCED")]
    block = f2.fit2(reqs, resolver())
    ones = [{**line("roadmapping", "MET"), "id": "a", "provisional": False}, {**line("x", "PARTIAL"), "id": "b", "provisional": False}]
    assert block["v0"]["fit"] == fit_value(ones)
    assert block["counts"]["generic"] == 1


def test_v1_charges_half_a_must_weight_per_not_evidenced_specific_must_and_only_the_number_moves():
    base = [line("roadmapping", "MET")]
    ne = base + [line("agile delivery", "NOT_EVIDENCED")]
    a, b = f2.fit2(base, resolver()), f2.fit2(ne, resolver())
    assert f2.NOT_EVIDENCED_WEIGHT == Fraction(1, 2)
    assert a["v0"]["fit"] == b["v0"]["fit"] == 100
    assert a["v1"]["fit"] == 100
    # 100*3 / (3 + 1.5)
    assert b["v1"]["fit"] == 67
    # a NOT_EVIDENCED preferred is not charged
    pref = base + [line("agile delivery", "NOT_EVIDENCED", "preferred")]
    assert f2.fit2(pref, resolver())["v1"]["fit"] == 100
    assert a["confidence"] == 1.0 and b["confidence"] < 1.0
    assert f2.fit2(ne, resolver())["confidence"] == b["confidence"]


def test_nothing_settled_has_no_number_and_is_insufficient():
    block = f2.fit2([line("roadmapping", "NOT_EVIDENCED"), line("junk", "MET")], resolver())
    assert block["v0"]["fit"] is None and block["v1"]["fit"] is None
    assert block["insufficientEvidence"] and "nothing settled" in block["insufficientReasons"]


def test_unverified_quote_lowers_confidence_and_flags_insufficient():
    block = f2.fit2([line("roadmapping", "MET", verified=False), line("stakeholder management", "MET", verified=False)], resolver())
    assert block["confidence"] == 0.0 and block["insufficientEvidence"]


def test_unmapped_lines_are_display_only_and_counted():
    block = f2.fit2([line("roadmapping"), line("unmapped must"), line("unmapped nice", importance="nice")], resolver())
    assert block["counts"]["unmapped"] == 2 and block["counts"]["unmappedMusts"] == 1
    assert block["counts"]["unmappedMustShare"] == 0.5
    assert block["unmapped"][0] == {"index": 1, "kind": "skill", "importance": "must", "status": "MET"}
    assert "text" not in block["unmapped"][0]


# ---- variance script keys ----

def test_deterministic_keys_share_one_id_across_wordings_and_hold_no_text():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import measure_extraction_variance as mv

    a = mv.det_unit_keys({"requirements": [line("roadmapping", importance="nice"), line("Experience with product roadmapping"), line("odd one")]}, resolver())
    assert a["units"] == [{"key": "d:roadmapping", "importance": "must", "kind": "skill"}]
    assert a["unmapped"] == {"must": 1, "other": 0}


# ---- never mixed ----

def test_rank_orders_by_the_variant_and_refuses_a_mixed_list():
    rows = [{"id": "b", "fit2": f2.fit2([line("roadmapping")], resolver())},
            {"id": "a", "fit2": f2.fit2([line("roadmapping", "PARTIAL")], resolver())},
            {"id": "c", "fit2": f2.fit2([line("junk")], resolver())}]
    assert [r["id"] for r in f2.rank(rows)] == ["b", "a", "c"]
    with pytest.raises(f2.MixedScoringVersions):
        f2.rank(rows + [{"id": "old", "fit": 70}])
    with pytest.raises(f2.MixedScoringVersions):
        f2.rank([{"id": "v", "fit2": {"scoringVersion": "1.5", "v0": {"fit": 1}}}])


# ---- shadow wiring ----

def test_shadow_adds_fit2_and_leaves_the_1x_output_as_it_was(tmp_path):
    import test_engine_shadow as t

    eng = ShadowEngine(t.CANDIDATE, judge=True, provider="test", model="m", cache_path=tmp_path / "engine.json", complete=t.Fake(),
                       workers=1, unit_resolver=resolver())
    out = eng.apply([t.job("j1", 70)])[0]["engineShadow"]
    block = out.pop("fit2")
    assert block["scoringVersion"] == "2.0"
    assert {"fit", "confidence", "label", "caps", "counts"} <= set(out)
