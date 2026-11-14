"""Step 7 runner on a fictional profile and fictional ads, with the model replaced. No real data, no network, no production file."""

import json
import stat
from types import SimpleNamespace

import pytest

from calibration import engine_sample as eng
from calibration import enrich_sample as es
from calibration.prelabel import owner_leaks
from conftest import select_provider

PROFILE = {
    "basicProfile": {"fullName": "Zorana Testovic", "email": "zorana.testovic@example.test", "phone": "+381 64 123 4567",
                     "preferredLocations": ["Atlantis"]},
    "resume": {"parsedData": {
        "links": ["https://zorana.example/me"],
        "experienceDetail": [{"title": "Product Manager", "company": "Initech", "start": "2018-01", "end": "2022-06",
                              "bullets": ["Led the billing roadmap for 40 customers",
                                          "Reach Zorana Testovic at zorana.testovic@example.test or +381 64 123 4567 or https://zorana.example/me"]}],
        "skills": ["SQL", "Roadmapping"], "education": ["BSc Computer Science"], "certifications": [],
    }},
}
INTELLIGENCE = {"candidateSummary": {"seniorityLevel": "Senior"}, "experienceMap": {"yearsOfExperience": 9},
                "roleStrategy": {"primaryTargetRoles": ["Product Manager"]}, "languages": ["English"]}


def ad(n, **extra):
    return {"jobId": f"job{n}", "title": f"Role {n}", "company": f"Firm {n}", "location": "Remote", "site": "x",
            "jobUrl": f"https://example.test/{n}",
            "description": f"Own the roadmap number {n}. Five years of SQL. Mail hr{n}@third-party.test.", **extra}


def facts_for(item):
    clean = es.sanitized(item)
    return {"requirements": [{"id": "sql", "text": "SQL", "kind": "skill", "importance": "must",
                              "postingQuote": "Five years of SQL"}],
            "_fingerprint": es.job_fingerprint(clean)}


def write(folder, items):
    (folder / "review-items.json").write_text(json.dumps({"version": 1, "items": items}))
    (folder / es.FACTS_NAME).write_text(json.dumps({"version": 1, "facts": {i["jobId"]: facts_for(i) for i in items}}))


class Model:
    def __init__(self):
        self.prompts = []

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.prompts.append(prompt)
        return {"matches": [], "gates": {g: {"quote": None} for g in ("work_authorization", "location", "language",
                                                                        "salary_floor", "role_family")}}


@pytest.fixture
def out(tmp_path, monkeypatch):
    select_provider(tmp_path, monkeypatch, "openai", "gpt-6-luna")
    folder = tmp_path / "stage-a"
    folder.mkdir()
    write(folder, [ad(1), ad(2), ad(3)])
    monkeypatch.setattr(eng, "load_confirmed_facts", lambda: [])
    monkeypatch.setattr(eng, "cheap_gate_report", lambda job, candidate: ([], "unknown"))
    monkeypatch.setattr(eng, "preflight", lambda *a, **k: SimpleNamespace(allowed=True, reason=None, row={}))
    return folder


# --- redaction before the scan, scan fails closed -------------------------------------------


def test_the_owners_identifiers_in_the_cv_evidence_are_redacted_before_any_request_is_built(out):
    p = eng.plan(out, PROFILE, INTELLIGENCE)
    assert p["rows"] and p["leaks"] == {}
    for row in p["rows"].values():
        for raw in ("Zorana", "Testovic", "zorana.testovic@example.test", "381 64 123", "zorana.example", "third-party.test"):
            assert raw not in row["prompt"]
        assert "Led the billing roadmap" in row["prompt"]  # the evidence itself is sent


def test_the_owners_name_in_an_ad_description_stops_the_run_before_any_call(out):
    # The generic redaction knows no name, so the scan is what protects it.
    write(out, [ad(1), ad(2, description="Own the roadmap. Five years of SQL. Ask Zorana Testovic.")])
    model = Model()
    result = eng.run(out, PROFILE, INTELLIGENCE, complete=model)
    assert "privacy scan" in result["stopped"] and model.prompts == []
    assert not (out / eng.RESULTS_NAME).exists()


@pytest.mark.parametrize("secret", ["zorana.testovic@example.test", "+381 64 123 4567", "https://zorana.example/me"])
def test_an_owner_e_mail_phone_or_link_in_a_description_is_redacted_before_the_scan(out, secret):
    write(out, [ad(1, description=f"Own the roadmap. Five years of SQL. Write to {secret}.")])
    p = eng.plan(out, PROFILE, INTELLIGENCE)
    assert p["leaks"] == {} and secret not in next(iter(p["rows"].values()))["prompt"]


