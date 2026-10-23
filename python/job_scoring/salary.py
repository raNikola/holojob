"""Read a monthly EUR figure from an ad's free-text pay, and compare it with the candidate's floor.

Display metadata only. Nothing here reaches matchScore, matchLabel, priority,
applyRecommendation or the red flags: scorer.py attaches the result next to
them, never into them.

Conservative on purpose. A figure is returned only when the text names one
currency, a yearly or monthly interval, and one amount or one range. Hourly or
daily rates, several ranges, an open-ended "from / up to", a currency this file
does not know, and a missing currency or interval are all unknown (None).

One exception to "no currency, no figure": JobSpy's formatter (normalize_jobs.py)
leaves the currency off when it is USD, so exactly its own shape,
"92900 - 209500 yearly", is read as USD. Free text in any other shape with no
currency stays unknown.

USD and GBP are converted at the fixed approximate rates below and marked
"converted": a display flag does not need a live rate, but a figure that was
converted must not look like one that was stated in euros.
"""

from __future__ import annotations

import re

# EUR per unit, rounded and fixed: change them here when they drift far enough to matter.
EUR_PER_UNIT = {"EUR": 1.0, "USD": 0.92, "GBP": 1.17}

_CURRENCY_PATTERNS = {
    "EUR": re.compile(r"€|\b(eur|euros?)\b", re.IGNORECASE),
    "USD": re.compile(r"(?<![A-Za-z])\$|\bus\$|\b(usd|us\s+dollars?|dollars?)\b", re.IGNORECASE),
    "GBP": re.compile(r"£|\b(gbp|pounds?(\s+sterling)?)\b", re.IGNORECASE),
}
# A currency this file cannot convert makes the text unknown, as does a
# prefixed dollar sign (CA$, A$) that is not the US dollar.
_OTHER_CURRENCY = re.compile(
    r"[A-Za-z]\$|\b(chf|rsd|din|dinars?|cad|aud|nzd|sek|nok|dkk|pln|czk|huf|ron|bgn|inr|jpy|cny)\b",
    re.IGNORECASE,
)
# The one currency-less shape that is read as USD: what normalize_jobs writes.
_JOBSPY_BARE = re.compile(r"^\s*[\d.,]+(\s*-\s*[\d.,]+)?\s+(yearly|monthly)\s*$", re.IGNORECASE)

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


def _currency(text: str) -> str | None:
    if _OTHER_CURRENCY.search(text):
        return None
    named = [code for code, pattern in _CURRENCY_PATTERNS.items() if pattern.search(text)]
    if len(named) == 1:
        return named[0]
    if not named and _JOBSPY_BARE.match(text):
        return "USD"
    return None


def parse_monthly_eur(text) -> dict | None:
    """{"min", "max", "currency", "converted"} in EUR per month, or None when the text cannot be read with certainty."""
    if not isinstance(text, str) or not text.strip():
        return None
    currency = _currency(text)
    if currency is None:
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

    factor = EUR_PER_UNIT[currency] / (12 if yearly else 1)
    low, high = min(amounts) * factor, max(amounts) * factor
    if low < _MIN_PLAUSIBLE_MONTHLY:
        return None
    return {"min": round(low), "max": round(high), "currency": currency, "converted": currency != "EUR"}


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
