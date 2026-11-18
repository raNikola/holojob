"""Professional Fit 3 on closed lists. SHADOW ONLY: nothing here reaches matchScore, a verdict, a priority or an order.

Plan and pre-registered rules: ~/holojob-eval/w5-plan.md. The model CLASSIFIES into closed lists (roles: fit3_roles.json; competencies:
src/data/competencies/<family>.json) and quotes the ad; code anchors every answer and composes. Nothing maps an ad sentence to an id by
keyword or alias. The classification call sends the ad and the two lists only: no candidate data.

Anchoring (fail closed, each drop counted): a role or competency name outside its list, a mark other than core / secondary, and any claim whose
quote is not found in the ad (normalize.quote_in) are dropped. Role class comes from the config, never from the model's label; the title can only
demote (title role class "other" turns a target / adjacent function into "other"), never promote.

Composition, no blended number and no weight: the order is (role class, domain, core coverage, secondary coverage, id); confidence and
Insufficient evidence are shown beside it. Seniority is a signed distance, shown, never a cap. Eligibility stays the unchanged gate.
A 3.0 row is never ranked with a 1.x, 2.0 or 2.1 row (rank() refuses).
"""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

from job_fingerprint import job_fingerprint

from . import competencies as comp_lists
from .constants import ENGINE_VERSION, MAX_UNKNOWN_MUST_RATIO, MIN_CONFIDENCE
from .fit import credit
from .fit21 import build_units as dictionary_units
from .fit2 import _normal_status
from .normalize import normalize, quote_in
from .verify import NOT_EVIDENCED

SCORING_VERSION = "3.0"
PROMPT_VERSION = 1
ROLES_PATH = Path(__file__).with_name("fit3_roles.json")
ROLE_CLASSES = ("target", "adjacent", "other")
ROLE_ORDER = {"target": 0, "adjacent": 1, "other": 2}  # a missing role class goes after all of them
MARKS = ("core", "secondary")
MARK_IMPORTANCE = {"core": "must", "secondary": "preferred"}
LEVELS = {"junior": 1, "mid": 2, "senior": 3, "lead": 4, "head": 5}
KINDS = ("skill", "domain", "experience", "education", "certification", "other")
SCHEMA = {
    "type": "object",
    "properties": {
        "function": {"type": "object", "properties": {"role": {"type": "string"}, "quote": {"type": "string"}}},
        "title": {"type": "object", "properties": {"role": {"type": "string"}}},
        "competencies": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "mark": {"type": "string"}, "quote": {"type": "string"}}}},
    },
    "required": ["function", "title", "competencies"],
}

PROMPT = """You classify ONE job ad into closed lists. Use only the ad text below. Answer with one JSON object, nothing else.

1. function: the role the ad's actual RESPONSIBILITIES describe (the work, not the title). role = exactly one name from ROLES (use "Other" for hands-on
   engineering and for unrelated functions); quote = one passage copied exactly from the ad that shows the responsibilities.
2. title: the role the ad's TITLE names, one name from ROLES ("Other" when it names none of them).
3. competencies: for each competency of COMPETENCIES that the ad asks for, id = its id exactly, mark = "core" (the ad makes it central or required) or
   "secondary" (mentioned, preferred or minor), quote = one passage copied exactly from the ad that asks for it. Leave out every competency the ad does not ask
   for. Do not invent ids, do not judge any candidate, do not guess what the ad does not say.

TITLE: {title}

ROLES: {roles}

COMPETENCIES (id: definition):
{competencies}

AD:
{description}

JSON shape: {{"function": {{"role": "...", "quote": "..."}}, "title": {{"role": "..."}}, "competencies": [{{"id": "...", "mark": "core", "quote": "..."}}]}}"""


class Fit3Error(ValueError):
    """The reply is not the shape the call asked for (one retry, then the ad has no classification)."""


