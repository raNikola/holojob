"""Provider group resolution: the default run is the full serbia group."""

from providers.provider_registry import PROVIDER_GROUPS, resolve_providers


def test_no_spec_means_the_standard_serbia_run():
    assert resolve_providers("") == PROVIDER_GROUPS["serbia"]
    assert resolve_providers(None) == PROVIDER_GROUPS["serbia"]


def test_serbia_covers_the_boards_and_the_ats_providers():
    assert set(PROVIDER_GROUPS["serbia"]) == {"jobspy", "infostud", "workable", "greenhouse", "lever", "ashby"}


def test_an_unknown_name_resolves_to_nothing_instead_of_another_group():
    assert resolve_providers("nonsense") == []
    assert resolve_providers("jobspy,nonsense") == ["jobspy"]
