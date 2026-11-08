"""Role-family config: in step with the enrichment enum, and the cap it drives."""

import pytest

from enrich_jobs import ROLE_TRACKS
from scorer import OFF_TRACK_CAP, ROLE_FAMILIES, accepted_tracks, score_job

# The enrichment fallback for an ad it cannot place. No family accepts it, so
# such an ad is capped for every candidate, as it was before the config.
UNCLASSIFIED_TRACK = "other"


def test_every_accepted_track_is_a_real_enum_value():
    for family, entry in ROLE_FAMILIES.items():
        unknown = set(entry["acceptedRoleTracks"]) - ROLE_TRACKS
        assert not unknown, f"{family} accepts tracks enrich_jobs.py never emits: {unknown}"


def test_every_enum_value_belongs_to_a_family():
    covered = {track for entry in ROLE_FAMILIES.values() for track in entry["acceptedRoleTracks"]}
    missing = ROLE_TRACKS - covered - {UNCLASSIFIED_TRACK}
    assert not missing, f"ROLE_TRACKS values no family accepts: {missing}"
    assert UNCLASSIFIED_TRACK not in covered


def test_every_family_has_synonyms_and_tracks():
    for family, entry in ROLE_FAMILIES.items():
        assert entry["titleSynonyms"], family
        assert entry["acceptedRoleTracks"], family


def test_product_family_accepts_product_and_program_work_not_delivery():
    assert accepted_tracks({"roleFamily": "product"}) == ("product", {"product_management", "product_ownership", "program_management"})


def test_no_family_assumes_none():
    assert accepted_tracks({}) == (None, None)
    assert accepted_tracks({"roleFamily": ""}) == (None, None)


@pytest.mark.parametrize("track", ["engineering", "project_delivery", "other"])
def test_without_a_family_no_job_is_capped_for_its_role(track):
    result = score_job(_job(track), {})
    assert not any(r.startswith("Capped: the ad describes") for r in result["reasons"])
    assert "No role family set in the profile: the role is not checked against one" in result["reasons"]


def test_no_family_scores_like_a_family_that_accepts_the_track():
    assert score_job(_job("engineering"), {})["matchScore"] == score_job(_job("engineering"), {"roleFamily": "engineering"})["matchScore"]


def test_unknown_family_is_an_error():
    with pytest.raises(ValueError, match="Unknown role family"):
        accepted_tracks({"roleFamily": "astronaut"})


def _job(track):
    return {
        "jobId": "rf-1",
        "title": "Senior Product Manager",
        "company": "Example",
        "location": "Remote",
        "description": "Own the roadmap, discovery, stakeholders, B2B SaaS platform, APIs.",
        "remote": "remote",
        "llmFacts": {"roleTrack": track, "roleTrackEvidence": "Own the roadmap and discovery."},
    }


@pytest.mark.parametrize(
    "family,track,capped",
    [
        ("product", "product_management", False),
        ("product", "product_ownership", False),
        ("product", "project_delivery", True),
        ("product", "engineering", True),
        ("product", "other", False),
        ("engineering", "engineering", False),
        ("engineering", "product_management", True),
    ],
)
def test_off_track_cap_follows_the_family(family, track, capped):
    intelligence = {"roleFamily": family}
    result = score_job(_job(track), intelligence)
    reason = f"Capped: the ad describes {track}, not a {family} role"
    assert (reason in result["reasons"]) is capped
    if capped:
        assert result["matchScore"] <= OFF_TRACK_CAP


def test_a_track_without_evidence_does_not_cap():
    job = _job("engineering")
    job["llmFacts"].pop("roleTrackEvidence")
    result = score_job(job, {"roleFamily": "product"})
    assert not any(r.startswith("Capped: the ad describes") for r in result["reasons"])
