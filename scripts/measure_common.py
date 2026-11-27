"""Package B measurement helpers: read-only, no model call, no provider.

Shared by measure_baseline.py, measure_rescore_impact.py, measure_gate_confusion.py, measure_extraction_variance.py
and measure_package_b.py. Everything printed is a count, a job id or a public ad title; no description, name, profile
or CV value is ever read into an output.

The Re-score here is run_scoring.score() itself (the code behind the Jobs screen's Re-score button), pointed at a data
directory and an output directory of our own, with the model call replaced by the same raising stub run_scoring uses.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _sub in ("job_scoring", "llm"):
    if str(ROOT / "python" / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / "python" / _sub))
if str(ROOT / "python") not in sys.path:
    sys.path.append(str(ROOT / "python"))

import work_authorization as wa  # noqa: E402
import view_guard  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts"))
from measure_tmp import private_tempdir  # noqa: E402
from atomic_write import PRIVATE_FILE_MODE, make_private_dirs, write_text_atomic  # noqa: E402
from scorer import OFF_TRACK_CAP, UNRELATED_TITLE_CAP  # noqa: E402

# Caps scoringVersion 1.4 and older rows carry. Step 2 (1.5) removed them from scorer.py; the numbers stay here, frozen,
# so a baseline snapshot or a stored 1.4 file can still be read and a changed ad classified by what capped it before.
LANGUAGE_CAP = 25
WORK_AUTHORIZATION_CAPS = {wa.NEEDS_VISA_REFUSED: 25, wa.OUTSIDE_ALLOWED: 40, wa.NEEDS_VISA_SILENT: 45}
LEGACY_INSUFFICIENT_CEILING = 5
NOT_READ_STATUSES = ("insufficient", "not_read")  # dataStatus: the 1.4 "insufficient" state and the 1.5 "not_read" state

EVAL_DIR = Path("/home/ranikola/holojob-eval")
REPORT_PATH = EVAL_DIR / "package-b-report.md"
SNAPSHOT_PATH = EVAL_DIR / "package-b-snapshot.json"

RED_FLAG_CAP = 54  # scorer.score_job: `if red_flags and match_score > 55: min(match_score, 54)`; not a named constant there
INSUFFICIENT = "Insufficient data"
NOT_READ = "Not read"

# The "Capped: ..." reason texts score_job writes. No cap field is stored on a row, so the three caps without a status of
# their own are read from these prefixes; tests/python/test_package_b_measure.py checks they still exist in scorer.py.
OFF_TRACK_PREFIX = "Capped: the ad describes"
TITLE_PREFIX = "Capped: the title matches no"
LANGUAGE_PREFIX = "Capped: the ad requires"

# cap name -> the number it lowers a score to (None: not a number, the insufficient ceiling is separate)
CAP_VALUES = {
    "red_flag": RED_FLAG_CAP,
    "off_track": OFF_TRACK_CAP,
    "unrelated_title": UNRELATED_TITLE_CAP,
    "language": LANGUAGE_CAP,
    **{f"visa:{status}": value for status, value in WORK_AUTHORIZATION_CAPS.items()},
    "insufficient_data": LEGACY_INSUFFICIENT_CEILING,
}
CAP_ORDER = list(CAP_VALUES)


def default_data_dir() -> Path:
    """This checkout's data/, or the main checkout's when this is a worktree (a worktree holds the examples only)."""
    here = ROOT / "data"
    if (here / "jobs" / "scored_jobs.json").exists():
        return here
    parts = ROOT.parts
    if ".worktrees" in parts or "worktrees" in parts:
        main = ROOT
        while main.name != ".claude" and main.parent != main:
            main = main.parent
        candidate = main.parent / "data"
        if (candidate / "jobs" / "scored_jobs.json").exists():
            return candidate
    return here


def git_stamp() -> dict:
    def run(*args):
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False).stdout.strip()
    return {"commit": run("rev-parse", "--short=12", "HEAD"), "dirty": bool(run("status", "--porcelain", "--untracked-files=no"))}


def band_of(row: dict) -> str:
    return row.get("matchLabel") or "(none)"


def auth_of(row: dict) -> dict:
    return row.get("workAuthorization") or {}


def caps_of(row: dict) -> tuple[set, set]:
    """(fired, binding) cap names for one scored row.

    fired: the rule applies to the ad (its condition holds), whether or not it lowered the score.
    binding: it fired, its number is below scoreBeforeCaps, and the final score sits at that number (so it is the cap that
    decided the score). Two caps that fire together can both be named fired; only the lowest can be binding. A fit-judge
    adjustment applied after the caps can move a score off its cap, which then shows as fired but not binding.
    Insufficient-data rows have scoreBeforeCaps clamped to the ceiling, so they are counted by dataStatus alone.
    """
    reasons = [r for r in row.get("reasons") or [] if isinstance(r, str)]
    fired = set()
    if row.get("dataStatus") in NOT_READ_STATUSES:
        fired.add("insufficient_data")
    if row.get("redFlags") and (row.get("scoreBeforeCaps") or 0) > 55:
        fired.add("red_flag")
    if any(r.startswith(OFF_TRACK_PREFIX) for r in reasons):
        fired.add("off_track")
    if any(r.startswith(TITLE_PREFIX) for r in reasons):
        fired.add("unrelated_title")
    if any(r.startswith(LANGUAGE_PREFIX) for r in reasons):
        fired.add("language")
    status = auth_of(row).get("status")
    if status in WORK_AUTHORIZATION_CAPS and not row.get("scoringVersion"):  # a 1.5 row is stamped; no visa cap exists for it
        fired.add(f"visa:{status}")
    before, score = row.get("scoreBeforeCaps"), row.get("matchScore")
    binding = set()
    for name in fired:
        if name == "insufficient_data":
            binding.add(name)
        elif before is not None and score is not None and CAP_VALUES[name] < before and score == CAP_VALUES[name]:
            binding.add(name)
    return fired, binding


def snapshot_rows(rows: list[dict]) -> dict:
    """{jobId: the fields a later package is compared on}. No text field of the ad is kept."""
    out = {}
    for row in rows:
        fired, binding = caps_of(row)
        auth = auth_of(row)
        out[row["jobId"]] = {
            "score": row.get("matchScore"), "band": band_of(row), "scoreBeforeCaps": row.get("scoreBeforeCaps"),
            "dataStatus": row.get("dataStatus"), "readStatus": row.get("readStatus"),
            "eligibility": (row.get("eligibility") or {}).get("state"), "scoringVersion": row.get("scoringVersion"), "authStatus": auth.get("status"), "authBasis": auth.get("basis"),
            "capsFired": sorted(fired), "capsBinding": sorted(binding),
            "manual": bool(row.get("manualEntry")),
            "judgeAdjustment": (row.get("llmFit") or {}).get("adjustment") or 0, "profileGuard": row.get("profileGuard"),
            "hardCapped": bool(row.get("hardCapped")),
            "applyRecommendation": row.get("applyRecommendation"), "priority": row.get("priority"),
            "blockedKinds": sorted(b.get("kind") for b in row.get("blockedBy") or []),
            "locationState": (row.get("locationState") or {}).get("state"),
        }
    return out


def load_scored(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def meta_stamp(meta: dict) -> dict:
    return {key: meta.get(key) for key in ("scoringVersion", "generatedAt", "intelligenceGeneratedAt", "discoveryGeneratedAt", "jobCount")}


def read_snapshot(path: Path) -> dict:
    """A frozen snapshot file, or a scored_jobs.json converted on the fly (stamp then holds its meta only)."""
    doc = load_scored(path)
    if "rows" in doc and "stamp" in doc:
        return doc
    return {"stamp": {"source": "scored_jobs file", "meta": meta_stamp(doc.get("meta") or {})},
            "rows": snapshot_rows(doc.get("jobs") or []),
            "titles": {j["jobId"]: (None if j.get("manualEntry") else j.get("title")) for j in doc.get("jobs") or []}}


def write_private(path: Path, text: str) -> None:
    path = Path(path)
    make_private_dirs(path.parent)
    write_text_atomic(path, text, new_file_mode=PRIVATE_FILE_MODE)


# --- the Re-score -------------------------------------------------------------------------------------------------

class StaleViewError(RuntimeError):
    pass


def rescore(data_dir: Path | None = None, keep_output: Path | None = None, extra_ids: set | None = None) -> dict:
    """Run run_scoring.score() on `data_dir` with no model call; return the scored payload (never written under data/).

    Refuses when the job list is not in step with the ledger (run_scoring would rebuild and rewrite it). Switches the
    shadow engine off in this process (it writes its own cache and has a second model path). Reads the selected provider
    and model from <data_dir>/config, because the cached fit judgements are keyed by them; the AI ledger directory is a
    temp one, since a cache hit records a line there.
    """
    import run_scoring

    data_dir = Path(data_dir or default_data_dir())
    jobs, ledger = data_dir / "jobs" / "discovered_jobs.json", data_dir / "jobs" / "job_history.json"
    state = view_guard.state(jobs, ledger)
    if not state["consistent"]:
        raise StaleViewError(f"job list and ledger are out of step ({state['reason']}); run a scoring first so the view is rebuilt")

    with private_tempdir("package-b-") as tmp:
        output = keep_output or (tmp / "scored_jobs.json")
        kept = data_dir / "jobs" / "rescored_kept.json"
        if extra_ids:
            # Ads the list no longer holds are scored from the ledger exactly like a kept ad (kept_ads.with_kept): marked
            # keptRescore and outside the term-rarity corpus, so no other ad's score moves. The real kept file is not touched.
            import kept_ads
            entries = {**kept_ads.load(kept), **{i: {} for i in extra_ids if kept_ads.JOB_ID.match(str(i))}}
            kept = tmp / "kept.json"
            kept.write_text(json.dumps({"version": 1, "ids": entries}), encoding="utf-8")
        argv = ["--intelligence", str(data_dir / "intelligence" / "candidate-intelligence.json"), "--jobs", str(jobs),
                "--manual", str(data_dir / "jobs" / "manual_jobs.json"), "--kept", str(kept),
                "--output", str(output)]
        saved_env = {k: os.environ.get(k) for k in ("HOLOJOB_ENGINE_SHADOW", "HOLOJOB_CONFIG_DIR", "HOLOJOB_AI_DIR")}
        saved_paths = (run_scoring.FIT_CACHE_PATH, run_scoring.PROFILE_PATH)
        try:
            os.environ.pop("HOLOJOB_ENGINE_SHADOW", None)
            os.environ["HOLOJOB_CONFIG_DIR"] = str(data_dir / "config")
            os.environ["HOLOJOB_AI_DIR"] = str(tmp / "ai")
            run_scoring.FIT_CACHE_PATH = data_dir / "cache" / "llm_fit.json"
            run_scoring.PROFILE_PATH = data_dir / "profile" / "candidate-profile.json"
            args = _parse(run_scoring, argv)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = run_scoring.score(args)
            if code != 0:
                raise RuntimeError(f"run_scoring.score returned {code}")
            return json.loads(Path(output).read_text(encoding="utf-8"))
        finally:
            run_scoring.FIT_CACHE_PATH, run_scoring.PROFILE_PATH = saved_paths
            for key, value in saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _parse(module, argv):
    old = sys.argv
    sys.argv = ["run_scoring.py", *argv]
    try:
        return module.parse_args()
    finally:
        sys.argv = old


def data_fingerprint(data_dir: Path) -> dict:
    """{relative path: (size, mtime_ns)} of the files a measurement reads or could be mistaken for writing. No content."""
    out = {}
    for sub in ("jobs", "profile", "intelligence", "cache", "config", "ai", "calibration/stage-a", "applications"):
        base = Path(data_dir) / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                st = path.stat()
                out[str(path.relative_to(data_dir))] = (st.st_size, st.st_mtime_ns)
    return out


def fingerprint_changes(before: dict, after: dict) -> list[str]:
    names = sorted(set(before) | set(after))
    return [n for n in names if before.get(n) != after.get(n)]


def tally(values) -> dict:
    return dict(sorted(Counter(values).items(), key=lambda kv: (-kv[1], str(kv[0]))))
