"""Fill from ad, step 2: what the AI is given, when it may be asked, and what of its answer is kept."""

import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python" / "job_import"))

import ad_ai  # noqa: E402
import ad_fill  # noqa: E402
import ai_gate  # noqa: E402
import claude_code  # noqa: E402
import redact  # noqa: E402

OWNER = {"basicProfile": {"fullName": "Zlatan Qwerty"},
         "resume": {"parsedData": {"links": ["https://qwerty-cv.example/zlatan", "https://github.com/zqwerty"]}}}
LONG = " ".join(f"Responsibility {i}: own the payments roadmap and ship it with the team." for i in range(1, 9))
PAGE = f"""Page title: Careers
Acme d.o.o. is hiring
Senior Product Manager
Location: Niš, Serbia
Salary: 3000 - 3500 EUR per month
About the role. {LONG} That is the whole role.
Contact the recruiter Mirela Fakeson: mirela.fakeson@recruit-test.example, +381 64 555 0199, https://www.linkedin.com/in/mirela-fakeson
Candidate sample: Zlatan Qwerty, zlatan.qwerty@owner-test.example, https://qwerty-cv.example/zlatan"""

START = "About the role. Responsibility 1: own the payments roadmap"
END = "own the payments roadmap and ship it with the team. That is the whole role."


@pytest.fixture
def allowlisted(tmp_path, monkeypatch):
    """Claude Code on the subscription with job-import allowed, and the CLI present."""
    ai_dir = tmp_path / "ai"
    ai_dir.mkdir(exist_ok=True)
    (ai_dir / "settings.json").write_text(json.dumps({"claudeCodeSubscription": {"enabled": True, "maxCallsDaily": 5, "features": ["job-import"]}}))
    monkeypatch.setattr(claude_code, "availability", lambda: {"available": True, "reason": ""})


def settings(tmp_path, **sub):
    ai_dir = tmp_path / "ai"
    ai_dir.mkdir(exist_ok=True)
    (ai_dir / "settings.json").write_text(json.dumps({"claudeCodeSubscription": sub}))


# --- what is sent ------------------------------------------------------------------------------------------------

def test_the_request_has_the_owner_and_third_party_identifiers_removed():
    request = ad_ai.build_request(PAGE, ["company", "location"], OWNER)
    sent = request["prompt"]
    for secret in ("Zlatan", "Qwerty", "owner-test.example", "qwerty-cv.example", "github.com/zqwerty", "mirela.fakeson", "recruit-test.example", "555 0199", "mirela-fakeson"):
        assert secret not in sent, secret
    assert "Acme d.o.o." in request["text"] and "Senior Product Manager" in request["text"]
    assert request["removed"]["emails"] == 2 and request["removed"]["links"] >= 2 and request["removed"]["names"] >= 1


def test_a_salary_range_survives_the_redaction_that_removes_phone_numbers():
    request = ad_ai.build_request("Pay: 3000 - 3500 EUR per month. Call +381 64 555 0199. Also EUR 2.500-3.200 net, 36000 EUR/year.", ["salary"], None)
    assert "3000 - 3500 EUR per month" in request["text"] and "EUR 2.500-3.200" in request["text"] and "36000 EUR/year" in request["text"]
    assert "555 0199" not in request["text"] and "[PHONE]" in request["text"]


def test_the_instruction_asks_only_for_the_fields_still_missing():
    request = ad_ai.build_request(PAGE, ["company"], None)
    assert '"company"' in request["prompt"]
    for other in ('"title"', '"salary"', '"location"', "descriptionStart"):
        assert other not in request["prompt"]
    both = ad_ai.build_request(PAGE, ["location", "description", "bogus"], None)
    assert both["want"] == ["location", "description"] and "descriptionStart" in both["prompt"] and "bogus" not in both["prompt"]


def test_nothing_to_ask_is_a_refusal():
    for want in ([], ["bogus"], None):
        with pytest.raises(ad_ai.Refused) as raised:
            ad_ai.build_request(PAGE, want, OWNER)
        assert raised.value.code == "nothing_to_ask"


def test_if_redaction_leaves_anything_of_the_owner_the_step_fails_closed(monkeypatch):
    monkeypatch.setattr(redact, "redact_cv_text", lambda text, name="", links=None: (text, {"names": 0, "emails": 0, "phones": 0, "links": 0}))
    with pytest.raises(ad_ai.Refused) as raised:
        ad_ai.build_request(PAGE, ["company"], OWNER)
    assert raised.value.code == "redaction" and "Zlatan" not in raised.value.message
    for leaky in ("write to jane@x.example", "call +381 64 555 0199", "see https://qwerty-cv.example/zlatan", "by Zlatan"):
        assert ad_ai.find_leaks(leaky, "Zlatan Qwerty", OWNER["resume"]["parsedData"]["links"])
    assert ad_ai.find_leaks("Acme is hiring a Product Manager", "Zlatan Qwerty", []) == []


# --- may it be asked --------------------------------------------------------------------------------------------

