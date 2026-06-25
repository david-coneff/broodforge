#!/usr/bin/env python3
"""
Tests for Phase 6.B — Backup Infrastructure.

Covers:
  - BackupNaming (all naming helpers — pure, no I/O)
  - generate_backup_passphrase (format, length, uniqueness)
  - SpaceProbe (local statvfs mock, rclone about JSON parsing)
  - ResticRunner (all methods via injected mock runner_fn)
  - RcloneRunner (copy and ls via injected mock runner_fn)
  - BackupEngine.run_secrets_backup (mocked rclone)
  - BackupEngine.run_restic_backup (mocked restic)
  - RestoreEngine.list_snapshot_sets
  - RestoreEngine.find_record_for_set
  - RestoreEngine.restore_snapshot_set (mocked restic)
  - _score_backup_config_completeness (readiness.py)
  - Recovery runbook Appendix H rendering
  - bootstrap-state-schema.json validates backup_config entries
"""

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

from backup_engine import (
    BackupEngine,
    BackupNaming,
    RcloneRunner,
    ResticRunner,
    RestoreEngine,
    SpaceInfo,
    SpaceProbe,
    generate_backup_passphrase,
)
from readiness import _score_backup_config_completeness

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

CELL_ID = "proxmox-cell-a"
TS      = "2026-06-01_03_00_00"

def _now_fixed():
    return datetime(2026, 6, 1, 3, 0, 0, tzinfo=timezone.utc)

def _mock_rclone_ok(src, dst_dir, dst_filename):
    return True, ""

def _mock_rclone_fail(src, dst_dir, dst_filename):
    return False, "connection refused"

def _minimal_backup_config(
    secrets_enabled=True,
    config_enabled=True,
    appdata_enabled=False,
    last_backup_at=None,
    consec_fail=0,
    history=None,
):
    return {
        "layers": {
            "secrets": {
                "enabled": secrets_enabled,
                "destinations": [
                    {"id": "local-usb", "type": "local",
                     "kdbx_destination_root": "/mnt/usb/secrets"},
                ],
                "last_backup_at": last_backup_at,
                "last_successful_destination_id": None,
                "consecutive_all_fail_count": consec_fail,
            },
            "config": {
                "enabled": config_enabled,
                "destinations": [
                    {"id": "local-drive", "type": "local",
                     "restic_repo_root": "/mnt/backup",
                     "restic_repo_password_keepass_prefix": "Backup/config",
                     "retention_count": 5},
                ],
                "last_backup_at": last_backup_at,
                "last_successful_destination_id": None,
                "consecutive_all_fail_count": consec_fail,
            },
            "appdata": {
                "enabled": appdata_enabled,
                "destinations": [],
                "last_backup_at": None,
                "last_successful_destination_id": None,
                "consecutive_all_fail_count": 0,
            },
        },
        "checkpoint_tag": "checkpoint",
        "all_failed_policy": ["alert", "block_assessment"],
        "backup_history": history or [],
    }


# ---------------------------------------------------------------------------
# BackupNaming
# ---------------------------------------------------------------------------

