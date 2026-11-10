"""The matcher cause-test runner on a fictional profile and ads, with the model replaced. No real data, no network."""

import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import ai_gate
import llm_client
from calibration import matcher_cause_test as mc
from conftest import select_provider
from llm_client import LlmUnavailable

PROFILE = {
    "basicProfile": {"fullName": "Zorana Testovic", "email": "zorana.testovic@example.test", "phone": "+381 64 123 4567"},
    "resume": {"parsedData": {
        "links": ["https://zorana.example/me"],
        "experienceDetail": [{"title": "Analyst", "company": "Initech", "start": "2018-01", "end": "2022-06",
                              "bullets": ["Built dashboards for the finance team", "Negotiated renewals with logistics suppliers", "Reach Zorana Testovic at zorana.testovic@example.test"]}],
        "skills": ["SQL", "Forecasting"], "education": ["BSc Economics"], "certifications": [], "projects": [],
    }},
}
INTELLIGENCE = {"candidateSummary": {"seniorityLevel": "Senior"}, "roleStrategy": {"primaryTargetRoles": ["Analyst"]}, "languages": ["English"]}
GATES = ("work_authorization", "location", "language", "salary_floor", "role_family")


def req(job, n):
    return {"id": f"{job}-r{n}", "text": f"Requirement {n}", "kind": "skill", "importance": "must", "postingQuote": f"Quote number {n}"}


def stage(tmp_path, reqs_per_ad=8):
    """8 ads: dev ad0-ad5 (3 per mode), test ad6-ad7."""
    out = tmp_path / "stage-a"
    out.mkdir()
    ads, facts, engine, frozen_ads, lines = [], {}, {}, {}, {}
    k = 0
    for i in range(8):
        job, mode = f"ad{i}", mc.MODES[i % 2]
        reqs = [req(job, n) for n in range(reqs_per_ad)]
        quotes = " ".join(f"Quote number {n}." for n in range(reqs_per_ad))
        ads.append({"jobId": job, "title": f"T{i}", "company": "C", "description": f"{quotes} Mail hr{i}@third-party.test."})
        facts[job] = {"requirements": reqs}
        engine[job] = {"mode": mode, "output": {"requirements": [{**r, "status": "MISSING"} for r in reqs]}}
        frozen_ads[job] = {"split": "dev" if i < 6 else "test", "overall": 1}
        for n in range(2):
            k += 1
            lines[f"i{k:02d}"] = {"jobId": job, "mode": mode, "probe": False, "split": frozen_ads[job]["split"], "first": {"isMust": "yes", "meets": ("yes", "no")[n]}}
    sample = {"items": [{"itemId": item_id, "reqId": f"{line['jobId']}-r{int(item_id[1:]) % 2}"} for item_id, line in lines.items()]}
    (out / "review-items.json").write_text(json.dumps({"items": ads}))
    (out / "enrichment-facts.json").write_text(json.dumps({"facts": facts}))
    (out / "engine-shadow.json").write_text(json.dumps({"ads": engine}))
    (out / "must-sample.json").write_text(json.dumps(sample))
    return out, {"ads": frozen_ads, "lines": lines}, sample


class Model:
    """Answers UNKNOWN to everything and records what it was asked and at which reasoning effort."""

    def __init__(self, fail_on=None, reply=None):
        self.prompts, self.efforts, self.fail_on, self.reply = [], [], fail_on, reply

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.prompts.append(prompt)
        self.efforts.append(llm_client.reasoning_options(model).get("reasoning_effort"))
        if self.fail_on and len(self.prompts) == self.fail_on:
            raise LlmUnavailable("provider down")
        if self.reply is not None:
            return self.reply
        return {"matches": [{"ref": f"r{i}", "status": "UNKNOWN", "evidence_id": None, "evidence_quote": None, "strength": 0} for i in range(1, mc._asked(prompt) + 1)],
                "gates": {g: {"quote": None} for g in GATES}}


@pytest.fixture
def ready(tmp_path, monkeypatch):
    select_provider(tmp_path, monkeypatch, "openai", "gpt-6-luna", reasoningEffort="low")
    monkeypatch.setattr(mc, "load_confirmed_facts", lambda: [])
    monkeypatch.setattr(mc, "preflight", lambda *a, **k: SimpleNamespace(allowed=True, reason=None, row={}))
    return stage(tmp_path)


# --- selection and the requests --------------------------------------------------------------------


