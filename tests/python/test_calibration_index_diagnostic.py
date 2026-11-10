"""The free evidence-index diagnostic on a fictional profile and ads. No real data, no model, nothing sent."""

import json

import pytest

from calibration import index_diagnostic as dx

PROFILE = {
    "basicProfile": {"fullName": "Zorana Testovic", "email": "zorana.testovic@example.test", "phone": "+381 64 123 4567"},
    "resume": {"parsedData": {
        "links": ["https://zorana.example/me"],
        "summary": "Led the billing platform migration for forty customers. Reach Zorana Testovic at zorana.testovic@example.test. Ran quarterly vendor audits.",
        "experienceDetail": [{"title": "Analyst", "company": "Initech", "start": "2018-01", "end": "2022-06",
                              "bullets": ["Built dashboards for the finance team", "Negotiated renewals with logistics suppliers"]}],
        "skills": ["SQL", "Forecasting"], "education": ["BSc Economics"], "certifications": [], "projects": [],
    }},
    "questionnaire": {"answers": [{"id": 1, "question": "Q", "answer": "I coordinated warehouse relocation planning."}]},
    "repositories": {"githubLinks": ["https://github.example/zorana"], "localRepoPaths": []},
    "cvLibrary": [{"id": "cv1"}],
}
INTELLIGENCE = {"candidateSummary": {"seniorityLevel": "Senior", "careerNarrative": "A narrative a model wrote.", "oneLinePitch": "", "positioningStatement": ""},
                "experienceMap": {"projectHighlights": [], "ownershipExamples": []}, "roleStrategy": {"primaryTargetRoles": ["Analyst"]}, "languages": ["English"]}


def evidence(*texts, source="role"):
    return [{"id": f"ev-{i}", "source": source, "role": None, "start": None, "end": None, "text": t} for i, t in enumerate(texts)]


# --- sources -------------------------------------------------------------------------------


def test_the_inventory_counts_each_source_and_what_is_in_the_index():
    ev = evidence("a", "b") + evidence("SQL", "BSc Economics", source="fact")
    rows = {r["source"]: r for r in dx.inventory(PROFILE, INTELLIGENCE, ev, [])}
    assert rows["work history (bullets)"]["entries"] == 2 and rows["work history (bullets)"]["inIndex"] == 2
    assert rows["summary text"]["entries"] == 3 and rows["summary text"]["inIndex"] == 0
    assert rows["projects (parsed or project highlights)"]["entries"] == 0
    assert rows["questionnaire answers"]["entries"] == 1 and "no per-answer confirmed flag" in rows["questionnaire answers"]["decision"]
    assert rows["GitHub"]["entries"] == 1 and "never a confirmation" in rows["GitHub"]["decision"]
    assert rows["derived intelligence text (narrative, pitch, positioning)"]["entries"] == 1


def test_the_source_listing_prints_counts_and_no_text():
    ev = evidence("Built dashboards for the finance team")
    text = "\n".join(dx.render_sources(dx.inventory(PROFILE, INTELLIGENCE, ev, []), ev))
    assert "dashboards" not in text and "Zorana" not in text and "billing" not in text


# --- classification -----------------------------------------------------------------------------


def toks(*words):
    return set(words)


def test_class_b_needs_two_shared_distinctive_words_and_half_of_the_requirement_inside_one_indexed_item():
    index = [toks("warehouse", "planning", "relocation"), toks("budget")]
    assert dx.classify_line(toks("warehouse", "relocation"), index, [], "yes") == ("b", "index")
    assert dx.classify_line(toks("warehouse", "forecasting", "logistics", "tendering"), index, [], "yes")[0] != "b"  # 1 of 4 words


def test_class_a_when_only_an_unindexed_source_holds_it_and_b_wins_when_the_index_also_does():
    other = [("summary", toks("billing", "platform", "migration"))]
    assert dx.classify_line(toks("billing", "migration"), [toks("budget")], other, "yes") == ("a", "summary")
    assert dx.classify_line(toks("billing", "migration"), [toks("billing", "migration")], other, "yes") == ("b", "index")


def test_class_c_only_for_a_partly_answer_with_one_shared_word_in_the_index():
    index = [toks("logistics", "suppliers")]
    assert dx.classify_line(toks("logistics", "tendering", "customs"), index, [], "partial") == ("c", "index")
    assert dx.classify_line(toks("logistics", "tendering", "customs"), index, [], "yes")[0] == "d"  # a full yes with weak overlap is not forced


def test_everything_else_stays_d_the_cannot_tell_class_and_an_empty_requirement_never_matches():
    assert dx.classify_line(toks("kubernetes", "terraform"), [toks("budget")], [("summary", toks("billing"))], "yes") == ("d", None)
    assert dx.classify_line(set(), [toks("anything")], [("summary", toks("anything"))], "yes") == ("d", None)


def test_words_common_to_many_profile_items_are_ignored_without_a_word_list():
    units = [toks("manage", "alpha"), toks("manage", "beta"), toks("manage", "gamma"), toks("manage", "delta"), toks("unique")]
    generic = dx.generic_words(units)
    assert "manage" in generic and "unique" not in generic and "alpha" not in generic
    assert dx.generic_words([toks("one"), toks("one")]) == set()  # two units are never enough to call a word common


