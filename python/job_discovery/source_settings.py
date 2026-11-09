"""The owner's source switches: data/config/sources.json (SOURCES_SPEC.md, first slice).

Opt-in sources (source_definitions.py) need `active: true` and a consent time. Every other
source is on unless its entry says `active: false` (the owner's switch, no consent); discovery
skips such a source entirely, which is "skipped by owner", never an empty or failed read.

    { "version": 1, "updatedAt": "...",
      "boards": { "joberty": { "active": false, "consentAcceptedAt": "2026-10-30T12:00:00+00:00",
                               "disabledAt": "...", "history": [{ "at": "...", "event": "enabled", ... }] } },
      "migrations": { "job-dashboard-discovery-options": "..." } }

An opt-in source is active only with `active: true` AND a consent time. A missing
file, a missing entry or an unreadable file means off: nothing here ever switches
one on by default. Turning one on needs `consentAccepted: true` in the request and
stores the server's time as `consentAcceptedAt`; turning it off keeps that time
and the history. The one exception to "only the owner switches it on" is the
one-time move of the old Jobs-screen checkbox (`migrate_legacy`), which the owner
ticked under the same terms note; it is recorded as such.

The server is the master (DECISIONS.md principle 15): the browser keeps no copy.
Written only here, atomically and under a lock; the API reaches it through the CLI
at the bottom (scripts/sources-handler.js), discovery reads it (run_discovery.py).
"""

from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:  # run as a script by the Node API
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from source_definitions import PROVIDER_GROUPS, SOURCE_DEFINITIONS, STANDARD_GROUP, opt_in_names  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# Loaded by path, as export_jobs does: job_scoring on sys.path would let its modules shadow this package's.
_atomic_spec = importlib.util.spec_from_file_location("_sources_atomic_write", ROOT / "python" / "job_scoring" / "atomic_write.py")
_atomic_module = importlib.util.module_from_spec(_atomic_spec)
_atomic_spec.loader.exec_module(_atomic_module)

VERSION = 1
HISTORY_LIMIT = 50
LEGACY_BROWSER_KEY = "job-dashboard-discovery-options"
OFF_HINT = "enable it in Settings > Sources"


class SourcesError(RuntimeError):
    """The file exists but cannot be used. It is left as it is."""


def sources_path() -> Path:
    explicit = os.environ.get("HOLOJOB_SOURCES")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("HOLOJOB_CONFIG_DIR") or ROOT / "data" / "config") / "sources.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def empty() -> dict:
    return {"version": VERSION, "updatedAt": None, "boards": {}, "migrations": {}}


