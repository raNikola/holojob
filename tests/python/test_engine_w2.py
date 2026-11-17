"""W2: the status split (CONTRADICTED / NOT_EVIDENCED), the specificity weight, read freshness, extract-7. No model, no network."""

import json
import sys
from pathlib import Path

import pytest

from match_engine.fit import confidence_value, counts_of, fit_value, questions_for, score
from match_engine.matcher import GATES
from match_engine.specificity import GENERIC_COMPETENCY_IDS, is_specific, requirement_is_specific
from match_engine.verify import apply_confirmed_fact, output_status

_n = iter(range(1, 10_000))
PASS5 = [{"gate": g, "result": "pass", "quote": None} for g in GATES]


def req(status, importance="must", strength=None, kind="skill", rid=None, provisional=True):
    n = next(_n)
    if strength is None:
        strength = {"MET": 4, "PARTIAL": 2}.get(status, 0)
    return {"id": rid or f"r{n}", "provisional": provisional, "text": f"Skill {n}", "kind": kind, "importance": importance,
            "status": status, "quoteVerified": status in ("MET", "PARTIAL"), "strength": strength}


def canon(status, rid="roadmapping", importance="must", kind="skill"):
    return req(status, importance, kind=kind, rid=rid, provisional=False)


# ---- status split ----

def test_a_model_missing_is_not_evidenced_and_other_statuses_pass_through():
    assert output_status("MISSING") == "NOT_EVIDENCED"
    for status in ("MET", "PARTIAL", "UNKNOWN", "CONTRADICTED", "NOT_EVIDENCED", None):
        assert output_status(status) == status


def test_a_confirmed_no_is_contradicted():
    settled = apply_confirmed_fact(req("MISSING"), {"answer": "no"}, {})
    assert settled["status"] == "CONTRADICTED"


def test_not_evidenced_moves_nothing_unlike_contradicted():
    base = [req("MET", strength=4), req("PARTIAL", strength=2)]
    for status in ("NOT_EVIDENCED", "UNKNOWN"):
        assert fit_value(base + [req(status), req(status, "preferred")]) == fit_value(base)
    assert fit_value(base + [req("CONTRADICTED")]) < fit_value(base)


def test_not_evidenced_behaves_like_unknown_in_counts_questions_and_incomplete():
    for status in ("UNKNOWN", "NOT_EVIDENCED"):
        result = score([req("MET", strength=4), req(status), req(status), req(status, "preferred")], PASS5)
        assert result["counts"]["unknown"] == 3 and result["counts"]["blockers"] == 0
        assert len(result["questions"]) == 3
        assert result["label"] == "Incomplete"  # two of three musts unjudged
    assert counts_of([req("NOT_EVIDENCED")], PASS5)["notEvidenced"] == 1


def test_not_evidenced_lowers_confidence_and_contradicted_does_not():
    met = req("MET", strength=4)
    assert confidence_value([met, req("NOT_EVIDENCED")], PASS5) < confidence_value([met, req("CONTRADICTED")], PASS5)


def test_a_stored_pre_0_3_missing_is_read_as_not_evidenced():
    result = score([req("MET", strength=4), req("MISSING")], PASS5)
    assert result["counts"]["blockers"] == 0 and result["counts"]["notEvidenced"] == 1


# ---- specificity ----

def test_the_specificity_rule():
    assert is_specific("other", "roadmapping", True)                 # canonical
    assert is_specific("skill", None, False)                         # a specific kind, no id
    assert is_specific("language", "q:abc", False)
    assert not is_specific("experience", None, False)                # none of the two
    assert not is_specific("other", None, False)
    for generic in GENERIC_COMPETENCY_IDS:                           # Q3: generic overrides canonical and kind
        assert not is_specific("skill", generic, True)
    assert is_specific("skill", "stakeholder-management", True)      # a product competency stays specific
    assert not requirement_is_specific(req("MET", kind="experience"))
    assert requirement_is_specific(canon("MET", rid="communication-x"))
    assert not requirement_is_specific(canon("MET", rid="communication"))


def test_a_generic_requirement_weighs_nothing_in_fit_and_confidence():
    base = [canon("MET")]
    for generic in (canon("CONTRADICTED", rid="communication"), req("CONTRADICTED", kind="other")):
        assert fit_value(base + [generic]) == fit_value(base)
        assert confidence_value(base + [generic], PASS5) == confidence_value(base, PASS5)
    # shown and asked about when unjudged, still
    assert len(questions_for([canon("UNKNOWN", rid="communication")], PASS5)) == 1
    # and a posting whose only judged line is generic has nothing settled
    assert score([canon("MET", rid="communication")], PASS5)["label"] == "Incomplete"


# ---- read freshness (read-once) ----

import enrich_jobs  # noqa: E402
import job_fingerprint  # noqa: E402
from facts_guard import read_freshness  # noqa: E402

AD = {"jobId": "a", "title": "Product Manager", "company": "Acme", "location": "Nis",
      "description": "You will own the roadmap and run discovery with customers. 5+ years of product management."}


def _read(job, **over):
    return {**job, "llmFacts": {"requirements": [], "_fingerprint": job_fingerprint.job_fingerprint(job), **over}}


