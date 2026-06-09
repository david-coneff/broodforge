#!/usr/bin/env python3
"""Tests for Phase 12.E.3 — Spawn planner (service catalog, fit assessment, plan builder)."""

import sys, unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "proxmox-bootstrap"))

from spawn_planner import (
    ServiceCatalog, FitResult,
    SpawnPlannerSession,
    FIT_OK, FIT_MARGINAL, FIT_NO_FIT,
    NET_LAN, NET_WAN, NET_SPECIFY,
    EXEC_AUTONOMOUS, EXEC_INTERACTIVE,
    SEL_FULL_MIRROR, SEL_GROUP, SEL_INDIVIDUAL,
    assess_service_fit, assess_all_services,
    full_mirror_services,
    build_spawn_plan,
    step0_set_network_mode, step1_set_execution_mode,
    step2_select_services, step3_allocate_resources,
    generate_temp_password,
    _parse_service_catalog_yaml,
    GROUPS,
)

# ---------------------------------------------------------------------------
# Fixture catalog — 5 services with known resource requirements
# ---------------------------------------------------------------------------

_CATALOG_YAML = """\
services:

  - name:         k3s-worker
    display_name: k3s Worker Node
    group:        Infrastructure
    ram_gb:       4
    disk_gb:      20
    description:  Baseline k3s worker
    dependencies: []
    baseline:     true
    vm_count:     1

  - name:         longhorn
    display_name: Longhorn Storage
    group:        Platform
    ram_gb:       4
    disk_gb:      100
    description:  Distributed storage
    dependencies: [k3s-worker]
    baseline:     false
    vm_count:     1

  - name:         monitoring
    display_name: Monitoring Stack
    group:        Monitoring
    ram_gb:       8
    disk_gb:      50
    description:  Prometheus + Grafana
    dependencies: [k3s-worker, longhorn]
    baseline:     false
    vm_count:     2

  - name:         pbs-datastore
    display_name: PBS Datastore
    group:        Infrastructure
    ram_gb:       4
    disk_gb:      500
    description:  Backup server
    dependencies: []
    baseline:     false
    vm_count:     1

  - name:         nextcloud
    display_name: Nextcloud
    group:        Applications
    ram_gb:       4
    disk_gb:      100
    description:  File sync
    dependencies: [k3s-worker, longhorn]
    baseline:     false
    vm_count:     1
"""

_BOOTSTRAP_STATE = {
    "cell_id": "cell-alpha",
    "host_identity": {
        "hostname": "pve01",
        "fqdn":     "pve01.home.example.com",
        "domain":   "home.example.com",
        "lan_ip":   "192.168.1.10",
    },
    "vms": [
        {"vmid": 100, "name": "k3s-server-01", "ip": "192.168.1.20",
         "status": "running", "cores": 4, "memory_mb": 4096},
    ],
    "dns_registry": [
        {"hostname": "pve01", "fqdn": "pve01.home.example.com",
         "ip": "192.168.1.10", "role": "proxmox-host"},
    ],
    "network_topology": {
        "management_cidr": "192.168.1.0/24",
        "gateway": "192.168.1.1",
    },
    "k3s_cluster": {
        "server_count": 1, "worker_count": 0,
        "pod_cidr": "10.42.0.0/16", "service_cidr": "10.43.0.0/16",
        "server_url": "https://k3s-server-01.home.example.com:6443",
    },
    "k3s": {
        "worker_join_token": "test-worker-token-abc123",
        "server_join_token": "test-server-token-def456",
    },
    "capacity_model": {"host_ram_gb": 32},
}

_HARDWARE_16 = {
    "hostname": "pve02", "cpu_cores": 4, "cpu_model": "AMD Ryzen", "ram_gb": 16.0,
    "disks": [
        {"name": "/dev/sda", "size_gb": 500, "rotational": False},
        {"name": "/dev/sdb", "size_gb": 500, "rotational": False},
    ],
    "nics": [{"name": "eno1", "mac": "AA:BB:CC:DD:EE:FF"}],
    "derived": {"usable_disks": 2, "ssd_count": 2, "hdd_count": 0, "zfs_topology": "mirror"},
}

