"""W5: Professional Fit 3 (shadow) on closed lists: anchoring, layers, ordering, rank guard, shadow wiring. No network, no real data/."""

import copy
import json
import sys
from pathlib import Path

import pytest

from match_engine import fit3
from match_engine.matcher import GATES
from match_engine.shadow import ShadowEngine

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

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


def anchored(r=None, ad=AD, roles=None, title="Product Manager"):
    return fit3.anchor(r or reply(), ad, roles or ROLES, COMPS, title)


def answer(cid, status="MET", strength=3, verified=True):
    return {"id": cid, "status": status, "strength": strength, "quoteVerified": verified}


# ---- config ----

def test_role_config_is_the_declared_lists():
    assert [n for n, c in ROLES.items() if c == "target"] == [
        "Product Manager", "Technical Product Manager", "Product Owner", "Technical Program Manager",
        "Technical Project Manager", "IT Project Manager", "Software Delivery Manager"]
    assert {n for n, c in ROLES.items() if c == "adjacent"} == {"Project Manager", "Program Manager", "Engineering Manager"}
    assert ROLES["Other"] == "other"
    assert {n for n, c in ROLES.items() if c == "other"} == {  # A2.3: exact names only, no generic "Engineer" or "Manager"
        "Other", "Backend Engineer", "Frontend Engineer", "Full-Stack Engineer", "Software Engineer", "QA Engineer", "Data Engineer", "DevOps Engineer",
        "Account Executive"}


def test_the_shipped_competency_list_is_the_closed_list():
    ids = {c["id"] for c in fit3.closed_competencies()}
    assert len(ids) > 100 and "communication" in ids


# ---- anchoring ----

def test_a_good_reply_is_anchored():
    a = anchored()
    assert a["role"]["class"] == "target" and [m["id"] for m in a["competencies"]] == ["roadmapping", "stakeholder-management"]
    assert not any(a["dropped"].values()) and a["modelMarks"] == 2


def test_unlisted_role_or_unquoted_role_makes_the_role_not_available():
    assert anchored(reply(function={"role": "Chief Wizard", "quote": "own the product roadmap"}))["role"]["class"] is None
    assert anchored(reply(function={"role": "Product Manager", "quote": "invented sentence"}))["role"]["class"] is None
    assert anchored(reply(function={"role": "product manager", "quote": "OWN the product roadmap"}))["role"]["class"] == "target"


def test_class_comes_from_the_config_not_from_the_model_label():
    r = reply(function={"role": "Project Manager", "quote": "own the product roadmap", "class": "target"})
    assert anchored(r)["role"]["class"] == "adjacent"


SPECIFIC = ROLES


def test_title_demotes_only_with_a_specific_other_role_and_a_title_quote():
    title = "Software Engineer, Platform"
    demote = anchored(reply(title={"role": "Software Engineer", "quote": "Software Engineer"}), roles=SPECIFIC, title=title)
    assert demote["role"]["class"] == "other" and demote["role"]["demotedByTitle"] is True
    # the generic "Other", a missing quote, a quote that is not in the title, or an unknown name never demote
    for t in ({"role": "Other", "quote": "Software Engineer"}, {"role": "Software Engineer"}, {"role": "Software Engineer", "quote": "Platform Wizard"},
              {"role": "nonsense", "quote": "Software Engineer"}, {"role": "Other"}):
        got = anchored(reply(title=t), roles=SPECIFIC, title=title)
        assert got["role"]["class"] == "target" and got["role"]["demotedByTitle"] is False, t
    assert anchored(reply(title={"role": "nonsense"}))["dropped"]["title"] == 1


def test_titles_that_only_contain_an_other_name_are_not_demoted():
    # A2.3: the model can only name a listed role; none of these titles is one, so none demotes, whatever the quote
    for title, named in (("Software Engineering Manager", "Software Engineering Manager"), ("Data Product Manager", "Data Product Manager"),
                         ("Technical Program Manager, Data Platform", "Technical Program Manager, Data Platform")):
        got = anchored(reply(title={"role": named, "quote": title}), title=title)
        assert got["role"]["class"] == "target" and got["role"]["demotedByTitle"] is False, title
    # and every listed Other name does demote when quoted from the title
    for name in ("Backend Engineer", "Frontend Engineer", "Full-Stack Engineer", "Software Engineer", "QA Engineer", "Data Engineer", "DevOps Engineer",
                 "Account Executive"):
        assert anchored(reply(title={"role": name, "quote": name}), title=f"{name} II")["role"]["demotedByTitle"] is True, name
    assert "Engineer" not in ROLES and "Manager" not in ROLES


