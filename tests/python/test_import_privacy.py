"""Profile import never calls a model or the network, and its failures never carry what was uploaded (Wave 7, S1)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMPORT_DIR = ROOT / "python" / "profile_import"
RUNNER = IMPORT_DIR / "run_text_import.py"

# Canary identifiers: whatever the input holds must not come back through an error, stderr or a file.
NAME = "Zorbel Quantifex"
EMAIL = "zorbel.quantifex@canary-7741.example"
PHONE = "+999 555 010 7741"
LINK = "https://canary-7741.example/in/zorbel-quantifex"
CANARIES = (NAME, "Quantifex", EMAIL, PHONE, "canary-7741")
CV = f"{NAME}\n{EMAIL}\n{PHONE}\n{LINK}\n\nExperience\nProduct Manager, Acme | 2020 - 2023\n- Led the roadmap.\n"

FORBIDDEN_IMPORT = re.compile(
    r"^\s*(?:from|import)\s+(?:llm\b|ai_gate\b|anthropic\b|openai\b|requests\b|urllib\b|http\b|socket\b|subprocess\b|httpx\b|aiohttp\b|claude_code\b)",
    re.M,
)


def _run(payload: str, **kw):
    return subprocess.run([sys.executable, "-I", str(RUNNER)], input=payload, capture_output=True, text=True, **kw)


def test_no_import_module_reaches_a_model_or_the_network():
    files = sorted(IMPORT_DIR.glob("*.py"))
    assert files
    for file in files:
        found = FORBIDDEN_IMPORT.findall(file.read_text(encoding="utf-8"))
        assert not found, f"{file.name} imports {found}"
    node = (ROOT / "scripts" / "run-profile-import.js").read_text(encoding="utf-8")
    assert "ai-gate" not in node and "ai_gate" not in node and "fetch(" not in node


@pytest.mark.parametrize("payload,code", [
    ("", "invalid_request"),
    (json.dumps({"text": "   \n  ", "source": "paste"}), "empty"),
    (json.dumps({"text": CV, "source": "not_a_source"}), None),
    (json.dumps({"text": 12345}), None),
    (json.dumps([CV]), None),
    ("{ this is not json " + CV, None),
])
def test_a_failure_prints_a_fixed_code_and_nothing_of_the_input(payload, code):
    done = _run(payload)
    out = json.loads(done.stdout)
    assert out["ok"] is False and isinstance(out["code"], str)
    if code:
        assert out["code"] == code
    everything = done.stdout + done.stderr
    assert done.stderr == ""
    for canary in CANARIES:
        assert canary not in everything


def test_a_crash_inside_the_parser_is_a_fixed_code_not_the_exception(tmp_path):
    crash = tmp_path / "crash_runner.py"
    crash.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT / 'python')!r}); sys.path.insert(0, {str(IMPORT_DIR)!r})\n"
        "import profile_import.text_parser as text_parser\n"
        f"def boom(*a, **k): raise ValueError({CV!r})\n"
        "text_parser.parse_text = boom\n"
        f"sys.argv = [{str(RUNNER)!r}]\n"
        f"exec(compile(open({str(RUNNER)!r}).read(), 'runner', 'exec'))\n",
        encoding="utf-8",
    )
    done = subprocess.run([sys.executable, str(crash)], input=json.dumps({"text": CV}), capture_output=True, text=True)
    out = json.loads(done.stdout)
    assert out == {"ok": False, "code": "parse_failed"}
    assert done.stderr == ""
    for canary in CANARIES:
        assert canary not in done.stdout + done.stderr


def test_a_successful_parse_writes_nothing_and_logs_nothing(tmp_path):
    before = sorted(p.name for p in ROOT.joinpath("data").rglob("*") if p.is_file()) if (ROOT / "data").exists() else []
    done = _run(json.dumps({"text": CV, "source": "paste"}))
    out = json.loads(done.stdout)
    assert out["ok"] is True and out["draft"]["version"] == 1 and out["draft"]["parserVersion"] == "text-1"
    assert done.stderr == ""
    after = sorted(p.name for p in ROOT.joinpath("data").rglob("*") if p.is_file()) if (ROOT / "data").exists() else []
    assert before == after
    # The identifiers live in their own fields; the free text fields never carry them.
    draft = out["draft"]
    assert draft["basicProfile"].get("email") == EMAIL
    body = json.dumps({k: v for k, v in draft.items() if k not in ("rawText", "basicProfile", "links", "source")})
    assert EMAIL not in body and PHONE not in body