def test_without_the_allowlist_entry_the_gate_refuses_and_says_how_to_fix_it(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_code, "availability", lambda: {"available": True, "reason": ""})
    for sub in ({}, {"enabled": True, "maxCallsDaily": 5, "features": ["jobAnalysis"]}, {"enabled": False, "features": ["job-import"]}):
        settings(tmp_path, **sub)
        status = ad_ai.gate_status("x" * 500)
        assert status["allowed"] is False and status["class"] != "subscription"
        assert "job-import" in status["reason"] and "allowlist" in status["reason"]


def test_with_the_entry_it_is_a_subscription_call_and_allowed(allowlisted):
    status = ad_ai.gate_status("x" * 500)
    assert status == {"allowed": True, "reason": None, "class": "subscription", "provider": "claude-code"}


def test_when_claude_code_is_missing_the_reason_says_so(allowlisted, monkeypatch):
    monkeypatch.setattr(claude_code, "availability", lambda: {"available": False, "reason": "Claude Code is not logged in"})
    assert ad_ai.gate_status("x") == {"allowed": False, "reason": "Claude Code is not logged in", "class": "subscription", "provider": "claude-code"}


def test_adding_job_import_to_the_allowlist_needs_the_owners_confirm_and_is_never_done_by_code(tmp_path):
    ai_gate.save_settings({"claudeCodeSubscription": {"enabled": True, "maxCallsDaily": 5, "features": ["jobAnalysis"]}}, confirm=True)
    asked = ai_gate.save_settings({"claudeCodeSubscription": {"features": ["jobAnalysis", "job-import"]}})
    assert asked["ok"] is False and asked["needsConfirm"] and "job-import" in " ".join(asked["increases"])
    assert "job-import" not in json.dumps(ai_gate.load_settings())
    assert ai_gate.save_settings({"claudeCodeSubscription": {"features": ["jobAnalysis", "job-import"]}}, confirm=True)["ok"]
    source = (ROOT / "python" / "job_import" / "ad_ai.py").read_text() + (ROOT / "python" / "job_import" / "ad_fill.py").read_text()
    assert "save_settings" not in source


def test_the_daily_subscription_cap_is_the_gates_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_code, "availability", lambda: {"available": True, "reason": ""})
    settings(tmp_path, enabled=True, maxCallsDaily=1, features=["job-import"])
    ticket = ai_gate.reserve("claude-code", None, 100, feature="job-import")
    ticket.finish(True)
    status = ad_ai.gate_status("x" * 100)
    assert status["allowed"] is False and "limit" in status["reason"]


def test_the_preview_calls_no_model_and_writes_no_ledger_row(allowlisted, tmp_path, monkeypatch):
    monkeypatch.setattr(claude_code, "complete_json", lambda *a, **k: pytest.fail("a model was called"))
    shown = ad_ai.preview(PAGE, ["company"], OWNER)
    assert shown["ok"] and shown["gate"]["allowed"] and "Zlatan" not in shown["text"] and shown["provider"] == "claude-code"
    assert not (tmp_path / "ai" / "usage-ledger.jsonl").exists()


# --- the call and what is kept ------------------------------------------------------------------------------------

def run(answer, want, profile=OWNER, page=PAGE):
    seen = {}

    def complete(prompt, timeout=0):
        seen["prompt"], seen["feature"] = prompt, ai_gate._feature.get()
        return answer, ""

    return ad_ai.extract(page, want, profile, complete=complete), seen


def test_the_call_carries_only_the_redacted_text_under_the_job_import_feature(allowlisted):
    _, seen = run({"company": "Acme d.o.o."}, ["company"])
    assert seen["feature"] == "job-import"
    for secret in ("Zlatan", "owner-test.example", "qwerty-cv.example", "mirela.fakeson", "555 0199"):
        assert secret not in seen["prompt"]


def test_only_values_the_text_shows_are_kept(allowlisted):
    result, _ = run({"title": "Chief Visionary Officer", "company": "Acme d.o.o.", "location": "Niš, Serbia", "salary": "3000 - 3500 EUR per month"},
                    ["title", "company", "location", "salary"])
    assert result["fields"] == {"company": "Acme d.o.o.", "location": "Niš, Serbia", "salary": "3000 - 3500 monthly EUR"}
    assert result["rejected"] == ["title"]  # invented: nowhere in the text


def test_matching_ignores_case_accents_and_spacing_but_not_content(allowlisted):
    result, _ = run({"company": "ACME  D.O.O.", "location": "nis, serbia"}, ["company", "location"])
    assert set(result["fields"]) == {"company", "location"}
    result, _ = run({"company": "Acme GmbH", "location": "Berlin"}, ["company", "location"])
    assert result["fields"] == {} and result["rejected"] == ["company", "location"]


@pytest.mark.parametrize("pay", ["EUR 20 per hour", "USD 5000 per month", "2500", "up to 3500 EUR per month"])
def test_pay_must_be_in_the_text_and_read_as_eur_per_month(allowlisted, pay):
    page = f"{PAGE}\nPay: {pay}"
    result, _ = run({"salary": pay}, ["salary"], page=page)
    assert "salary" not in result["fields"]


