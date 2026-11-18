"""Professional Fit 3 on closed lists. SHADOW ONLY: nothing here reaches matchScore, a verdict, a priority or an order.

Plan and pre-registered rules: ~/holojob-eval/w5-plan.md. The model CLASSIFIES into closed lists (roles: fit3_roles.json; competencies:
src/data/competencies/<family>.json) and quotes the ad; code anchors every answer and composes. Nothing maps an ad sentence to an id by
keyword or alias. The classification call sends the ad and the two lists only: no candidate data.

Anchoring (fail closed, each drop counted; amendment A1.1): a role or competency name outside its list and a mark other than core / secondary are
dropped; an item in the wrong list is dropped and counted `misplaced` (A2.5); a secondary mark without a verbatim ad quote is dropped, a core mark without one falls to secondary
with status UNKNOWN (never dropped, never sent to the matcher). Role class comes from the config, never from the model's label; the title can only
demote, and only when it names a SPECIFIC role of the Other list with a quote found in the ad title (A1.5), never promote.

Composition, no blended number and no weight (A1.3, A1.4): coverage is credit over the RESOLVED units (MET / PARTIAL with a verified quote,
CONTRADICTED); UNKNOWN and NOT_EVIDENCED are left out of the denominator and shown as confidence; V1 adds NOT_EVIDENCED at half weight to the
denominator. Order: tier (target and adjacent together, then other), domain (different last), core coverage, secondary coverage, id; Insufficient
evidence is a separate group, never ranked among the rest. Domain is the ad's industry against the candidate's by synonym (fit3_industry.py).
Seniority is a signed distance, shown, never a cap. Eligibility stays the unchanged gate. A 3.0 row is never ranked with a 1.x, 2.0 or 2.1 row.
"""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

from job_fingerprint import job_fingerprint

from . import competencies as comp_lists
from .constants import ENGINE_VERSION, MAX_UNKNOWN_MUST_RATIO, MIN_CONFIDENCE, PARTIAL_FACTOR
from .fit import credit
from .fit3_industry import Industries, compare as compare_industries
from .fit2 import _normal_status
from .normalize import normalize, quote_in
from .verify import NOT_EVIDENCED

SCORING_VERSION = "3.0"
PROMPT_VERSION = 2
GENERIC_ROLE = "Other"  # the unclear / no-role answer: it never demotes by title (A1.5)
ROLES_PATH = Path(__file__).with_name("fit3_roles.json")
ROLE_CLASSES = ("target", "adjacent", "other")
TIER = {"target": 0, "adjacent": 0, "other": 1}  # target and adjacent are ordered together (A1.4); a missing class goes after both
VARIANTS = ("v0", "v1")
MARKS = ("core", "secondary")
MARK_IMPORTANCE = {"core": "must", "secondary": "preferred"}
LEVELS = {"junior": 1, "mid": 2, "senior": 3, "lead": 4, "head": 5}
KINDS = ("skill", "domain", "experience", "education", "certification", "other")
SCHEMA = {
    "type": "object",
    "properties": {
        "function": {"type": "object", "properties": {"role": {"type": "string"}, "quote": {"type": "string"}}},
        "title": {"type": "object", "properties": {"role": {"type": "string"}, "quote": {"type": "string"}}},
        "competencies": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "mark": {"type": "string"}, "quote": {"type": "string"}}}},
    },
    "required": ["function", "title", "competencies"],
}

PROMPT = """You classify ONE job ad into closed lists. Use only the ad text below. Answer with one JSON object, nothing else.

1. function: the role the ad's actual RESPONSIBILITIES describe (the work, not the title). role = exactly one name from ROLES (use "Other" for hands-on
   engineering and for unrelated functions); quote = one passage copied exactly from the ad that shows the responsibilities.
2. title: the role the ad's TITLE names, one name from ROLES ("Other" when it names none of them or when it is unclear); quote = the words of the TITLE
   that name it, copied exactly (leave quote empty when role is "Other").
3. competencies: for each competency of COMPETENCIES that the ad asks for, id = its id exactly, mark = "core" (the ad makes it central or required) or
   "secondary" (mentioned, preferred or minor), quote = one passage copied exactly from the ad that asks for it. Leave out every competency the ad does not ask
   for. Do not invent ids, do not judge any candidate, do not guess what the ad does not say.

TITLE: {title}

ROLES: {roles}

COMPETENCIES (id: definition):
{competencies}

AD:
{description}

JSON shape: {{"function": {{"role": "...", "quote": "..."}}, "title": {{"role": "...", "quote": "..."}}, "competencies": [{{"id": "...", "mark": "core", "quote": "..."}}]}}"""


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


