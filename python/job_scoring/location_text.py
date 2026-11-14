"""Where may the candidate work from, read from the board's fields and the ad's own words.

work_authorization.py asks this when the candidate set allowedLocations. No
model is involved: the board's `isRemote`, the work mode and the stored
description decide, so the same job always reads the same way.

Four outcomes, `state`:

  None      no remote signal: the job is an office somewhere, and the board's
            location against allowedLocations decides, as before.
  "fail"    a remote signal AND a geography the ad states that the candidate
            does not allow ("Remote, UK only", "must be based in the UK"):
            the job is capped like any other location outside allowedLocations.
  "pass"    available from the candidate's own country, the Balkans or
            anywhere in the world, stated.
  "unknown" a remote, worldwide or EU / Europe signal with no confirmed
            restriction. Not capped, not scored down; the job carries the flag
            "Verify location". "Remote" alone never means available from Serbia.

Conservative on purpose: a phrase only counts when it is about the role
("This is a remote role", "Location: Remote"), not about the employer's
benefits ("fully remote workers get a stipend", "two weeks of working from
anywhere"). A hybrid or office-days mention cancels a plain remote signal.
"""

from __future__ import annotations

import html
import re
from functools import lru_cache

from geography import REMOTE, WORLDWIDE, _fold, _table, covers, region_codes

VERIFY_FLAG = "Verify location"

# Stated availability that settles it from the candidate's side of the world.
_BALKANS = re.compile(r"\b(balkans?|western balkans|south[- ]?east(ern)? europe)\b", re.I)
# "Our impact is worldwide" and "a globally distributed organization" say nothing about where a hire may live.
_WORLDWIDE = re.compile(
    r"\bremote\b[^.\n]{0,30}\b(worldwide|world-?wide|globally|anywhere in the world)\b"
    r"|\b(worldwide|global)[ -]remote\b|\blocation:\s*(worldwide|global|anywhere)\b"
    r"|\bhir(?:e|ing)\b[^.\n]{0,25}\b(worldwide|world-?wide|globally|anywhere in the world)\b"
    r"|\bwork from anywhere in the world\b",
    re.I,
)
# The ad is open to candidates living in a region. Not enough to be sure about Serbia.
_REGION_OPEN = re.compile(
    r"\bopen to (?:candidates|applicants)\s+(?:located|based|residing|living)\s+(?:anywhere\s+)?(?:in|across)\s+"
    r"(?:the\s+)?(?:europe|eu|emea|european union)\b"
    r"|\bremote\s*[-–—(,:]?\s*(?:eu|europe|emea|european union)\b|\b(?:eu|europe|emea)[- ]remote\b",
    re.I,
)
_REMOTE = re.compile(
    r"\bthis (?:is a|role is|position is|job is) (?:a )?(?:fully |100% |completely )?remote\b"
    r"|\b(?:fully|100%|completely)[ -]remote\b(?!\s+(?:work|employee|team|staff|colleague|contract))"
    r"|\bremote[- ]first\b|\blocation:\s*remote\b|\bremote (?:role|position|job|opportunity)\b"
    r"|\bremote\s*[-–—(,:]?\s*(?:uk|u\.k\.|us|usa|united states|united kingdom|canada|europe|eu|emea)\b"
    r"|\b(?:uk|us|usa|eu|europe|emea)[- ]remote\b",
    re.I,
)
_HYBRID = re.compile(
    r"\bhybrid\b(?!\s+(?:monetis|monetiz|cloud|casual|app|model of))"
    r"|\b\d\s*days?\s+(?:per|a|each)\s+week\s+(?:in|at)\b|\b\d\s*days?\s+in\s+(?:the\s+)?office\b"
    r"|\bon-?site\s+\d\s+days?\b|\bin-?office\s+\d\b|\boffice[- ]based\b",
    re.I,
)

# Frames that tie a country to where the candidate must live. {C} is a country name or alias.
_FRAMES = (
    r"{C}\s*[- ]?\s*(?:only|residents?|citizens?|nationals?)\b",
    r"(?:must|need to|required to|should)\s+(?:be\s+)?(?:based|located|resident|reside|live|living|residing)\s+(?:in|within)\s+(?:the\s+)?{C}",
    r"(?:candidates|applicants|hires|you)\s+(?:must\s+)?(?:be\s+)?(?:based|located|residing|living|resident)\s+(?:in|within)\s+(?:the\s+)?{C}",
    r"(?:right|eligib\w+|authori[sz]ed?|permit\w*)\s+to\s+work\s+(?:in|within)\s+(?:the\s+)?{C}",
    r"remote\s*(?:\(|[-–—:,]|in|within|from)\s*(?:the\s+)?{C}",
    r"{C}\s*(?:\)|[-–—:,])?\s*remote\b",
)


