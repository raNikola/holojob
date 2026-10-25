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


def test_product_family_accepts_exactly_the_old_set():
    assert accepted_tracks({"roleFamily": "product"}) == ("product", {"product_management", "product_ownership"})


def test_missing_family_behaves_as_product():
    assert accepted_tracks({}) == accepted_tracks({"roleFamily": "product"})


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
        "llmFacts": {"roleTrack": track},
    }


@pytest.mark.parametrize(
    "family,track,capped",
    [
        ("product", "product_management", False),
        ("product", "product_ownership", False),
        ("product", "project_delivery", True),
        ("product", "engineering", True),
        ("product", "other", True),
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