def test_title_never_promotes():
    got = anchored(reply(function={"role": "Other", "quote": "own the product roadmap"}, title={"role": "Product Manager", "quote": "Product Manager"}))
    assert got["role"]["class"] == "other" and got["role"]["demotedByTitle"] is False


def test_competency_marks_are_dropped_unless_listed_and_marked_a_core_without_quote_falls_to_secondary():
    r = reply(competencies=[
        {"id": "made-up", "mark": "core", "quote": "Strong stakeholder management"},
        {"id": "fintech", "mark": "core", "quote": "payments at scale"},
        {"id": "roadmapping", "mark": "none", "quote": "product roadmap"},
        {"id": "stakeholder-management", "mark": "core", "quote": "Strong  Stakeholder   management"},
        {"id": "stakeholder-management", "mark": "secondary", "quote": "Strong stakeholder management"},
        "junk"])
    a = anchored(r)
    assert [(m["id"], m["mark"], m["quote"] is None) for m in a["competencies"]] == [("fintech", "secondary", True), ("stakeholder-management", "core", False)]
    assert a["dropped"] == {"role": 0, "title": 0, "unknownId": 1, "badMark": 2, "unquoted": 0, "duplicate": 1, "misplaced": 0, "coreDemoted": 1}


def test_a_secondary_without_a_quote_is_dropped():
    a = anchored(reply(competencies=[{"id": "roadmapping", "mark": "secondary", "quote": "never said"}]))
    assert a["competencies"] == [] and a["dropped"]["unquoted"] == 1


def test_a_quoteless_core_gets_no_matcher_row_and_stays_unknown():
    a = anchored(reply(competencies=[{"id": "fintech", "mark": "core", "quote": "payments at scale"},
                                     {"id": "stakeholder-management", "mark": "core", "quote": "Strong stakeholder management"}]))
    assert [r["id"] for r in fit3.matcher_requirements(a, COMPS)] == ["stakeholder-management"]
    b = fit3.fit3(a, [answer("fintech"), answer("stakeholder-management")])  # even a stray answer for the unquoted one is not read
    unit = {u["id"]: u for u in b["requirements"]["units"]}["fintech"]
    assert unit["status"] == "UNKNOWN" and unit["ask"] == "secondary" and unit["demotedFromCore"] is True


def test_misplaced_items_are_dropped_and_counted_not_moved():
    # a competency id in the function slot: the role is not available, nothing is added to the competencies
    a = anchored(reply(function={"role": "roadmapping", "quote": "own the product roadmap"}, competencies=[]))
    assert a["role"]["class"] is None and a["dropped"]["misplaced"] == 1 and a["competencies"] == []
    # a role name in the competency list is dropped, even when the function slot is empty
    b = anchored(reply(function={"role": "", "quote": ""}, competencies=[{"id": "Product Manager", "mark": "core", "quote": "own the product roadmap"}]))
    assert b["role"]["class"] is None and b["dropped"]["misplaced"] == 1 and b["competencies"] == [] and b["dropped"]["unknownId"] == 0
    c = anchored(reply(competencies=[{"id": "Project Manager", "mark": "core", "quote": "own the product roadmap"}, {"id": "made-up", "mark": "core"}]))
    assert c["role"]["class"] == "target" and c["dropped"]["misplaced"] == 1 and c["dropped"]["unknownId"] == 1
    assert "moved" not in c["dropped"]


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
    assert fit3.PROMPT_VERSION == 2 and '"title": {"role": "...", "quote": "..."}' in prompt


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
    assert b["insufficientEvidence"] is True and "low confidence" in b["insufficientReasons"] and "no resolved core competency" in b["insufficientReasons"]


def test_core_is_weight_only_a_mark_alone_proves_nothing():
    b = fit3.fit3(anchored(), None)
    assert b["requirements"]["coverage"] is None and b["requirements"]["coreCoverage"] is None and b["confidence"] == 0.0


