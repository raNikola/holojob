"""Reading an Infostud ad's full text from its detail page, and saying whether it is whole (Wave 5).

The listing carries a teaser (`jobSummary.summary` + `textAdSnippet`, about 500 characters ending in "..."). The detail page holds the
real ad as HTML in `__NEXT_DATA__ -> props.pageProps.job.textAd`. Its JSON-LD `description` is only the SEO blurb (about 150
characters), which is why a "replace if longer" rule on JSON-LD alone never fixed anything.

A longer text is not a better one: a page body can be long and be navigation, cookie text, related-ads lists or a JSON blob. A
candidate is accepted only if `real_content_reasons` finds nothing wrong with it; length only breaks a tie between candidates that
passed. Pure functions, no I/O, no model.

`descriptionStatus` values:
    complete          the full ad text was read from the detail page
    teaser            only the listing teaser is known (detail page not read yet)
    failed            the detail page could not be fetched; the teaser stays
    source_truncated  the page was read and holds no fuller real text than the teaser (the ad is cut off at source)
"""

from __future__ import annotations

import html as html_lib
import json
import re
from html.parser import HTMLParser

COMPLETE = "complete"
TEASER = "teaser"
FAILED = "failed"
SOURCE_TRUNCATED = "source_truncated"
STATUSES = (COMPLETE, TEASER, FAILED, SOURCE_TRUNCATED)
INCOMPLETE = (TEASER, FAILED, SOURCE_TRUNCATED)  # statuses that lower confidence in a score
REPAIRABLE = (TEASER, FAILED)  # statuses a repair run fetches again; source_truncated is not retried every run

MIN_REAL_CHARS = 120  # shorter than this is a blurb, not an ad
MIN_DISTINCT_LINE_RATIO = 0.6  # below this the text is mostly repeated lines (teaser fragments, menus)
MAX_BOILERPLATE_LINE_RATIO = 0.3
MAX_SHORT_LINE_RATIO = 0.7  # a list of 1-3 word lines is navigation, not prose
MIN_WORDS_FOR_PROSE = 25  # prose needs at least this many words in lines of 6 or more words
ELLIPSIS = ("...", "…")

# Source priority: structured ad fields beat the visible page, which is the most likely to hold boilerplate.
PRIORITY = {"next_data": 3, "json_ld": 2, "body": 1}

_BOILERPLATE = (
    "cookie", "kolačić", "kolacic", "accept all", "prihvatam sve", "privacy policy", "politika privatnosti", "terms of use",
    "uslovi korišćenja", "uslovi koriscenja", "prijavi se", "log in", "sign in", "newsletter", "slični oglasi", "slicni oglasi",
    "similar jobs", "related jobs", "pogledaj sve oglase", "all rights reserved", "sva prava zadržana", "follow us", "pratite nas",
    "download the app", "instaliraj aplikaciju", "skip to content",
)

_BLOCK = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "table"}
_SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "iframe", "template", "header", "form", "button", "aside"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
        elif tag in _BLOCK:
            self.parts.append("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(value) -> str:
    """HTML (or plain text) to readable text: block tags become line breaks, list items "- ", entities decoded, blanks collapsed."""
    if not isinstance(value, str) or not value.strip():
        return ""
    parser = _Text()
    parser.feed(value)
    parser.close()
    text = html_lib.unescape("".join(parser.parts)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line and line != "-").strip()


def real_content_reasons(text: str) -> list[str]:
    """Why `text` is not real ad content; an empty list means it is. Looks at the text itself, never at its length alone."""
    text = (text or "").strip()
    if len(text) < MIN_REAL_CHARS:
        return [f"too short to be an ad ({len(text)} characters)"]
    reasons = []
    if text[0] in "{[" or text.count('":') > 5 or text.count("{") + text.count("}") > 10:
        reasons.append("looks like a JSON blob")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) >= 4:
        distinct = len({line.lower() for line in lines}) / len(lines)
        if distinct < MIN_DISTINCT_LINE_RATIO:
            reasons.append("mostly repeated lines")
        marked = sum(1 for line in lines if any(mark in line.lower() for mark in _BOILERPLATE))
        if marked / len(lines) > MAX_BOILERPLATE_LINE_RATIO:
            reasons.append("mostly navigation or cookie text")
        short = sum(1 for line in lines if len(line.split()) <= 3)
        if len(lines) >= 8 and short / len(lines) > MAX_SHORT_LINE_RATIO:
            reasons.append("a list of short items, not prose")
    prose_words = sum(len(line.split()) for line in lines if len(line.split()) >= 6)
    if prose_words < MIN_WORDS_FOR_PROSE:
        reasons.append("no running prose")
    return reasons


