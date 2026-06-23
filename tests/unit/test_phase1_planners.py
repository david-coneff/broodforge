"""
Tests for Phase 1 planners and readiness validator.

Covers:
  - storage_planner.py: topology decisions, pool planning, mixed disk handling
  - network_planner.py: bridge/gateway/DNS/NIC validation checks
  - naming_planner.py: VM naming, IP assignment, KeePass paths, DNS registry
  - readiness_validator.py: gate logic, individual checks, overall status

Run: py -3 tests/unit/test_phase1_planners.py
"""

import importlib.util
import json
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

STORAGE_REPORT_EMPTY = {
    "collected_at": "2026-05-31 16:00:00 UTC",
    "zfs_pools": [],
    "proxmox_datastores": [],
    "collection_errors": [],
}

HARDWARE_2_SSD = {
    "disks": [
        {"name": "sda", "size_raw": "2T", "type": "SSD", "interface": "SATA"},
        {"name": "sdb", "size_raw": "2T", "type": "SSD", "interface": "SATA"},
    ]
}

HARDWARE_4_HDD = {
    "disks": [
        {"name": f"sd{c}", "size_raw": "4T", "type": "HDD", "interface": "SATA"}
        for c in "abcd"
    ]
}

HARDWARE_MIXED = {
    "disks": [
        {"name": "nvme0n1", "size_raw": "1T", "type": "NVMe", "interface": "NVMe"},
        {"name": "sda", "size_raw": "4T", "type": "HDD", "interface": "SATA"},
        {"name": "sdb", "size_raw": "4T", "type": "HDD", "interface": "SATA"},
    ]
}

NETWORK_REPORT_WITH_BRIDGE = {
    "collected_at": "2026-05-31 16:00:00 UTC",
    "physical_nics": [{"name": "enp2s0", "mac": "aa:bb:cc:dd:ee:ff", "state": "UP"}],
    "bridges": [{"name": "vmbr0", "addresses": ["192.168.1.10/24"], "state": "UP"}],
    "default_gateway": "192.168.1.1",
    "routes": [{"dst": "default", "gateway": "192.168.1.1", "dev": "vmbr0"}],
    "dns_servers": ["192.168.1.1", "8.8.8.8"],
    "search_domains": ["internal"],
    "collection_errors": [],
}

NETWORK_REPORT_NO_BRIDGE = {
    "collected_at": "2026-05-31 16:00:00 UTC",
    "physical_nics": [{"name": "enp2s0", "mac": "aa:bb:cc:dd:ee:ff"}],
    "bridges": [],
    "default_gateway": "192.168.1.1",
    "routes": [{"dst": "default", "gateway": "192.168.1.1"}],
    "dns_servers": [],
    "search_domains": [],
    "collection_errors": [],
}

TOPOLOGY_META = {
    "management_network": {
        "cidr": "192.168.1.0/24",
        "gateway": "192.168.1.1",
        "nameservers": ["192.168.1.1", "8.8.8.8"],
        "search_domain": "internal",
    },
    "proxmox_host": {"hostname": "pve01", "ip": "192.168.1.10"},
    "bridges": [{"name": "vmbr0"}],
    "vm_nic_interface": "ens18",
}

CELL_META = {
    "cell_id": "proxmox-cell-a",
    "host_identity": {"hostname": "pve01"},
    "keepass_config": {"root_path": "Infrastructure"},
}

VMS_META = [
    {"name": "forgejo", "vmid": 100, "role": "forgejo"},
    {"name": "operations", "vmid": 101, "role": "operations"},
    {"name": "k3s-server-01", "vmid": 110, "role": "k3s-server"},
]

NETWORK_META = {
    "management_network": {"cidr": "192.168.1.0/24", "search_domain": "internal"}
}


# ---------------------------------------------------------------------------
# Storage planner tests
# ---------------------------------------------------------------------------

