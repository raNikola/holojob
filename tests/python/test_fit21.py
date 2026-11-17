"""W4: Professional Fit 2.1 (shadow) and the role mix. Units by code, V0/V1/V2, role mix cues, ranking guard. No model, no network, no real data/."""

import pytest

from match_engine import fit2 as f2
from match_engine import fit21 as f21
from match_engine import role_mix as rm

COMPS = [{"id": "roadmapping", "definition": "d", "kind": "skill", "aliases": ["roadmapping"]}]
_n = iter(range(1, 10_000))


def line(text, status="MET", importance="must", kind="skill", **extra):
    strength = {"MET": 4, "PARTIAL": 2}.get(status, 0)
    return {"id": f"x{next(_n)}", "provisional": True, "text": text, "kind": kind, "importance": importance, "status": status,
            "strength": strength, "quoteVerified": status in ("MET", "PARTIAL"), "postingQuote": text, **extra}


def block(reqs, resp=None, answers=None, aux=None):
    return f21.fit21(reqs, f2.UnitResolver(COMPS, None), resp, answers, aux)


# ---- units ----

def test_dictionary_skill_unit_even_when_the_text_is_also_an_alias():
    skills, domains, gaps = f21.build_units([line("SQL"), line("roadmapping")])  # "roadmapping" is an alias, not a dictionary term
    assert [u["id"] for u in skills] == ["sql"]
    assert len(gaps) == 1 and gaps[0]["kind"] == "skill"


def test_sentences_are_display_only_gaps_with_no_weight():
    b = block([line("SQL"), line("Ten years in a large company", kind="experience"), line("AWS Certified Solutions Architect", kind="certification")])
    assert b["requirements"]["counts"]["units"] == 1
    assert b["gaps"]["count"] == 2 and b["requirements"]["v0"] == 100


def test_domain_unit_keyed_by_quote_hash_when_no_dictionary_id():
    _, domains, _ = f21.build_units([line("Fintech payments", kind="domain")])
    assert len(domains) == 1 and domains[0]["id"].startswith("q:")
    again = f21.build_units([line("Fintech   payments.", kind="domain")])[1]
    assert again[0]["id"] == domains[0]["id"]


# ---- variants ----

def test_v0_v1_v2_differ_exactly_where_planned():
    reqs = [line("SQL", "MET"), line("Python", "NOT_EVIDENCED"), line("Fintech payments", "NOT_EVIDENCED", kind="domain"),
            line("Docker", "MET")]
    r = block(reqs)["requirements"]
    # settled: sql, docker (must 3 each, credit 1). V0: 6/6 = 100.
    assert r["v0"] == 100
    # V1: + half of 3 for python and for the domain = 6 + 3 = 9 -> 6/9 = 67
    assert r["v1"] == 67
    # V2: only the domain half: 6 / 7.5 = 80
    assert r["v2"] == 80
    d = block(reqs)["domain"]
    assert d["v0"] is None and d["v1"] is None  # nothing settled in domain


def test_nothing_settled_is_none_not_zero():
    r = block([line("SQL", "NOT_EVIDENCED")])["requirements"]
    assert r["v0"] is None and r["v1"] is None and r["v2"] is None


def test_confidence_is_the_fit20_value():
    reqs = [line("SQL", "MET"), line("Python", "NOT_EVIDENCED")]
    assert block(reqs)["confidence"] == f2.fit2(reqs, f2.UnitResolver(COMPS, None))["confidence"]


# ---- role mix ----

@pytest.mark.parametrize("text,cls", [
    ("Own the product roadmap and prioritize the backlog", "product"),
    ("Manage cross-functional programs and run sprint planning", "program"),
    ("Write code for backend services", "engineering"),
    ("Install racks and servers in the data center", "operations"),
    ("Respond to production incidents", "operations"),
])
def test_classify_by_verb_plus_object(text, cls):
    assert rm.classify(text)["class"] == cls


@pytest.mark.parametrize("text", ["engineering", "product", "delivery", "Developers and the engineering team", "leadership of delivery",
                                  "A strong product mindset", "The designer of the roadmap"])
def test_single_words_and_nouns_never_decide(text):
    assert rm.classify(text)["class"] is None


@pytest.mark.parametrize("text", ["Monitor Slack channels", "Manage programming languages", "Run serverless workloads", "Maintain the apiary", "Own programmatic advertising"])
def test_an_object_phrase_is_a_whole_phrase_with_an_optional_plural_only(text):
    assert rm.classify(text)["class"] is None


@pytest.mark.parametrize("text,cls", [("Define user stories", "product"), ("Track cross team dependencies", "program"), ("Run scrum ceremonies", "program"),
                                      ("Manage facilities", "operations"), ("Contribute to the repositories", "engineering"), ("Design APIs", "engineering"),
                                      ("Monitor SLAs", "operations")])
