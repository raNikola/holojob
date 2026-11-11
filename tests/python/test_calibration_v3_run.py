"""The slice 3 runner on a fictional profile and ads, with the model replaced. No real data, no network."""

import json
from types import SimpleNamespace

import pytest

from calibration import matcher_v3 as v3
from calibration import v3_run as run3
from conftest import select_provider
from llm_client import LlmUnavailable

PROFILE = {"basicProfile": {"fullName": "Zorana Testovic", "email": "zorana.testovic@example.test", "phone": "+381 64 123 4567"},
           "resume": {"parsedData": {"links": ["https://zorana.example/me"], "experienceDetail": [
               {"title": "Analyst", "company": "Initech", "start": "2018-01", "end": "2022-06", "bullets": ["Built dashboards for the finance team", "Holds a licence for inland waters only", "Reach Zorana Testovic at zorana.testovic@example.test"]}],
               "skills": ["SQL"], "education": [], "certifications": [], "projects": []}}}
INTELLIGENCE = {"candidateSummary": {"seniorityLevel": "Senior"}, "roleStrategy": {"primaryTargetRoles": ["Analyst"]}, "languages": ["English"]}
GATES = {g: {"quote": None} for g in v3.GATES}
MODES = run3.MODES


def stage(tmp_path):
    out = tmp_path / "stage-a"
    out.mkdir()
    review, facts, engine, ads, lines, items = [], {}, {}, {}, {}, []
    for i in range(4):
        job, mode = f"ad{i}", MODES[i % 2]
        reqs = [{"id": f"{job}-r{n}", "text": f"Requirement {n}", "kind": "skill", "importance": "must", "postingQuote": f"Quote number {n}"} for n in range(3)]
        review.append({"jobId": job, "title": "T", "company": "C", "description": " ".join(f"Quote number {n}." for n in range(3)) + f" Mail hr{i}@third-party.test."})
        facts[job] = {"requirements": reqs}
        engine[job] = {"mode": mode, "gates": [{"gate": g, "result": "pass"} for g in v3.GATES], "output": {"requirements": [{**r, "status": s, "strength": 2, "quoteVerified": s == "PARTIAL"} for r, s in zip(reqs, ("PARTIAL", "MISSING", "UNKNOWN"))]}}
        ads[job] = {"split": "dev", "overall": i}
        lines[f"i{i}0"] = {"jobId": job, "mode": mode, "probe": False, "split": "dev", "first": {"isMust": "yes", "meets": "no"}}
        items.append({"itemId": f"i{i}0", "reqId": f"{job}-r1"})
    ads["ad-test"] = {"split": "test", "overall": 1}
    (out / "review-items.json").write_text(json.dumps({"items": review}))
    (out / "enrichment-facts.json").write_text(json.dumps({"facts": facts}))
    (out / "engine-shadow.json").write_text(json.dumps({"ads": engine}))
    sample = {"items": items}
    (out / "must-sample.json").write_text(json.dumps(sample))
    return out, {"ads": ads, "lines": lines}, sample


def entry(ref, status, evidence_id=None, quote=None, strength=0):
    return {"ref": ref, "status": status, "evidence_id": evidence_id, "evidence_quote": quote, "strength": strength, "requirement_level": None, "requirement_level_quote": None, "candidate_level": None}


class Model:
    """Reading-aware: answers from a function of (call number, prompt)."""

    def __init__(self, fail_on=None, reply=None):
        self.prompts, self.fail_on, self.reply = [], fail_on, reply

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.prompts.append(prompt)
        assert schema is v3.SCHEMA
        if self.fail_on == len(self.prompts):
            raise LlmUnavailable("down")
        if self.reply is not None:
            return self.reply
        return {"matches": [entry("r1", "NOT_EVIDENCED"), entry("r2", "NOT_EVIDENCED"), entry("r3", "NOT_EVIDENCED")], "gates": GATES}


@pytest.fixture
def ready(tmp_path, monkeypatch):
    select_provider(tmp_path, monkeypatch, "openai", "gpt-6-luna", reasoningEffort="low")
    monkeypatch.setattr(run3.off, "load_confirmed_facts", lambda: [])
    monkeypatch.setattr(run3, "preflight", lambda *a, **k: SimpleNamespace(allowed=True, reason=None, row={}))
    return stage(tmp_path)


def test_run_without_yes_sends_nothing(capsys):
    assert run3.main(["run"]) == 0
    assert "nothing sent" in capsys.readouterr().out