class TestStoragePlannerTopology(unittest.TestCase):
    def setUp(self):
        self.sp = _import("planners/storage_planner.py", "storage_planner")

    def test_single_disk_stripe(self):
        topology, rationale = self.sp.recommend_topology(1, ["SSD"])
        self.assertEqual(topology, "stripe")
        self.assertIn("no redundancy", rationale.lower())

    def test_two_disks_mirror(self):
        topology, _ = self.sp.recommend_topology(2, ["SSD", "SSD"])
        self.assertEqual(topology, "mirror")

    def test_three_disks_raidz(self):
        topology, _ = self.sp.recommend_topology(3, ["HDD"] * 3)
        self.assertEqual(topology, "raidz")

    def test_five_disks_raidz(self):
        topology, _ = self.sp.recommend_topology(5, ["HDD"] * 5)
        self.assertEqual(topology, "raidz")

    def test_six_disks_raidz2(self):
        topology, _ = self.sp.recommend_topology(6, ["HDD"] * 6)
        self.assertEqual(topology, "raidz2")

    def test_nine_disks_raidz3(self):
        topology, _ = self.sp.recommend_topology(9, ["HDD"] * 9)
        self.assertEqual(topology, "raidz3")

    def test_zero_disks_error(self):
        topology, _ = self.sp.recommend_topology(0, [])
        self.assertEqual(topology, "error")

    def test_classify_disks_nvme(self):
        disks = [{"type": "NVMe", "interface": "NVMe"}]
        groups = self.sp.classify_disks(disks)
        self.assertEqual(len(groups["nvme"]), 1)
        self.assertEqual(len(groups["ssd"]), 0)
        self.assertEqual(len(groups["hdd"]), 0)

    def test_classify_disks_mixed(self):
        disks = [
            {"type": "NVMe", "interface": "NVMe"},
            {"type": "HDD", "interface": "SATA"},
            {"type": "SSD", "interface": "SATA"},
        ]
        groups = self.sp.classify_disks(disks)
        self.assertEqual(len(groups["nvme"]), 1)
        self.assertEqual(len(groups["ssd"]), 1)
        self.assertEqual(len(groups["hdd"]), 1)

    def test_usable_capacity_mirror(self):
        gb = self.sp.estimate_usable_gb(2, "mirror", 2000)
        self.assertEqual(gb, 2000)  # 1 disk usable of 2-disk mirror

    def test_usable_capacity_raidz(self):
        gb = self.sp.estimate_usable_gb(4, "raidz", 4000)
        self.assertEqual(gb, 12000)  # 3 disks usable of 4

    def test_usable_capacity_raidz2(self):
        gb = self.sp.estimate_usable_gb(6, "raidz2", 4000)
        self.assertEqual(gb, 16000)  # 4 disks usable of 6

    def test_parse_disk_size_tb(self):
        self.assertAlmostEqual(self.sp._disk_size_gb({"size_raw": "2T"}), 2048.0, delta=1)

    def test_parse_disk_size_gb(self):
        self.assertAlmostEqual(self.sp._disk_size_gb({"size_raw": "500G"}), 500.0, delta=1)