def test_coverage_uses_the_matcher_statuses():
    b = fit3.fit3(anchored(), [answer("stakeholder-management", "MET", 4), answer("roadmapping", "PARTIAL", 2)])
    assert b["requirements"]["coreCoverage"] == "1" and b["confidence"] == 1.0
    assert b["requirements"]["secondaryCoverage"] == "1/4"
    assert b["insufficientEvidence"] is False
    contradicted = fit3.fit3(anchored(), [answer("stakeholder-management", "CONTRADICTED", 0)])
    assert contradicted["requirements"]["coreCoverage"] == "0" and contradicted["confidence"] == 1.0


def three_core():
    marks = [{"id": i, "mark": "core", "quote": "q"} for i in ("stakeholder-management", "fintech", "roadmapping")]
    return {"role": {"class": "target"}, "competencies": marks, "dropped": {}}


def test_coverage_is_over_resolved_units_and_v1_adds_half_weight_for_not_evidenced():
    answers = [answer("stakeholder-management", "MET", 4), answer("fintech", "MET", 4), answer("roadmapping", "NOT_EVIDENCED", 0)]
    r = fit3.fit3(three_core(), answers)["requirements"]
    assert r["coreCoverage"] == "1" and r["coreCoverageV1"] == "4/5"  # 2 / (2 + 1/2)
    unknown = fit3.fit3(three_core(), [answer("stakeholder-management", "MET", 4), answer("fintech", "MET", 4)])
    assert unknown["requirements"]["coreCoverage"] == "1" and unknown["requirements"]["coreCoverageV1"] == "1"  # UNKNOWN is not NOT_EVIDENCED
    assert unknown["requirements"]["coreCounts"]["UNKNOWN"] == 1 and unknown["confidence"] == 0.6667
    unverified = fit3.fit3(three_core(), [answer("stakeholder-management", "MET", 4, verified=False)])
    assert unverified["requirements"]["coreCoverage"] is None  # a MET without a verified quote is not resolved


def test_role_not_available_is_insufficient_and_the_title_is_no_substitute():
    b = fit3.fit3(anchored(reply(function={"role": "Product Manager", "quote": "nope"})), [answer("stakeholder-management")])
    assert b["role"]["class"] is None and "role not available" in b["insufficientReasons"]


def test_seniority_is_a_distance_not_a_cap():
    assert fit3.seniority("senior", "lead") == {"ad": "senior", "candidate": "lead", "distance": 1, "reading": "candidate above"}
    assert fit3.seniority("head", "senior")["distance"] == -2
    assert fit3.seniority("unclear", "senior")["distance"] is None
    assert fit3.seniority(None, None)["reading"] is None


# ---- domain (A1.2) ----

def test_domain_by_synonym_from_the_stored_industry_fields():
    from match_engine import fit3_industry as ind
    assert ind.domains_in_text("Fintech and payments") == {"banking"} and ind.domains_in_text("nothing relevant") == set()
    posting = {"title": "Product Manager", "company": "Acme", "description": "We build software for the hospital sector, a medical product."}
    assert ind.ad_industries(posting, {}) == {"healthcare"}
    assert ind.ad_industries({**posting, "description": "x"}, {"domain": "Insurance"}) == {"insurance"}
    intel = {"historyEntries": [{"role": "r", "domains": ["telecom", "nonsense"]}, {"role": "s"}],
             "jobFitPreferences": {"preferredIndustries": ["SaaS", "gardening"]}, "experienceMap": {"domainsWorkedIn": ["Banking"]}}
    got = ind.candidate_industries(intel)  # A2.4: preferences are display only; one history entry has no domains, so the set is incomplete
    assert got.confirmed == {"telecom", "banking"} and got.preferred == {"saas"} and got.complete is False
    assert ind.candidate_industries(None) == ind.Industries()
    full = ind.candidate_industries({"historyEntries": [{"domains": ["telecom"]}, {"domains": ["saas", "x"]}]})
    assert full.confirmed == {"telecom", "saas"} and full.complete is True
    assert ind.candidate_industries({"historyEntries": [{"domains": ["nonsense"]}]}).complete is False  # no table domain: not complete
    assert ind.candidate_industries({"experienceMap": {"domainsWorkedIn": ["Banking"]}}).complete is False  # no history at all
    complete, partial = ind.Industries(frozenset({"saas"}), True), ind.Industries(frozenset({"saas"}), False)
    assert ind.compare({"banking"}, ind.Industries(frozenset({"banking", "saas"}), False)) == ("match", ["banking"])  # match is valid when incomplete
    assert ind.compare({"healthcare"}, complete) == ("different", [])
    assert ind.compare({"healthcare"}, partial)[0] == "unknown"  # different needs a complete candidate set
    assert ind.compare({"healthcare"}, ind.Industries(frozenset({"saas"}), False, frozenset({"healthcare"})))[0] == "unknown"  # preferences never count
    assert ind.compare(set(), complete)[0] == "unknown" and ind.compare({"saas"}, ind.Industries())[0] == "unknown"