class TestBackupNaming(unittest.TestCase):

    def test_kdbx_prefix(self):
        self.assertEqual(BackupNaming.kdbx_prefix(), "kdbx")

    def test_cell_config_prefix(self):
        self.assertEqual(BackupNaming.cell_config_prefix(), "cell-config")

    def test_node_prefix(self):
        self.assertEqual(BackupNaming.node_prefix("pve01"), "node-pve01")

    def test_vm_prefix(self):
        self.assertEqual(BackupNaming.vm_prefix("forgejo", 101), "vm-forgejo-101")

    def test_ct_prefix(self):
        self.assertEqual(BackupNaming.ct_prefix("postgresql", 200), "ct-postgresql-200")

    def test_vol_prefix(self):
        self.assertEqual(BackupNaming.vol_prefix("nextcloud", "data"), "vol-nextcloud-data")

    def test_svc_prefix(self):
        self.assertEqual(BackupNaming.svc_prefix("immich"), "svc-immich")

    def test_repo_path_structure(self):
        path = BackupNaming.repo_path(
            "b2:my-bucket", CELL_ID, "config", "vm-forgejo-101"
        )
        self.assertEqual(path, "b2:my-bucket/proxmox-cell-a/config/vm-forgejo-101")

    def test_repo_path_strips_trailing_slash(self):
        path = BackupNaming.repo_path("/mnt/backup/", CELL_ID, "config", "cell-config")
        self.assertFalse(path.startswith("/mnt/backup//"))
        self.assertIn(CELL_ID, path)

    def test_kdbx_filename(self):
        name = BackupNaming.kdbx_filename(CELL_ID, TS, "a3f2b891")
        self.assertEqual(name, f"kdbx_{CELL_ID}_{TS}_a3f2b891.kdbx")

    def test_kdbx_filename_ends_with_kdbx(self):
        name = BackupNaming.kdbx_filename("cell-x", TS, "12345678")
        self.assertTrue(name.endswith(".kdbx"))

    def test_snapshot_set_id_structure(self):
        sid = BackupNaming.snapshot_set_id(CELL_ID, TS, "f7c1d3a2")
        self.assertEqual(sid, f"{CELL_ID}_{TS}_f7c1d3a2")

    def test_keepass_key_path(self):
        path = BackupNaming.keepass_key_path("Backup/config", "vm-forgejo-101", TS)
        self.assertEqual(path, f"Backup/config/vm-forgejo-101/{TS}/repo-password")

    def test_keepass_current_path(self):
        path = BackupNaming.keepass_current_path("Backup/config", "vm-forgejo-101")
        self.assertEqual(path, "Backup/config/vm-forgejo-101/current")

    def test_snapshot_tags_contain_all_fields(self):
        set_id = "cell-a_2026_abc"
        tags = BackupNaming.snapshot_tags(CELL_ID, set_id, "vm-forgejo-101", "config", TS)
        joined = " ".join(tags)
        self.assertIn(f"cell:{CELL_ID}", joined)
        self.assertIn(f"set:{set_id}", joined)
        self.assertIn("component:vm-forgejo-101", joined)
        self.assertIn("layer:config", joined)
        self.assertIn(f"run:{TS}", joined)

    def test_snapshot_tags_count(self):
        tags = BackupNaming.snapshot_tags("c", "s", "comp", "config", TS)
        self.assertEqual(len(tags), 5)


# ---------------------------------------------------------------------------
# generate_backup_passphrase
# ---------------------------------------------------------------------------

class TestGenerateBackupPassphrase(unittest.TestCase):

    def test_format_capital_start(self):
        for _ in range(20):
            p = generate_backup_passphrase()
            self.assertTrue(p[0].isupper(), f"Should start with capital: {p}")

    def test_format_has_periods(self):
        for _ in range(20):
            p = generate_backup_passphrase()
            self.assertIn(".", p)

    def test_format_ends_with_digit(self):
        for _ in range(20):
            p = generate_backup_passphrase()
            self.assertTrue(p[-1].isdigit(), f"Should end with digit: {p}")

    def test_length_in_range(self):
        for _ in range(20):
            p = generate_backup_passphrase()
            self.assertGreaterEqual(len(p), 20)
            self.assertLessEqual(len(p), 30)

    def test_generates_unique_values(self):
        phrases = {generate_backup_passphrase() for _ in range(10)}
        # With a 50-word list and random selection, expect high uniqueness
        self.assertGreater(len(phrases), 5)

    def test_no_special_shell_chars(self):
        for _ in range(20):
            p = generate_backup_passphrase()
            for ch in ("'", '"', " ", "\t", "\n", "$", "`", "\\"):
                self.assertNotIn(ch, p)


# ---------------------------------------------------------------------------
# SpaceProbe
# ---------------------------------------------------------------------------

