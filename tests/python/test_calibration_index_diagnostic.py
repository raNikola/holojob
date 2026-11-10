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


# --- the paid run, with the model replaced --------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from conftest import select_provider  # noqa: E402
from llm_client import LlmUnavailable  # noqa: E402


class Model:
    def __init__(self, reply=None):
        self.prompts, self.reply = [], reply

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.prompts.append(prompt)
        if self.reply is not None:
            return self.reply
        n = prompt.split("BEGIN REQUIREMENTS")[1].split("END REQUIREMENTS")[0].count('"ref"')
        return {"matches": [{"ref": f"r{i}", "status": "UNKNOWN", "evidence_id": None, "evidence_quote": None, "strength": 0} for i in range(1, n + 1)],
                "gates": {g: {"quote": None} for g in ("work_authorization", "location", "language", "salary_floor", "role_family")}}


FROZEN = {"lines": {"i01": {"probe": False, "first": {"isMust": "yes", "meets": "yes"}, "mode": "production_like"},
                    "i02": {"probe": False, "first": {"isMust": "yes", "meets": "partial"}, "mode": "diagnostic"}}}
SAMPLE = {"items": [{"itemId": "i01", "jobId": "ad1", "reqId": "r1a", "kind": "experience", "verdict": {"status": "MISSING"}},
                    {"itemId": "i02", "jobId": "ad2", "reqId": "r2a", "kind": "experience", "verdict": {"status": "UNKNOWN"}}]}


@pytest.fixture
def stage_ready(tmp_path, monkeypatch):
    select_provider(tmp_path, monkeypatch, "openai", "gpt-6-luna")
    monkeypatch.setattr(dx, "load_confirmed_facts", lambda: [])
    monkeypatch.setattr(dx, "preflight", lambda *a, **k: SimpleNamespace(allowed=True, reason=None, row={}))
    out = tmp_path / "stage-a"
    out.mkdir()
    stage(out)
    return out


def test_run_without_yes_sends_nothing_and_does_not_even_read_the_profile(capsys):
    assert dx.main(["run"]) == 0
    assert "nothing sent" in capsys.readouterr().out


def test_two_variants_one_call_per_ad_results_stored_with_mode_600_and_a_rerun_asks_for_nothing(stage_ready):
    model = Model()
    result = dx.run(stage_ready, PROFILE, INTELLIGENCE, FROZEN, SAMPLE, workers=1, complete=model)
    assert result == {"stopped": None, "asked": 4, "ok": 4, "failed": 0, "refused": 0, "modelCalls": 4, "retries": 0}
    stored = json.loads((stage_ready / dx.RESULTS_NAME).read_text())["variants"]
    assert set(stored) == set(dx.VARIANTS) and all(set(v) == {"ad1", "ad2"} for v in stored.values())
    assert oct((stage_ready / dx.RESULTS_NAME).stat().st_mode & 0o777) == "0o600"
    summary_prompts = [p for p in model.prompts if "billing platform migration" in p]
    assert len(summary_prompts) == 2  # only the summary variant carries the summary
    assert dx.run(stage_ready, PROFILE, INTELLIGENCE, FROZEN, SAMPLE, workers=1, complete=Model())["asked"] == 0


def test_questionnaire_answers_are_in_neither_variant(stage_ready):
    model = Model()
    dx.run(stage_ready, PROFILE, INTELLIGENCE, FROZEN, SAMPLE, workers=1, complete=model)
    assert all("warehouse relocation" not in p for p in model.prompts)


def test_a_name_in_an_ad_stops_the_whole_run_before_any_call(stage_ready):
    ads = json.loads((stage_ready / "review-items.json").read_text())
    ads["items"][0]["description"] += " Ask Zorana Testovic."
    (stage_ready / "review-items.json").write_text(json.dumps(ads))
    model = Model()
    result = dx.run(stage_ready, PROFILE, INTELLIGENCE, FROZEN, SAMPLE, workers=1, complete=model)
    assert "privacy scan" in result["stopped"] and model.prompts == []
    assert not (stage_ready / dx.RESULTS_NAME).exists()


