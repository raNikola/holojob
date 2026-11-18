"""W5: Professional Fit 3 (shadow) on closed lists: anchoring, layers, ordering, rank guard, shadow wiring. No network, no real data/."""

import copy
import json

import pytest

from match_engine import fit3
from match_engine.matcher import GATES
from match_engine.shadow import ShadowEngine

AD = ("Product Manager at Acme.\nYou will own the product roadmap and talk to customers every week.\n"
      "Requirements:\n* Strong stakeholder management\n* Nice to have: SQL")
ROLES = fit3.load_roles()
COMPS = [{"id": "stakeholder-management", "definition": "Aligning stakeholders.", "kind": "skill"},
         {"id": "fintech", "definition": "Payments domain.", "kind": "domain"},
         {"id": "roadmapping", "definition": "Owning a roadmap.", "kind": "skill"}]


def reply(**over):
    base = {"function": {"role": "Product Manager", "quote": "own the product roadmap"}, "title": {"role": "Product Manager"},
            "competencies": [{"id": "stakeholder-management", "mark": "core", "quote": "Strong stakeholder management"},
                             {"id": "roadmapping", "mark": "secondary", "quote": "product roadmap"}]}
    base.update(over)
    return base


def anchored(r=None, ad=AD):
    return fit3.anchor(r or reply(), ad, ROLES, COMPS)


def answer(cid, status="MET", strength=3, verified=True):
    return {"id": cid, "status": status, "strength": strength, "quoteVerified": verified}


# ---- config ----

def test_role_config_is_the_declared_lists():
    assert [n for n, c in ROLES.items() if c == "target"] == [
        "Product Manager", "Technical Product Manager", "Product Owner", "Technical Program Manager",
        "Technical Project Manager", "IT Project Manager", "Software Delivery Manager"]
    assert {n for n, c in ROLES.items() if c == "adjacent"} == {"Project Manager", "Program Manager", "Engineering Manager"}
    assert ROLES["Other"] == "other"


def test_the_shipped_competency_list_is_the_closed_list():
    ids = {c["id"] for c in fit3.closed_competencies()}
    assert len(ids) > 100 and "communication" in ids


# ---- anchoring ----

def test_a_good_reply_is_anchored():
    a = anchored()
    assert a["role"]["class"] == "target" and [m["id"] for m in a["competencies"]] == ["roadmapping", "stakeholder-management"]
    assert not any(a["dropped"].values())


def test_unlisted_role_or_unquoted_role_makes_the_role_not_available():
    assert anchored(reply(function={"role": "Chief Wizard", "quote": "own the product roadmap"}))["role"]["class"] is None
    assert anchored(reply(function={"role": "Product Manager", "quote": "invented sentence"}))["role"]["class"] is None
    assert anchored(reply(function={"role": "product manager", "quote": "OWN the product roadmap"}))["role"]["class"] == "target"


def test_class_comes_from_the_config_not_from_the_model_label():
    r = reply(function={"role": "Project Manager", "quote": "own the product roadmap", "class": "target"})
    assert anchored(r)["role"]["class"] == "adjacent"


def test_title_only_demotes():
    demote = anchored(reply(title={"role": "Other"}))
    assert demote["role"]["class"] == "other" and demote["role"]["demotedByTitle"] is True
    promote = anchored(reply(function={"role": "Other", "quote": "own the product roadmap"}, title={"role": "Product Manager"}))
    assert promote["role"]["class"] == "other" and promote["role"]["demotedByTitle"] is False
    unknown_title = anchored(reply(title={"role": "nonsense"}))
    assert unknown_title["role"]["class"] == "target" and unknown_title["dropped"]["title"] == 1