class TestSpaceProbe(unittest.TestCase):

    def test_rclone_about_json_parsed(self):
        about_json = json.dumps({"free": 10_000_000_000, "total": 50_000_000_000,
                                  "used": 40_000_000_000})

        def mock_rclone(path):
            return 0, about_json, ""

        probe = SpaceProbe(rclone_fn=mock_rclone)
        info = probe.check("rclone", "gdrive:/backups")
        self.assertIsNotNone(info)
        self.assertEqual(info.available_bytes, 10_000_000_000)
        self.assertAlmostEqual(info.available_gb, 9.31, places=1)

    def test_rclone_about_failure_returns_none(self):
        def mock_rclone(path):
            return 1, "", "permission denied"

        probe = SpaceProbe(rclone_fn=mock_rclone)
        info = probe.check("rclone", "gdrive:/backups")
        self.assertIsNone(info)

    def test_rclone_extracts_top_level_remote(self):
        called_with = []

        def mock_rclone(path):
            called_with.append(path)
            return 0, json.dumps({"free": 1000}), ""

        probe = SpaceProbe(rclone_fn=mock_rclone)
        probe.check("rclone", "b2:my-bucket/proxmox-cell-a/config/vm-forgejo-101")
        self.assertEqual(len(called_with), 1)
        self.assertEqual(called_with[0], "b2:my-bucket")

    def test_space_info_available_gb(self):
        info = SpaceInfo(available_bytes=2 * 1024 ** 3)
        self.assertAlmostEqual(info.available_gb, 2.0, places=3)


# ---------------------------------------------------------------------------
# ResticRunner
# ---------------------------------------------------------------------------

class TestResticRunner(unittest.TestCase):

    def _make_runner(self, responses: dict):
        """
        responses: {arg_substring: (returncode, stdout, stderr)}
        The first matching key is used.
        """
        def mock_run(cmd, env, input_text=None):
            cmd_str = " ".join(cmd)
            for key, val in responses.items():
                if key in cmd_str:
                    return val
            return 1, "", "no mock for command"
        return ResticRunner("/repo/path", "test-password", runner_fn=mock_run)

    def test_init_success(self):
        runner = self._make_runner({"init": (0, "created", "")})
        ok, msg = runner.init()
        self.assertTrue(ok)

    def test_init_failure(self):
        runner = self._make_runner({"init": (1, "", "already exists")})
        ok, msg = runner.init()
        self.assertFalse(ok)

    def test_exists_true(self):
        runner = self._make_runner({"cat config": (0, "{}", "")})
        self.assertTrue(runner.exists())

    def test_exists_false(self):
        runner = self._make_runner({"cat config": (1, "", "repo not found")})
        self.assertFalse(runner.exists())

    def test_backup_parses_snapshot_id(self):
        summary = json.dumps({"message_type": "summary", "snapshot_id": "abc123def456"})
        runner = self._make_runner({"backup": (0, summary + "\n", "")})
        ok, snap_id, msg = runner.backup(["/data"], ["tag:test"])
        self.assertTrue(ok)
        self.assertEqual(snap_id, "abc123def456")

    def test_backup_failure(self):
        runner = self._make_runner({"backup": (1, "", "permission denied")})
        ok, snap_id, msg = runner.backup(["/data"], [])
        self.assertFalse(ok)
        self.assertIsNone(snap_id)

    def test_stats_parses_json(self):
        stats_json = json.dumps({"total_size": 1024, "total_file_count": 10})
        runner = self._make_runner({"stats": (0, stats_json, "")})
        ok, stats = runner.stats()
        self.assertTrue(ok)
        self.assertEqual(stats["total_size"], 1024)

    def test_key_list_parses_json(self):
        keys = json.dumps([{"id": "aabbcc", "current": True}])
        runner = self._make_runner({"key list": (0, keys, "")})
        ok, key_list = runner.key_list()
        self.assertTrue(ok)
        self.assertEqual(len(key_list), 1)
        self.assertEqual(key_list[0]["id"], "aabbcc")

    def test_forget_called_with_keep_last(self):
        called = []

        def mock_run(cmd, env, input_text=None):
            called.append(cmd)
            return 0, "", ""

        runner = ResticRunner("/repo", "pwd", runner_fn=mock_run)
        runner.forget(keep_last=5)
        self.assertTrue(any("--keep-last=5" in " ".join(c) for c in called))

    def test_restore_success(self):
        runner = self._make_runner({"restore": (0, "restored", "")})
        ok, msg = runner.restore("abc123", "/tmp/target")
        self.assertTrue(ok)

    def test_check_success(self):
        runner = self._make_runner({"check": (0, "no errors", "")})
        ok, msg = runner.check()
        self.assertTrue(ok)

    def test_password_not_in_args(self):
        """RESTIC_PASSWORD must be in env, never in cmd args."""
        captured_cmds = []

        def mock_run(cmd, env, input_text=None):
            captured_cmds.append(cmd)
            return 0, json.dumps({"message_type": "summary", "snapshot_id": "x"}), ""

        runner = ResticRunner("/repo", "secret-password-123", runner_fn=mock_run)
        runner.backup(["/data"], [])
        for cmd in captured_cmds:
            cmd_str = " ".join(cmd)
            self.assertNotIn("secret-password-123", cmd_str)