def test_domain_does_not_read_the_matcher_statuses():
    dom = {"id": "x", "provisional": True, "text": "Fintech", "kind": "domain", "importance": "must", "status": "CONTRADICTED", "strength": 0,
           "quoteVerified": True, "postingQuote": "Fintech"}
    assert fit3.fit3(anchored(), [dom])["domain"] == "unknown"
    from match_engine.fit3_industry import Industries
    b = fit3.fit3(anchored(), None, {"banking"}, Industries(frozenset({"banking"}), False, frozenset({"saas"})))
    assert b["domain"] == "match" and b["domainDetail"] == {"adIndustries": ["banking"], "sharedIndustries": ["banking"], "candidateIndustryCount": 1,
                                                            "candidateComplete": False, "preferredIndustries": ["saas"]}
    assert fit3.fit3(anchored(), None, {"banking"}, Industries(frozenset({"saas"}), True))["domain"] == "different"
    assert fit3.fit3(anchored(), None, {"banking"}, Industries(frozenset({"saas"}), False))["domain"] == "unknown"


# ---- ordering ----

def I(domains, complete=False):
    from match_engine.fit3_industry import Industries
    return Industries(frozenset(domains), complete)


def row(rid, role_cls, domain, core_status, *, secondary=None):
    marks = [{"id": "stakeholder-management", "mark": "core", "quote": "q"}]
    if secondary:
        marks.append({"id": "roadmapping", "mark": "secondary", "quote": "q"})
    a = {"role": {"class": role_cls}, "competencies": marks, "dropped": {}}
    answers = [answer("stakeholder-management", core_status, 4)] + ([answer("roadmapping", secondary, 4)] if secondary else [])
    ad, cand = ({"healthcare"}, I({"saas"}, True)) if domain == "different" else ({"saas"}, I({"saas"}, True)) if domain == "match" else (None, I({"saas"}, True))
    return {"id": rid, "fit3": fit3.fit3(a, answers, ad, cand)}


def ids(rows):
    return [r["id"] for r in rows]


def test_order_is_tier_then_domain_then_core_then_secondary_then_id():
    rows = [row("a", "other", "match", "MET"), row("b", "adjacent", "match", "MET"), row("c", "target", "different", "MET"),
            row("d", "target", "match", "PARTIAL"), row("e", "target", "match", "MET", secondary="MET"),
            row("f", "target", "match", "MET"), row("g", None, "match", "MET")]
    got = fit3.rank(rows)
    # target and adjacent are one tier (b ties f on every key, id decides); other is last; a missing role is Insufficient evidence
    assert ids(got["ranked"]) == ["e", "b", "f", "d", "c", "a"] and ids(got["insufficient"]) == ["g"]


def test_insufficient_evidence_is_a_separate_group_sorted_by_id():
    weak = {"id": "z", "fit3": fit3.fit3(three_core(), [answer("stakeholder-management", "MET", 4)])}  # 1 of 3 core resolved
    good = row("m", "other", "unknown", "MET")
    got = fit3.rank([weak, good])
    assert ids(got["ranked"]) == ["m"] and ids(got["insufficient"]) == ["z"]


