"""Provider group resolution: the default run is the full serbia group."""

from providers.provider_registry import PROVIDER_GROUPS, resolve_providers






def test_an_unknown_name_resolves_to_nothing_instead_of_another_group():
    assert resolve_providers("nonsense") == []
    assert resolve_providers("jobspy,nonsense") == ["jobspy"]
