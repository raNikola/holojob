"""M8: a years qualifier per requirement, verified against its quote; and the --max-usd cap. No model call is made."""

import sys
import types

import pytest

import enrich_jobs
import job_fingerprint
from llm_client import GuardrailRefused

AD = {"jobId": "a", "title": "T", "company": "C", "location": "L", "description": "Body."}
QUOTE = "5+ years of product management"


def _item(**over):
    return {"text": "Product management", "kind": "experience", "importance": "must", "posting_quote": QUOTE,
            "previous_id": None, "qualifier": {"kind": "years", "value": 5}, **over}


def _qualifier(item):
    reqs = enrich_jobs._coerce({"requirements": [item]})["requirements"]
    return reqs[0]["qualifier"]


def test_kept_when_its_number_is_in_the_quote():
    assert _qualifier(_item()) == {"kind": "years", "value": 5}


@pytest.mark.parametrize("qualifier", [
    {"kind": "years", "value": 3},      # number not in the quote
    {"kind": "years", "value": 55},     # out of range (and not a whole token of the quote)
    {"kind": "years", "value": 41},
    {"kind": "years", "value": -5},
    {"kind": "years", "value": "5"},    # not an integer
    {"kind": "years", "value": 5.0},
    {"kind": "years", "value": True},
    {"kind": "level", "value": 5},      # wrong kind
    {"value": 5},
    "5",
    None,
])
def test_dropped_to_null(qualifier):
    assert _qualifier(_item(qualifier=qualifier)) is None


def test_number_inside_a_longer_number_does_not_count():
    assert _qualifier(_item(posting_quote="15 years of sales", qualifier={"kind": "years", "value": 5})) is None


def test_zero_and_forty_are_in_range():
    assert _qualifier(_item(posting_quote="0 years", qualifier={"kind": "years", "value": 0})) == {"kind": "years", "value": 0}
    assert _qualifier(_item(posting_quote="40 years", qualifier={"kind": "years", "value": 40})) == {"kind": "years", "value": 40}


def test_missing_field_is_null():
    item = _item()
    del item["qualifier"]
    assert _qualifier(item) is None


@pytest.mark.parametrize("with_competencies", [False, True])
def test_schema_requires_the_field_and_stays_strict(with_competencies):
    item = enrich_jobs.fact_schema(with_competencies)["schema"]["properties"]["requirements"]["items"]
    assert "qualifier" in item["required"]
    q = item["properties"]["qualifier"]
    assert q["type"] == ["object", "null"] and q["additionalProperties"] is False
    assert sorted(q["required"]) == sorted(q["properties"]) == ["kind", "value"]
    assert item["additionalProperties"] is False and set(item["required"]) == set(item["properties"])


def test_fixed_text_still_comes_first_and_names_the_field():
    prompt = enrich_jobs.build_prompt(AD)
    head = prompt.split("=== BEGIN JOB AD")[0]
    assert '"qualifier"' in head and "qualifier" in head.split("Rules:")[1]
    assert "Title: T" not in head and prompt.index('"qualifier"') < prompt.index("Title: T")


# --- the cap ---------------------------------------------------------------

PRICE = {"in": 1.0, "out": 10.0}


def test_worst_case_and_stop_before_overspending(monkeypatch):
    monkeypatch.setattr(enrich_jobs.ai_gate, "read_ledger", lambda: [])
    prompt = "x" * 3000  # 1000 tokens at 3 chars per token
    guard = enrich_jobs.SpendGuard(0.0025, PRICE, 100)  # worst = (1000*1 + 100*10) / 1e6 = 0.002
    assert guard.worst(prompt) == pytest.approx(0.002)
    first = guard.reserve(prompt)
    with pytest.raises(GuardrailRefused):  # one call in flight, a second would pass the cap
        guard.reserve(prompt)
    guard.release(first)
    guard.reserve(prompt)  # fits again once the first is done and billed nothing


