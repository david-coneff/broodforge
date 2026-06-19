"""
Tests for migration_manager.py and bootstrap_state.py (Phase 1.N).

Covers:
  - SchemaVersion parsing and comparison (YYYY-MM-DD_HH-MM-SS_hash format + "initial" sentinel)
  - discover_migrations() — filtering, ordering, bad filenames
  - read_schema_version() — present/absent/invalid
  - load_migration() — valid module, missing run(), bad file
  - run_migrations() — nothing-to-do, single, multi, failure, dry-run
  - append_migration_log()
  - migrate_initial__to__2026-06-09_00-00-00_0000000 migration script itself
  - bootstrap_state.py — load_bootstrap_state(), schema_version warning

Run: pytest tests/unit/test_migration_manager.py -v
"""

import importlib.util
import json
import sys
import tempfile
import textwrap
import unittest
import warnings
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_REPO = REPO_ROOT / "proxmox-bootstrap"
MIGRATIONS_DIR = REPO_ROOT / "migrations"

# Version strings used throughout these tests
_V_INITIAL = "initial"
_V_BASELINE = "2026-06-09_00-00-00_0000000"   # first real schema version
_V_A = "2026-06-01_00-00-00_aaaaaaa"           # "older" test version
_V_B = "2026-06-09_00-00-00_bbbbbbb"           # "newer" test version
_V_FUTURE = "2099-01-01_00-00-00_fffffff"       # far-future version for warning tests


