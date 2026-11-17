"""Role mix of an ad's responsibilities, by deterministic verb + object cues. Code only, no model. SHADOW ONLY (Fit 2.1, `engineShadow.fit21.role`).

The cue lists below are the ones declared in ~/holojob-eval/w4-plan.md section 3 BEFORE any measurement (verbs read as base forms, A1.5).
A cue family is a pair (verbs, objects) and fires only when an inflected verb is followed, within three words, by one of its object
phrases: "engineering", "product" or "delivery" on their own never fire anything, and a noun such as "developer", "manager" or
"leadership" is not a verb. A responsibility's class is the class with the strictly highest number of fired families; a tie is
ambiguous, none is unclassified. The families that fired are counted per ad, so the word matching is visible.

Role Fit = 100 x (product + program) / (product + program + engineering + operations) over the classified responsibilities. Not
available when there is no responsibility text or none is classified: the title tier is never a substitute. Insufficient evidence
for the role part when classified / all responsibilities is below MIN_CONFIDENCE (1/2).
"""

from __future__ import annotations

import re
from fractions import Fraction

from .constants import MIN_CONFIDENCE
from .fit import round_half_up

CLASSES = ("product", "program", "engineering", "operations")
PM_CLASSES = ("product", "program")

# Irregular inflections (everything else follows the regular rules in _forms).
_IRREGULAR = {
    "run": ("ran",), "build": ("built",), "lead": ("led",), "write": ("wrote", "written"), "drive": ("drove", "driven"),
    "bring": ("brought",), "set": (), "ship": (), "own": (), "hire": (),
}


def _forms(base: str) -> list[str]:
    """The inflections of a verb: base, +s, +es, +ed, +d, +ing, e-drop, consonant doubling (one-syllable verbs), irregulars."""
    forms = {base, base + "s", base + "es", base + "ed", base + "d", base + "ing", *_IRREGULAR.get(base, ())}
    if base.endswith("e"):
        forms |= {base[:-1] + "ing", base + "d"}
    if base.endswith("y") and base[-2:-1] not in "aeiou":
        forms |= {base[:-1] + "ies", base[:-1] + "ied"}
    if re.search(r"[^aeiou][aeiou][^aeiouwxy]$", base) and base in ONE_SYLLABLE:
        forms |= {base + base[-1] + "ed", base + base[-1] + "ing"}
    return sorted(forms)


ONE_SYLLABLE = {"run", "set", "ship", "plan", "rack", "commit", "cable"}

# (class, family, verbs, objects)
_FAMILIES = (
    ("product", "product.roadmap",
     "own define drive shape set lead build develop maintain prioritize prioritise",
     "product roadmap|product strategy|product vision|roadmap|product backlog|backlog|product requirement|user stor|product discovery|product lifecycle|product priorit"),
    ("product", "product.customer",
     "conduct run gather translate synthesize synthesise analyze analyse interview understand identify",
     "customer need|customer feedback|customer problem|customer insight|customer interview|user research|user need|user feedback|market research|market need"),
    ("product", "product.metrics",
     "define track monitor analyze analyse measure set",
     "product metric|success metric|product kpi|adoption metric|key result|okr"),
    ("product", "product.launch",
     "launch ship release bring drive plan",
     "product launch|new product|product feature|go to market|product release"),
    ("program", "program.delivery",
     "manage lead drive coordinate run oversee own plan track deliver",
     "program delivery|program|programme|technical program|cross functional program|project plan|project schedule|project timeline|delivery timeline|release schedule|release plan|milestone|cross team dependenc|dependenc|program risk|project risk|risks and dependenc|cross functional team"),
    ("program", "program.ceremonies",
     "facilitate run lead conduct",
     "sprint planning|scrum ceremon|agile ceremon|retrospective|stand up|standup|program review|status meeting|steering committee"),
    ("program", "program.reporting",
     "report communicate provide escalate manage",
     "program status|project status|status update|status report|stakeholder expectation|executive update|risks and issue"),
    ("program", "program.process",
     "establish drive define improve implement",
     "delivery process|program governance|project governance|agile practice|delivery cadence|release process|planning process"),
    ("engineering", "eng.code",
     "write develop design build implement architect review debug refactor optimize optimise",
     "code|software|backend service|backend system|microservice|api|distributed system|system architecture|software architecture|data pipeline|unit test|pull request|code review|production code|algorithm|database|scalable system|technical architecture"),
    ("engineering", "eng.codebase",
     "contribute commit work",
     "codebase|code base|repositor"),
    ("engineering", "eng.mentor",
     "mentor coach",
     "engineer|software engineer|backend engineer|developer|engineering team"),
    ("operations", "ops.incidents",
     "monitor maintain operate support troubleshoot resolve respond handle triage",
     "production incident|incident|production issue|outage|system uptime|service level|sla|support ticket|customer ticket|service request|on call rotation|on call"),
    ("operations", "ops.physical",
     "install commission rack cable inspect procure source order maintain manage",
     "hardware|server|rack|equipment|network equipment|machinery|component|material|data center equipment|data center operation|facilit|inventory|supply chain|logistic|warehouse|production line|manufacturing operation|plant operation|field operation|maintenance schedule"),
)


