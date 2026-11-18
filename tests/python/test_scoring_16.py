"""Top-of-list fixes, scoringVersion 1.6 (owner brief 2026-11-18): skill dimension without role-title tokens and with the ad's
requirements, role ceiling, security-clearance blocker, location eligibility cap, unmet must-requirement ceiling.
The smoke-test ads of the brief are never used here: every ad below is synthetic."""

import copy

import pytest

import blocking
import ceilings
import labels
import remote_text
import scorer
from dimensions import location_match, skill_match
from scorer import score_job
from test_eligibility import BODY, ad, prefs

STACK = {
    "skillsMap": {"p": ["roadmap", "discovery"]},
    "roleFamily": "product",
    "languages": ["Serbian (native)", "English (fluent)"],
    "roleStrategy": {"primaryTargetRoles": ["Product Manager"], "secondaryTargetRoles": ["Product Owner"], "searchRoleVariants": ["Technical Product Manager"]},
}
PAD = " ".join(["The team ships the product to customers every week and we value clear writing and calm planning."] * 12)


def intel(**kw):
    return {**copy.deepcopy(STACK), "jobFitPreferences": {**prefs(), **kw.pop("prefs", {})}, **kw}


def job(**kw):
    base = ad(location="Belgrade, Serbia", visaSponsorship="not_mentioned")
    base["description"] = base["description"] + " " + PAD
    base.update(kw)
    return base


# --- remote text -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["This role is fully remote.", "We are 100% remote", "You can work from anywhere", "Working remotely from anywhere in the world",
                                  "<p>Entirely remote team</p>", "completely remote"])
def test_clear_remote_wording_is_found(text):
    assert remote_text.clear_remote_text(text)


@pytest.mark.parametrize("text", ["", None, "Remote work is possible two days a week", "This is not a fully remote position", "no 100% remote option",
                                  "hybrid, remote friendly", "remote-first culture",
                                  "For fully remote workers we provide extra support for their home office.", "Two weeks of 'Work from Anywhere' each year."])
def test_negated_or_vague_wording_is_not(text):
    assert remote_text.clear_remote_text(text) is None


def test_clear_text_wins_over_a_structured_field_that_says_onsite():
    onsite = job(workMode="onsite", isRemote=False, description="This role is fully remote. " + PAD)
    assert location_match.is_remote_job(onsite) is True
    assert location_match.is_remote_job(job(workMode="onsite", isRemote=False)) is False


# --- fix 1: skill dimension --------------------------------------------------------------------------------------------

BANK = {"atsKeywordBank": {"highPriority": ["Product Manager", "Technical Product Manager", "Product Owner", "roadmap", "experimentation"], "mediumPriority": [], "supportingKeywords": []}}


def test_role_title_keywords_are_not_skills():
    vocab = skill_match.role_title_vocabulary(intel(**BANK))
    assert skill_match.is_role_title_keyword("Product Manager", vocab)
    assert skill_match.is_role_title_keyword("Senior Technical Product Manager", vocab)
    assert skill_match.is_role_title_keyword("Product Owner", vocab)
    assert not skill_match.is_role_title_keyword("roadmap", vocab)
    assert not skill_match.is_role_title_keyword("Product Strategy", vocab)
    assert not skill_match.is_role_title_keyword("Product Leadership", vocab)


def test_matched_skills_hold_skills_only_and_the_title_is_not_matched_against_the_bank():
    j = job(title="Technical Product Manager", description="We need roadmap ownership and experimentation. " + PAD)
    score, reasons, matched, missing = skill_match.score_skill_match(j, intel(**BANK))
    assert "roadmap" in matched and "experimentation" in matched
    assert not any("Product Manager" in m or "Product Owner" in m for m in matched)
    # a title alone earns no skill credit: the same ad with a description that names no skill
    bare = job(title="Roadmap experimentation lead", description="Join us. " + PAD)
    _, _, matched_bare, _ = skill_match.score_skill_match(bare, intel(**BANK))
    assert matched_bare == []


