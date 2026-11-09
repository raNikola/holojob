"""Verify resume content traces to candidate profile/intelligence only.

The fact gate (DECISIONS.md principle 8): text a model wrote is checked in code against the candidate's confirmed
facts, and a draft with anything unverified is rejected as a whole (the caller falls back to rule-based content).

Claim types covered, each matched against the facts as whole tokens:
- metrics with a unit (%, users, customers, ms, x, k, m): the fact must state the metric with its unit;
- every other number ("47 engineers", "$8 billion", a headcount, an amount, a year): the number must appear in a fact;
- years of experience ("12+ years"): a fact must state that many years, or be that bare number (`experienceYears`);
- named things: every capitalised word that does not open a sentence (employers, titles, schools, projects,
  technologies, products) must occur in the facts, the job's own title / company / location, or the project
  intelligence names the candidate keeps (`extra`); the subtitle is checked word by word the same way;
- degrees and certifications (bachelor, master's, MBA, PhD, diploma, certified, certification, certificate):
  a fact must contain the same word.
Structure is checked elsewhere: experience companies must be in the CV (`llm_tailor._validate`), skills must be in the
candidate's skill pool and projects in project intelligence (`run_tailor._apply_llm_content`).

A pass means "passed the defined automatic checks" (`provenancePassed`, a verdict file), never that every statement is true; the
owner reads a document before sending it. NOT covered: a lowercase technology or role invented in prose ("built it on kubernetes"), a true fact reworded into a
false one with the same words and numbers, a number reused with another meaning when the same number occurs elsewhere
in the CV, tone and quality. The gate checks that claims trace to facts, not that they are well written.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

# The whole number ("1.5%", "1,000 users") and the whole unit word ("5 xylophones"), so that a metric is compared as
# one token. Finds a metric in the same places as a plain number and unit would; only the matched text is longer.
METRIC_RE = re.compile(r"\b\d+(?:[.,]\d+)*(?:%|\s*(?:users|customers|ms|x)\w*|\s*[km]\b)", re.I)


# Any number as one token, with the letters glued to it ("5G", "3M", "10k", "2x") so that a fact "5g" vouches for "5G".
NUMBER_RE = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*[^\W\d_]*%?")
YEARS_RE = re.compile(r"(?<![\w.,])(\d+)\+?\s*(?:years?|yrs?)\b", re.I)
WORD_RE = re.compile(r"[^\W\d_][\w'’&+#.-]*")
# A word that opens a sentence or a bullet is capitalised without being a name.
SENTENCE_END = ".!?:;•*|–—\"“"
ALWAYS_OK = {"i", "january", "february", "march", "april", "may", "june", "july", "august", "september",
             "october", "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday"}
SUBTITLE_FILLER = {"and", "the", "for", "with", "from", "into", "of", "in", "on", "at", "to", "a", "an"}
# Degree and certification words. "master" only as the degree ("master's", "master of"), not the verb or "scrum master".
CREDENTIALS = {
    "bachelor": re.compile(r"\bbachelor", re.I),
    "master's degree": re.compile(r"\bmaster(?:'s|’s|s)\b|\bmaster of\b|\bmaster degree\b", re.I),
    "mba": re.compile(r"\bmba\b", re.I),
    "phd": re.compile(r"\bph\.?\s?d\b|\bdoctorate\b|\bdoctoral\b", re.I),
    "diploma": re.compile(r"\bdiploma", re.I),
    "bsc/msc": re.compile(r"\b[bm]\.?\s?sc\b", re.I),
    "certification": re.compile(r"\bcertif(?:ied|ication|icate)", re.I),
}


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").replace("đ", "dj").replace("Đ", "Dj"))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _clean_word(word: str) -> str:
    word = re.sub(r"(?:'s|’s)$", "", word).rstrip(".-'’")
    return _fold(word)


def _vocabulary(*sources: Iterable[str]) -> set[str]:
    vocab: set[str] = set()
    for source in sources:
        for text in source:
            vocab.update(_clean_word(m.group(0)) for m in WORD_RE.finditer(text or ""))
    vocab.discard("")
    return vocab


def build_canonical_facts(profile: dict, intelligence: dict) -> set[str]:
    facts: set[str] = set()
    basic = profile.get("basicProfile") or {}
    for v in basic.values():
        if isinstance(v, str) and v.strip():
            facts.add(v.strip().lower())

    resume = profile.get("resume") or {}
    parsed = resume.get("parsedData") or {}
    for key in ("skills", "projects", "education", "workExperience", "certifications"):
        for item in parsed.get(key) or []:
            if isinstance(item, str) and item.strip():
                facts.add(item.strip().lower())

    raw = resume.get("rawText") or ""
    for line in raw.splitlines():
        line = line.strip()
        if len(line) > 4:
            facts.add(line.lower())

    exp_map = intelligence.get("experienceMap") or {}
    for key in ("projectHighlights", "ownershipExamples", "leadershipExamples", "businessImpactExamples"):
        for item in exp_map.get(key) or []:
            if isinstance(item, str) and item.strip():
                facts.add(item.strip().lower())

    skills_map = intelligence.get("skillsMap") or {}
    for items in skills_map.values():
        if isinstance(items, list):
            for s in items:
                if str(s or "").strip():
                    facts.add(str(s).strip().lower())

    return facts


def metric_in_fact(metric: str) -> re.Pattern[str]:
    """A metric as a whole token: 50% is not in 150% or 1.50%, 10m is not in 10ms. A letter before it changes no number."""
    after = "" if metric.endswith("%") else r"(?!\w)"
    return re.compile(r"(?<!\d)(?<!\d[.,])" + re.escape(metric) + after)


def check_provenance(content: str, facts: set[str]) -> tuple[bool, list[str]]:
    """Return (passed, issues). Flags metrics not found in source facts.

    Only a fact that states the metric can vouch for it. A fact inside the metric never does: years of experience "5"
    say nothing about 5% or 500%, and a skill "R" says nothing about 870 users.
    """
    issues: list[str] = []
    for match in METRIC_RE.finditer(content):
        pattern = metric_in_fact(match.group(0).lower())
        if not any(pattern.search(f) for f in facts):
            issues.append(f"Unverified metric or number: {match.group(0)}")

    return len(issues) == 0, issues


def check_numbers(content: str, facts: set[str]) -> list[str]:
    """Every number of `content` that no fact states, as one whole token. Unit metrics are matched with their unit
    by `check_provenance`; this covers the rest ("47 engineers", "$8 billion", an invented year)."""
    issues = []
    metrics = [m.span() for m in METRIC_RE.finditer(content)]
    for match in NUMBER_RE.finditer(content):
        if any(a <= match.start() < b for a, b in metrics):
            continue
        token = match.group(0).lower()
        if not any(metric_in_fact(token).search(f) for f in facts):
            issues.append(f"Unverified number: {match.group(0)}")
    return issues


def check_years(content: str, facts: set[str]) -> list[str]:
    """Years of experience: a fact must state that many years, or be that bare number (`experienceYears`)."""
    issues = []
    for match in YEARS_RE.finditer(content):
        n = match.group(1)
        stated = re.compile(rf"(?<![\w.,]){n}\+?\s*(?:years?|yrs?)\b", re.I)
        if not any(f.strip().rstrip("+") == n or stated.search(f) for f in facts):
            issues.append(f"Unverified years of experience: {match.group(0)}")
    return issues


def check_credentials(content: str, facts: set[str]) -> list[str]:
    """A degree or certification word the text uses must occur in a fact."""
    return [f"Unverified degree or certification: {name}" for name, pattern in CREDENTIALS.items()
            if pattern.search(content) and not any(pattern.search(f) for f in facts)]


def check_named_things(content: str, vocab: set[str]) -> list[str]:
    """Capitalised words that do not open a sentence must be words of the facts, the job or the project names."""
    issues = []
    for match in WORD_RE.finditer(content):
        word = match.group(0)
        if not word[0].isupper():
            continue
        before = content[: match.start()]
        stripped = before.rstrip()
        if not stripped or stripped[-1] in SENTENCE_END or "\n" in before[len(stripped):]:
            continue
        clean = _clean_word(word)
        if len(clean) < 2 or clean in ALWAYS_OK or clean in vocab:
            continue
        issues.append(f"Unverified name or term: {word}")
    return issues


def check_subtitle(subtitle: str, vocab: set[str]) -> list[str]:
    """The tagline is in title case, so each word is checked, not only the capitalised ones mid-sentence."""
    words = {_clean_word(m.group(0)) for m in WORD_RE.finditer(subtitle or "")}
    return [f"Unverified title wording: {w}" for w in sorted(words)
            if len(w) >= 3 and w not in vocab and w not in SUBTITLE_FILLER and w not in ALWAYS_OK]


def check_document(content: str, facts: set[str]) -> list[str]:
    """Numbers, metrics with their unit, years of experience and degrees of finished text (a rendered document or a
    drafted string). Named things are not checked here: a document also holds the template's own headings."""
    return check_provenance(content, facts)[1] + check_numbers(content, facts) + check_years(content, facts) \
        + check_credentials(content, facts)