def test_the_title_company_and_location_are_not_part_of_the_request(out):
    write(out, [ad(1, title="Role for Zorana Testovic", company="zorana.testovic@example.test", location="+381 64 123 4567")])
    p = eng.plan(out, PROFILE, INTELLIGENCE)
    assert p["leaks"] == {} and "Zorana" not in next(iter(p["rows"].values()))["prompt"]


def test_a_hash_id_that_looks_like_a_phone_number_is_aliased_not_allowed_through_a_looser_scan(out):
    candidate = {"evidence": [{"id": "ev-1234567890ab", "text": "x"}, {"id": "ev-abcdefabcdef", "text": "y"}]}
    fixed, aliases = eng.alias_unsafe_ids(candidate, PROFILE)
    assert aliases == {"ev-cal-1": "ev-1234567890ab"}
    assert [e["id"] for e in fixed["evidence"]] == ["ev-cal-1", "ev-abcdefabcdef"]
    assert owner_leaks("ev-1234567890ab", PROFILE)  # the scan itself is unchanged


def test_a_live_call_scans_the_exact_text_again_and_refuses_on_a_hit(out, monkeypatch):
    state = {"live": False}
    real, real_plan = eng.owner_leaks, eng.plan

    def plan_then_go_live(*args, **kw):
        result = real_plan(*args, **kw)
        state["live"] = True  # from here on only the wrapper around the live call scans
        return result

    monkeypatch.setattr(eng, "plan", plan_then_go_live)
    monkeypatch.setattr(eng, "owner_leaks", lambda text, profile: ["a name"] if state["live"] else real(text, profile))
    model = Model()
    result = eng.run(out, PROFILE, INTELLIGENCE, complete=model)
    assert model.prompts == [] and result["ok"] == 0 and result["refused"] >= 1
    assert real("Zorana Testovic", PROFILE)


# --- the dry run, resume, production paths -----------------------------------------------------


def test_the_estimate_makes_no_call_and_writes_nothing(out):
    before = sorted(f.name for f in out.iterdir())
    model = Model()
    p = eng.plan(out, PROFILE, INTELLIGENCE)
    lines = "\n".join(eng.describe(p))
    assert "UPPER BOUND" in lines and "calls to make: 3" in lines and "3 of 3 requests pass" in lines
    assert model.prompts == [] and sorted(f.name for f in out.iterdir()) == before


def test_results_are_written_only_to_the_calibration_folder_with_mode_600_and_a_rerun_asks_for_nothing(out):
    model = Model()
    assert eng.run(out, PROFILE, INTELLIGENCE, complete=model) == {"stopped": None, "asked": 3, "ok": 3, "failed": 0, "refused": 0, "modelCalls": 3, "retries": 0}
    assert stat.S_IMODE((out / eng.RESULTS_NAME).stat().st_mode) == 0o600
    assert sorted(f.name for f in out.iterdir()) == sorted(["review-items.json", es.FACTS_NAME, eng.RESULTS_NAME])
    again = Model()
    assert eng.run(out, PROFILE, INTELLIGENCE, complete=again)["asked"] == 0 and again.prompts == []


def test_resume_asks_only_for_the_ads_not_yet_done(out):
    eng.run(out, PROFILE, INTELLIGENCE, complete=Model())
    data = json.loads((out / eng.RESULTS_NAME).read_text())
    del data["ads"]["job2"]
    (out / eng.RESULTS_NAME).write_text(json.dumps(data))
    again = Model()
    assert eng.run(out, PROFILE, INTELLIGENCE, complete=again)["asked"] == 1 and len(again.prompts) == 1


def test_an_estimate_over_the_hard_stop_and_a_gate_refusal_send_nothing(out, monkeypatch):
    model = Model()
    monkeypatch.setattr(eng, "HARD_STOP_USD", 1e-9)
    assert "hard stop" in eng.run(out, PROFILE, INTELLIGENCE, complete=model)["stopped"]
    monkeypatch.setattr(eng, "HARD_STOP_USD", 0.5)
    monkeypatch.setattr(eng, "preflight", lambda *a, **k: SimpleNamespace(allowed=False, reason="daily budget", row={}))
    monkeypatch.setattr(eng.ai_gate, "record_refused", lambda *a, **k: None)
    assert "AI gate refused" in eng.run(out, PROFILE, INTELLIGENCE, complete=model)["stopped"]
    assert model.prompts == []