def test_spent_counts_only_this_runs_enrichment_results(monkeypatch):
    guard = enrich_jobs.SpendGuard(1.0, PRICE, 10)
    when = guard.started_at.isoformat()
    rows = [
        {"type": "call", "id": "1", "feature": "enrichment", "decision": "allowed", "ts": when},
        {"type": "result", "id": "1", "cost": 0.4},
        {"type": "call", "id": "2", "feature": "evidence-matcher", "decision": "allowed", "ts": when},
        {"type": "result", "id": "2", "cost": 9},
        {"type": "call", "id": "3", "feature": "enrichment", "decision": "allowed", "ts": "2000-01-01T00:00:00+00:00"},
        {"type": "result", "id": "3", "cost": 9},
    ]
    monkeypatch.setattr(enrich_jobs.ai_gate, "read_ledger", lambda: rows)
    assert guard.spent() == pytest.approx(0.4)
    with pytest.raises(GuardrailRefused):
        enrich_jobs.SpendGuard.reserve(guard, "x" * 3_000_000)


def _run(tmp_path, monkeypatch, capsys, extra):
    import json
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [{**AD, "jobId": f"j{i}", "title": f"T{i}"} for i in range(3)]}))
    calls = []

    def fake(prompt, schema=None, model=None, provider=None):
        calls.append(prompt)
        return {"requirements": [_item()]}

    monkeypatch.setattr(enrich_jobs, "complete_json", fake)
    monkeypatch.setattr(enrich_jobs, "preflight", lambda *a, **k: types.SimpleNamespace(allowed=True))
    monkeypatch.setattr(enrich_jobs, "active_provider", lambda: "fake")
    monkeypatch.setattr(enrich_jobs, "make_guard", lambda cap, p, m: enrich_jobs.SpendGuard(cap, PRICE, 100))
    monkeypatch.setattr(enrich_jobs.ai_gate, "read_ledger", lambda: [])
    for mod, attr, val in (
        (enrich_jobs.view_guard, "ensure_or_exit", lambda *a, **k: None),
        (enrich_jobs.competency_mapping, "load_mapper", lambda *a: None),
        (enrich_jobs.competency_mapping, "load_remap", lambda: {}),
        (enrich_jobs.requirement_frames, "load", lambda: {}),
        (enrich_jobs.requirement_frames, "save", lambda f: None),
    ):
        monkeypatch.setattr(mod, attr, val)
    monkeypatch.setattr(sys, "argv", ["enrich", "--jobs", str(jobs), "--intelligence", str(tmp_path / "none.json"),
                                      "--ledger", str(tmp_path / "ledger.json"), "--workers", "1", "--manual", *extra])
    try:
        code = enrich_jobs.enrich(enrich_jobs.parse_args())
    except Exception as exc:  # surfaced below with the output
        code = repr(exc)
    return code, calls, capsys.readouterr()


def test_cap_stops_before_overspending_and_prints_the_spend(tmp_path, monkeypatch, capsys):
    # every call's worst case is far above this cap, so nothing is sent
    code, calls, out = _run(tmp_path, monkeypatch, capsys, ["--max-usd", "0.0001"])
    assert calls == []
    assert "enrichment spend: $0.0000 of the $0.00 cap" in out.out and "cap" in out.err


def test_no_cap_no_change(tmp_path, monkeypatch, capsys):
    code, calls, out = _run(tmp_path, monkeypatch, capsys, [])
    assert len(calls) == 3 and "enrichment spend" not in out.out


def test_extract_without_a_guard_is_unchanged(monkeypatch):
    monkeypatch.setattr(enrich_jobs, "complete_json", lambda *a, **k: {"requirements": [_item()]})
    facts = enrich_jobs.extract(AD, None, None)
    assert facts["requirements"][0]["qualifier"] == {"kind": "years", "value": 5}


def test_parse_args_default_is_off():
    sys.argv = ["enrich"]
    assert enrich_jobs.parse_args().max_usd is None


def test_after_the_bump_every_fingerprint_differs(monkeypatch):
    ads = [AD, {**AD, "title": "Other"}, {**AD, "description": "Else"}]
    new = [job_fingerprint.job_fingerprint(a) for a in ads]
    monkeypatch.setattr(job_fingerprint, "PROMPT_VERSION", 5)
    old = [job_fingerprint.job_fingerprint(a) for a in ads]
    assert all(n != o for n, o in zip(new, old))
