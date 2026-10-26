"""No personal identifier reaches the provider in a judged run (DECISIONS.md principle 14).

The pipeline runs as it does on the server: enrich_jobs.main() reads the ad,
then run_scoring.main() --judge with HOLOJOB_ENGINE_SHADOW on builds the
candidate from the profile and runs the matcher through shadow.py. Nothing
in between is called directly or trusted: requests.post, where llm_client
hands a body to the network, is replaced, and every body it receives is
searched for the profile's identifiers and for candidate.gates.languages,
which the matcher settles locally (step 7b) and never sends. The Fit judge,
which runs in the same judged run, is held to the same identifiers; it sends
the language list on purpose.

The identifiers are placed where a real profile carries them, and also inside
the texts that become evidence items, so the redaction is what keeps them out.
The last tests remove one safeguard at a time and check that this test then
fails, so a passing run means something.
"""

import json
import re
import sys
import unicodedata

import pytest

import enrich_jobs
import evidence_index
from match_engine import shadow

NAME = "Milica Jovanović-Stanković"
EMAIL = "milica.jovanovic@gmail.com"
PHONE = "+381 64 123 4567"
CV_SITE = "milicaj.dev"
LINKEDIN = "https://www.linkedin.com/in/milica-jovanovic-pm/"
GITHUB = "github.com/mjovanovic"
LANGUAGES = ["Serbian (native)", "English (C2)", "German (B1)"]

PROFILE = {
    "basicProfile": {"fullName": NAME, "email": EMAIL, "phone": PHONE, "location": "Niš, Serbia",
                     "links": [f"https://{CV_SITE}", LINKEDIN, f"https://{GITHUB}"]},
    "resume": {"parsedData": {
        "links": [f"https://{CV_SITE}", LINKEDIN, f"https://{GITHUB}"],
        "experienceDetail": [
            {"title": "Senior Product Manager", "company": "Rute Inc", "start": "Apr 2021", "end": "Present",
             "bullets": [
                 "Led SQL-based analytics for the TMS, cutting reporting time by 40%",
                 f"{NAME} owned the roadmap; contact {EMAIL} or {PHONE}",
                 f"Case studies at {CV_SITE} and {CV_SITE}/work, profile {LINKEDIN}",
             ]},
            {"title": "Product Consultant", "company": "Jovanović Consulting", "start": "Jan 2018", "end": "Mar 2021",
             "bullets": [f"Shipped an open-source planner, code at {GITHUB}/planner",
                         "Managed discovery for 12 clients (call 064 123 4567)"]},
        ],
        "projects": [f"Planner: Built a planning tool, see https://{CV_SITE}/planner"],
        "skills": ["SQL", "Product discovery", f"Portfolio {CV_SITE}"],
    }},
}

INTELLIGENCE = {
    "languages": LANGUAGES,
    "jobFitPreferences": {"allowedLocations": ["REMOTE", "RS"], "minSalaryEur": 4321,
                          "preferredLocations": ["Niška Banja"], "relocation": "none", "country": "RS"},
    # What the Fit judge's digest reads, with identifiers where generated text could carry them.
    "candidateSummary": {"seniorityLevel": "senior",
                         "careerNarrative": f"{NAME} is a senior product manager; portfolio at {CV_SITE}"},
    "experienceMap": {
        "projectHighlights": [f"Planner, an open-source tool ({GITHUB}/planner)",
                              f"TMS rollout, case study on {LINKEDIN}"],
        "ownershipExamples": [f"Owned pricing for a SaaS product (write-up at {CV_SITE}/pricing)"],
        "leadershipExamples": [f"Mentored 3 PMs; references via {EMAIL} or {PHONE}"],
        "businessImpactExamples": [f"Grew activation by 25% (Jovanović Consulting)"],
    },
}

# Answers the candidate gave; the matcher never sends confirmed facts or their notes.
CONFIRMED_FACTS = [{"competencyId": "product-management", "has": True, "note": f"ask {NAME} at {PHONE}"}]

