#!/usr/bin/env python3
"""Tests for Phase 12.E.6 — Spawn scripts generator."""

import sys, unittest, tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "proxmox-bootstrap"))

from spawn_scripts import (
    generate_spawn_sh, generate_tailscale_join_sh,
    generate_phase_00_preflight, generate_phase_00_host,
    generate_phase_01_proxmox, generate_phase_02_vms, generate_phase_03_cloudinit,
    generate_phase_04_k3s, generate_phase_05_ha, generate_phase_06_verify,
    write_all_scripts,
)

PLAN = {
    "package_id": "spawn-cell-a-pve02-ts",
    "hostname": "pve02", "domain": "home.example.com",
    "lan_ip": "192.168.1.15", "k3s_role": "worker",
    "generated_at": "2026-06-01T12:00:00Z",
    "disposition": {"execution_mode": "autonomous"},
    "vms": [
        {"vmid": 200, "name": "k3s-worker-01", "ip": "192.168.1.50",
         "memory_mb": 4096, "initial_user": "ubuntu"},
    ],
    "storage": {"pool_name": "rpool", "topology": "mirror",
                "disk_ids": ["/dev/sda", "/dev/sdb"], "datastore_name": "local-rpool"},
    "network": {"gateway": "192.168.1.1", "bridge": "vmbr0",
                "nameservers": ["192.168.1.1"]},
    "k3s": {"role": "worker", "server_url": "https://pve01.home.example.com:6443",
            "worker_join_token": "K10::worker::abc"},
    "hatchery": {"proxmox_cluster_address": "192.168.1.10"},
}


class TestSpawnSh(unittest.TestCase):
    def setUp(self): self.s = generate_spawn_sh(PLAN)
    def test_shebang(self): self.assertTrue(self.s.startswith("#!/usr/bin/env bash"))
    def test_hostname_present(self): self.assertIn("pve02", self.s)
    def test_keepass_gate_hook(self): self.assertIn("keepass", self.s.lower())
    def test_phase_00_referenced(self): self.assertIn("phase-00-preflight", self.s)
    def test_phase_06_referenced(self): self.assertIn("phase-06-verify", self.s)
    def test_no_ha_phase_for_worker(self): self.assertNotIn("phase-05-ha", self.s)
    def test_ha_phase_included_for_server(self):
        plan = {**PLAN, "k3s_role": "server"}
        s = generate_spawn_sh(plan)
        self.assertIn("phase-05-ha", s)
    def test_wan_phase_optional(self):
        s_wan = generate_spawn_sh(PLAN, include_wan_phase=True)
        self.assertIn("tailscale", s_wan.lower())
        s_lan = generate_spawn_sh(PLAN, include_wan_phase=False)
        self.assertNotIn("tailscale", s_lan.lower())


class TestPhase00Preflight(unittest.TestCase):
    def setUp(self): self.s = generate_phase_00_preflight(PLAN)
    def test_checks_disks(self): self.assertIn("/dev/sda", self.s)
    def test_checks_pool_conflict(self): self.assertIn("rpool", self.s)
    def test_checks_ram(self): self.assertIn("MemAvailable", self.s)
    def test_runs_conflict_validator(self): self.assertIn("validate-spawn.py", self.s)
    def test_exits_on_failure(self): self.assertIn("exit 1", self.s)
    def test_do_not_edit_header(self): self.assertIn("DO NOT EDIT", self.s)


class TestPhase00Host(unittest.TestCase):
    def setUp(self): self.s = generate_phase_00_host(PLAN)
    def test_sets_hostname(self): self.assertIn("hostnamectl set-hostname pve02", self.s)
    def test_creates_zfs_pool(self): self.assertIn("zpool create rpool", self.s)
    def test_disk_ids_in_zpool_cmd(self):
        self.assertIn("/dev/sda", self.s)
        self.assertIn("/dev/sdb", self.s)
    def test_registers_datastore(self): self.assertIn("pvesm add zfspool", self.s)
    def test_fixes_etc_hosts(self): self.assertIn("127.0.1.1", self.s)
    def test_checkpoint_pattern(self):
        self.assertIn("checkpoint_start", self.s)
        self.assertIn("checkpoint_done", self.s)


class TestPhase01Proxmox(unittest.TestCase):
    def setUp(self): self.s = generate_phase_01_proxmox(PLAN)
    def test_pvecm_add(self): self.assertIn("pvecm add 192.168.1.10", self.s)
    def test_idempotent_check(self): self.assertIn("Already a cluster member", self.s)
    def test_checkpoint(self): self.assertIn("checkpoint_done", self.s)


class TestPhase02Vms(unittest.TestCase):
    def setUp(self): self.s = generate_phase_02_vms(PLAN)
    def test_tofu_apply(self): self.assertIn("tofu apply", self.s)
    def test_var_file_named_for_broodling(self): self.assertIn("spawn-pve02.auto.tfvars", self.s)
    def test_checkpoint(self): self.assertIn("checkpoint_done", self.s)