def test_competency_marks_are_dropped_unless_listed_marked_and_quoted():
    r = reply(competencies=[
        {"id": "made-up", "mark": "core", "quote": "Strong stakeholder management"},
        {"id": "fintech", "mark": "core", "quote": "payments at scale"},
        {"id": "roadmapping", "mark": "none", "quote": "product roadmap"},
        {"id": "stakeholder-management", "mark": "core", "quote": "Strong  Stakeholder   management"},
        {"id": "stakeholder-management", "mark": "secondary", "quote": "Strong stakeholder management"},
        "junk"])
    a = anchored(r)
    assert [(m["id"], m["mark"]) for m in a["competencies"]] == [("stakeholder-management", "core")]
    assert a["dropped"] == {"role": 0, "title": 0, "unknownId": 1, "badMark": 2, "unquoted": 1, "duplicate": 1}


def test_a_bad_frame_is_an_error():
    with pytest.raises(fit3.Fit3Error):
        fit3.check_reply({"function": "x"})


def test_classify_needs_the_owners_confirm_and_sends_only_ad_and_lists():
    seen = []
    with pytest.raises(fit3.Fit3Error):
        fit3.classify({"title": "t", "description": AD}, confirmed=False, provider="p", model="m", complete=lambda *a, **k: reply())
    out = fit3.classify({"id": "j", "title": "PM role", "description": AD}, confirmed=True, provider="p", model="m", roles=ROLES, comps=COMPS,
                        complete=lambda prompt, **k: seen.append(prompt) or reply())
    assert out["function"]["role"] == "Product Manager"
    prompt = seen[0]
    assert "stakeholder-management: Aligning stakeholders." in prompt and AD in prompt and "PM role" in prompt


# ---- layers ----

def test_matcher_rows_are_the_marked_competencies():
    rows = fit3.matcher_requirements(anchored(), COMPS)
    assert [(r["id"], r["importance"], r["text"]) for r in rows] == [
        ("roadmapping", "preferred", "Owning a roadmap."), ("stakeholder-management", "must", "Aligning stakeholders.")]
    assert all(r["postingQuote"] and not r["provisional"] for r in rows)


def test_no_answer_is_unknown_never_not_evidenced_and_never_borrowed():
    b = fit3.fit3(anchored(), [answer("roadmapping")])  # an answer for the secondary only
    core = [u for u in b["requirements"]["units"] if u["ask"] == "core"][0]
    assert core["status"] == "UNKNOWN" and core["answered"] is False
    assert b["requirements"]["coreCounts"]["UNKNOWN"] == 1 and b["requirements"]["coreCounts"]["NOT_EVIDENCED"] == 0
    assert b["insufficientEvidence"] is True and "low confidence" in b["insufficientReasons"]


def test_core_is_weight_only_a_mark_alone_proves_nothing():
    b = fit3.fit3(anchored(), None)
    assert b["requirements"]["coverage"] == 0.0 and b["confidence"] == 0.0


def test_coverage_uses_the_matcher_statuses():
    b = fit3.fit3(anchored(), [answer("stakeholder-management", "MET", 4), answer("roadmapping", "PARTIAL", 2)])
    assert b["requirements"]["coreCoverage"] == "1" and b["confidence"] == 1.0
    assert b["requirements"]["secondaryCoverage"] == "1/4"
    assert b["insufficientEvidence"] is False
    contradicted = fit3.fit3(anchored(), [answer("stakeholder-management", "CONTRADICTED", 0)])
    assert contradicted["requirements"]["coreCoverage"] == "0" and contradicted["confidence"] == 1.0


def test_role_not_available_is_insufficient_and_the_title_is_no_substitute():
    b = fit3.fit3(anchored(reply(function={"role": "Product Manager", "quote": "nope"})), [answer("stakeholder-management")])
    assert b["role"]["class"] is None and "role not available" in b["insufficientReasons"]


