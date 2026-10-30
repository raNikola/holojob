"""What each discovery source is, without importing the scrapers behind it.

provider_registry.py maps these names to their provider classes (and pulls in
JobSpy, pandas and Playwright); this module stays light, so the Settings API can
list the sources and their switches in a fast child process.

`opt_in` sources are in no provider group and never run because nothing turned
them off: they run only while the owner has switched them on, with recorded
consent, in Settings > Sources (source_settings.py). Every other source still
follows the groups below until board switching (SOURCES_SPEC.md, Phase 3b).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceDefinition:
    name: str
    opt_in: bool = False


SOURCE_DEFINITIONS = {
    d.name: d
    for d in (
        SourceDefinition("jobspy"),
        SourceDefinition("greenhouse"),
        SourceDefinition("lever"),
        SourceDefinition("ashby"),
        SourceDefinition("wellfound"),
        SourceDefinition("remoteok"),
        SourceDefinition("yc"),
        SourceDefinition("wwr"),
        SourceDefinition("infostud"),
        SourceDefinition("workable"),
        # Undocumented API, terms restrict use (sections 7 and 8): only with the owner's consent.
        SourceDefinition("joberty", opt_in=True),
    )
}

PROVIDER_GROUPS = {
    "all": [
        "jobspy", "infostud", "greenhouse", "lever", "ashby", "wellfound",
        "remoteok", "yc", "wwr",
    ],
    "ats": ["greenhouse", "lever", "ashby"],
    "remote": ["remoteok", "wwr", "workable", "jobspy"],
    "startup": ["yc", "wellfound", "ashby"],
    "serbia": ["jobspy", "infostud", "workable", "greenhouse", "lever", "ashby"],
}

STANDARD_GROUP = "serbia"


def opt_in_names() -> list[str]:
    return [name for name, d in SOURCE_DEFINITIONS.items() if d.opt_in]