def test_two_identical_readings_for_each_dev_ad_are_stored_with_mode_600_and_a_rerun_asks_for_nothing(ready):
    out, frozen, _ = ready
    model = Model()
    result = run3.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=model)
    assert result == {"stopped": None, "asked": 8, "ok": 8, "failed": 0, "refused": 0, "modelCalls": 8, "retries": 0}
    assert model.prompts[:4] == model.prompts[4:]  # reading 1 complete before reading 2, the same text and order
    assert oct((out / run3.RESULTS_NAME).stat().st_mode & 0o777) == "0o600"
    assert run3.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=Model())["asked"] == 0


def test_a_stopped_run_resumes_with_only_the_missing_calls(ready):
    out, frozen, _ = ready
    first = run3.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=Model(fail_on=3))
    assert "provider" in first["stopped"] and first["ok"] == 2
    again = Model()
    assert run3.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=again)["asked"] == 6 and len(again.prompts) == 6


def test_any_error_stops_the_batch_at_once(ready):
    out, frozen, _ = ready
    model = Model(fail_on=2)
    result = run3.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=model)
    assert len(model.prompts) == 2 and result["failed"] == 1 and result["refused"] == 6


def test_a_malformed_reply_is_retried_once_counted_and_then_stops(ready):
    out, frozen, _ = ready
    result = run3.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=Model(reply={"not": "the schema"}))
    assert result["failed"] == 1 and result["modelCalls"] == 2 and result["retries"] == 1 and "after one retry" in result["stopped"]


def test_nothing_is_sent_on_a_scan_hit_an_estimate_over_the_cap_a_gate_refusal_or_another_effort(ready, tmp_path, monkeypatch):
    out, frozen, _ = ready
    model = Model()
    monkeypatch.setattr(run3, "HARD_STOP_USD", 1e-9)
    assert "hard maximum" in run3.run(out, PROFILE, INTELLIGENCE, frozen, complete=model)["stopped"]
    monkeypatch.setattr(run3, "HARD_STOP_USD", 0.15)
    monkeypatch.setattr(run3, "preflight", lambda *a, **k: SimpleNamespace(allowed=False, reason="daily budget", row={}))
    monkeypatch.setattr(run3.ai_gate, "record_refused", lambda *a, **k: None)
    assert "AI gate refused" in run3.run(out, PROFILE, INTELLIGENCE, frozen, complete=model)["stopped"]
    select_provider(tmp_path, monkeypatch, "openai", "gpt-6-luna", reasoningEffort="medium")
    assert "not low" in run3.run(out, PROFILE, INTELLIGENCE, frozen, complete=model)["stopped"]
    doc = json.loads((out / "review-items.json").read_text())
    doc["items"][0]["description"] += " Ask Zorana Testovic."
    (out / "review-items.json").write_text(json.dumps(doc))
    assert "privacy scan" in run3.run(out, PROFILE, INTELLIGENCE, frozen, complete=model)["stopped"]
    assert model.prompts == []


def test_the_exact_text_is_scanned_again_before_it_leaves(ready, monkeypatch):
    out, frozen, _ = ready
    real_build, real_leaks, state = run3.off.build_requests, run3.off.owner_leaks, {"live": False}

    def build_then_live(*a, **k):
        built = real_build(*a, **k)
        state["live"] = True
        return built

    monkeypatch.setattr(run3.off, "build_requests", build_then_live)
    monkeypatch.setattr(run3.off, "owner_leaks", lambda t, p: ["a name"] if state["live"] else real_leaks(t, p))
    model = Model()
    assert "privacy scan" in run3.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=model)["stopped"] and model.prompts == []


def test_the_cap_guard_stops_the_batch_when_real_spend_leaves_no_room(ready, monkeypatch):
    out, frozen, _ = ready
    monkeypatch.setattr(run3.mc.SpendGuard, "actual", lambda self: 0.149)
    model = Model()
    result = run3.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=model)
    assert "cap" in result["stopped"] and model.prompts == []


def test_the_raw_proposal_is_kept_next_to_the_verified_status(ready):
    out, frozen, _ = ready
    run3.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=Model(reply={"matches": [entry("r1", "CONTRADICTED", "ev-none", "no such quote"), entry("r2", "NOT_EVIDENCED"), entry("r3", "NOT_EVIDENCED")], "gates": GATES}))
    calls = json.loads((out / run3.RESULTS_NAME).read_text())["calls"]
    line = calls["1|ad0"]["requirements"]["ad0-r0"]
    assert line["rawStatus"] == "CONTRADICTED" and line["status"] == "NOT_EVIDENCED"


# --- analysis ------------------------------------------------------------------------------------------


def line(status, raw=None, kind="skill"):
    return {"id": "x", "kind": kind, "importance": "must", "status": status, "rawStatus": raw or status, "strength": 2, "quoteVerified": status in v3.NEEDS_QUOTE, "requirementLevel": None, "candidateLevel": None}


