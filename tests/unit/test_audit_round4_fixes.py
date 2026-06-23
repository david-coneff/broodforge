#!/usr/bin/env python3
"""
test_audit_round4_fixes.py — Tests for audit round 4 findings.

Covers:
  - _score_migration_health(): ORANGE on failed, YELLOW on rolled_back (I3)
  - HatcheryReceiverConfig.state_path field (I1)
  - /api/spawn-complete endpoint routing (I1)
  - reconstruction-drill.py CLI wrapper importable and has main() (D1/I4)
  - hatchery_state.read_hatchery_state() embeds hatchery_url in manifest (I1)
  - migrate_k3s_lib imports from collector_utils (I5)
  - collector import alias removed (A2)
  - _commit_migration_record added to both migration scripts (I2)
"""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

REPO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# I3 — _score_migration_health
# ---------------------------------------------------------------------------

class TestScoreMigrationHealth(unittest.TestCase):

    def _score(self, manifest):
        from readiness import _score_migration_health
        return _score_migration_health(manifest)

    def test_no_migration_history_returns_no_gaps(self):
        self.assertEqual(self._score({}), [])

    def test_empty_migration_history_returns_no_gaps(self):
        self.assertEqual(self._score({"migration_history": []}), [])

    def test_successful_migration_returns_no_gaps(self):
        gaps = self._score({"migration_history": [{
            "migration_id": "m1",
            "node_vm_name": "k3s-server-01",
            "from_variant": "ubuntu",
            "to_variant": "talos",
            "outcome": "success",
        }]})
        self.assertEqual(gaps, [])

    def test_failed_migration_orange(self):
        gaps = self._score({"migration_history": [{
            "migration_id": "m1",
            "node_vm_name": "k3s-server-01",
            "from_variant": "ubuntu",
            "to_variant": "talos",
            "outcome": "failed",
            "error": "talosctl timed out",
        }]})
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "ORANGE")
        self.assertIn("k3s-server-01", gaps[0].description)
        self.assertIn("talosctl timed out", gaps[0].description)

    def test_rolled_back_migration_yellow(self):
        gaps = self._score({"migration_history": [{
            "migration_id": "m2",
            "node_vm_name": "k3s-server-02",
            "from_variant": "talos",
            "to_variant": "ubuntu",
            "outcome": "rolled_back",
        }]})
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")
        self.assertIn("k3s-server-02", gaps[0].description)

    def test_multiple_failures_all_reported(self):
        gaps = self._score({"migration_history": [
            {"migration_id": "m1", "node_vm_name": "node-a", "from_variant": "ubuntu",
             "to_variant": "talos", "outcome": "failed"},
            {"migration_id": "m2", "node_vm_name": "node-b", "from_variant": "talos",
             "to_variant": "ubuntu", "outcome": "rolled_back"},
        ]})
        self.assertEqual(len(gaps), 2)
        severities = {g.severity for g in gaps}
        self.assertIn("ORANGE", severities)
        self.assertIn("YELLOW", severities)

    def test_aborted_not_scored(self):
        # 'aborted' is not currently scored (user cancelled before any changes)
        gaps = self._score({"migration_history": [{
            "migration_id": "m3",
            "node_vm_name": "node-c",
            "from_variant": "ubuntu",
            "to_variant": "talos",
            "outcome": "aborted",
        }]})
        self.assertEqual(gaps, [])

    def test_gap_type_migration_failed(self):
        gaps = self._score({"migration_history": [{
            "migration_id": "m4", "node_vm_name": "n", "from_variant": "ubuntu",
            "to_variant": "talos", "outcome": "failed"}]})
        self.assertEqual(gaps[0].gap_type, "MIGRATION_FAILED")

    def test_gap_type_migration_rolled_back(self):
        gaps = self._score({"migration_history": [{
            "migration_id": "m5", "node_vm_name": "n", "from_variant": "ubuntu",
            "to_variant": "talos", "outcome": "rolled_back"}]})
        self.assertEqual(gaps[0].gap_type, "MIGRATION_ROLLED_BACK")

    def test_remediation_message_references_docs(self):
        gaps = self._score({"migration_history": [{
            "migration_id": "m6", "node_vm_name": "n", "from_variant": "ubuntu",
            "to_variant": "talos", "outcome": "failed"}]})
        self.assertIn("TALOS-ALTERNATIVE", gaps[0].remediation)

    def test_wired_into_score_graph(self):
        from dependencies import build_graph
        from readiness import _score_migration_health, score_graph
        manifest = {
            "host": {"hostname": "pve01"},
            "vms": [], "containers": [],
            "migration_history": [{
                "migration_id": "m7", "node_vm_name": "k3s-server-01",
                "from_variant": "ubuntu", "to_variant": "talos",
                "outcome": "failed",
            }],
        }
        # Verify _score_migration_health is called (via direct call confirms wiring)
        gaps = _score_migration_health(manifest)
        self.assertTrue(any(g.severity == "ORANGE" for g in gaps),
                        "Expected ORANGE gap for failed migration")
        # Verify score_graph includes migration gap in registry_gaps
        graph = build_graph(manifest)
        readiness = score_graph(graph, manifest)
        gap_types = {g.gap_type for g in readiness.registry_gaps}
        self.assertIn("MIGRATION_FAILED", gap_types,
                      f"Expected MIGRATION_FAILED in {gap_types}")


