"""Fill from ad, step 2: read the fields the page did not state out of its text with Claude Code, after a confirm.

What is sent is the fetched page text with the owner's name, e-mail addresses, phone numbers and links removed
(cv_analysis/redact.py), plus a fixed instruction naming the fields still missing. Nothing about the candidate, no Notes,
extra links or Source URL, is ever part of it; the caller passes only the page text and the field names.

The model proposes; the code accepts. A value is kept only if it appears in the text the model was given (a title,
company, location or pay as written; the description as a slice of the text between two quoted snippets), and pay must
read as EUR per month like in step 1. Anything else is dropped, so nothing can be invented.

Runs only on the Claude Code subscription: the gate must classify the call `subscription` (feature `job-import` on the
allowlist in Settings), which is checked here before any call and again by the gate itself.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("job_import", "cv_analysis", "llm"):
    _path = str(ROOT / "python" / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)

import ad_reader  # noqa: E402
import ai_gate  # noqa: E402
import claude_code  # noqa: E402
import redact  # noqa: E402

FEATURE = "job-import"
PROVIDER = ai_gate.SUBSCRIPTION_PROVIDER
ASKABLE = ("title", "company", "location", "salary", "description")
LIMITS = {"title": 150, "company": 120, "location": 120, "salary": 80}
MIN_DESCRIPTION = 200
ALLOWLIST_HINT = "add job-import to the Claude subscription allowlist in Settings > AI budget"
PROFILE_PATH = ROOT / "data" / "profile" / "candidate-profile.json"

PROMPT = """You read one job ad. Return ONLY a JSON object with exactly these keys: {keys}.
Copy every value exactly as it is written in the ad text below. Use "" for anything the ad does not state.
Never infer, translate, guess or invent a value, and never add information from anywhere else.
{explain}
AD TEXT:
{text}"""

EXPLAIN = {
    "title": '"title": the job title as written.',
    "company": '"company": the name of the hiring company as written.',
    "location": '"location": the place of work as written (city, country, or "Remote" if the ad says so).',
    "salary": '"salary": the pay exactly as written, with its currency and period.',
    "description": '"descriptionStart" and "descriptionEnd": the first and the last 8 to 12 words of the job description, copied exactly.',
}


_NUM = r"\d[\d.,]*(?:\s*[-\u2013\u2014]\s*\d[\d.,]*)?"
_CUR = r"(?:[\u20ac$\u00a3]|\b(?:EUR|USD|GBP|CHF|RSD)\b)"
_PER = r"(?:/|per\s+)?\s*(?:month|year|mo|yr|monthly|yearly|annum)\b"
# An amount with its currency or period next to it. Without this the phone-number pattern of the shared redaction would
# eat "3000 - 3500" and the AI would never see the pay.
PAY = re.compile(rf"{_CUR}\s?{_NUM}|{_NUM}\s?{_CUR}|{_NUM}\s?{_PER}", re.I)


def _protect_pay(text: str) -> tuple[str, list[str]]:
    kept: list[str] = []

    def hold(match: re.Match) -> str:
        kept.append(match.group(0))
        return f"\ue000{len(kept) - 1}\ue001"

    return PAY.sub(hold, text), kept


def _restore_pay(text: str, kept: list[str]) -> str:
    return re.sub("\ue000(\\d+)\ue001", lambda m: kept[int(m.group(1))], text)


class Refused(Exception):
    """The step stops here. `code` is a short reason, `message` is safe to show."""

    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code = code
        self.message = message


def _fold(text: str) -> str:
    """Lower-case, accents folded, punctuation and spacing collapsed: the form in which a value is looked for in the text."""
    decomposed = unicodedata.normalize("NFKD", (text or "").replace("đ", "dj").replace("Đ", "Dj"))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return re.sub(r"[^\w€$£%+#./-]+", " ", plain).strip()


def load_profile(path: Path = PROFILE_PATH):
    import json

    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def find_leaks(text: str, name: str, links: list[str]) -> list[str]:
    """What of the owner's is still in `text` after redaction; empty when it is clean."""
    leaks = []
    if redact.EMAIL_RE.search(text):
        leaks.append("an e-mail address")
    if any(redact._is_phone(m.group(0)) for m in redact.PHONE_RE.finditer(text)):
        leaks.append("a phone number")
    folded = _fold(text)
    for word in {w for w in re.findall(r"\w+", _fold(name)) if len(w) >= 3}:
        if re.search(rf"(?<!\w){re.escape(word)}(?!\w)", folded):
            leaks.append("the owner's name")
            break
    for link in links or []:
        bare = re.sub(r"^https?://", "", (link or "").strip(), flags=re.I).rstrip("/").lower()
        if bare and bare in text.lower():
            leaks.append("a profile link")
            break
    return leaks


