#!/usr/bin/env python3
"""
Tests for Phase 12.E.11 — Spawn scenarios.

Each scenario exercises the spawn pipeline modules in combination with
a specific hardware profile and disposition. Tests validate that:
  - Allocation helpers produce non-conflicting resources
  - Conflict detection catches deliberate collisions
  - IaC generator adapts to each scenario's hardware
  - Scripts are correct for each scenario's k3s role
  - State updater integrates broodling into bootstrap-state
"""

import unittest

from hatchery_state import (
    SpawnManifest,
    next_ip_block,
    next_vmid_block,
    read_hatchery_state,
    suggest_hostname,
)
from spawn_hardware_discovery import (
    DiskInfo,
    HardwareProfile,
    NicInfo,
    hardware_profile_to_dict,
    zfs_topology_for_profile,
)
from spawn_iac_generator import generate_ansible_inventory, generate_tfvars
from spawn_scripts import (
    generate_phase_00_host,
    generate_phase_04_k3s,
    generate_phase_05_ha,
    generate_spawn_sh,
    generate_tailscale_join_sh,
)
from update_state_after_spawn import build_spawn_result, update_state_after_spawn
from validate_spawn import SpawnProposal, is_valid, summarise, validate_spawn

# ---------------------------------------------------------------------------
# Shared hatchery fixture — represents a single-node hatchery already running
# ---------------------------------------------------------------------------

_BOOTSTRAP_STATE = {
    "cell_id": "cell-alpha",
    "host_identity": {
        "hostname": "pve01",
        "fqdn": "pve01.home.example.com",
        "domain": "home.example.com",
        "lan_ip": "192.168.1.10",
    },
    "vms": [
        {"vmid": 100, "name": "k3s-server-01", "ip": "192.168.1.20",
         "status": "running", "cores": 4, "memory_mb": 4096},
        {"vmid": 101, "name": "forgejo",        "ip": "192.168.1.21",
         "status": "running", "cores": 2, "memory_mb": 2048},
        {"vmid": 102, "name": "assessment-engine","ip": "192.168.1.22",
         "status": "running", "cores": 2, "memory_mb": 2048},
    ],
    "dns_registry": [
        {"hostname": "pve01", "fqdn": "pve01.home.example.com", "ip": "192.168.1.10",
         "role": "proxmox-host"},
        {"hostname": "k3s-server-01", "fqdn": "k3s-server-01.home.example.com",
         "ip": "192.168.1.20", "role": "k3s-server"},
    ],
    "network_topology": {
        "management_cidr": "192.168.1.0/24",
        "gateway": "192.168.1.1",
    },
    "k3s_cluster": {
        "server_count": 1,
        "worker_count": 0,
        "pod_cidr": "10.42.0.0/16",
        "service_cidr": "10.43.0.0/16",
        "server_url": "https://k3s-server-01.home.example.com:6443",
    },
    "capacity_model": {
        "host_ram_gb": 64,
    },
}

_K3S_TOKENS = {
    "worker": "K10::worker::test-token",
    "server": "K10::server::test-token",
}


def _make_manifest() -> SpawnManifest:
    return read_hatchery_state(_BOOTSTRAP_STATE, _K3S_TOKENS)


def _make_plan(
    hostname: str,
    vmids: list,
    ips: list,
    k3s_role: str = "worker",
    services: list = None,
    ram_gb: float = 16,
    storage_topology: str = "mirror",
    disk_ids: list = None,
    network_mode: str = "lan",
    execution_mode: str = "autonomous",
) -> dict:
    return {
        "cell_id": "cell-alpha",
        "hostname": hostname,
        "domain": "home.example.com",
        "lan_ip": ips[0] if ips else "192.168.1.100",
        "package_id": f"spawn-cell-alpha-{hostname}-ts",
        "generated_at": "2026-06-01T12:00:00Z",
        "disposition": {
            "execution_mode": execution_mode,
            "network_mode": network_mode,
            "services": services or ["k3s-worker"],
            "excluded": [],
        },
        "storage": {
            "pool_name": "rpool",
            "topology": storage_topology,
            "disk_ids": disk_ids or ["/dev/sda", "/dev/sdb"],
            "datastore_name": "local-rpool",
        },
        "network": {
            "bridge": "vmbr0",
            "gateway": "192.168.1.1",
            "nameservers": ["192.168.1.1"],
        },
        "hatchery": {
            "proxmox_cluster_address": "192.168.1.10",
        },
        "vms": [
            {"vmid": vmids[i], "name": f"vm-{i:02d}", "ip": ips[i],
             "memory_mb": int(ram_gb * 1024 / len(vmids)),
             "initial_user": "ubuntu"}
            for i in range(min(len(vmids), len(ips)))
        ],
        "k3s": {
            "role": k3s_role,
            "server_url": "https://k3s-server-01.home.example.com:6443",
            "worker_join_token": "K10::worker::test",
            "node_labels": [f"{k3s_role}=true"],
        },
        "k3s_role": k3s_role,
    }


