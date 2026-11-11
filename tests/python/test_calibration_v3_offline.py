"""Offline validation and the slice 3 dry run on fictional stored verdicts. No real data, no model."""

import json

import pytest

from calibration import aggregation_preview as ap
from calibration import matcher_v3 as v3
from calibration import v3_offline as off
from conftest import select_provider

GATES = [{"gate": g, "result": "pass", "quote": None} for g in v3.GATES]
SECTIONS = {"education": 1, "certification": 1, "language": 1}


def req(n, status, strength=3, kind="skill", importance="must"):
    return {"id": f"r{n}", "text": "SECRET TEXT", "kind": kind, "importance": importance, "status": status, "strength": strength, "quoteVerified": status in ("MET", "PARTIAL"), "postingQuote": f"Quote number {n}"}


MIX = [req(1, "MET"), req(2, "PARTIAL", 2), req(3, "PARTIAL", 1), req(4, "MISSING", 0), req(5, "UNKNOWN", 0)]


def test_stored_absence_and_unknown_are_both_silence_because_no_conflicting_quote_is_stored():
    assert [off.typed(r)["status"] for r in MIX] == ["MET", "PARTIAL", "PARTIAL", "NOT_EVIDENCED", "NOT_EVIDENCED"]


def test_demote_touches_only_partials_at_or_below_the_strength():
    assert [off.demote(r, 1, "X")["status"] for r in MIX] == ["MET", "PARTIAL", "X", "MISSING", "UNKNOWN"]
    assert [off.demote(r, None, "X")["status"] for r in MIX[:3]] == ["MET", "X", "X"]


def test_under_the_new_rules_a_stricter_partial_raises_fit_and_lowers_confidence():
    typed = [off.typed(r) for r in MIX]
    strict = [off.demote(r, 1, v3.NOT_EVIDENCED) for r in typed]
    assert ap.fit_of(strict, {}) > ap.fit_of(typed, {})  # a low-credit line leaves the denominator
    assert ap.confidence_of(strict, GATES, {}) < ap.confidence_of(typed, GATES, {})


def test_under_the_current_formula_a_stricter_partial_lowers_fit():
    assert off._current([off.demote(r, 1, "MISSING") for r in MIX]) < off._current(MIX)


def test_the_effect_reports_size_direction_labels_and_rank():
    e = off.effect({"a": 10, "b": 50, "c": 80, "d": None}, {"a": 20, "b": 40, "c": 80, "d": 5}, {"a": 0, "b": 1, "c": 3, "d": 2})
    assert (e["n"], e["up"], e["down"], e["same"], e["meanDelta"], e["minDelta"], e["maxDelta"]) == (3, 1, 1, 1, 0.0, -10, 10)
    assert e["labels"] == {"Weak": 1, "Partial": 1, "Strong": 1}
    assert off.effect({"a": 1}, {"a": None}, {"a": 0})["noEstimate"] == 1


def test_partials_at_risk_are_counted_overall_and_by_the_owners_answer():
    lines = [{"jobId": "a", "reqId": "r3", "meets": "no"}, {"jobId": "a", "reqId": "r2", "meets": "yes"}, {"jobId": "a", "reqId": "r1", "meets": "yes"}]
    p = off.partial_at_risk(MIX, lines, {"a": {r["id"]: r for r in MIX}})
    assert (p["partial"], p["partialStrength01"], p["partialStrengths"]) == (2, 1, {1: 1, 2: 1})
    assert p["labelledPartial"] == {"no": 1, "yes": 1} and p["labelledPartialStrength01"] == {"no": 1}


def stage(tmp_path):
    out = tmp_path / "stage-a"
    out.mkdir()
    engine, ads, lines, items, calls, review, facts, chosen, k = {}, {}, {}, [], {}, [], {}, {}, 0
    for i in range(6):
        job, mode = f"ad{i}", off.MODES[i % 2]
        reqs = [{**r, "id": f"{job}-{r['id']}"} for r in MIX]
        engine[job] = {"mode": mode, "gates": GATES, "confidence": 0.7, "output": {"requirements": reqs}}
        ads[job] = {"split": "dev", "overall": i % 4}
        chosen[job] = mode
        k += 1
        lines[f"i{k:02d}"] = {"jobId": job, "mode": mode, "probe": False, "split": "dev", "first": {"isMust": "yes", "meets": "yes"}}
        items.append({"itemId": f"i{k:02d}", "reqId": reqs[3]["id"]})
        second = [{**r, "status": "PARTIAL" if n == 3 else r["status"], "strength": 2 if n == 3 else r["strength"]} for n, r in enumerate(reqs)]
        calls[f"full_1|{job}|0"] = {"arm": "full_1", "jobId": job, "chunk": 0, "requirements": [{k2: r.get(k2) for k2 in ("id", "status", "strength", "quoteVerified", "evidenceId")} for r in reqs]}
        calls[f"full_2|{job}|0"] = {"arm": "full_2", "jobId": job, "chunk": 0, "requirements": [{k2: r.get(k2) for k2 in ("id", "status", "strength", "quoteVerified", "evidenceId")} for r in second]}
        review.append({"jobId": job, "title": "T", "company": "C", "description": " ".join(f"Quote number {n}." for n in range(1, 6)) + f" Mail hr{i}@third-party.test."})
        facts[job] = {"requirements": [{k2: r[k2] for k2 in ("text", "kind", "importance", "postingQuote")} | {"id": r["id"]} for r in reqs]}
    (out / "engine-shadow.json").write_text(json.dumps({"ads": engine}))
    (out / "matcher-cause-test.json").write_text(json.dumps({"ads": chosen, "calls": calls}))
    (out / "review-items.json").write_text(json.dumps({"items": review}))
    (out / "enrichment-facts.json").write_text(json.dumps({"facts": facts}))
    (out / "must-sample.json").write_text(json.dumps({"items": items}))
    return out, {"ads": ads, "lines": lines}, {"items": items}


