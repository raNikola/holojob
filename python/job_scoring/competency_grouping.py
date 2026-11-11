"""AI batch grouping of requirement texts (competency memory MVP spec, 4.2). A manual command only.

The model answers per text: same_as an id of the family list, a group label, or none, with a confidence. It holds
no threshold. Code decides: high + compatible kind + id on the list -> auto; a high group of new texts -> a
deterministic provisional group id, members auto, reported as a product.json candidate (never written there);
anything else -> pending. A demoted text-id pair is never linked again; the same text may link to another id.

The prompt holds ad requirement texts and the family's competency list only: nothing about the candidate.

    python python/job_scoring/competency_grouping.py             # dry run: counts and an estimate, sends nothing
    python python/job_scoring/competency_grouping.py --confirm   # sends, up to --max-usd (default 0.10)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("llm", "job_scoring"):
    if str(ROOT / "python" / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / "python" / _sub))
if str(ROOT / "python") not in sys.path:
    sys.path.append(str(ROOT / "python"))

from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic  # noqa: E402
import competency_mapping as cm  # noqa: E402
from match_engine import competencies  # noqa: E402
import row_state  # noqa: E402

FEATURE = "competency-grouping"
PROMPT_VERSION = "g1"
BATCH_SIZE = 150  # A6
MAX_USD = 0.10  # A6
CACHE_PATH = ROOT / "data" / "cache" / "competency-grouping.json"
JOBS_PATH = ROOT / "data" / "jobs" / "discovered_jobs.json"
UPPER_CHARS_PER_TOKEN = 3.0  # over-counts on purpose
OUTPUT_TOKENS_PER_TEXT = 60  # worst case of one answer: index, "group: <short label>", confidence

PROMPT = """You group job-ad requirement texts. Ad text only; nothing here is about any person.

Below are numbered requirement texts (REQUIREMENTS) and a fixed list of competencies (COMPETENCIES: id, kind, definition).
For each text answer one of:
- "same_as: <id>": the text names the same thing as that competency, worded differently. The id must be on the list.
- "group: <label>": no listed competency fits, but at least one other text in this batch names the same thing. Use the
  same short label (at most 6 words) for every text of that group.
- "none": neither.
"Equivalent" is strict: the same thing worded differently. Not broader, not narrower, not related. Ignore the level
(years, seniority). "Writing acceptance criteria" and "Defining acceptance criteria" are one thing; "A/B testing" and
"Statistical experiment design" are two. Be conservative: when unsure, answer "none" or confidence "uncertain".
Give confidence "high" or "uncertain" per text.

=== COMPETENCIES ===
{competencies}
=== REQUIREMENTS ===
{texts}
=== END ===