def anchor(raw: dict, description: str, roles: dict[str, str], comps: list[dict], title: str = "") -> dict:
    """The model's reply made safe by code: {role, competencies, dropped, modelMarks}. See the module docstring for what is dropped, moved, demoted."""
    dropped = {"role": 0, "title": 0, "unknownId": 0, "badMark": 0, "unquoted": 0, "duplicate": 0, "misplaced": 0, "coreDemoted": 0}
    by_name = {normalize(n): n for n in roles}
    ids = {c["id"] for c in comps}
    fn = raw.get("function") if isinstance(raw.get("function"), dict) else {}
    ttl = raw.get("title") if isinstance(raw.get("title"), dict) else {}
    fn_quote = str(fn.get("quote") or "").strip()
    fn_name = by_name.get(normalize(fn.get("role")))
    if fn_name is not None and not quote_in(fn_quote, description):
        fn_name = None
    title_name = by_name.get(normalize(ttl.get("role")))
    marks: dict[str, dict] = {}

    def put(cid: str, mark: str, quote: str | None) -> None:
        old = marks.get(cid)
        if old:
            dropped["duplicate"] += 1
            stronger = MARKS.index(mark) < MARKS.index(old["mark"])
            better_quote = mark == old["mark"] and old["quote"] is None and quote is not None
            if not (stronger or better_quote):
                return
        marks[cid] = {"id": cid, "mark": mark, "quote": quote, **({"demotedFromCore": True} if quote is None else {})}

    # A2.5: an item in the wrong list (a competency id in a role slot) is dropped and counted, never moved.
    for name in (fn.get("role"), ttl.get("role")):
        if isinstance(name, str) and name in ids and normalize(name) not in by_name:
            dropped["misplaced"] += 1

    entries = raw.get("competencies") or []
    for entry in entries:
        if not isinstance(entry, dict):
            dropped["badMark"] += 1
            continue
        cid, mark = entry.get("id"), entry.get("mark")
        quote = str(entry.get("quote") or "").strip()
        if cid not in ids:
            if isinstance(cid, str) and normalize(cid) in by_name:  # A2.5: a role name in the competency list is dropped, not moved
                dropped["misplaced"] += 1
            else:
                dropped["unknownId"] += 1
            continue
        if mark not in MARKS:
            dropped["badMark"] += 1
            continue
        if quote_in(quote, description):
            put(cid, mark, quote)
        elif mark == "core":
            dropped["coreDemoted"] += 1
            put(cid, "secondary", None)
        else:
            dropped["unquoted"] += 1

    dropped["role"] += fn_name is None
    dropped["title"] += title_name is None
    function_class = roles[fn_name] if fn_name else None
    title_class = roles[title_name] if title_name else None
    specific_other = title_name is not None and title_class == "other" and normalize(title_name) != normalize(GENERIC_ROLE)
    title_quoted = quote_in(ttl.get("quote"), title)
    demoted = function_class in ("target", "adjacent") and specific_other and title_quoted
    return {"role": {"function": fn_name, "functionClass": function_class, "title": title_name, "titleClass": title_class,
                     "titleQuoted": bool(title_quoted), "demotedByTitle": bool(demoted), "class": "other" if demoted else function_class,
                     "quote": fn_quote if fn_name else None},
            "competencies": [marks[k] for k in sorted(marks)], "dropped": dropped, "modelMarks": len(entries)}


