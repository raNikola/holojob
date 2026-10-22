"""Spoken languages from the profile (basicProfile.languages), as the CV prints them.

The profile stores a list of {"language", "proficiency"} entries. The values
mirror LANGUAGE_PROFICIENCIES in src/utils/languages.js; keep the two in step.
"""

from __future__ import annotations

PROFICIENCIES = ("native", "fluent", "advanced", "intermediate", "basic")

# JSON Resume's schema leaves `fluency` as free text (its own examples are
# "Fluent" and "Beginner"), so this maps each profile value to a wording in
# that spirit.
JSON_RESUME_FLUENCY = {
    "native": "Native speaker",
    "fluent": "Fluent",
    "advanced": "Advanced",
    "intermediate": "Intermediate",
    "basic": "Beginner",
}


def normalize_languages(raw) -> list[dict]:
    """A clean list of entries. Missing or malformed input is an empty list, and
    an unknown proficiency is left unstated rather than guessed."""
    if not isinstance(raw, list):
        return []
    entries = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        language = str(item.get("language") or "").strip()
        if not language:
            continue
        proficiency = str(item.get("proficiency") or "").strip().lower()
        entries.append(
            {"language": language, "proficiency": proficiency if proficiency in PROFICIENCIES else ""}
        )
    return entries


def format_language(entry: dict) -> str:
    """'Serbian (native)', or just the name when no proficiency is stated."""
    proficiency = entry.get("proficiency")
    return f"{entry['language']} ({proficiency})" if proficiency else entry["language"]


def languages_text(languages: list[dict]) -> str:
    """The single line the CV prints: 'Serbian (native), English (fluent)'."""
    return ", ".join(format_language(e) for e in languages)