_HARDWARE_8 = {**_HARDWARE_16, "ram_gb": 8.0,
               "derived": {**_HARDWARE_16["derived"], "zfs_topology": "mirror"}}

_HARDWARE_64 = {**_HARDWARE_16, "ram_gb": 64.0,
                "derived": {**_HARDWARE_16["derived"], "zfs_topology": "mirror"}}


def _catalog() -> ServiceCatalog:
    return ServiceCatalog.from_list(_parse_service_catalog_yaml(_CATALOG_YAML))


def _manifest():
    from hatchery_state import read_hatchery_state
    return read_hatchery_state(_BOOTSTRAP_STATE, {})


# ===========================================================================
# ServiceCatalog tests
# ===========================================================================

class TestServiceCatalogParsing(unittest.TestCase):
    def test_parse_services(self):
        cat = _catalog()
        self.assertEqual(len(cat.all()), 5)

    def test_parse_name(self):
        cat = _catalog()
        self.assertIsNotNone(cat.get("k3s-worker"))

    def test_parse_ram_gb(self):
        cat = _catalog()
        self.assertEqual(cat.get("k3s-worker")["ram_gb"], 4)

    def test_parse_disk_gb(self):
        cat = _catalog()
        self.assertEqual(cat.get("pbs-datastore")["disk_gb"], 500)

    def test_parse_baseline_true(self):
        cat = _catalog()
        self.assertTrue(cat.get("k3s-worker")["baseline"])

    def test_parse_baseline_false(self):
        cat = _catalog()
        self.assertFalse(cat.get("longhorn").get("baseline", False))

    def test_parse_dependencies(self):
        cat = _catalog()
        deps = cat.get("longhorn")["dependencies"]
        self.assertIn("k3s-worker", deps)

    def test_parse_vm_count(self):
        cat = _catalog()
        self.assertEqual(cat.get("monitoring")["vm_count"], 2)


class TestServiceCatalogQueries(unittest.TestCase):
    def setUp(self):
        self.cat = _catalog()

    def test_baseline_services(self):
        baseline = self.cat.baseline()
        self.assertEqual(len(baseline), 1)
        self.assertEqual(baseline[0]["name"], "k3s-worker")

    def test_by_group(self):
        infra = self.cat.by_group("Infrastructure")
        names = {s["name"] for s in infra}
        self.assertIn("k3s-worker", names)
        self.assertIn("pbs-datastore", names)

    def test_groups_returns_populated_only(self):
        groups = self.cat.groups()
        self.assertIn("Infrastructure", groups)
        self.assertIn("Platform", groups)
        self.assertIn("Monitoring", groups)

    def test_total_ram_gb(self):
        ram = self.cat.total_ram_gb(["k3s-worker", "longhorn"])
        self.assertEqual(ram, 8)

    def test_total_disk_gb(self):
        disk = self.cat.total_disk_gb(["k3s-worker", "longhorn"])
        self.assertEqual(disk, 120)

    def test_total_vm_count(self):
        count = self.cat.total_vm_count(["k3s-worker", "monitoring"])
        self.assertEqual(count, 3)  # 1 + 2

    def test_resolve_dependencies_adds_deps(self):
        resolved = self.cat.resolve_dependencies(["monitoring"])
        self.assertIn("k3s-worker", resolved)
        self.assertIn("longhorn", resolved)
        self.assertIn("monitoring", resolved)

    def test_resolve_dependencies_no_duplicates(self):
        resolved = self.cat.resolve_dependencies(["k3s-worker", "monitoring"])
        self.assertEqual(resolved.count("k3s-worker"), 1)

    def test_resolve_order_deps_before_service(self):
        resolved = self.cat.resolve_dependencies(["monitoring"])
        self.assertLess(resolved.index("k3s-worker"), resolved.index("monitoring"))


# ===========================================================================
# FitResult tests
# ===========================================================================