class TestStoragePlannerPlanGeneration(unittest.TestCase):
    def setUp(self):
        self.sp = _import("planners/storage_planner.py", "storage_planner")

    def test_two_ssd_gives_mirror(self):
        plan = self.sp.plan_storage(STORAGE_REPORT_EMPTY, HARDWARE_2_SSD)
        self.assertEqual(len(plan["pools"]), 1)
        self.assertEqual(plan["pools"][0]["topology"], "mirror")

    def test_four_hdd_gives_raidz(self):
        plan = self.sp.plan_storage(STORAGE_REPORT_EMPTY, HARDWARE_4_HDD)
        self.assertEqual(plan["pools"][0]["topology"], "raidz")

    def test_mixed_disks_gives_two_pools(self):
        plan = self.sp.plan_storage(STORAGE_REPORT_EMPTY, HARDWARE_MIXED)
        self.assertEqual(len(plan["pools"]), 2)
        purposes = {p["purpose"] for p in plan["pools"]}
        self.assertIn("primary", purposes)
        self.assertIn("secondary", purposes)

    def test_plan_includes_datastores(self):
        plan = self.sp.plan_storage(STORAGE_REPORT_EMPTY, HARDWARE_2_SSD)
        self.assertGreater(len(plan["recommended_datastores"]), 0)
        # local storage always included
        self.assertTrue(any(d["name"] == "local" for d in plan["recommended_datastores"]))

    def test_plan_has_required_fields(self):
        plan = self.sp.plan_storage(STORAGE_REPORT_EMPTY, HARDWARE_2_SSD)
        for field in ("pools", "recommended_datastores", "ashift",
                      "warnings", "errors", "disk_inventory"):
            self.assertIn(field, plan)

    def test_single_disk_adds_warning(self):
        hw_one_disk = {"disks": [{"name": "sda", "size_raw": "1T", "type": "SSD"}]}
        plan = self.sp.plan_storage(STORAGE_REPORT_EMPTY, hw_one_disk)
        self.assertTrue(len(plan["warnings"]) > 0)

    def test_no_disks_adds_error_or_empty_pools(self):
        hw_no_disks = {"disks": []}
        plan = self.sp.plan_storage(STORAGE_REPORT_EMPTY, hw_no_disks)
        # Either no pools or an error — not both silently empty and clean
        self.assertTrue(len(plan["pools"]) == 0 or len(plan["errors"]) > 0
                        or len(plan["warnings"]) > 0)

    def test_ashift_is_12(self):
        plan = self.sp.plan_storage(STORAGE_REPORT_EMPTY, HARDWARE_2_SSD)
        self.assertEqual(plan["ashift"], 12)

    def test_existing_pools_recorded(self):
        storage_with_pools = {**STORAGE_REPORT_EMPTY, "zfs_pools": [{"name": "rpool"}]}
        plan = self.sp.plan_storage(storage_with_pools, HARDWARE_2_SSD)
        self.assertIn("rpool", plan["existing_pools"])


# ---------------------------------------------------------------------------
# Network planner tests
# ---------------------------------------------------------------------------

class TestNetworkPlannerChecks(unittest.TestCase):
    def setUp(self):
        self.np = _import("planners/network_planner.py", "network_planner")

    def test_bridge_exists_green(self):
        status, msg = self.np.check_bridge_exists(NETWORK_REPORT_WITH_BRIDGE, "vmbr0")
        self.assertEqual(status, "GREEN")

    def test_bridge_missing_red(self):
        status, msg = self.np.check_bridge_exists(NETWORK_REPORT_WITH_BRIDGE, "vmbr99")
        self.assertEqual(status, "RED")
        self.assertIn("vmbr99", msg)

    def test_bridge_empty_discovery_red(self):
        status, msg = self.np.check_bridge_exists(NETWORK_REPORT_NO_BRIDGE, "vmbr0")
        self.assertEqual(status, "RED")

    def test_gateway_matches_default_green(self):
        status, msg = self.np.check_gateway_reachable(NETWORK_REPORT_WITH_BRIDGE, "192.168.1.1")
        self.assertEqual(status, "GREEN")

    def test_gateway_mismatch_red(self):
        status, msg = self.np.check_gateway_reachable(NETWORK_REPORT_WITH_BRIDGE, "10.0.0.1")
        self.assertEqual(status, "RED")

    def test_dns_match_green(self):
        status, msg = self.np.check_dns_servers(
            NETWORK_REPORT_WITH_BRIDGE, ["192.168.1.1", "8.8.8.8"]
        )
        self.assertEqual(status, "GREEN")

    def test_dns_partial_yellow(self):
        status, msg = self.np.check_dns_servers(
            NETWORK_REPORT_WITH_BRIDGE, ["192.168.1.1", "1.1.1.1"]
        )
        self.assertEqual(status, "YELLOW")

    def test_dns_no_match_yellow(self):
        status, msg = self.np.check_dns_servers(
            NETWORK_REPORT_WITH_BRIDGE, ["9.9.9.9"]
        )
        self.assertEqual(status, "YELLOW")

    def test_nic_ens18_green(self):
        status, msg = self.np.check_nic_interface(NETWORK_REPORT_WITH_BRIDGE, "ens18")
        self.assertEqual(status, "GREEN")

    def test_cidr_host_ip_in_range_green(self):
        status, msg = self.np.check_management_cidr(
            NETWORK_REPORT_WITH_BRIDGE, "192.168.1.0/24", "192.168.1.10"
        )
        self.assertEqual(status, "GREEN")

    def test_cidr_host_ip_out_of_range_yellow(self):
        status, msg = self.np.check_management_cidr(
            NETWORK_REPORT_WITH_BRIDGE, "10.0.0.0/24", "192.168.1.10"
        )
        self.assertEqual(status, "YELLOW")


