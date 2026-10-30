"""Provider registry and group resolution."""

from __future__ import annotations

from providers.ashby_provider import AshbyProvider
from providers.greenhouse_provider import GreenhouseProvider
from providers.jobspy_provider import JobSpyProvider
from providers.lever_provider import LeverProvider
from providers.remoteok_provider import RemoteOKProvider
from providers.wellfound_provider import WellfoundProvider
from providers.wwr_provider import WWRProvider
from providers.yc_provider import YCProvider
from providers.infostud_provider import InfostudProvider
from providers.joberty_provider import JobertyProvider
from providers.workable_provider import WorkableProvider
from source_definitions import PROVIDER_GROUPS  # noqa: F401  (re-exported)

PROVIDER_CLASSES = {
    "jobspy": JobSpyProvider,
    "greenhouse": GreenhouseProvider,
    "lever": LeverProvider,
    "ashby": AshbyProvider,
    "wellfound": WellfoundProvider,
    "remoteok": RemoteOKProvider,
    "yc": YCProvider,
    "wwr": WWRProvider,
    "infostud": InfostudProvider,
    "workable": WorkableProvider,
    "joberty": JobertyProvider,  # opt-in (source_definitions.py): in no group
}


def resolve_providers(spec: str) -> list[str]:
    key = (spec or "serbia").strip().lower()
    if key in PROVIDER_GROUPS:
        return list(PROVIDER_GROUPS[key])

    names = []
    for part in key.split(","):
        name = part.strip().lower()
        # A list may mix groups and names ("serbia,joberty").
        for member in PROVIDER_GROUPS.get(name) or [name]:
            if member in PROVIDER_CLASSES and member not in names:
                names.append(member)
    return names


def get_provider(name: str):
    cls = PROVIDER_CLASSES.get(name.lower())
    if cls is None:
        raise ValueError(f"Unknown provider: {name}")
    return cls()