def test_v0_and_v1_orders_are_computed_side_by_side():
    two = {"role": {"class": "target"}, "competencies": three_core()["competencies"][:2], "dropped": {}}
    x = {"id": "b", "fit3": fit3.fit3(two, [answer("stakeholder-management", "MET", 4), answer("fintech", "MET", 4)])}
    y = {"id": "a", "fit3": fit3.fit3(three_core(), [answer("stakeholder-management", "MET", 4), answer("fintech", "MET", 4),
                                                    answer("roadmapping", "NOT_EVIDENCED", 0)])}
    assert ids(fit3.rank([x, y], "v0")["ranked"]) == ["a", "b"]  # equal core coverage 1: id decides
    assert ids(fit3.rank([x, y], "v1")["ranked"]) == ["b", "a"]  # a's NOT_EVIDENCED counts half in V1
    with pytest.raises(ValueError):
        fit3.rank([x], "v2")


def test_unknown_domain_moves_nothing():
    plain = row("p", "target", "unknown", "MET")
    other = row("q", "target", "match", "MET")
    assert ids(fit3.rank([other, plain])["ranked"]) == ["p", "q"]  # equal on every key: id decides


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

    from match_engine.fit3_industry import Industries
    again = ShadowEngine(CANDIDATE, judge=False, provider="t", model="m", cache_path=cache, complete=Fake(), workers=1, candidate_level="lead",
                         candidate_industries=Industries(frozenset({"saas"}), True))
    [with3] = again.apply([a_job()])
    block = with3["engineShadow"].pop("fit3")
    assert block["scoringVersion"] == "3.0" and block["role"]["class"] == "target"
    assert block["seniority"]["distance"] == 1 and block["requirements"]["coreCoverage"] == "1"
    assert block["domain"] == "unknown" and block["domainDetail"]["candidateIndustryCount"] == 1  # the ad names no industry
    # 1.x fields are byte-identical with and without the Fit 3 store.
    stripped = copy.deepcopy(with3)
    for key in ("fromCache",):
        stripped["engineShadow"].pop(key), plain["engineShadow"].pop(key)
    assert json.dumps(stripped, sort_keys=True) == json.dumps({**plain}, sort_keys=True)
    assert {k: v for k, v in with3.items() if k != "engineShadow"} == {k: v for k, v in a_job().items()}


def test_stored_fit3_reads_the_industry_from_the_ad_facts_and_the_title_from_the_posting():
    roles, comps = SPECIFIC, COMPS
    job = {**a_job(), "llmFacts": {"domain": "Insurance", "seniority": "mid"}}
    posting = {"id": "a", "title": "Software Engineer", "company": "Acme", "description": AD}
    store = {fit3.classification_key(posting, roles, comps): {"reply": reply(title={"role": "Software Engineer", "quote": "Software Engineer"}), "answers": None}}
    block = fit3.stored_fit3(job, posting, store, roles, comps, I({"banking"}, True), "senior")
    assert block["domain"] == "different" and block["role"]["demotedByTitle"] is True and block["seniority"]["distance"] == 1


def test_candidate_level_is_read_only_when_on_the_scale():
    import run_scoring
    assert run_scoring._candidate_level({"candidateSummary": {"seniorityLevel": "Lead"}}) == "lead"
    assert run_scoring._candidate_level({"candidateSummary": {"seniorityLevel": "wizard"}}) is None and run_scoring._candidate_level({}) is None


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
    import measure_fit3 as m3
    import measure_holdout_matcher as hm

    item = {"jobId": "j1", "title": "Product Manager", "company": "Acme", "description": AD}
    roles, comps = fit3.load_roles(), fit3.closed_competencies()
    good = {"function": {"role": "Product Manager", "quote": "own the product roadmap"}, "title": {"role": "Product Manager"},
            "competencies": [{"id": "communication", "mark": "core", "quote": "Strong stakeholder management"},
                             {"id": "roadmapping", "mark": "core", "quote": "never said anywhere"}]}
    key = fit3.classification_key(m3.posting_of(item), roles, comps)
    (tmp_path / "fit3").mkdir()
    (tmp_path / "fit3" / "classification.json").write_text(json.dumps({"version": 1, "entries": {key: {"reply": good, "answers": None}}}))
    other = {**item, "jobId": "j2", "description": AD + " other ad"}
    items, facts, counts = hm.facts_from_fit3(tmp_path, [item, other], {"j1": {"seniority": "senior"}, "j2": {}})
    assert [i["jobId"] for i in items] == ["j1"] and counts == {"noFit3Rows": 1, "fit3Rows": 1}  # the quoteless core mark gets no row
    row = facts["j1"]["requirements"][0]
    assert row["id"] == "communication" and row["importance"] == "must" and facts["j1"]["seniority"] == "senior"
    with pytest.raises(SystemExit):
        hm.facts_from_fit3(tmp_path / "nowhere", [item], {})