def read() -> dict:
    path = sources_path()
    if not path.exists():
        return empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourcesError(f"{path.name} is unreadable ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict) or not isinstance(data.get("boards", {}), dict):
        raise SourcesError(f"{path.name} has an unexpected shape")
    if not isinstance(data.get("version"), int) or data["version"] > VERSION:
        raise SourcesError(f"{path.name} has version {data.get('version')!r}; this build reads {VERSION}")
    return {**empty(), **data}


def is_enabled(name: str, data: dict) -> bool:
    entry = (data.get("boards") or {}).get(name)
    return isinstance(entry, dict) and entry.get("active") is True and bool(entry.get("consentAcceptedAt"))


def is_owner_off(name: str, data: dict | None) -> bool:
    """A source that follows the groups is on unless the owner switched it off here (`active: false`). Opt-in sources use is_enabled."""
    entry = ((data or {}).get("boards") or {}).get(name)
    return name not in opt_in_names() and isinstance(entry, dict) and entry.get("active") is False


SKIP_SWITCH = "skipped by owner (switched off in Settings > Sources)"
SKIP_THIS_RUN = "skipped by owner for this run"


def owner_skips(names: list[str], data: dict | None, exclude: list[str] | None = None) -> tuple[list[str], list[tuple[str, str]]]:
    """(sources to run, [(source, reason)] skipped by the owner). Skipped is not empty and not failed: nothing was searched,
    so the run records a skipped row and the importer holds that source's ads as they are (a source that did not run closes nothing).
    `data` None (settings unreadable) switches nothing off. `exclude` is the one-off "not this time", never saved."""
    excluded = {n.strip().lower() for n in exclude or [] if n.strip()}
    kept, skipped = [], []
    for name in names:
        if is_owner_off(name, data):
            skipped.append((name, SKIP_SWITCH))
        elif name in excluded:
            skipped.append((name, SKIP_THIS_RUN))
        else:
            kept.append(name)
    return kept, skipped


def effective_providers(spec: str | None, resolved: list[str], data: dict | None) -> tuple[list[str], list[str]]:
    """(providers to run, opt-in sources dropped because they are off), whatever the request named.

    An opt-in source that is off is dropped even when the request names it. One that
    is on joins every run that asks for a group (the standard run is the `serbia`
    group); a run that lists only names gets those names. `data` None means the
    settings could not be read: every opt-in source is then off.
    """
    data = data or empty()
    opt_in = set(opt_in_names())
    kept = [n for n in resolved if n not in opt_in or is_enabled(n, data)]
    dropped = [n for n in resolved if n in opt_in and not is_enabled(n, data)]
    parts = [p.strip().lower() for p in (spec or STANDARD_GROUP).split(",")]
    if any(p in PROVIDER_GROUPS for p in parts):
        kept += [n for n in opt_in_names() if is_enabled(n, data) and n not in kept]
    return kept, dropped


@contextmanager
def _locked():
    path = sources_path()
    _atomic_module.make_private_dirs(path.parent)
    private = lambda name, flags: os.open(name, flags, _atomic_module.PRIVATE_FILE_MODE)
    with open(path.with_name(f".{path.name}.lock"), "a", opener=private) as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _write(data: dict) -> None:
    path = sources_path()
    data["updatedAt"] = now_iso()
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _record(entry: dict, event: str, at: str, **extra) -> None:
    entry["history"] = [*(entry.get("history") or []), {"at": at, "event": event, **extra}][-HISTORY_LIMIT:]


def view(data: dict | None = None, error: str | None = None) -> dict:
    """What GET /api/sources answers: every source, whether it is opt-in, and the opt-in switches."""
    data = data or empty()
    boards = []
    for name, definition in SOURCE_DEFINITIONS.items():
        row = {"name": name, "optIn": definition.opt_in, "inStandardRun": name in PROVIDER_GROUPS[STANDARD_GROUP]}
        if not definition.opt_in:
            entry = (data.get("boards") or {}).get(name) or {}
            row.update(active=not is_owner_off(name, data), disabledAt=entry.get("disabledAt"), history=entry.get("history") or [])
        else:
            entry = (data.get("boards") or {}).get(name) or {}
            row.update(
                active=is_enabled(name, data),
                consentAcceptedAt=entry.get("consentAcceptedAt"),
                disabledAt=entry.get("disabledAt"),
                migratedFrom=entry.get("migratedFrom"),
                history=entry.get("history") or [],
            )
        boards.append(row)
    return {"boards": boards, "updatedAt": data.get("updatedAt"), **({"error": error} if error else {})}


def get() -> dict:
    try:
        return view(read())
    except SourcesError as exc:
        return view(None, f"{exc}; every opt-in source counts as off until it is fixed or removed")


def save(boards, now: str | None = None) -> dict:
    """Apply {name: {active, consentAccepted?}} for opt-in sources.

    {ok, ...view} | {ok: False, errors} | {ok: False, needsConsent: [names]}. Nothing is
    written unless every change is valid.
    """
    if not isinstance(boards, dict) or not boards:
        return {"ok": False, "errors": ["boards must be an object naming at least one source"]}
    errors = []
    for name, change in boards.items():
        if name not in SOURCE_DEFINITIONS:
            errors.append(f"{name}: unknown source")
        elif not isinstance(change, dict) or not isinstance(change.get("active"), bool):
            errors.append(f"{name}: active must be true or false")
    if errors:
        return {"ok": False, "errors": errors}

    at = now or now_iso()
    with _locked():
        try:
            data = read()
        except SourcesError as exc:
            return {"ok": False, "errors": [f"{exc}; fix or remove the file, it was left as it is"]}
        opt_in = set(opt_in_names())
        turning_on = [n for n, c in boards.items() if n in opt_in and c["active"] and not is_enabled(n, data)]
        missing = [n for n in turning_on if boards[n].get("consentAccepted") is not True]
        if missing:
            return {"ok": False, "needsConsent": missing}
        for name, change in boards.items():
            if name not in opt_in:  # a group source: on unless switched off; no consent, no entry until the owner changes it
                was_off = is_owner_off(name, data)
                if change["active"] == (not was_off):
                    continue
                entry = data["boards"].setdefault(name, {"active": True, "history": []})
                entry.update(active=change["active"], disabledAt=None if change["active"] else at)
                _record(entry, "enabled" if change["active"] else "disabled", at)
                continue
            entry = data["boards"].setdefault(name, {"active": False, "consentAcceptedAt": None, "history": []})
            if name in turning_on:
                entry.update(active=True, consentAcceptedAt=at, disabledAt=None)
                _record(entry, "enabled", at, consentAcceptedAt=at)
            elif not change["active"] and entry.get("active"):
                entry.update(active=False, disabledAt=at)  # consentAcceptedAt and history stay
                _record(entry, "disabled", at)
        _write(data)
    return {"ok": True, **view(data)}


def migrate_legacy(value, now: str | None = None) -> dict:
    """Move the old Jobs-screen checkbox ({"includeJoberty": true}) here, once.

    Only an explicit `includeJoberty: true` switches Joberty on, with the migration
    time as consent, and only when the server has no decision of its own yet. Runs
    at most once per install; any later call changes nothing.
    """
    at = now or now_iso()
    with _locked():
        try:
            data = read()
        except SourcesError as exc:
            return {"ok": False, "errors": [str(exc)]}
        if LEGACY_BROWSER_KEY in data["migrations"]:
            return {"ok": True, "migrated": False, "reason": "already migrated", **view(data)}
        ticked = isinstance(value, dict) and value.get("includeJoberty") is True
        migrated = ticked and "joberty" not in data["boards"]
        if migrated:
            entry = data["boards"]["joberty"] = {
                "active": True, "consentAcceptedAt": at, "disabledAt": None,
                "migratedFrom": LEGACY_BROWSER_KEY, "history": [],
            }
            _record(entry, "enabled", at, consentAcceptedAt=at,
                    note="moved from the Jobs-screen checkbox, ticked under the same terms note")
        data["migrations"][LEGACY_BROWSER_KEY] = at
        _write(data)
    return {"ok": True, "migrated": migrated, **view(data)}


def _cli(argv: list[str]) -> int:
    """`get`, `put` ({boards}), `migrate-legacy` ({value}): JSON on stdin, one JSON object on stdout."""
    command = argv[0] if argv else ""
    raw = sys.stdin.read() if command != "get" else ""
    try:
        args = json.loads(raw) if raw.strip() else {}
    except ValueError:
        args = None
    if not isinstance(args, dict):
        print(json.dumps({"ok": False, "errors": ["input must be a JSON object"]}))
        return 0
    if command == "get":
        print(json.dumps(get()))
    elif command == "put":
        print(json.dumps(save(args.get("boards"))))
    elif command == "migrate-legacy":
        print(json.dumps(migrate_legacy(args.get("value"))))
    else:
        print("usage: source_settings.py get|put|migrate-legacy  (JSON on stdin)", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