def drafted_texts(draft: dict) -> dict[str, list[str]]:
    """The strings a model wrote, by kind. Shape problems are `llm_tailor._validate`'s, so missing parts are skipped."""
    def strings(value):
        return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []

    bullets, project_lines = [], []
    for entry in draft.get("experience") or []:
        if isinstance(entry, dict):
            bullets += strings(entry.get("bullets"))
    for entry in draft.get("projects") or []:
        if isinstance(entry, dict) and isinstance(entry.get("line"), str):
            project_lines.append(entry["line"])
    return {
        "subtitle": strings([draft.get("subtitle")]),
        "prose": strings([draft.get("summary")]) + bullets + project_lines + strings(draft.get("cover_letter_paragraphs")),
    }


def check_draft(draft: dict, facts: set[str], *, job: dict | None = None, extra: Iterable[str] = ()) -> list[str]:
    """All claim checks on what a model drafted; an empty list means every claim traces to a fact.

    `job` supplies the title, company and location, which are the target and may be named. `extra` is text whose
    names (not numbers) may be used: the names of the candidate's own projects from project intelligence.
    """
    job = job or {}
    context = [str(job.get(k) or "") for k in ("title", "company", "location")]
    vocab = _vocabulary(facts, context, extra)
    allowed = facts | {c.lower() for c in context if c}
    texts = drafted_texts(draft)
    issues: list[str] = []
    for text in texts["subtitle"]:
        issues += check_subtitle(text, vocab)
    for text in texts["subtitle"] + texts["prose"]:
        issues += check_document(text, allowed)
    for text in texts["prose"]:
        issues += check_named_things(text, vocab)
    return list(dict.fromkeys(issues))