def test_merge_puts_the_matcher_rows_into_the_classification_entry():
    import measure_fit3 as m3
    import merge_fit3_answers as merge

    roles, comps = fit3.load_roles(), fit3.closed_competencies()
    items = [{"jobId": f"j{n}", "title": "Product Manager", "company": "Acme", "description": AD + f" {n}"} for n in (1, 2, 3)]
    keys = [fit3.classification_key(m3.posting_of(i), roles, comps) for i in items[:2]]
    classification = {"version": 1, "promptVersion": 2, "entries": {k: {"reply": reply(), "answers": None} for k in keys}}
    results = {"j1": {"output": {"requirements": [answer("communication"), {"status": "MET"}]}}, "j2": {"output": None}}
    store, counts = merge.merge(classification, items, results)
    assert store["entries"][keys[0]]["answers"] == [answer("communication")] and store["entries"][keys[1]]["answers"] is None
    assert counts == {"entries": 2, "ads": 3, "withAnswers": 1, "noClassification": 1, "noMatcherResult": 1, "rowsWithoutId": 1}


def test_bars_checker_computes_b1_to_b5_on_synthetic_passes():
    import check_fit3_bars as bars
    from match_engine.fit3_industry import Industries

    def ad(i, company):
        return {"posting": {"id": i, "title": "Product Manager", "company": company, "description": AD}, "facts": {}}

    ads = {"a1": ad("a1", "Alpha Corp"), "a2": ad("a2", "Beta Ltd"), "a3": ad("a3", "Gamma Inc")}

    def entry(role, mark_quote="Strong stakeholder management", status="MET"):
        return {"anchored": fit3.anchor(reply(function={"role": role, "quote": "own the product roadmap"},
                                              competencies=[{"id": "stakeholder-management", "mark": "core", "quote": mark_quote}]), AD, ROLES, COMPS, "PM"),
                "answers": [answer("stakeholder-management", status, 4)]}

    p1 = {"a1": entry("Product Manager"), "a2": entry("Other"), "a3": entry("Product Manager")}
    p2 = {"a1": entry("Product Manager"), "a2": entry("Other"), "a3": entry("Product Manager", "never said")}
    labels = {"apply": ["alpha", "monzo"], "fitSkip": ["beta"], "expectTarget": ["alpha"], "expectOther": ["beta"]}
    out = bars.evaluate(ads, [p1, p2], labels, Industries(frozenset({"saas"}), True), "senior", 20)
    assert out["B1"]["flips"] == 0 and out["B1"]["verdict"] == "PASS" and out["B2"]["verdict"] == "PASS"
    assert out["B3"]["medianOverlap"] == 1.0 and out["B3"]["shareWithCore"] == [1.0, 0.6667] and out["B3"]["verdict"] == "FAIL"  # a3's core fell in pass 2
    assert out["B4"]["passes"][1] == {"modelMarks": 3, "secondaryDropped": 0, "coreDemoted": 1, "share": 0.3333} and out["B4"]["verdict"] == "FAIL"
    first = out["B5"][0]["v0"]
    assert first["applyInTop6"] == 1 and first["of"] == 2 and first["fitSkipAboveApply"] == [] and first["verdict"] == "FAIL (PRELIMINARY)"  # 1 of 2 in the top 6
    swapped = bars.evaluate(ads, [{**p1, "a1": entry("Other"), "a2": entry("Product Manager")}], {**labels, "expectTarget": [], "expectOther": []}, Industries(), None, 20)
    assert swapped["B5"][0]["v0"]["fitSkipAboveApply"] == ["a2"]
    assert bars.evaluate(ads, [p1], labels, Industries(), None, 20)["B1"]["verdict"] == "NOT EVALUABLE"


