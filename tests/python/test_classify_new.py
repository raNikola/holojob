"""Package 12: automatic Fit 3 role classification of new ads (classify_new.py), and the owner's ads staying in every scoring run (kept_ads.register_owner_ads).

Rules under test: an ad with no entry gets one and Re-score then reads its class (the key round-trip); an ad whose entry failed to anchor is never called again;
only title and masked ad text leave (no note, link or source URL; the owner's own identifier refuses the ad); a cap, a gate refusal or a provider failure stops or
skips without failing the run and never waits; plain Re-score calls no model; the owner's applied / kept ads cannot drop out of the scored list. Synthetic data in
temp dirs only; no network, nothing under the real data dir.
"""

from __future__ import annotations

import json
import stat

import pytest

import classify_new
import job_history
import kept_ads
import role_class
from llm_client import GuardrailRefused
from match_engine import fit3

OWNER_NAME = "Zorana Testovic"
OWNER_EMAIL = "zorana.testovic@example.test"
OWNER_PHONE = "+381 64 555 0123"
PROFILE = {"basicProfile": {"fullName": OWNER_NAME, "email": OWNER_EMAIL, "phone": OWNER_PHONE, "links": []},
           "resume": {"parsedData": {"skills": ["SQL"], "links": []}}}
AD = ("Technical Project Manager. You will own the delivery roadmap and talk to customers every week. "
      "Requirements: strong stakeholder management. Nice to have: SQL. Questions? recruiter@acme.example or +44 20 7946 0958.")


def row(job_id="a1", **over):
    return {"jobId": job_id, "title": "Technical Project Manager", "company": "Acme", "description": AD, "location": "Remote", **over}


def good_reply():
    target = next(name for name, cls in fit3.load_roles().items() if cls == "target")
    return {"function": {"role": target, "quote": "own the delivery roadmap"}, "title": {"role": target, "quote": "Project Manager"}, "competencies": []}


class Guard:
    """A stand-in for the spend guard: allows `n` calls, then refuses like the cap does."""

    def __init__(self, n=99):
        self.n, self.reserved = n, 0

    def reserve(self, prompt):
        if self.reserved >= self.n:
            raise GuardrailRefused("the next call could pass the $0.05 cap")
        self.reserved += 1
        return 0.0

    def release(self, worst):
        pass

    def spent(self):
        return 0.0


@pytest.fixture
def lists():
    with fit3.production_candidate():
        yield fit3.load_roles(), fit3.closed_competencies("product")


def run_with(lists, rows, complete, guard=None, profile=PROFILE):
    roles, comps = lists
    entries = {}
    todo = classify_new.plan(rows, entries, roles, comps)["todo"]
    return classify_new.run(todo, profile, roles, comps, guard or Guard(), None, None, complete=complete), todo


def test_a_new_ad_is_classified_and_rescore_reads_its_class(lists, tmp_path):
    roles, comps = lists
    store = tmp_path / "fit3.json"
    result, todo = run_with(lists, [row()], lambda prompt, **kw: good_reply())
    assert len(result["entries"]) == 1 and not result["stopped"]
    assert classify_new.merge_into_store(store, result["entries"]) == 1
    rows = [row()]
    counts = role_class.label(rows, path=store)  # the key the step wrote is the key Re-score looks up
    assert rows[0]["roleClass"] == "target" and counts["target"] == 1


def test_an_ad_that_has_an_entry_is_not_called_again_even_if_its_role_did_not_anchor(lists):
    roles, comps = lists
    bad = {"function": {"role": "Not A Role", "quote": "x"}, "title": {}, "competencies": []}
    old, done, new = row("old", description=AD + " One."), row("done", description=AD + " Two."), row("new", description=AD + " Three.")
    entries = {fit3.classification_key(old, roles, comps): {"reply": bad, "answers": None},
               fit3.classification_key(done, roles, comps): {"reply": good_reply(), "answers": None}}
    groups = classify_new.plan([old, done, new], entries, roles, comps)
    assert [r["jobId"] for _, r in groups["todo"]] == ["new"]
    assert groups["anchoringFailed"] == ["old"] and groups["classed"] == 1


def test_closed_unfound_and_textless_ads_cost_nothing(lists):
    roles, comps = lists
    rows = [row("c", isClosed=True), row("n", notFoundThisRun=True), row("t", description="  "), row("ok", description=AD + " Unique.")]
    groups = classify_new.plan(rows, {}, roles, comps)
    assert [r["jobId"] for _, r in groups["todo"]] == ["ok"] and groups["noText"] == 1 and groups["skipped"] == 2


def test_only_the_title_and_masked_ad_text_leave(lists):
    sent = []
    manual = row("m1", manualEntry=True, notes="PRIVATE-NOTE", extraLinks=["https://private.example/x"], sourceUrl="https://private.example/src")
    run_with(lists, [manual], lambda prompt, **kw: sent.append(prompt) or good_reply())
    prompt = sent[0]
    assert "Technical Project Manager" in prompt and "[EMAIL]" in prompt and "[PHONE]" in prompt
    for secret in ("PRIVATE-NOTE", "private.example", "recruiter@acme.example", "7946", "Acme"):
        assert secret not in prompt


def test_an_ad_carrying_the_owners_own_identifier_is_refused_and_never_sent(lists):
    roles, comps = lists
    bad = row("o1", description=AD + f" Contact {OWNER_EMAIL}")
    fine = row("ok2", description=AD + " Another.")
    est = classify_new.estimate(classify_new.plan([bad, fine], {}, roles, comps)["todo"], PROFILE, roles, comps, 100, 0.05)
    assert est["privacyRefused"] == ["o1"] and [r["jobId"] for _, r in est["send"]] == ["ok2"]