def test_domain_from_the_existing_matcher_answers():
    def dom(status, importance="must", text="Fintech payments"):
        return {"id": "x", "provisional": True, "text": text, "kind": "domain", "importance": importance, "status": status,
                "strength": 2, "quoteVerified": True, "postingQuote": text}
    assert fit3.fit3(anchored(), None, [dom("CONTRADICTED")])["domain"] == "different"
    assert fit3.fit3(anchored(), None, [dom("MET")])["domain"] == "match"
    assert fit3.fit3(anchored(), None, [dom("PARTIAL"), dom("CONTRADICTED", "preferred", "Insurance")])["domain"] == "match"
    assert fit3.fit3(anchored(), None, [dom("NOT_EVIDENCED")])["domain"] == "unknown"
    assert fit3.fit3(anchored(), None, [])["domain"] == "unknown"


def test_seniority_is_a_distance_not_a_cap():
    assert fit3.seniority("senior", "lead") == {"ad": "senior", "candidate": "lead", "distance": 1, "reading": "candidate above"}
    assert fit3.seniority("head", "senior")["distance"] == -2
    assert fit3.seniority("unclear", "senior")["distance"] is None
    assert fit3.seniority(None, None)["reading"] is None


# ---- ordering ----

def row(rid, role_cls, domain, core_status, *, secondary=None):
    marks = [{"id": "stakeholder-management", "mark": "core", "quote": "q"}]
    if secondary:
        marks.append({"id": "roadmapping", "mark": "secondary", "quote": "q"})
    a = {"role": {"class": role_cls}, "competencies": marks, "dropped": {}}
    answers = [answer("stakeholder-management", core_status, 4)] + ([answer("roadmapping", secondary, 4)] if secondary else [])
    dom_req = [] if domain != "different" else [{"id": "d", "provisional": True, "text": "Fintech", "kind": "domain", "importance": "must",
                                                 "status": "CONTRADICTED", "strength": 0, "quoteVerified": True, "postingQuote": "Fintech"}]
    return {"id": rid, "fit3": fit3.fit3(a, answers, dom_req)}


def test_order_is_role_then_domain_then_core_then_secondary_then_id():
    rows = [row("a", "other", "match", "MET"), row("b", "adjacent", "match", "MET"), row("c", "target", "different", "MET"),
            row("d", "target", "match", "PARTIAL"), row("e", "target", "match", "MET", secondary="MET"),
            row("f", "target", "match", "MET"), row("g", None, "match", "MET")]
    assert [r["id"] for r in fit3.rank(rows)] == ["e", "f", "d", "c", "b", "a", "g"]


def test_unknown_domain_moves_nothing():
    plain = row("p", "target", "unknown", "MET")
    other = row("q", "target", "match", "MET")
    assert [r["id"] for r in fit3.rank([other, plain])] == ["p", "q"]  # equal on every tier: id decides


def test_rank_refuses_mixed_versions():
    good = row("a", "target", "match", "MET")
    with pytest.raises(fit3.MixedScoringVersions):
        fit3.rank([good, {"id": "x", "fit21": {"scoringVersion": "2.1"}}])
    with pytest.raises(fit3.MixedScoringVersions):
        fit3.rank([good, {"id": "y", "fit3": {**good["fit3"], "scoringVersion": "1.5"}}])
    with pytest.raises(fit3.MixedScoringVersions):
        fit3.rank([good, {"id": "z"}])


# ---- shadow wiring ----

REQ = {"id": "sql", "provisional": False, "text": "SQL", "kind": "skill", "importance": "must", "postingQuote": "Nice to have: SQL"}
CANDIDATE = {"profileVersion": "pv1", "evidenceVersion": "pv1", "answersVersion": "av1", "roleFamily": "product", "confirmedFacts": [], "gates": {},
             "evidence": [{"id": "ev-b", "text": "Wrote SQL daily", "source": "role", "role": "PM", "start": "2020", "end": None, "strength": 3}]}


def a_job():
    return {"jobId": "a", "title": "Product Manager", "company": "Acme", "location": "", "description": AD,
            "llmFacts": {"requirements": [REQ], "roleTrack": "product_management", "seniority": "senior"}, "matchScore": 70, "matchLabel": "Good", "priority": "P2"}


