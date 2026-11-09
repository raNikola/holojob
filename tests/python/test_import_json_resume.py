"""Wave 7 S3: a JSON Resume file as an import draft."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from profile_import.json_resume import parse_json_resume
from profile_import.text_parser import TextImportError

ROOT = Path(__file__).resolve().parents[2]
TODAY = date(2026, 11, 9)

SAMPLE = {
    "$schema": "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json",
    "basics": {
        "name": "Jane Sample", "label": "Technical Product Leader", "email": "jane@example.invalid", "phone": "+1 555 010 0100",
        "url": "https://example.invalid/jane", "summary": "Product leader. Write to jane@example.invalid.",
        "location": {"city": "Springfield", "region": "IL", "countryCode": "US"},
        "profiles": [{"network": "LinkedIn", "username": "jane", "url": "https://linkedin.com/in/jane-sample"}],
    },
    "work": [
        {"name": "Northwind", "position": "Head of Product", "startDate": "2024-04", "summary": "Own the portfolio.", "highlights": ["Grew ARR by 40%.", "Cut churn."]},
        {"name": "Beta Corp", "position": "Analyst", "startDate": "2016-01-15", "endDate": "2019-12", "highlights": ["Built weekly reports."]},
    ],
    "education": [{"institution": "University of Springfield", "area": "Economics", "studyType": "BSc", "startDate": "2008", "endDate": "2012"}],
    "certificates": [{"name": "CSPO", "issuer": "Scrum Alliance", "date": "2019-03-01"}],
    "skills": [{"name": "Product", "keywords": ["Roadmapping", "Discovery"]}, {"name": "Data", "keywords": ["SQL", "roadmapping"]}],
    "languages": [{"language": "English", "fluency": "Native speaker"}, {"language": "German", "fluency": "Professional working proficiency"}],
    "projects": [{"name": "Payments revamp", "description": "Rebuilt checkout."}],
    "awards": [{"title": "A"}, {"title": "B"}],
    "references": [{"name": "Someone Else", "reference": "Call 555 0199"}],
}


def parse(doc, **kw):
    return parse_json_resume(json.dumps(doc), today=TODAY, **kw)


def test_maps_every_section_to_the_draft_shape():
    d = parse(SAMPLE)
    assert (d["version"], d["parserVersion"], d["source"]) == (1, "json-1", "json_resume")
    assert d["basicProfile"] == {"fullName": "Jane Sample", "email": "jane@example.invalid", "phone": "+1 555 010 0100", "location": "Springfield, IL, US",
                                 "currentRole": "Head of Product", "experienceYears": "10"}
    assert d["headline"] == "Technical Product Leader"
    first, second = d["parsedData"]["experienceDetail"]
    assert first == {"title": "Head of Product", "company": "Northwind", "location": "", "start": "April 2024", "end": "Present",
                     "description": "Own the portfolio.", "bullets": ["Grew ARR by 40%.", "Cut churn."]}
    assert (second["start"], second["end"]) == ("January 2016", "December 2019")
    assert d["parsedData"]["workExperience"][0] == "Head of Product — Northwind | April 2024 – Present | Own the portfolio. Grew ARR by 40%. Cut churn."
    assert d["parsedData"]["education"] == ["BSc Economics, University of Springfield, 2012"]
    assert d["parsedData"]["educationDetail"][0] == {"text": "BSc Economics, University of Springfield, 2012", "degree": "BSc Economics", "school": "University of Springfield", "year": "2012"}
    assert d["parsedData"]["certifications"] == ["CSPO, Scrum Alliance, March 2019"]
    assert d["parsedData"]["projects"] == ["Payments revamp: Rebuilt checkout."]
    assert d["parsedData"]["skills"] == ["Roadmapping", "Discovery", "SQL"]
    assert d["parsedData"]["competencyGroups"] == [{"label": "Product", "items": ["Roadmapping", "Discovery"]}, {"label": "Data", "items": ["SQL", "roadmapping"]}]
    assert d["languages"] == [{"language": "English", "proficiency": "native"}, {"language": "German", "proficiency": "advanced"}]
    assert d["links"] == ["https://example.invalid/jane", "https://linkedin.com/in/jane-sample"]
    assert d["confidence"]["fullName"] == d["confidence"]["skills"] == "high" and d["confidence"]["experienceYears"] == "derived"


def test_the_draft_has_exactly_the_text_parsers_keys_so_the_review_screen_cannot_tell_the_difference():
    from profile_import.text_parser import parse_text

    text_keys = set(parse_text("Skills\nSQL", "paste"))
    assert set(parse(SAMPLE)) == text_keys
    assert set(parse(SAMPLE)["parsedData"]) == set(parse_text("Skills\nSQL", "paste")["parsedData"])


def test_free_text_is_scrubbed_like_pasted_text_and_the_identifier_moves_to_its_field():
    d = parse(SAMPLE)
    assert "jane@example.invalid" not in d["summary"]
    assert d["summary"].startswith("Product leader.")
    assert any("moved out of the text" in w for w in d["warnings"])


def test_references_awards_and_the_like_are_counted_never_read():
    d = parse(SAMPLE)
    names = {i["name"]: i["reason"] for i in d["ignored"]}
    assert set(names) == {"Awards (2)", "References (1)"}
    assert "not read" in names["References (1)"]
    assert "Someone Else" not in json.dumps(d) and "555 0199" not in json.dumps(d)


def test_the_plain_text_kept_with_the_cv_is_rendered_from_what_was_read():
    raw = parse(SAMPLE)["rawText"]
    assert raw.startswith("Jane Sample\nTechnical Product Leader")
    assert "Experience\nHead of Product — Northwind\nApril 2024 – Present" in raw and "- Grew ARR by 40%." in raw
    assert "$schema" not in raw and "{" not in raw


def test_a_minimal_and_a_partly_wrong_file_are_read_not_refused():
    assert parse({"basics": {"name": "A B"}})["basicProfile"] == {"fullName": "A B"}
    d = parse({"basics": {"name": "A B"}, "work": "nope", "skills": [{"name": "SQL"}, "x", 5, {"keywords": ["Go"]}], "languages": [{"language": "French"}]})
    assert any("'work' section is not in the shape" in w for w in d["warnings"])
    assert d["parsedData"]["skills"] == ["SQL", "Go"]
    assert d["languages"] == [{"language": "French", "proficiency": ""}]
    d = parse({"work": [{"position": "Engineer"}, {"name": "Acme", "position": "Lead", "startDate": "2020"}]})
    assert d["confidence"]["experienceDetail.0"] == "low" and d["confidence"]["experienceDetail.1"] == "high"
    assert any("Experience entry 1" in w for w in d["warnings"])


def test_a_bom_is_tolerated():
    assert parse_json_resume("﻿" + json.dumps({"basics": {"name": "A B"}}))["basicProfile"]["fullName"] == "A B"


@pytest.mark.parametrize("text,code", [
    ("", "empty"), ("   ", "empty"), ("{ not json", "json_invalid"), ("[1, 2]", "json_not_resume"), ('"text"', "json_not_resume"),
    (json.dumps({"name": "package", "version": "1.0.0", "dependencies": {}}), "json_not_resume"), (json.dumps({"basics": {}}), "json_not_resume"),
    (json.dumps({"basics": {"name": "x"}, "pad": "a" * 210_000}), "too_large"),
])
def test_refusals_use_fixed_codes(text, code):
    with pytest.raises(TextImportError) as err:
        parse_json_resume(text)
    assert err.value.code == code


def test_non_string_input_is_invalid_request():
    with pytest.raises(TextImportError) as err:
        parse_json_resume({"basics": {}})
    assert err.value.code == "invalid_request"


def test_the_runner_dispatches_by_source_and_failures_carry_nothing_of_the_file():
    runner = str(ROOT / "python/profile_import/run_text_import.py")
    ok = subprocess.run([sys.executable, "-I", runner], input=json.dumps({"source": "json_resume", "text": json.dumps(SAMPLE)}), capture_output=True, text=True)
    out = json.loads(ok.stdout)
    assert out["ok"] is True and out["draft"]["source"] == "json_resume" and ok.stderr == ""
    bad = subprocess.run([sys.executable, "-I", runner], input=json.dumps({"source": "json_resume", "text": '{"basics": {"name": "CANARY-Zed" '}), capture_output=True, text=True)
    assert json.loads(bad.stdout) == {"ok": False, "code": "json_invalid"}
    assert "CANARY" not in bad.stdout + bad.stderr and bad.stderr == ""


def test_other_sources_do_not_take_json_as_a_resume():
    from profile_import.text_parser import parse_text

    d = parse_text(json.dumps({"basics": {"name": "A B"}}), "paste")
    assert d["source"] == "paste" and "parserVersion" in d