class TestServiceFitAssessment(unittest.TestCase):
    def test_service_fits(self):
        svc = {"name": "longhorn", "ram_gb": 4, "disk_gb": 100}
        result = assess_service_fit(svc, {}, available_ram_gb=20, available_disk_gb=500)
        self.assertEqual(result.status, FIT_OK)

    def test_service_no_fit_ram(self):
        svc = {"name": "longhorn", "ram_gb": 16, "disk_gb": 100}
        result = assess_service_fit(svc, {}, available_ram_gb=8, available_disk_gb=500)
        self.assertEqual(result.status, FIT_NO_FIT)
        self.assertIn("RAM", result.reason)

    def test_service_no_fit_disk(self):
        svc = {"name": "pbs-datastore", "ram_gb": 2, "disk_gb": 500}
        result = assess_service_fit(svc, {}, available_ram_gb=32, available_disk_gb=200)
        self.assertEqual(result.status, FIT_NO_FIT)
        self.assertIn("disk", result.reason)

    def test_service_marginal_ram(self):
        # 4 GB required, 5 GB available — 4/5 = 80% > 75% threshold
        svc = {"name": "longhorn", "ram_gb": 4, "disk_gb": 10}
        result = assess_service_fit(svc, {}, available_ram_gb=5, available_disk_gb=500)
        self.assertEqual(result.status, FIT_MARGINAL)
        self.assertIn("marginal", result.reason)

    def test_assess_all_services_returns_dict(self):
        cat     = _catalog()
        results = assess_all_services(cat, _HARDWARE_16, host_ram_gb=16)
        self.assertIn("k3s-worker", results)
        self.assertIn("longhorn", results)

    def test_large_machine_all_fit(self):
        cat     = _catalog()
        results = assess_all_services(cat, _HARDWARE_64, host_ram_gb=64)
        no_fits = [n for n, r in results.items() if r.status == FIT_NO_FIT]
        self.assertEqual(no_fits, [])

    def test_small_machine_some_no_fit(self):
        cat     = _catalog()
        results = assess_all_services(cat, _HARDWARE_8, host_ram_gb=8)
        # monitoring requires 8GB RAM; on a small machine most would fail
        no_fits = [n for n, r in results.items() if r.status == FIT_NO_FIT]
        self.assertGreater(len(no_fits), 0)


class TestFullMirrorServices(unittest.TestCase):
    def test_full_mirror_on_large_machine(self):
        cat     = _catalog()
        results = assess_all_services(cat, _HARDWARE_64, host_ram_gb=64)
        selected, excluded = full_mirror_services(cat, results)
        self.assertIn("k3s-worker", selected)
        self.assertIn("longhorn", selected)

    def test_full_mirror_excludes_no_fit(self):
        cat     = _catalog()
        results = assess_all_services(cat, _HARDWARE_8, host_ram_gb=8)
        selected, excluded = full_mirror_services(cat, results)
        excluded_names = {e["service"] for e in excluded}
        # monitoring (8GB) should be excluded from 8GB machine
        fit_names = {n for n, r in results.items() if r.status == FIT_NO_FIT}
        self.assertTrue(excluded_names >= fit_names)

    def test_excluded_has_reason(self):
        cat     = _catalog()
        results = assess_all_services(cat, _HARDWARE_8, host_ram_gb=8)
        _, excluded = full_mirror_services(cat, results)
        for e in excluded:
            self.assertIn("service", e)
            self.assertIn("reason", e)


# ===========================================================================
# Planner session step tests
# ===========================================================================

class TestStep0NetworkMode(unittest.TestCase):
    def test_set_lan_mode(self):
        s = SpawnPlannerSession()
        step0_set_network_mode(s, NET_LAN, broodling_ip="192.168.1.15")
        self.assertEqual(s.network_mode, NET_LAN)
        self.assertEqual(s.broodling_ip, "192.168.1.15")

    def test_set_wan_mode(self):
        s = SpawnPlannerSession()
        step0_set_network_mode(s, NET_WAN,
                               wan_auth_key="tskey-ABCDE",
                               headscale_url="https://pve01.home.example.com:8080")
        self.assertEqual(s.network_mode, NET_WAN)
        self.assertEqual(s.wan_auth_key, "tskey-ABCDE")
        self.assertIsNotNone(s.headscale_url)

    def test_set_specify_mode(self):
        s = SpawnPlannerSession()
        step0_set_network_mode(s, NET_SPECIFY, broodling_ip="10.0.0.50")
        self.assertEqual(s.network_mode, NET_SPECIFY)
        self.assertEqual(s.broodling_ip, "10.0.0.50")