Answer with one JSON object: {{"answers": [{{"n": <number>, "answer": "same_as: <id>" | "group: <label>" | "none", "confidence": "high" | "uncertain"}}]}}
"""

SCHEMA = {"name": "competency_grouping", "strict": True, "schema": {"type": "object", "additionalProperties": False, "required": ["answers"], "properties": {
    "answers": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["n", "answer", "confidence"], "properties": {
        "n": {"type": "integer"}, "answer": {"type": "string"}, "confidence": {"type": "string"}}}}}}}


def build_prompt(comps: list[dict], texts: list[str]) -> str:
    return PROMPT.format(competencies=cm.list_rows(comps), texts="\n".join(f"{i}. {t}" for i, t in enumerate(texts)))


def _key(text: str) -> str:
    return competencies.alias_key(text)


def _cache_key(text: str) -> str:
    return f"{PROMPT_VERSION}|{_key(text)}"


def load_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_cache(cache: dict, path: Path) -> None:
    make_private_dirs(path.parent)
    write_text_atomic(path, json.dumps(cache, indent=1, ensure_ascii=False, sort_keys=True), PRIVATE_FILE_MODE)


def pool_texts(jobs: list[dict], mapper: cm.Mapper, cache: dict) -> list[dict]:
    """Requirements of open ads still `prov:` or behind a pending link, not cached; one per normalized text."""
    out: dict[str, dict] = {}
    for job in jobs:
        if job.get("isClosed") or row_state.not_found(job):
            continue
        for r in (job.get("llmFacts") or {}).get("requirements") or []:
            text, key = r.get("text"), _key(r.get("text"))
            if not text or key in out or _cache_key(text) in cache:
                continue
            status = (mapper.learned.get(key) or {}).get("status")
            if (status not in (None, cm.PENDING, cm.DEMOTED)) or key in mapper.seed:
                continue
            if str(r.get("id", "")).startswith("prov:") or status in (cm.PENDING, cm.DEMOTED):
                out[key] = {"text": text, "kind": r.get("kind")}
    return list(out.values())


def batches(items: list, size: int = BATCH_SIZE) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def parse_answers(response: dict | None, count: int) -> dict[int, tuple[str, str | None, bool]]:
    """n -> (kind, value, high): kind is same_as, group or none. Unreadable entries are left out (they stay pending)."""
    out: dict[int, tuple[str, str | None, bool]] = {}
    for a in (response or {}).get("answers") or []:
        if not isinstance(a, dict) or not isinstance(a.get("n"), int) or not 0 <= a["n"] < count:
            continue
        answer = str(a.get("answer") or "").strip()
        head, _, value = answer.partition(":")
        head, value = head.strip().lower(), value.strip()
        high = str(a.get("confidence") or "").strip().lower() == "high"
        if head in ("same_as", "group") and value:
            out[a["n"]] = (head, value, high)
        elif answer.lower() in cm.NONE_ANSWERS:
            out[a["n"]] = ("none", None, high)
    return out


def group_id(label: str) -> str:
    return cm.GROUP_PREFIX + hashlib.sha256(_key(label).encode("utf-8")).hexdigest()[:10]


def decide(items: list[dict], answers: dict, by_id: dict) -> tuple[dict[int, dict], dict[str, list[int]]]:
    """n -> outcome {status, competencyId, group?}. Also group label -> member numbers, for groups of at least two."""
    members: dict[str, list[int]] = {}
    for n, (kind, value, high) in answers.items():
        if kind == "group" and high:
            members.setdefault(_key(value), []).append(n)
    outcomes: dict[int, dict] = {}
    for n, item in enumerate(items):
        kind, value, high = answers.get(n, ("none", None, False))
        outcome = {"status": cm.PENDING, "competencyId": None}
        if kind == "same_as" and high:
            comp = by_id.get(value)
            if comp and cm.kinds_compatible(item.get("kind"), comp["kind"]):
                outcome = {"status": cm.AUTO, "competencyId": value}
        elif kind == "group" and high and len(members[_key(value)]) >= 2:
            outcome = {"status": cm.AUTO, "competencyId": group_id(value), "group": _key(value)}
        outcomes[n] = outcome
    return outcomes, {k: v for k, v in members.items() if len(v) >= 2}


class SpendGuard:
    """Refuses a call whose true worst case, on top of the worst case of the calls already made, could pass the cap."""

    def __init__(self, cap: float, price: dict):
        self.cap, self.price, self.spent, self.calls = cap, price, 0.0, 0

    def worst(self, prompt: str, texts: int) -> float:
        tokens_in = len(prompt) / UPPER_CHARS_PER_TOKEN
        return (tokens_in * self.price["in"] + (texts * OUTPUT_TOKENS_PER_TEXT + 100) * self.price["out"]) / 1e6

    def allows(self, prompt: str, texts: int) -> bool:
        return self.spent + self.worst(prompt, texts) <= self.cap

    def reserve(self, prompt: str, texts: int) -> None:
        self.spent += self.worst(prompt, texts)
        self.calls += 1


def run(jobs: list[dict], mapper: cm.Mapper, cache_path: Path, *, complete, price: dict | None, max_usd: float = MAX_USD,
        confirm: bool = False) -> dict:
    """Group the pool. `complete(prompt) -> dict | None` is the gated model call. Counts only in the result."""
    cache = load_cache(cache_path)
    items = pool_texts(jobs, mapper, cache)
    result = {"texts": len(items), "batches": len(batches(items)), "sent": 0, "auto": 0, "pending": 0, "groups": 0,
              "stopped": None, "groupCandidates": []}
    if not confirm:
        return result
    if not price:
        result["stopped"] = "no price for this model; nothing sent"
        return result
    guard = SpendGuard(max_usd, price)
    for batch in batches(items):
        prompt = build_prompt(mapper.comps, [i["text"] for i in batch])
        if not guard.allows(prompt, len(batch)):
            result["stopped"] = f"the next call could pass the ${max_usd:.2f} cap"
            break
        guard.reserve(prompt, len(batch))
        try:
            response = complete(prompt)
        except Exception as exc:  # a refusal or a provider failure ends the run; what was done is kept
            result["stopped"] = type(exc).__name__
            break
        result["sent"] += len(batch)
        outcomes, groups = decide(batch, parse_answers(response, len(batch)), mapper.by_id)
        result["groups"] += len(groups)
        result["groupCandidates"] += [group_id(label) for label in groups]
        for n, item in enumerate(batch):
            out = outcomes[n]
            cache[_cache_key(item["text"])] = out
            result[out["status"]] += 1
            if out["competencyId"]:
                mapper.link(item["text"], out["competencyId"], out["status"])
        save_cache(cache, cache_path)
        mapper.save()
    return result


def link_confirm_texts(covered_texts: list[str] | None, group_texts: list[str]) -> list[str]:
    """Texts linked to a group that the owner's answer did not cover: each needs a one-click link_confirm (A3)."""
    covered = {_key(t) for t in covered_texts or []}
    return [t for t in group_texts if _key(t) not in covered]


