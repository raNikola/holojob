"""Read a CV with a model, then check every claim against the CV itself.

The model returns facts it copied from the text: the CV's own groupings, roles,
bullets, tools, education. Code decides what survives: an item that cannot be
found in the CV is dropped and reported, so nothing the model made up reaches
the profile. The one exception is the draft career summary, which is the
model's own prose; it is kept only when every number and proper noun in it is
in the CV.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

PROMPT_VERSION = "cv-analysis-2"

_STR = {"type": "string"}
_OPT = {"type": ["string", "null"]}


def _list(item: dict) -> dict:
    return {"type": "array", "items": item}


def _obj(**props) -> dict:
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


CV_SCHEMA = {
    "name": "cv_facts",
    "strict": True,
    "schema": _obj(
        summary=_OPT,
        draft_career_summary=_STR,
        skills=_list(_STR),
        key_projects=_list(_obj(name=_STR, summary=_STR)),
        experience=_list(_obj(title=_STR, company=_STR, start=_OPT, end=_OPT, bullets=_list(_STR))),
        competency_groups=_list(_obj(label=_STR, items=_list(_STR))),
        tool_groups=_list(_obj(label=_STR, items=_list(_STR))),
        education=_list(_obj(degree=_STR, school=_STR, year=_OPT)),
        certifications=_list(_obj(name=_STR, issuer=_OPT, year=_OPT)),
    ),
}

PROMPT = """You read one CV and report what it says. You do not judge the candidate.

The text below has had the candidate's name, e-mail, phone and links replaced with
[NAME], [EMAIL], [PHONE] and [LINK]. It may be flattened onto one line; section
headings are usually in capitals.

Rules, all of them strict:
- Copy wording exactly as it appears in the CV. Never paraphrase, translate, shorten or add.
  Every string you return except draft_career_summary must be a passage of the CV.
- Never invent an employer, title, date, metric, degree, tool or skill. If the CV does not
  say it, leave it out. An empty list is a correct answer.
- summary: the CV's own professional summary, verbatim, or null if it has none.
- skills: the concrete technical skills the CV names anywhere: programming languages,
  frameworks, platforms, tools, protocols and delivery methods (for example "PHP", "Laravel",
  "Scrum", "Jira"), one per entry, as written. Leave out leadership, management and other
  soft competencies (they belong to competency_groups), phrases, and anything repeated.
  At most 40, the most clearly stated first.
- key_projects: the distinct projects or products the experience describes. One entry per
  project, never the same project twice. name is the project or product name as written
  (with its company if that is how the CV writes it); summary is one sentence copied from the CV.
- experience: every role, newest first as the CV lists them. title and company as written;
  start and end as written ("Apr 2024", "Present") or null; bullets are the CV's own
  bullet or sentence text for that role, one per entry.
- competency_groups: if the CV has a competencies / skills section split into labeled groups,
  return each group with the CV's own label and its items. Do not regroup or invent groups.
  If there is no such grouping, return an empty list.
- tool_groups: the same for a tools section: the CV's own group labels and the tools in each.
- education: degree, school, year as written. certifications: name, issuer, year as written.
- draft_career_summary: write 3 to 5 sentences in the first person that the candidate could
  use as a career summary, using only facts, numbers and names found in this CV.
  This is the only field you may word yourself.