# ---------------------------------------------------------------------------
# RcloneRunner
# ---------------------------------------------------------------------------

class TestRcloneRunner(unittest.TestCase):

    def test_copy_success(self):
        def mock_run(cmd, env=None):
            return 0, "", ""

        r = RcloneRunner(runner_fn=mock_run)
        ok, msg = r.copy("/src/db.kdbx", "/mnt/usb/", "kdbx_cell_ts_hash.kdbx")
        self.assertTrue(ok)

    def test_copy_failure(self):
        def mock_run(cmd, env=None):
            return 1, "", "no space left"

        r = RcloneRunner(runner_fn=mock_run)
        ok, msg = r.copy("/src/db.kdbx", "/mnt/", "db.kdbx")
        self.assertFalse(ok)
        self.assertIn("no space left", msg)

    def test_copy_uses_copyto(self):
        captured = []

        def mock_run(cmd, env=None):
            captured.append(cmd)
            return 0, "", ""

        r = RcloneRunner(runner_fn=mock_run)
        r.copy("/src/file.kdbx", "b2:bucket/secrets", "name.kdbx")
        self.assertTrue(any("copyto" in c for c in captured[0]))
        self.assertTrue(any("name.kdbx" in c for c in captured[0]))

    def test_ls_parses_output(self):
        def mock_run(cmd, env=None):
            return 0, "file1.kdbx\nfile2.kdbx\n", ""

        r = RcloneRunner(runner_fn=mock_run)
        ok, files = r.ls("b2:bucket/")
        self.assertTrue(ok)
        self.assertIn("file1.kdbx", files)

    def test_ls_failure_returns_empty(self):
        def mock_run(cmd, env=None):
            return 1, "", "not found"

        r = RcloneRunner(runner_fn=mock_run)
        ok, files = r.ls("b2:bucket/")
        self.assertFalse(ok)
        self.assertEqual(files, [])


# ---------------------------------------------------------------------------
# BackupEngine — secrets layer
# ---------------------------------------------------------------------------

