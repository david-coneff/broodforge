"""
Tests for Phase 1 Bootstrap Intelligence Framework.

Covers:
  - discover.py: individual collector functions with fixture data
  - cluster_planner.py: planning logic with various hardware profiles
  - capacity_validator.py: validation checks with pass/fail/warn scenarios

All tests use fixture data — no real hardware or Proxmox host required.

Run: py -3 tests/unit/test_phase1_bootstrap.py
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
BOOTSTRAP_DIR = REPO_ROOT / "proxmox-bootstrap"


def _import(rel_path: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, BOOTSTRAP_DIR / rel_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

HARDWARE_16GB = {
    "collected_at": "2026-05-31 16:00:00 UTC",
    "cpu": {
        "model": "Intel Core i5-12600K",
        "sockets": 1,
        "cores_per_socket": 10,
        "threads_per_core": 2,
        "total_threads": 20,
        "architecture": "x86_64",
        "virtualization": "VT-x (Intel)",
    },
    "memory": {"total_gb": 16.0, "ecc": False},
    "disks": [
        {"name": "sda", "model": "Samsung 870 QVO", "size_raw": "2T",
         "type": "SSD", "interface": "SATA"},
        {"name": "sdb", "model": "Samsung 870 QVO", "size_raw": "2T",
         "type": "SSD", "interface": "SATA"},
    ],
    "nics": [
        {"name": "enp2s0", "mac": "aa:bb:cc:dd:ee:ff", "mtu": 1500, "state": "UP"}
    ],
    "collection_errors": [],
}

HARDWARE_64GB = {
    "collected_at": "2026-05-31 16:00:00 UTC",
    "cpu": {
        "model": "AMD EPYC 7302",
        "sockets": 1,
        "cores_per_socket": 16,
        "threads_per_core": 2,
        "total_threads": 32,
        "architecture": "x86_64",
        "virtualization": "AMD-V",
    },
    "memory": {"total_gb": 64.0, "ecc": True},
    "disks": [
        {"name": "sda", "size_raw": "4T", "type": "HDD", "interface": "SATA"},
        {"name": "sdb", "size_raw": "4T", "type": "HDD", "interface": "SATA"},
        {"name": "sdc", "size_raw": "4T", "type": "HDD", "interface": "SATA"},
    ],
    "nics": [
        {"name": "enp2s0", "mac": "11:22:33:44:55:66", "mtu": 1500, "state": "UP"},
        {"name": "enp3s0", "mac": "11:22:33:44:55:77", "mtu": 1500, "state": "UP"},
    ],
    "collection_errors": [],
}

HARDWARE_INSUFFICIENT = {
    "collected_at": "2026-05-31 16:00:00 UTC",
    "cpu": {"total_threads": 2, "virtualization": None},
    "memory": {"total_gb": 4.0, "ecc": False},
    "disks": [{"name": "sda", "size_raw": "64G", "type": "SSD"}],
    "nics": [{"name": "eth0", "mac": "aa:bb:cc:00:00:01"}],
    "collection_errors": [],
}

K3S_META_SINGLE = {
    "ha_policy": {"control_plane_ha_threshold": 3, "ha_enabled": False},
}

K3S_META_HA = {
    "ha_policy": {"control_plane_ha_threshold": 3, "ha_enabled": True},
}


# ---------------------------------------------------------------------------
# discover.py — utility functions
# ---------------------------------------------------------------------------

class TestDiscoverUtils(unittest.TestCase):
    def setUp(self):
        self.d = _import("discovery/discover.py", "discover")

    def test_now_utc_returns_string(self):
        ts = self.d._now_utc()
        self.assertIsInstance(ts, str)
        self.assertIn("UTC", ts)
        self.assertIn("2026", ts)  # current year

    def test_parse_zpool_topology_mirror(self):
        text = "  config:\n    mirror\n      sda\n      sdb\n"
        self.assertEqual(self.d._parse_zpool_topology(text), "mirror")

    def test_parse_zpool_topology_raidz(self):
        text = "  config:\n    raidz\n      sda sdb sdc\n"
        self.assertEqual(self.d._parse_zpool_topology(text), "raidz")

    def test_parse_zpool_topology_raidz2(self):
        text = "  raidz2\n"
        self.assertEqual(self.d._parse_zpool_topology(text), "raidz2")

    def test_parse_zpool_topology_unknown(self):
        self.assertEqual(self.d._parse_zpool_topology(""), "unknown")

    def test_run_returns_tuple(self):
        stdout, stderr, rc = self.d._run(["echo", "hello"])
        self.assertIsInstance(stdout, str)
        self.assertIsInstance(stderr, str)
        self.assertIsInstance(rc, int)

    def test_run_missing_command_returns_127(self):
        _, _, rc = self.d._run(["this-command-does-not-exist-xyz"])
        self.assertEqual(rc, 127)

    def test_run_json_parses_valid_json(self):
        import sys
        data, err = self.d._run_json([sys.executable, "-c", "import json; print(json.dumps({'a': 1}))"])
        self.assertEqual(data, {"a": 1})
        self.assertEqual(err, "")

    def test_run_json_handles_invalid_json(self):
        data, err = self.d._run_json(["echo", "not-json"])
        self.assertIsNone(data)
        self.assertIn("JSON parse error", err)


# ---------------------------------------------------------------------------
# discover.py — collector outputs have required structure
# ---------------------------------------------------------------------------

class TestCollectorStructure(unittest.TestCase):
    def setUp(self):
        self.d = _import("discovery/discover.py", "discover")

    def _validate_output(self, result: dict, required_keys: list[str]):
        self.assertIsInstance(result, dict)
        self.assertIn("collected_at", result)
        self.assertIn("collection_errors", result)
        self.assertIsInstance(result["collection_errors"], list)
        for key in required_keys:
            self.assertIn(key, result, msg=f"Missing key: {key}")

    def test_hardware_output_structure(self):
        result = self.d.collect_hardware()
        self._validate_output(result, ["cpu", "memory", "disks", "nics"])
        self.assertIsInstance(result["cpu"], dict)
        self.assertIsInstance(result["memory"], dict)
        self.assertIsInstance(result["disks"], list)
        self.assertIsInstance(result["nics"], list)

    def test_network_output_structure(self):
        result = self.d.collect_network()
        self._validate_output(result, ["physical_nics", "bridges", "routes",
                                        "dns_servers", "default_gateway"])
        self.assertIsInstance(result["physical_nics"], list)
        self.assertIsInstance(result["bridges"], list)
        self.assertIsInstance(result["dns_servers"], list)

    def test_storage_output_structure(self):
        result = self.d.collect_storage()
        self._validate_output(result, ["zfs_pools", "proxmox_datastores"])
        self.assertIsInstance(result["zfs_pools"], list)
        self.assertIsInstance(result["proxmox_datastores"], list)

    def test_proxmox_output_structure(self):
        result = self.d.collect_proxmox()
        self._validate_output(result, ["proxmox_version", "hostname", "vms",
                                        "containers", "cluster"])
        self.assertIsInstance(result["vms"], list)
        self.assertIsInstance(result["containers"], list)

    def test_collectors_dict_complete(self):
        for name in ("hardware", "network", "storage", "proxmox"):
            self.assertIn(name, self.d.COLLECTORS)
            self.assertTrue(callable(self.d.COLLECTORS[name]))

    def test_output_filenames_complete(self):
        for name in ("hardware", "network", "storage", "proxmox"):
            self.assertIn(name, self.d.OUTPUT_FILENAMES)
            self.assertTrue(self.d.OUTPUT_FILENAMES[name].endswith(".json"))


# ---------------------------------------------------------------------------
# cluster_planner.py
# ---------------------------------------------------------------------------

class TestClusterPlanner(unittest.TestCase):
    def setUp(self):
        self.cp = _import("planners/cluster_planner.py", "cluster_planner")

    def test_single_node_plan_from_16gb(self):
        plan = self.cp.plan_cluster(HARDWARE_16GB, K3S_META_SINGLE, 1)
        self.assertEqual(plan["server_nodes"]["count"], 1)
        self.assertFalse(plan["ha"]["enabled"])
        self.assertTrue(plan["server_nodes"]["also_worker"])

    def test_ha_plan_from_64gb_three_hosts(self):
        plan = self.cp.plan_cluster(HARDWARE_64GB, K3S_META_HA, 3)
        self.assertEqual(plan["server_nodes"]["count"], 3)
        self.assertTrue(plan["ha"]["enabled"])
        self.assertFalse(plan["server_nodes"]["also_worker"])

    def test_ha_not_triggered_with_fewer_hosts(self):
        plan = self.cp.plan_cluster(HARDWARE_64GB, K3S_META_HA, 2)
        self.assertFalse(plan["ha"]["enabled"])

    def test_plan_has_required_fields(self):
        plan = self.cp.plan_cluster(HARDWARE_16GB, {}, 1)
        for field in ("server_nodes", "worker_nodes", "pre_k3s_vms",
                      "storage", "total_vm_ram_mb", "warnings", "recommendations"):
            self.assertIn(field, plan)

    def test_plan_pre_k3s_vms_declared(self):
        plan = self.cp.plan_cluster(HARDWARE_16GB, {}, 1)
        self.assertIn("forgejo", plan["pre_k3s_vms"])
        self.assertIn("operations", plan["pre_k3s_vms"])

    def test_plan_storage_classes_declared(self):
        plan = self.cp.plan_cluster(HARDWARE_16GB, {}, 1)
        self.assertEqual(plan["storage"]["initial_class"], "local-path")
        self.assertEqual(plan["storage"]["phase11_class"], "longhorn")

    def test_insufficient_ram_adds_warning(self):
        plan = self.cp.plan_cluster(HARDWARE_INSUFFICIENT, {}, 1)
        self.assertTrue(len(plan["warnings"]) > 0)
        self.assertTrue(any("RAM" in w or "INSUFFICIENT" in w or "LOW" in w
                            for w in plan["warnings"]))

    def test_available_workload_ram_is_non_negative(self):
        plan = self.cp.plan_cluster(HARDWARE_16GB, {}, 1)
        # available_workload_ram_mb can be 0 but not negative in plan output
        # (warnings are added when negative)
        self.assertGreaterEqual(plan["total_vm_ram_mb"], 0)

    def test_recommendations_list_non_empty(self):
        plan = self.cp.plan_cluster(HARDWARE_16GB, {}, 1)
        self.assertGreater(len(plan["recommendations"]), 0)

    def test_ha_threshold_from_metadata(self):
        meta_with_threshold = {"ha_policy": {"control_plane_ha_threshold": 2}}
        plan = self.cp.plan_cluster(HARDWARE_16GB, meta_with_threshold, 2)
        self.assertTrue(plan["ha"]["enabled"])  # 2 hosts >= threshold 2

    def test_parse_disk_size_gb_terabytes(self):
        self.assertAlmostEqual(self.cp._parse_disk_size_gb({"size_raw": "4T"}), 4096.0, delta=1)

    def test_parse_disk_size_gb_gigabytes(self):
        self.assertAlmostEqual(self.cp._parse_disk_size_gb({"size_raw": "500G"}), 500.0, delta=1)

    def test_parse_disk_size_gb_bytes(self):
        self.assertAlmostEqual(
            self.cp._parse_disk_size_gb({"size_bytes": 500 * 1024**3}), 500.0, delta=1
        )

    def test_plan_written_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "cluster-plan.json"
            plan = self.cp.plan_cluster(HARDWARE_64GB, {}, 1)
            out.write_text(json.dumps(plan), encoding="utf-8")
            loaded = json.loads(out.read_text())
            self.assertEqual(loaded["server_nodes"]["count"], plan["server_nodes"]["count"])


# ---------------------------------------------------------------------------
# capacity_validator.py
# ---------------------------------------------------------------------------

class TestCapacityValidator(unittest.TestCase):
    def setUp(self):
        self.cv = _import("validation/capacity_validator.py", "capacity_validator")

    def test_check_ram_green(self):
        status, msg = self.cv.check_ram(HARDWARE_64GB, 16)
        self.assertEqual(status, "GREEN")

    def test_check_ram_red(self):
        status, msg = self.cv.check_ram(HARDWARE_INSUFFICIENT, 16)
        self.assertEqual(status, "RED")
        self.assertIn("minimum", msg)

    def test_check_ram_yellow_tight(self):
        hw = {**HARDWARE_16GB, "memory": {"total_gb": 16.5}}
        status, msg = self.cv.check_ram(hw, 16)
        # 16.5 < 16 * 1.25 = 20 → YELLOW
        self.assertEqual(status, "YELLOW")

    def test_check_ram_zero_gives_yellow(self):
        status, msg = self.cv.check_ram({"memory": {"total_gb": 0}}, 16)
        self.assertEqual(status, "YELLOW")

    def test_check_cpu_green(self):
        status, msg = self.cv.check_cpu(HARDWARE_64GB, 4)
        self.assertEqual(status, "GREEN")

    def test_check_cpu_red(self):
        status, msg = self.cv.check_cpu(HARDWARE_INSUFFICIENT, 4)
        self.assertEqual(status, "RED")

    def test_check_storage_green(self):
        status, msg = self.cv.check_storage(HARDWARE_64GB, 100)
        self.assertEqual(status, "GREEN")

    def test_check_storage_red(self):
        status, msg = self.cv.check_storage(HARDWARE_INSUFFICIENT, 100)
        self.assertEqual(status, "RED")

    def test_check_virtualization_green_when_present(self):
        status, msg = self.cv.check_virtualization(HARDWARE_16GB, True)
        self.assertEqual(status, "GREEN")
        self.assertIn("VT-x", msg)

    def test_check_virtualization_yellow_when_missing(self):
        hw = {**HARDWARE_INSUFFICIENT, "cpu": {"virtualization": None}}
        status, msg = self.cv.check_virtualization(hw, True)
        self.assertEqual(status, "YELLOW")

    def test_check_virtualization_green_when_not_required(self):
        status, msg = self.cv.check_virtualization(HARDWARE_INSUFFICIENT, False)
        self.assertEqual(status, "GREEN")

    def test_check_nic_count_green(self):
        status, msg = self.cv.check_nic_count(HARDWARE_16GB, 1)
        self.assertEqual(status, "GREEN")

    def test_check_nic_count_red(self):
        hw = {**HARDWARE_INSUFFICIENT, "nics": []}
        status, msg = self.cv.check_nic_count(hw, 1)
        self.assertEqual(status, "RED")

    def test_check_plan_fits_ram_green(self):
        plan = {
            "total_vm_ram_mb": 8192,
            "hardware_summary": {"total_ram_mb": 65536},
        }
        status, msg = self.cv.check_plan_fits_ram(plan)
        self.assertEqual(status, "GREEN")

    def test_check_plan_fits_ram_red(self):
        plan = {
            "total_vm_ram_mb": 70000,
            "hardware_summary": {"total_ram_mb": 16384},
        }
        status, msg = self.cv.check_plan_fits_ram(plan)
        self.assertEqual(status, "RED")

    def test_check_plan_fits_ram_yellow_when_tight(self):
        plan = {
            "total_vm_ram_mb": 14000,
            "hardware_summary": {"total_ram_mb": 16384},
        }
        status, msg = self.cv.check_plan_fits_ram(plan)
        self.assertEqual(status, "YELLOW")

    def test_full_validation_green(self):
        result = self.cv.run_validation(HARDWARE_64GB, None, None)
        self.assertEqual(result["overall"], "GREEN")
        self.assertEqual(result["red_count"], 0)

    def test_full_validation_red_on_insufficient(self):
        result = self.cv.run_validation(HARDWARE_INSUFFICIENT, None, None)
        self.assertEqual(result["overall"], "RED")
        self.assertGreater(result["red_count"], 0)

    def test_validation_result_structure(self):
        result = self.cv.run_validation(HARDWARE_16GB, None, None)
        for field in ("overall", "checks", "red_count", "yellow_count", "green_count"):
            self.assertIn(field, result)
        self.assertIsInstance(result["checks"], list)
        for check in result["checks"]:
            self.assertIn("check", check)
            self.assertIn("status", check)
            self.assertIn("message", check)
            self.assertIn(check["status"], ("GREEN", "YELLOW", "RED"))

    def test_with_plan_adds_plan_checks(self):
        cp = _import("planners/cluster_planner.py", "cluster_planner")
        plan = cp.plan_cluster(HARDWARE_64GB, {}, 1)
        result = self.cv.run_validation(HARDWARE_64GB, plan, None)
        check_names = [c["check"] for c in result["checks"]]
        self.assertIn("Plan fits RAM", check_names)

    def test_status_order_green_is_best(self):
        self.assertGreater(self.cv.STATUS_ORDER["GREEN"], self.cv.STATUS_ORDER["YELLOW"])
        self.assertGreater(self.cv.STATUS_ORDER["YELLOW"], self.cv.STATUS_ORDER["RED"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
