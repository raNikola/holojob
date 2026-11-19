"""Clear remote wording in an ad's own text (scoringVersion 1.6, fix 4; owner decision 2026-11-18).

"Fully remote", "100% remote", "work from anywhere" in the description win over a structured field that says onsite or
hybrid: the field is a board default or an extraction guess, the sentence is the ad. A negation just before the phrase
cancels it ("not a fully remote position"). The same list lives in src/modules/jobs/workAuthorization.js
(`clearRemoteText`); tests/python/test_scoring_16.py and tests/js/eligibilityFeasibility.test.js keep them in step.
"""

from __future__ import annotations

import re

_PATTERNS = [re.compile(p) for p in (
    r"\b(?:fully|100%|entirely|completely)[ -]remote\b",
    r"\bwork(?:ing)?\s+(?:remotely\s+)?from\s+anywhere\b",
    r"\bremote\s+from\s+anywhere\b",
)]
_NEGATION = re.compile(r"\b(?:not|no|never|isn't|aren't|non|without)\b[^.;\n]{0,25}$")
# A benefit or an allowance is not the job: "for fully remote workers we provide ...", "two weeks of 'Work from Anywhere' each year".
_PEOPLE_AFTER = re.compile(r"^\W{0,2}\s*(?:workers|employees|colleagues|staff|teammates|team\s+members|candidates|people|contractors)\b")
_ALLOWANCE_BEFORE = re.compile(r"\b(?:weeks?|days?|months?|benefits?|perks?|stipend|policy|programme?)\b[^.;\n]{0,25}$")
_ALLOWANCE_AFTER = re.compile(r"^\W{0,2}\s*(?:each|per|a|every)\s+(?:year|month|quarter)\b|^\W{0,2}\s*annually\b")


def clear_remote_text(description) -> str | None:
    """The phrase of the ad text that says the job is fully remote, or None. Tags and case are ignored."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(description or ""))).replace("’", "'").lower()
    for pattern in _PATTERNS:
        for match in pattern.finditer(text):
            before, after = text[max(0, match.start() - 30):match.start()], text[match.end():match.end() + 30]
            if _NEGATION.search(before) or _PEOPLE_AFTER.search(after) or _ALLOWANCE_BEFORE.search(before) or _ALLOWANCE_AFTER.search(after):
                continue
            return match.group(0)
    return None