def matcher_requirements(anchored: dict, comps: list[dict]) -> list[dict]:
    """One requirement row per QUOTED marked competency for the existing matcher (layer b): id = the competency id, text = its definition, the ad quote as
    postingQuote. A core mark that fell to secondary for want of a quote gets no row (A1.1)."""
    by_id = {c["id"]: c for c in comps}
    rows = []
    for m in anchored["competencies"]:
        if not m["quote"]:
            continue
        c = by_id[m["id"]]
        rows.append({"id": m["id"], "text": c["definition"] or m["id"], "kind": c.get("kind") if c.get("kind") in KINDS else "other",
                     "importance": MARK_IMPORTANCE[m["mark"]], "postingQuote": m["quote"], "qualifier": None, "provisional": False})
    return rows


def _units(anchored: dict, answers: list[dict] | None) -> list[dict]:
    """Layer (b): the matcher's status for each marked competency, by its own id. No answer is UNKNOWN: never NOT_EVIDENCED, never taken from another id.
    A mark without an ad quote was never asked: UNKNOWN."""
    by_id: dict[str, dict] = {}
    for row in answers or []:
        if isinstance(row, dict) and row.get("id") not in by_id:
            by_id[row.get("id")] = row
    out = []
    for m in anchored["competencies"]:
        row = by_id.get(m["id"]) if m["quote"] else None
        out.append({"id": m["id"], "ask": m["mark"], "adQuote": m["quote"], "demotedFromCore": bool(m.get("demotedFromCore")),
                    "status": _normal_status(row.get("status")) if row else "UNKNOWN",
                    "strength": (row.get("strength") if row else 0) or 0,
                    "quoteVerified": bool(row and row.get("quoteVerified") is True), "answered": row is not None})
    return out


def resolved(unit: dict) -> bool:
    """MET / PARTIAL with a verified quote, or CONTRADICTED: the units that enter the coverage denominator (A1.3)."""
    return unit["status"] == "CONTRADICTED" or (unit["status"] in ("MET", "PARTIAL") and unit["quoteVerified"])


def _coverage(units: list[dict], v1: bool = False) -> Fraction | None:
    """Credit over the resolved units; None when there is no resolved unit. V1: NOT_EVIDENCED units add half their weight to the denominator, no credit."""
    done = [u for u in units if resolved(u)]
    denominator = len(done) + (PARTIAL_FACTOR * sum(u["status"] == NOT_EVIDENCED for u in units) if v1 else 0)
    return sum((credit(u) for u in done), Fraction(0)) / denominator if denominator else None


def _text(value: Fraction | None) -> str | None:
    return None if value is None else str(value)


def seniority(ad_level: str | None, candidate_level: str | None) -> dict:
    ad, cand = LEVELS.get(str(ad_level or "").lower()), LEVELS.get(str(candidate_level or "").lower())
    distance = None if ad is None or cand is None else cand - ad
    return {"ad": ad_level if ad else None, "candidate": candidate_level if cand else None, "distance": distance,
            "reading": None if distance is None else ("match" if distance == 0 else "candidate above" if distance > 0 else "candidate below")}


