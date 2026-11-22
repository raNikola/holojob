"""A third party's phone number in an ad is masked in the text sent to the provider, and the ad is sent; the owner's own phone, e-mail and name still stop an
ad; CV redaction and the strict scan are unchanged. Synthetic values only."""

from types import SimpleNamespace

import pytest

import engine_missing
import evidence_index
from calibration.prelabel import owner_in_text, owner_leaks
from match_engine import matcher
from redact import find_leaks, identity_of, mask_ad_contacts, redact_cv_text

OWNER_NAME = "Zorana Testovic"
OWNER_EMAIL = "zorana.testovic@example.test"
OWNER_PHONE = "+381 64 555 0123"
PROFILE = {"basicProfile": {"fullName": OWNER_NAME, "email": OWNER_EMAIL, "phone": OWNER_PHONE, "links": []},
           "resume": {"parsedData": {"skills": ["SQL", "Product discovery"], "links": []}}}

THIRD_PARTY = ["+44 20 7946 0958", "+1 (555) 123-4567", "00381 11 234 5678", "(011) 234-5678", "064/123-4567", "Tel: 011 2345678",
               "555-123-4567", "1-800-555-1234", "06412345678", "call 12345678", "Phone 641234567"]
NOT_PHONES = ["Requisition # 12345678", "Job ID: 123456789", "Posted 15/11/2026", "Salary 120 000 - 150 000 EUR", "ZIP 94105-1234",
              "Version 3.14.159.2653", "Range 120,000.00 - 150,000.00", "Case 2024-123456", "2019 - 2024"]


def prompt_for(description):
    asked = [("r1", {"text": "Experience with SQL", "kind": "skill", "importance": "must"})]
    return matcher.build_prompt(description, asked, [], identity_of(PROFILE))


@pytest.mark.parametrize("number", THIRD_PARTY)
def test_a_third_party_phone_is_masked_and_the_ad_is_sent(number):
    prompt = prompt_for(f"Experience with SQL. Questions? {number}. Thanks")
    assert "[PHONE]" in prompt
    assert not any(ch.isdigit() for ch in prompt.split("=== BEGIN JOB AD")[1].split("=== END JOB AD")[0])
    assert owner_leaks(prompt, PROFILE) == []  # nothing left for the scan to refuse


@pytest.mark.parametrize("text", NOT_PHONES)
def test_numbers_that_are_not_phones_are_left_as_they_are(text):
    masked, counts = mask_ad_contacts(f"Experience with SQL. {text} ends here")
    assert text in masked and counts["phones"] == 0


@pytest.mark.parametrize("ad", [
    f"Contact the owner at {OWNER_PHONE}", "Call 064 555 0123 for details", "Ref 381645550123 please", f"Mail {OWNER_EMAIL} now",
    f"Ask {OWNER_NAME.split()[0]} about it", f"Reach {OWNER_EMAIL.upper()}",
])
def test_the_owners_own_identifiers_in_the_raw_ad_are_found(ad):
    assert owner_in_text(ad, PROFILE)


@pytest.mark.parametrize("ad", ["Call +44 20 7946 0958 or write to recruiter@example.test", "Requisition 12345678, pay 120 000 - 150 000 EUR"])
def test_a_strangers_contact_is_not_the_owners(ad):
    assert owner_in_text(ad, PROFILE) == []


def _stub_fill(monkeypatch):
    candidate = evidence_index.build_candidate(PROFILE, {"languages": []}, [], None)
    engine = SimpleNamespace(candidate=candidate, identity=identity_of(PROFILE), select=None, compact=False, excluded={},
                             _posting=lambda job: matcher.posting_from_job(job, {}))
    price = {"priceKnown": True, "inputPerMTok": 0.1, "outputPerMTok": 0.5, "cachedInputPerMTok": None, "tier": "standard", "class": "paid"}
    monkeypatch.setattr(engine_missing.ai_gate, "classify", lambda *a, **k: price)
    monkeypatch.setattr(engine_missing.ai_gate, "load_settings", lambda: {"dailyLimit": 3, "monthlyLimit": 10})
    monkeypatch.setattr(engine_missing.ai_gate, "totals", lambda *a, **k: {"today": {"cost": 0}, "thisMonth": {"cost": 0}})
    monkeypatch.setattr(engine_missing, "service_tier_for", lambda provider: "standard")
    return engine


def _job(job_id, tail):
    text = f"Experience with SQL is required. {tail}"
    return {"jobId": job_id, "title": "PM", "company": "Acme", "location": "Remote", "description": text,
            "llmFacts": {"requirements": [{"id": "sql", "text": "Experience with SQL", "kind": "skill", "importance": "must", "postingQuote": "Experience with SQL"}]}}


def test_the_fill_sends_an_ad_with_a_third_party_phone_and_refuses_one_with_the_owners(monkeypatch):
    engine = _stub_fill(monkeypatch)
    jobs = [_job("clean", "Remote role."), _job("stranger", "Call +44 20 7946 0958 for details."), _job("stranger-local", "Contact 06412345678."),
            _job("owner-phone", f"Contact {OWNER_PHONE}."), _job("owner-mail", f"Write to {OWNER_EMAIL}."), _job("owner-name", f"Ask {OWNER_NAME} directly.")]
    ids = {j["jobId"] for j in jobs}
    est = engine_missing.estimate(engine, jobs, ids, PROFILE, {"provider": "openai", "model": "m", "baseUrl": ""})
    assert set(est["leaks"]) == {"owner-phone", "owner-mail", "owner-name"}
    assert set(est["ownerAds"]) == {"owner-phone", "owner-mail", "owner-name"}
    assert est["toAsk"] == 3  # clean + both strangers' ads are sent


def test_cv_redaction_and_the_strict_scan_are_unchanged():
    text, removed = redact_cv_text("Reach me on 064 555 0123 or 12345678.", OWNER_NAME, [])
    assert removed["phones"] == 2 and not any(ch.isdigit() for ch in text)
    assert find_leaks("Contact 12345678") == ["a phone number"]
    assert find_leaks("Requisition # 12345678") == ["a phone number"]
