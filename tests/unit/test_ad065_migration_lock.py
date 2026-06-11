"""
test_ad065_migration_lock.py — AD-065 enforcement: migration_manager.py must
refuse to run if migration.lock is absent in the state directory.

Requirement (AD-065): No autonomous pathway may initiate migration.
forge-quiesce.sh creates migration.lock *and* calls forge_keepass_gate() to
enforce operator presence before any timer stop or lock creation.
migration_manager.py must verify the lock exists before executing any
migrations — otherwise direct invocation bypasses the gate entirely.

Run:
    pytest tests/unit/test_ad065_migration_lock.py -v
"""

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_REPO = REPO_ROOT / "proxmox-bootstrap"


def _import_mm():
    """Import migration_manager.py as a module (isolated per test)."""
    spec = importlib.util.spec_from_file_location(
        "_migration_manager_ad065", BOOTSTRAP_REPO / "migration_manager.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_state(state_dir: Path, schema_version: str = "initial") -> None:
    """Write a minimal bootstrap-state.json to state_dir."""
    state = {"schema_version": schema_version, "cell_id": "test-cell-ad065"}
    (state_dir / "bootstrap-state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )


def _write_lock(state_dir: Path) -> None:
    """Write a migration.lock as forge-quiesce.sh would."""
    lock = json.dumps(
        {"locked_at": "2026-06-09T00:00:00Z", "pid": "12345", "reason": "migration"}
    )
    (state_dir / "migration.lock").write_text(lock, encoding="utf-8")


class TestAD065MigrationLockEnforcement(unittest.TestCase):
    """
    AD-065: migration_manager.py must refuse to run without migration.lock.

    All tests call migration_manager.main() directly — the same path an
    autonomous or operator-initiated-but-ungated invocation would take.
    """

    def test_exits_nonzero_without_lock_file(self):
        """
        Direct invocation without migration.lock must exit non-zero.

        This is the primary AD-065 enforcement test: confirms that calling
        migration_manager.py without first running forge-quiesce.sh is
        rejected before any migration logic runs.
        """
        mm = _import_mm()
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            _write_state(state_dir)
            # Explicitly confirm no lock exists
            self.assertFalse((state_dir / "migration.lock").exists())
            rc = mm.main(["--state-dir", str(state_dir)])
            self.assertNotEqual(
                rc, 0,
                "migration_manager.main() must return non-zero when migration.lock is absent",
            )

    def test_proceeds_with_lock_file_nothing_to_migrate(self):
        """
        When migration.lock exists and state is current, main() must return 0.

        Verifies the lock check does not block legitimate gated invocations.
        Uses a state dir with no pending migrations so only the lock-check
        and version-check paths are exercised.
        """
        mm = _import_mm()
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            _write_state(state_dir, schema_version=mm.CURRENT_SCHEMA_VERSION)
            _write_lock(state_dir)
            rc = mm.main(["--state-dir", str(state_dir)])
            self.assertEqual(
                rc, 0,
                "migration_manager.main() must return 0 when lock exists and nothing to migrate",
            )

    def test_dry_run_also_requires_lock(self):
        """
        --dry-run must not bypass the migration.lock requirement.

        AD-065 applies equally to dry-run invocations: the KeePass gate is
        about operator presence, not about whether state will be mutated.
        """
        mm = _import_mm()
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            _write_state(state_dir)
            rc = mm.main(["--state-dir", str(state_dir), "--dry-run"])
            self.assertNotEqual(
                rc, 0,
                "--dry-run must still require migration.lock (AD-065 gate is not bypassed by dry-run)",
            )

    def test_error_message_mentions_quiesce_and_ad065(self):
        """
        The error output when lock is absent must reference forge-quiesce.sh
        and AD-065 so the operator knows exactly what to run.
        """
        mm = _import_mm()
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            _write_state(state_dir)
            captured = io.StringIO()
            old_stderr = sys.stderr
            sys.stderr = captured
            try:
                mm.main(["--state-dir", str(state_dir)])
            finally:
                sys.stderr = old_stderr
            err = captured.getvalue()
            self.assertIn(
                "forge-quiesce.sh", err,
                "Error message must name forge-quiesce.sh so operator knows what to run",
            )
            self.assertIn(
                "AD-065", err,
                "Error message must cite AD-065 so auditors can trace the requirement",
            )

    def test_lock_check_occurs_before_migration_execution(self):
        """
        The lock check must fire even when migrations are pending.

        Creates a well-formed pending migration script to confirm the lock
        check is not deferred until after migration discovery.
        """
        import textwrap
        mm = _import_mm()
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            migrations_dir = Path(tmp) / "migrations"
            migrations_dir.mkdir()
            # Write a migration script that would run if the lock check were absent
            script = migrations_dir / "migrate_initial__to__2099-01-01_00-00-00_fffffff.py"
            script.write_text(
                textwrap.dedent("""\
                    def run(state_dir):
                        raise RuntimeError("Lock check failed — migration ran without quiesce")
                """),
                encoding="utf-8",
            )
            _write_state(state_dir, schema_version="initial")
            # No lock file — must refuse before executing the migration
            rc = mm.main([
                "--state-dir", str(state_dir),
                "--migrations-dir", str(migrations_dir),
            ])
            self.assertNotEqual(
                rc, 0,
                "Lock check must fire before migration execution — no lock, no run",
            )


if __name__ == "__main__":
    unittest.main()
