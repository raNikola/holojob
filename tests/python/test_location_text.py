"""The location rule: office, remote with a stated geography, remote with none, stated open (fictional ads)."""

import pytest

import work_authorization as wa
from match_engine.gates import location_result
from scorer import score_job

PREFS = {
    "country": "Serbia",
    "preferredLocations": ["Niš"],
    "relocation": "none",
    "workAuthorization": {"holds": [{"jurisdiction": "RS"}, {"jurisdiction": "EU"}], "openToSponsorship": False},
    # US is not allowed here, so "US only" is a disallowed geography (the owner's real list includes it).
    "allowedLocations": ["REMOTE", "EU", "RS"],
}


def ad(location="London, England, UK", description="", remote=False, **facts):
    return {"jobId": "x", "title": "Product Manager", "company": "Acme", "location": location,
            "description": description, "isRemote": remote, "llmFacts": facts or None}


def read(job):
    return wa.authorization_status(job, PREFS)


def test_london_onsite_is_outside_and_capped():
    result = read(ad(description="Based in our London office, five days a week."))
    assert result["status"] == wa.OUTSIDE_ALLOWED and "location" not in result
    scored = score_job(ad(description="Based in our London office, five days a week."), {"jobFitPreferences": PREFS})
    assert scored["matchScore"] <= 40


def test_remote_uk_only_is_outside_and_capped():
    job = ad(description="Remote. This role is open to UK only.", remote=True)
    result = read(job)
    assert result["status"] == wa.OUTSIDE_ALLOWED and result["location"]["state"] == "fail"
    assert score_job(job, {"jobFitPreferences": PREFS})["matchScore"] <= 40


def test_remote_eu_is_unknown_with_a_flag_and_no_cap():
    job = ad(description="Remote (EU). Join our product team.", remote=True)
    result = read(job)
    assert result["location"]["state"] == "unknown" and result["location"]["flag"] == "Verify location"
    assert result["status"] != wa.OUTSIDE_ALLOWED
    scored = score_job(job, {"jobFitPreferences": PREFS})
    assert any(r.startswith("Verify location") for r in scored["reasons"])
    assert not any(r.startswith("Capped") for r in scored["reasons"])


def test_remote_worldwide_is_a_pass():
    job = ad(description="Remote worldwide: we hire anywhere in the world.", remote=True)
    result = read(job)
    assert result["location"]["state"] == "pass" and result["location"]["flag"] is None


def test_remote_open_to_serbia_or_the_balkans_is_a_pass():
    assert read(ad(description="Remote role, candidates based in Serbia welcome.", remote=True))["location"]["state"] == "pass"
    assert read(ad(description="Remote, open to candidates in the Balkans.", remote=True))["location"]["state"] == "pass"


def test_board_says_remote_but_the_text_says_us_only():
    job = ad(location="Remote", description="Fully remote, but you must be based in the US.", remote=True)
    result = read(job)
    assert result["status"] == wa.OUTSIDE_ALLOWED and result["location"]["state"] == "fail"


def test_empty_text_with_a_remote_board_is_unknown_not_a_pass():
    result = read(ad(location="Remote", description="", remote=True))
    assert result["location"]["state"] == "unknown" and result["location"]["flag"] == "Verify location"


def test_a_remote_role_in_the_text_beats_the_boards_office_city():
    # Board: not remote, London. Text: "This is a remote role". No geography is stated.
    result = read(ad(description="This is a remote role, with occasional travel to our offices."))
    assert result["status"] != wa.OUTSIDE_ALLOWED and result["location"]["state"] == "unknown"


@pytest.mark.parametrize("text", [
    "For fully remote workers we provide extra support for their home office.",
    "Two weeks of 'Work from Anywhere' each year.",
    "London / Hybrid, 3 days in office. Remote working arrangements are flexible.",
    "Cohere is remote-friendly, with offices in Toronto and London.",
])
def test_benefit_lines_and_hybrid_are_not_a_remote_signal(text):
    assert read(ad(description=text))["status"] == wa.OUTSIDE_ALLOWED


def test_extracted_remote_eligibility_keeps_its_work_permit_reading():
    # Only the ad's own words confirm a location cap; the facts stay a visa question (45, not 40).
    result = read(ad(description="Remote.", remote=True, remoteEligibility=["GB"]))
    assert result["status"] == wa.NEEDS_VISA_SILENT


def test_a_refused_visa_stays_stricter_than_the_location_cap():
    job = ad(description="Remote, UK only.", remote=True, remoteEligibility=["GB"], visaSponsorship="not_offered")
    assert read(job)["status"] == wa.NEEDS_VISA_REFUSED


@pytest.mark.parametrize("text", ["Our impact is worldwide.", "A globally distributed organization."])
def test_worldwide_words_about_the_employer_are_not_availability(text):
    assert read(ad(description=text, remote=True))["location"]["state"] == "unknown"


def test_remote_alone_never_passes_the_location_gate():
    gates = {"workAuthorization": PREFS["workAuthorization"], "allowedLocations": PREFS["allowedLocations"],
             "country": "Serbia", "relocation": "none", "preferredLocations": ["Niš"]}
    assert location_result(ad(description="", remote=True), gates) == "unknown"
    assert location_result(ad(description="Remote worldwide.", remote=True), gates) == "pass"
    assert location_result(ad(description="Remote, UK only.", remote=True), gates) == "fail"


def test_unknown_location_does_not_change_the_score():
    unknown = score_job(ad(description="Remote role.", remote=True), {"jobFitPreferences": PREFS})
    passed = score_job(ad(description="Remote role, open worldwide.", remote=True), {"jobFitPreferences": PREFS})
    assert unknown["matchScore"] == passed["matchScore"]