def test_the_triage_picks_the_lines_the_engine_understated_and_prints_ids_only():
    frozen = {"lines": {
        "i01": {"probe": False, "first": {"isMust": "yes", "meets": "yes"}, "mode": "production_like"},
        "i02": {"probe": False, "first": {"isMust": "yes", "meets": "no"}, "mode": "production_like"},
        "i03": {"probe": True, "first": {"isMust": "yes", "meets": "yes"}, "mode": "diagnostic"},
        "i04": {"probe": False, "first": {"isMust": "nice", "meets": "yes"}, "mode": "production_like"},
        "i05": {"probe": False, "first": {"isMust": "yes", "meets": "partial"}, "mode": "diagnostic"}}}
    sample = {"items": [{"itemId": f"i0{n}", "kind": "skill", "text": "SECRET", "verdict": {"status": s}} for n, s in
                        ((1, "MISSING"), (2, "MISSING"), (3, "MISSING"), (4, "UNKNOWN"), (5, "UNKNOWN"))]}
    rows = dx.understated_lines(frozen, sample)
    assert [r["itemId"] for r in rows] == ["i01", "i05"]
    classified = dx.classify(PROFILE, INTELLIGENCE, evidence("Built dashboards"), [{**r, "item": {**r["item"], "text": "kubernetes terraform"}} for r in rows])
    text = "\n".join(dx.render_classes(classified))
    assert "SECRET" not in text and "kubernetes" not in text and "(d)" in text


# --- the proposed diagnostic ----------------------------------------------------------------------


def stage(tmp_path):
    ads, facts = [], {}
    for n in (1, 2):
        ads.append({"jobId": f"ad{n}", "title": f"T{n}", "company": "C", "description": f"Own the vendor audits {n}. Five years of forecasting. Write to hr{n}@third-party.test."})
        facts[f"ad{n}"] = {"requirements": [
            {"id": f"r{n}a", "text": "Vendor audit experience", "kind": "experience", "importance": "must", "postingQuote": "Own the vendor audits"},
            {"id": f"r{n}b", "text": "Forecasting", "kind": "skill", "importance": "must", "postingQuote": "Five years of forecasting"}]}
    (tmp_path / "review-items.json").write_text(json.dumps({"items": ads}))
    (tmp_path / "enrichment-facts.json").write_text(json.dumps({"facts": facts}))
    return tmp_path


def test_selection_takes_understated_musts_and_partial_where_ran_says_yes_only():
    frozen = {"lines": {f"i0{n}": {"probe": False, "first": {"isMust": "yes", "meets": m}} for n, m in ((1, "yes"), (2, "partial"), (3, "yes"), (4, "no"))}}
    sample = {"items": [{"itemId": f"i0{n}", "jobId": "ad1", "reqId": f"r{n}", "verdict": {"status": s}} for n, s in ((1, "PARTIAL"), (2, "PARTIAL"), (3, "MET"), (4, "MISSING"))]}
    assert dx.diagnostic_selection(frozen, sample) == {"ad1": {"r1"}}  # PARTIAL+yes only; PARTIAL+partly, MET and a true "no" are left out


def test_requests_hold_only_the_selected_requirements_the_redacted_summary_and_pass_the_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(dx, "load_confirmed_facts", lambda: [])
    out = stage(tmp_path)
    extra = dx.summary_items(PROFILE, dx.identity_of(PROFILE))
    r = dx.build_requests(out, PROFILE, INTELLIGENCE, extra, {"ad1": {"r1a"}, "ad2": {"r2a", "r2b"}})
    assert set(r["prompts"]) == {"ad1", "ad2"} and r["asked"] == {"ad1": 1, "ad2": 2} and r["leaks"] == {}
    p = r["prompts"]["ad1"]
    assert "Vendor audit experience" in p and "Forecasting" not in p.split("BEGIN REQUIREMENTS")[1].split("END REQUIREMENTS")[0]
    assert "billing platform migration" in p  # the summary reached the evidence
    for secret in ("Zorana", "Testovic", "zorana.testovic@example.test", "381 64 123", "third-party.test"):
        assert secret not in p


def test_a_name_left_in_an_ad_fails_the_scan_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(dx, "load_confirmed_facts", lambda: [])
    out = stage(tmp_path)
    ads = json.loads((out / "review-items.json").read_text())
    ads["items"][0]["description"] += " Ask Zorana Testovic."
    (out / "review-items.json").write_text(json.dumps(ads))
    r = dx.build_requests(out, PROFILE, INTELLIGENCE, [], {"ad1": {"r1a"}})
    assert r["leaks"] and "Zorana" not in json.dumps(r["leaks"])


def test_the_tool_has_no_way_to_call_a_model():
    source = open(dx.__file__, encoding="utf-8").read()
    assert "complete_json" not in source and "requests.post" not in source and "urlopen" not in source
    with pytest.raises(SystemExit):
        dx.main(["run"])  # no such command