def test_new_verdicts_use_the_levels_slice_1_was_measured_in():
    assert run3.as_statuses({"j": {"a": line("NOT_EVIDENCED"), "b": line("CONTRADICTED"), "c": line("PARTIAL")}}) == {"j": {"a": "UNKNOWN", "b": "MISSING", "c": "PARTIAL"}}


def test_transitions_show_where_the_old_partials_went_and_what_became_partial():
    old = {"j": {"a": "PARTIAL", "b": "PARTIAL", "c": "MISSING", "d": "MET"}}
    new = {"j": {"a": "PARTIAL", "b": "NOT_EVIDENCED", "c": "PARTIAL", "d": "MET"}}
    t = run3.transitions(old, new, ["j"])
    assert (t["n"], t["oldPartial"], t["newPartial"]) == (4, 2, 2)
    assert t["oldPartialBecame"] == {"NOT_EVIDENCED": 1, "PARTIAL": 1} and t["newPartialFrom"] == {"MISSING": 1, "PARTIAL": 1}


def test_stable_old_partials_are_only_lines_partial_in_both_old_readings():
    first, second = {"j": {"a": "PARTIAL", "b": "PARTIAL", "c": "MET"}}, {"j": {"a": "PARTIAL", "b": "MET", "c": "MET"}}
    s = run3.stable_old_partials(first, second, {"j": {"a": "MET", "b": "MET", "c": "MET"}}, {"j": {"a": "PARTIAL", "b": "MET", "c": "MET"}}, ["j"])
    assert s["n"] == 1 and s["newVerdicts"] == {"MET / PARTIAL": 1} and s["oldRepeatReference"] == {"stayed PARTIAL": 1, "left PARTIAL": 1}


def test_contradictions_are_counted_at_every_step_and_judged_against_the_owner():
    first = {"j": {"a": {**line("CONTRADICTED"), "id": "a"}, "b": {**line("CONTRADICTED"), "id": "b"}, "c": {**line("NOT_EVIDENCED", "CONTRADICTED"), "id": "c"}, "d": {**line("CONTRADICTED"), "id": "d"}}}
    second = {"j": {"a": {**line("CONTRADICTED"), "id": "a"}, "b": {**line("CONTRADICTED"), "id": "b"}, "c": {**line("NOT_EVIDENCED"), "id": "c"}, "d": {**line("NOT_EVIDENCED"), "id": "d"}}}
    merged = {"j": v3.aggregate_two(first["j"], second["j"])}
    c = run3.contradictions(first, second, merged, ["j"], [{"jobId": "j", "reqId": "a", "meets": "no"}, {"jobId": "j", "reqId": "b", "meets": "yes"}])
    assert (c["proposed"], c["verified"], c["finalBothReadings"], c["oneReadingOnly"]) == (6, 5, 2, 1)
    assert (c["finalOnLabelledLines"], c["ownerSaysRight (no)"], c["ownerSaysWrong (yes or partly)"], c["finalWithoutOwnerLabel"]) == (2, 1, 1, 0)


def test_the_joined_verdict_is_judged_against_the_owner_and_a_shared_error_is_not_flagged():
    merged = {"j": {"a": {"status": "NOT_EVIDENCED", "flagged": False}, "b": {"status": "PARTIAL", "flagged": True}, "c": {"status": "MET", "flagged": False}}}
    lines = [{"jobId": "j", "reqId": "a", "meets": "yes"}, {"jobId": "j", "reqId": "b", "meets": "no"}, {"jobId": "j", "reqId": "c", "meets": "yes"}]
    a = run3.against_merged(merged, lines)
    assert (a["n"], a["sameLevel"], a["understated"], a["overstated"], a["wrong"], a["wrongFlagged"], a["ranNoButCredited"]) == (3, 1, 1, 1, 2, 1, 1)


def test_the_analysis_keeps_the_modes_apart_and_prints_no_text(ready):
    out, frozen, sample = ready
    run3.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=Model())
    report = run3.analyse(out, frozen, sample)
    assert set(report["modes"]) == set(MODES) and all(m["ads"] == 2 for m in report["modes"].values())
    assert report["modes"]["production_like"]["noise"]["n"] == 6 and report["modes"]["production_like"]["noise"]["changedLevel"] == 0
    assert report["modes"]["production_like"]["partialFromStep7ToReading1"]["oldPartialBecame"] == {"NOT_EVIDENCED": 2}
    text = "\n".join(run3.render_analysis(report))
    assert "DIAGNOSTIC ONLY" in text and "CAVEAT" in text and "Requirement" not in text and "Quote number" not in text and "pooled" not in text.lower()
