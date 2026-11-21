"""The scan of an outgoing prompt that carries a job ad (prelabel.owner_leaks -> redact.find_leaks(ad_text=True)) no longer refuses an ad for a digit run
that is not a phone (requisition number, date, pay range, amount, ZIP+4), and still refuses a real phone shape. Synthetic values only.
The strict scan (find_leaks default: CV redaction and every other caller) is unchanged."""

import pytest

from calibration.prelabel import owner_leaks
from redact import find_leaks, mask_ad_contacts

PROFILE = {"basicProfile": {"fullName": "Zorana Testovic", "email": "zorana.testovic@example.test", "phone": "+381 64 555 0123"}}


def scan(text):
    return owner_leaks(text, PROFILE)


@pytest.mark.parametrize("text", [
    "Requisition # 12345678", "Job ID: 123456789", "Ref 1234567890", "Req no. 20261119", "Position 99999999999 is open",
    "Posted 15/11/2026", "Closing date 2026-11-30", "Apply between 05/12/2026 - 20/12/2026", "Start 01.02.2027",
    "Salary 120 000 - 150 000", "Pay 100.00 - 130 per hour", "Budget 1 500 000 per year", "EUR 80 000 - 95 000", "$ 12345678 total",
    "Revenue 40 000 000 - 60 000 000", "ZIP 94105-1234", "Case 2024-123456", "Ticket 202611-1234567", "2019 - 2024", "2019-2024-2026",
    "Please call the team about the offer. Requisition 12345678 closes soon.",
    "Range 120,000.00 - 150,000.00 annually", "Base 95,000.00 - 130,000.00 plus bonus",
])
def test_digit_runs_that_are_not_phones_do_not_stop_an_ad(text):
    assert scan(text) == []


@pytest.mark.parametrize("text", [
    "+381 11 234 5678", "+381-64-123-4567", "+381.64.123.4567", "+1 (555) 123-4567", "+44 20 7946 0958", "+381641234567",
    "00381 64 123 4567", "00381641234567", "(011) 234-5678", "011 234 5678", "064/123-4567", "064 123 4567", "0641234567",
    "Tel: 381641234567", "Phone 12345678", "WhatsApp 641234567", "call us on 641234567", "Mobile: 641 234 567", "call 555 123 4567",
    "555-123-4567", "1-800-555-1234", "Telefon: 011-2345678",
])
def test_real_phone_shapes_still_stop_an_ad(text):
    assert scan(f"Contact us. {text} Thanks") == ["a phone number"]


def test_the_strict_scan_is_unchanged_for_everything_else():
    assert find_leaks("Requisition # 12345678") == ["a phone number"]  # CV redaction and other callers: still broad and fail-closed
    assert find_leaks("Contact 12345678") == ["a phone number"]
    assert find_leaks("Req 12345678", ad_text=True) == []


def test_the_owners_own_number_is_found_in_any_shape():
    assert "the owner's phone number" in scan("Ref 381645550123 for details")
    assert "the owner's phone number" in scan("Call +381 64 555 0123")
    assert "the owner's phone number" in scan("Requisition 645550123")  # a run equal to part of the owner's number is still refused


def test_other_identifiers_are_still_found_in_an_ad_prompt():
    assert "an e-mail address" in scan("Write to someone@example.test")
    assert "the owner's name" in scan("Ask Zorana")


@pytest.mark.parametrize("number", ["555-123-4567", "555.123.4567", "1-800-555-1234", "(555) 123-4567", "1(555) 123-4567", "1 (555) 123 4567"])
def test_north_american_numbers_in_an_ad_are_masked_so_the_ad_is_kept(number):
    text, counts = mask_ad_contacts(f"Accessibility line: {number}. Thanks")
    assert counts["phones"] == 1 and "[PHONE]" in text and not any(ch.isdigit() for ch in text)
    assert scan(text) == []


@pytest.mark.parametrize("text", ["Req 123-456-7890x", "ISBN 1234-5678", "Version 3.14.159.2653", "ID 20261119"])
def test_the_north_american_mask_does_not_touch_other_numbers(text):
    masked, counts = mask_ad_contacts(text)
    assert counts["phones"] == 0 and masked == text
