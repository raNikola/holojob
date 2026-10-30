"""Read a fetched job page without a model: schema.org JobPosting JSON-LD, nothing guessed.

`read_ad` returns the fields the page states (`fields`), the ones it does not (`missing`), and the page's visible text
(`pageText`, capped), which is all a later, confirmed AI step may be given. Salary is kept only when it reads with
certainty as EUR per month (job_scoring/salary.py); any other currency or interval is left unknown, not converted.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "python" / "job_scoring") not in sys.path:
    sys.path.insert(0, str(ROOT / "python" / "job_scoring"))

from salary import parse_monthly_eur  # noqa: E402

FIELDS = ("title", "company", "location", "salary", "description")
PAGE_TEXT_CAP = 8000
MIN_READABLE_CHARS = 200
_NOISE = ("script", "style", "noscript", "svg", "nav", "footer", "iframe", "template")


def html_to_text(value) -> str:
    """HTML (possibly entity-escaped, as JSON-LD often is) to text, keeping paragraph and list-item breaks."""
    if not isinstance(value, str) or not value.strip():
        return ""
    soup = BeautifulSoup(html_lib.unescape(value), "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for item in soup.find_all("li"):
        item.insert_before("\n- ")
    for block in soup.find_all(["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "tr"]):
        block.insert_before("\n")
        block.insert_after("\n")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in soup.get_text().split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _job_postings(soup: BeautifulSoup):
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            kind = item.get("@type") if isinstance(item, dict) else None
            if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                yield item


def _number(value) -> str:
    try:
        number = float(str(value).replace(",", "").strip())
    except ValueError:
        return ""
    return str(int(number)) if number == int(number) else str(number)


def salary_text(base) -> str:
    """The pay as "min - max monthly EUR", or "" unless the posting states EUR with a monthly or yearly interval."""
    if not isinstance(base, dict):
        return ""
    value = base.get("value")
    spec = value if isinstance(value, dict) else {"value": value}
    interval = {"MONTH": "monthly", "YEAR": "yearly"}.get(str(spec.get("unitText") or base.get("unitText") or "").upper())
    low = _number(spec.get("minValue") or spec.get("value"))
    high = _number(spec.get("maxValue") or "") or low
    currency = str(base.get("currency") or "").strip().upper()
    if not (interval and low and currency == "EUR"):
        return ""
    parsed = parse_monthly_eur(f"{low} - {high} {interval} EUR" if high != low else f"{low} {interval} EUR")
    if not parsed or parsed["currency"] != "EUR" or parsed["converted"]:
        return ""
    return f"{parsed['min']} - {parsed['max']} monthly EUR" if parsed["min"] != parsed["max"] else f"{parsed['min']} monthly EUR"


def normalize_salary(text) -> str:
    """The same rule for pay found in free text: kept only when it reads as EUR per month with certainty."""
    parsed = parse_monthly_eur(text)
    if not parsed or parsed["currency"] != "EUR" or parsed["converted"]:
        return ""
    return f"{parsed['min']} - {parsed['max']} monthly EUR" if parsed["min"] != parsed["max"] else f"{parsed['min']} monthly EUR"


def _location(item: dict) -> str:
    place = item.get("jobLocation") or {}
    if isinstance(place, list):
        place = place[0] if place else {}
    address = place.get("address") if isinstance(place, dict) else None
    if not isinstance(address, dict):
        return ""
    country = address.get("addressCountry")
    country = country.get("name") if isinstance(country, dict) else country
    parts = [address.get("addressLocality"), address.get("addressRegion"), country]
    return ", ".join(html_to_text(p) for p in parts if isinstance(p, str) and p.strip())


def page_text(soup: BeautifulSoup) -> str:
    """The page's visible text, one line per block, capped. The page title leads it."""
    title = soup.title.get_text(" ").strip() if soup.title else ""
    for tag in soup(list(_NOISE)):
        tag.decompose()
    body = soup.body or soup
    lines = [re.sub(r"\s+", " ", line).strip() for line in body.get_text("\n").split("\n")]
    text = re.sub(r"\n{2,}", "\n", "\n".join(line for line in lines if line))
    return (f"Page title: {title}\n{text}" if title else text)[:PAGE_TEXT_CAP]


def read_ad(html: str) -> dict:
    """{"fields", "missing", "pageText", "source", "readable"}. `source` is "json-ld" or "none"."""
    soup = BeautifulSoup(html or "", "html.parser")
    posting = next(_job_postings(soup), None)
    fields = dict.fromkeys(FIELDS, "")
    if posting:
        org = posting.get("hiringOrganization")
        fields.update(
            title=html_to_text(posting.get("title") or posting.get("name") or ""),
            company=html_to_text(org.get("name") if isinstance(org, dict) else org if isinstance(org, str) else ""),
            location=_location(posting),
            salary=salary_text(posting.get("baseSalary")),
            description=html_to_text(posting.get("description") or ""),
        )
    text = page_text(soup)
    return {
        "fields": fields,
        "missing": [f for f in FIELDS if not fields[f]],
        "pageText": text,
        "source": "json-ld" if posting else "none",
        # A page with no posting data and next to no text is a wall or an empty shell, not an ad.
        "readable": bool(posting) or len(text) >= MIN_READABLE_CHARS,
    }