def _compile(verbs: str, objects: str) -> re.Pattern:
    forms = sorted({f for v in verbs.split() for f in _forms(v)}, key=len, reverse=True)
    # Object entries are phrase stems: an optional plural / suffix tail is allowed on the last word only ("user stor" = story, stories).
    objs = "|".join(re.escape(o).replace(r"\ ", " ") for o in objects.split("|"))
    return re.compile(rf"\b(?:{'|'.join(forms)})\b(?: \w+){{0,3}}? (?:{objs})\w*\b")


FAMILIES = tuple((cls, name, _compile(verbs, objects)) for cls, name, verbs, objects in _FAMILIES)
FAMILY_NAMES = tuple(name for _, name, _ in FAMILIES)


def normalize(text: str | None) -> str:
    """Lower-case, punctuation to spaces, whitespace collapsed (apostrophes join: "don't" is "dont")."""
    return " ".join(re.sub(r"[^\w]+", " ", re.sub(r"['’]", "", (text or "").lower())).split())


def classify(text: str | None) -> dict:
    """{"class": product|program|engineering|operations|ambiguous|None, "families": [names that fired]} for one responsibility."""
    norm = normalize(text)
    fired = [(cls, name) for cls, name, pattern in FAMILIES if pattern.search(norm)]
    score = {c: sum(1 for cls, _ in fired if cls == c) for c in CLASSES}
    top = max(score.values()) if score else 0
    winners = [c for c, n in score.items() if n == top]
    cls = None if top == 0 else (winners[0] if len(winners) == 1 else "ambiguous")
    return {"class": cls, "families": [name for _, name in fired]}


def role_mix(responsibilities: list[dict] | None) -> dict:
    """The role block of one ad from its responsibilities (each with `text`). No text anywhere in the result, only counts."""
    items = [r for r in responsibilities or [] if isinstance(r, dict) and (r.get("text") or "").strip()]
    counts = {c: 0 for c in CLASSES}
    counts.update({"ambiguous": 0, "unclassified": 0})
    cues = {name: 0 for name in FAMILY_NAMES}
    for item in items:
        got = classify(item["text"])
        counts[got["class"] or "unclassified"] += 1
        for name in got["families"]:
            cues[name] += 1
    classified = sum(counts[c] for c in CLASSES)
    total = len(items)
    if not total:
        return {"available": False, "roleFit": None, "insufficient": True, "reasons": ["no responsibility text"],
                "total": 0, "classified": 0, "counts": counts, "cuesFired": {}}
    reasons = []
    if not classified:
        reasons.append("no responsibility classified")
    elif Fraction(classified, total) < MIN_CONFIDENCE:
        reasons.append("too few responsibilities classified")
    pm = sum(counts[c] for c in PM_CLASSES)
    return {
        "available": bool(classified),
        "roleFit": int(round_half_up(Fraction(100 * pm, classified))) if classified else None,
        "insufficient": bool(reasons), "reasons": reasons, "total": total, "classified": classified, "counts": counts,
        "cuesFired": {k: v for k, v in cues.items() if v},
    }
