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


def test_the_ads_requirements_do_not_move_the_skill_score():
    # owner decision 2026-11-19: token overlap is not a valid test of a met requirement, so the requirements stay reported, never scored
    musts = ["Five years of mobile gaming monetisation", "Shipped live-ops economy tuning", "Led a studio of thirty engineers"]
    plain = job(description="We need roadmap ownership and experimentation. " + PAD)
    with_reqs = {**plain, "llmFacts": {**plain["llmFacts"], "mustHaves": musts}}
    without_reqs = {**plain, "llmFacts": {**plain["llmFacts"], "mustHaves": []}}
    assert skill_match.score_skill_match(with_reqs, intel(**BANK))[0] == skill_match.score_skill_match(without_reqs, intel(**BANK))[0]
    assert set(musts) <= set(skill_match.score_skill_match(with_reqs, intel(**BANK))[3])  # reported first in missingSkills


# --- fix 2: role ceiling ------------------------------------------------------------------------------------------------

def scored_row(**kw):
    return score_job(job(**kw), intel(**BANK))


def test_role_class_other_caps_at_weak_and_the_verdict_follows():
    cls = "other"
    row = scored_row()
    row["matchScore"], row["scoreBeforeCaps"] = 83, 83
    row["matchLabel"], row["applyRecommendation"], row["priority"] = "Strong", "Apply", "P1"
    row["roleClass"] = cls
    ceilings.apply_role_ceiling([row])
    assert row["matchScore"] == ceilings.ROLE_CEILING == 54
    assert row["matchLabel"] == "Weak" and row["applyRecommendation"] == "Maybe" and row["priority"] == "P3"
    assert row["hardCapped"] is True and any(r.startswith("Capped: role class") for r in row["reasons"])
    assert row["scoreBeforeCaps"] == 83  # the uncapped number is kept for the list tie-break


@pytest.mark.parametrize("cls", ["target", "adjacent", "not available", None])
def test_target_adjacent_and_unknown_are_not_capped(cls):
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


@pytest.mark.parametrize("quote", [
    "Government security clearance.",
    "TS/SCI Clearance.",
    "Security clearance",
    "Our client specifies nationality criteria for individuals seeking security clearance.",
    "Security clearance sponsorship is part of our benefits.",
])
def test_a_bare_mention_is_unconfirmed_never_blocked(quote):
    """Owner rule 2026-11-19: Blocked only when the sentence says the ad REQUIRES it; a mention is a flag beside the score."""
    for j in (with_quote(quote), job(description=f"{BODY} {quote} {PAD}")):
        assert blocking.clearance_state(j) is None
        assert blocking.clearance_unconfirmed(j)["quote"]
    row = score_job(with_quote(quote), intel(**BANK))
    assert row["blockedBy"] == [] and row["clearanceUnconfirmed"]
    assert any(r.startswith("Clearance unconfirmed") for r in row["reasons"])


@pytest.mark.parametrize("quote", [
    "Ability to obtain NPPV3 security clearance requiring UK residency",
    "Ability to obtain a Secret clearance",
    "An active Secret clearance is required",
    "Must be able to obtain and maintain a US DOW Security Clearance",
])
def test_demand_wording_in_the_sentence_blocks(quote):
    assert blocking.clearance_state(with_quote(quote)) and blocking.clearance_unconfirmed(with_quote(quote)) is None


def test_a_negated_or_softened_mention_is_neither_blocked_nor_flagged():
    for q in ("No security clearance required.", "Security clearance is a plus."):
        assert blocking.clearance_state(with_quote(q)) is None and blocking.clearance_unconfirmed(with_quote(q)) is None


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


# --- fix 5: unmet must-requirement ceiling from the evidence engine statuses ---------------------------------------------

def engine_row(statuses, score=80, importance="must"):
    reqs = [{"id": f"r{n}", "importance": importance, "status": st, "postingQuote": "q"} for n, st in enumerate(statuses)]
    return {"matchScore": score, "scoreBeforeCaps": score, "matchLabel": "Strong", "applyRecommendation": "Apply", "priority": "P1", "redFlags": [],
            "blockedBy": [], "reasons": [], "engineShadow": {"requirements": reqs}}


def test_variant_a_counts_contradicted_only_and_variant_b_adds_not_evidenced():
    row = engine_row(["CONTRADICTED", "NOT_EVIDENCED", "NOT_EVIDENCED", "MET", "UNKNOWN"])
    a, b = ceilings.unmet_share(row, "A"), ceilings.unmet_share(row, "B")
    assert (a["unmet"], a["decided"], a["share"]) == (1, 4, 0.25)  # UNKNOWN is in neither count
    assert (b["unmet"], b["decided"], b["share"]) == (3, 4, 0.75)