def test_uncovered_requirements_lower_the_skill_score():
    musts = ["Five years of mobile gaming monetisation", "Shipped live-ops economy tuning", "Led a studio of thirty engineers"]
    plain = job(description="We need roadmap ownership and experimentation. " + PAD)
    with_reqs = {**plain, "llmFacts": {**plain["llmFacts"], "mustHaves": musts}}
    without_reqs = {**plain, "llmFacts": {**plain["llmFacts"], "mustHaves": []}}
    s_with = skill_match.score_skill_match(with_reqs, intel(**BANK))[0]
    s_without = skill_match.score_skill_match(without_reqs, intel(**BANK))[0]
    assert s_with < s_without  # unmet requirements cost points; an ad that lists none is scored on the bank alone
    covered = {**plain, "llmFacts": {**plain["llmFacts"], "mustHaves": ["roadmap discovery"]}}
    assert skill_match.score_skill_match(covered, intel(**BANK))[0] > s_with


def test_requirement_share_counts_missing_over_all_usable_requirements():
    j = job(llmFacts={"roleTrack": "product_management", "mustHaves": ["roadmap discovery", "Shipped live-ops economy tuning", "Led a studio of thirty engineers", "x"]})
    info = skill_match.requirement_share(j, intel(**BANK))
    assert info["usable"] == info["covered"] + info["uncovered"] and info["usable"] >= 3
    assert info["share"] == pytest.approx(info["uncovered"] / info["usable"])
    assert skill_match.requirement_share(job(llmFacts={"roleTrack": "product_management", "mustHaves": []}), intel(**BANK)) is None


# --- fix 2: role ceiling ------------------------------------------------------------------------------------------------

def scored_row(**kw):
    return score_job(job(**kw), intel(**BANK))


@pytest.mark.parametrize("cls", ["other", "not available"])
def test_role_class_other_or_not_available_caps_at_weak_and_the_verdict_follows(cls):
    row = scored_row()
    row["matchScore"], row["scoreBeforeCaps"] = 83, 83
    row["matchLabel"], row["applyRecommendation"], row["priority"] = "Strong", "Apply", "P1"
    row["roleClass"] = cls
    ceilings.apply_role_ceiling([row])
    assert row["matchScore"] == ceilings.ROLE_CEILING == 54
    assert row["matchLabel"] == "Weak" and row["applyRecommendation"] == "Maybe" and row["priority"] == "P3"
    assert row["hardCapped"] is True and any(r.startswith("Capped: role class") for r in row["reasons"])
    assert row["scoreBeforeCaps"] == 83  # the uncapped number is kept for the list tie-break


@pytest.mark.parametrize("cls", ["target", "adjacent"])
def test_target_and_adjacent_are_not_capped(cls):
    row = scored_row()
    row["matchScore"] = 83
    row["roleClass"] = cls
    ceilings.apply_role_ceiling([row])
    assert row["matchScore"] == 83


def test_a_low_score_or_no_score_is_left_alone_and_a_blocked_ad_keeps_its_blocked_verdict():
    low, none, blocked = scored_row(), scored_row(), scored_row()
    low["matchScore"], none["matchScore"] = 30, None
    blocked["matchScore"], blocked["blockedBy"] = 80, [{"kind": "language", "text": "x"}]
    blocked["applyRecommendation"] = blocked["priority"] = labels.BLOCKED_LABEL
    for r in (low, none, blocked):
        r["roleClass"] = "other"
    ceilings.apply_role_ceiling([low, none, blocked])
    assert low["matchScore"] == 30 and none["matchScore"] is None
    assert blocked["matchScore"] == 54 and blocked["applyRecommendation"] == labels.BLOCKED_LABEL
    assert blocked["blockedFrom"] == {"applyRecommendation": "Maybe", "priority": "P3"}


# --- fix 3: security clearance and citizenship ---------------------------------------------------------------------------

def with_quote(quote, importance="must", **extra):
    j = job(description=f"{BODY} {quote} {PAD}", **extra)
    j["llmFacts"] = {**j["llmFacts"], "requirements": [{"kind": "other", "text": quote, "importance": importance, "postingQuote": quote}]}
    return j