def test_the_replay_keeps_the_modes_apart_and_scores_two_identical_readings(tmp_path):
    out, frozen, sample = stage(tmp_path)
    report = off.replay(out, frozen, sample, SECTIONS)
    assert set(report["modes"]) == set(off.MODES) and all(m["ads"] == 3 for m in report["modes"].values())
    t = report["twoReadings"]["production_like"]
    assert (t["ads"], t["requirements"], t["flagged"], t["reasons"]) == (3, 15, 3, {"positive against silence": 3})
    assert (t["shownInQueue"], t["overflow"], t["labelled"], t["wrong"], t["wrongFlaggedAnywhere"], t["wrongInQueue"]) == (3, 0, 3, 3, 3, 3)
    assert report["modes"]["production_like"]["confidence"]["strict bound"] <= report["modes"]["production_like"]["confidence"]["typed"]


def test_the_replay_prints_no_text_and_writes_nothing(tmp_path):
    out, frozen, sample = stage(tmp_path)
    before = sorted(p.name for p in out.iterdir())
    text = "\n".join(off.render_replay(off.replay(out, frozen, sample, SECTIONS)))
    assert "SECRET" not in text and "Quote number" not in text and "CAVEAT" in text and "DIAGNOSTIC ONLY" in text and "sensitivity bounds" in text
    assert sorted(p.name for p in out.iterdir()) == before


PROFILE = {"basicProfile": {"fullName": "Zorana Testovic", "email": "zorana.testovic@example.test", "phone": "+381 64 123 4567"},
           "resume": {"parsedData": {"links": ["https://zorana.example/me"], "experienceDetail": [
               {"title": "Analyst", "company": "Initech", "start": "2018-01", "end": "2022-06", "bullets": ["Built dashboards for finance", "Reach Zorana Testovic at zorana.testovic@example.test"]}],
               "skills": ["SQL"], "education": [], "certifications": [], "projects": []}}}
INTELLIGENCE = {"candidateSummary": {"seniorityLevel": "Senior"}, "roleStrategy": {"primaryTargetRoles": ["Analyst"]}, "languages": ["English"]}


def test_the_dry_run_builds_clean_requests_for_the_dev_ads_only(tmp_path, monkeypatch):
    monkeypatch.setattr(off, "load_confirmed_facts", lambda: [])
    out, frozen, _ = stage(tmp_path)
    frozen["ads"]["ad5"]["split"] = "test"
    chosen = off.dev_ads(frozen, json.loads((out / "engine-shadow.json").read_text())["ads"])
    assert "ad5" not in chosen and len(chosen) == 5
    built = off.build_requests(out, PROFILE, INTELLIGENCE, chosen)
    assert built["leaks"] == {} and set(built["requests"]) == set(chosen)
    for r in built["requests"].values():
        for secret in ("Zorana", "Testovic", "zorana.testovic@example.test", "third-party.test"):
            assert secret not in r["prompt"]
    est = off.estimate(built["requests"], {"in": 0.1, "out": 0.5})
    assert est["calls"] == 10 and est["upperBound"] >= est["expected"]


def test_a_name_left_in_an_ad_fails_the_dry_run_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(off, "load_confirmed_facts", lambda: [])
    out, frozen, _ = stage(tmp_path)
    doc = json.loads((out / "review-items.json").read_text())
    doc["items"][0]["description"] += " Ask Zorana Testovic."
    (out / "review-items.json").write_text(json.dumps(doc))
    assert off.build_requests(out, PROFILE, INTELLIGENCE, {"ad0": "production_like"})["leaks"]


def test_the_tool_cannot_send_anything(tmp_path, monkeypatch):
    select_provider(tmp_path, monkeypatch, "openai", "gpt-6-luna")
    source = open(off.__file__, encoding="utf-8").read()
    assert "complete_json" not in source and "requests.post" not in source and "urlopen" not in source
    with pytest.raises(SystemExit):
        off.main(["run"])