CV:
\"\"\"
{cv}
\"\"\"
"""


def build_prompt(redacted_cv: str) -> str:
    return PROMPT.replace("{cv}", redacted_cv)


def fingerprint(redacted_cv: str, provider: str, model: str | None) -> str:
    raw = f"{PROMPT_VERSION}\0{provider}\0{model or ''}\0{redacted_cv}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


# --- the guard -------------------------------------------------------------

_FOLD_MAP = str.maketrans({"đ": "d", "Đ": "D", "ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "ß": "ss"})


def normalize(text: str) -> str:
    """Lower-case, accent-folded words only: the form items are compared in."""
    decomposed = unicodedata.normalize("NFKD", (text or "").translate(_FOLD_MAP))
    folded = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    # "250+" and "250" are the same figure; "c++" and "c#" keep their symbols.
    return " ".join(re.sub(r"^(\d+)\+$", r"\1", t) for t in re.findall(r"[a-z0-9+#]+", folded))


def _dicts(value) -> list[dict]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


class _Source:
    def __init__(self, text: str):
        self.norm = f" {normalize(text)} "
        self.words = set(self.norm.split())

    def has_name(self, value) -> bool:
        """A name the model may have joined from nearby parts ("Company — Product")."""
        if self.has(value):
            return True
        parts = [p for p in re.split(r"\s+[—–-]\s+|:\s+|\s*[()]\s*", value if isinstance(value, str) else "") if p.strip()]
        return len(parts) > 1 and all(self.has(p) for p in parts)

    def has(self, value) -> bool:
        needle = normalize(value if isinstance(value, str) else "")
        return bool(needle) and f" {needle} " in self.norm


def _strings(values, source: _Source, field: str, rejected: list) -> list[str]:
    kept: list[str] = []
    seen: set[str] = set()
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        key = normalize(value)
        if key in seen:
            continue
        if source.has(value):
            seen.add(key)
            kept.append(value)
        else:
            rejected.append({"field": field, "value": value, "reason": "not found in the CV"})
    return kept


def _optional(value, source: _Source, field: str, rejected: list):
    if not isinstance(value, str) or not value.strip():
        return None
    if source.has(value):
        return value.strip()
    rejected.append({"field": field, "value": value, "reason": "not found in the CV"})
    return None


def _groups(raw, source: _Source, field: str, rejected: list) -> list[dict]:
    groups = []
    for group in _dicts(raw):
        label = group.get("label")
        if not isinstance(label, str) or not source.has(label):
            rejected.append({"field": f"{field}.label", "value": str(label), "reason": "group label not found in the CV"})
            continue
        items = _strings(group.get("items"), source, f"{field}.items", rejected)
        if items:
            groups.append({"label": label.strip(), "items": items})
    return groups


_NUMBER_RE = re.compile(r"(?<![\w])\d[\d,.]*")


def _draft_problems(draft: str, source: _Source) -> list[str]:
    """Numbers and mid-sentence capitalised words in the draft that the CV lacks."""
    problems = []
    for number in (n.rstrip(".,") for n in _NUMBER_RE.findall(draft)):
        if not source.has(number):
            problems.append(number)
    for sentence in re.split(r"(?<=[.!?])\s+", draft):
        for word in re.findall(r"\b[A-Z][\w+#&-]*", sentence)[1:] if sentence else []:
            if word != "I" and normalize(word) and normalize(word) not in source.words:
                problems.append(word)
    return problems


def verify(raw: dict, cv_text: str) -> tuple[dict, list[dict]]:
    """(the facts that are really in the CV, what was dropped and why)."""
    source = _Source(cv_text)
    rejected: list[dict] = []
    raw = raw if isinstance(raw, dict) else {}

    experience = []
    for role in _dicts(raw.get("experience")):
        title, company = role.get("title"), role.get("company")
        if not (isinstance(title, str) and source.has(title) and isinstance(company, str) and source.has(company)):
            rejected.append({"field": "experience", "value": f"{title} — {company}", "reason": "title or company not found in the CV"})
            continue
        experience.append({
            "title": title.strip(),
            "company": company.strip(),
            "start": _optional(role.get("start"), source, "experience.start", rejected),
            "end": _optional(role.get("end"), source, "experience.end", rejected),
            "bullets": _strings(role.get("bullets"), source, "experience.bullets", rejected),
        })

    projects, seen_projects = [], set()
    for project in _dicts(raw.get("key_projects")):
        name, summary = project.get("name"), project.get("summary")
        key = normalize(summary if isinstance(summary, str) else "")
        if not (isinstance(name, str) and source.has_name(name) and isinstance(summary, str) and source.has(summary)):
            rejected.append({"field": "keyProjects", "value": f"{name} — {summary}", "reason": "name or summary not found in the CV"})
        elif key not in seen_projects:
            seen_projects.add(key)
            projects.append({"name": name.strip(), "summary": summary.strip()})

    education = []
    for entry in _dicts(raw.get("education")):
        if isinstance(entry.get("degree"), str) and source.has(entry["degree"]) and isinstance(entry.get("school"), str) and source.has(entry["school"]):
            education.append({
                "degree": entry["degree"].strip(),
                "school": entry["school"].strip(),
                "year": _optional(entry.get("year"), source, "education.year", rejected),
            })
        else:
            rejected.append({"field": "education", "value": f"{entry.get('degree')} — {entry.get('school')}", "reason": "degree or school not found in the CV"})

    certifications = []
    for entry in _dicts(raw.get("certifications")):
        if isinstance(entry.get("name"), str) and source.has(entry["name"]):
            certifications.append({
                "name": entry["name"].strip(),
                "issuer": _optional(entry.get("issuer"), source, "certifications.issuer", rejected),
                "year": _optional(entry.get("year"), source, "certifications.year", rejected),
            })
        else:
            rejected.append({"field": "certifications", "value": str(entry.get("name")), "reason": "not found in the CV"})

    draft = raw.get("draft_career_summary")
    draft = draft.strip() if isinstance(draft, str) else ""
    if draft:
        problems = _draft_problems(draft, source)
        if problems:
            rejected.append({
                "field": "draftCareerSummary",
                "value": draft,
                "reason": f"names or numbers not in the CV: {', '.join(sorted(set(problems))[:8])}",
            })
            draft = ""

    facts = {
        "summary": _optional(raw.get("summary"), source, "summary", rejected),
        "draftCareerSummary": draft,
        "skills": _strings(raw.get("skills"), source, "skills", rejected),
        "keyProjects": projects,
        "experience": experience,
        "competencyGroups": _groups(raw.get("competency_groups"), source, "competencyGroups", rejected),
        "toolGroups": _groups(raw.get("tool_groups"), source, "toolGroups", rejected),
        "education": education,
        "certifications": certifications,
    }
    return facts, rejected