def test_read_freshness_none_fresh_stale_unversioned():
    assert read_freshness(AD) == "none"
    assert read_freshness(_read(AD)) == "fresh"
    assert read_freshness({**_read(AD), "description": AD["description"] + " Changed."}) == "stale"
    assert read_freshness({**_read(AD), "title": "Other"}) == "stale"
    assert read_freshness({**AD, "llmFacts": {"requirements": [{"text": "x"}]}}) == "unversioned"
    old = {**AD, "llmFacts": {"_fingerprint": job_fingerprint.job_fingerprint(AD, 5)}}
    assert read_freshness(old) == "stale"  # an older prompt version is never taken for the current one


def test_a_prompt_7_read_is_not_a_prompt_6_read():
    assert job_fingerprint.PROMPT_VERSION == 6  # the pipeline stays on extract-6 until the owner decides
    assert job_fingerprint.job_fingerprint(AD, 7) != job_fingerprint.job_fingerprint(AD)
    assert job_fingerprint.job_fingerprint(AD, 6) == job_fingerprint.job_fingerprint(AD)


# ---- extract-7: responsibilities ----

QUOTE_OK = "own the roadmap"
REQ_ITEM = {"text": "Product management", "kind": "experience", "importance": "must", "posting_quote": "5+ years of product management",
            "previous_id": None, "qualifier": {"kind": "years", "value": 5}}


def _reply(responsibilities):
    base = {"work_mode": "remote", "role_track": "product_management", "seniority": "senior", "requirements": [REQ_ITEM]}
    return {**base, **({} if responsibilities is None else {"responsibilities": responsibilities})}


def test_prompt_6_is_byte_identical_and_prompt_7_adds_the_field_and_rule():
    six, seven = enrich_jobs.build_prompt(AD), enrich_jobs.build_prompt(AD, responsibilities=True)
    assert "responsibilit" not in six.split("=== BEGIN JOB AD")[0].replace("no named responsibilities", "")
    assert '"responsibilities"' in seven and "14. responsibilities" in seven
    assert seven.index('"responsibilities"') < seven.index("Title: Product Manager")  # the fixed text still comes first
    assert six.replace("{", "").replace("}", "") != seven.replace("{", "").replace("}", "")


def test_the_schema_asks_for_responsibilities_only_in_prompt_7():
    assert "responsibilities" not in enrich_jobs.fact_schema()["schema"]["properties"]
    schema = enrich_jobs.fact_schema(True, True)["schema"]
    item = schema["properties"]["responsibilities"]["items"]
    assert "responsibilities" in schema["required"] and item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"]) == {"text", "posting_quote"}


def test_extract_7_keeps_only_responsibilities_whose_quote_is_in_the_ad(monkeypatch):
    monkeypatch.setattr(enrich_jobs, "complete_json", lambda *a, **k: _reply([
        {"text": "Own the roadmap", "posting_quote": QUOTE_OK},
        {"text": "Invented", "posting_quote": "manage a team of fifty"},
        {"text": "", "posting_quote": "run discovery"},
    ]))
    facts = enrich_jobs.extract(AD, None, None, responsibilities=True)
    assert facts["responsibilities"] == [{"text": "Own the roadmap", "postingQuote": QUOTE_OK}]
    assert facts["responsibilitiesDropped"] == 1  # the invented quote; the empty-text item never gets that far
    assert facts["_fingerprint"] == job_fingerprint.job_fingerprint(AD, 7)
    assert facts["requirements"][0]["postingQuote"] == "5+ years of product management"


def test_extract_6_is_unchanged_by_the_new_code(monkeypatch):
    monkeypatch.setattr(enrich_jobs, "complete_json", lambda *a, **k: _reply([{"text": "x", "posting_quote": QUOTE_OK}]))
    facts = enrich_jobs.extract(AD, None, None)
    assert "responsibilities" not in facts and "responsibilitiesDropped" not in facts
    assert facts["_fingerprint"] == job_fingerprint.job_fingerprint(AD)


def test_facts_with_responsibilities_pass_the_shape_guard():
    from facts_guard import facts_shape_ok
    assert facts_shape_ok({"requirements": [], "responsibilities": [{"text": "x", "postingQuote": "y"}]})


# ---- responsibility keys and the stability tool ----

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import measure_extraction_variance as variance  # noqa: E402
import measure_requirement_stability as stability  # noqa: E402


def test_responsibility_keys_are_hashes_of_the_normalised_quote_and_hold_no_text():
    a = variance.responsibility_keys({"responsibilities": [{"postingQuote": "Own the Roadmap."}, {"postingQuote": "own  the roadmap"}]})
    assert len(a) == 1 and a[0]["key"].startswith("r:") and "roadmap" not in json.dumps(a)
    assert variance.responsibility_keys({}) == []


def test_the_stability_tool_reports_responsibilities_as_a_separate_class():
    doc = {"responsibilityKeys": {"a": [[{"key": "r:1"}, {"key": "r:2"}], [{"key": "r:1"}]], "b": [[], []]}}
    out = stability.responsibility_stability(doc)
    assert out["ads"] == 1 and out["median"] == 0.5 and out["adsUndefined"] == 1
    assert stability.responsibility_stability({"unitKeys": {}}) is None


def test_the_specific_must_class_uses_the_engine_rule():
    unit = lambda key, kind, canonical=True: {"key": key, "canonical": canonical, "kind": kind, "importance": "must"}  # noqa: E731
    assert not stability.is_specific_must(unit("c:communication", "skill"))
    assert stability.is_specific_must(unit("c:roadmapping", "other"))
    assert stability.is_specific_must(unit("q:abc", "skill", False))
    assert not stability.is_specific_must(unit("q:abc", "experience", False))
    assert not stability.is_specific_must({**unit("c:roadmapping", "skill"), "importance": "preferred"})