class TestBackupEngineSecrets(unittest.TestCase):

    def _make_engine(self, rclone_ok=True):
        bc = _minimal_backup_config()
        calls = []

        def mock_rclone(cmd, env=None):
            calls.append(cmd)
            return (0, "", "") if rclone_ok else (1, "", "connection refused")

        rclone = RcloneRunner(runner_fn=mock_rclone)
        engine = BackupEngine(
            cell_id=CELL_ID,
            backup_config=bc,
            rclone_runner=rclone,
            now_fn=_now_fixed,
        )
        return engine, calls

    def test_secrets_backup_success(self):
        engine, calls = self._make_engine(rclone_ok=True)
        # Need a real-ish path; mock will succeed regardless
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".kdbx", delete=False) as f:
            f.write(b"fake kdbx content")
            tmp = f.name
        try:
            result = engine.run_secrets_backup(tmp)
            self.assertFalse(result.all_failed)
            self.assertEqual(len(result.destination_results), 1)
            self.assertTrue(result.destination_results[0].success)
        finally:
            os.unlink(tmp)

    def test_secrets_backup_failure_reported(self):
        engine, calls = self._make_engine(rclone_ok=False)
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".kdbx", delete=False) as f:
            f.write(b"fake")
            tmp = f.name
        try:
            result = engine.run_secrets_backup(tmp)
            self.assertTrue(result.all_failed)
            self.assertFalse(result.destination_results[0].success)
        finally:
            os.unlink(tmp)

    def test_secrets_backup_result_has_layer(self):
        engine, _ = self._make_engine()
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".kdbx", delete=False) as f:
            f.write(b"x")
            tmp = f.name
        try:
            result = engine.run_secrets_backup(tmp)
            self.assertEqual(result.layer, "secrets")
        finally:
            os.unlink(tmp)

    def test_secrets_backup_snapshot_set_id_format(self):
        engine, _ = self._make_engine()
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".kdbx", delete=False) as f:
            f.write(b"x")
            tmp = f.name
        try:
            result = engine.run_secrets_backup(tmp)
            self.assertIn(CELL_ID, result.snapshot_set_id)
        finally:
            os.unlink(tmp)

    def test_secrets_backup_no_destinations_returns_empty_result(self):
        bc = _minimal_backup_config()
        bc["layers"]["secrets"]["destinations"] = []
        engine = BackupEngine(cell_id=CELL_ID, backup_config=bc, now_fn=_now_fixed)
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".kdbx", delete=False) as f:
            f.write(b"x")
            tmp = f.name
        try:
            result = engine.run_secrets_backup(tmp)
            self.assertEqual(result.destination_results, [])
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# BackupEngine — restic layer
# ---------------------------------------------------------------------------

class TestBackupEngineRestic(unittest.TestCase):

    def _make_engine(self, restic_ok=True, stats_ok=True):
        bc = _minimal_backup_config()
        snap_json = json.dumps({"message_type": "summary", "snapshot_id": "deadbeef12345678"})
        stats_json = json.dumps({"total_size": 1024 * 1024, "total_file_count": 42})
        keys_json  = json.dumps([{"id": "oldkeyid", "current": False}])

        _VERBS = {"init", "backup", "stats", "forget", "restore", "check", "snapshots"}  # noqa: N806
        _SUBS  = {"add", "remove", "list"}  # noqa: N806

        def mock_restic(cmd, env, input_text=None):
            # Route by restic subcommand verb — avoids false matches in repo paths
            verb = next((a for a in cmd if a in _VERBS), "")
            sub  = next((a for a in cmd if a in _SUBS),  "")
            if "cat" in cmd:
                return 0, "{}", ""
            if "key" in cmd:
                if sub == "list":   return 0, keys_json, ""
                if sub == "add":    return 0, "key added", ""
                if sub == "remove": return 0, "key removed", ""
            if verb == "backup":
                return (0, snap_json + "\n", "") if restic_ok else (1, "", "backup failed")
            if verb == "stats":
                return (0, stats_json, "") if stats_ok else (1, "", "stats failed")
            if verb == "forget":
                return 0, "pruned", ""
            return 0, "", ""

        def restic_factory(repo, pwd, rfn=None):
            return ResticRunner(repo, pwd, runner_fn=mock_restic)

        engine = BackupEngine(
            cell_id=CELL_ID,
            backup_config=bc,
            restic_factory=restic_factory,
            now_fn=_now_fixed,
        )
        return engine

    def test_restic_backup_success(self):
        engine = self._make_engine()
        result = engine.run_restic_backup("config", "cell-config", ["/opt/broodforge"])
        self.assertFalse(result.all_failed)
        dr = result.destination_results[0]
        self.assertTrue(dr.success)
        self.assertTrue(dr.verified)
        self.assertEqual(dr.snapshot_id, "deadbeef12345678")

    def test_restic_backup_failure_not_verified(self):
        engine = self._make_engine(restic_ok=False)
        result = engine.run_restic_backup("config", "cell-config", ["/opt"])
        self.assertTrue(result.all_failed)

    def test_restic_backup_stats_fail_not_verified(self):
        engine = self._make_engine(restic_ok=True, stats_ok=False)
        result = engine.run_restic_backup("config", "cell-config", ["/opt"])
        dr = result.destination_results[0]
        self.assertFalse(dr.verified)

    def test_restic_backup_result_layer(self):
        engine = self._make_engine()
        result = engine.run_restic_backup("config", "cell-config", ["/opt"])
        self.assertEqual(result.layer, "config")

    def test_restic_backup_component_prefix_in_result(self):
        engine = self._make_engine()
        result = engine.run_restic_backup("config", "vm-forgejo-101", ["/opt"])
        dr = result.destination_results[0]
        self.assertEqual(dr.component_prefix, "vm-forgejo-101")

    def test_restic_backup_history_record_structure(self):
        engine = self._make_engine()
        result = engine.run_restic_backup("config", "cell-config", ["/opt"])
        rec = result.to_history_record()
        self.assertIn("run_at", rec)
        self.assertIn("snapshot_set_id", rec)
        self.assertIn("layer", rec)
        self.assertIn("components", rec)


