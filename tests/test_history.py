"""Tests for Phase 3: SQLite history layer, diff engine, and CLI history commands."""

import json
from pathlib import Path

from engine.cli import build_parser, cmd_diff, cmd_history, cmd_store
from engine.db import HistoryDB, _compute_changes
from engine.diff import Change, diff_assessments, format_diff

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _base_assessment(**overrides) -> dict:
    a = {
        "schema_version": "1.0",
        "timestamp": "2024-01-01T00:00:00+00:00",
        "hostname": "pve01.lab",
        "hardware": {
            "cpu": {"model": "Intel Xeon E-2236", "total_cores": 6},
            "memory": {"total_bytes": 34359738368, "ecc_enabled": True},
        },
        "storage": {
            "disks": [{"name": "sda", "size_bytes": 500000000000, "smart_status": "PASSED"}],
        },
    }
    a.update(overrides)
    return a


# ===========================================================================
# HistoryDB – basic CRUD
# ===========================================================================

def test_store_and_fetch(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    a = _base_assessment()
    row_id = db.store(a)
    assert row_id == 1
    fetched = db.fetch(row_id)
    assert fetched["hostname"] == "pve01.lab"
    db.close()


def test_store_multiple_returns_incrementing_ids(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    id1 = db.store(_base_assessment(timestamp="2024-01-01T00:00:00+00:00"))
    id2 = db.store(_base_assessment(timestamp="2024-01-02T00:00:00+00:00"))
    assert id2 == id1 + 1
    db.close()


def test_fetch_nonexistent_returns_none(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    assert db.fetch(999) is None
    db.close()


def test_list_assessments_empty(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    assert db.list_assessments() == []
    db.close()


def test_list_assessments_ordered_newest_first(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    db.store(_base_assessment(timestamp="2024-01-01T00:00:00+00:00"))
    db.store(_base_assessment(timestamp="2024-01-02T00:00:00+00:00"))
    rows = db.list_assessments()
    assert rows[0]["id"] > rows[1]["id"]
    db.close()


def test_list_assessments_hostname_filter(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    db.store(_base_assessment(hostname="pve01.lab"))
    db.store(_base_assessment(hostname="pve02.lab"))
    rows = db.list_assessments(hostname="pve01.lab")
    assert all(r["hostname"] == "pve01.lab" for r in rows)
    assert len(rows) == 1
    db.close()


def test_list_assessments_limit(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    for i in range(5):
        db.store(_base_assessment(timestamp=f"2024-01-0{i+1}T00:00:00+00:00"))
    rows = db.list_assessments(limit=3)
    assert len(rows) == 3
    db.close()


def test_hostnames(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    db.store(_base_assessment(hostname="alpha"))
    db.store(_base_assessment(hostname="beta"))
    db.store(_base_assessment(hostname="alpha"))
    assert db.hostnames() == ["alpha", "beta"]
    db.close()


# ===========================================================================
# HistoryDB – change tracking
# ===========================================================================

def test_first_snapshot_has_no_changes(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    row_id = db.store(_base_assessment())
    assert db.changes_for(row_id) == []
    db.close()


def test_unchanged_snapshot_has_no_changes(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    a = _base_assessment()
    db.store(a)
    id2 = db.store(a.copy())
    # timestamp is skipped, everything else identical
    assert db.changes_for(id2) == []
    db.close()


def test_cpu_model_change_recorded(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    a1 = _base_assessment()
    a2 = _base_assessment(
        timestamp="2024-02-01T00:00:00+00:00",
        hardware={"cpu": {"model": "Intel Xeon E-2278G", "total_cores": 8},
                  "memory": {"total_bytes": 34359738368, "ecc_enabled": True}},
    )
    db.store(a1)
    id2 = db.store(a2)
    changes = db.changes_for(id2)
    paths = {c["path"] for c in changes}
    assert "hardware.cpu.model" in paths
    assert "hardware.cpu.total_cores" in paths
    db.close()


def test_disk_added_recorded(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    a1 = _base_assessment()
    a2 = _base_assessment(
        timestamp="2024-02-01T00:00:00+00:00",
        storage={
            "disks": [
                {"name": "sda", "size_bytes": 500000000000, "smart_status": "PASSED"},
                {"name": "sdb", "size_bytes": 500000000000, "smart_status": "PASSED"},
            ]
        },
    )
    db.store(a1)
    id2 = db.store(a2)
    changes = db.changes_for(id2)
    assert any("disk" in c["path"] or "storage" in c["path"] for c in changes)
    db.close()


def test_changes_for_unknown_id_returns_empty(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    assert db.changes_for(999) == []
    db.close()


# ===========================================================================
# _compute_changes unit tests
# ===========================================================================

def test_compute_changes_scalar():
    old = {"hardware": {"cpu": {"model": "old"}}}
    new = {"hardware": {"cpu": {"model": "new"}}}
    changes = _compute_changes(old, new)
    assert any(c[0] == "hardware.cpu.model" for c in changes)


def test_compute_changes_skip_timestamp():
    old = {"timestamp": "2024-01-01T00:00:00+00:00", "hostname": "h"}
    new = {"timestamp": "2024-02-01T00:00:00+00:00", "hostname": "h"}
    changes = _compute_changes(old, new)
    assert changes == []


def test_compute_changes_added_key():
    old = {"hardware": {}}
    new = {"hardware": {"cpu": {"model": "X"}}}
    changes = _compute_changes(old, new)
    assert any("cpu" in c[0] for c in changes)


def test_compute_changes_removed_key():
    old = {"hardware": {"cpu": {"model": "X"}}}
    new = {"hardware": {}}
    changes = _compute_changes(old, new)
    assert any("cpu" in c[0] for c in changes)


# ===========================================================================
# diff engine
# ===========================================================================

def test_diff_no_changes():
    a = _base_assessment()
    assert diff_assessments(a, a) == []


def test_diff_scalar_changed():
    a1 = _base_assessment()
    a2 = _base_assessment()
    a2["hardware"]["cpu"]["model"] = "AMD EPYC 7302"
    changes = diff_assessments(a1, a2)
    assert any(c.path == "hardware.cpu.model" and c.kind == "changed" for c in changes)


def test_diff_field_added():
    a1 = _base_assessment()
    a2 = _base_assessment()
    a2["hardware"]["cpu"]["max_freq_mhz"] = 4600
    changes = diff_assessments(a1, a2)
    assert any(c.path == "hardware.cpu.max_freq_mhz" and c.kind == "added" for c in changes)


def test_diff_field_removed():
    a1 = _base_assessment()
    a2 = _base_assessment()
    del a2["hardware"]["cpu"]["total_cores"]
    changes = diff_assessments(a1, a2)
    assert any(c.path == "hardware.cpu.total_cores" and c.kind == "removed" for c in changes)


def test_diff_skips_timestamp():
    a1 = _base_assessment(timestamp="2024-01-01T00:00:00+00:00")
    a2 = _base_assessment(timestamp="2024-06-01T00:00:00+00:00")
    assert diff_assessments(a1, a2) == []


def test_format_diff_no_changes():
    assert format_diff([]) == "No changes detected."


def test_format_diff_shows_path():
    c = Change(path="hardware.cpu.model", old_value="old", new_value="new", kind="changed")
    output = format_diff([c])
    assert "hardware.cpu.model" in output
    assert "old" in output
    assert "new" in output


def test_change_summary_added():
    c = Change(path="hardware.cpu.flags", old_value=None, new_value=["avx2"], kind="added")
    assert c.summary().startswith("+")


def test_change_summary_removed():
    c = Change(path="hardware.cpu.flags", old_value=["avx2"], new_value=None, kind="removed")
    assert c.summary().startswith("-")


def test_change_summary_changed():
    c = Change(path="hardware.cpu.model", old_value="old", new_value="new", kind="changed")
    assert "→" in c.summary()


# ===========================================================================
# CLI – store / history / diff
# ===========================================================================

def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data))


def test_cli_store(tmp_path):
    f = tmp_path / "a.json"
    _write_json(f, _base_assessment())
    db = tmp_path / "h.db"
    parser = build_parser()
    args = parser.parse_args(["store", "--input", str(f), "--db", str(db)])
    assert cmd_store(args) == 0
    assert db.exists()


def test_cli_store_creates_record(tmp_path):
    f = tmp_path / "a.json"
    _write_json(f, _base_assessment())
    db_path = tmp_path / "h.db"
    parser = build_parser()
    args = parser.parse_args(["store", "--input", str(f), "--db", str(db_path)])
    cmd_store(args)
    db = HistoryDB(db_path)
    assert len(db.list_assessments()) == 1
    db.close()


def test_cli_history_empty(tmp_path, capsys):
    db_path = tmp_path / "h.db"
    HistoryDB(db_path).close()  # create empty db
    parser = build_parser()
    args = parser.parse_args(["history", "--db", str(db_path)])
    rc = cmd_history(args)
    assert rc == 0
    assert "No assessments" in capsys.readouterr().out


def test_cli_history_lists_rows(tmp_path, capsys):
    db_path = tmp_path / "h.db"
    db = HistoryDB(db_path)
    db.store(_base_assessment())
    db.close()
    parser = build_parser()
    args = parser.parse_args(["history", "--db", str(db_path)])
    cmd_history(args)
    out = capsys.readouterr().out
    assert "pve01.lab" in out


def test_cli_diff_identical(tmp_path, capsys):
    db_path = tmp_path / "h.db"
    db = HistoryDB(db_path)
    id1 = db.store(_base_assessment(timestamp="2024-01-01T00:00:00+00:00"))
    id2 = db.store(_base_assessment(timestamp="2024-02-01T00:00:00+00:00"))
    db.close()
    parser = build_parser()
    args = parser.parse_args(["diff", "--db", str(db_path), "--id1", str(id1), "--id2", str(id2)])
    rc = cmd_diff(args)
    assert rc == 0
    assert "No changes" in capsys.readouterr().out


def test_cli_diff_with_changes(tmp_path, capsys):
    db_path = tmp_path / "h.db"
    a1 = _base_assessment(timestamp="2024-01-01T00:00:00+00:00")
    a2 = _base_assessment(timestamp="2024-02-01T00:00:00+00:00")
    a2["hardware"]["cpu"]["model"] = "AMD EPYC 7302"
    db = HistoryDB(db_path)
    id1 = db.store(a1)
    id2 = db.store(a2)
    db.close()
    parser = build_parser()
    args = parser.parse_args(["diff", "--db", str(db_path), "--id1", str(id1), "--id2", str(id2)])
    cmd_diff(args)
    out = capsys.readouterr().out
    assert "hardware.cpu.model" in out


def test_cli_diff_missing_id(tmp_path, capsys):
    db_path = tmp_path / "h.db"
    HistoryDB(db_path).close()
    parser = build_parser()
    args = parser.parse_args(["diff", "--db", str(db_path), "--id1", "1", "--id2", "2"])
    rc = cmd_diff(args)
    assert rc == 1