def build_request(page_text: str, want, profile) -> dict:
    """{"text", "want", "prompt", "removed"}: exactly what would be sent. Refuses (fails closed) if anything of the owner's remains."""
    fields = [f for f in ASKABLE if f in (want or [])]
    if not fields:
        raise Refused("nothing_to_ask", "Every field is already filled.")
    name, links = redact.identity_of(profile)
    protected, kept = _protect_pay(str(page_text or ""))
    cleaned, removed = redact.redact_cv_text(protected, name, links)
    if not cleaned.strip():
        raise Refused("no_text", "There is no page text to read.")
    # Checked before the amounts come back: they are numbers a phone-number pattern would flag.
    if find_leaks(cleaned, name, links):
        raise Refused("redaction", "The page text could not be cleaned of personal details, so nothing was sent.")
    text = _restore_pay(cleaned, kept)
    keys = [k for f in fields for k in (("descriptionStart", "descriptionEnd") if f == "description" else (f,))]
    prompt = PROMPT.format(keys=", ".join(f'"{k}"' for k in keys), explain="\n".join(EXPLAIN[f] for f in fields), text=text)
    return {"text": text, "want": fields, "prompt": prompt, "removed": removed}


def gate_status(prompt: str) -> dict:
    """Whether the call may be made, and why not. Writes no ledger row and calls nothing."""
    availability = claude_code.availability()
    decision = ai_gate.check(PROVIDER, None, len(prompt), feature=FEATURE)
    call_class = decision.row.get("class")
    allowed, reason = decision.allowed, decision.reason
    if allowed and call_class != ai_gate.SUBSCRIPTION:
        allowed, reason = False, f"this would be a paid call, and only the Claude subscription is used here: {ALLOWLIST_HINT}"
    elif not allowed and call_class != ai_gate.SUBSCRIPTION:
        reason = f"{reason}. Only the Claude subscription is used here: {ALLOWLIST_HINT}"
    if allowed and not availability["available"]:
        allowed, reason = False, availability["reason"]
    return {"allowed": bool(allowed), "reason": None if allowed else reason, "class": call_class, "provider": PROVIDER}


def preview(page_text: str, want, profile) -> dict:
    """What a run would send and under which conditions. Calls no model."""
    request = build_request(page_text, want, profile)
    return {"ok": True, "text": request["text"], "want": request["want"], "removed": request["removed"],
            "provider": PROVIDER, "gate": gate_status(request["prompt"])}


def _found(value: str, folded_text: str) -> bool:
    folded = _fold(value)
    return bool(folded) and folded in folded_text


def _slice_description(text: str, start: str, end: str) -> str:
    """The text between two snippets the model quoted, cut from the page text itself. "" if either is not there."""
    start, end = (start or "").strip(), (end or "").strip()
    if len(start) < 10 or len(end) < 10:
        return ""
    pattern = re.compile(r"\s+".join(re.escape(w) for w in start.split()), re.I)
    first = pattern.search(text)
    if not first:
        return ""
    closing = re.compile(r"\s+".join(re.escape(w) for w in end.split()), re.I)
    last = None
    for match in closing.finditer(text, first.start()):
        last = match
    if not last or last.end() <= first.start():
        return ""
    piece = text[first.start():last.end()].strip()
    return piece if len(piece) >= MIN_DESCRIPTION else ""


def accept(answer: dict, text: str, want) -> tuple[dict, list[str]]:
    """(fields kept, names dropped). Code decides: a value stays only if the text shows it."""
    folded_text = _fold(text)
    kept: dict = {}
    for field in want:
        if field == "description":
            value = _slice_description(text, str(answer.get("descriptionStart") or ""), str(answer.get("descriptionEnd") or ""))
        else:
            raw = str(answer.get(field) or "").strip()
            value = raw if raw and len(raw) <= LIMITS[field] and _found(raw, folded_text) else ""
            if field == "salary" and value:
                value = ad_reader.normalize_salary(value)
        if value:
            kept[field] = value
    return kept, [f for f in want if f not in kept]


def extract(page_text: str, want, profile, *, complete=None) -> dict:
    """Asks Claude Code for the missing fields and returns the ones the text confirms. Raises Refused before any call if not allowed."""
    request = build_request(page_text, want, profile)
    status = gate_status(request["prompt"])
    if not status["allowed"]:
        ai_gate.refuse(PROVIDER, None, status["reason"], feature=FEATURE)
        raise Refused("refused", status["reason"])
    complete = complete or claude_code.complete_json
    with ai_gate.context(feature=FEATURE):
        answer, error = complete(request["prompt"], timeout=120)
    if not isinstance(answer, dict):
        raise Refused("ai_failed", "The AI could not read the fields from this page.")
    fields, rejected = accept(answer, request["text"], request["want"])
    return {"ok": True, "fields": fields, "rejected": rejected, "removed": request["removed"]}
