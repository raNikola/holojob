"""Read a monthly EUR figure from an ad's free-text pay, and compare it with the candidate's floor.

Display metadata only. Nothing here reaches matchScore, matchLabel, priority,
applyRecommendation or the red flags: scorer.py attaches the result next to
them, never into them.

Conservative on purpose. A figure is returned only when the text names EUR and
a yearly or monthly interval and carries one amount or one range. Any other
currency, a missing currency or interval, an hourly or daily rate, several
ranges or an open-ended "from / up to" is unknown (None). LinkedIn's formatter
drops the currency when it is USD, so "92900 - 209500 yearly" is unknown here
rather than guessed.
"""

from __future__ import annotations

import re

# Anything that names a currency other than the euro makes the text unknown.
_OTHER_CURRENCY = re.compile(
    r"\$|£|\b(usd|gbp|chf|rsd|din|dinars?|dollars?|pounds?|cad|aud|sek|nok|dkk|pln|czk|huf|ron|bgn|inr)\b",
    re.IGNORECASE,
)
_EUR = re.compile(r"€|\b(eur|euros?)\b", re.IGNORECASE)

_YEARLY = re.compile(r"\b(yearly|annual|annually|per\s+annum|p\.?a\.?|per\s+year|a\s+year|/\s*y(ea)?r|year|yr)\b", re.IGNORECASE)
_MONTHLY = re.compile(r"\b(monthly|per\s+month|a\s+month|/\s*mo(nth)?|month)\b", re.IGNORECASE)
_OTHER_INTERVAL = re.compile(r"\b(hourly|per\s+hour|/\s*h(ou)?r|hour|daily|per\s+day|day|weekly|per\s+week|week|bi-?weekly)\b", re.IGNORECASE)
_OPEN_ENDED = re.compile(r"\b(up\s+to|from|starting|at\s+least|minimum|min\.?|over|above|plus|\+)\b|\d\s*\+", re.IGNORECASE)

_AMOUNT = re.compile(r"(?<![\w.])(\d+(?:[.,\s]\d+)*)\s*(k\b)?", re.IGNORECASE)
_GROUPED = re.compile(r"^\d{1,3}(?:[.,\s]\d{3})+$")

# Below this a "monthly" figure is more likely an hourly rate than a salary.
_MIN_PLAUSIBLE_MONTHLY = 100


def _to_number(token: str, thousands: bool) -> float | None:
    token = token.strip()
    if _GROUPED.match(token):
        value = float(re.sub(r"[.,\s]", "", token))
    elif re.fullmatch(r"\d+", token):
        value = float(token)
    elif re.fullmatch(r"\d+[.,]\d+", token):
        value = float(token.replace(",", "."))
    else:
        return None
    return value * 1000 if thousands else value


def parse_monthly_eur(text) -> dict | None:
    """{"min", "max"} in EUR per month, or None when the text cannot be read with certainty."""
    if not isinstance(text, str) or not text.strip():
        return None
    if _OTHER_CURRENCY.search(text) or not _EUR.search(text):
        return None
    if _OTHER_INTERVAL.search(text) or _OPEN_ENDED.search(text):
        return None

    yearly, monthly = bool(_YEARLY.search(text)), bool(_MONTHLY.search(text))
    if yearly == monthly:  # neither, or both
        return None

    amounts = []
    for match in _AMOUNT.finditer(text):
        value = _to_number(match.group(1), bool(match.group(2)))
        if value is None:
            return None
        amounts.append(value)
    if not 1 <= len(amounts) <= 2:
        return None

    divisor = 12 if yearly else 1
    low, high = min(amounts) / divisor, max(amounts) / divisor
    if low < _MIN_PLAUSIBLE_MONTHLY:
        return None
    return {"min": round(low), "max": round(high)}


def _positive(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def minimum_salary(intelligence: dict) -> float | None:
    """The candidate's floor in EUR per month, from the intelligence; None when unset."""
    return _positive(((intelligence or {}).get("jobFitPreferences") or {}).get("minSalaryEur"))


def below_minimum(parsed: dict | None, minimum: float | None) -> bool | None:
    """True when even the top of the ad's range is under the floor.

    None when the pay cannot be read or the candidate set no floor. A range that
    reaches the floor is not flagged: the ad might pay it.
    """
    if parsed is None or minimum is None:
        return None
    return parsed["max"] < minimum


def salary_metadata(job: dict, intelligence: dict) -> dict:
    """The two display fields scorer.py attaches to a scored job."""
    parsed = parse_monthly_eur(job.get("salary"))
    return {
        "salaryMonthlyEur": parsed,
        "belowMinSalary": below_minimum(parsed, minimum_salary(intelligence)),
    }