def test_irregular_plurals_are_listed(text, cls):
    assert rm.classify(text)["class"] == cls


def test_irregular_and_inflected_verbs():
    assert rm.classify("Ran the program reviews")["class"] == "program"
    assert rm.classify("Led product discovery")["class"] == "product"
    assert rm.classify("Building the product roadmap")["class"] == "product"


def test_tie_is_ambiguous():
    got = rm.classify("Own the product roadmap and write code")
    assert got["class"] == "ambiguous" and set(got["families"]) == {"product.roadmap", "eng.code"}


def test_role_fit_and_cue_counts_and_no_text():
    mix = rm.role_mix([{"text": "Own the product roadmap"}, {"text": "Manage programs"}, {"text": "Write code"}, {"text": "hello there"}])
    assert mix["roleFit"] == 67 and mix["counts"]["unclassified"] == 1 and mix["classified"] == 3
    assert mix["cuesFired"] == {"product.roadmap": 1, "program.delivery": 1, "eng.code": 1}
    assert not mix["insufficient"]
    assert "Own the product" not in str(mix)


def test_role_fit_not_available_without_responsibilities_and_no_title_fallback():
    b = block([line("SQL")], None, aux={"titleTier": "target", "roleTrack": "product", "roleMatchScore": 90})
    assert b["role"]["available"] is False and b["role"]["roleFit"] is None and b["role"]["insufficient"]
    assert b["auxiliary"] == {"titleTier": "target", "roleTrack": "product", "roleMatchScore": 90}
    assert f21.signal_value(b, "role") is None


def test_role_insufficient_when_under_half_classified():
    mix = rm.role_mix([{"text": "Write code"}, {"text": "x"}, {"text": "y"}])
    assert mix["roleFit"] == 0 and mix["insufficient"] and mix["reasons"] == ["too few responsibilities classified"]


# ---- responsibilities as matcher units ----

def test_responsibility_units_keyed_by_quote_hash_with_statuses():
    answers = [line("Own the roadmap", "MET", importance="nice"), line("Run stand ups", "NOT_EVIDENCED"), line("Own the roadmap.", "PARTIAL")]
    b = block([line("SQL")], [{"text": "Own the roadmap"}], answers)
    units = b["responsibilities"]["units"]
    assert len(units) == 2 and all(u["id"].startswith("r:") and u["importance"] == "nice" for u in units)
    assert b["responsibilities"]["fit"] == 100  # the one settled unit: MET beats PARTIAL on the merged quote


# ---- ranking guard ----

def test_rank_refuses_mixed_lists_and_orders_by_signal():
    a = {"id": "a", "fit21": block([line("SQL", "MET")])}
    b = {"id": "b", "fit21": block([line("SQL", "MET"), line("Python", "PARTIAL")])}
    assert [r["id"] for r in f21.rank([b, a])] == ["a", "b"]
    with pytest.raises(f21.MixedScoringVersions):
        f21.rank([a, {"id": "c", "fit2": {"scoringVersion": "2.0"}}])
    with pytest.raises(f21.MixedScoringVersions):
        f21.rank([a, {"id": "d", "fit21": {"scoringVersion": "1.5"}}])


# ---- shadow wiring ----

def test_shadow_adds_fit21_and_changes_no_1x_field(tmp_path):
    import test_engine_shadow as t
    from match_engine.shadow import ShadowEngine

    def run(job):
        eng = ShadowEngine(t.CANDIDATE, judge=True, provider="test", model="m", cache_path=tmp_path / "engine.json", complete=t.Fake(),
                           workers=1, unit_resolver=f2.UnitResolver(COMPS, None), role_family="product")
        return eng.apply([job])[0]["engineShadow"]

    plain = run(t.job("j1", 70))
    assert plain["fit21"]["scoringVersion"] == "2.1" and plain["fit2"]["scoringVersion"] == "2.0"
    assert plain["fit21"]["role"]["available"] is False  # no responsibility text in production reads: not available, no title fallback
    with_resp = t.job("j1", 70)
    with_resp["llmFacts"] = {**(with_resp.get("llmFacts") or {}), "responsibilities": [{"text": "Own the product roadmap", "postingQuote": "q"}],
                             "roleTrack": "product_management"}
    got = run(with_resp)
    assert got["fit21"]["role"]["roleFit"] == 100 and got["fit21"]["auxiliary"]["roleTrack"] == "product_management"
    for key in ("fit", "confidence", "label", "caps", "counts", "requirements"):
        assert got[key] == plain[key]