@lru_cache(maxsize=1)
def _frames() -> tuple[re.Pattern, ...]:
    names = sorted({*_table()[0], "us"}, key=len, reverse=True)
    alt = "|".join(re.escape(n) for n in names if len(n) >= 2)
    return tuple(re.compile(f.replace("{C}", f"(?P<c>{alt})"), re.I) for f in _FRAMES)


def _restrictions(text: str) -> list[str]:
    """Country codes the ad ties the hire to, in order of appearance."""
    found: list[str] = []
    for frame in _frames():
        for m in frame.finditer(_fold(text)):
            name = m.group("c")
            # "us" is a country only written "US"; the table has no such alias.
            code = _table()[0].get(name) or ("US" if name == "us" and re.search(r"\bUS\b", text) else None)
            if code and code not in found:
                found.append(code)
    return found


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"[.;!?\n•]|\s[-*]\s", html.unescape(text or "")) if s.strip()]


def _from_text(text: str) -> dict:
    sentences = _sentences(text)
    remote = [s for s in sentences if _REMOTE.search(s)]
    return {
        "remote": bool(remote),
        "hybrid": bool(_HYBRID.search(text or "")),
        "worldwide": next((s.strip() for s in sentences if _WORLDWIDE.search(s)), None),
        "region": next((s.strip() for s in sentences if _REGION_OPEN.search(s)), None),
        "balkans": next((s.strip() for s in sentences if _BALKANS.search(s)
                         and re.search(r"remote|based|located|candidates|eligible|apply|open to", s, re.I)), None),
        "serbia": next((s.strip() for s in sentences if re.search(r"\b(serbia|srbija|belgrade|beograd)\b", _fold(s))
                        and re.search(r"remote|based in|located in|candidates|eligible|open to", s, re.I)), None),
        "countries": _restrictions(text),
        "remote_quote": remote[0].strip() if remote else None,
    }


def _disallowed(code: str, allowed: list[str]) -> bool:
    return not any(covers(a, code) for a in allowed if a != REMOTE)


def read_location(job: dict, allowed: list[str], board_remote: bool) -> dict | None:
    """The location state of a job against `allowed` (upper-case codes), or None for "no signal".

    `board_remote` is the board's own remote flag or work mode (is_remote_job).
    The result is {"state", "flag", "quote", "reason", "remote"}; `remote` is
    True when the job is to be treated as remote rather than as an office.
    """
    facts = job.get("llmFacts") or {}
    text = _from_text(job.get("description") or "")
    eligibility = [str(p).upper() for p in facts.get("remoteEligibility") or [] if p]
    remote_text = text["remote"] and not text["hybrid"]
    signal = board_remote or remote_text or bool(text["worldwide"] or text["region"] or text["balkans"])
    if not signal:
        return None

    def out(state: str, reason: str, quote: str | None = None, names_place: bool = False) -> dict:
        # names_place: the ad's own words name a country or region (work_authorization does not narrow such an ad to the board country).
        return {"state": state, "flag": VERIFY_FLAG if state == "unknown" else None, "quote": quote,
                "reason": reason, "remote": True, "names_place": names_place}

    stated = text["countries"]
    places = [p for p in eligibility if p != WORLDWIDE] + stated
    # Available from the candidate's side: stated, and nothing contradicts it.
    if WORLDWIDE in eligibility or text["worldwide"]:
        return out("pass", "the ad states it is open worldwide", text["worldwide"])
    if text["balkans"] or text["serbia"] or any(covers(p, "RS") for p in places if p in _table()[2]):
        return out("pass", "the ad states it is open from Serbia or the Balkans", text["balkans"] or text["serbia"])
    countries = [p for p in places if p in _table()[2]]
    # Only the ad's own words confirm a restriction; the extracted remoteEligibility keeps its older
    # reading (a work-permit check), so a visa refusal is never softened into a location cap.
    if stated and all(_disallowed(p, allowed) for p in stated):
        return out("fail", f"remote, but limited to {'/'.join(stated[:3])}, outside the locations you will take a job in",
                   text["remote_quote"])
    if countries:
        return out("unknown", f"remote, limited to {'/'.join(countries[:3])}; it does not say you may live in Serbia", names_place=True)
    regions = [p for p in places if p in region_codes()]
    if regions or text["region"]:
        return out("unknown", "remote or open to a region, and the ad does not say Serbia is included", text["region"], names_place=True)
    return out("unknown", "the ad is remote but does not say where you may live", text["remote_quote"])