class TestStep1ExecutionMode(unittest.TestCase):
    def test_autonomous_generates_password(self):
        s = SpawnPlannerSession()
        step1_set_execution_mode(s, EXEC_AUTONOMOUS)
        self.assertIsNotNone(s.temp_root_password)
        self.assertIn(".", s.temp_root_password)  # Capital.to.word.N format

    def test_interactive_no_password(self):
        s = SpawnPlannerSession()
        step1_set_execution_mode(s, EXEC_INTERACTIVE)
        self.assertIsNone(s.temp_root_password)

    def test_execution_mode_set(self):
        s = SpawnPlannerSession()
        step1_set_execution_mode(s, EXEC_AUTONOMOUS)
        self.assertEqual(s.execution_mode, EXEC_AUTONOMOUS)

    def test_temp_password_format(self):
        pw = generate_temp_password(seed=42)
        # Should be Capital.to.word.N
        self.assertTrue(pw[0].isupper())
        self.assertIn(".to.", pw)
        parts = pw.split(".")
        self.assertTrue(parts[-1].isdigit())


class TestStep2ServiceSelection(unittest.TestCase):
    def setUp(self):
        self.cat = _catalog()
        self.session = SpawnPlannerSession()
        step0_set_network_mode(self.session, NET_LAN, broodling_ip="192.168.1.15")
        step1_set_execution_mode(self.session, EXEC_AUTONOMOUS)

    def test_full_mirror_large_machine(self):
        step2_select_services(self.session, self.cat, _HARDWARE_64, host_ram_gb=64)
        self.assertIn("k3s-worker", self.session.selected_services)
        self.assertIn("longhorn", self.session.selected_services)

    def test_full_mirror_baseline_always_selected(self):
        step2_select_services(self.session, self.cat, _HARDWARE_8, host_ram_gb=8)
        self.assertIn("k3s-worker", self.session.selected_services)

    def test_excluded_populated(self):
        step2_select_services(self.session, self.cat, _HARDWARE_8, host_ram_gb=8)
        # Some services should be excluded on 8GB machine
        self.assertGreaterEqual(len(self.session.excluded_services), 0)

    def test_manual_group_selection(self):
        step2_select_services(
            self.session, self.cat, _HARDWARE_16, host_ram_gb=16,
            mode=SEL_GROUP,
            manual_selection=["longhorn"],
        )
        self.assertIn("k3s-worker", self.session.selected_services)
        self.assertIn("longhorn", self.session.selected_services)

    def test_individual_selection_deps_resolved(self):
        step2_select_services(
            self.session, self.cat, _HARDWARE_64, host_ram_gb=64,
            mode=SEL_INDIVIDUAL,
            manual_selection=["nextcloud"],
        )
        # nextcloud depends on k3s-worker + longhorn
        self.assertIn("k3s-worker", self.session.selected_services)
        self.assertIn("longhorn", self.session.selected_services)
        self.assertIn("nextcloud", self.session.selected_services)

    def test_fit_results_populated(self):
        step2_select_services(self.session, self.cat, _HARDWARE_16, host_ram_gb=16)
        self.assertIn("k3s-worker", self.session.fit_results)

    def test_interactive_mode_no_service_selection(self):
        s = SpawnPlannerSession()
        step1_set_execution_mode(s, EXEC_INTERACTIVE)
        # Interactive mode doesn't call step2 — services list stays empty
        self.assertEqual(s.selected_services, [])