def test_the_last_check_refuses_an_outgoing_prompt_that_carries_the_owner(lists):
    sent = []
    leaky = row("o2", description=f"Own the delivery roadmap. Call {OWNER_PHONE}")
    result, _ = run_with(lists, [leaky], lambda prompt, **kw: sent.append(prompt) or good_reply())
    assert sent == [] and result["failed"] == {"privacyRefused": 1} and result["entries"] == {}


def test_a_cap_stops_the_run_and_says_how_many_are_left(lists):
    rows = [row(f"a{i}", description=AD + f" variant {i}") for i in range(5)]
    result, todo = run_with(lists, rows, lambda prompt, **kw: good_reply(), guard=Guard(2))
    assert len(result["entries"]) == 2 and result["left"] == 3 and "cap" in result["stopped"]
    assert classify_new.stop_code(result["stopped"]) == "cap"


def test_a_provider_failure_skips_the_ad_and_never_raises(lists):
    calls = []

    def flaky(prompt, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("provider down")
        return good_reply()

    rows = [row(f"b{i}", description=AD + f" v{i}") for i in range(3)]
    result, _ = run_with(lists, rows, flaky)
    assert result["failed"] == {"RuntimeError": 1} and len(result["entries"]) == 2 and not result["stopped"]


def test_three_failures_in_a_row_stop_the_run(lists):
    def down(prompt, **kw):
        raise RuntimeError("provider down")

    rows = [row(f"c{i}", description=AD + f" v{i}") for i in range(6)]
    result, _ = run_with(lists, rows, down)
    assert result["entries"] == {} and result["left"] == 3 and classify_new.stop_code(result["stopped"]) == "failures"


def test_a_failed_step_never_fails_a_pipeline_run(monkeypatch, capsys):
    monkeypatch.setattr(classify_new, "_main", lambda args: (_ for _ in ()).throw(ValueError("boom")))
    assert classify_new.main([]) == 0
    assert "skipped" in capsys.readouterr().out


def test_the_store_only_gains_entries_keeps_its_mode_and_a_backup(tmp_path):
    store = tmp_path / "fit3.json"
    store.write_text(json.dumps({"version": 1, "promptVersion": 3, "entries": {"old": {"reply": {}, "answers": None}}}))
    store.chmod(0o600)
    assert classify_new.merge_into_store(store, {"old": {"reply": {"x": 1}}, "new": {"reply": {}, "answers": None}}) == 1
    doc = json.loads(store.read_text())
    assert set(doc["entries"]) == {"old", "new"} and doc["entries"]["old"]["reply"] == {} and doc["promptVersion"] == 3
    assert stat.S_IMODE(store.stat().st_mode) == 0o600
    backups = list(tmp_path.glob("fit3.json.bak-pre-classify-*"))
    assert len(backups) == 1 and stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    assert classify_new.merge_into_store(store, {"new": {"reply": {}}}) == 0  # nothing new: nothing written


def test_plain_rescore_calls_no_model(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError("a model call from the label step")

    monkeypatch.setattr(fit3, "classify", boom)
    rows = [row()]
    counts = role_class.label(rows, path=tmp_path / "missing.json")
    assert rows[0]["roleClass"] == "not available" and counts["not available"] == 1


def test_a_failed_run_record_has_fixed_codes_not_free_text():
    assert classify_new.stop_code("stopped: AI gate refused: anything the provider said") == "gate"
    assert classify_new.stop_code(None) is None


# --- item 11: the owner's ads stay in every scoring run ----------------------------------------------------------------


@pytest.fixture
def ledger_file(tmp_path):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    view = jobs / "discovered_jobs.json"
    ledger = job_history.empty_ledger()
    ledger["jobs"] = {"applied1": {"job": row("applied1")}, "kept1": {"job": row("kept1")}, "other1": {"job": row("other1")}}
    job_history.ledger_path(view).write_text(json.dumps(ledger))
    return job_history.ledger_path(view), jobs / "rescored_kept.json"


def test_owner_ads_are_registered_and_come_back_into_the_scoring_set(ledger_file):
    ledger, kept = ledger_file
    out = kept_ads.register_owner_ads({"applied1", "kept1", "gone-from-ledger"}, ledger, kept)
    assert out == {"registered": 2, "already": 0, "notInLedger": 1}
    assert set(kept_ads.load(kept)) == {"applied1", "kept1"} and stat.S_IMODE(kept.stat().st_mode) == 0o600
    rows = kept_ads.with_kept([], ledger, kept)  # the view dropped both: the scoring set still holds them
    assert {r["jobId"] for r in rows} == {"applied1", "kept1"} and all(r.get("keptRescore") for r in rows)
    assert kept_ads.register_owner_ads({"applied1"}, ledger, kept) == {"registered": 0, "already": 1, "notInLedger": 0}


def test_an_unregistered_ad_is_not_added_and_a_registered_applied_ad_survives_the_prune(ledger_file):
    ledger, kept = ledger_file
    kept_ads.register_owner_ads({"applied1"}, ledger, kept)
    assert {r["jobId"] for r in kept_ads.with_kept([], ledger, kept)} == {"applied1"}  # other1 is not owner data: it may leave the list
    assert kept_ads.prune({"applied1"}, kept) == [] and set(kept_ads.load(kept)) == {"applied1"}