# ---------------------------------------------------------------------------
# Hardware profile fixtures
# ---------------------------------------------------------------------------

def _hw_small() -> HardwareProfile:
    """2 disks, 8GB RAM — baseline only."""
    return HardwareProfile(
        hostname="pve02", cpu_cores=2, cpu_model="Intel N100", ram_gb=8.0,
        disks=[DiskInfo("/dev/sda", 120.0, False), DiskInfo("/dev/sdb", 120.0, False)],
        nics=[NicInfo("eno1", "AA:BB:CC:DD:EE:01")],
    )


def _hw_compute() -> HardwareProfile:
    """2 disks, 32GB RAM — suitable for compute workloads."""
    return HardwareProfile(
        hostname="pve02", cpu_cores=8, cpu_model="AMD Ryzen 5600", ram_gb=32.0,
        disks=[DiskInfo("/dev/sda", 500.0, False), DiskInfo("/dev/sdb", 500.0, False)],
        nics=[NicInfo("eno1", "AA:BB:CC:DD:EE:02")],
    )


def _hw_storage() -> HardwareProfile:
    """4 disks, 32GB RAM — suitable for PBS + Longhorn storage."""
    return HardwareProfile(
        hostname="pve02", cpu_cores=8, cpu_model="Intel Xeon", ram_gb=32.0,
        disks=[
            DiskInfo("/dev/sda", 2000.0, True),
            DiskInfo("/dev/sdb", 2000.0, True),
            DiskInfo("/dev/sdc", 2000.0, True),
            DiskInfo("/dev/sdd", 2000.0, True),
        ],
        nics=[NicInfo("eno1", "AA:BB:CC:DD:EE:03")],
    )


def _hw_server() -> HardwareProfile:
    """2 disks, 64GB RAM — control plane candidate."""
    return HardwareProfile(
        hostname="pve02", cpu_cores=16, cpu_model="AMD EPYC", ram_gb=64.0,
        disks=[DiskInfo("/dev/nvme0n1", 1000.0, False), DiskInfo("/dev/nvme1n1", 1000.0, False)],
        nics=[NicInfo("eno1", "AA:BB:CC:DD:EE:04"), NicInfo("eno2", "AA:BB:CC:DD:EE:05")],
    )


def _hw_mixed() -> HardwareProfile:
    """3 disks, 48GB RAM — compute + limited storage."""
    return HardwareProfile(
        hostname="pve02", cpu_cores=12, cpu_model="Intel i9", ram_gb=48.0,
        disks=[
            DiskInfo("/dev/sda", 500.0, False),
            DiskInfo("/dev/sdb", 1000.0, True),
            DiskInfo("/dev/sdc", 1000.0, True),
        ],
        nics=[NicInfo("eno1", "AA:BB:CC:DD:EE:06")],
    )


# ===========================================================================
# Scenario 1 — Baseline (small machine, worker, baseline services only)
# ===========================================================================