def test_the_selection_takes_dev_ads_only_per_mode_most_labelled_first_and_is_stable(ready):
    out, frozen, _ = ready
    engine = json.loads((out / "engine-shadow.json").read_text())["ads"]
    chosen = mc.select_ads(frozen, engine)
    assert set(chosen) == {f"ad{i}" for i in range(6)} and sorted(chosen.values()).count("diagnostic") == 3
    assert mc.select_ads(frozen, engine) == chosen


def test_each_arm_is_built_as_specified_and_nothing_personal_is_in_a_request(ready):
    out, frozen, _ = ready
    built = mc.build_calls(out, PROFILE, INTELLIGENCE, {"ad0": "production_like"})
    by_arm = {}
    for c in built["calls"]:
        by_arm.setdefault(c["arm"], []).append(c)
    assert {a: len(v) for a, v in by_arm.items()} == {"full_1": 1, "full_2": 1, "medium": 1, "shuffled": 1, "batched": 2}
    assert by_arm["full_1"][0]["prompt"] == by_arm["full_2"][0]["prompt"] == by_arm["medium"][0]["prompt"]
    assert by_arm["full_1"][0]["asked"] == 8 and by_arm["shuffled"][0]["asked"] == 8
    assert [c["asked"] for c in by_arm["batched"]] == [6, 2]  # at most 6 per call, in the original order
    ids = [r["id"] for c in by_arm["batched"] for r in c["posting"]["facts"]["requirements"]]
    assert ids == [r["id"] for r in by_arm["full_1"][0]["posting"]["facts"]["requirements"]]
    shuffled = by_arm["shuffled"][0]
    assert sorted(r["id"] for r in shuffled["posting"]["facts"]["requirements"]) == sorted(ids) and [r["id"] for r in shuffled["posting"]["facts"]["requirements"]] != ids
    assert [e["id"] for e in shuffled["candidate"]["evidence"]] != [e["id"] for e in by_arm["full_1"][0]["candidate"]["evidence"]] or len(shuffled["candidate"]["evidence"]) < 3
    assert built["leaks"] == {}
    for c in built["calls"]:
        for secret in ("Zorana", "Testovic", "zorana.testovic@example.test", "third-party.test"):
            assert secret not in c["prompt"]


def test_the_shuffle_is_the_same_on_every_build_so_a_resume_matches(ready):
    out, _, _ = ready
    first = mc.build_calls(out, PROFILE, INTELLIGENCE, {"ad0": "production_like"})["calls"]
    second = mc.build_calls(out, PROFILE, INTELLIGENCE, {"ad0": "production_like"})["calls"]
    assert [c["hash"] for c in first] == [c["hash"] for c in second]


def test_the_upper_bound_is_above_the_expected_cost_and_the_medium_arm_reserves_more_output(ready):
    out, _, _ = ready
    built = mc.build_calls(out, PROFILE, INTELLIGENCE, {"ad0": "production_like"})
    est = mc.estimate(built["calls"], {"known": True, "in": 0.1, "out": 0.5})
    assert est["upperBound"] >= est["expected"] and est["calls"] == 6
    assert est["arms"]["medium"]["output"] == est["arms"]["full_1"]["output"] * mc.MEDIUM_OUTPUT_FACTOR


# --- the run ---------------------------------------------------------------------------------------


def test_run_without_yes_sends_nothing(capsys):
    assert mc.main(["run"]) == 0
    assert "nothing sent" in capsys.readouterr().out


def test_a_full_run_stores_every_call_with_mode_600_and_a_rerun_asks_for_nothing(ready):
    out, frozen, _ = ready
    model = Model()
    result = mc.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=model)
    assert result["stopped"] is None and result["ok"] == result["asked"] == result["modelCalls"] == 6 * 6 and result["retries"] == 0
    assert oct((out / mc.RESULTS_NAME).stat().st_mode & 0o777) == "0o600"
    assert mc.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=Model())["asked"] == 0


def test_a_stopped_run_resumes_with_only_the_missing_calls(ready):
    out, frozen, _ = ready
    first = mc.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=Model(fail_on=4))
    assert first["stopped"] and first["ok"] == 3 and first["failed"] == 1
    again = Model()
    assert mc.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=again)["asked"] == 33 and len(again.prompts) == 33


