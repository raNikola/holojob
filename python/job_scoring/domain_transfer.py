"""Domain transferability: experience in a neighbouring industry, credited only with a proof the owner can check.

Two kinds of credit, never mixed up:

* **Proven**: a history entry of the candidate (role and period, from `historyEntries` in the intelligence) is in the ad's own
  domain. That is experience, and it earns the full bonus.
* **Transferable (assumed)**: no entry is in the ad's domain, but an entry in an adjacent domain states a capability (regulatory
  compliance, vendor management, ...) that the ad also asks for, on an edge of `src/data/domainAdjacency.json` that carries a
  `why`. This is an assumption: each bridge adds a smaller bonus and its reason says so.

The bonus lives in the industry dimension and is capped at MAX_BONUS. It is never given to an ad whose title is outside the
candidate's target roles (the 40 cap would hold anyway; the reason says why nothing was added), and never when an avoided
industry matched. Deterministic; no model, no AI call.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from text_utils import normalize_text

ADJACENCY_FILE = Path(__file__).resolve().parents[2] / "src" / "data" / "domainAdjacency.json"
ADJACENCY = json.loads(ADJACENCY_FILE.read_text(encoding="utf-8"))

PROVEN_BONUS = 16
BRIDGE_BONUS = 8
MAX_BONUS = 16

# An ad is in a domain when two different markers of it appear in the text, or one appears in the title.
_MIN_TEXT_MARKERS = 2


def _has(text: str, marker: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text) is not None


def ad_domains(title: str, description: str, company: str = "") -> set[str]:
    title_text, body = normalize_text(f"{title} {company}"), normalize_text(description)
    found = set()
    for domain_id, domain in ADJACENCY["domains"].items():
        markers = domain["markers"]
        in_title = any(_has(title_text, m) for m in markers)
        in_text = sum(1 for m in markers if _has(body, m)) >= _MIN_TEXT_MARKERS
        if in_title or in_text:
            found.add(domain_id)
    return found


def ad_capabilities(title: str, description: str) -> set[str]:
    text = normalize_text(f"{title} {description}")
    return {cid for cid, cap in ADJACENCY["capabilities"].items() if any(_has(text, m) for m in cap["markers"])}


def _edges(a: str, b: str) -> list[dict]:
    return [e for e in ADJACENCY["edges"] if set(e["between"]) == {a, b}]


def _label(domain_id: str) -> str:
    return ADJACENCY["domains"][domain_id]["label"]


def _who(entry: dict) -> str:
    role = (entry.get("role") or "").strip() or "a role"
    period = (entry.get("period") or "").strip()
    return f"your {role} ({period})" if period else f"your {role}"


def _entries(intelligence: dict) -> list[dict]:
    return [e for e in intelligence.get("historyEntries") or [] if isinstance(e, dict)]


def assess(job: dict, intelligence: dict, allowed: bool = True) -> dict:
    """{applied, bonus, proven, bridges, skipped, reasons} for one ad. `allowed` is False for an Unrelated-title ad."""
    domains = ad_domains(job.get("title") or "", job.get("description") or "", job.get("company") or "")
    capabilities = ad_capabilities(job.get("title") or "", job.get("description") or "")
    entries = _entries(intelligence)

    proven = []
    for domain_id in sorted(domains):
        entry = next((e for e in entries if domain_id in (e.get("domains") or [])), None)
        if entry:
            proven.append({"domain": domain_id, "role": entry.get("role") or "", "period": entry.get("period") or ""})
    proven_domains = {p["domain"] for p in proven}

    bridges = []
    seen = set()
    for domain_id in sorted(domains - proven_domains):
        for entry in entries:
            for from_domain in entry.get("domains") or []:
                for edge in _edges(from_domain, domain_id):
                    cap = edge["capability"]
                    key = (from_domain, domain_id, cap)
                    if key in seen or cap not in capabilities or cap not in (entry.get("capabilities") or []):
                        continue
                    seen.add(key)
                    bridges.append({
                        "from": from_domain, "to": domain_id, "capability": cap, "why": edge["why"],
                        "role": entry.get("role") or "", "period": entry.get("period") or "",
                    })

    bonus = PROVEN_BONUS if proven else min(MAX_BONUS, BRIDGE_BONUS * len(bridges))
    result = {"applied": False, "bonus": 0, "proven": proven, "bridges": bridges, "skipped": None, "reasons": []}
    if not (proven or bridges):
        return result
    if not allowed:
        result["skipped"] = "title_unrelated"
        result["reasons"] = ["Industry transfer not applied: the title is outside your target roles"]
        return result

    result["applied"], result["bonus"] = True, bonus
    for index, p in enumerate(proven):
        points = f"+{PROVEN_BONUS}" if index == 0 else "no further points"
        result["reasons"].append(
            f"Proven industry experience ({points}): {_who(p)} is in {_label(p['domain'])}, this ad's industry")
    if not proven:
        for index, b in enumerate(bridges):
            cap = ADJACENCY["capabilities"][b["capability"]]["label"]
            points = f"+{BRIDGE_BONUS}" if (index + 1) * BRIDGE_BONUS <= MAX_BONUS else "no further points, at the cap"
            result["reasons"].append(
                f"Transferable (assumed, {points}): {_who(b)} in {_label(b['from'])} states {cap}, and this ad "
                f"({_label(b['to'])}) asks for it, because {b['why']}. Not proven experience in {_label(b['to'])}")
    return result