def test_every_ad_is_marked_production_like_or_diagnostic_and_a_diagnostic_one_records_its_gate(out, monkeypatch):
    fails = {"job2": ["role_family"], "job3": ["language", "work_authorization"]}
    monkeypatch.setattr(eng, "cheap_gate_report", lambda job, candidate: (fails.get(job["title"].replace("Role ", "job"), []), "unknown"))
    rows = eng.plan(out, PROFILE, INTELLIGENCE)["rows"]
    assert {j: (r["mode"], r["excludedBy"]) for j, r in rows.items()} == {
        "job1": ("production_like", []), "job2": ("diagnostic", ["role_family"]),
        "job3": ("diagnostic", ["language", "work_authorization"])}
    assert set(eng.plan(out, PROFILE, INTELLIGENCE, production_only=True)["rows"]) == {"job1"}
    assert "1 production_like, 2 diagnostic" in "\n".join(eng.describe(eng.plan(out, PROFILE, INTELLIGENCE)))


def test_the_stored_result_carries_the_mode_and_the_excluding_gate(out, monkeypatch):
    monkeypatch.setattr(eng, "cheap_gate_report", lambda job, candidate: (["role_family"] if job["title"] == "Role 2" else [], "unknown"))
    eng.run(out, PROFILE, INTELLIGENCE, complete=Model())
    ads = json.loads((out / eng.RESULTS_NAME).read_text())["ads"]
    assert (ads["job1"]["mode"], ads["job1"]["excludedBy"]) == ("production_like", [])
    assert (ads["job2"]["mode"], ads["job2"]["excludedBy"]) == ("diagnostic", ["role_family"])


def test_a_matcher_retry_counts_against_the_cap_and_stops_the_batch(out, monkeypatch):
    class Bad(Model):
        def __call__(self, prompt, **kw):
            self.prompts.append(prompt)
            return {"not": "the schema"}  # malformed: the matcher asks a second time

    monkeypatch.setattr(eng, "HARD_STOP_USD", 0.0001)  # below the planned estimate: stops before any call
    assert "hard stop" in eng.run(out, PROFILE, INTELLIGENCE, complete=Bad())["stopped"]
    monkeypatch.setattr(eng, "HARD_STOP_USD", 0.25)
    model = Bad()
    result = eng.run(out, PROFILE, INTELLIGENCE, workers=1, complete=model)
    assert result["failed"] == 3 and result["retries"] == 3 and result["modelCalls"] == 6


def test_the_runner_names_no_production_state():
    src = (eng.ROOT / "python" / "calibration" / "engine_sample.py").read_text()
    for production in ("engine.json", "scored_jobs", "discovered_jobs", "job_history", "requirement-frames", "usage-ledger"):
        assert production not in src
    assert "CACHE_PATH" not in src


# --- the id-list option: matcher only, on stored facts, a caller-chosen cap ---------------------------------


def test_matcher_ids_copies_only_the_listed_ads_with_their_facts_and_never_the_unextracted(tmp_path):
    from calibration import matcher_ids as mi
    a, b, c, d = ad(1), ad(2), ad(3), ad(4)
    jobs = [{**a, "llmFacts": facts_for(a)}, {**b, "llmFacts": facts_for(b)}, c, {**d, "llmFacts": {"requirements": []}}]
    view = tmp_path / "discovered.json"
    view.write_text(json.dumps({"jobs": jobs}))
    before = view.read_bytes()
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps({"ids": ["job1", "job3", "job4", "job1", "missing"]}))
    folder = tmp_path / "m"
    remap = tmp_path / "remap.json"
    remap.write_text(json.dumps({"prov:abc": "sql"}))
    assert mi.prepare(mi.load_ids(ids), view, folder, remap) == {
        "ids": 4, "found": 3, "prepared": 1, "noFacts": 1, "noRequirements": 1, "closedButPrepared": 0, "remapEntries": 1}
    assert json.loads((folder / "requirement-remap.json").read_text()) == {"prov:abc": "sql"}
    assert [i["jobId"] for i in json.loads((folder / "review-items.json").read_text())["items"]] == ["job1"]
    assert "llmFacts" not in json.loads((folder / "review-items.json").read_text())["items"][0]
    assert set(json.loads((folder / es.FACTS_NAME).read_text())["facts"]) == {"job1"}
    assert stat.S_IMODE((folder / es.FACTS_NAME).stat().st_mode) == 0o600 and stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert view.read_bytes() == before


def test_max_usd_sets_the_cap_and_the_default_stays(out, monkeypatch):
    assert "hard stop in the runner: $0.25" in "\n".join(eng.describe(eng.plan(out, PROFILE, INTELLIGENCE)))
    assert "hard stop in the runner: $0.40" in "\n".join(eng.describe(eng.plan(out, PROFILE, INTELLIGENCE, cap=0.4)))
    assert "hard stop" in eng.run(out, PROFILE, INTELLIGENCE, complete=Model(), cap=1e-9)["stopped"]
    assert eng.run(out, PROFILE, INTELLIGENCE, complete=Model(), cap=0.4)["ok"] == 3