def test_only_the_medium_arm_runs_at_medium_effort_and_the_setting_is_restored(ready):
    out, frozen, _ = ready
    before = os.environ["HOLOJOB_AI_SELECTION"]
    model = Model()
    mc.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=model)
    assert model.efforts.count("medium") == 6 and model.efforts.count("low") == 30
    assert model.efforts[-6:] == ["medium"] * 6 and os.environ["HOLOJOB_AI_SELECTION"] == before


def test_any_error_stops_the_batch_at_once(ready):
    out, frozen, _ = ready
    model = Model(fail_on=2)
    result = mc.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=model)
    assert "failed" in result["stopped"] and len(model.prompts) == 2 and result["refused"] == 36 - 2


def test_a_name_in_an_ad_stops_everything_before_any_call(ready):
    out, frozen, _ = ready
    ads = json.loads((out / "review-items.json").read_text())
    ads["items"][0]["description"] += " Ask Zorana Testovic."
    (out / "review-items.json").write_text(json.dumps(ads))
    model = Model()
    assert "privacy scan" in mc.run(out, PROFILE, INTELLIGENCE, frozen, complete=model)["stopped"] and model.prompts == []
    assert not (out / mc.RESULTS_NAME).exists()


def test_the_exact_text_is_scanned_again_before_it_leaves(ready, monkeypatch):
    out, frozen, _ = ready
    real, real_build = mc.owner_leaks, mc.build_calls
    state = {"live": False}

    def build_then_live(*a, **k):
        built = real_build(*a, **k)
        state["live"] = True
        return built

    monkeypatch.setattr(mc, "build_calls", build_then_live)
    monkeypatch.setattr(mc, "owner_leaks", lambda t, p: ["a name"] if state["live"] else real(t, p))
    model = Model()
    result = mc.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=model)
    assert "privacy scan" in result["stopped"] and model.prompts == []


def test_an_estimate_over_the_cap_and_a_gate_refusal_send_nothing(ready, monkeypatch):
    out, frozen, _ = ready
    model = Model()
    monkeypatch.setattr(mc, "HARD_STOP_USD", 1e-9)
    assert "hard maximum" in mc.run(out, PROFILE, INTELLIGENCE, frozen, complete=model)["stopped"]
    monkeypatch.setattr(mc, "HARD_STOP_USD", 0.2)
    monkeypatch.setattr(mc, "preflight", lambda *a, **k: SimpleNamespace(allowed=False, reason="daily budget", row={}))
    monkeypatch.setattr(mc.ai_gate, "record_refused", lambda *a, **k: None)
    assert "AI gate refused" in mc.run(out, PROFILE, INTELLIGENCE, frozen, complete=model)["stopped"]
    assert model.prompts == []


def test_a_malformed_reply_is_retried_once_and_the_retry_is_counted(ready):
    out, frozen, _ = ready
    result = mc.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=Model(reply={"not": "the schema"}))
    assert result["failed"] == 1 and result["modelCalls"] == 2 and result["retries"] == 1  # stopped after the first failed call


# --- the spend guard ----------------------------------------------------------------------------------


PRICE = {"in": 0.1, "out": 0.5}
START = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def write_ledger(rows):
    ai_gate.ledger_path().parent.mkdir(parents=True, exist_ok=True)
    ai_gate.ledger_path().write_text("".join(json.dumps(r) + "\n" for r in rows))


def call_row(i, minutes, feature=mc.FEATURE, decision="allowed", cost=0.05):
    return {"type": "call", "id": i, "feature": feature, "decision": decision, "ts": (START + timedelta(minutes=minutes)).isoformat(), "cost": cost}


def test_the_guard_counts_only_this_batchs_real_cost_and_an_unfinished_earlier_call_at_its_estimate():
    write_ledger([call_row("old", -5), {"type": "result", "id": "old", "cost": 9.0},
                  call_row("other", 1, feature="enrichment"), {"type": "result", "id": "other", "cost": 9.0},
                  call_row("refused", 1, decision="refused"),
                  call_row("done", 2), {"type": "result", "id": "done", "cost": 0.01},
                  call_row("orphan", 3)])
    guard = mc.SpendGuard(0.2, START, PRICE, 8000)
    guard.process_started = START + timedelta(hours=1)  # the orphan call belongs to an earlier process
    assert guard.actual() == pytest.approx(0.06)
    guard.process_started = START  # the same call in this process is in flight, and already reserved
    assert guard.actual() == pytest.approx(0.01)