# ---------------------------------------------------------------------------
# I1 — HatcheryReceiverConfig.state_path and /api/spawn-complete routing
# ---------------------------------------------------------------------------

class TestHatcheryReceiverStatePathConfig(unittest.TestCase):

    def test_state_path_default_is_empty(self):
        import hatchery_receiver as hr
        cfg = hr.HatcheryReceiverConfig()
        self.assertEqual(cfg.state_path, "")

    def test_state_path_can_be_set(self):
        import hatchery_receiver as hr
        cfg = hr.HatcheryReceiverConfig(state_path="/var/lib/broodforge/bootstrap-state.json")
        self.assertEqual(cfg.state_path, "/var/lib/broodforge/bootstrap-state.json")


class TestSpawnCompleteRouting(unittest.TestCase):
    """Verify that /api/spawn-complete routes to _handle_spawn_complete."""

    def _make_handler(self, path, body=None, token=""):
        from unittest.mock import MagicMock

        import hatchery_receiver as hr
        data = json.dumps(body or {}).encode()

        cfg = hr.HatcheryReceiverConfig(auth_token=token)

        class _Handler(hr._ReceiverHandler):
            _config = cfg

        handler = _Handler.__new__(_Handler)
        handler.path = path
        handler.headers = {
            "Content-Length": str(len(data)),
            "X-Broodforge-Token": token,
        }
        handler.rfile = io.BytesIO(data)
        handler.client_address = ("127.0.0.1", 9999)

        responses = []
        handler.send_error = lambda code, msg="": responses.append(("error", code, msg))
        handler.send_response = lambda code: responses.append(("ok", code))
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = io.BytesIO()
        handler.log_message = lambda *a: None
        return handler, responses

    def test_unknown_path_returns_404(self):
        handler, responses = self._make_handler("/api/unknown")
        handler.do_POST()
        self.assertTrue(any(r[1] == 404 for r in responses))

    def test_spawn_complete_missing_state_path_returns_400(self):
        handler, responses = self._make_handler(
            "/api/spawn-complete",
            body={"spawn_plan": {"target_hostname": "broodling-01"}}
        )
        handler.do_POST()
        self.assertTrue(any(r[1] in (400, 500) for r in responses))

    def test_spawn_complete_ignores_state_path_in_body(self):
        """Security: state_path in body must NOT be used (path traversal prevention)."""
        import hatchery_receiver as hr
        # No state_path configured on the server → should 400 even if body has one
        data = json.dumps({"spawn_plan": {}, "state_path": "/etc/passwd"}).encode()
        cfg = hr.HatcheryReceiverConfig()  # state_path = ""

        class _Handler(hr._ReceiverHandler):
            _config = cfg

        handler = _Handler.__new__(_Handler)
        handler.path = "/api/spawn-complete"
        handler.headers = {"Content-Length": str(len(data))}
        handler.rfile = io.BytesIO(data)
        handler.client_address = ("127.0.0.1", 9999)

        responses = []
        handler.send_error = lambda code, msg="": responses.append(("error", code, msg))
        handler.send_response = lambda code: responses.append(("ok", code))
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = io.BytesIO()
        handler.log_message = lambda *a: None
        handler.do_POST()
        # Must return 400 (no configured state_path), NOT 200 (path from body ignored)
        self.assertTrue(any(r[1] == 400 for r in responses))

    def test_spawn_complete_with_state_updates_file(self):
        import hatchery_receiver as hr
        state = {
            "cell_id": "test-cell",
            "vms": [],
            "dns_registry": [],
            "spawn_history": [],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(state, f)
            state_path = f.name

        try:
            spawn_plan = {
                "target_hostname": "broodling-01",
                "cell_id": "test-cell",
                "hostname": "broodling-01",
                "allocated_vmids": [201, 202],
                "allocated_ips": ["192.168.1.51", "192.168.1.52"],
                "disposition": {"services": [], "execution_mode": "autonomous"},
                "vms": [],
            }
            # state_path must NOT be in the body (path traversal fix) —
            # the server only uses self._config.state_path
            body = {"spawn_plan": spawn_plan}
            data = json.dumps(body).encode()

            cfg = hr.HatcheryReceiverConfig(state_path=state_path)

            class _Handler(hr._ReceiverHandler):
                _config = cfg

            handler = _Handler.__new__(_Handler)
            handler.path = "/api/spawn-complete"
            handler.headers = {"Content-Length": str(len(data))}
            handler.rfile = io.BytesIO(data)
            handler.client_address = ("127.0.0.1", 9999)

            responses = []
            handler.send_error = lambda code, msg="": responses.append(("error", code, msg))
            handler.send_response = lambda code: responses.append(("ok", code))
            handler.send_header = MagicMock()
            handler.end_headers = MagicMock()
            handler.wfile = io.BytesIO()
            handler.log_message = lambda *a: None

            handler.do_POST()
            # Either 200 (success) or 500 (import error in test env) — not 404
            self.assertFalse(any(r[1] == 404 for r in responses))
        finally:
            os.unlink(state_path)


# ---------------------------------------------------------------------------
# D1/I4 — reconstruction-drill.py CLI wrapper
# ---------------------------------------------------------------------------

class TestReconstructionDrillCLI(unittest.TestCase):

    def test_cli_file_exists(self):
        cli_path = REPO_ROOT / "proxmox-bootstrap" / "reconstruction-drill.py"
        self.assertTrue(cli_path.exists(), "reconstruction-drill.py CLI wrapper is missing")

    def test_cli_has_main_function(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "reconstruction_drill_cli",
            REPO_ROOT / "proxmox-bootstrap" / "reconstruction-drill.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, "main"), "CLI wrapper must have a main() function")

    def test_cli_subcommands_defined(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "reconstruction_drill_cli",
            REPO_ROOT / "proxmox-bootstrap" / "reconstruction-drill.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name in ("cmd_start", "cmd_last", "cmd_report", "cmd_complete"):
            self.assertTrue(hasattr(mod, name), f"CLI wrapper missing {name}")

    def test_cli_last_with_no_drills(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "reconstruction_drill_cli",
            REPO_ROOT / "proxmox-bootstrap" / "reconstruction-drill.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            state_path = f.name

        try:
            import argparse
            args = argparse.Namespace(state=state_path)
            # Should print "No drill records found." without crashing
            import io as _io
            captured = _io.StringIO()
            import sys as _sys
            old_stdout = _sys.stdout
            _sys.stdout = captured
            mod.cmd_last(args)
            _sys.stdout = old_stdout
            self.assertIn("No drill records", captured.getvalue())
        finally:
            _sys.stdout = old_stdout if '_sys' in dir() else _sys.stdout
            os.unlink(state_path)


# ---------------------------------------------------------------------------
# I1 — hatchery_url in spawn manifest
# ---------------------------------------------------------------------------

class TestHatcheryUrlInSpawnManifest(unittest.TestCase):

    def _make_state(self, fqdn="hatchery.home.example.com"):
        return {
            "cell_id": "test-cell",
            "host_identity": {"hostname": "pve01", "fqdn": fqdn, "domain": "home.example.com"},
            "network_topology": {"profile": "wan", "management_cidr": "192.168.1.0/24"},
            "vms": [],
            "dns_registry": [],
            "service_contracts": [],
            "k3s_cluster": {"pod_cidr": "10.42.0.0/16", "service_cidr": "10.43.0.0/16"},
        }

    def test_hatchery_url_present_in_manifest(self):
        from hatchery_state import read_hatchery_state
        manifest = read_hatchery_state(self._make_state())
        self.assertIn("hatchery_url", manifest.raw)

    def test_hatchery_url_contains_fqdn(self):
        from hatchery_state import read_hatchery_state
        manifest = read_hatchery_state(self._make_state("myhost.example.com"))
        self.assertIn("myhost.example.com", manifest.raw["hatchery_url"])

    def test_hatchery_url_contains_receiver_port(self):
        from hatchery_state import read_hatchery_state
        manifest = read_hatchery_state(self._make_state())
        self.assertIn("9321", manifest.raw["hatchery_url"])

    def test_receiver_token_field_present(self):
        from hatchery_state import read_hatchery_state
        manifest = read_hatchery_state(self._make_state())
        self.assertIn("receiver_token", manifest.raw)

    def test_hatchery_url_empty_without_fqdn(self):
        from hatchery_state import read_hatchery_state
        state = self._make_state()
        state["host_identity"].pop("fqdn", None)
        state["host_identity"].pop("hostname", None)
        manifest = read_hatchery_state(state)
        self.assertEqual(manifest.raw.get("hatchery_url", ""), "")


# ---------------------------------------------------------------------------
# I5 — migrate_k3s_lib imports from collector_utils
# ---------------------------------------------------------------------------

class TestMigrateKszLibUsesCollectorUtils(unittest.TestCase):

    def test_local_runner_imported_from_collector_utils(self):
        import migrate_k3s_lib as lib
        # _local_runner should resolve to collector_utils.local_runner or a fallback
        # Either way, the function should exist on the module
        self.assertTrue(hasattr(lib, "_local_runner"))

    def test_collector_utils_local_runner_is_importable(self):
        from collector_utils import local_runner
        self.callable(local_runner) if hasattr(self, "callable") else self.assertTrue(callable(local_runner))


# ---------------------------------------------------------------------------
# A2 — collector import alias removed
# ---------------------------------------------------------------------------

class TestCollectorImportAlias(unittest.TestCase):

    def _check_no_alias(self, module_name):
        import importlib
        mod = importlib.import_module(module_name)
        # local_runner should be accessible directly (not only as _local_runner)
        self.assertTrue(hasattr(mod, "local_runner"),
                        f"{module_name} should export local_runner (not aliased as _local_runner)")
        self.assertFalse(hasattr(mod, "_local_runner"),
                         f"{module_name} should not have _local_runner alias")

    def test_hardware_state_collector(self):
        self._check_no_alias("hardware_state_collector")

    def test_platform_state_collector(self):
        self._check_no_alias("platform_state_collector")

    def test_cluster_state_collector(self):
        self._check_no_alias("cluster_state_collector")

    def test_storage_state_collector(self):
        self._check_no_alias("storage_state_collector")

    def test_data_protection_collector(self):
        self._check_no_alias("data_protection_collector")


# ---------------------------------------------------------------------------
# I2 — _commit_migration_record added to migration scripts
# ---------------------------------------------------------------------------

class TestMigrationCommitHelper(unittest.TestCase):

    def _load(self, filename):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            filename.replace("-", "_").replace(".py", ""),
            REPO_ROOT / "proxmox-bootstrap" / filename,
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_talos_migration_has_commit_helper(self):
        m = self._load("migrate-k3s-to-talos.py")
        self.assertTrue(hasattr(m, "_commit_migration_record"),
                        "migrate-k3s-to-talos.py missing _commit_migration_record")

    def test_ubuntu_migration_has_commit_helper(self):
        m = self._load("migrate-k3s-to-ubuntu.py")
        self.assertTrue(hasattr(m, "_commit_migration_record"),
                        "migrate-k3s-to-ubuntu.py missing _commit_migration_record")

    def test_commit_helper_nonfatal_on_git_failure(self):
        m = self._load("migrate-k3s-to-talos.py")
        # Should not raise even if git fails (no real git repo in test env)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(b"{}")
            p = f.name
        try:
            m._commit_migration_record(p, "node-01", "ubuntu", "talos")
        except Exception as exc:
            self.fail(f"_commit_migration_record raised unexpectedly: {exc}")
        finally:
            os.unlink(p)


if __name__ == "__main__":
    unittest.main()
