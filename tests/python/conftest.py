"""Pytest path setup for Holojob Python modules."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Insert in reverse so job_scoring (last) wins import precedence over resume_generator.
for sub in ("job_import", "llm", "job_discovery", "resume_generator", "job_scoring", "cv_analysis"):
    path = ROOT / "python" / sub
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# match_engine is a package: python/ itself goes last, so none of its folders
# shadows a flat module above.
if str(ROOT / "python") not in sys.path:
    sys.path.append(str(ROOT / "python"))


@pytest.fixture(autouse=True)
def _requirement_frames_in_tmp(tmp_path, monkeypatch):
    """No test reads or writes the server's data/cache/requirement-frames.json."""
    import requirement_frames

    monkeypatch.setattr(requirement_frames, "FRAMES_PATH", tmp_path / "requirement-frames.json")


@pytest.fixture(autouse=True)
def _competency_files_in_tmp(tmp_path, monkeypatch):
    """No test reads or writes the server's learned aliases or remap table."""
    import competency_mapping

    monkeypatch.setattr(competency_mapping, "ALIASES_PATH", tmp_path / "competency-aliases.json")
    monkeypatch.setattr(competency_mapping, "REMAP_PATH", tmp_path / "requirement-remap.json")


@pytest.fixture(autouse=True)
def _ai_gate_in_tmp(tmp_path, monkeypatch):
    """No test reads the server's AI budget settings or writes its usage ledger."""
    monkeypatch.setenv("HOLOJOB_AI_DIR", str(tmp_path / "ai"))
    monkeypatch.delenv("HOLOJOB_AI_PRICING", raising=False)
    # Set, not deleted, so teardown also removes what enrich_jobs.main() writes into os.environ.
    monkeypatch.setenv("HOLOJOB_AI_TRIGGER", "manual")


@pytest.fixture(autouse=True)
def _ai_selection_in_tmp(tmp_path, monkeypatch):
    """No test reads the server's data/config/ai-settings.json. By default nothing is selected, so a call refuses."""
    monkeypatch.setenv("HOLOJOB_AI_SELECTION", str(tmp_path / "config" / "ai-settings.json"))
    monkeypatch.delenv("HOLOJOB_LLM_PROVIDER", raising=False)


@pytest.fixture(autouse=True)
def _source_settings_in_tmp(tmp_path, monkeypatch):
    """No test reads the server's data/config/sources.json: every opt-in source starts off."""
    monkeypatch.setenv("HOLOJOB_SOURCES", str(tmp_path / "config" / "sources.json"))


@pytest.fixture(autouse=True)
def _run_log_in_tmp(tmp_path, monkeypatch):
    """No test writes the server's data/analytics/runs/."""
    monkeypatch.setenv("HOLOJOB_ANALYTICS_DIR", str(tmp_path / "analytics"))


@pytest.fixture(autouse=True)
def _manual_jobs_in_tmp(tmp_path, monkeypatch):
    """No test reads the owner's data/jobs/manual_jobs.json: a scoring run merges that file in, which changes what it scores and sends."""
    import manual_jobs

    monkeypatch.setattr(manual_jobs, "MANUAL_PATH", tmp_path / "jobs" / "manual_jobs.json")


@pytest.fixture(autouse=True)
def _secret_store_in_tmp(tmp_path, monkeypatch):
    """No test reads the server's data/secrets/, and no key from the host shell reaches a test."""
    monkeypatch.setenv("HOLOJOB_SECRETS_DIR", str(tmp_path / "secrets"))
    for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "LLM_API_KEY",
                 "ANTHROPIC_API_KEY", "OPENAI_BASE_URL", "OPENROUTER_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    import secret_store

    monkeypatch.setattr(secret_store, "_masked", set())


def fail_replacing(monkeypatch, target):
    """Make the rename onto `target` fail, and only that one, so no other write can be what the test sees fail.
    Returns the names of the temp files it was asked to rename, which proves the write went through a temp file."""
    import os
    from pathlib import Path

    real_replace, temps = os.replace, []

    def replace(src, dst, **kwargs):
        if Path(dst) == Path(target):
            assert Path(src).exists()
            temps.append(Path(src).name)
            raise OSError("disk full")
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    return temps


def write_secret_store(tmp_path, entries, mode=0o600):
    """Write data/secrets/ai.json the way the Node store would (directory 700, file 600 unless told otherwise)."""
    import json
    import os

    directory = tmp_path / "secrets"
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / "ai.json"
    path.write_text(json.dumps(entries))
    os.chmod(path, mode)
    return path


def select_provider(tmp_path, monkeypatch, provider="openai", model="test-model", **extra):
    """Write a provider selection the way Settings would (the same file the Node path reads)."""
    import json

    path = tmp_path / "config" / "ai-settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provider": provider, "model": model, **extra}))
    monkeypatch.setenv("HOLOJOB_AI_SELECTION", str(path))
    return path


@pytest.fixture(autouse=True)
def _no_real_model_call(monkeypatch):
    """Tripwire: a test that reaches a real provider or the claude CLI fails, unless it patched the call itself."""
    import subprocess

    import requests

    def no_post(*args, **kwargs):
        raise AssertionError(f"a test made a real HTTP POST: {args[:1]}")

    real_run = subprocess.run

    def guarded_run(args, *rest, **kwargs):
        first = args[0] if isinstance(args, (list, tuple)) and args else args
        if str(first).rsplit("/", 1)[-1] == "claude":
            raise AssertionError("a test ran the claude CLI")
        return real_run(args, *rest, **kwargs)

    monkeypatch.setattr(requests, "post", no_post)
    monkeypatch.setattr(subprocess, "run", guarded_run)


def permissive_ai_budget(tmp_path, monkeypatch, *, price=1.0, daily=1000, monthly=10000, **extra):
    """Settings and a price table under which a paid test call is allowed (for tests of the call itself)."""
    import json

    ai = tmp_path / "ai"
    ai.mkdir(parents=True, exist_ok=True)
    (ai / "settings.json").write_text(json.dumps({"dailyLimit": daily, "monthlyLimit": monthly, **extra}))
    providers = ("openai", "deepseek", "openrouter", "groq", "claude-code", "custom")
    pricing = tmp_path / "pricing.json"
    pricing.write_text(json.dumps({"currency": "USD", "entries": [
        {"provider": "ollama", "model": "*", "class": "local", "inputPerMTok": 0, "outputPerMTok": 0,
         "source": "test", "checkedAt": "2026-10-29"},
        *({"provider": name, "model": "*", "class": "paid", "inputPerMTok": price, "outputPerMTok": price,
           "source": "test", "checkedAt": "2026-10-29"} for name in providers),
    ]}))
    monkeypatch.setenv("HOLOJOB_AI_PRICING", str(pricing))
    return ai


@pytest.fixture
def open_ai_budget(tmp_path, monkeypatch):
    """For tests of the work around a model call, not of the gate: paid calls priced and allowed, automation on."""
    return permissive_ai_budget(tmp_path, monkeypatch, automation={"enabled": True})


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: hits a live third-party site; skipped when unreachable"
    )