DESCRIPTION = """Senior Product Manager, fully remote.
Requirements:
* 5+ years of product management
* Hands-on SQL for analytics
* Fluent English
* Spanish is a plus
"""
JOB = {"jobId": "job-1", "title": "Senior Product Manager", "company": "Acme", "location": "Remote",
       "isRemote": True, "description": DESCRIPTION}

REQUIREMENTS = [
    ("5+ years of product management", "experience", "must"),
    ("Hands-on SQL for analytics", "skill", "must"),
    ("Fluent English", "language", "must"),
    ("Spanish is a plus", "language", "nice"),
]


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()


def _digits(text: str) -> str:
    return re.sub(r"[\s()./\-]", "", text)


def leaks(body: dict) -> list[str]:
    """Every identifier or language entry found anywhere in one outgoing request body."""
    raw = json.dumps(body, ensure_ascii=False)
    folded = _fold(raw)
    found = [f"name part {w!r}" for w in ("milica", "jovanovic", "stankovic") if w in folded]
    found += [f"{label} {value!r}" for label, value in (
        ("email", EMAIL), ("CV site", CV_SITE), ("LinkedIn", "linkedin.com/in/milica"), ("GitHub", GITHUB),
    ) if _fold(value) in folded]
    found += [f"phone {PHONE!r}" for local in ("641234567",) if local in _digits(raw)]
    found += [f"language {lang!r}" for lang in LANGUAGES if lang.lower() in raw.lower()]
    found += [f"gate {value!r}" for value in ("4321", "Niška Banja") if value in raw]
    return found


def _reply(body: dict) -> dict:
    """A well-formed answer for whichever prompt this is, by the schema it asks for."""
    schema = ((body.get("response_format") or {}).get("json_schema") or {}).get("name")
    prompt = body["messages"][0]["content"]
    if schema == "job_facts":
        return {
            "work_mode": "remote", "work_mode_evidence": "fully remote", "role_track": "product_management",
            "role_track_evidence": "Senior Product Manager", "seniority": "senior", "years_required": 5,
            "requirements": [{"text": t, "kind": k, "importance": i, "posting_quote": t, "previous_id": None}
                             for t, k, i in REQUIREMENTS],
            "domain": None, "listing_quality_flags": [], "job_country": None, "remote_eligibility": ["RS"],
            "visa_sponsorship": "not_mentioned", "visa_evidence": None,
        }
    if schema == "requirement_matches":
        refs = re.findall(r'"ref": "(r\d+)"', prompt)
        return {"matches": [{"ref": r, "status": "UNKNOWN", "evidence_id": None, "evidence_quote": None,
                             "strength": 0} for r in refs],
                "gates": {g: {"quote": None} for g in ("work_authorization", "location", "language",
                                                        "salary_floor", "role_family")}}
    if schema == "job_fit":
        return {"fit": "good", "fit_reason": "ok", "requirements": [], "missing": [], "dealbreakers": []}
    raise AssertionError(f"unexpected request schema {schema!r}")


