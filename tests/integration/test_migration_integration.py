"""
tests/integration/test_migration_integration.py — F-6 fix.

Integration tests for migration_manager.py using a REAL temp directory as the
state store — no mocks.  These tests exercise the full path from
read_schema_version → discover_migrations → run_migrations → migration log
write, verifying that the state store is mutated on disk exactly as expected.
"""

from __future__ import annotations

import json
import tempfile
import textwrap
from pathlib import Path

import pytest

# Ensure the proxmox-bootstrap package is importable regardless of cwd.
_REPO_ROOT = Path(__file__).parent.parent.parent

from migration_manager import (  # noqa: E402
    HISTORY_FILENAME,
    STATE_FILENAME,
    MigrationRecord,
    SchemaVersion,
    append_migration_log,
    discover_migrations,
    read_schema_version,
    run_migrations,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_state(state_dir: Path, schema_version: str | None) -> None:
    """Write a minimal bootstrap-state.json to *state_dir*."""
    data: dict = {"cell_id": "test-cell"}
    if schema_version is not None:
        data["schema_version"] = schema_version
    (state_dir / STATE_FILENAME).write_text(json.dumps(data, indent=2))


def _read_state(state_dir: Path) -> dict:
    return json.loads((state_dir / STATE_FILENAME).read_text())


def _write_migration(migrations_dir: Path, from_ver: str, to_ver: str, body: str = "") -> Path:
    """Write a minimal migration script and return its path."""
    fname = f"migrate_{from_ver}__to__{to_ver}.py"
    script = migrations_dir / fname
    if not body:
        body = textwrap.dedent(f"""\
            import json, os
            from pathlib import Path
            _TARGET = {to_ver!r}
            def run(state_dir):
                p = Path(state_dir) / "bootstrap-state.json"
                if not p.exists():
                    return
                d = json.loads(p.read_text())
                d["schema_version"] = _TARGET
                tmp = p.with_suffix(".tmp")
                tmp.write_text(json.dumps(d, indent=2))
                os.replace(tmp, p)
        """)
    script.write_text(body)
    return script


def _lock(state_dir: Path) -> None:
    """Create the migration.lock file that AD-065 requires."""
    lock = state_dir / "migration.lock"
    lock.write_text(json.dumps({"locked_at": "2026-06-10T00:00:00Z", "pid": 1, "reason": "integration-test"}))


# ---------------------------------------------------------------------------
# read_schema_version
# ---------------------------------------------------------------------------

class TestReadSchemaVersionReal:
    def test_missing_file_returns_initial(self, tmp_path):
        """No state file → version 'initial'."""
        v = read_schema_version(tmp_path)
        assert v == SchemaVersion.parse("initial")

    def test_no_version_field_returns_initial(self, tmp_path):
        """State file without schema_version field → 'initial'."""
        (tmp_path / STATE_FILENAME).write_text('{"cell_id": "x"}')
        v = read_schema_version(tmp_path)
        assert v == SchemaVersion.parse("initial")

    def test_reads_version_correctly(self, tmp_path):
        _write_state(tmp_path, "2026-06-09_00-00-00_0000000")
        v = read_schema_version(tmp_path)
        assert str(v) == "2026-06-09_00-00-00_0000000"

    def test_invalid_json_raises(self, tmp_path):
        (tmp_path / STATE_FILENAME).write_text("{ not valid json")
        with pytest.raises(RuntimeError):
            read_schema_version(tmp_path)


# ---------------------------------------------------------------------------
# discover_migrations (real filesystem)
# ---------------------------------------------------------------------------

class TestDiscoverMigrationsReal:
    def test_empty_dir_returns_empty(self, tmp_path):
        assert discover_migrations(tmp_path, SchemaVersion.parse("initial")) == []

    def test_missing_dir_returns_empty(self, tmp_path):
        absent = tmp_path / "no-such-dir"
        assert discover_migrations(absent, SchemaVersion.parse("initial")) == []

    def test_finds_pending_migration(self, tmp_path):
        _write_migration(tmp_path, "initial", "2026-06-09_00-00-00_0000000")
        pending = discover_migrations(tmp_path, SchemaVersion.parse("initial"))
        assert len(pending) == 1
        assert str(pending[0][0]) == "initial"
        assert str(pending[0][1]) == "2026-06-09_00-00-00_0000000"

    def test_already_applied_excluded(self, tmp_path):
        _write_migration(tmp_path, "initial", "2026-06-09_00-00-00_0000000")
        # Current version is the target → this migration is already done
        current = SchemaVersion.parse("2026-06-09_00-00-00_0000000")
        pending = discover_migrations(tmp_path, current)
        assert pending == []

    def test_ordering(self, tmp_path):
        _write_migration(tmp_path, "2026-06-10_00-00-00_aaaaaaa", "2026-06-11_00-00-00_bbbbbbb")
        _write_migration(tmp_path, "initial", "2026-06-09_00-00-00_0000000")
        _write_migration(tmp_path, "2026-06-09_00-00-00_0000000", "2026-06-10_00-00-00_aaaaaaa")
        pending = discover_migrations(tmp_path, SchemaVersion.parse("initial"))
        # Must run in chronological order
        assert len(pending) == 3
        assert str(pending[0][0]) == "initial"
        assert str(pending[1][0]) == "2026-06-09_00-00-00_0000000"
        assert str(pending[2][0]) == "2026-06-10_00-00-00_aaaaaaa"

    def test_invalid_filename_skipped(self, tmp_path):
        (tmp_path / "migrate_badname.py").write_text("def run(s): pass")
        _write_migration(tmp_path, "initial", "2026-06-09_00-00-00_0000000")
        pending = discover_migrations(tmp_path, SchemaVersion.parse("initial"))
        assert len(pending) == 1  # only valid script counted


# ---------------------------------------------------------------------------
# run_migrations — real state dir, real migration scripts
# ---------------------------------------------------------------------------

class TestRunMigrationsIntegration:
    """End-to-end: real temp dir as state store, real migration scripts."""

    def setup_method(self):
        self._td = tempfile.TemporaryDirectory()
        self.state_dir = Path(self._td.name) / "state"
        self.migrations_dir = Path(self._td.name) / "migrations"
        self.state_dir.mkdir()
        self.migrations_dir.mkdir()
        _lock(self.state_dir)  # AD-065 lock (run_migrations itself doesn't check; main() does)

    def teardown_method(self):
        self._td.cleanup()

    def test_nothing_to_do_returns_true(self):
        """No pending migrations → succeeds immediately."""
        _write_state(self.state_dir, "2026-06-09_00-00-00_0000000")
        ok = run_migrations(self.state_dir, self.migrations_dir)
        assert ok is True

    def test_applies_single_migration(self):
        """One pending migration is applied; state is updated on disk."""
        _write_state(self.state_dir, None)  # "initial" (no field)
        _write_migration(
            self.migrations_dir,
            "initial",
            "2026-06-09_00-00-00_0000000",
        )
        ok = run_migrations(self.state_dir, self.migrations_dir)
        assert ok is True
        state = _read_state(self.state_dir)
        assert state["schema_version"] == "2026-06-09_00-00-00_0000000"

    def test_migration_log_written(self):
        """run_migrations writes an entry to migration-history.jsonl."""
        _write_state(self.state_dir, None)
        _write_migration(
            self.migrations_dir,
            "initial",
            "2026-06-09_00-00-00_0000000",
        )
        run_migrations(self.state_dir, self.migrations_dir)
        log_path = self.state_dir / HISTORY_FILENAME
        assert log_path.exists(), "migration-history.jsonl was not created"
        lines = [ln for ln in log_path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["success"] is True
        assert entry["from_version"] == "initial"
        assert entry["to_version"] == "2026-06-09_00-00-00_0000000"
        assert entry["dry_run"] is False

    def test_dry_run_no_state_mutation(self):
        """dry_run=True: prints plan, does not write state or log."""
        _write_state(self.state_dir, None)
        _write_migration(
            self.migrations_dir,
            "initial",
            "2026-06-09_00-00-00_0000000",
        )
        ok = run_migrations(self.state_dir, self.migrations_dir, dry_run=True)
        assert ok is True
        # State file unchanged
        state = _read_state(self.state_dir)
        assert "schema_version" not in state
        # No log file written
        assert not (self.state_dir / HISTORY_FILENAME).exists()

    def test_applies_migration_chain(self):
        """Three chained migrations applied in order; final version correct."""
        _write_state(self.state_dir, None)
        _write_migration(
            self.migrations_dir,
            "initial",
            "2026-06-09_00-00-00_aaaaaaa",
        )
        _write_migration(
            self.migrations_dir,
            "2026-06-09_00-00-00_aaaaaaa",
            "2026-06-10_00-00-00_bbbbbbb",
        )
        _write_migration(
            self.migrations_dir,
            "2026-06-10_00-00-00_bbbbbbb",
            "2026-06-11_00-00-00_ccccccc",
        )
        ok = run_migrations(self.state_dir, self.migrations_dir)
        assert ok is True
        state = _read_state(self.state_dir)
        assert state["schema_version"] == "2026-06-11_00-00-00_ccccccc"
        log_path = self.state_dir / HISTORY_FILENAME
        lines = [ln for ln in log_path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 3  # one log entry per migration

    def test_halts_on_migration_failure(self):
        """If a migration raises, run_migrations returns False and stops."""
        _write_state(self.state_dir, None)
        # First migration: raises an exception
        bad_body = textwrap.dedent("""\
            def run(state_dir):
                raise RuntimeError("deliberate failure")
        """)
        _write_migration(
            self.migrations_dir,
            "initial",
            "2026-06-09_00-00-00_0000000",
            body=bad_body,
        )
        # Second migration: would set version if first hadn't failed
        _write_migration(
            self.migrations_dir,
            "2026-06-09_00-00-00_0000000",
            "2026-06-10_00-00-00_1111111",
        )
        ok = run_migrations(self.state_dir, self.migrations_dir)
        assert ok is False
        # State should not have been advanced past the failure
        state = _read_state(self.state_dir)
        assert state.get("schema_version") != "2026-06-10_00-00-00_1111111"
        # Failure is logged
        log_path = self.state_dir / HISTORY_FILENAME
        assert log_path.exists()
        entry = json.loads(log_path.read_text().splitlines()[0])
        assert entry["success"] is False
        assert "deliberate failure" in (entry.get("error") or "")

    def test_uses_real_migration_script(self):
        """Use the actual repo migration script against a real temp state dir."""
        real_migrations = _REPO_ROOT / "migrations"
        if not real_migrations.is_dir():
            pytest.skip("migrations/ directory not found in repo root")
        _write_state(self.state_dir, None)  # "initial"
        ok = run_migrations(self.state_dir, real_migrations)
        assert ok is True
        state = _read_state(self.state_dir)
        # After the real migration the state must have a valid version string
        assert "schema_version" in state
        SchemaVersion.parse(state["schema_version"])  # must not raise

    def test_idempotent_on_rerun(self):
        """Running migrations twice does not duplicate log entries."""
        _write_state(self.state_dir, None)
        _write_migration(
            self.migrations_dir,
            "initial",
            "2026-06-09_00-00-00_0000000",
        )
        run_migrations(self.state_dir, self.migrations_dir)
        run_migrations(self.state_dir, self.migrations_dir)  # second run
        log_path = self.state_dir / HISTORY_FILENAME
        lines = [ln for ln in log_path.read_text().splitlines() if ln.strip()]
        # Second run finds nothing to do → only one log entry (from first run)
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# append_migration_log — real file I/O
# ---------------------------------------------------------------------------

class TestAppendMigrationLogReal:
    def test_creates_file_if_absent(self, tmp_path):
        rec = MigrationRecord(
            from_version="initial",
            to_version="2026-06-09_00-00-00_0000000",
            script="migrate_initial__to__2026-06-09_00-00-00_0000000.py",
            ran_at="2026-06-10T00:00:00Z",
            success=True,
            dry_run=False,
        )
        append_migration_log(tmp_path, rec)
        log = tmp_path / HISTORY_FILENAME
        assert log.exists()
        entry = json.loads(log.read_text().strip())
        assert entry["success"] is True

    def test_appends_multiple_entries(self, tmp_path):
        for i in range(3):
            rec = MigrationRecord(
                from_version="initial",
                to_version=f"2026-06-0{i+1}_00-00-00_000000{i}",
                script=f"migrate_{i}.py",
                ran_at="2026-06-10T00:00:00Z",
                success=True,
                dry_run=False,
            )
            append_migration_log(tmp_path, rec)
        lines = (tmp_path / HISTORY_FILENAME).read_text().splitlines()
        assert len(lines) == 3
