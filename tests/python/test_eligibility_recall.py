"""Missed-block audit: markdown in the stored text, and a refusal the extraction did not mark (Step 2 rule, scoringVersion 1.5)."""

import pytest

import eligibility as el
from test_eligibility import ad, prefs

ACI_TEXT = (
    "Own the roadmap. *Applicants*\n***must be currently authorized to work in the US***\n*on a full-time basis. This position*\n"
    "***does not offer sponsorship***\n*for employment visa status or work permit now or in the future.*\n"
)
ACI_QUOTE = ("Applicants must be currently authorized to work in the US on a full-time basis. This position does not offer "
             "sponsorship for employment visa status or work permit now or in the future.")


def test_markdown_emphasis_in_the_stored_text_does_not_hide_a_verbatim_quote():
    assert el.quote_in_text(ACI_QUOTE, ACI_TEXT)
    assert el.quote_in_text("Visa sponsorship is not available for this position.", "Visa sponsorship is\n**not**\navailable for this position.")
    assert not el.quote_in_text("Visa sponsorship is available for this position.", "Visa sponsorship is\n**not**\navailable for this position.")


def test_a_refusing_quote_wrapped_in_markdown_is_a_refusal():
    job = ad(visaSponsorship="not_offered", visaEvidence=ACI_QUOTE)
    job["description"] = ACI_TEXT
    r = el.assess(job, prefs())
    assert r["state"] == el.REFUSED and r["kind"] == "refused"


@pytest.mark.parametrize("sentence", [
    "We are unable to sponsor or take over sponsorship of an employment visa.",
    "Candidates must be authorized to work in the U.S. without requiring visa transfer or sponsorship, now or in the future.",
    "USAA does not provide visa sponsorship for this role.",
    "We do not sponsor applicants for work visas.",
    "Candidates must be legally authorized to work in the us, as we cannot sponsor visas at this time.",
])
@pytest.mark.parametrize("fact", ["not_mentioned", None])
def test_a_refusal_in_the_ad_text_the_extraction_did_not_mark_is_still_a_refusal(sentence, fact):
    facts = {"visaSponsorship": fact} if fact else {}
    job = ad(extra=sentence, **facts)
    r = el.assess(job, prefs())
    assert r["state"] == el.REFUSED and r["kind"] == "refused_in_text"
    assert el.quote_in_text(r["quote"], job["description"])  # the quote is the ad's own sentence


def test_a_refusal_in_the_text_keeps_the_b2b_exception():
    job = ad(extra="We do not sponsor work visas. Contractors on a B2B basis are welcome.", visaSponsorship="not_mentioned")
    r = el.assess(job, prefs(b2bAvailable=True))
    assert r["state"] == el.UNKNOWN and r["kind"] == "b2b_exception"


@pytest.mark.parametrize("sentence", [
    "We sponsor visas for the right candidate.",
    "Visa sponsorship is available.",
    "Must be authorized to work in the US.",
    "We do not discriminate. Relocation support is offered.",
])
def test_text_without_a_refusal_stays_silent(sentence):
    assert el.assess(ad(extra=sentence, visaSponsorship="not_mentioned"), prefs())["kind"] == "silent"


def test_an_offer_marked_by_the_extraction_is_not_overridden_by_the_text_scan():
    job = ad(extra="We do not sponsor work visas for contractors. Sponsorship is available for employees.",
             visaSponsorship="offered", visaEvidence="Sponsorship is available for employees.")
    assert el.assess(job, prefs())["state"] == el.OFFERED


def test_a_refusal_in_the_text_changes_nothing_in_an_authorized_country():
    assert el.assess(ad("Warsaw, Poland", extra="We do not sponsor work visas."), prefs())["state"] == el.AUTHORIZED


def test_an_unread_ad_is_not_scanned():
    job = ad(extra="We do not sponsor work visas.")
    job["llmFacts"] = None
    assert el.assess(job, prefs())["kind"] == "not_read"
