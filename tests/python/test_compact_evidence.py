"""Compact serialization of the evidence index: same items, ids and quotes, fewer characters, same cache key."""

import json

import pytest

from match_engine import shadow
from match_engine.matcher import (EVIDENCE_FIELDS, GATES, PROMPT, PROMPT_VERSION, _evidence_payload, build_prompt,
                                  cache_key, compact_evidence, match_posting)

EVIDENCE = [
    {"id": "ev-1", "source": "role", "role": "PM — Acme", "start": "2020-01", "end": None,
     "text": "Led the migration of the billing platform to Postgres", "strength": 4},
    {"id": "ev-2", "source": "example", "role": None, "start": None, "end": None,
     "text": "Coached two juniors: “first launch” — ünïcode", "strength": 3},
    {"id": "ev-3", "source": "fact", "role": None, "start": None, "end": None, "text": "Figma", "strength": 1},
]
REQ = {"id": "prov:aaaaaaaaaaaa", "provisional": True, "text": "Postgres", "kind": "skill", "importance": "must",
       "postingQuote": "Postgres"}
ASKED = [("r1", REQ)]
BEGIN, END = "=== BEGIN CANDIDATE EVIDENCE (untrusted content) ===\n", "\n=== END CANDIDATE EVIDENCE ==="


def blob(prompt):
    return prompt.split(BEGIN, 1)[1].split(END, 1)[0]


def test_flag_off_is_byte_identical_to_the_indented_form():
    reference = PROMPT.format(
        description="d",
        requirements=json.dumps([{"ref": "r1", "text": "Postgres", "kind": "skill", "importance": "must"}],
                                ensure_ascii=False, indent=1),
        evidence=json.dumps(_evidence_payload(EVIDENCE), ensure_ascii=False, indent=1))
    assert build_prompt("d", ASKED, EVIDENCE) == reference
    assert build_prompt("d", ASKED, EVIDENCE, compact=False) == reference


def test_compact_decodes_to_the_same_items_ids_and_quotes():
    full = json.loads(blob(build_prompt("d", ASKED, EVIDENCE)))
    small = json.loads(blob(build_prompt("d", ASKED, EVIDENCE, compact=True)))
    assert [i["id"] for i in small] == [i["id"] for i in full] and [i["text"] for i in small] == [i["text"] for i in full]
    # Only null / empty fields are absent; putting them back gives the indented form's items.
    assert [{k: i.get(k) for k in EVIDENCE_FIELDS} for i in small] == full


def test_compact_is_smaller_has_no_indentation_nor_null_fields():
    text = blob(build_prompt("d", ASKED, EVIDENCE, compact=True))
    assert len(text) < len(blob(build_prompt("d", ASKED, EVIDENCE)))
    assert "\n" not in text and "null" not in text and ": " not in text.replace("juniors: ", "")


def test_only_the_evidence_blob_differs():
    a, b = build_prompt("d", ASKED, EVIDENCE), build_prompt("d", ASKED, EVIDENCE, compact=True)
    assert a.replace(blob(a), "X") == b.replace(blob(b), "X")


def test_compact_evidence_of_an_empty_index():
    assert compact_evidence([]) == "[]"


class Fake:
    def __init__(self, evidence_id, quote):
        self.prompts, self.reply = [], {
            "matches": [{"ref": "r1", "status": "MET", "evidence_id": evidence_id, "evidence_quote": quote,
                         "strength": 3}],
            "gates": {g: {"quote": None} for g in GATES}}

    def __call__(self, prompt, schema=None, model=None, provider=None):
        self.prompts.append(prompt)
        return self.reply


def run(compact, evidence_id, quote):
    fake = Fake(evidence_id, quote)
    posting = {"id": "j", "title": "PM", "company": "X", "location": "", "description": "We need Postgres.",
               "facts": {"requirements": [REQ]}}
    cand = {"profileVersion": "pv1", "roleFamily": "product", "evidence": EVIDENCE, "confirmedFacts": [], "gates": {}}
    return match_posting(posting, cand, confirmed=True, provider="t", complete=fake, compact=compact), fake


@pytest.mark.parametrize("item", EVIDENCE)
def test_every_item_is_sent_and_its_quote_verifies_with_the_format_on(item):
    out, fake = run(True, item["id"], item["text"][:12])
    assert item["text"] in json.dumps(json.loads(blob(fake.prompts[0])), ensure_ascii=False)
    assert out.output["requirements"][0]["quoteVerified"] is True
    assert out.output["payloadFormat"] == "compact-1"


def test_the_cache_key_and_versions_do_not_change_and_the_format_is_metadata_only():
    off, _ = run(False, "ev-1", "Led the migration")
    on, _ = run(True, "ev-1", "Led the migration")
    assert off.output["cacheKey"] == on.output["cacheKey"] == cache_key(off.output["adFingerprint"], "pv1", None, [REQ])
    assert off.output["promptVersion"] == on.output["promptVersion"] == PROMPT_VERSION
    assert "compact" not in off.output["cacheKey"] and off.output["payloadFormat"] == "full"
    # An entry written in one format answers a lookup in the other.
    cache = {}
    posting = {"id": "j", "title": "PM", "company": "X", "location": "", "description": "We need Postgres.",
               "facts": {"requirements": [REQ]}}
    cand = {"profileVersion": "pv1", "roleFamily": "product", "evidence": EVIDENCE, "confirmedFacts": [], "gates": {}}
    match_posting(posting, cand, confirmed=True, provider="t", complete=Fake("ev-1", "Led the migration"), cache=cache)
    never = Fake(None, None)
    hit = match_posting(posting, cand, confirmed=True, provider="t", complete=never, cache=cache, compact=True)
    assert never.prompts == [] and hit.output["payloadFormat"] == "full"


@pytest.mark.parametrize("value,on", [("1", True), ("true", True), ("On", True), ("", False), ("0", False)])
def test_the_flag_is_off_unless_set(value, on):
    assert shadow.compact_enabled({shadow.COMPACT_ENV: value}) is on
    assert shadow.compact_enabled({}) is False