def test_the_description_is_cut_from_the_page_text_between_the_quoted_snippets(allowlisted):
    result, _ = run({"descriptionStart": START, "descriptionEnd": END}, ["description"])
    text = result["fields"]["description"]
    assert text.startswith("About the role.") and text.endswith("That is the whole role.") and "Responsibility 5" in text
    assert "mirela" not in text.lower() and "Zlatan" not in text


def test_the_stored_description_is_the_ad_itself_not_the_redacted_copy_the_model_saw(allowlisted):
    page = PAGE.replace("That is the whole role.", "That is the whole role. Questions: hr@acme-test.example, +381 11 555 0100.")
    seen = {}

    def complete(prompt, timeout=0):
        seen["prompt"] = prompt
        return {"descriptionStart": START, "descriptionEnd": "Questions: [EMAIL], [PHONE]."}, ""

    result = ad_ai.extract(page, ["description"], OWNER, complete=complete)
    assert "hr@acme-test.example" not in seen["prompt"] and "[EMAIL]" in seen["prompt"]  # the model never saw it
    assert "hr@acme-test.example" in result["fields"]["description"]                       # the stored ad is whole


def test_partial_json_ld_then_ai_asks_only_for_what_the_page_left_out(allowlisted):
    import ad_reader

    html = ('<html><head><title>Careers</title><script type="application/ld+json">'
            + json.dumps({"@type": "JobPosting", "title": "Senior Product Manager", "description": "<p>" + LONG + "</p>"})
            + "</script></head><body><p>Acme d.o.o. is hiring in Niš, Serbia. Salary: 3000 - 3500 EUR per month.</p></body></html>")
    ad = ad_reader.read_ad(html)
    assert ad["fields"]["title"] == "Senior Product Manager" and ad["missing"] == ["company", "location", "salary"]

    seen = {}

    def complete(prompt, timeout=0):
        seen["prompt"] = prompt
        return {"title": "Something else entirely", "company": "Acme d.o.o.", "location": "Niš, Serbia", "salary": "3000 - 3500 EUR per month"}, ""

    result = ad_ai.extract(ad["pageText"], ad["missing"], OWNER, complete=complete)
    assert '"company"' in seen["prompt"] and '"location"' in seen["prompt"] and '"salary"' in seen["prompt"]
    assert '"title"' not in seen["prompt"] and "descriptionStart" not in seen["prompt"]       # found in JSON-LD: not asked for
    assert set(result["fields"]) == {"company", "location", "salary"}                          # the stray title was never accepted
    assert ad["fields"]["title"] == "Senior Product Manager"                                    # and the JSON-LD value stays


def test_a_description_the_model_paraphrases_or_cannot_bracket_is_dropped(allowlisted):
    for answer in (
        {"descriptionStart": "A summary of the role in my own words", "descriptionEnd": END},
        {"descriptionStart": START, "descriptionEnd": "words that never appear in this page text"},
        {"descriptionStart": END, "descriptionEnd": START},       # reversed
        {"descriptionStart": "short", "descriptionEnd": "tiny"},
        {},
    ):
        result, _ = run(answer, ["description"])
        assert result["fields"] == {} and result["rejected"] == ["description"]


def test_extra_keys_and_non_object_answers_add_nothing(allowlisted):
    result, _ = run({"company": "Acme d.o.o.", "notes": "x", "sourceUrl": "https://s.example", "name": "Zlatan"}, ["company"])
    assert result["fields"] == {"company": "Acme d.o.o."}
    with pytest.raises(ad_ai.Refused) as raised:
        run(None, ["company"])
    assert raised.value.code == "ai_failed" and raised.value.message == "The AI could not read the fields from this page."


def test_a_refusal_happens_before_the_call_and_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_code, "availability", lambda: {"available": True, "reason": ""})
    settings(tmp_path)
    with pytest.raises(ad_ai.Refused) as raised:
        ad_ai.extract(PAGE, ["company"], OWNER, complete=lambda *a, **k: pytest.fail("the model was called"))
    assert raised.value.code == "refused" and "job-import" in raised.value.message
    rows = ai_gate.read_ledger()
    assert rows and rows[-1]["decision"] == "refused" and rows[-1]["feature"] == "job-import"


# --- the command --------------------------------------------------------------------------------------------------

def test_the_commands_take_page_text_and_field_names_and_report_refusals(allowlisted, tmp_path, monkeypatch, capsys):
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(OWNER))
    monkeypatch.setenv("CAREER_OS_PROFILE_PATH", str(profile))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"pageText": PAGE, "want": ["company"], "notes": "NOTE-CANARY", "sourceUrl": "https://canary.example"})))
    assert ad_fill.main(["ai-preview"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["ok"] and "NOTE-CANARY" not in json.dumps(shown) and "Zlatan" not in shown["text"]

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"pageText": PAGE, "want": []})))
    ad_fill.main(["ai-extract"])
    assert json.loads(capsys.readouterr().out) == {"ok": False, "error": "nothing_to_ask", "message": "Every field is already filled."}
