"""The AI budget gate (python/llm/ai_gate.py): every model call asks first, and every one is recorded.

No test here reaches a provider: requests.post and the claude CLI are tripwired in
conftest.py, and the end-to-end pipeline run points its provider at a closed port.
"""

import io
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import ai_gate
import claude_code
import enrich_jobs
import llm_client
from conftest import permissive_ai_budget, select_provider
from llm_enhancer import LlmFitEnhancer

ROOT = Path(__file__).resolve().parents[2]
NOON = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def ledger():
    return ai_gate.read_ledger()


def calls(decision=None):
    return [r for r in ledger() if r["type"] == "call" and (decision is None or r["decision"] == decision)]


def settings(tmp_path, **values):
    ai = tmp_path / "ai"
    ai.mkdir(parents=True, exist_ok=True)
    (ai / "settings.json").write_text(json.dumps(values))


class _Reply:
    status_code, ok = 200, True

    def __init__(self, content='{"a": 1}', usage=None):
        self._data = {"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                      **({"usage": usage} if usage else {})}
        self.text = json.dumps(self._data)

    def json(self):
        return self._data


@pytest.fixture
def posts(monkeypatch):
    """Counts HTTP calls that get past the gate; answers each with a small JSON reply."""
    import requests

    sent = []

    def post(url, headers=None, json=None, timeout=None):
        sent.append(url)
        return _Reply(usage={"prompt_tokens": 120, "completion_tokens": 30})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    return sent


@pytest.fixture
def no_keys(monkeypatch):
    for name in ("CAREER_OS_LLM_PROVIDER", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY",
                 "GROQ_API_KEY", "LLM_API_KEY", "OLLAMA_BASE_URL", "LLM_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


# --- budget 0 -----------------------------------------------------------------


def test_with_no_settings_file_the_budget_is_0_and_automation_off():
    s = ai_gate.load_settings()
    assert s["dailyLimit"] == 0 and s["monthlyLimit"] == 0
    assert s["automation"]["enabled"] is False


def test_budget_0_refuses_a_paid_http_call_before_anything_is_sent(monkeypatch, posts, no_keys):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    with pytest.raises(llm_client.GuardrailRefused, match="AI budget is 0"):
        llm_client.complete_json("prompt", provider="openai")
    assert posts == []
    [row] = calls()
    assert row["decision"] == "refused" and row["provider"] == "openai" and row["class"] == "paid"


def test_budget_0_refuses_the_selected_cli(tmp_path, monkeypatch, no_keys):
    ran = []
    monkeypatch.setattr(llm_client.subprocess, "run", lambda *a, **k: ran.append(a))
    select_provider(tmp_path, monkeypatch, "claude-code", "sonnet")
    assert llm_client.active_provider() == "claude-code"
    with pytest.raises(llm_client.GuardrailRefused):
        llm_client.complete_json("prompt")
    assert ran == []
    assert calls("refused")[0]["provider"] == "claude-code"


def test_with_nothing_selected_a_call_refuses_and_no_provider_is_picked(monkeypatch, no_keys, caplog):
    # Keys in the environment, the CLI on the path: neither may choose a provider.
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("CAREER_OS_LLM_PROVIDER", "openai")
    ran = []
    monkeypatch.setattr(llm_client.subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(llm_client.NoProviderSelected, match="No AI provider selected"):
        llm_client.active_provider()
    with pytest.raises(llm_client.NoProviderSelected):
        llm_client.complete_json("prompt")
    assert ran == []
    assert "AI call refused: No AI provider selected" in caplog.text
    rows = calls("refused")
    assert rows and all(r["reason"].startswith("No AI provider selected") for r in rows)
    assert llm_client.peek_provider() == ""


def test_a_provider_the_python_pipeline_cannot_run_is_refused_not_swapped(tmp_path, monkeypatch, no_keys, caplog):
    monkeypatch.setenv("OPENAI_API_KEY", "k")  # a working key for another provider must not be used instead
    select_provider(tmp_path, monkeypatch, "gemini", "gemini-2.0-flash")
    with pytest.raises(llm_client.NoProviderSelected, match="gemini is selected but the Python pipeline cannot run it"):
        llm_client.active_provider()
    with pytest.raises(llm_client.NoProviderSelected):
        llm_client.complete_json("prompt")
    assert "gemini is selected" in caplog.text
    assert calls("refused")[0]["provider"] == "gemini"


def test_a_selected_provider_without_its_key_fails_and_does_not_fall_back(tmp_path, monkeypatch, posts, no_keys):
    permissive_ai_budget(tmp_path, monkeypatch)
    select_provider(tmp_path, monkeypatch, "openai")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")  # another provider is usable; it must not be tried
    ran = []
    monkeypatch.setattr(llm_client.subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(llm_client.LlmUnavailable, match="No API key for openai"):
        llm_client.complete_json("prompt")
    assert posts == [] and ran == []
    assert [r["decision"] for r in calls()] == ["refused"]  # logged, and refused before the gate reserved anything


def test_budget_0_refuses_the_cli_bridge_used_by_tailoring_import_and_scans(monkeypatch):
    ran = []
    monkeypatch.setattr(claude_code.subprocess, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(claude_code, "_availability", {"available": True, "reason": ""})
    with ai_gate.context(feature="tailoring", job_id="j9"):
        data, err = claude_code.complete_json("prompt")
    assert data is None and "AI budget is 0" in err
    assert ran == []
    [row] = calls("refused")
    assert row["feature"] == "tailoring" and row["jobId"] == "j9"


def test_the_cli_availability_check_sends_no_prompt(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setattr(claude_code.subprocess, "run", lambda *a, **k: ran.append(a))
    monkeypatch.setattr(claude_code, "_availability", None)
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(claude_code.Path, "home", lambda: tmp_path)
    assert claude_code.availability()["available"] is False  # no login file
    assert ran == [] and ledger() == []


def test_unknown_provider_is_treated_as_paid(monkeypatch, tmp_path, posts, no_keys):
    monkeypatch.setenv("LLM_BASE_URL", "http://10.0.0.5:8000/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    with pytest.raises(llm_client.GuardrailRefused):
        llm_client.complete_json("prompt", provider="custom")
    assert calls()[0]["class"] == "unknown"
    assert ai_gate.classify("somebody-new")["class"] == "unknown"
    # A budget above 0 does not help an unpriced provider: its cost cannot be checked.
    settings(tmp_path, dailyLimit=5, monthlyLimit=50)
    with pytest.raises(llm_client.GuardrailRefused, match="price unknown"):
        llm_client.complete_json("prompt", provider="custom")
    assert posts == []


def test_the_shipped_price_table_has_a_source_or_no_price_for_every_entry():
    table = json.loads((ROOT / "src" / "data" / "aiPricing.json").read_text())
    for entry in table["entries"]:
        assert entry["class"] in ai_gate.CLASSES
        if entry["inputPerMTok"] is not None:
            assert entry["source"] and entry["checkedAt"], entry
    assert ai_gate.classify("claude-code")["class"] == "paid"


# --- free and local ------------------------------------------------------------


def test_a_local_model_is_allowed_at_budget_0_and_recorded(monkeypatch, posts, no_keys):
    with ai_gate.context(feature="enrichment", job_id="j1"):
        assert llm_client.complete_json("prompt", provider="ollama") == {"a": 1}
    assert len(posts) == 1
    [row] = calls()
    assert row["decision"] == "allowed" and row["class"] == "local"
    assert row["feature"] == "enrichment" and row["jobId"] == "j1" and row["cache"] == "miss"
    [result] = [r for r in ledger() if r["type"] == "result"]
    assert result["id"] == row["id"] and result["ok"] is True
    assert (result["inputTokens"], result["outputTokens"], result["tokensAreEstimate"]) == (120, 30, False)
    assert result["cost"] == 0 and result["costIsEstimate"] is True
    assert ai_gate.totals()["today"]["calls"] == 1 and ai_gate.totals()["today"]["paidCalls"] == 0


def test_ollama_on_someone_elses_machine_is_not_local(monkeypatch, posts, no_keys):
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.example.com/v1")
    with pytest.raises(llm_client.GuardrailRefused):
        llm_client.complete_json("prompt", provider="ollama")
    assert posts == [] and calls()[0]["class"] == "unknown"


# --- limits --------------------------------------------------------------------


def _reserve(provider="openai", chars=4000, now=NOON):
    ticket = ai_gate.reserve(provider, "m", chars, now=now)
    ticket.finish(True, input_tokens=1000, output_tokens=1000, now=now)
    return ticket


def test_the_daily_limit_refuses_the_call_that_would_pass_it(tmp_path, monkeypatch):
    # 1 USD per million tokens: 2000 tokens cost 0.002.
    permissive_ai_budget(tmp_path, monkeypatch, daily=0.005, monthly=100, estimatedOutputTokens=1000)
    _reserve()
    _reserve()
    with pytest.raises(ai_gate.AiRefused, match="daily AI budget"):
        ai_gate.reserve("openai", "m", 4000, now=NOON)
    # Tomorrow is a new day.
    _reserve(now=NOON + timedelta(days=1))


def test_the_monthly_limit_counts_every_day_of_the_month_and_no_other(tmp_path, monkeypatch):
    permissive_ai_budget(tmp_path, monkeypatch, daily=1, monthly=0.005, estimatedOutputTokens=1000)
    _reserve(now=NOON - timedelta(days=20))  # previous month: not counted
    _reserve(now=NOON - timedelta(days=3))
    _reserve(now=NOON - timedelta(days=1))
    with pytest.raises(ai_gate.AiRefused, match="monthly AI budget"):
        ai_gate.reserve("openai", "m", 4000, now=NOON)
    month = ai_gate.totals(NOON)["thisMonth"]
    assert month["paidCalls"] == 2 and month["cost"] == pytest.approx(0.004)


def test_call_limits(tmp_path, monkeypatch):
    permissive_ai_budget(tmp_path, monkeypatch, maxCallsDaily=2, maxCallsMonthly=3)
    _reserve()
    _reserve()
    with pytest.raises(ai_gate.AiRefused, match="daily paid call limit"):
        ai_gate.reserve("openai", "m", 10, now=NOON)
    _reserve(now=NOON + timedelta(days=1))
    with pytest.raises(ai_gate.AiRefused, match="monthly paid call limit"):
        ai_gate.reserve("openai", "m", 10, now=NOON + timedelta(days=2))


def test_an_unfinished_call_still_counts_against_the_limit(tmp_path, monkeypatch):
    permissive_ai_budget(tmp_path, monkeypatch, maxCallsDaily=1)
    ai_gate.reserve("openai", "m", 10, now=NOON)  # in flight, or the process died
    with pytest.raises(ai_gate.AiRefused):
        ai_gate.reserve("openai", "m", 10, now=NOON)


def test_free_calls_do_not_use_the_paid_budget(tmp_path, monkeypatch):
    permissive_ai_budget(tmp_path, monkeypatch, maxCallsDaily=1)
    for _ in range(3):
        _reserve(provider="ollama")
    _reserve()


def test_an_unreadable_settings_file_refuses_paid_calls(tmp_path, monkeypatch):
    permissive_ai_budget(tmp_path, monkeypatch)
    (tmp_path / "ai" / "settings.json").write_text("{ not json")
    with pytest.raises(ai_gate.AiRefused, match="unreadable"):
        ai_gate.reserve("openai", "m", 10)
    _reserve(provider="ollama")


# --- automation ------------------------------------------------------------------


def test_an_automatic_task_is_refused_until_automation_is_enabled_even_when_free(tmp_path, monkeypatch, posts):
    monkeypatch.setenv(ai_gate.TRIGGER_ENV, ai_gate.AUTOMATION)
    with pytest.raises(llm_client.GuardrailRefused, match="automatic AI tasks are off"):
        llm_client.complete_json("prompt", provider="ollama")
    assert posts == []
    settings(tmp_path, automation={"enabled": True})
    assert llm_client.complete_json("prompt", provider="ollama") == {"a": 1}
    assert [r["trigger"] for r in calls()] == ["automation", "automation"]


def test_automation_on_does_not_lift_the_budget(tmp_path, monkeypatch, posts):
    monkeypatch.setenv(ai_gate.TRIGGER_ENV, ai_gate.AUTOMATION)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    settings(tmp_path, automation={"enabled": True})
    with pytest.raises(llm_client.GuardrailRefused, match="AI budget is 0"):
        llm_client.complete_json("prompt", provider="openai")
    assert posts == []


# --- the ledger ------------------------------------------------------------------


def test_the_ledger_is_append_only(tmp_path, monkeypatch):
    permissive_ai_budget(tmp_path, monkeypatch, maxCallsDaily=2)
    path = ai_gate.ledger_path()
    snapshots = []
    for step in (lambda: _reserve(), lambda: ai_gate.record_cache_hit("openai", "m"),
                 lambda: _reserve(provider="ollama"), lambda: _reserve()):
        step()
        snapshots.append(path.read_bytes())
    with pytest.raises(ai_gate.AiRefused):
        ai_gate.reserve("openai", "m", 10, now=NOON)
    snapshots.append(path.read_bytes())
    for before, after in zip(snapshots, snapshots[1:]):
        assert after.startswith(before) and len(after) > len(before)
    assert all(json.loads(line)["v"] == 1 for line in path.read_text().splitlines())


def test_a_ledger_line_has_every_field_the_owner_asked_for(posts, no_keys):
    with ai_gate.context(feature="cv-analysis", job_id="j2"):
        llm_client.complete_json("prompt", provider="ollama")
    row = calls()[0]
    for key in ("ts", "feature", "provider", "model", "inputTokens", "outputTokens", "cost", "costIsEstimate",
                "jobId", "cache", "decision"):
        assert key in row, key


def test_a_cache_hit_is_recorded_and_costs_nothing(tmp_path, monkeypatch):
    permissive_ai_budget(tmp_path, monkeypatch, maxCallsDaily=1)
    ai_gate.record_cache_hit("openai", "m", feature="fit-judge", job_id="j3", now=NOON)
    _reserve()  # the cache hit did not use the one paid call
    t = ai_gate.totals(NOON)["today"]
    assert t["cacheHits"] == 1 and t["paidCalls"] == 1


def test_a_failed_call_is_recorded_once_and_not_retried_by_the_gate(tmp_path, monkeypatch):
    import requests

    permissive_ai_budget(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    sent = []

    class Denied:
        status_code, ok, text = 401, False, "no"

    monkeypatch.setattr(requests, "post", lambda *a, **k: sent.append(1) or Denied())
    with pytest.raises(llm_client.LlmUnavailable):
        llm_client.complete_json("prompt", provider="openai")
    assert len(sent) == 1
    results = [r for r in ledger() if r["type"] == "result"]
    assert len(results) == 1 and results[0]["ok"] is False


def test_the_cli_reserve_and_finish_round_trip(tmp_path, monkeypatch, capsys):
    """The contract scripts/ai-gate.js relies on."""
    def cli(command, payload):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload) if payload is not None else ""))
        code = ai_gate._cli([command])
        return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    code, out = cli("reserve", {"provider": "openai", "model": "gpt", "promptChars": 400, "feature": "coverLetter"})
    assert code == 0 and out["allowed"] is False and "AI budget is 0" in out["reason"]
    code, out = cli("reserve", {"provider": "ollama", "promptChars": 400, "feature": "jobAnalysis",
                                "baseUrl": "http://localhost:11434", "jobId": "j4"})
    assert out["allowed"] is True
    code, done = cli("finish", {"id": out["id"], "ok": True, "inputTokens": 50, "outputTokens": 9})
    assert done == {"ok": True}
    code, again = cli("finish", {"id": out["id"], "ok": True})
    assert code == 1  # one result per call
    code, usage = cli("usage", None)
    assert usage["today"]["calls"] == 1 and usage["today"]["refused"] == 1
    assert usage["byFeature"]["jobAnalysis"]["inputTokens"] == 50
    assert usage["costsAreEstimates"] is True


# --- batches stop after a refusal, and free work goes on ----------------------------


AD = {"title": "Product Manager", "company": "Acme", "location": "Remote", "description": "Own the roadmap."}


def _jobs_file(tmp_path, n):
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps({"jobs": [{**AD, "jobId": f"j{i}", "title": f"PM {i}"} for i in range(n)]}))
    return path


def _enrich(tmp_path, monkeypatch, jobs, *extra):
    monkeypatch.setattr(sys, "argv", ["enrich_jobs.py", "--jobs", str(jobs), "--workers", "1",
                                      "--intelligence", str(tmp_path / "none.json"),
                                      "--ledger", str(tmp_path / "history.json"), *extra])
    return enrich_jobs.main()


def test_refused_enrichment_sends_nothing_logs_one_refusal_and_exits_0(tmp_path, monkeypatch, posts, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    select_provider(tmp_path, monkeypatch, "openai")
    jobs = _jobs_file(tmp_path, 4)
    assert _enrich(tmp_path, monkeypatch, jobs, "--manual") == 0
    out = capsys.readouterr().out
    assert "refused 4 (AI budget gate)" in out and "ai gate refused: paid call openai" in out
    assert posts == []
    [row] = calls()
    assert row["decision"] == "refused" and row["skipped"] == 4 and row["feature"] == "enrichment"


def test_enrichment_is_an_automatic_task_unless_run_with_manual(tmp_path, monkeypatch, posts, capsys):
    jobs = _jobs_file(tmp_path, 2)
    select_provider(tmp_path, monkeypatch, "ollama")
    assert _enrich(tmp_path, monkeypatch, jobs) == 0
    assert "automatic AI tasks are off" in capsys.readouterr().out and posts == []
    assert _enrich(tmp_path, monkeypatch, jobs, "--manual") == 0
    assert "extracted 2" in capsys.readouterr().out and len(posts) == 2


def test_a_limit_reached_mid_run_stops_the_batch(tmp_path, monkeypatch, capsys):
    import requests

    permissive_ai_budget(tmp_path, monkeypatch, maxCallsDaily=2)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    select_provider(tmp_path, monkeypatch, "openai")
    facts = json.dumps({"workMode": "remote", "roleTrack": "product_management", "seniority": "senior",
                        "yearsRequired": 5, "requirements": []})
    sent = []
    monkeypatch.setattr(requests, "post", lambda *a, **k: sent.append(1) or _Reply(facts))
    jobs = _jobs_file(tmp_path, 6)
    assert _enrich(tmp_path, monkeypatch, jobs, "--manual") == 0
    out = capsys.readouterr().out
    assert len(sent) == 2 and "extracted 2" in out
    assert len(calls("refused")) == 1  # the first refusal stops the batch; nothing is asked again
    saved = json.loads(jobs.read_text())["jobs"]
    assert sum(1 for j in saved if j.get("llmFacts")) == 2


def test_a_refused_judge_keeps_local_scores_and_stops_asking():
    asked = []

    def refuse(prompt, **kw):
        asked.append(prompt)
        raise llm_client.GuardrailRefused("AI budget is 0")

    enhancer = LlmFitEnhancer("openai", "m", threshold=0, complete=refuse)
    for i in range(3):
        job = {"jobId": f"j{i}", "title": "PM", "description": f"ad {i}"}
        base = {"matchScore": 70, "jobId": f"j{i}"}
        assert enhancer.enhance(job, base, {}) == base
    assert len(asked) == 1 and enhancer.counts["refused"] == 3 and enhancer.counts["failed"] == 0


# --- the whole pipeline with zero AI calls ------------------------------------------


def _copy_app(dest: Path) -> Path:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "python", dest / "python", ignore=ignore)
    shutil.copytree(ROOT / "src" / "data", dest / "src" / "data", ignore=ignore)
    data = dest / "data"
    (data / "intelligence").mkdir(parents=True)
    (data / "jobs").mkdir()
    shutil.copy(ROOT / "data" / "examples" / "candidate-intelligence.example.json",
                data / "intelligence" / "candidate-intelligence.json")
    jobs = [{**AD, "jobId": f"j{i}", "title": f"Senior Product Manager {i}", "jobUrl": f"https://x/{i}"}
            for i in range(5)]
    (data / "jobs" / "discovered_jobs.json").write_text(json.dumps({
        "meta": {"generatedAt": datetime.now(timezone.utc).isoformat(), "dedupedCount": 5}, "jobs": jobs}))
    return dest


@pytest.mark.parametrize("automation", [False, True])
def test_the_pipeline_runs_end_to_end_with_zero_ai_calls(tmp_path, automation):
    app = _copy_app(tmp_path / "app")
    ai = tmp_path / "ai-ledger"
    ai.mkdir()
    (ai / "settings.json").write_text(json.dumps({"automation": {"enabled": automation}}))
    env = {k: v for k, v in os.environ.items() if not k.endswith(("_API_KEY", "_BASE_URL"))}
    selection = tmp_path / "ai-settings.json"
    selection.write_text(json.dumps({"provider": "openai", "model": "test-model"}))
    env.update({
        "CAREER_OS_AI_DIR": str(ai), "CAREER_OS_AI_SELECTION": str(selection),
        # A paid provider at a closed port: if anything got past the gate, it would fail loudly here.
        "OPENAI_API_KEY": "test", "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
        "PATH": "/nonexistent",  # no claude CLI either
    })
    env.pop("CAREER_OS_AI_TRIGGER", None)
    proc = subprocess.run([sys.executable, str(app / "python" / "run_pipeline.py"), "--skip-discovery", "--json"],
                          cwd=app, env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary = json.loads(proc.stdout.strip().splitlines()[-1])
    assert summary["quality"]["reduced"] is True
    assert ("automatic AI tasks are off" if not automation else "AI budget is 0") in summary["quality"]["reason"]
    assert summary["enrichment"]["refused"] == 5
    scored = json.loads((app / "data" / "jobs" / "scored_jobs.json").read_text())
    assert len(scored["jobs"]) == 5
    assert all(j["aiEnrichment"] == "missing" for j in scored["jobs"])
    assert scored["meta"]["aiEnrichment"] == {"jobsWithoutFacts": 5, "jobs": 5}
    assert scored["meta"]["quality"]["reduced"] is True
    assert scored["meta"]["quality"]["reason"] == summary["quality"]["reason"]
    rows = [json.loads(line) for line in (ai / "usage-ledger.jsonl").read_text().splitlines()]
    assert [r["decision"] for r in rows] == ["refused"]
    assert rows[0]["trigger"] == "automation"