def _import(filename: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, BOOTSTRAP_REPO / filename
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod  # required so @dataclass can resolve cls.__module__
    spec.loader.exec_module(mod)
    return mod


def _import_migration(filename: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, MIGRATIONS_DIR / filename
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod  # required so @dataclass can resolve cls.__module__
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# TestSchemaVersion
# ---------------------------------------------------------------------------

class TestSchemaVersion(unittest.TestCase):
    def setUp(self):
        self.mm = _import("migration_manager.py", "migration_manager")

    def test_parse_valid(self):
        v = self.mm.SchemaVersion.parse(_V_BASELINE)
        self.assertEqual(str(v), _V_BASELINE)

    def test_parse_initial(self):
        v = self.mm.SchemaVersion.parse("initial")
        self.assertEqual(str(v), "initial")

    def test_str_round_trip(self):
        v = self.mm.SchemaVersion.parse(_V_A)
        self.assertEqual(str(v), _V_A)

    def test_ordering_less_than(self):
        v_old = self.mm.SchemaVersion.parse(_V_A)
        v_new = self.mm.SchemaVersion.parse(_V_B)
        self.assertLess(v_old, v_new)

    def test_ordering_equal(self):
        v1 = self.mm.SchemaVersion.parse(_V_BASELINE)
        v2 = self.mm.SchemaVersion.parse(_V_BASELINE)
        self.assertEqual(v1, v2)

    def test_ordering_time_component(self):
        v_morning = self.mm.SchemaVersion.parse("2026-06-09_08-00-00_aaaaaaa")
        v_afternoon = self.mm.SchemaVersion.parse("2026-06-09_14-30-00_bbbbbbb")
        self.assertLess(v_morning, v_afternoon)

    def test_initial_sorts_before_any_real_version(self):
        v_initial = self.mm.SchemaVersion.parse("initial")
        v_first = self.mm.SchemaVersion.parse(_V_BASELINE)
        self.assertLess(v_initial, v_first)

    def test_initial_sorts_before_old_version(self):
        v_initial = self.mm.SchemaVersion.parse("initial")
        v_a = self.mm.SchemaVersion.parse(_V_A)
        self.assertLess(v_initial, v_a)

    def test_initial_equal_to_initial(self):
        v1 = self.mm.SchemaVersion.parse("initial")
        v2 = self.mm.SchemaVersion.parse("initial")
        self.assertEqual(v1, v2)

    def test_le(self):
        v_old = self.mm.SchemaVersion.parse(_V_A)
        v_new = self.mm.SchemaVersion.parse(_V_B)
        self.assertLessEqual(v_old, v_new)
        self.assertLessEqual(v_old, v_old)

    def test_ge(self):
        v_old = self.mm.SchemaVersion.parse(_V_A)
        v_new = self.mm.SchemaVersion.parse(_V_B)
        self.assertGreaterEqual(v_new, v_old)
        self.assertGreaterEqual(v_old, v_old)

    def test_hash_usable_in_set(self):
        v1 = self.mm.SchemaVersion.parse(_V_BASELINE)
        v2 = self.mm.SchemaVersion.parse(_V_BASELINE)
        self.assertEqual(len({v1, v2}), 1)

    def test_parse_invalid_single_part(self):
        with self.assertRaises(ValueError):
            self.mm.SchemaVersion.parse("1")

    def test_parse_invalid_too_few_underscores(self):
        with self.assertRaises(ValueError):
            self.mm.SchemaVersion.parse("20260609_0000000")

    def test_parse_invalid_date_length(self):
        # Date "2026-6-9" is only 7 chars, not 10
        with self.assertRaises(ValueError):
            self.mm.SchemaVersion.parse("2026-6-9_00-00-00_0000000")

    def test_parse_invalid_time_length(self):
        # Time "0-0-0" is only 5 chars, not 8
        with self.assertRaises(ValueError):
            self.mm.SchemaVersion.parse("2026-06-09_0-0-0_0000000")

    def test_parse_invalid_non_numeric_date(self):
        with self.assertRaises(ValueError):
            self.mm.SchemaVersion.parse("XXXX-XX-XX_00-00-00_0000000")

    def test_parse_invalid_non_numeric_time(self):
        with self.assertRaises(ValueError):
            self.mm.SchemaVersion.parse("2026-06-09_HH-MM-SS_0000000")

    def test_repr(self):
        v = self.mm.SchemaVersion.parse(_V_BASELINE)
        self.assertIn(_V_BASELINE, repr(v))


# ---------------------------------------------------------------------------
# TestDiscoverMigrations
# ---------------------------------------------------------------------------

class TestDiscoverMigrations(unittest.TestCase):
    def setUp(self):
        self.mm = _import("migration_manager.py", "migration_manager")

    def _make_dir(self, tmpdir: Path, names: list[str]) -> Path:
        mdir = tmpdir / "migrations"
        mdir.mkdir()
        for name in names:
            (mdir / name).touch()
        return mdir

    def _mig(self, from_v: str, to_v: str) -> str:
        """Build a migration filename with the double-underscore separator."""
        return f"migrate_{from_v}__to__{to_v}.py"

    def test_discovers_pending_scripts(self):
        with tempfile.TemporaryDirectory() as td:
            mdir = self._make_dir(Path(td), [
                self._mig(_V_INITIAL, _V_A),
                self._mig(_V_A, _V_B),
            ])
            current = self.mm.SchemaVersion.parse(_V_INITIAL)
            results = self.mm.discover_migrations(mdir, current)
            self.assertEqual(len(results), 2)
            from_v, to_v, path = results[0]
            self.assertEqual(str(from_v), _V_INITIAL)
            self.assertEqual(str(to_v), _V_A)

    def test_skips_already_applied(self):
        with tempfile.TemporaryDirectory() as td:
            mdir = self._make_dir(Path(td), [
                self._mig(_V_INITIAL, _V_A),
                self._mig(_V_A, _V_B),
            ])
            current = self.mm.SchemaVersion.parse(_V_A)
            results = self.mm.discover_migrations(mdir, current)
            self.assertEqual(len(results), 1)
            from_v, _, _ = results[0]
            self.assertEqual(str(from_v), _V_A)

    def test_sorted_order(self):
        with tempfile.TemporaryDirectory() as td:
            # Create in reverse order to verify sort
            mdir = self._make_dir(Path(td), [
                self._mig(_V_A, _V_B),
                self._mig(_V_INITIAL, _V_A),
            ])
            current = self.mm.SchemaVersion.parse(_V_INITIAL)
            results = self.mm.discover_migrations(mdir, current)
            self.assertEqual(str(results[0][0]), _V_INITIAL)
            self.assertEqual(str(results[1][0]), _V_A)

    def test_skips_bad_filename_no_double_underscore(self):
        with tempfile.TemporaryDirectory() as td:
            # Old-style "migrate_a_to_b.py" won't match the new glob "migrate_*__to__*.py"
            mdir = self._make_dir(Path(td), [
                "migrate_bad.py",
                self._mig(_V_INITIAL, _V_BASELINE),
            ])
            current = self.mm.SchemaVersion.parse(_V_INITIAL)
            results = self.mm.discover_migrations(mdir, current)
            self.assertEqual(len(results), 1)

    def test_skips_bad_version_in_filename(self):
        with tempfile.TemporaryDirectory() as td:
            # Matches glob but has unparseable version strings
            mdir = self._make_dir(Path(td), [
                "migrate_bad__to__also-bad.py",
                self._mig(_V_INITIAL, _V_BASELINE),
            ])
            current = self.mm.SchemaVersion.parse(_V_INITIAL)
            results = self.mm.discover_migrations(mdir, current)
            self.assertEqual(len(results), 1)

    def test_missing_dir_returns_empty(self):
        mdir = Path("/nonexistent/migrations")
        current = self.mm.SchemaVersion.parse(_V_INITIAL)
        results = self.mm.discover_migrations(mdir, current)
        self.assertEqual(results, [])

    def test_empty_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            mdir = Path(td) / "migrations"
            mdir.mkdir()
            current = self.mm.SchemaVersion.parse(_V_INITIAL)
            results = self.mm.discover_migrations(mdir, current)
            self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# TestReadSchemaVersion
# ---------------------------------------------------------------------------

class TestReadSchemaVersion(unittest.TestCase):
    def setUp(self):
        self.mm = _import("migration_manager.py", "migration_manager")

    def _write_state(self, tmpdir: Path, state: dict) -> Path:
        f = tmpdir / "bootstrap-state.json"
        with open(f, "w") as fh:
            json.dump(state, fh)
        return f

    def test_reads_existing_version(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"schema_version": _V_BASELINE})
            v = self.mm.read_schema_version(Path(td))
            self.assertEqual(str(v), _V_BASELINE)

    def test_reads_initial_sentinel(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"schema_version": "initial"})
            v = self.mm.read_schema_version(Path(td))
            self.assertEqual(str(v), "initial")

    def test_defaults_to_initial_when_field_absent(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"host_identity": {}})
            v = self.mm.read_schema_version(Path(td))
            self.assertEqual(str(v), "initial")

    def test_defaults_to_initial_when_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            v = self.mm.read_schema_version(Path(td))
            self.assertEqual(str(v), "initial")

    def test_raises_on_invalid_version(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"schema_version": "bad"})
            with self.assertRaises(RuntimeError):
                self.mm.read_schema_version(Path(td))


