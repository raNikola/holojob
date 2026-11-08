"""The shape of `lastImport.meta` (Wave 4, n): v2 keys, v1 compatibility, a clean error, and `lastPartial` for a cancelled run."""

import import_meta
import pytest
import view_guard
from test_cancel import NEW, cancel_run
from test_stale import JOB, OTHER, day, good_run, ledger_at


def test_a_full_import_writes_meta_v2_with_every_v1_key(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    meta = ledger_at(tmp_path)["lastImport"]["meta"]
    assert meta["metaVersion"] == import_meta.META_VERSION and meta["kind"] == "full"
    assert import_meta.missing_keys(meta) == []
    assert isinstance(meta["sources"], list) and meta["sources"], "one row per source of the run"
    row = meta["sources"][0]
    assert set(row) == {"name", "state", "readClass", "read", "kept", "reportedTotal", "proven", "why"}
    assert isinstance(meta["filterReasons"], dict)


def test_the_view_does_not_carry_the_new_keys(tmp_path, monkeypatch):
    """The view file keeps the bytes it always had: sources and filterReasons are in the ledger's meta only."""
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    view = view_guard.derive_view(ledger_at(tmp_path))
    assert "sources" not in view["meta"] and "metaVersion" not in view["meta"] and "filterReasons" not in view["meta"]


def test_a_v1_meta_still_gives_a_view(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    ledger = ledger_at(tmp_path)
    for key in ("metaVersion", "kind", "sources", "filterReasons"):
        ledger["lastImport"]["meta"].pop(key)
    assert import_meta.missing_keys(ledger["lastImport"]["meta"]) == []
    assert view_guard.derive_view(ledger)["jobs"]


def test_a_meta_without_a_required_key_is_a_view_error_not_a_key_error(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    ledger = ledger_at(tmp_path)
    del ledger["lastImport"]["meta"]["rawCount"]
    assert import_meta.missing_keys(ledger["lastImport"]["meta"]) == ["rawCount"]
    with pytest.raises(view_guard.ViewError, match="rawCount"):
        view_guard.derive_view(ledger)


def test_a_cancelled_run_leaves_last_import_and_writes_last_partial(tmp_path, monkeypatch):
    good_run(tmp_path, monkeypatch, "a", day(0), ads=(JOB, OTHER))
    before = ledger_at(tmp_path)
    assert "lastPartial" not in before
    from test_stale import GOOD
    cancel_run(tmp_path, monkeypatch, "b", day(10), {"jobspy": ([OTHER, NEW], GOOD, [])})
    after = ledger_at(tmp_path)
    assert after["lastImport"] == before["lastImport"], "lifecycle rules: the list is still the last complete run's"
    assert after["lastPartial"]["runId"] == "b" and after["lastPartial"]["saved"] == 2 and after["lastPartial"]["reason"] == "cancelled"