def test_no_answers_or_too_few_decided_must_requirements_means_no_share():
    assert ceilings.unmet_share({"matchScore": 80}) is None
    assert ceilings.unmet_share(engine_row(["CONTRADICTED", "CONTRADICTED"])) is None  # 2 decided < 3
    assert ceilings.unmet_share(engine_row(["CONTRADICTED"] * 3, importance="nice")) is None  # nice-to-haves are not must requirements
    assert ceilings.unmet_share(engine_row(["UNKNOWN"] * 5)) is None


def test_the_ceiling_is_off_without_a_theta(monkeypatch):
    monkeypatch.setattr(ceilings, "UNMET_THETA", None)
    row = engine_row(["CONTRADICTED"] * 4)
    assert ceilings.apply_unmet_ceiling([row]) == 0 and row["matchScore"] == 80
    assert ceilings.apply_unmet_ceiling([engine_row(["CONTRADICTED"] * 4)]) == 0  # still off
    monkeypatch.setattr(ceilings, "UNMET_THETA", 0.3)
    assert ceilings.apply_unmet_ceiling([engine_row(["CONTRADICTED"] * 4)]) == 1


def test_a_share_at_or_over_theta_caps_at_good_and_recomputes_the_verdict():
    row = engine_row(["CONTRADICTED", "CONTRADICTED", "MET", "MET"])
    assert ceilings.apply_unmet_ceiling([row], 0.5, "A") == 1
    assert row["matchScore"] == ceilings.UNMET_CAP == 69 and row["matchLabel"] == "Good" and row["applyRecommendation"] == "Maybe" and row["priority"] == "P2"
    assert row["hardCapped"] is True and any(r.startswith("Capped: 2 of 4 must requirements") for r in row["reasons"])
    under = engine_row(["CONTRADICTED", "MET", "MET", "MET"])
    assert ceilings.apply_unmet_ceiling([under], 0.5, "A") == 0 and under["matchScore"] == 80
    already_good = engine_row(["CONTRADICTED"] * 4, score=60)
    assert ceilings.apply_unmet_ceiling([already_good], 0.3, "A") == 0 and already_good["matchScore"] == 60


def test_the_ceiling_can_be_switched_off_for_the_measurement(monkeypatch):
    monkeypatch.setattr(ceilings, "DISABLED_FIXES", {"unmet"})
    row = engine_row(["CONTRADICTED"] * 4)
    assert ceilings.apply_unmet_ceiling([row], 0.3, "A") == 0


# --- the version --------------------------------------------------------------------------------------------------------

def test_the_scoring_version_is_1_6():
    assert scorer.SCORING_VERSION == "1.6"
    assert score_job(job(), intel(**BANK))["scoringVersion"] == "1.6"


def test_only_the_fixes_that_passed_the_guard_run_in_production():
    assert scorer.active_fixes() == frozenset({"role_ceiling", "clearance", "location", "unmet"})
    assert "skill" in scorer.ALL_FIXES and "skill" not in scorer.active_fixes()  # failed the guard alone: off by default


def test_the_failed_skill_change_changes_nothing_unless_a_measurement_switches_it_on(monkeypatch):
    j = job(title="Product Manager", description="We need roadmap ownership. " + PAD)
    off = score_job(j, intel(**BANK))
    monkeypatch.setattr(ceilings, "EXTRA_FIXES", {"skill"})
    on = score_job(j, intel(**BANK))
    assert "Product Manager" in off["matchedSkills"] and "Product Manager" not in on["matchedSkills"]


def test_the_engine_ceiling_is_variant_b_at_theta_0_3():
    assert (ceilings.UNMET_VARIANT, ceilings.UNMET_THETA) == ("B", 0.3)


# --- engine coverage: an ad with no current engine answer says so instead of silently passing the ceiling -----------------------------

def _row(**kw):
    return {"jobId": "x", "matchScore": 80, "reasons": [], "llmFacts": {"requirements": [{"id": "r"}]}, **kw}


def test_an_ad_without_a_current_engine_answer_is_marked_not_evaluated():
    answered = _row(engineShadow={"requirements": []})
    missing, closed, unread, no_reqs, failed = _row(), _row(isClosed=True), _row(matchScore=None), _row(llmFacts={}), _row(engineShadow={"error": "x"})
    counts = ceilings.stamp_engine_coverage([answered, missing, closed, unread, no_reqs, failed], engine_on=True)
    assert counts == {"answered": 1, "not_evaluated": 2, "not_applicable": 3}
    assert missing["engineCoverage"] == {"status": "not_evaluated", "reason": "no_answer"}
    assert failed["engineCoverage"]["reason"] == "failed"
    assert any(r.startswith("Ceiling not evaluated") for r in missing["reasons"])
    assert answered["reasons"] == closed["reasons"] == []


def test_with_the_engine_off_every_applicable_ad_says_so():
    row = _row()
    ceilings.stamp_engine_coverage([row], engine_on=False)
    assert row["engineCoverage"]["reason"] == "engine_off" and "did not run" in row["reasons"][-1]


def test_the_paid_fill_command_refuses_a_confirm_without_a_cap():
    import engine_missing
    assert engine_missing.main(["--confirm"]) == 2