class TestScenarioBaseline(unittest.TestCase):
    def setUp(self):
        self.manifest = _make_manifest()
        hw = _hw_small()
        self.topology = zfs_topology_for_profile(hw)
        vmids = next_vmid_block(self.manifest, 1)
        ips   = next_ip_block(self.manifest, "192.168.1.0/24", 1)
        self.hostname = suggest_hostname(self.manifest, "pve", "home.example.com")
        self.plan = _make_plan(
            hostname=self.hostname,
            vmids=vmids, ips=ips, k3s_role="worker",
            services=["k3s-worker"], ram_gb=4,
            storage_topology=self.topology,
        )

    def test_small_hw_gets_mirror_topology(self):
        self.assertEqual(self.topology, "mirror")

    def test_no_vmid_conflicts(self):
        proposal = SpawnProposal(
            vmids=[v["vmid"] for v in self.plan["vms"]],
            ips=[v["ip"] for v in self.plan["vms"]],
            hostnames=[self.hostname],
            ram_gb=4,
            host_ram_gb=8,
        )
        findings = validate_spawn(self.manifest, proposal)
        self.assertTrue(is_valid(findings), summarise(findings))

    def test_tfvars_generated(self):
        tfvars = generate_tfvars(self.plan)
        self.assertIn("vmid", tfvars)

    def test_spawn_sh_no_ha_phase(self):
        sh = generate_spawn_sh(self.plan)
        self.assertNotIn("phase-05-ha", sh)

    def test_worker_join_token_in_k3s_script(self):
        s = generate_phase_04_k3s(self.plan)
        self.assertIn("worker", s)


# ===========================================================================
# Scenario 2 — Compute disposition (moderate hardware)
# ===========================================================================

class TestScenarioCompute(unittest.TestCase):
    def setUp(self):
        self.manifest = _make_manifest()
        hw = _hw_compute()
        self.topology = zfs_topology_for_profile(hw)
        vmids = next_vmid_block(self.manifest, 3)
        ips   = next_ip_block(self.manifest, "192.168.1.0/24", 3)
        hostname = suggest_hostname(self.manifest, "pve", "home.example.com")
        self.plan = _make_plan(
            hostname=hostname, vmids=vmids, ips=ips, k3s_role="worker",
            services=["k3s-worker", "longhorn", "prometheus-agent"],
            ram_gb=24, storage_topology=self.topology,
        )

    def test_compute_hw_mirror(self):
        self.assertEqual(self.topology, "mirror")

    def test_three_vmids_allocated(self):
        self.assertEqual(len(self.plan["vms"]), 3)

    def test_vmids_not_in_hatchery(self):
        hatchery_vmids = {100, 101, 102}
        plan_vmids = {v["vmid"] for v in self.plan["vms"]}
        self.assertFalse(plan_vmids & hatchery_vmids)

    def test_ips_not_in_hatchery(self):
        hatchery_ips = {"192.168.1.10", "192.168.1.20", "192.168.1.21", "192.168.1.22"}
        plan_ips = {v["ip"] for v in self.plan["vms"]}
        self.assertFalse(plan_ips & hatchery_ips)

    def test_services_in_disposition(self):
        services = self.plan["disposition"]["services"]
        self.assertIn("k3s-worker", services)
        self.assertIn("longhorn", services)

    def test_ansible_inventory_generated(self):
        inv = generate_ansible_inventory(self.plan)
        self.assertIn(self.plan["hostname"], inv)

    def test_phase_host_sets_correct_bridge(self):
        s = generate_phase_00_host(self.plan)
        self.assertIn("vmbr0", s)


# ===========================================================================
# Scenario 3 — Storage disposition (4 disks → raidz1)
# ===========================================================================

class TestScenarioStorage(unittest.TestCase):
    def setUp(self):
        self.manifest = _make_manifest()
        hw = _hw_storage()
        self.topology = zfs_topology_for_profile(hw)
        vmids = next_vmid_block(self.manifest, 2)
        ips   = next_ip_block(self.manifest, "192.168.1.0/24", 2)
        hostname = suggest_hostname(self.manifest, "pve", "home.example.com")
        self.plan = _make_plan(
            hostname=hostname, vmids=vmids, ips=ips, k3s_role="worker",
            services=["k3s-worker", "pbs-datastore", "longhorn"],
            ram_gb=16, storage_topology=self.topology,
            disk_ids=["/dev/sda", "/dev/sdb", "/dev/sdc", "/dev/sdd"],
        )

    def test_four_disks_get_raidz2(self):
        # 4 disks → raidz2 per zfs_topology_for_profile (n <= 6 → raidz2)
        self.assertEqual(self.topology, "raidz2")

    def test_all_disk_ids_in_plan(self):
        self.assertEqual(len(self.plan["storage"]["disk_ids"]), 4)

    def test_phase_00_host_uses_raidz2(self):
        s = generate_phase_00_host(self.plan)
        self.assertIn("raidz2", s)

    def test_pbs_datastore_in_services(self):
        self.assertIn("pbs-datastore", self.plan["disposition"]["services"])

    def test_no_vmid_conflicts(self):
        proposal = SpawnProposal(
            vmids=[v["vmid"] for v in self.plan["vms"]],
            ips=[v["ip"] for v in self.plan["vms"]],
            hostnames=[self.plan["hostname"]],
            ram_gb=16,
            host_ram_gb=32,
        )
        findings = validate_spawn(self.manifest, proposal)
        self.assertTrue(is_valid(findings), summarise(findings))