def test_an_estimate_over_the_cap_and_a_gate_refusal_send_nothing(stage_ready, monkeypatch):
    model = Model()
    monkeypatch.setattr(dx, "HARD_STOP_USD", 1e-9)
    assert "hard maximum" in dx.run(stage_ready, PROFILE, INTELLIGENCE, FROZEN, SAMPLE, complete=model)["stopped"]
    monkeypatch.setattr(dx, "HARD_STOP_USD", 0.05)
    monkeypatch.setattr(dx, "preflight", lambda *a, **k: SimpleNamespace(allowed=False, reason="daily budget", row={}))
    monkeypatch.setattr(dx.ai_gate, "record_refused", lambda *a, **k: None)
    assert "AI gate refused" in dx.run(stage_ready, PROFILE, INTELLIGENCE, FROZEN, SAMPLE, complete=model)["stopped"]
    assert model.prompts == []


def test_matcher_retries_count_against_the_cap_and_stop_the_batch(stage_ready, monkeypatch):
    estimate = dx.plan_cost = None  # noqa: F841 (the estimate is read from a dry run below)
    dry = dx.build_requests(stage_ready, PROFILE, INTELLIGENCE, [], {"ad1": {"r1a"}, "ad2": {"r2a"}})
    one = dx.price_and_budget(dry["prompts"], dry["asked"])["costUsd"]
    monkeypatch.setattr(dx, "HARD_STOP_USD", one * 2 * 1.2)  # the estimate for both variants passes; a retry on every call would not
    bad = Model(reply={"not": "the schema"})  # malformed: the matcher asks again
    result = dx.run(stage_ready, PROFILE, INTELLIGENCE, FROZEN, SAMPLE, workers=1, complete=bad)
    assert result["stopped"] and "cap" in result["stopped"] and result["modelCalls"] < 8


# --- reading the result ------------------------------------------------------------------------------------------


def stored(control, summary, cited=()):
    def entry(status, evidence=None):
        return {"requirements": [{"id": "r1a", "status": status, "evidenceId": evidence}], "extraEvidenceIds": ["ev-sum"]}
    return {"variants": {dx.VARIANTS[0]: {"ad1": entry(control)}, dx.VARIANTS[1]: {"ad1": entry(summary, "ev-sum" if cited else None)}}}


@pytest.mark.parametrize("step7, control, summary, expect_noise, expect_summary", [
    ("MISSING", "MISSING", "PARTIAL", "unchanged", "toward"),   # ran yes -> target MET: PARTIAL is nearer than MISSING
    ("MISSING", "PARTIAL", "MET", "toward", "toward"),
    ("PARTIAL", "PARTIAL", "MISSING", "unchanged", "away"),
    ("MISSING", "UNKNOWN", "MISSING", "sideways", "sideways"),  # silence and absence rank together: no nearer, no farther
])
def test_movement_toward_or_away_from_rans_answer(tmp_path, step7, control, summary, expect_noise, expect_summary):
    frozen = {"lines": {"i01": {"probe": False, "first": {"isMust": "yes", "meets": "yes"}, "mode": "production_like"}}}
    sample = {"items": [{"itemId": "i01", "jobId": "ad1", "reqId": "r1a", "kind": "skill", "verdict": {"status": step7}}]}
    (tmp_path / dx.RESULTS_NAME).write_text(json.dumps(stored(control, summary, cited=True)))
    g = dx.analyse(tmp_path, frozen, sample)["groups"]["all 17"]
    noise = g["step7 vs control (same evidence, same ad; only the other requirements differ)"]
    change = g["control vs summary (what the summary changes)"]
    assert noise[expect_noise] == 1 and change[expect_summary] == 1 and noise["n"] == change["n"] == 1


def test_the_analysis_splits_the_two_groups_cites_the_summary_and_prints_no_text(tmp_path):
    (tmp_path / dx.RESULTS_NAME).write_text(json.dumps(stored("MISSING", "MET", cited=True)))
    report = dx.analyse(tmp_path, FROZEN, SAMPLE)
    assert report["lines"] == 2 and report["summaryCitedByAnsweredLines"] == 1  # ad2 has no stored result: not run
    assert report["notRun"] == 1 and set(report["groups"]) == {"all 17", *dx.GROUPS}
    text = "\n".join(dx.render_analysis(report))
    assert "does NOT measure" in text and "billing" not in text and "SECRET" not in text
