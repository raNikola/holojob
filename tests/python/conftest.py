"""Pytest path setup for Career OS Python modules."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Insert in reverse so job_scoring (last) wins import precedence over resume_generator.
for sub in ("llm", "job_discovery", "resume_generator", "job_scoring", "cv_analysis"):
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
    monkeypatch.setenv("CAREER_OS_AI_DIR", str(tmp_path / "ai"))
    monkeypatch.delenv("CAREER_OS_AI_PRICING", raising=False)
    # Set, not deleted, so teardown also removes what enrich_jobs.main() writes into os.environ.
    monkeypatch.setenv("CAREER_OS_AI_TRIGGER", "manual")


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
    monkeypatch.setenv("CAREER_OS_AI_PRICING", str(pricing))
    return ai


@pytest.fixture
def open_ai_budget(tmp_path, monkeypatch):
    """For tests of the work around a model call, not of the gate: paid calls priced and allowed, automation on."""
    return permissive_ai_budget(tmp_path, monkeypatch, automation={"enabled": True})


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: hits a live third-party site; skipped when unreachable"
    )