# ===========================================================================
# Scenario 4 — Control-plane disposition (server role → HA promotion)
# ===========================================================================

class TestScenarioControlPlane(unittest.TestCase):
    def setUp(self):
        self.manifest = _make_manifest()
        hw = _hw_server()
        self.topology = zfs_topology_for_profile(hw)
        vmids = next_vmid_block(self.manifest, 2)
        ips   = next_ip_block(self.manifest, "192.168.1.0/24", 2)
        hostname = suggest_hostname(self.manifest, "pve", "home.example.com")
        self.plan = _make_plan(
            hostname=hostname, vmids=vmids, ips=ips, k3s_role="server",
            services=["k3s-server", "monitoring"],
            ram_gb=32, storage_topology=self.topology,
        )

    def test_spawn_sh_includes_ha_phase(self):
        sh = generate_spawn_sh(self.plan)
        self.assertIn("phase-05-ha", sh)

    def test_phase_05_ha_generated(self):
        s = generate_phase_05_ha(self.plan)
        self.assertIn("etcd", s)

    def test_phase_04_k3s_server_role(self):
        s = generate_phase_04_k3s(self.plan)
        self.assertIn("server", s)

    def test_no_vmid_conflicts(self):
        proposal = SpawnProposal(
            vmids=[v["vmid"] for v in self.plan["vms"]],
            ips=[v["ip"] for v in self.plan["vms"]],
            hostnames=[self.plan["hostname"]],
            ram_gb=32,
            host_ram_gb=64,
        )
        findings = validate_spawn(self.manifest, proposal)
        self.assertTrue(is_valid(findings), summarise(findings))


# ===========================================================================
# Scenario 5 — Mixed disposition (compute + storage)
# ===========================================================================

class TestScenarioMixed(unittest.TestCase):
    def setUp(self):
        self.manifest = _make_manifest()
        hw = _hw_mixed()
        self.topology = zfs_topology_for_profile(hw)
        vmids = next_vmid_block(self.manifest, 3)
        ips   = next_ip_block(self.manifest, "192.168.1.0/24", 3)
        hostname = suggest_hostname(self.manifest, "pve", "home.example.com")
        self.plan = _make_plan(
            hostname=hostname, vmids=vmids, ips=ips, k3s_role="worker",
            services=["k3s-worker", "pbs-datastore", "prometheus-agent"],
            ram_gb=32, storage_topology=self.topology,
            disk_ids=["/dev/sda", "/dev/sdb", "/dev/sdc"],
        )

    def test_three_disks_get_raidz1(self):
        # 3 disks → raidz1 per zfs_topology_for_profile
        self.assertEqual(self.topology, "raidz1")

    def test_mixed_services_in_disposition(self):
        svcs = self.plan["disposition"]["services"]
        self.assertIn("k3s-worker", svcs)
        self.assertIn("pbs-datastore", svcs)
        self.assertIn("prometheus-agent", svcs)

    def test_tfvars_has_all_vmids(self):
        tfvars = generate_tfvars(self.plan)
        for vm in self.plan["vms"]:
            self.assertIn(str(vm["vmid"]), tfvars)


# ===========================================================================
# Scenario 6 — Hardware insufficient for one selected service
# ===========================================================================

