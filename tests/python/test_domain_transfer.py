"""Wave 3: industry experience that is proven versus industry experience that is only assumed to transfer."""

import domain_transfer as dt
from dimensions.industry_match import score_industry_match, score_industry_match_detail
from scorer import UNRELATED_TITLE_CAP, score_job

TELECOM_PM = {"role": "Program Manager", "period": "2018–2022", "domains": ["telecom"], "capabilities": ["regulatory", "vendor_management"]}
BASE = {
    "roleFamily": "product",
    "roleStrategy": {"primaryTargetRoles": ["Senior Product Manager"], "searchRoleVariants": []},
    "atsKeywordBank": {"highPriority": ["Senior Product Manager", "Roadmap"]},
    "jobFitPreferences": {"preferredIndustries": [], "avoidedIndustries": []},
    "historyEntries": [TELECOM_PM],
}
BANK_AD = ("Senior Product Manager for our payments platform at a retail bank. You will own the roadmap, work with regulators "
           "on compliance and with stakeholders across the bank. Requirements: five years of product experience.")


def job(title="Senior Product Manager", description=BANK_AD):
    return {"jobId": "t", "title": title, "company": "Acme", "description": description, "location": "Remote", "isRemote": True}


def test_an_ad_in_a_neighbouring_industry_gets_an_assumed_bridge_with_a_checkable_reason():
    result = dt.assess(job(), BASE)
    assert result["applied"] and result["bonus"] == dt.BRIDGE_BONUS and not result["proven"]
    [bridge] = result["bridges"]
    assert (bridge["from"], bridge["to"], bridge["capability"], bridge["role"], bridge["period"]) == (
        "telecom", "banking", "regulatory", "Program Manager", "2018–2022")
    [reason] = result["reasons"]
    assert reason.startswith("Transferable (assumed, +8)")
    assert "your Program Manager (2018–2022)" in reason and "telecom" in reason and "regulatory compliance" in reason
    assert "Not proven experience in banking" in reason, "an assumption is never presented as a confirmed fact"


def test_proven_experience_in_the_ads_own_industry_is_labelled_proven_and_not_assumed():
    intelligence = {**BASE, "historyEntries": [{**TELECOM_PM, "domains": ["telecom", "banking"]}]}
    result = dt.assess(job(), intelligence)
    assert result["bonus"] == dt.PROVEN_BONUS and result["proven"] and not result["bridges"]
    assert result["reasons"][0].startswith("Proven industry experience") and "assumed" not in result["reasons"][0]


def test_no_bridge_without_the_capability_in_the_candidates_own_entry():
    intelligence = {**BASE, "historyEntries": [{**TELECOM_PM, "capabilities": ["vendor_management"]}]}
    assert dt.assess(job(), intelligence)["bonus"] == 0


def test_no_bridge_when_the_ad_does_not_ask_for_the_capability():
    quiet = "Senior Product Manager for our payments platform at a retail bank. You will own the roadmap and the cards product."
    assert dt.assess(job(description=quiet), BASE)["bonus"] == 0


def test_no_bridge_without_an_edge_between_the_two_industries():
    intelligence = {**BASE, "historyEntries": [{**TELECOM_PM, "domains": ["logistics"]}]}
    assert dt.assess(job(), intelligence)["bonus"] == 0


def test_no_history_no_credit():
    assert dt.assess(job(), {k: v for k, v in BASE.items() if k != "historyEntries"})["bonus"] == 0


def test_bridges_are_capped():
    entries = [
        {"role": "A", "period": "", "domains": ["telecom"], "capabilities": ["regulatory", "vendor_management"]},
        {"role": "B", "period": "", "domains": ["insurance"], "capabilities": ["regulatory"]},
        {"role": "C", "period": "", "domains": ["public_sector"], "capabilities": ["regulatory"]},
    ]
    result = dt.assess(job(), {**BASE, "historyEntries": entries})
    assert len(result["bridges"]) == 3 and result["bonus"] == dt.MAX_BONUS
    assert sum("(assumed, +8)" in r for r in result["reasons"]) == 2 and "at the cap" in result["reasons"][2]


def test_the_industry_score_rises_by_the_bonus_only_and_the_old_score_is_unchanged_without_history():
    plain = {k: v for k, v in BASE.items() if k != "historyEntries"}
    base_score, _ = score_industry_match(job(), plain)
    score, reasons, transferability = score_industry_match_detail(job(), BASE)
    assert score == base_score + dt.BRIDGE_BONUS and transferability["applied"] and any(r.startswith("Transferable") for r in reasons)


def test_an_avoided_industry_gets_nothing():
    intelligence = {**BASE, "jobFitPreferences": {"preferredIndustries": [], "avoidedIndustries": ["bank"]}}
    score, reasons, transferability = score_industry_match_detail(job(), intelligence)
    assert score == 20 and transferability is None and not any("Transferable" in r for r in reasons)


def test_an_unrelated_title_gets_no_transfer_and_stays_capped():
    designer = job(title="Senior Product Designer")
    result = score_job(designer, BASE)
    assert result["matchScore"] <= UNRELATED_TITLE_CAP and result["hardCapped"]
    assert result["transferability"]["applied"] is False and result["transferability"]["bonus"] == 0
    assert result["transferability"]["skipped"] == "title_unrelated"
    assert "Industry transfer not applied: the title is outside your target roles" in result["reasons"]
    plain = score_job(designer, {k: v for k, v in BASE.items() if k != "historyEntries"})
    assert result["industryMatch"] == plain["industryMatch"], "no point of transfer reached the dimension"


def test_a_related_title_gets_the_bonus_in_the_result_and_the_reason_list():
    result = score_job(job(), BASE)
    assert result["transferability"]["applied"] and result["transferability"]["bonus"] == dt.BRIDGE_BONUS
    assert any(r.startswith("Transferable (assumed") for r in result["reasons"])
    plain = score_job(job(), {k: v for k, v in BASE.items() if k != "historyEntries"})
    assert result["industryMatch"] - plain["industryMatch"] == dt.BRIDGE_BONUS
    assert result["matchScore"] - plain["matchScore"] <= 2, "the industry weight keeps the effect small"