def _price(provider: str | None, model: str | None) -> dict | None:
    import ai_gate
    import ai_selection
    from llm_client import service_tier_for
    selection = ai_selection.require()
    provider, model = provider or selection["provider"], model or selection["model"]
    p = ai_gate.classify(provider, model, selection.get("baseUrl") or None, tier=service_tier_for(provider))
    if not p.get("priceKnown"):
        return None
    return {"in": p["inputPerMTok"], "out": p["outputPerMTok"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--confirm", action="store_true", help="send to the model (default: dry run)")
    ap.add_argument("--max-usd", type=float, default=MAX_USD)
    ap.add_argument("--provider")
    ap.add_argument("--model")
    ap.add_argument("--jobs", type=Path, default=JOBS_PATH)
    args = ap.parse_args(argv)

    import ai_gate
    from llm_client import complete_json, preflight
    import enrich_jobs

    family = enrich_jobs._role_family(enrich_jobs.INTELLIGENCE_PATH)
    mapper = cm.load_mapper(family)
    if mapper is None:
        print("no usable competency list for the role family; nothing to do")
        return 1
    os.environ[ai_gate.TRIGGER_ENV] = ai_gate.MANUAL
    jobs = json.loads(args.jobs.read_text(encoding="utf-8"))
    jobs = jobs if isinstance(jobs, list) else jobs.get("jobs", [])

    def complete(prompt: str):
        with ai_gate.context(feature=FEATURE):
            decision = preflight(len(prompt), args.provider, args.model)
            if not decision.allowed:
                ai_gate.record_refused(decision)
                raise RuntimeError("refused by the budget gate: " + decision.reason)
            return complete_json(prompt, schema=SCHEMA, model=args.model, provider=args.provider)

    price = None
    try:
        price = _price(args.provider, args.model)
    except Exception as exc:
        print(f"price unknown ({type(exc).__name__})")
    result = run(jobs, mapper, CACHE_PATH, complete=complete, price=price, max_usd=args.max_usd, confirm=args.confirm)
    if not args.confirm:
        print(f"dry run, nothing sent: {result['texts']} texts in {result['batches']} batches (up to {BATCH_SIZE} each)")
        if price:
            guard = SpendGuard(args.max_usd, price)
            est = sum(guard.worst(build_prompt(mapper.comps, [i["text"] for i in b]), len(b))
                      for b in batches(pool_texts(jobs, mapper, load_cache(CACHE_PATH))))
            print(f"estimated worst-case cost ${est:.4f}; cap ${args.max_usd:.2f}")
        print("add --confirm to send")
        return 0
    print({k: v for k, v in result.items() if k != "groupCandidates"}, f"product.json candidates: {len(result['groupCandidates'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