@pytest.mark.parametrize("quote", [
    "Active Top Secret security clearance required.",
    "Must hold an active TS/SCI clearance.",
    "Ability to obtain a U.S. security clearance is required.",
    "Applicants must be a U.S. citizen.",
    "This position requires U.S. citizenship.",
    "Candidates must be a U.S. person as defined by ITAR.",
    "Public Trust clearance required.",
])
def test_a_verbatim_unsoftened_clearance_or_us_person_requirement_is_a_blocker(quote):
    state = blocking.clearance_state(with_quote(quote))
    assert state and state["quote"] and quote.startswith(state["quote"][:20])
    assert [b["kind"] for b in blocking.blockers(None, [], None, state)] == ["security_clearance"]


@pytest.mark.parametrize("quote", [
    "Security clearance is a plus.",
    "An active clearance is preferred.",
    "No security clearance required.",
    "Security clearance is not required for this role.",
    "EU citizenship is required.",
    "We run a background check before the start date.",
    "You will clear blockers for the team.",
])
def test_softened_negated_or_other_wording_is_not(quote):
    assert blocking.clearance_state(with_quote(quote)) is None


def test_the_ad_text_alone_is_enough_when_the_extraction_marked_nothing():
    j = job(description=f"{BODY} All roles require an active Secret security clearance. {PAD}")
    assert blocking.clearance_state(j)["kind"] == "security_clearance"
    assert blocking.clearance_state(job(description=f"{BODY} Security clearance is a plus. {PAD}")) is None


def test_an_optional_extraction_mark_does_not_block():
    assert blocking.clearance_state(with_quote("Top secret clearance required.", importance="nice")) is not None  # the sentence itself still says required
    j = with_quote("Clearance is welcome.", importance="nice")
    assert blocking.clearance_state(j) is None


def test_a_clearance_block_changes_the_verdict_not_the_number():
    plain = score_job(job(), intel(**BANK))
    blocked = score_job(with_quote("Active Top Secret security clearance required."), intel(**BANK))
    assert [b["kind"] for b in blocked["blockedBy"]] == ["security_clearance"]
    assert blocked["applyRecommendation"] == labels.BLOCKED_LABEL and blocked["blockedFrom"] is not None
    assert plain["blockedBy"] == []
    # same ad, same dimensions: only the blocker differs
    same = score_job({**with_quote("Active Top Secret security clearance required.")}, intel(**BANK))
    assert same["matchScore"] == blocked["matchScore"]


# --- fix 4: location eligibility ----------------------------------------------------------------------------------------

def foreign(**kw):
    base = {"location": "Austin, TX, USA", "workMode": "onsite", "isRemote": False, "llmFacts": {"roleTrack": "product_management", "jobCountry": "US", "workMode": "onsite"}}
    return job(**{**base, **kw})


NO_RELOCATION = {"country": "Serbia", "relocation": "none", "allowedLocations": []}


def test_onsite_outside_the_relocation_scope_is_out_of_scope_and_hybrid_too():
    assert location_match.outside_relocation_scope(foreign(), NO_RELOCATION)
    hybrid = foreign(workMode="hybrid")
    assert location_match.outside_relocation_scope(hybrid, NO_RELOCATION)


def test_in_scope_unknown_or_remote_is_not_out_of_scope():
    assert location_match.outside_relocation_scope(foreign(), {**NO_RELOCATION, "relocation": "abroad"}) is None
    assert location_match.outside_relocation_scope(foreign(), {**NO_RELOCATION, "relocation": "anywhere"}) is None
    home = job(location="Belgrade, Serbia", workMode="onsite", llmFacts={"jobCountry": "RS", "workMode": "onsite"})
    assert location_match.outside_relocation_scope(home, NO_RELOCATION) is None
    # unknown mode or unknown country: unknown never caps
    assert location_match.outside_relocation_scope(foreign(workMode=None, llmFacts={"roleTrack": "product_management", "jobCountry": "US", "workMode": "unclear"}), NO_RELOCATION) is None
    nowhere = job(location="", workMode="onsite", llmFacts={"roleTrack": "product_management", "workMode": "onsite"})
    assert location_match.outside_relocation_scope(nowhere, NO_RELOCATION) is None
    assert location_match.outside_relocation_scope(foreign(isRemote=True, workMode="remote"), NO_RELOCATION) is None