class Response:
    status_code, ok = 200, True

    def __init__(self, reply: dict):
        self._reply = reply
        self.text = json.dumps(reply)

    def json(self):
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(self._reply)}}]}


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    """Runs extraction, then a judged scoring run with shadow on; returns {schema name: [bodies]}."""
    import requests
    import run_scoring

    sent: dict[str, list[dict]] = {}

    def post(url, headers=None, json=None, timeout=None):
        name = ((json.get("response_format") or {}).get("json_schema") or {}).get("name")
        sent.setdefault(name, []).append(json)
        return Response(_reply(json))

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setenv("HOLOJOB_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv(shadow.SHADOW_ENV, "1")

    jobs, intel, profile = tmp_path / "jobs.json", tmp_path / "intel.json", tmp_path / "profile.json"
    jobs.write_text(json.dumps({"jobs": [dict(JOB)]}))
    intel.write_text(json.dumps(INTELLIGENCE))
    profile.write_text(json.dumps(PROFILE))
    monkeypatch.setattr(run_scoring, "PROFILE_PATH", profile)
    monkeypatch.setattr(run_scoring, "FIT_CACHE_PATH", tmp_path / "llm_fit.json")
    monkeypatch.setattr(shadow, "CACHE_PATH", tmp_path / "engine.json")
    monkeypatch.setattr("confirmed_facts.load", lambda *a, **k: CONFIRMED_FACTS)

    def run():
        monkeypatch.setattr(sys, "argv", ["enrich_jobs.py", "--jobs", str(jobs), "--intelligence", str(intel),
                                          "--ledger", str(tmp_path / "ledger.json"), "--workers", "1"])
        assert enrich_jobs.main() == 0
        monkeypatch.setattr(sys, "argv", ["run_scoring.py", "--judge", "--judge-threshold", "0",
                                          "--intelligence", str(intel), "--jobs", str(jobs),
                                          "--output", str(tmp_path / "out.json"), "--workers", "1"])
        assert run_scoring.main() == 0
        out = json.loads((tmp_path / "out.json").read_text())
        return sent, out
    return run


def test_the_pipeline_really_calls_extraction_and_the_matcher(pipeline):
    sent, out = pipeline()
    assert len(sent.get("job_facts", [])) == 1
    assert len(sent.get("requirement_matches", [])) == 1
    assert out["jobs"][0]["engineShadow"]["requirements"], "the shadow engine produced no output"


def test_extraction_sends_no_identifier_and_no_language(pipeline):
    sent, _ = pipeline()
    assert [leaks(body) for body in sent["job_facts"]] == [[]]


def test_the_matcher_sends_no_identifier_and_no_language(pipeline):
    sent, _ = pipeline()
    (body,) = sent["requirement_matches"]
    assert leaks(body) == []
    # It did send the candidate's evidence, redacted, so the check above looked at real text.
    prompt = body["messages"][0]["content"]
    assert "cutting reporting time by 40%" in prompt and "[NAME]" in prompt and "[LINK]" in prompt


def test_the_languages_were_settled_locally(pipeline):
    sent, out = pipeline()
    prompt = sent["requirement_matches"][0]["messages"][0]["content"]
    asked = prompt.split("=== BEGIN REQUIREMENTS ===")[1].split("=== END REQUIREMENTS ===")[0]
    assert "SQL" in asked and "English" not in asked and "Spanish" not in asked
    statuses = {r["text"]: r["status"] for r in out["jobs"][0]["engineShadow"]["requirements"]}
    assert statuses["Fluent English"] == "MET" and statuses["Spanish is a plus"] == "UNKNOWN"


# --- the Fit judge (llm_enhancer.py), in the same judged run --------------------

def test_the_judge_sends_no_identifier_but_does_send_the_languages(pipeline):
    sent, _ = pipeline()
    (body,) = sent["job_fit"]
    found = leaks(body)
    # The language list is a deliberate send (CLAUDE.md, "Privacy rules and exceptions").
    assert [leak for leak in found if not leak.startswith("language")] == []
    assert all(f"language {lang!r}" in found for lang in LANGUAGES)
    prompt = body["messages"][0]["content"]
    assert "Grew activation by 25%" in prompt and "[NAME]" in prompt and "[LINK]" in prompt


# --- the matcher's second pass ------------------------------------------------

def test_the_second_pass_strips_the_name_and_the_profiles_links():
    from match_engine.matcher import _evidence_payload
    from redact import identity_of

    item = {"id": "ev-1", "source": "role", "role": f"PM — {NAME}", "start": None, "end": None,
            "text": f"{NAME}, portfolio {CV_SITE}"}
    assert leaks({"e": _evidence_payload([item], identity_of(PROFILE))}) == []
    assert leaks({"e": _evidence_payload([item])}), "without the identity the name gets through"


# --- the test fails when a safeguard is removed ----------------------------------

def _engine_leaks(sent) -> list[str]:
    return [leak for name in ("job_facts", "requirement_matches") for body in sent.get(name, []) for leak in leaks(body)]


def _no_redaction(text, *a, **k):
    return text, {}


def test_the_second_pass_alone_keeps_the_matcher_clean(pipeline, monkeypatch):
    monkeypatch.setattr(evidence_index, "redact_cv_text", _no_redaction)
    assert _engine_leaks(pipeline()[0]) == []


def test_it_catches_the_matcher_wired_without_the_identity(pipeline, monkeypatch):
    # The first pass removed and the shadow wiring passing no identity: the
    # second pass then knows neither the name nor the bare CV site.
    monkeypatch.setattr(evidence_index, "redact_cv_text", _no_redaction)
    init = shadow.ShadowEngine.__init__
    monkeypatch.setattr(shadow.ShadowEngine, "__init__", lambda self, *a, **k: init(self, *a, **{**k, "identity": None}))
    found = _engine_leaks(pipeline()[0])
    assert any(leak.startswith("name part") for leak in found)
    assert f"CV site {CV_SITE!r}" in found


def test_it_catches_both_redactions_removed(pipeline, monkeypatch):
    import match_engine.matcher as matcher

    monkeypatch.setattr(evidence_index, "redact_cv_text", _no_redaction)
    monkeypatch.setattr(matcher, "redact_cv_text", _no_redaction)
    found = _engine_leaks(pipeline()[0])
    for expected in (f"email {EMAIL!r}", f"phone {PHONE!r}", f"GitHub {GITHUB!r}", "LinkedIn 'linkedin.com/in/milica'",
                     f"CV site {CV_SITE!r}"):
        assert expected in found
    assert any(leak.startswith("name part") for leak in found)


def test_it_catches_a_careless_shadow_wiring(pipeline, monkeypatch):
    # What a careless edit of run_scoring._shadow_engine could do: give the
    # matcher the profile's own fields and the language list as evidence.
    # The second pass strips the name and e-mail; nothing can strip the languages.
    build = evidence_index.build_candidate

    def careless(profile, intelligence, facts):
        candidate = build(profile, intelligence, facts)
        basic = profile["basicProfile"]
        extra = [basic["fullName"], basic["email"], *intelligence["languages"]]
        candidate["evidence"] += [{"id": f"ev-x{i}", "source": "fact", "role": None, "start": None, "end": None,
                                   "text": text, "strength": 1} for i, text in enumerate(extra)]
        return candidate

    monkeypatch.setattr(evidence_index, "build_candidate", careless)
    found = _engine_leaks(pipeline()[0])
    assert all(f"language {lang!r}" in found for lang in LANGUAGES)
    assert not any(leak.startswith(("name part", "email")) for leak in found)


def _judge_leaks(sent) -> list[str]:
    return [leak for body in sent.get("job_fit", []) for leak in leaks(body) if not leak.startswith("language")]


def test_it_catches_a_judge_digest_without_redaction(pipeline, monkeypatch):
    import llm_enhancer

    monkeypatch.setattr(llm_enhancer, "redact_cv_text", _no_redaction)
    found = _judge_leaks(pipeline()[0])
    for expected in (f"email {EMAIL!r}", f"phone {PHONE!r}", f"GitHub {GITHUB!r}", f"CV site {CV_SITE!r}"):
        assert expected in found


def test_it_catches_a_judge_run_without_the_identity(pipeline, monkeypatch):
    import run_scoring

    monkeypatch.setattr(run_scoring, "identity_of", lambda profile: ("", []))
    found = _judge_leaks(pipeline()[0])
    assert any(leak.startswith("name part") for leak in found)
    assert f"CV site {CV_SITE!r}" in found