# ---------------------------------------------------------------------------
# RestoreEngine
# ---------------------------------------------------------------------------

HISTORY = [
    {
        "run_at": "2026-06-01T03:00:00Z",
        "snapshot_set_id": f"{CELL_ID}_2026-06-01_03_00_00_aabbccdd",
        "layer": "config",
        "destinations_attempted": ["local-drive"],
        "destinations_succeeded": ["local-drive"],
        "consecutive_all_fail_count": 0,
        "components": [{
            "component_id": "cell-config",
            "component_prefix": "cell-config",
            "destination_id": "local-drive",
            "restic_snapshot_id": "snap1234",
            "keepass_key_path": "Backup/config/cell-config/2026-06-01_03_00_00/repo-password",
            "size_bytes": 1024,
            "verified": True,
            "routed_reason": "primary",
        }],
    },
    {
        "run_at": "2026-05-31T03:00:00Z",
        "snapshot_set_id": f"{CELL_ID}_2026-05-31_03_00_00_11223344",
        "layer": "config",
        "destinations_attempted": ["local-drive"],
        "destinations_succeeded": [],
        "consecutive_all_fail_count": 1,
        "components": [],
    },
]


class TestRestoreEngine(unittest.TestCase):

    def _make_engine(self, restore_ok=True, check_ok=True):
        bc = _minimal_backup_config(history=HISTORY)

        _VERBS = {"init", "restore", "check", "stats", "snapshots"}  # noqa: N806

        def mock_restic(cmd, env, input_text=None):
            verb = next((a for a in cmd if a in _VERBS), "")
            if "cat" in cmd:
                return 0, "{}", ""
            if verb == "restore":
                return (0, "restored", "") if restore_ok else (1, "", "restore failed")
            if verb == "check":
                return (0, "no errors", "") if check_ok else (1, "", "errors found")
            return 0, "", ""

        def restic_factory(repo, pwd, rfn=None):
            return ResticRunner(repo, pwd, runner_fn=mock_restic)

        return RestoreEngine(
            cell_id=CELL_ID,
            backup_config=bc,
            restic_factory=restic_factory,
        )

    def test_list_snapshot_sets_returns_sets(self):
        engine = self._make_engine()
        sets = engine.list_snapshot_sets()
        self.assertEqual(len(sets), 2)

    def test_list_snapshot_sets_most_recent_first(self):
        engine = self._make_engine()
        sets = engine.list_snapshot_sets()
        self.assertGreater(sets[0]["run_at"], sets[1]["run_at"])

    def test_list_snapshot_sets_deduplicates(self):
        history_dup = HISTORY + [HISTORY[0]]  # duplicate first entry
        bc = _minimal_backup_config(history=history_dup)
        engine = RestoreEngine(cell_id=CELL_ID, backup_config=bc)
        sets = engine.list_snapshot_sets()
        ids = [s["snapshot_set_id"] for s in sets]
        self.assertEqual(len(ids), len(set(ids)))

    def test_find_record_for_set(self):
        engine = self._make_engine()
        rec = engine.find_record_for_set(
            f"{CELL_ID}_2026-06-01_03_00_00_aabbccdd", "config"
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec["layer"], "config")

    def test_find_record_returns_none_when_not_found(self):
        engine = self._make_engine()
        self.assertIsNone(engine.find_record_for_set("nonexistent", "config"))

    def test_restore_dry_run_returns_results(self):
        engine = self._make_engine()
        results = engine.restore_snapshot_set(
            f"{CELL_ID}_2026-06-01_03_00_00_aabbccdd",
            "config", "/tmp/restore", dry_run=True
        )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].get("dry_run"))

    def test_restore_success(self):
        engine = self._make_engine(restore_ok=True, check_ok=True)
        results = engine.restore_snapshot_set(
            f"{CELL_ID}_2026-06-01_03_00_00_aabbccdd",
            "config", "/tmp/restore"
        )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["success"])

    def test_restore_failure_recorded(self):
        engine = self._make_engine(restore_ok=False)
        results = engine.restore_snapshot_set(
            f"{CELL_ID}_2026-06-01_03_00_00_aabbccdd",
            "config", "/tmp/restore"
        )
        self.assertFalse(results[0]["success"])