def test_clear_remote_text_wins_over_a_structured_onsite_field():
    j = foreign(description=f"{BODY} This role is fully remote. {PAD}")
    assert location_match.outside_relocation_scope(j, NO_RELOCATION) is None
    assert location_match.score_location_match(j, {"jobFitPreferences": NO_RELOCATION})[0] >= 85


def test_allowed_locations_set_the_scope_too():
    far = foreign()
    assert location_match.outside_relocation_scope(far, {"country": "Serbia", "relocation": "anywhere", "allowedLocations": ["RS", "REMOTE"]})


def test_the_location_dimension_is_low_and_the_score_is_capped_at_weak_for_a_hybrid_job_out_of_scope():
    j = foreign(workMode="hybrid")
    i = intel(prefs=NO_RELOCATION, **BANK)
    row = score_job(j, i)
    assert row["locationMatch"] == location_match.ONSITE_ELSEWHERE
    assert row["matchScore"] <= ceilings.LOCATION_CAP == 54 and row["matchLabel"] in ("Weak", "Reject")
    assert all(b["kind"] != "location" for b in row["blockedBy"])  # a cap, not a block
    assert any(r.startswith("Capped: onsite") for r in row["reasons"]) and row["hardCapped"] is True


# --- fix 5: unmet must-requirement ceiling -------------------------------------------------------------------------------

def unmet_job():
    musts = ["Five years of mobile gaming monetisation", "Shipped live-ops economy tuning", "Led a studio of thirty engineers", "Owned a console launch pipeline"]
    j = job(description="We need roadmap ownership and experimentation. " + PAD)
    j["llmFacts"] = {**j["llmFacts"], "mustHaves": musts}
    return j


def test_the_ceiling_is_off_until_a_theta_is_set(monkeypatch):
    assert scorer.UNMET_MUST_THETA is None
    row = score_job(unmet_job(), intel(**BANK))
    assert row["unmetMustShare"] is not None and row["unmetMustShare"] >= 0.5


def test_a_share_at_or_over_theta_caps_at_good(monkeypatch):
    monkeypatch.setattr(scorer, "UNMET_MUST_THETA", 0.3)
    monkeypatch.setattr(scorer, "_weighted_total", lambda dims, weights: 88)
    row = score_job(unmet_job(), intel(**BANK))
    assert row["matchScore"] == ceilings.UNMET_CAP == 69 and row["matchLabel"] == "Good"
    assert any(r.startswith("Capped: ") and "requirements" in r for r in row["reasons"]) and row["hardCapped"] is True
    covered = job()
    covered["llmFacts"] = {**covered["llmFacts"], "mustHaves": ["roadmap discovery", "experimentation roadmap"]}
    assert score_job(covered, intel(**BANK))["matchScore"] == 88  # share under theta: no cap


def test_an_ad_with_no_usable_requirements_is_never_capped(monkeypatch):
    monkeypatch.setattr(scorer, "UNMET_MUST_THETA", 0.3)
    monkeypatch.setattr(scorer, "_weighted_total", lambda dims, weights: 88)
    row = score_job(job(), intel(**BANK))
    assert row["unmetMustShare"] is None and row["matchScore"] == 88


# --- the version --------------------------------------------------------------------------------------------------------

def test_the_scoring_version_is_1_6():
    assert scorer.SCORING_VERSION == "1.6"
    assert score_job(job(), intel(**BANK))["scoringVersion"] == "1.6"


def test_every_fix_can_be_switched_off_for_the_leave_one_out_measurement():
    assert scorer.ALL_FIXES == frozenset({"skill", "role_ceiling", "clearance", "location", "unmet"})
    assert scorer.active_fixes() == scorer.ALL_FIXES
