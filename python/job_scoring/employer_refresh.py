"""Refresh a discovered ad's text from the employer's own page (package 13 of PACKAGES_PLAN; needs package 6, which finds the thin ads).

Flow, all on the owner's click, no model:
  1. `propose`: the owner gives the employer page address. The server fetches it with `job_import/safe_fetch.py` (the only fetcher with
     SSRF limits), reads the posting with `ad_reader.py` (JSON-LD description, else the page text) and stores the text as a PROPOSAL in
     `data/jobs/employer_refresh.json` (600). The answer is a line diff of the scraped text against the proposal.
  2. `accept` (in `rescore_kept.py --accept-employer`): the proposal becomes the ad's overlay text (`pasted_descriptions`, source
     "employer") and the ad is re-scored locally. `discard` drops the proposal.
The scraped text in the ledger is never changed: the original stays, and removing the overlay brings it back. Discovery writes none of
these files. Errors and answers carry codes, never page text beyond the proposal the owner asked for.
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("python/job_import", "python/job_scoring"):
    if str(ROOT / _sub) not in sys.path:
        sys.path.insert(0, str(ROOT / _sub))

import job_history  # noqa: E402
import pasted_descriptions  # noqa: E402
from atomic_write import write_text_atomic  # noqa: E402

PROPOSALS_PATH = ROOT / "data" / "jobs" / "employer_refresh.json"
JOBS_PATH = ROOT / "data" / "jobs" / "discovered_jobs.json"
JOB_ID = pasted_descriptions.JOB_ID
FILE_MODE = 0o600
MAX_DIFF_LINES = 2000


def load(path: Path = PROPOSALS_PATH) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    ads = doc.get("ads") if isinstance(doc, dict) else None
    if not isinstance(ads, dict):
        return {}
    return {k: v for k, v in ads.items() if isinstance(k, str) and JOB_ID.match(k) and isinstance(v, dict) and isinstance(v.get("text"), str)}


def _save(ads: dict, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(Path(path), json.dumps({"version": 1, "ads": ads}, indent=2), FILE_MODE)


def discard(job_id: str, path: Path = PROPOSALS_PATH) -> bool:
    ads = load(path)
    if job_id not in ads:
        return False
    del ads[job_id]
    _save(ads, path)
    return True


def proposal_text(job_id: str, path: Path = PROPOSALS_PATH) -> str | None:
    entry = load(path).get(job_id)
    return entry["text"] if entry else None


def _lines(text: str) -> list[str]:
    return [re.sub(r"[ \t]+", " ", line).strip() for line in (text or "").replace("\r\n", "\n").split("\n") if line.strip()]


def diff_lines(original: str, proposed: str) -> list[dict]:
    """[{"op": "same" | "add" | "del", "text"}] over the non-empty lines, whitespace folded. Capped; the cap is reported by the caller."""
    a, b = _lines(original), _lines(proposed)
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            out += [{"op": "same", "text": t} for t in a[i1:i2]]
            continue
        out += [{"op": "del", "text": t} for t in a[i1:i2]]
        out += [{"op": "add", "text": t} for t in b[j1:j2]]
    return out


def propose(job_id: str, url: str, *, jobs: Path = JOBS_PATH, path: Path = PROPOSALS_PATH, fetch_page=None, now: str | None = None) -> tuple[int, dict]:
    """Fetch `url`, store the proposal for `job_id`, answer the diff. Exit codes: 0 ok, 2 invalid, 3 fetch failed, 4 ad not in history."""
    if not isinstance(job_id, str) or not JOB_ID.match(job_id):
        return 2, {"ok": False, "error": "invalid", "field": "jobId"}
    import ad_reader  # noqa: PLC0415
    import safe_fetch  # noqa: PLC0415

    ledger = job_history.load(job_history.ledger_path(jobs), read_only=True)
    entry = (ledger.get("jobs") or {}).get(job_id)
    if not entry or (entry.get("job") or {}).get("manualEntry"):
        return 4, {"ok": False, "error": "not_in_history"}
    original = str((entry.get("job") or {}).get("description") or "")
    try:
        page = (fetch_page or safe_fetch.fetch_page)(str(url or ""))
    except safe_fetch.FetchRefused as exc:
        return 3, {"ok": False, "error": exc.code, "status": exc.status}
    ad = ad_reader.read_ad(page.html)
    text = ad["fields"].get("description") or ""
    from_posting = bool(text)
    if not text and ad["readable"]:
        text = ad["pageText"]
    if not ad["readable"] or len(text.strip()) < pasted_descriptions.MIN_TEXT:
        return 3, {"ok": False, "error": "js_only" if "<script" in page.html.lower() else "unreadable"}
    text = pasted_descriptions.clean(text[: pasted_descriptions.MAX_TEXT])
    ads = load(path)
    ads[job_id] = {"text": text, "url": page.url, "fetchedAt": now or datetime.now(timezone.utc).isoformat(), "from": "json-ld" if from_posting else "page-text"}
    _save(ads, path)
    diff = diff_lines(original, text)
    return 0, {"ok": True, "finalUrl": page.url, "from": ads[job_id]["from"], "originalChars": len(original.strip()), "proposedChars": len(text),
               "identical": all(d["op"] == "same" for d in diff), "truncated": len(diff) > MAX_DIFF_LINES, "diff": diff[:MAX_DIFF_LINES]}


def main(argv=None) -> int:
    """`propose --job-id ID` (stdin {"url"}) or `discard --job-id ID`. One JSON object on stdout."""
    argv = sys.argv[1:] if argv is None else argv
    job_id = next((a.split("=", 1)[1] for a in argv if a.startswith("--job-id=")), "")
    if argv[:1] == ["propose"]:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            payload = {}
        code, body = propose(job_id, payload.get("url") if isinstance(payload, dict) else "")
    elif argv[:1] == ["discard"] and JOB_ID.match(job_id):
        code, body = 0, {"ok": True, "discarded": discard(job_id)}
    else:
        code, body = 2, {"ok": False, "error": "invalid", "field": "jobId"}
    print(json.dumps(body))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
