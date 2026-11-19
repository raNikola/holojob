"""A recruiter's e-mail or phone in the ad text is masked before the matcher prompt is built; the owner-identifier scan itself is not loosened."""

from match_engine import matcher
from redact import find_leaks, mask_ad_contacts

AD = "Great role 2019 - 2024 experience. Write to jane.doe@example.com or call +381 11 234 5678 today."


def test_mask_replaces_contacts_and_keeps_date_ranges():
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


def test_owner_data_in_an_ad_is_still_caught():
    assert find_leaks(mask_ad_contacts("Contact Zed Quux for details")[0], "Zed Quux") == ["the owner's name"]
