"""Per-ad evidence selection for the matcher (offline, deterministic, no model).

The matcher is sent the candidate's whole evidence index for every posting
(about 5,600 of the ~9,400 input tokens of a call). Most of it has nothing to
do with a given ad. `select_evidence` keeps, for one ad, only:

  * every item that shares a keyword with ANY requirement the model is asked
    about (text, the ad's quote, or the words of a competency id): the safety
    rule is that an item overlapping a requirement is never dropped, and a
    doubtful case is kept;
  * the core: the first item of every role (so the work history, with its
    dates, stays complete) and, with `keep_facts` (default), every `fact`
    item. Facts are the candidate's listed tools, skills and certificates,
    and the matcher's MISSING rule ("the evidence lists the tools and Docker
    is not among them") needs the whole list to rule a requirement out.

Nothing is rewritten: an item that is sent is the same dict, so its id and its
text, and therefore every verbatim quote, are unchanged. The verifier is still
given the FULL index (matcher.py keeps `evidence_by_id` over all of it), so an
id the model cites from memory of an earlier call still resolves.

Words are compared case- and accent-folded, with a crude stem (the first five
letters of a longer word), so "analytics" matches "analysis" and "managing"
matches "management". Over-matching only keeps more.
"""

from __future__ import annotations

import re

from text_utils import normalize_text

# Bump when the selection logic changes: cached matches made under the old one are then not reused.
SELECTION_VERSION = "sel-1"
FOCUSED_VERSION = "sel-1-focused"

# Function words and the boilerplate every ad uses; none says anything about a topic.
STOPWORDS = frozenset(
    """
    a about above across after all also an and any are as at be been being both but by can could do does each
    etc for from had has have having how if in into is it its may more most must no not of on one only or other
    our out over per such than that the their them then there these they this those through to up us use used
    using via was we were what when where which while who will with within without would you your
    able ability years year experience experienced strong proven track record skills skill knowledge working
    work works worked excellent good great plus preferred required requirements requirement including include
    includes least minimum demonstrated relevant related understanding familiarity solid deep hands role roles
    team teams company companies ideally bonus nice
    """.split()
)
_WORD = re.compile(r"[a-z0-9][a-z0-9+#./-]*")
_SHORT_KEPT = frozenset({"ai", "ml", "ux", "ui", "qa", "pm", "bi", "it", "hr", "go", "r", "c"})


def keywords(text: str) -> set[str]:
    """The comparable stems of a text: folded words minus stopwords, long words cut to five letters."""
    out = set()
    for word in _WORD.findall(normalize_text(text or "")):
        for part in {word, *re.split(r"[/.-]+", word)}:
            part = part.strip("+#./-") if len(part) > 1 else part
            if not part or part in STOPWORDS or (len(part) < 3 and part not in _SHORT_KEPT and not part.isdigit()):
                continue
            if part.isdigit():
                continue
            out.add(part[:5] if len(part) > 5 else part)
    return out


def _requirement_words(req: dict) -> set[str]:
    competency = "" if req.get("provisional") else re.sub(r"[-_]+", " ", str(req.get("id") or ""))
    return keywords(f"{req.get('text') or ''} {req.get('postingQuote') or ''} {competency}")


# A stem found in this share of the candidate's own evidence items says nothing about which item matters.
UBIQUITOUS_SHARE = 0.12


def select_evidence(evidence: list[dict], asked: list[dict], keep_facts: bool = True,
                    focused: bool = False) -> tuple[list[dict], list[str]]:
    """(the items to send, in index order; the ids of the items left out).

    `asked` is the list of requirements the model will be asked about.

    Default (strict): any shared keyword keeps an item. `focused` is the looser
    alternative: a stem that appears in UBIQUITOUS_SHARE of the candidate's own items
    ("product", "manage" for a product manager) is ignored for the overlap, unless
    a requirement has no other keyword, in which case its words all count. It sends
    less and can drop an item that shares only such a word with a requirement,
    so it is not the default and the owner decides.
    """
    counts: dict[str, int] = {}
    item_words = [keywords(f"{i.get('text') or ''} {i.get('role') or ''}") for i in evidence]
    for words in item_words:
        for w in words:
            counts[w] = counts.get(w, 0) + 1
    common = {w for w, n in counts.items() if n >= UBIQUITOUS_SHARE * max(1, len(evidence))} if focused else set()
    wanted = set()
    for req in asked:
        words = _requirement_words(req)
        wanted |= (words - common) or words
    seen_roles = set()
    sent, dropped = [], []
    for item, words in zip(evidence, item_words):
        core = False
        if item.get("source") == "role":
            role = item.get("role") or ""
            core = role not in seen_roles
            seen_roles.add(role)
        elif item.get("source") == "fact" and keep_facts:
            core = True
        if core or words & wanted:
            sent.append(item)
        else:
            dropped.append(item["id"])
    return sent, dropped


def mode_of(value) -> str | None:
    """None (off), "strict" or "focused" from a flag value (True, "1", "on", "focused", ...)."""
    text = str(value if value is not None else "").strip().lower()
    if text == "focused":
        return "focused"
    return "strict" if value is True or text in {"1", "true", "yes", "on", "strict"} else None


def version_of(mode: str | None) -> str | None:
    return {"strict": SELECTION_VERSION, "focused": FOCUSED_VERSION}.get(mode)
