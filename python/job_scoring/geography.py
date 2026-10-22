"""Countries and regions: where a job is, and what a work right covers.

Reads src/data/geography.json, the table the profile form also uses, so the UI
and the scorer agree on every code. It is reference data about the world, the
same for every candidate. A place it does not know resolves to None, and an
unknown place never caps a score.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

GEOGRAPHY_PATH = Path(__file__).resolve().parents[2] / "src" / "data" / "geography.json"

REMOTE = "REMOTE"
WORLDWIDE = "WORLDWIDE"


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().strip(" .")


@lru_cache(maxsize=1)
def _table() -> tuple[dict[str, str], dict[str, frozenset[str]], frozenset[str]]:
    data = json.loads(GEOGRAPHY_PATH.read_text(encoding="utf-8"))
    names: dict[str, str] = {}
    members: dict[str, set[str]] = {code: set() for code in data["regions"]}
    for country in data["countries"]:
        code = country["code"]
        for name in [country["name"], *country.get("aliases", [])]:
            names[_fold(name)] = code
        for region in country.get("regions", []):
            members[region].add(code)
    codes = frozenset(c["code"] for c in data["countries"])
    return names, {r: frozenset(m) for r, m in members.items()}, codes


def country_codes() -> frozenset[str]:
    return _table()[2]


def region_codes() -> frozenset[str]:
    return frozenset(_table()[1])


def is_known(code: str) -> bool:
    return code in country_codes() or code in region_codes()


def country_of_name(text: str) -> str | None:
    """The code when the whole text is a country's name: "Srbija" -> "RS"."""
    return _table()[0].get(_fold(text))


def resolve_country(location: str) -> str | None:
    """The country a location names, read from its last part backwards.

    "Belgrade, Serbia" and "Niš, Centralna Srbija, Serbia" give "RS". A part in
    capitals that is a known code counts too ("Remote, US").
    """
    for part in reversed([p.strip() for p in re.split(r"[,|/()]", location or "") if p.strip()]):
        code = country_of_name(part)
        if code:
            return code
        if part.isupper() and part in country_codes():
            return part
    return None


def covers(right: str, place: str) -> bool:
    """Whether a work right held for `right` lets the holder work in `place`.

    Both are country or region codes: a right for "EU" covers "DE", and covers
    a role open to "EU" residents; a right for "RS" covers only "RS".
    """
    if right == place:
        return True
    return place in _table()[1].get(right, frozenset())