def load_roles(path: Path | None = None) -> dict[str, str]:
    """name -> class (target / adjacent / other) from the config; a name listed twice is a config error."""
    doc = json.loads((path or ROLES_PATH).read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for cls in ROLE_CLASSES:
        for name in doc.get(cls) or []:
            if name in out:
                raise ValueError(f"role {name!r} is listed twice in the Fit 3 role config")
            out[name] = cls
    return out


def closed_competencies(family: str = "product") -> list[dict]:
    """[{id, definition, kind}] of the family's curated list: the closed list the model picks from."""
    return [{"id": c["id"], "definition": c.get("definition") or "", "kind": c.get("kind")} for c in comp_lists.load(family)]


def lists_hash(roles: dict[str, str], comps: list[dict]) -> str:
    raw = json.dumps([sorted(roles.items()), [(c["id"], c["definition"]) for c in comps]], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def classification_key(posting: dict, roles: dict[str, str], comps: list[dict]) -> str:
    """A stored classification answers exactly this ad under this prompt and these lists."""
    return f"{job_fingerprint(posting)}:f3p{PROMPT_VERSION}:{lists_hash(roles, comps)}"


def build_prompt(posting: dict, roles: dict[str, str], comps: list[dict]) -> str:
    return PROMPT.format(
        title=posting.get("title") or "", roles=json.dumps(list(roles), ensure_ascii=False),
        competencies="\n".join(f"{c['id']}: {c['definition']}" for c in comps), description=posting.get("description") or "")


def check_reply(raw) -> dict:
    """The reply's frame, or Fit3Error. A malformed single entry is not an error: anchor() drops it and counts it."""
    if not isinstance(raw, dict) or not isinstance(raw.get("function"), dict) or not isinstance(raw.get("competencies"), list):
        raise Fit3Error("reply needs a 'function' object and a 'competencies' list")
    return raw


def classify(posting: dict, *, confirmed: bool, provider: str | None, model: str | None, complete, roles=None, comps=None) -> dict:
    """One gated call (the ad and the closed lists only; `confirmed` is the owner's confirm). Returns the raw reply: store it, never the anchored form."""
    if confirmed is not True:
        raise Fit3Error("the Fit 3 classification calls a provider; it needs the owner's confirm")
    import ai_gate
    roles = roles or load_roles()
    comps = comps if comps is not None else closed_competencies()
    prompt = build_prompt(posting, roles, comps)
    for attempt in (1, 2):
        try:
            with ai_gate.context(feature="fit3-classify", job_id=str(posting.get("id") or "") or None):
                return check_reply(complete(prompt, schema=SCHEMA, model=model, provider=provider))
        except Fit3Error:
            if attempt == 2:
                raise
    raise AssertionError("unreachable")


def anchor(raw: dict, description: str, roles: dict[str, str], comps: list[dict]) -> dict:
    """The model's reply made safe by code: {role, competencies, dropped}. See the module docstring for what is dropped."""
    dropped = {"role": 0, "title": 0, "unknownId": 0, "badMark": 0, "unquoted": 0, "duplicate": 0}
    by_name = {normalize(n): n for n in roles}
    ids = {c["id"] for c in comps}
    fn = raw.get("function") if isinstance(raw.get("function"), dict) else {}
    fn_name = by_name.get(normalize(fn.get("role")))
    if fn_name is None or not quote_in(fn.get("quote"), description):
        dropped["role"] += 1
        fn_name = None
    title = raw.get("title") if isinstance(raw.get("title"), dict) else {}
    title_name = by_name.get(normalize(title.get("role")))
    if title_name is None:
        dropped["title"] += 1
    function_class = roles[fn_name] if fn_name else None
    title_class = roles[title_name] if title_name else None
    demoted = function_class in ("target", "adjacent") and title_class == "other"
    marks: dict[str, dict] = {}
    for entry in raw.get("competencies") or []:
        if not isinstance(entry, dict):
            dropped["badMark"] += 1
            continue
        cid, mark = entry.get("id"), entry.get("mark")
        if cid not in ids:
            dropped["unknownId"] += 1
            continue
        if mark not in MARKS:
            dropped["badMark"] += 1
            continue
        if not quote_in(entry.get("quote"), description):
            dropped["unquoted"] += 1
            continue
        if cid in marks:
            dropped["duplicate"] += 1
            if MARKS.index(mark) >= MARKS.index(marks[cid]["mark"]):
                continue
        marks[cid] = {"id": cid, "mark": mark, "quote": str(entry["quote"]).strip()}
    return {"role": {"function": fn_name, "functionClass": function_class, "title": title_name, "titleClass": title_class,
                     "demotedByTitle": demoted, "class": "other" if demoted else function_class,
                     "quote": str(fn.get("quote") or "").strip() if fn_name else None},
            "competencies": [marks[k] for k in sorted(marks)], "dropped": dropped}


def matcher_requirements(anchored: dict, comps: list[dict]) -> list[dict]:
    """One requirement row per marked competency for the existing matcher (layer b): id = the competency id, text = its definition, the ad quote as postingQuote."""
    by_id = {c["id"]: c for c in comps}
    rows = []
    for m in anchored["competencies"]:
        c = by_id[m["id"]]
        rows.append({"id": m["id"], "text": c["definition"] or m["id"], "kind": c.get("kind") if c.get("kind") in KINDS else "other",
                     "importance": MARK_IMPORTANCE[m["mark"]], "postingQuote": m["quote"], "qualifier": None, "provisional": False})
    return rows


def _units(anchored: dict, answers: list[dict] | None) -> list[dict]:
    """Layer (b): the matcher's status for each marked competency, by its own id. No answer is UNKNOWN: never NOT_EVIDENCED, never taken from another id."""
    by_id: dict[str, dict] = {}
    for row in answers or []:
        if isinstance(row, dict) and row.get("id") not in by_id:
            by_id[row.get("id")] = row
    out = []
    for m in anchored["competencies"]:
        row = by_id.get(m["id"])
        out.append({"id": m["id"], "ask": m["mark"], "adQuote": m["quote"],
                    "status": _normal_status(row.get("status")) if row else "UNKNOWN",
                    "strength": (row.get("strength") if row else 0) or 0,
                    "quoteVerified": bool(row and row.get("quoteVerified") is True), "answered": row is not None})
    return out


def _coverage(units: list[dict]) -> Fraction:
    return sum((credit(u) for u in units), Fraction(0)) / len(units) if units else Fraction(0)


def _domain(requirements: list[dict] | None) -> str:
    """different / match / unknown from the stored matcher answers' domain units (no new call)."""
    _, domains, _ = dictionary_units(requirements)
    if any(u["status"] == "CONTRADICTED" and u["importance"] == "must" for u in domains):
        return "different"
    return "match" if any(u["status"] in ("MET", "PARTIAL") for u in domains) else "unknown"


def seniority(ad_level: str | None, candidate_level: str | None) -> dict:
    ad, cand = LEVELS.get(str(ad_level or "").lower()), LEVELS.get(str(candidate_level or "").lower())
    distance = None if ad is None or cand is None else cand - ad
    return {"ad": ad_level if ad else None, "candidate": candidate_level if cand else None, "distance": distance,
            "reading": None if distance is None else ("match" if distance == 0 else "candidate above" if distance > 0 else "candidate below")}


def fit3(anchored: dict | None, answers: list[dict] | None = None, requirements: list[dict] | None = None, *,
         ad_level: str | None = None, candidate_level: str | None = None) -> dict:
    """The Fit 3 block of one posting. `anchored` = anchor() of the stored reply; `answers` = matcher rows over matcher_requirements();
    `requirements` = the ad's stored 1.x matcher answers (domain only)."""
    anchored = anchored or {"role": {"class": None}, "competencies": [], "dropped": {}}
    units = _units(anchored, answers)
    core, secondary = ([u for u in units if u["ask"] == m] for m in MARKS)
    role_class = anchored["role"].get("class")
    verified = sum(1 for u in core if u["status"] == "CONTRADICTED" or (u["status"] in ("MET", "PARTIAL") and u["quoteVerified"]))
    confidence = Fraction(verified, len(core)) if core else Fraction(0)
    unproved = sum(1 for u in core if u["status"] in ("UNKNOWN", NOT_EVIDENCED))
    reasons = []
    if role_class is None:
        reasons.append("role not available")
    if not core:
        reasons.append("no core competency")
    else:
        if confidence < MIN_CONFIDENCE:
            reasons.append("low confidence")
        if Fraction(unproved, len(core)) > MAX_UNKNOWN_MUST_RATIO:
            reasons.append("too many core competencies not judged")
    core_cov, sec_cov = _coverage(core), _coverage(secondary)
    counts = {"core": len(core), "secondary": len(secondary), "answered": sum(u["answered"] for u in units)}
    for status in ("MET", "PARTIAL", "CONTRADICTED", NOT_EVIDENCED, "UNKNOWN"):
        counts[status] = sum(u["status"] == status for u in core)
    return {
        "scoringVersion": SCORING_VERSION,
        "engineVersion": ENGINE_VERSION,
        "promptVersion": PROMPT_VERSION,
        "role": anchored["role"],
        "domain": _domain(requirements),
        "requirements": {"units": units, "coreCounts": counts, "coreCoverage": str(core_cov), "secondaryCoverage": str(sec_cov),
                         "coverage": float(round(core_cov, 4)) if core else None},
        "seniority": seniority(ad_level, candidate_level),
        "confidence": float(round(confidence, 4)),
        "insufficientEvidence": bool(reasons),
        "insufficientReasons": reasons,
        "dropped": anchored.get("dropped") or {},
    }


class MixedScoringVersions(ValueError):
    """A rank list held a 3.0 row and something else."""


def order_key(block: dict) -> tuple:
    """The pre-declared ordering rule: role class, then domain (only "different" is worse), then core coverage, then secondary coverage."""
    r = block["requirements"]
    return (ROLE_ORDER.get(block["role"].get("class"), len(ROLE_ORDER)), block["domain"] == "different",
            -Fraction(r["coreCoverage"]), -Fraction(r["secondaryCoverage"]))


def rank(rows: list[dict]) -> list[dict]:
    """Rows (each {"id", "fit3": {...}}) best first by order_key, id as the tie-break. Refuses a list in which any row is not scoringVersion 3.0."""
    for row in rows:
        block = row.get("fit3")
        if not isinstance(block, dict) or block.get("scoringVersion") != SCORING_VERSION:
            raise MixedScoringVersions(f"row {row.get('id')!r} is not a scoringVersion {SCORING_VERSION} row")
    return sorted(rows, key=lambda r: (*order_key(r["fit3"]), str(r.get("id"))))


def stored_fit3(job: dict, posting: dict, store: dict | None, roles: dict[str, str], comps: list[dict],
                requirements: list[dict] | None, candidate_level: str | None = None) -> dict | None:
    """The block for a job from the stored entry {"reply": raw, "answers": [rows] | None}, or None when the ad has no stored classification."""
    entry = (store or {}).get(classification_key(posting, roles, comps))
    if not isinstance(entry, dict) or not isinstance(entry.get("reply"), dict):
        return None
    anchored = anchor(entry["reply"], posting.get("description") or "", roles, comps)
    return fit3(anchored, entry.get("answers"), requirements, ad_level=(job.get("llmFacts") or {}).get("seniority"),
                candidate_level=candidate_level)
