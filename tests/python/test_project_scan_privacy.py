"""The project scan lets the model read a repository. Nothing it may run can print commit authors' names or e-mails."""

import re
import sys
from pathlib import Path

import claude_code

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python" / "project_intelligence"))
import run_project_scan  # noqa: E402

# The only commands the scan may run, besides the file tools: they list names or count lines, nothing else.
SAFE_COMMANDS = {"ls", "wc"}
FILE_TOOLS = {"Read", "Grep", "Glob", "LS"}


def bash_command(entry: str):
    match = re.fullmatch(r"Bash\((\S+?)(?::\*|\s.*)?\)", entry)
    return match.group(1) if match else None


def test_every_allowed_tool_is_a_file_tool_or_a_listing_command():
    for entry in claude_code.READONLY_TOOLS:
        if entry in FILE_TOOLS:
            continue
        assert bash_command(entry) in SAFE_COMMANDS, entry


def test_no_allowed_tool_can_print_authors_or_run_other_commands():
    joined = " ".join(claude_code.READONLY_TOOLS).lower()
    for word in ("git", "cat", "find", "xargs", "awk", "sed", "sh", "bash:", "env", "python", "node", "curl", "tail", "head", "less", "grep:"):
        assert not re.search(rf"\bbash\({word}\b", joined), word
    assert "git" not in joined
    # `Bash(*)` or a bare Bash would allow anything.
    assert "Bash" not in claude_code.READONLY_TOOLS and not any(e in ("Bash(*)", "Bash(:*)") for e in claude_code.READONLY_TOOLS)


def test_git_s_own_files_are_denied_to_the_file_tools():
    assert any(".git" in rule and rule.startswith("Read(") for rule in claude_code.DISALLOWED_TOOLS)


def test_the_repo_analysis_passes_both_lists_to_the_cli(monkeypatch):
    seen = {}
    monkeypatch.setattr(claude_code, "is_available", lambda: True)
    monkeypatch.setattr(claude_code, "_run", lambda args, prompt, timeout, cwd=None: (seen.update(args=args, prompt=prompt) or ('{"name": "x"}', "")))
    data, err = claude_code.analyze_repo("/repo", "PROMPT")
    assert data == {"name": "x"} and err == ""
    args = seen["args"]
    assert args[args.index("--allowed-tools") + 1] == ",".join(claude_code.READONLY_TOOLS)
    assert args[args.index("--disallowed-tools") + 1] == ",".join(claude_code.DISALLOWED_TOOLS)


def test_the_prompt_no_longer_asks_for_the_git_history():
    prompt = run_project_scan.ANALYSIS_PROMPT.lower()
    assert "git log" not in prompt and "shortlog" not in prompt and "git show" not in prompt


def test_the_model_gets_the_commit_facts_counted_by_code_and_no_author_field(monkeypatch):
    stats = {"commits": 42, "firstCommit": "2024-01-02", "lastCommit": "2025-03-04", "fileCount": 120, "languages": ["Python"],
             "authors": ["Jane Canary <jane@example.com>"], "authorName": "Jane Canary"}
    sent = {}
    monkeypatch.setattr(run_project_scan, "git_stats", lambda repo: stats)
    monkeypatch.setattr(run_project_scan.claude_code, "analyze_repo", lambda path, prompt: (sent.update(prompt=prompt) or (None, "stub")))
    run_project_scan.scan_repo(Path("/tmp/some-repo"), "local", use_llm=True)
    prompt = sent["prompt"]
    for fact in ("42", "2024-01-02", "2025-03-04", "120", "Python"):
        assert fact in prompt
    assert "Jane" not in prompt and "example.com" not in prompt and "authors" not in prompt.lower()


def test_the_local_stats_hold_no_author_field():
    # git_stats reads dates and counts only; this keeps a future author field out of the prompt block.
    block = run_project_scan.stats_block({"commits": 1, "authorEmail": "x@example.com", "committer": "x"})
    assert "x@example.com" not in block and "committer" not in block