def _ends_cut(text: str) -> bool:
    return text.rstrip().endswith(ELLIPSIS)


def _next_data_job(html: str) -> dict:
    marker = html.find("__NEXT_DATA__")
    if marker < 0:
        return {}
    start = html.find(">", marker) + 1
    end = html.find("</script>", start)
    try:
        data = json.loads(html[start:end])
    except (ValueError, TypeError):
        return {}
    job = ((data.get("props") or {}).get("pageProps") or {}).get("job") if isinstance(data, dict) else None
    return job if isinstance(job, dict) else {}


def _json_ld_postings(html: str) -> list[dict]:
    found, position = [], 0
    while True:
        marker = html.find("application/ld+json", position)
        if marker < 0:
            return found
        start = html.find(">", marker) + 1
        end = html.find("</script>", start)
        position = end + 1
        try:
            parsed = json.loads(html[start:end])
        except json.JSONDecodeError:
            continue
        found += [i for i in (parsed if isinstance(parsed, list) else [parsed]) if isinstance(i, dict) and i.get("@type") == "JobPosting"]


def _body_text(html: str) -> str:
    return html_to_text(html)


def candidates(html: str) -> list[dict]:
    """Every text the detail page offers: {"source", "text", "reasons"}; `reasons` empty = real content."""
    out = []
    ad = _next_data_job(html).get("textAd")
    out.append(("next_data", html_to_text(ad) if isinstance(ad, str) else ""))
    for posting in _json_ld_postings(html):
        out.append(("json_ld", html_to_text(posting.get("description") or "")))
    out.append(("body", _body_text(html)))
    return [{"source": s, "text": t, "reasons": real_content_reasons(t)} for s, t in out if t]


def choose(options: list[dict]) -> dict | None:
    """The best candidate that is real content: highest source priority, then the longer text. None when none passes."""
    passing = [o for o in options if not o["reasons"]]
    if not passing:
        return None
    return max(passing, key=lambda o: (PRIORITY.get(o["source"], 0), len(o["text"])))


def read_detail(html: str, teaser: str = "") -> dict:
    """Read a fetched detail page against the teaser the listing gave.

    Returns {"description", "status", "source"}. A real candidate replaces the teaser when it is longer, or when it is whole
    (does not end in an ellipsis) and the teaser is cut. Otherwise the teaser stays and the page is called `source_truncated`:
    the page was read and holds nothing fuller.
    """
    teaser = (teaser or "").strip()
    best = choose(candidates(html))
    if best is not None:
        text = best["text"]
        grows = len(text) > len(teaser)
        if grows or (not _ends_cut(text) and _ends_cut(teaser)):
            if _ends_cut(text) and best["source"] != "next_data":
                return {"description": teaser, "status": SOURCE_TRUNCATED, "source": "teaser"}
            return {"description": text, "status": SOURCE_TRUNCATED if _ends_cut(text) else COMPLETE, "source": best["source"]}
    return {"description": teaser, "status": SOURCE_TRUNCATED, "source": "teaser"}


def is_incomplete(job: dict) -> bool:
    """For scoring and repair: the ad's description is known not to be whole. An absent status on a non-Infostud ad is not incomplete."""
    return (job.get("descriptionStatus") or "") in INCOMPLETE