class TestNetworkPlannerPlanGeneration(unittest.TestCase):
    def setUp(self):
        self.np = _import("planners/network_planner.py", "network_planner")

    def test_green_plan_from_matching_config(self):
        plan = self.np.plan_network(NETWORK_REPORT_WITH_BRIDGE, TOPOLOGY_META)
        self.assertEqual(plan["overall"], "GREEN")
        self.assertEqual(plan["red_count"], 0)

    def test_red_plan_from_missing_bridge(self):
        plan = self.np.plan_network(NETWORK_REPORT_NO_BRIDGE, TOPOLOGY_META)
        self.assertGreater(plan["red_count"], 0)
        self.assertEqual(plan["overall"], "RED")

    def test_plan_has_required_fields(self):
        plan = self.np.plan_network(NETWORK_REPORT_WITH_BRIDGE, TOPOLOGY_META)
        for field in ("overall", "findings", "validated_topology",
                      "red_count", "yellow_count", "green_count"):
            self.assertIn(field, plan)

    def test_validated_topology_has_gateway(self):
        plan = self.np.plan_network(NETWORK_REPORT_WITH_BRIDGE, TOPOLOGY_META)
        self.assertIn("gateway", plan["validated_topology"])

    def test_findings_list_non_empty(self):
        plan = self.np.plan_network(NETWORK_REPORT_WITH_BRIDGE, TOPOLOGY_META)
        self.assertGreater(len(plan["findings"]), 0)
        for finding in plan["findings"]:
            self.assertIn("check", finding)
            self.assertIn("status", finding)
            self.assertIn("message", finding)


# ---------------------------------------------------------------------------
# Naming planner tests
# ---------------------------------------------------------------------------