# ---------------------------------------------------------------------------
# _score_backup_config_completeness
# ---------------------------------------------------------------------------

class TestScoreBackupConfigCompleteness(unittest.TestCase):

    def test_no_backup_config_is_red(self):
        gaps = _score_backup_config_completeness({})
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "RED")
        self.assertIn("MISSING_BACKUP_CONFIG", gaps[0].gap_type)

    def test_no_backup_config_null_is_red(self):
        gaps = _score_backup_config_completeness({"backup_config": None})
        self.assertEqual(gaps[0].severity, "RED")

    def test_healthy_config_no_gaps(self):
        now_str = datetime.now(timezone.utc).isoformat()
        bc = _minimal_backup_config(
            last_backup_at=now_str, consec_fail=0
        )
        gaps = _score_backup_config_completeness({"backup_config": bc})
        red_orange = [g for g in gaps if g.severity in ("RED", "ORANGE")]
        self.assertEqual(red_orange, [])

    def test_consec_fail_2_is_red(self):
        bc = _minimal_backup_config(consec_fail=2)
        gaps = _score_backup_config_completeness({"backup_config": bc})
        red_gaps = [g for g in gaps if g.severity == "RED"
                    and g.gap_type == "BACKUP_ALL_DESTINATIONS_FAILED"]
        self.assertGreater(len(red_gaps), 0)

    def test_consec_fail_1_is_orange(self):
        bc = _minimal_backup_config(consec_fail=1)
        gaps = _score_backup_config_completeness({"backup_config": bc})
        orange_gaps = [g for g in gaps if g.severity == "ORANGE"
                       and g.gap_type == "BACKUP_ALL_DESTINATIONS_FAILED"]
        self.assertGreater(len(orange_gaps), 0)

    def test_never_backed_up_is_orange(self):
        bc = _minimal_backup_config(last_backup_at=None)
        gaps = _score_backup_config_completeness({"backup_config": bc})
        orange_gaps = [g for g in gaps if g.severity == "ORANGE"
                       and g.gap_type == "STALE_BACKUP"]
        self.assertGreater(len(orange_gaps), 0)

    def test_stale_backup_3x_is_red(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=200)).isoformat()
        bc = _minimal_backup_config(last_backup_at=old)
        gaps = _score_backup_config_completeness({"backup_config": bc})
        red_stale = [g for g in gaps if g.severity == "RED" and g.gap_type == "STALE_BACKUP"]
        self.assertGreater(len(red_stale), 0)

    def test_stale_backup_2x_is_orange(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=120)).isoformat()
        bc = _minimal_backup_config(last_backup_at=old)
        gaps = _score_backup_config_completeness({"backup_config": bc})
        orange_stale = [g for g in gaps if g.severity == "ORANGE"
                        and g.gap_type == "STALE_BACKUP"]
        self.assertGreater(len(orange_stale), 0)

    def test_no_destinations_for_config_is_red(self):
        bc = _minimal_backup_config()
        bc["layers"]["config"]["destinations"] = []
        gaps = _score_backup_config_completeness({"backup_config": bc})
        red_gaps = [g for g in gaps if g.severity == "RED"
                    and g.gap_type == "MISSING_BACKUP_DESTINATION"]
        self.assertGreater(len(red_gaps), 0)

    def test_disabled_layer_not_scored(self):
        bc = _minimal_backup_config(appdata_enabled=False)
        gaps = _score_backup_config_completeness({"backup_config": bc})
        appdata_gaps = [g for g in gaps if "appdata" in g.component_id]
        self.assertEqual(appdata_gaps, [])


