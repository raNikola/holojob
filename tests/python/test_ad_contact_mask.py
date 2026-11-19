"""A recruiter's e-mail or phone in the ad text is masked before the matcher prompt is built; numbers that are not contacts are never touched,
and the owner-identifier scan itself is not loosened."""

import pytest

from match_engine import matcher
from match_engine.normalize import quote_in
from redact import find_leaks, mask_ad_contacts

AD = "Great role 2019 - 2024 experience. Write to jane.doe@example.com or call +381 11 234 5678 today."


@pytest.mark.parametrize("contact", [
    "+381 11 234 5678", "+1 (555) 123-4567", "+44 20 7946 0958", "00381 64 123 4567", "(011) 234-5678",
    "011 234 5678", "064/123-4567", "Tel: 011 2345678", "WhatsApp +381641234567",
])
def test_real_phone_shapes_are_masked(contact):
    text, counts = mask_ad_contacts(f"Questions? {contact}. Thanks")
    assert counts["phones"] == 1 and "[PHONE]" in text and not any(ch.isdigit() for ch in text)


@pytest.mark.parametrize("numbers", [
    "Salary 120 000 - 150 000 EUR", "Pay: 120,000-150,000 USD", "100 000 000 users", "EUR 80 000 - 95 000 gross",
    "2019 - 2024", "2019-2024-2026", "5+ years of experience", "10+ years in B2B SaaS, 3-5 years leading teams",
    "Team of 150 engineers across 12 squads", "ID 20261119 ref 1234567890", "Posted 01.02.2024", "Start 2024-11-19",
    "Budget 1 500 000 per year", "Revenue 40 000 000 - 60 000 000", "Version 3.14.159.2653",
])
def test_pay_years_counts_ids_and_dates_are_left_alone(numbers):
    text, counts = mask_ad_contacts(numbers)
    assert text == numbers and counts == {"emails": 0, "phones": 0}


def test_email_is_masked():
    text, counts = mask_ad_contacts(AD)
    assert "[EMAIL]" in text and "[PHONE]" in text and "2019 - 2024" in text
    assert counts == {"emails": 1, "phones": 1}
    assert not find_leaks(text)


def test_prompt_carries_no_ad_contact_and_the_run_counts_it():
    before = dict(matcher.MASKED_CONTACTS)
    asked = [("r1", {"text": "Product experience", "kind": "experience", "importance": "must"})]
    prompt = matcher.build_prompt(AD, asked, [])
    assert "jane.doe@example.com" not in prompt and "234 5678" not in prompt
    assert matcher.MASKED_CONTACTS["ads"] == before["ads"] + 1
    assert matcher.MASKED_CONTACTS["emails"] == before["emails"] + 1
    assert find_leaks(prompt) == []


def test_quotes_still_verify_against_the_stored_ad():
    ad = "Requires 10+ years of experience. Salary 120 000 - 150 000 EUR. Contact: jane.doe@example.com, +381 11 234 5678."
    masked, _ = mask_ad_contacts(ad)
    # A requirement quote is checked against the stored (unmasked) ad before the prompt exists, and a quote of non-contact text is the same in both.
    for quote in ("Requires 10+ years of experience", "Salary 120 000 - 150 000 EUR"):
        assert quote_in(quote, ad) and quote_in(quote, masked)
    # A gate quote that was copied from masked text cannot match the stored ad; it is dropped, never kept as if verbatim.
    copied = "Contact: [EMAIL], [PHONE]"
    assert not quote_in(copied, ad) and matcher._unmasked_quote(copied) is None
    assert matcher._unmasked_quote("Salary 120 000 - 150 000 EUR") == "Salary 120 000 - 150 000 EUR"


def test_owner_data_in_an_ad_is_still_caught():
    assert find_leaks(mask_ad_contacts("Contact Zed Quux for details")[0], "Zed Quux") == ["the owner's name"]