def test_the_guard_reserves_the_true_worst_case_and_releases_it():
    write_ledger([])
    guard = mc.SpendGuard(0.0045, START, PRICE, 8000)  # one call's worst case: 8000 output tokens = $0.004
    worst = guard.reserve("x" * 3000)
    assert worst == pytest.approx(0.0041) and guard.calls == 1
    with pytest.raises(mc.GuardrailRefused, match="cap"):
        guard.reserve("x" * 3000)  # the first is still in flight
    guard.release(worst)
    assert guard.reserve("x" * 3000) == pytest.approx(worst)


def test_the_guard_refuses_once_real_spend_leaves_no_room():
    write_ledger([call_row("a", 1), {"type": "result", "id": "a", "cost": 0.198}])
    with pytest.raises(mc.GuardrailRefused):
        mc.SpendGuard(0.2, START, PRICE, 8000).reserve("x" * 3000)


# --- reading the result ------------------------------------------------------------------------------


def test_compare_counts_levels_direction_and_treats_missing_and_unknown_as_one_level():
    a = {"j": {"r1": "MISSING", "r2": "PARTIAL", "r3": "MET", "r4": "MISSING"}}
    b = {"j": {"r1": "UNKNOWN", "r2": "MET", "r3": "PARTIAL", "r4": "MISSING"}}
    c = mc.compare(a, b, ["j"])
    assert (c["n"], c["changedLevel"], c["up"], c["down"], c["statusDiffers"], c["adsWithChange"]) == (4, 2, 1, 1, 3, 1)


@pytest.mark.parametrize("a, b, final, flagged", [
    ("MET", "MET", "MET", False), ("MISSING", "UNKNOWN", "MISSING", False), ("UNKNOWN", "UNKNOWN", "UNKNOWN", False),
    ("MET", "PARTIAL", "PARTIAL", True), ("PARTIAL", "MET", "PARTIAL", True),
    ("PARTIAL", "MISSING", "UNKNOWN", True), ("UNKNOWN", "MET", "UNKNOWN", True),
])
def test_two_readings_follow_the_accepted_rule(a, b, final, flagged):
    assert mc.aggregate(a, b) == (final, flagged)


def test_accuracy_counts_understated_overstated_and_credit_on_a_no():
    reading = {"j": {"r1": "MET", "r2": "MISSING", "r3": "PARTIAL", "r4": "MISSING"}}
    lines = [{"jobId": "j", "reqId": "r1", "meets": "yes"}, {"jobId": "j", "reqId": "r2", "meets": "yes"},
             {"jobId": "j", "reqId": "r3", "meets": "no"}, {"jobId": "j", "reqId": "r4", "meets": "no"}]
    a = mc.against_ran(reading, lines)
    assert (a["n"], a["exact"], a["understated"], a["overstated"], a["ranNoLines"], a["ranNoButCredited"]) == (4, 2, 1, 1, 2, 1)


def test_two_readings_report_how_much_is_flagged_and_whether_the_flag_finds_the_wrong_lines():
    a = {"j": {"r1": "MET", "r2": "MISSING", "r3": "MET"}}
    b = {"j": {"r1": "MET", "r2": "PARTIAL", "r3": "MET"}}
    lines = [{"jobId": "j", "reqId": "r2", "meets": "yes"}, {"jobId": "j", "reqId": "r3", "meets": "no"}]
    t = mc.two_readings(a, b, ["j"], lines)
    assert (t["requirements"], t["flagged"], t["labelled"], t["wrong"], t["wrongFlagged"]) == (3, 1, 2, 2, 1)  # r3 is agreed and wrong: agreement is not accuracy


def test_the_analysis_keeps_the_modes_apart_and_prints_no_text(ready):
    out, frozen, sample = ready
    mc.run(out, PROFILE, INTELLIGENCE, frozen, workers=1, complete=Model())
    report = mc.analyse(out, frozen, sample)
    assert set(report["modes"]) == set(mc.MODES) and all(m["ads"] == 3 for m in report["modes"].values())
    assert report["modes"]["production_like"]["comparisons"]["pure repeat: full_1 vs full_2 (same input twice)"]["n"] == 3 * 8
    text = "\n".join(mc.render_analysis(report))
    assert "DIAGNOSTIC ONLY" in text and "CAVEAT" in text and "Requirement" not in text and "Quote number" not in text and "pooled" not in text.lower()