# ---------------------------------------------------------------------------
# Recovery runbook — Appendix H
# ---------------------------------------------------------------------------

class TestRunbookAppendixH(unittest.TestCase):

    def _build_html(self, bc=None):
        from dependencies import build_graph
        from html_recovery_runbook import build_recovery_runbook_html
        from readiness import score_graph

        manifest = {
            "host": {"hostname": "pve01", "proxmox_version": "8.0"},
            "network": {"default_gateway": "192.168.1.1", "dns_servers": []},
            "vms": [], "containers": [], "collected_at": "2026-01-01T00:00:00Z",
        }
        if bc is not None:
            manifest["backup_config"] = bc

        graph = build_graph(manifest)
        readiness = score_graph(graph, manifest)
        gen_meta = {"generated_at": "2026-01-01T12:00:00Z",
                    "generated_at_display": "2026-01-01 12:00:00 UTC"}
        return build_recovery_runbook_html(manifest, graph, readiness, gen_meta)

    def test_appendix_h_present(self):
        text = self._build_html()
        self.assertIn("Appendix H", text)
        self.assertIn("Backup Configuration", text)

    def test_no_backup_config_shows_warning(self):
        text = self._build_html(bc=None)
        self.assertIn("No backup configuration declared", text)
        self.assertIn("setup-backup.py", text)

    def test_configured_backup_shows_layers(self):
        bc = _minimal_backup_config(last_backup_at="2026-06-01T03:00:00Z")
        text = self._build_html(bc=bc)
        self.assertIn("Secrets", text)
        self.assertIn("Configuration state", text)

    def test_destination_ids_shown(self):
        bc = _minimal_backup_config()
        text = self._build_html(bc=bc)
        self.assertIn("local-drive", text)
        self.assertIn("local-usb", text)

    def test_all_fail_warning_shown(self):
        bc = _minimal_backup_config(consec_fail=2)
        text = self._build_html(bc=bc)
        self.assertIn("ALL DESTINATIONS FAILED", text)

    def test_restore_commands_shown(self):
        bc = _minimal_backup_config()
        text = self._build_html(bc=bc)
        self.assertIn("restore-from-backup.py", text)
        self.assertIn("--layer config", text)

    def test_keepass_backup_note_shown(self):
        bc = _minimal_backup_config()
        text = self._build_html(bc=bc)
        self.assertIn("KeePass Database Backup", text)
        self.assertIn("forge-manifest.json", text)

    def test_disabled_appdata_layer_shown_as_disabled(self):
        bc = _minimal_backup_config(appdata_enabled=False)
        text = self._build_html(bc=bc)
        self.assertIn("DISABLED", text)


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestBootstrapStateSchemaWithBackupConfig(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            import jsonschema
            cls.jsonschema = jsonschema
            cls.skip = False
        except ImportError:
            cls.skip = True
        schema_path = REPO_ROOT / "data-model" / "bootstrap-state-schema.json"
        cls.schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def _validate(self, instance):
        if self.skip:
            self.skipTest("jsonschema not installed")
        self.jsonschema.validate(instance, self.schema)

    def test_backup_config_section_validates(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        fixture["backup_config"] = _minimal_backup_config()
        self._validate(fixture)

    def test_backup_destination_restic_requires_id_type_root_prefix(self):
        if self.skip:
            self.skipTest("jsonschema not installed")
        # Missing restic_repo_root should fail schema validation
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        bc = _minimal_backup_config()
        del bc["layers"]["config"]["destinations"][0]["restic_repo_root"]
        fixture["backup_config"] = bc
        with self.assertRaises(self.jsonschema.ValidationError):
            self._validate(fixture)


if __name__ == "__main__":
    unittest.main()