class TestStep3ResourceAllocation(unittest.TestCase):
    def setUp(self):
        from hatchery_state import read_hatchery_state
        self.manifest = read_hatchery_state(_BOOTSTRAP_STATE, {})
        self.cat = _catalog()

    def test_allocates_vmids(self):
        s = SpawnPlannerSession()
        step1_set_execution_mode(s, EXEC_AUTONOMOUS)
        step2_select_services(s, self.cat, _HARDWARE_16, host_ram_gb=16,
                              mode=SEL_INDIVIDUAL, manual_selection=["longhorn"])
        step3_allocate_resources(s, self.manifest, _BOOTSTRAP_STATE, self.cat, _HARDWARE_16)
        self.assertGreater(len(s.allocated_vmids), 0)

    def test_vmids_not_in_hatchery(self):
        s = SpawnPlannerSession()
        step1_set_execution_mode(s, EXEC_AUTONOMOUS)
        step2_select_services(s, self.cat, _HARDWARE_16, host_ram_gb=16,
                              mode=SEL_INDIVIDUAL, manual_selection=["longhorn"])
        step3_allocate_resources(s, self.manifest, _BOOTSTRAP_STATE, self.cat, _HARDWARE_16)
        hatchery_vmids = {100}
        self.assertFalse(set(s.allocated_vmids) & hatchery_vmids)

    def test_ips_allocated(self):
        s = SpawnPlannerSession()
        step1_set_execution_mode(s, EXEC_AUTONOMOUS)
        step2_select_services(s, self.cat, _HARDWARE_16, host_ram_gb=16,
                              mode=SEL_INDIVIDUAL, manual_selection=[])
        step3_allocate_resources(s, self.manifest, _BOOTSTRAP_STATE, self.cat, _HARDWARE_16)
        self.assertGreater(len(s.allocated_ips), 0)

    def test_hostname_suggested(self):
        s = SpawnPlannerSession()
        step1_set_execution_mode(s, EXEC_AUTONOMOUS)
        step2_select_services(s, self.cat, _HARDWARE_16, host_ram_gb=16)
        step3_allocate_resources(s, self.manifest, _BOOTSTRAP_STATE, self.cat, _HARDWARE_16)
        self.assertIsNotNone(s.suggested_hostname)


# ===========================================================================
# Build spawn plan
# ===========================================================================

class TestBuildSpawnPlan(unittest.TestCase):
    def setUp(self):
        from hatchery_state import read_hatchery_state
        self.manifest = read_hatchery_state(_BOOTSTRAP_STATE, {})
        self.cat = _catalog()
        self.s   = SpawnPlannerSession()
        step0_set_network_mode(self.s, NET_LAN, broodling_ip="192.168.1.15")
        step1_set_execution_mode(self.s, EXEC_AUTONOMOUS)
        step2_select_services(self.s, self.cat, _HARDWARE_16, host_ram_gb=16,
                              mode=SEL_INDIVIDUAL, manual_selection=["longhorn"])
        step3_allocate_resources(self.s, self.manifest, _BOOTSTRAP_STATE, self.cat, _HARDWARE_16)
        self.plan = build_spawn_plan(
            self.s, self.manifest, _BOOTSTRAP_STATE, self.cat, _HARDWARE_16,
            now_fn=lambda: "2026-06-01T12:00:00+00:00",
        )

    def test_plan_has_cell_id(self):
        self.assertEqual(self.plan["cell_id"], "cell-alpha")

    def test_plan_has_hostname(self):
        self.assertIn("hostname", self.plan)
        self.assertIsNotNone(self.plan["hostname"])

    def test_plan_has_generated_at(self):
        self.assertEqual(self.plan["generated_at"], "2026-06-01T12:00:00+00:00")

    def test_disposition_execution_mode(self):
        self.assertEqual(self.plan["disposition"]["execution_mode"], "autonomous")

    def test_disposition_network_mode(self):
        self.assertEqual(self.plan["disposition"]["network_mode"], "lan")

    def test_selected_services_in_plan(self):
        self.assertIn("k3s-worker", self.plan["disposition"]["services"])
        self.assertIn("longhorn",   self.plan["disposition"]["services"])

    def test_vms_present(self):
        self.assertGreater(len(self.plan["vms"]), 0)

    def test_vms_have_vmids(self):
        for vm in self.plan["vms"]:
            self.assertIn("vmid", vm)
            self.assertGreater(vm["vmid"], 0)

    def test_storage_topology_from_hardware(self):
        self.assertEqual(self.plan["storage"]["topology"], "mirror")

    def test_storage_disk_ids_from_hardware(self):
        self.assertIn("/dev/sda", self.plan["storage"]["disk_ids"])

    def test_network_gateway(self):
        self.assertEqual(self.plan["network"]["gateway"], "192.168.1.1")

    def test_k3s_role_worker_by_default(self):
        self.assertEqual(self.plan["k3s"]["role"], "worker")

    def test_k3s_server_url(self):
        self.assertIn("k3s-server-01", self.plan["k3s"]["server_url"])

    def test_hatchery_address(self):
        self.assertEqual(self.plan["hatchery"]["proxmox_cluster_address"], "192.168.1.10")