class Fake:
    def __call__(self, prompt, schema=None, model=None, provider=None):
        return {"matches": [{"ref": "r1", "status": "MET", "evidence_id": "ev-b", "evidence_quote": "Wrote SQL daily", "strength": 3}],
                "gates": {g: {"quote": None} for g in GATES}}


def test_shadow_adds_fit3_from_a_stored_entry_and_changes_nothing_else(tmp_path):
    cache = tmp_path / "engine.json"
    first = ShadowEngine(CANDIDATE, judge=True, provider="t", model="m", cache_path=cache, complete=Fake(), workers=1)
    [plain] = first.apply([a_job()])
    first.save()
    assert "fit3" not in plain["engineShadow"]

    posting = first._posting(a_job())
    roles, comps = fit3.load_roles(), fit3.closed_competencies()
    entry = {"reply": reply(), "answers": [answer("stakeholder-management", "MET", 4)]}
    (tmp_path / "fit3.json").write_text(json.dumps({"version": 1, "entries": {fit3.classification_key(posting, roles, comps): entry}}))

    again = ShadowEngine(CANDIDATE, judge=False, provider="t", model="m", cache_path=cache, complete=Fake(), workers=1, candidate_level="lead")
    [with3] = again.apply([a_job()])
    block = with3["engineShadow"].pop("fit3")
    assert block["scoringVersion"] == "3.0" and block["role"]["class"] == "target"
    assert block["seniority"]["distance"] == 1 and block["requirements"]["coreCoverage"] == "1"
    # 1.x fields are byte-identical with and without the Fit 3 store.
    stripped = copy.deepcopy(with3)
    for key in ("fromCache",):
        stripped["engineShadow"].pop(key), plain["engineShadow"].pop(key)
    assert json.dumps(stripped, sort_keys=True) == json.dumps({**plain}, sort_keys=True)
    assert {k: v for k, v in with3.items() if k != "engineShadow"} == {k: v for k, v in a_job().items()}


def test_an_ad_without_a_stored_classification_gets_no_fit3(tmp_path):
    cache = tmp_path / "engine.json"
    first = ShadowEngine(CANDIDATE, judge=True, provider="t", model="m", cache_path=cache, complete=Fake(), workers=1)
    first.apply([a_job()])
    first.save()
    (tmp_path / "fit3.json").write_text(json.dumps({"version": 1, "entries": {"other:key": {"reply": reply()}}}))
    [out] = ShadowEngine(CANDIDATE, judge=False, provider="t", model="m", cache_path=cache, complete=Fake(), workers=1).apply([a_job()])
    assert "fit3" not in out["engineShadow"]


# ---- owner tools ----

def test_matcher_over_fit3_rows(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import measure_fit3 as m3
    import measure_holdout_matcher as hm

    item = {"jobId": "j1", "title": "Product Manager", "company": "Acme", "description": AD}
    roles, comps = fit3.load_roles(), fit3.closed_competencies()
    good = {"function": {"role": "Product Manager", "quote": "own the product roadmap"}, "title": {"role": "Product Manager"},
            "competencies": [{"id": "communication", "mark": "core", "quote": "Strong stakeholder management"}]}
    key = fit3.classification_key(m3.posting_of(item), roles, comps)
    (tmp_path / "fit3").mkdir()
    (tmp_path / "fit3" / "classification.json").write_text(json.dumps({"version": 1, "entries": {key: {"reply": good, "answers": None}}}))
    other = {**item, "jobId": "j2", "description": AD + " other ad"}
    items, facts, counts = hm.facts_from_fit3(tmp_path, [item, other], {"j1": {"seniority": "senior"}, "j2": {}})
    assert [i["jobId"] for i in items] == ["j1"] and counts == {"noFit3Rows": 1, "fit3Rows": 1}
    row = facts["j1"]["requirements"][0]
    assert row["id"] == "communication" and row["importance"] == "must" and facts["j1"]["seniority"] == "senior"
    with pytest.raises(SystemExit):
        hm.facts_from_fit3(tmp_path / "nowhere", [item], {})