class TestScenarioHardwareInsufficient(unittest.TestCase):
    """
    The spawn planner (12.E.3, not yet built) enforces hardware fit.
    Here we test that if the spawn plan is built with reduced services
    (after the planner drops a service that doesn't fit), the pipeline
    still produces valid artifacts.
    """
    def setUp(self):
        self.manifest = _make_manifest()
        hw = _hw_small()  # 8GB RAM — not enough for large services
        self.topology = zfs_topology_for_profile(hw)
        vmids = next_vmid_block(self.manifest, 1)
        ips   = next_ip_block(self.manifest, "192.168.1.0/24", 1)
        hostname = suggest_hostname(self.manifest, "pve", "home.example.com")
        # Plan shows only k3s-worker (pbs-datastore excluded — requires more RAM)
        self.plan = _make_plan(
            hostname=hostname, vmids=vmids, ips=ips, k3s_role="worker",
            services=["k3s-worker"],  # pbs excluded
            ram_gb=4, storage_topology=self.topology,
        )
        self.plan["disposition"]["excluded"] = [
            {"service": "pbs-datastore", "reason": "requires 16 GB RAM, host has 8 GB"}
        ]

    def test_reduced_plan_is_valid(self):
        proposal = SpawnProposal(
            vmids=[v["vmid"] for v in self.plan["vms"]],
            ips=[v["ip"] for v in self.plan["vms"]],
            hostnames=[self.plan["hostname"]],
            ram_gb=4,
            host_ram_gb=8,
        )
        findings = validate_spawn(self.manifest, proposal)
        self.assertTrue(is_valid(findings), summarise(findings))

    def test_excluded_service_recorded(self):
        excluded = self.plan["disposition"]["excluded"]
        self.assertGreater(len(excluded), 0)
        self.assertEqual(excluded[0]["service"], "pbs-datastore")

    def test_scripts_generated_without_error(self):
        sh = generate_spawn_sh(self.plan)
        self.assertIn("phase-00-preflight", sh)

    def test_tfvars_for_one_vm(self):
        tfvars = generate_tfvars(self.plan)
        self.assertIn("vmid", tfvars)


# ===========================================================================
# Scenario 7 — Full peer (matches hatchery capabilities)
# ===========================================================================

class TestScenarioFullPeer(unittest.TestCase):
    def setUp(self):
        self.manifest = _make_manifest()
        hw = _hw_server()
        self.topology = zfs_topology_for_profile(hw)
        vmids = next_vmid_block(self.manifest, 5)
        ips   = next_ip_block(self.manifest, "192.168.1.0/24", 5)
        hostname = suggest_hostname(self.manifest, "pve", "home.example.com")
        self.plan = _make_plan(
            hostname=hostname, vmids=vmids, ips=ips, k3s_role="server",
            services=["k3s-server", "pbs-datastore", "forgejo", "monitoring", "longhorn"],
            ram_gb=56, storage_topology=self.topology,
        )

    def test_five_vms_allocated(self):
        self.assertEqual(len(self.plan["vms"]), 5)

    def test_all_vmids_unique(self):
        vmids = [v["vmid"] for v in self.plan["vms"]]
        self.assertEqual(len(vmids), len(set(vmids)))

    def test_all_ips_unique(self):
        ips = [v["ip"] for v in self.plan["vms"]]
        self.assertEqual(len(ips), len(set(ips)))

    def test_no_collision_with_hatchery(self):
        hatchery_vmids = {100, 101, 102}
        plan_vmids = {v["vmid"] for v in self.plan["vms"]}
        self.assertFalse(plan_vmids & hatchery_vmids)


# ===========================================================================
# Collision scenarios — deliberate VMID/IP/hostname conflicts
# ===========================================================================