# ---------------------------------------------------------------------------
# TestLoadMigration
# ---------------------------------------------------------------------------

class TestLoadMigration(unittest.TestCase):
    def setUp(self):
        self.mm = _import("migration_manager.py", "migration_manager")

    def _write_script(self, tmpdir: Path, name: str, content: str) -> Path:
        p = tmpdir / name
        p.write_text(textwrap.dedent(content))
        return p

    def test_loads_valid_module(self):
        with tempfile.TemporaryDirectory() as td:
            script = self._write_script(
                Path(td),
                f"migrate_{_V_INITIAL}__to__{_V_BASELINE}.py",
                """\
                def run(state_dir: str) -> None:
                    pass
            """)
            mod = self.mm.load_migration(script)
            self.assertTrue(callable(mod.run))

    def test_raises_on_missing_run(self):
        with tempfile.TemporaryDirectory() as td:
            script = self._write_script(
                Path(td),
                f"migrate_{_V_INITIAL}__to__{_V_BASELINE}.py",
                """\
                def not_run(): pass
            """)
            with self.assertRaises(AttributeError):
                self.mm.load_migration(script)


# ---------------------------------------------------------------------------
# TestRunMigrations
# ---------------------------------------------------------------------------

class TestRunMigrations(unittest.TestCase):
    def setUp(self):
        self.mm = _import("migration_manager.py", "migration_manager")

    def _fixed_clock(self, ts: str = "2026-06-09T00:00:00Z"):
        dt = datetime(2026, 6, 9, tzinfo=timezone.utc)
        return lambda: dt

    def _setup(self, tmpdir: Path, state: dict, scripts: dict[str, str]) -> tuple[Path, Path]:
        state_dir = tmpdir / "state"
        state_dir.mkdir()
        (state_dir / "bootstrap-state.json").write_text(json.dumps(state))

        migrations_dir = tmpdir / "migrations"
        migrations_dir.mkdir()
        for name, content in scripts.items():
            (migrations_dir / name).write_text(textwrap.dedent(content))

        return state_dir, migrations_dir

    def test_nothing_to_do(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir, migrations_dir = self._setup(
                Path(td),
                {"schema_version": _V_BASELINE},
                {},
            )
            ok = self.mm.run_migrations(state_dir, migrations_dir, clock=self._fixed_clock())
            self.assertTrue(ok)

    def test_single_migration_applied(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir, migrations_dir = self._setup(
                Path(td),
                {"schema_version": "initial"},
                {
                    f"migrate_{_V_INITIAL}__to__{_V_BASELINE}.py": f"""\
                        import json
                        from pathlib import Path
                        def run(state_dir):
                            p = Path(state_dir) / "bootstrap-state.json"
                            s = json.loads(p.read_text())
                            s["schema_version"] = "{_V_BASELINE}"
                            p.write_text(json.dumps(s))
                    """
                },
            )
            ok = self.mm.run_migrations(state_dir, migrations_dir, clock=self._fixed_clock())
            self.assertTrue(ok)
            with open(state_dir / "bootstrap-state.json") as fh:
                state = json.load(fh)
            self.assertEqual(state["schema_version"], _V_BASELINE)

    def test_migration_failure_stops_chain(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir, migrations_dir = self._setup(
                Path(td),
                {"schema_version": "initial"},
                {
                    f"migrate_{_V_INITIAL}__to__{_V_A}.py": """\
                        def run(state_dir):
                            raise RuntimeError("intentional failure")
                    """,
                    f"migrate_{_V_A}__to__{_V_B}.py": """\
                        def run(state_dir):
                            pass  # should not run
                    """,
                },
            )
            ok = self.mm.run_migrations(state_dir, migrations_dir, clock=self._fixed_clock())
            self.assertFalse(ok)

    def test_dry_run_does_not_modify_state(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir, migrations_dir = self._setup(
                Path(td),
                {"schema_version": "initial"},
                {
                    f"migrate_{_V_INITIAL}__to__{_V_BASELINE}.py": f"""\
                        import json
                        from pathlib import Path
                        def run(state_dir):
                            p = Path(state_dir) / "bootstrap-state.json"
                            s = json.loads(p.read_text())
                            s["schema_version"] = "{_V_BASELINE}"
                            p.write_text(json.dumps(s))
                    """
                },
            )
            ok = self.mm.run_migrations(
                state_dir, migrations_dir, dry_run=True, clock=self._fixed_clock()
            )
            self.assertTrue(ok)
            with open(state_dir / "bootstrap-state.json") as fh:
                state = json.load(fh)
            # State must not have been modified in dry-run mode
            self.assertEqual(state["schema_version"], "initial")

    def test_migration_log_written_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir, migrations_dir = self._setup(
                Path(td),
                {"schema_version": "initial"},
                {
                    f"migrate_{_V_INITIAL}__to__{_V_BASELINE}.py": f"""\
                        import json
                        from pathlib import Path
                        def run(state_dir):
                            p = Path(state_dir) / "bootstrap-state.json"
                            s = json.loads(p.read_text())
                            s["schema_version"] = "{_V_BASELINE}"
                            p.write_text(json.dumps(s))
                    """
                },
            )
            self.mm.run_migrations(state_dir, migrations_dir, clock=self._fixed_clock())
            log_path = state_dir / "migration-history.jsonl"
            self.assertTrue(log_path.exists())
            record = json.loads(log_path.read_text().strip())
            self.assertTrue(record["success"])
            self.assertEqual(record["from_version"], "initial")
            self.assertEqual(record["to_version"], _V_BASELINE)

    def test_migration_log_written_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir, migrations_dir = self._setup(
                Path(td),
                {"schema_version": "initial"},
                {
                    f"migrate_{_V_INITIAL}__to__{_V_BASELINE}.py": """\
                        def run(state_dir):
                            raise RuntimeError("oops")
                    """
                },
            )
            self.mm.run_migrations(state_dir, migrations_dir, clock=self._fixed_clock())
            log_path = state_dir / "migration-history.jsonl"
            record = json.loads(log_path.read_text().strip())
            self.assertFalse(record["success"])
            self.assertIsNotNone(record["error"])

    def test_ran_at_uses_injected_clock(self):
        """ran_at in migration log must reflect the injected clock, not wall time."""
        with tempfile.TemporaryDirectory() as td:
            state_dir, migrations_dir = self._setup(
                Path(td),
                {"schema_version": "initial"},
                {
                    f"migrate_{_V_INITIAL}__to__{_V_BASELINE}.py": f"""\
                        import json
                        from pathlib import Path
                        def run(state_dir):
                            p = Path(state_dir) / "bootstrap-state.json"
                            s = json.loads(p.read_text())
                            s["schema_version"] = "{_V_BASELINE}"
                            p.write_text(json.dumps(s))
                    """
                },
            )
            ok = self.mm.run_migrations(state_dir, migrations_dir, clock=self._fixed_clock())
            self.assertTrue(ok)
            log_path = state_dir / "migration-history.jsonl"
            record = json.loads(log_path.read_text().strip())
            self.assertEqual(record["ran_at"], "2026-06-09T00:00:00Z")


# ---------------------------------------------------------------------------
# TestAppendMigrationLog
# ---------------------------------------------------------------------------

class TestAppendMigrationLog(unittest.TestCase):
    def setUp(self):
        self.mm = _import("migration_manager.py", "migration_manager")

    def test_appends_multiple_records(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td)
            r1 = self.mm.MigrationRecord(
                from_version=_V_INITIAL,
                to_version=_V_A,
                script=f"migrate_{_V_INITIAL}__to__{_V_A}.py",
                ran_at="2026-06-01T00:00:00Z",
                success=True,
                dry_run=False,
            )
            r2 = self.mm.MigrationRecord(
                from_version=_V_A,
                to_version=_V_B,
                script=f"migrate_{_V_A}__to__{_V_B}.py",
                ran_at="2026-06-09T00:01:00Z",
                success=False,
                dry_run=False,
                error="boom",
            )
            self.mm.append_migration_log(state_dir, r1)
            self.mm.append_migration_log(state_dir, r2)
            lines = (state_dir / "migration-history.jsonl").read_text().strip().splitlines()
            self.assertEqual(len(lines), 2)
            parsed = [json.loads(ln) for ln in lines]
            self.assertTrue(parsed[0]["success"])
            self.assertFalse(parsed[1]["success"])
            self.assertEqual(parsed[1]["error"], "boom")


# ---------------------------------------------------------------------------
# TestMigrateScript_initial_to_baseline
# ---------------------------------------------------------------------------

class TestMigrateScript_initial_to_baseline(unittest.TestCase):
    def setUp(self):
        self.migration = _import_migration(
            f"migrate_{_V_INITIAL}__to__{_V_BASELINE}.py",
            "migrate_initial_to_baseline",
        )

    def _write_state(self, tmpdir: Path, state: dict) -> Path:
        f = tmpdir / "bootstrap-state.json"
        with open(f, "w") as fh:
            json.dump(state, fh, indent=2)
        return f

    def test_adds_schema_version(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"host_identity": {"hostname": "pve01"}})
            self.migration.run(td)
            with open(Path(td) / "bootstrap-state.json") as fh:
                state = json.load(fh)
            self.assertEqual(state["schema_version"], _V_BASELINE)

    def test_idempotent_when_already_at_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"schema_version": _V_BASELINE, "host_identity": {}})
            self.migration.run(td)
            with open(Path(td) / "bootstrap-state.json") as fh:
                state = json.load(fh)
            self.assertEqual(state["schema_version"], _V_BASELINE)

    def test_stamps_initial_sentinel(self):
        """State that has schema_version="initial" should also be stamped."""
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"schema_version": "initial", "host_identity": {}})
            self.migration.run(td)
            with open(Path(td) / "bootstrap-state.json") as fh:
                state = json.load(fh)
            self.assertEqual(state["schema_version"], _V_BASELINE)

    def test_preserves_existing_fields(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(
                Path(td),
                {"cell_id": "cell-01", "host_identity": {"hostname": "pve01"}}
            )
            self.migration.run(td)
            with open(Path(td) / "bootstrap-state.json") as fh:
                state = json.load(fh)
            self.assertEqual(state["cell_id"], "cell-01")
            self.assertEqual(state["host_identity"]["hostname"], "pve01")

    def test_raises_when_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                self.migration.run(td)


# ---------------------------------------------------------------------------
# TestBootstrapState
# ---------------------------------------------------------------------------

class TestBootstrapState(unittest.TestCase):
    def setUp(self):
        self.bs = _import("bootstrap_state.py", "bootstrap_state")

    def _write_state(self, tmpdir: Path, state: dict) -> Path:
        f = tmpdir / "bootstrap-state.json"
        with open(f, "w") as fh:
            json.dump(state, fh)
        return f

    def test_loads_valid_state(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"schema_version": _V_BASELINE, "cell_id": "c01"})
            result = self.bs.load_bootstrap_state(Path(td))
            self.assertEqual(result.schema_version, _V_BASELINE)
            self.assertEqual(result.get("cell_id"), "c01")

    def test_accepts_path_to_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._write_state(Path(td), {"schema_version": _V_BASELINE})
            result = self.bs.load_bootstrap_state(p)
            self.assertEqual(result.schema_version, _V_BASELINE)

    def test_defaults_version_when_absent(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"cell_id": "c01"})
            result = self.bs.load_bootstrap_state(Path(td))
            self.assertEqual(result.schema_version, "initial")

    def test_warns_on_future_schema(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"schema_version": _V_FUTURE})
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self.bs.load_bootstrap_state(Path(td))
            self.assertTrue(any(_V_FUTURE in str(w.message) for w in caught))

    def test_no_warning_on_current_schema(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"schema_version": self.bs.CURRENT_SCHEMA_VERSION})
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self.bs.load_bootstrap_state(Path(td))
            schema_warns = [w for w in caught if issubclass(w.category, UserWarning)]
            self.assertEqual(len(schema_warns), 0)

    def test_raises_file_not_found(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                self.bs.load_bootstrap_state(Path(td))

    def test_allow_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.bs.load_bootstrap_state(Path(td), allow_missing=True)
            self.assertEqual(result.schema_version, "initial")
            self.assertEqual(result.raw, {})

    def test_contains_operator(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"schema_version": _V_BASELINE, "cell_id": "c01"})
            result = self.bs.load_bootstrap_state(Path(td))
            self.assertIn("cell_id", result)
            self.assertNotIn("nonexistent", result)

    def test_raises_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "bootstrap-state.json").write_text("{invalid json")
            with self.assertRaises(ValueError):
                self.bs.load_bootstrap_state(Path(td))

    def test_raises_on_invalid_schema_version_format(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_state(Path(td), {"schema_version": "not-valid"})
            with self.assertRaises(ValueError):
                self.bs.load_bootstrap_state(Path(td))


# ---------------------------------------------------------------------------
# TestMigrationManagerCLI
# ---------------------------------------------------------------------------

class TestMigrationManagerCLI(unittest.TestCase):
    def setUp(self):
        self.mm = _import("migration_manager.py", "migration_manager")

    def test_main_nothing_to_do(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir()
            (state_dir / "bootstrap-state.json").write_text(
                json.dumps({"schema_version": _V_BASELINE})
            )
            # AD-065: migration.lock required (created by forge-quiesce.sh in production)
            (state_dir / "migration.lock").write_text(
                json.dumps({"locked_at": "2026-06-09T00:00:00Z", "pid": "1", "reason": "migration"})
            )
            migrations_dir = Path(td) / "migrations"
            migrations_dir.mkdir()
            rc = self.mm.main([
                "--state-dir", str(state_dir),
                "--migrations-dir", str(migrations_dir),
            ])
            self.assertEqual(rc, 0)

    def test_main_missing_state_dir(self):
        rc = self.mm.main([])
        self.assertEqual(rc, 1)

    def test_main_nonexistent_state_dir(self):
        rc = self.mm.main(["--state-dir", "/nonexistent/path"])
        self.assertEqual(rc, 1)

    def test_main_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            state_dir = Path(td) / "state"
            state_dir.mkdir()
            (state_dir / "bootstrap-state.json").write_text(
                json.dumps({"schema_version": "initial"})
            )
            # AD-065: migration.lock required (created by forge-quiesce.sh in production)
            (state_dir / "migration.lock").write_text(
                json.dumps({"locked_at": "2026-06-09T00:00:00Z", "pid": "1", "reason": "migration"})
            )
            migrations_dir = Path(td) / "migrations"
            migrations_dir.mkdir()
            (migrations_dir / f"migrate_{_V_INITIAL}__to__{_V_BASELINE}.py").write_text(
                textwrap.dedent(f"""\
                    import json, pathlib
                    def run(state_dir):
                        p = pathlib.Path(state_dir) / "bootstrap-state.json"
                        s = json.loads(p.read_text())
                        s["schema_version"] = "{_V_BASELINE}"
                        p.write_text(json.dumps(s))
                """)
            )
            rc = self.mm.main([
                "--state-dir", str(state_dir),
                "--migrations-dir", str(migrations_dir),
                "--dry-run",
            ])
            self.assertEqual(rc, 0)
            # State must not change in dry-run
            state = json.loads((state_dir / "bootstrap-state.json").read_text())
            self.assertEqual(state["schema_version"], "initial")


if __name__ == "__main__":
    unittest.main()