class TestPhase03CloudInit(unittest.TestCase):
    def setUp(self): self.s = generate_phase_03_cloudinit(PLAN)
    def test_uploads_snippets(self): self.assertIn("pvesm upload", self.s)
    def test_starts_vm(self): self.assertIn("qm start 200", self.s)
    def test_waits_for_ssh(self): self.assertIn("wait_ssh", self.s)
    def test_vm_ip_in_wait(self): self.assertIn("192.168.1.50", self.s)


class TestPhase04K3s(unittest.TestCase):
    def setUp(self): self.s = generate_phase_04_k3s(PLAN)
    def test_ansible_playbook(self): self.assertIn("ansible-playbook", self.s)
    def test_worker_tag(self): self.assertIn("k3s-worker", self.s)
    def test_inventory_named_for_broodling(self): self.assertIn("spawn-pve02.ini", self.s)


class TestPhase05Ha(unittest.TestCase):
    def setUp(self): self.s = generate_phase_05_ha(PLAN)
    def test_etcd_mention(self): self.assertIn("etcd", self.s)
    def test_conditional_note(self): self.assertIn("3rd k3s server", self.s)


class TestPhase06Verify(unittest.TestCase):
    def setUp(self): self.s = generate_phase_06_verify(PLAN)
    def test_checks_vm_running(self): self.assertIn("qm status 200", self.s)
    def test_checks_k3s_node(self): self.assertIn("kubectl get node pve02", self.s)
    def test_checks_gateway(self): self.assertIn("192.168.1.1", self.s)
    def test_exits_on_failure(self): self.assertIn("exit 1", self.s)
    def test_mentions_update_state(self): self.assertIn("update_state_after_spawn", self.s)
    def test_posts_to_spawn_complete(self): self.assertIn("api/spawn-complete", self.s)
    def test_reads_hatchery_url(self): self.assertIn("HATCHERY_URL", self.s)


WAN_PLAN = {
    **PLAN,
    "disposition": {"execution_mode": "autonomous", "network_mode": "wan",
                    "wan_auth_key": "tskey-auth-test-abc123"},
    "hatchery": {**PLAN.get("hatchery", {}), "headscale_url": "https://headscale.example.com"},
}


class TestTailscaleJoinSh(unittest.TestCase):
    def setUp(self): self.s = generate_tailscale_join_sh(WAN_PLAN)

    def test_shebang(self):
        self.assertTrue(self.s.startswith("#!/usr/bin/env bash"))

    def test_embeds_auth_key(self):
        self.assertIn("tskey-auth-test-abc123", self.s)

    def test_embeds_headscale_url(self):
        self.assertIn("headscale.example.com", self.s)

    def test_runs_tailscale_up(self):
        self.assertIn("tailscale up", self.s)

    def test_login_server_flag(self):
        self.assertIn("--login-server", self.s)

    def test_exits_on_empty_key(self):
        self.assertIn("AUTH_KEY is empty", self.s)

    def test_installs_tailscale_if_missing(self):
        self.assertIn("tailscale.com/install.sh", self.s)

    def test_checkpoint_used(self):
        self.assertIn("tailscale-join", self.s)

    def test_empty_auth_key_placeholder(self):
        plan_no_key = {**WAN_PLAN, "disposition": {"network_mode": "wan"}}
        s = generate_tailscale_join_sh(plan_no_key)
        self.assertIn("AUTH_KEY", s)

    def test_empty_headscale_url_placeholder(self):
        plan_no_url = {**WAN_PLAN, "hatchery": {}}
        s = generate_tailscale_join_sh(plan_no_url)
        self.assertIn("HEADSCALE_URL", s)


class TestWriteAllScripts(unittest.TestCase):
    def test_writes_core_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = write_all_scripts(PLAN, Path(tmp))
            for name in ("spawn.sh", "phase-00-preflight.sh", "phase-00-host.sh",
                         "phase-01-proxmox.sh", "phase-02-vms.sh",
                         "phase-03-cloudinit.sh", "phase-04-k3s.sh",
                         "phase-06-verify.sh"):
                self.assertIn(name, written, f"{name} not in written")
                self.assertTrue(written[name].exists())

    def test_ha_script_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = write_all_scripts(PLAN, Path(tmp), include_ha=True)
            self.assertIn("phase-05-ha.sh", written)

    def test_wan_script_written_when_wan_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = write_all_scripts(WAN_PLAN, Path(tmp), include_wan_phase=True)
            self.assertIn("tailscale-join.sh", written)
            self.assertTrue(written["tailscale-join.sh"].exists())

    def test_wan_script_absent_for_lan(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = write_all_scripts(PLAN, Path(tmp), include_wan_phase=False)
            self.assertNotIn("tailscale-join.sh", written)

    def test_scripts_are_bash(self):
        with tempfile.TemporaryDirectory() as tmp:
            written = write_all_scripts(PLAN, Path(tmp))
            for path in written.values():
                self.assertTrue(path.read_text().startswith("#!/usr/bin/env bash"))


if __name__ == "__main__":
    unittest.main()