class TestConflictDetection(unittest.TestCase):
    def setUp(self):
        self.manifest = _make_manifest()

    def test_vmid_collision_with_hatchery(self):
        proposal = SpawnProposal(
            vmids=[100],  # already used by hatchery
            ips=["192.168.1.99"],
            hostnames=["pve02"],
            ram_gb=8, host_ram_gb=32,
        )
        findings = validate_spawn(self.manifest, proposal)
        self.assertFalse(is_valid(findings))
        self.assertTrue(any("vmid" in f.field.lower() for f in findings))

    def test_ip_collision_with_hatchery(self):
        proposal = SpawnProposal(
            vmids=[200],
            ips=["192.168.1.10"],  # hatchery LAN IP
            hostnames=["pve02"],
            ram_gb=8, host_ram_gb=32,
        )
        findings = validate_spawn(self.manifest, proposal)
        self.assertFalse(is_valid(findings))
        self.assertTrue(any("ip" in f.field.lower() for f in findings))

    def test_hostname_collision_with_hatchery(self):
        proposal = SpawnProposal(
            vmids=[200],
            ips=["192.168.1.99"],
            hostnames=["pve01"],  # hatchery hostname
            ram_gb=8, host_ram_gb=32,
        )
        findings = validate_spawn(self.manifest, proposal)
        self.assertFalse(is_valid(findings))
        self.assertTrue(any("hostname" in f.field.lower() for f in findings))

    def test_duplicate_vmids_in_proposal(self):
        proposal = SpawnProposal(
            vmids=[200, 200],  # duplicate
            ips=["192.168.1.50", "192.168.1.51"],
            hostnames=["pve02"],
            ram_gb=8, host_ram_gb=32,
        )
        findings = validate_spawn(self.manifest, proposal)
        self.assertFalse(is_valid(findings))

    def test_duplicate_ips_in_proposal(self):
        proposal = SpawnProposal(
            vmids=[200, 201],
            ips=["192.168.1.50", "192.168.1.50"],  # duplicate
            hostnames=["pve02"],
            ram_gb=8, host_ram_gb=32,
        )
        findings = validate_spawn(self.manifest, proposal)
        self.assertFalse(is_valid(findings))

    def test_ram_overprovision_red(self):
        # Request 95% of host RAM (> 90% threshold → RED)
        proposal = SpawnProposal(
            vmids=[200],
            ips=["192.168.1.50"],
            hostnames=["pve02"],
            ram_gb=62.0,   # 64 × 0.97 > 90%
            host_ram_gb=64,
        )
        findings = validate_spawn(self.manifest, proposal)
        red = [f for f in findings if f.severity == "RED"]
        self.assertTrue(len(red) > 0)

    def test_low_vmid_blocked(self):
        proposal = SpawnProposal(
            vmids=[50],   # < 100 → RED
            ips=["192.168.1.50"],
            hostnames=["pve02"],
            ram_gb=8, host_ram_gb=32,
        )
        findings = validate_spawn(self.manifest, proposal)
        self.assertFalse(is_valid(findings))

    def test_clean_proposal_is_valid(self):
        proposal = SpawnProposal(
            vmids=[200, 201],
            ips=["192.168.1.50", "192.168.1.51"],
            hostnames=["pve02"],
            ram_gb=16,
            host_ram_gb=64,
        )
        findings = validate_spawn(self.manifest, proposal)
        self.assertTrue(is_valid(findings), summarise(findings))


# ===========================================================================
# Scenario 8 — State update after successful spawn
# ===========================================================================

class TestStateUpdateAfterSpawn(unittest.TestCase):
    def setUp(self):
        import copy
        self.state = copy.deepcopy(_BOOTSTRAP_STATE)
        hw = _hw_compute()
        self.hw_dict = hardware_profile_to_dict(hw)

        def _NOW_FN():
            return "2026-06-01T13:00:00+00:00"

        plan = _make_plan(
            hostname="pve02", vmids=[200, 201], ips=["192.168.1.50", "192.168.1.51"],
            k3s_role="worker", services=["k3s-worker", "longhorn"], ram_gb=24,
        )
        plan["dns_entries"] = [
            {"hostname": "pve02", "fqdn": "pve02.home.example.com",
             "ip": "192.168.1.15", "role": "proxmox-host"},
            {"hostname": "vm-00", "fqdn": "vm-00.home.example.com",
             "ip": "192.168.1.50", "role": "k3s-worker"},
        ]
        self.result = build_spawn_result(plan, self.hw_dict, now_fn=_NOW_FN)
        self.updated = update_state_after_spawn(self.state, self.result, self.hw_dict)

    def test_broodling_vms_added(self):
        vmids = {v["vmid"] for v in self.updated.get("vms", [])}
        self.assertIn(200, vmids)
        self.assertIn(201, vmids)

    def test_hatchery_vms_still_present(self):
        vmids = {v["vmid"] for v in self.updated.get("vms", [])}
        self.assertIn(100, vmids)
        self.assertIn(101, vmids)

    def test_spawn_history_appended(self):
        history = self.updated.get("spawn_history", [])
        self.assertGreater(len(history), 0)
        self.assertEqual(history[0]["broodling_hostname"], "pve02")

    def test_dns_entries_added(self):
        dns = {e["hostname"] for e in self.updated.get("dns_registry", [])}
        self.assertIn("pve02", dns)

    def test_provenance_records_added(self):
        provenance = {p.get("vmid") for p in self.updated.get("provenance_records", [])}
        self.assertIn(200, provenance)

    def test_idempotent_state_update(self):
        # Re-applying should not duplicate entries
        updated2 = update_state_after_spawn(self.updated, self.result, self.hw_dict)
        vmids = [v["vmid"] for v in updated2.get("vms", [])]
        self.assertEqual(len(vmids), len(set(vmids)))