def test_b5_a2_apply_in_the_insufficient_group_is_a_miss_and_leaves_the_pairs_and_no_answers_is_not_evaluable():
    import check_fit3_bars as bars
    from match_engine.fit3_industry import Industries

    def ad(i, company):
        return {"posting": {"id": i, "title": "Product Manager", "company": company, "description": AD}, "facts": {}}

    ads = {"a1": ad("a1", "Alpha Corp"), "a2": ad("a2", "Beta Ltd"), "a3": ad("a3", "Gamma Inc")}

    def entry(answers, role="Product Manager"):
        return {"anchored": fit3.anchor(reply(function={"role": role, "quote": "own the product roadmap"},
                                              competencies=[{"id": "stakeholder-management", "mark": "core", "quote": "Strong stakeholder management"}]),
                                        AD, ROLES, COMPS, "PM"), "answers": answers}

    met = [answer("stakeholder-management", "MET", 4)]
    # Alpha (APPLY) has no resolved core unit: insufficient. Beta (FIT-skip) and Gamma (APPLY) are ranked.
    p = {"a1": entry([answer("stakeholder-management", "UNKNOWN", 0)]), "a2": entry(met, "Other"), "a3": entry(met)}
    labels = {"apply": ["alpha", "gamma"], "fitSkip": ["beta"]}
    out = bars.b5(p, ads, labels, Industries(), None)["v0"]
    assert out["applyInTop6"] == 1 and out["applyInsufficientOrNoText"] == 1 and out["criterion1"] is False
    assert out["fitSkipAboveApply"] == [] and out["criterion2"] is True  # Alpha is out of the pairs; Beta (Other tier) is below Gamma
    # an APPLY that is insufficient must not make criterion 2 fail: with only that APPLY and a ranked skip, there is no pair
    only = bars.b5({"a1": p["a1"], "a2": p["a2"]}, ads, {"apply": ["alpha"], "fitSkip": ["beta"]}, Industries(), None)["v0"]
    assert only["fitSkipAboveApply"] == [] and only["criterion2"] is True and only["criterion1"] is False
    # a pass with no matcher answers is NOT EVALUABLE, not FAIL
    bare = {i: entry(None) for i in ads}
    got = bars.b5(bare, ads, labels, Industries(), None)
    assert got["verdict"] == "NOT EVALUABLE" and "v0" not in got


def test_a3_split_groups_by_ad_id_not_by_company():
    import check_fit3_bars as bars
    from match_engine.fit3_industry import Industries
    role_skip, other_same_company = bars.A3_ROLE_SKIPS[0], "zz-unlabelled"

    def ad(i, company):
        return {"posting": {"id": i, "title": "Product Manager", "company": company, "description": AD}, "facts": {}}

    ads = {"a1": ad("a1", "Alpha"), role_skip: ad(role_skip, "Nebius"), other_same_company: ad(other_same_company, "Nebius")}
    met = [answer("stakeholder-management", "MET", 4)]

    def entry(role):
        return {"anchored": fit3.anchor(reply(function={"role": role, "quote": "own the product roadmap"},
                                              competencies=[{"id": "stakeholder-management", "mark": "core", "quote": "Strong stakeholder management"}]), AD, ROLES, COMPS, "PM"),
                "answers": met}

    # the labelled skip and the unlabelled same-company ad both rank above the APPLY ad; only the labelled one is in the A3 pairs
    p = {"a1": entry("Other"), role_skip: entry("Product Manager"), other_same_company: entry("Product Manager")}
    out = bars.b5(p, ads, {"apply": ["a1"], "fitSkip": [role_skip]}, Industries(), None)["v0"]["a3Split"]["roleOrRequirementSkips"]
    assert out["pairs"] == 1 and out["inverted"] == 1 and out["skipsAboveApply"] == [role_skip]


def test_the_schema_is_named_for_the_provider():
    # OpenAI answered 400 "Missing required parameter: response_format.json_schema.name" (plan Amendment A4): the wrapper needs a name and the schema.
    assert fit3.SCHEMA["name"] and fit3.SCHEMA["schema"]["type"] == "object"
    assert fit3.SCHEMA["schema"]["required"] == ["function", "title", "competencies"]