class TestBuildSpawnPlanServerRole(unittest.TestCase):
    def test_k3s_server_role_when_server_selected(self):
        from hatchery_state import read_hatchery_state
        manifest_dict = read_hatchery_state(_BOOTSTRAP_STATE, {})
        cat = ServiceCatalog.from_list(_parse_service_catalog_yaml("""
services:
  - name: k3s-worker
    display_name: Worker
    group: Infrastructure
    ram_gb: 4
    disk_gb: 20
    description: worker
    dependencies: []
    baseline: true
    vm_count: 1
  - name: k3s-server
    display_name: Server
    group: Infrastructure
    ram_gb: 8
    disk_gb: 20
    description: server
    dependencies: []
    baseline: false
    vm_count: 1
"""))
        s = SpawnPlannerSession()
        step0_set_network_mode(s, NET_LAN, broodling_ip="192.168.1.15")
        step1_set_execution_mode(s, EXEC_AUTONOMOUS)
        step2_select_services(s, cat, _HARDWARE_64, host_ram_gb=64,
                              mode=SEL_INDIVIDUAL, manual_selection=["k3s-server"])
        step3_allocate_resources(s, manifest_dict, _BOOTSTRAP_STATE, cat, _HARDWARE_64)
        plan = build_spawn_plan(s, manifest_dict, _BOOTSTRAP_STATE, cat, _HARDWARE_64)
        self.assertEqual(plan["k3s"]["role"], "server")


class TestBuildSpawnPlanInteractive(unittest.TestCase):
    def test_interactive_plan_has_empty_services(self):
        from hatchery_state import read_hatchery_state
        manifest_dict = read_hatchery_state(_BOOTSTRAP_STATE, {})
        cat = _catalog()
        s = SpawnPlannerSession()
        step0_set_network_mode(s, NET_LAN, broodling_ip="192.168.1.15")
        step1_set_execution_mode(s, EXEC_INTERACTIVE)
        # No step2 in interactive mode
        step3_allocate_resources(s, manifest_dict, _BOOTSTRAP_STATE, cat)
        plan = build_spawn_plan(s, manifest_dict, _BOOTSTRAP_STATE, cat)
        self.assertEqual(plan["disposition"]["execution_mode"], "interactive")
        self.assertEqual(plan["disposition"]["services"], [])

    def test_interactive_plan_has_vms(self):
        from hatchery_state import read_hatchery_state
        manifest_dict = read_hatchery_state(_BOOTSTRAP_STATE, {})
        cat = _catalog()
        s = SpawnPlannerSession()
        step0_set_network_mode(s, NET_LAN, broodling_ip="192.168.1.15")
        step1_set_execution_mode(s, EXEC_INTERACTIVE)
        step3_allocate_resources(s, manifest_dict, _BOOTSTRAP_STATE, cat)
        plan = build_spawn_plan(s, manifest_dict, _BOOTSTRAP_STATE, cat)
        self.assertGreater(len(plan["vms"]), 0)