class TestNamingPlanner(unittest.TestCase):
    def setUp(self):
        self.np = _import("planners/naming_planner.py", "naming_planner")

    def test_plan_has_required_fields(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        for field in ("cell_id", "hostname", "fqdn", "kp_root",
                      "vms", "keepass_paths", "dns_registry",
                      "repository_names", "archive_prefix"):
            self.assertIn(field, plan)

    def test_cell_id_preserved(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        self.assertEqual(plan["cell_id"], "proxmox-cell-a")

    def test_hostname_from_cell_identity(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        self.assertEqual(plan["hostname"], "pve01")

    def test_kp_root_from_cell_meta(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        self.assertEqual(plan["kp_root"], "Infrastructure")

    def test_all_vms_have_entries(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        vm_names = {vm["name"] for vm in plan["vms"]}
        for vm in VMS_META:
            self.assertIn(vm["name"], vm_names)

    def test_vms_have_required_fields(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        for vm in plan["vms"]:
            for field in ("name", "vmid", "hostname", "fqdn", "ip"):
                self.assertIn(field, vm)

    def test_fqdn_uses_search_domain(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        for vm in plan["vms"]:
            self.assertTrue(vm["fqdn"].endswith(".internal"),
                            msg=f"VM {vm['name']} fqdn should end with .internal")

    def test_keepass_paths_generated(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        kp = plan["keepass_paths"]
        self.assertGreater(len(kp), 0)
        # All paths should start with the KeePass root
        for path in kp.values():
            self.assertTrue(path.startswith("Infrastructure"),
                            msg=f"Path {path!r} should start with root 'Infrastructure'")

    def test_dns_registry_has_entries(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        self.assertGreater(len(plan["dns_registry"]), 0)

    def test_repository_names_generated(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        repos = plan["repository_names"]
        for purpose in ("bootstrap", "infrastructure", "ansible"):
            self.assertIn(purpose, repos)
            self.assertIn("proxmox-cell-a", repos[purpose])

    def test_archive_prefix_is_cell_id(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        self.assertEqual(plan["archive_prefix"], "proxmox-cell-a")

    def test_ips_assigned_from_cidr(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        vms_with_ips = [vm for vm in plan["vms"] if vm["ip"] != "UNRESOLVED"]
        self.assertGreater(len(vms_with_ips), 0)
        # All IPs should be within 192.168.1.x
        for vm in vms_with_ips:
            self.assertTrue(vm["ip"].startswith("192.168.1."),
                            msg=f"IP {vm['ip']} should be in 192.168.1.x subnet")

    def test_no_errors_with_complete_metadata(self):
        plan = self.np.plan_naming(CELL_META, VMS_META, NETWORK_META, {})
        self.assertEqual(plan["errors"], [])

    def test_empty_vms_gives_no_vm_declarations(self):
        plan = self.np.plan_naming(CELL_META, [], NETWORK_META, {})
        self.assertEqual(len(plan["vms"]), 0)


# ---------------------------------------------------------------------------
# Readiness validator tests
# ---------------------------------------------------------------------------

class TestReadinessValidator(unittest.TestCase):
    def setUp(self):
        self.rv = _import("validation/readiness_validator.py", "readiness_validator")

    def _make_plans(self, tmpdir: Path, plans: dict) -> None:
        """Write plan JSON files to a temp directory."""
        for name, data in plans.items():
            (tmpdir / name).write_text(json.dumps(data), encoding="utf-8")

    def test_check_plan_exists_green(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "cluster-plan.json").write_text("{}", encoding="utf-8")
            status, msg = self.rv.check_plan_exists(d, "cluster-plan.json")
            self.assertEqual(status, "GREEN")

    def test_check_plan_exists_red(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            status, msg = self.rv.check_plan_exists(Path(tmpdir), "missing.json")
            self.assertEqual(status, "RED")

    def test_check_capacity_green(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "capacity-check.json").write_text(
                json.dumps({"overall": "GREEN", "red_count": 0}), encoding="utf-8"
            )
            status, msg = self.rv.check_capacity(d)
            self.assertEqual(status, "GREEN")

    def test_check_capacity_red(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "capacity-check.json").write_text(
                json.dumps({"overall": "RED", "red_count": 2}), encoding="utf-8"
            )
            status, msg = self.rv.check_capacity(d)
            self.assertEqual(status, "RED")

    def test_check_cluster_plan_green(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "cluster-plan.json").write_text(
                json.dumps({"server_nodes": {"count": 1}, "warnings": []}),
                encoding="utf-8"
            )
            status, msg = self.rv.check_cluster_plan(d)
            self.assertEqual(status, "GREEN")

    def test_check_cluster_plan_red_no_servers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "cluster-plan.json").write_text(
                json.dumps({"server_nodes": {"count": 0}, "warnings": []}),
                encoding="utf-8"
            )
            status, msg = self.rv.check_cluster_plan(d)
            self.assertEqual(status, "RED")

    def test_check_storage_plan_green(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "storage-plan.json").write_text(
                json.dumps({"pools": [{"name": "rpool"}], "errors": [], "warnings": []}),
                encoding="utf-8"
            )
            status, msg = self.rv.check_storage_plan(d)
            self.assertEqual(status, "GREEN")

    def test_check_storage_plan_red_no_pools(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "storage-plan.json").write_text(
                json.dumps({"pools": [], "errors": [], "warnings": []}),
                encoding="utf-8"
            )
            status, msg = self.rv.check_storage_plan(d)
            self.assertEqual(status, "RED")

    def test_check_naming_plan_green(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "naming-plan.json").write_text(
                json.dumps({
                    "vms": [{"name": "forgejo", "ip": "192.168.1.20"}],
                    "host_ip": "192.168.1.10",
                    "errors": [],
                    "warnings": [],
                }),
                encoding="utf-8"
            )
            status, msg = self.rv.check_naming_plan(d)
            self.assertEqual(status, "GREEN")

    def test_check_naming_plan_yellow_unresolved_ip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            d = Path(tmpdir)
            (d / "naming-plan.json").write_text(
                json.dumps({
                    "vms": [{"name": "forgejo", "ip": "UNRESOLVED"}],
                    "host_ip": "UNRESOLVED",
                    "errors": [],
                    "warnings": [],
                }),
                encoding="utf-8"
            )
            status, msg = self.rv.check_naming_plan(d)
            self.assertEqual(status, "YELLOW")

    def test_full_readiness_green_with_all_plans(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plans = Path(tmpdir) / "plans"
            validation = Path(tmpdir) / "validation"
            plans.mkdir(); validation.mkdir()

            # Write valid plans
            (plans / "cluster-plan.json").write_text(
                json.dumps({"server_nodes": {"count": 1}, "warnings": []}),
                encoding="utf-8"
            )
            (plans / "storage-plan.json").write_text(
                json.dumps({"pools": [{"name": "rpool"}], "errors": [], "warnings": []}),
                encoding="utf-8"
            )
            (plans / "network-plan.json").write_text(
                json.dumps({"overall": "GREEN", "red_count": 0, "yellow_count": 0}),
                encoding="utf-8"
            )
            (plans / "naming-plan.json").write_text(
                json.dumps({
                    "vms": [{"name": "forgejo", "ip": "192.168.1.20"}],
                    "host_ip": "192.168.1.10",
                    "errors": [], "warnings": [],
                }),
                encoding="utf-8"
            )
            (validation / "capacity-check.json").write_text(
                json.dumps({"overall": "GREEN", "red_count": 0}),
                encoding="utf-8"
            )

            result = self.rv.run_readiness(plans, validation)
            self.assertTrue(result["ready_to_generate"])
            self.assertEqual(result["red_count"], 0)

    def test_full_readiness_blocked_by_missing_plan(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plans = Path(tmpdir) / "plans"
            validation = Path(tmpdir) / "validation"
            plans.mkdir(); validation.mkdir()
            # No plan files written — all checks will fail/warn
            result = self.rv.run_readiness(plans, validation)
            self.assertFalse(result["ready_to_generate"])

    def test_result_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plans = Path(tmpdir) / "plans"
            validation = Path(tmpdir) / "validation"
            plans.mkdir(); validation.mkdir()
            result = self.rv.run_readiness(plans, validation)
            for field in ("overall", "ready_to_generate", "findings",
                          "red_count", "yellow_count", "green_count"):
                self.assertIn(field, result)
            self.assertIsInstance(result["findings"], list)

    def test_status_order_green_best(self):
        self.assertGreater(
            self.rv.STATUS_ORDER["GREEN"],
            self.rv.STATUS_ORDER["YELLOW"]
        )
        self.assertGreater(
            self.rv.STATUS_ORDER["YELLOW"],
            self.rv.STATUS_ORDER["RED"]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