def fit3(anchored: dict | None, answers: list[dict] | None = None, ad_industries=None, candidate_industries=None, *,
         ad_level: str | None = None, candidate_level: str | None = None) -> dict:
    """The Fit 3 block of one posting. `anchored` = anchor() of the stored reply; `answers` = matcher rows over matcher_requirements();
    `ad_industries` = a set of table domain ids, `candidate_industries` = fit3_industry.Industries (A2.4), for the domain only."""
    anchored = anchored or {"role": {"class": None}, "competencies": [], "dropped": {}}
    units = _units(anchored, answers)
    core, secondary = ([u for u in units if u["ask"] == m] for m in MARKS)
    role_class = anchored["role"].get("class")
    done = sum(1 for u in core if resolved(u))
    confidence = Fraction(done, len(core)) if core else Fraction(0)
    unproved = sum(1 for u in core if u["status"] in ("UNKNOWN", NOT_EVIDENCED))
    reasons = []
    if role_class is None:
        reasons.append("role not available")
    if not core:
        reasons.append("no core competency")
    else:
        if not done:
            reasons.append("no resolved core competency")
        if confidence < MIN_CONFIDENCE:
            reasons.append("low confidence")
        if Fraction(unproved, len(core)) > MAX_UNKNOWN_MUST_RATIO:
            reasons.append("too many core competencies not judged")
    core_cov, sec_cov = _coverage(core), _coverage(secondary)
    counts = {"core": len(core), "secondary": len(secondary), "answered": sum(u["answered"] for u in units), "resolvedCore": done,
              "resolvedSecondary": sum(1 for u in secondary if resolved(u))}
    for status in ("MET", "PARTIAL", "CONTRADICTED", NOT_EVIDENCED, "UNKNOWN"):
        counts[status] = sum(u["status"] == status for u in core)
    cand = candidate_industries or Industries()
    domain, shared = compare_industries(ad_industries, cand)
    return {
        "scoringVersion": SCORING_VERSION,
        "engineVersion": ENGINE_VERSION,
        "promptVersion": PROMPT_VERSION,
        "role": anchored["role"],
        "domain": domain,
        "domainDetail": {"adIndustries": sorted(ad_industries or ()), "sharedIndustries": shared, "candidateIndustryCount": len(cand.confirmed),
                         "candidateComplete": cand.complete, "preferredIndustries": sorted(cand.preferred)},
        "requirements": {"units": units, "coreCounts": counts, "coreCoverage": _text(core_cov), "secondaryCoverage": _text(sec_cov),
                         "coreCoverageV1": _text(_coverage(core, True)), "secondaryCoverageV1": _text(_coverage(secondary, True)),
                         "coverage": None if core_cov is None else float(round(core_cov, 4))},
        "seniority": seniority(ad_level, candidate_level),
        "confidence": float(round(confidence, 4)),
        "insufficientEvidence": bool(reasons),
        "insufficientReasons": reasons,
        "dropped": anchored.get("dropped") or {},
    }


class MixedScoringVersions(ValueError):
    """A rank list held a 3.0 row and something else."""


def order_key(block: dict, variant: str = "v0") -> tuple:
    """The pre-declared ordering rule (A1.4): tier (target and adjacent together, then other), domain (only "different" is worse), core coverage,
    secondary coverage. A coverage with no resolved unit orders as 0. `variant` v1 reads the NOT_EVIDENCED-at-half-weight coverage."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown coverage variant {variant!r}")
    r = block["requirements"]
    suffix = "V1" if variant == "v1" else ""
    core, sec = (Fraction(r[f"{k}Coverage{suffix}"] or 0) for k in ("core", "secondary"))
    return (TIER.get(block["role"].get("class"), len(TIER)), block["domain"] == "different", -core, -sec)


def rank(rows: list[dict], variant: str = "v0") -> dict:
    """Rows (each {"id", "fit3": {...}}) as {"ranked": best first by order_key then id, "insufficient": the Insufficient-evidence ads by id only}: that group is
    never ranked among the others. Refuses a list in which any row is not scoringVersion 3.0."""
    for row in rows:
        block = row.get("fit3")
        if not isinstance(block, dict) or block.get("scoringVersion") != SCORING_VERSION:
            raise MixedScoringVersions(f"row {row.get('id')!r} is not a scoringVersion {SCORING_VERSION} row")
    sufficient = [r for r in rows if not r["fit3"]["insufficientEvidence"]]
    return {"ranked": sorted(sufficient, key=lambda r: (*order_key(r["fit3"], variant), str(r.get("id")))),
            "insufficient": sorted((r for r in rows if r["fit3"]["insufficientEvidence"]), key=lambda r: str(r.get("id")))}


def stored_fit3(job: dict, posting: dict, store: dict | None, roles: dict[str, str], comps: list[dict],
                candidate_industries: Industries | None = None, candidate_level: str | None = None) -> dict | None:
    """The block for a job from the stored entry {"reply": raw, "answers": [rows] | None}, or None when the ad has no stored classification."""
    from .fit3_industry import ad_industries
    entry = (store or {}).get(classification_key(posting, roles, comps))
    if not isinstance(entry, dict) or not isinstance(entry.get("reply"), dict):
        return None
    anchored = anchor(entry["reply"], posting.get("description") or "", roles, comps, posting.get("title") or "")
    facts = job.get("llmFacts") or {}
    return fit3(anchored, entry.get("answers"), ad_industries(posting, facts), candidate_industries, ad_level=facts.get("seniority"),
                candidate_level=candidate_level)