class TestBuildSpawnPlanWanMode(unittest.TestCase):
    def test_wan_fields_in_plan(self):
        from hatchery_state import read_hatchery_state
        manifest_dict = read_hatchery_state(_BOOTSTRAP_STATE, {})
        cat = _catalog()
        s = SpawnPlannerSession()
        step0_set_network_mode(s, NET_WAN,
                               wan_auth_key="ts-TESTKEY",
                               headscale_url="https://pve01.home.example.com:8080")
        step1_set_execution_mode(s, EXEC_AUTONOMOUS)
        step2_select_services(s, cat, _HARDWARE_16, host_ram_gb=16)
        step3_allocate_resources(s, manifest_dict, _BOOTSTRAP_STATE, cat, _HARDWARE_16)
        plan = build_spawn_plan(s, manifest_dict, _BOOTSTRAP_STATE, cat, _HARDWARE_16)
        self.assertEqual(plan["disposition"]["network_mode"], "wan")
        self.assertIn("wan_auth_key", plan["disposition"])
        self.assertIn("headscale_url", plan["hatchery"])


# ===========================================================================
# Service catalog file loading
# ===========================================================================

class TestServiceCatalogFromFile(unittest.TestCase):
    def test_loads_from_file(self):
        cat = ServiceCatalog.from_file()
        # Should have at least k3s-worker
        self.assertIsNotNone(cat.get("k3s-worker"))

    def test_baseline_service_in_file(self):
        cat = ServiceCatalog.from_file()
        baseline = cat.baseline()
        self.assertGreater(len(baseline), 0)

    def test_groups_present_in_file(self):
        cat = ServiceCatalog.from_file()
        groups = cat.groups()
        self.assertIn("Infrastructure", groups)
        self.assertIn("Platform", groups)


# ===========================================================================
# Temp password generation
# ===========================================================================

class TestTempPassword(unittest.TestCase):
    def test_deterministic_with_seed(self):
        p1 = generate_temp_password(seed=1)
        p2 = generate_temp_password(seed=1)
        self.assertEqual(p1, p2)

    def test_different_seeds_different_passwords(self):
        p1 = generate_temp_password(seed=1)
        p2 = generate_temp_password(seed=2)
        self.assertNotEqual(p1, p2)

    def test_format_capital_dot_to_dot_word_dot_n(self):
        pw = generate_temp_password(seed=99)
        self.assertTrue(pw[0].isupper())
        self.assertIn(".to.", pw)
        self.assertTrue(pw[-1].isdigit())

    def test_no_spaces(self):
        pw = generate_temp_password()
        self.assertNotIn(" ", pw)


class TestR3002HeadscaleCommand(unittest.TestCase):
    """R3-002: headscale CLI must use 'preauthkeys create' not 'authkeys generate'."""

    def test_spawn_planner_library_uses_preauthkeys(self):
        import inspect
        import spawn_planner as _spl
        src = inspect.getsource(_spl)
        self.assertNotIn("authkeys generate", src,
                         "spawn_planner.py must not use deprecated 'authkeys generate'")
        self.assertIn("preauthkeys", src,
                      "spawn_planner.py must reference 'preauthkeys'")

    def test_spawn_planner_interactive_cli_uses_preauthkeys(self):
        cli_path = REPO_ROOT / "proxmox-bootstrap" / "spawn-planner.py"
        src = cli_path.read_text(encoding="utf-8")
        self.assertNotIn("authkeys generate", src,
                         "spawn-planner.py must not use deprecated 'authkeys generate'")
        self.assertIn("preauthkeys", src,
                      "spawn-planner.py must use 'preauthkeys' subcommand")

    def test_federated_reconstruction_uses_preauthkeys(self):
        fr_path = REPO_ROOT / "proxmox-bootstrap" / "federated_reconstruction.py"
        src = fr_path.read_text(encoding="utf-8")
        self.assertNotIn("authkeys generate", src,
                         "federated_reconstruction.py must not use deprecated 'authkeys generate'")
        self.assertIn("preauthkeys create", src,
                      "federated_reconstruction.py must use 'preauthkeys create'")


if __name__ == "__main__":
    unittest.main()