# ===========================================================================
# WAN mode scenario
# ===========================================================================

class TestScenarioWanMode(unittest.TestCase):
    def setUp(self):
        self.manifest = _make_manifest()
        _hw_compute()
        vmids = next_vmid_block(self.manifest, 2)
        ips   = next_ip_block(self.manifest, "192.168.1.0/24", 2)
        hostname = suggest_hostname(self.manifest, "pve", "home.example.com")
        self.plan = _make_plan(
            hostname=hostname, vmids=vmids, ips=ips,
            network_mode="wan", services=["k3s-worker"],
        )
        # Add WAN-specific fields (matching spawn_planner.py:509-510 field names)
        self.plan["disposition"]["wan_auth_key"] = "ts-key-ABCDE"
        self.plan["hatchery"]["headscale_url"] = "https://pve01.home.example.com:8080"

    def test_wan_spawn_sh_includes_tailscale(self):
        sh = generate_spawn_sh(self.plan, include_wan_phase=True)
        self.assertIn("tailscale", sh.lower())

    def test_wan_tailscale_join_sh_embeds_auth_key(self):
        sh = generate_tailscale_join_sh(self.plan)
        self.assertIn("ts-key-ABCDE", sh)

    def test_wan_tailscale_join_sh_embeds_headscale_url(self):
        sh = generate_tailscale_join_sh(self.plan)
        self.assertIn("pve01.home.example.com:8080", sh)

    def test_headscale_url_in_plan(self):
        self.assertIn("headscale_url", self.plan["hatchery"])

    def test_no_conflicts(self):
        proposal = SpawnProposal(
            vmids=[v["vmid"] for v in self.plan["vms"]],
            ips=[v["ip"] for v in self.plan["vms"]],
            hostnames=[self.plan["hostname"]],
            ram_gb=16, host_ram_gb=32,
        )
        findings = validate_spawn(self.manifest, proposal)
        self.assertTrue(is_valid(findings), summarise(findings))


# ===========================================================================
# Interactive mode scenario
# ===========================================================================

class TestScenarioInteractiveMode(unittest.TestCase):
    def setUp(self):
        self.manifest = _make_manifest()
        _hw_compute()
        vmids = next_vmid_block(self.manifest, 1)
        ips   = next_ip_block(self.manifest, "192.168.1.0/24", 1)
        hostname = suggest_hostname(self.manifest, "pve", "home.example.com")
        self.plan = _make_plan(
            hostname=hostname, vmids=vmids, ips=ips,
            execution_mode="interactive", services=[],
        )
        self.plan["disposition"]["services"] = []  # no pre-selection

    def test_interactive_mode_in_plan(self):
        self.assertEqual(self.plan["disposition"]["execution_mode"], "interactive")

    def test_no_service_preselection(self):
        self.assertEqual(self.plan["disposition"]["services"], [])

    def test_spawn_sh_still_generated(self):
        sh = generate_spawn_sh(self.plan)
        self.assertIn("phase-00-preflight", sh)


if __name__ == "__main__":
    unittest.main()
