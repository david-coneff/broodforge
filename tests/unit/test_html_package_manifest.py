"""
test_html_package_manifest.py — HTML package manifest tests.

Covers:
  build_forge_manifest_html   — structure, key fields, operator checklist
  build_spawn_manifest_html   — structure, service disposition, operator checklist
  build_phoenix_manifest_html — structure, waves, operator checklist
  AD-047 architecture pattern  — HTML manifest present in forge and spawn package contents
"""

import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "proxmox-bootstrap"))

import html_package_manifest as _hpm


def _now():
    return "2026-06-02T12:00:00+00:00"


def _forge_manifest():
    return {
        "cell_id": "pve01-cell",
        "host_identity": {
            "hostname": "pve01",
            "fqdn": "pve01.home.example.com",
            "domain": "home.example.com",
        },
        "network_topology": {
            "management_cidr": "192.168.1.0/24",
            "gateway": "192.168.1.1",
            "ssl_provider": "certbot",
            "ddns_provider": "cloudflare",
            "headscale_url": "https://pve01.home.example.com:8080",
        },
        "vms": [
            {"name": "forgejo", "vmid": 101, "role": "git", "memory_mb": 4096, "cores": 2, "initial_ip": "192.168.1.101"},
            {"name": "k3s-server-01", "vmid": 102, "role": "k3s-server", "memory_mb": 8192, "cores": 4, "initial_ip": "192.168.1.102"},
        ],
        "storage_config": {
            "zfs_pool_name": "tank",
            "local_lvm": "local-lvm",
        },
        "setup_mode": "autonomous",
    }


def _spawn_manifest():
    return {
        "cell_id": "pve01-cell",
        "target_hostname": "broodling-01",
        "k3s_server_address": "192.168.1.102",
        "proxmox_join_address": "192.168.1.10",
    }


def _spawn_plan():
    return {
        "target_hostname": "broodling-01",
        "execution_mode": "autonomous",
        "network_mode": "lan",
        "vmid_block": {"start": 200, "end": 299},
        "ip_block": ["192.168.1.201", "192.168.1.202"],
        "zfs_topology": "mirror",
        "k3s_role": "worker",
        "disposition": {
            "services": ["k3s-worker", "longhorn-node"],
            "excluded": [{"service": "pbs-datastore", "reason": "insufficient disk"}],
        },
    }


def _phoenix_playbook():
    return {
        "cell_id": "pve01-cell",
        "target_node": {"hostname": "pve01", "role": "hatchery", "k3s_role": "server"},
        "restoration_scope": "full",
        "identity": {
            "lan_ip": "192.168.1.10",
            "vmids": [101, 102, 103],
            "bridge_names": ["vmbr0"],
            "zfs_pool_name": "tank",
        },
        "estimated_total_minutes": 45,
        "waves": [
            {"wave": 0, "name": "Network Reconstruction", "steps": [
                {"action": "reconstruct_bridges", "commands": []},
            ]},
            {"wave": 1, "name": "ZFS Pool", "steps": [
                {"action": "create_pool", "commands": []},
            ]},
            {"wave": 2, "name": "Host Config", "steps": [
                {"action": "configure_hostname", "commands": []},
            ]},
            {"wave": 3, "name": "VM Restore", "steps": [
                {"action": "restore_vm", "commands": []},
            ]},
            {"wave": 4, "name": "k3s Rejoin", "steps": [
                {"action": "k3s_join", "commands": []},
            ]},
        ],
    }


# ===========================================================================
# Forge manifest HTML
# ===========================================================================

class TestForgeManifestHtml:

    def test_returns_html_string(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_cell_id(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        assert "pve01-cell" in html

    def test_contains_hostname(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        assert "pve01" in html

    def test_contains_fqdn(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        assert "pve01.home.example.com" in html

    def test_contains_management_cidr(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        assert "192.168.1.0/24" in html

    def test_contains_vm_table(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        assert "forgejo" in html
        assert "k3s-server-01" in html

    def test_contains_vmid(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        assert "101" in html
        assert "102" in html

    def test_contains_package_contents_section(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        assert "forge.sh" in html
        assert "forge-workbook.html" in html

    def test_contains_operator_checklist(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        assert "KeePass gate" in html or "master password" in html.lower()
        assert "bash forge.sh" in html

    def test_contains_all_phase_descriptions(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        for phase in ["phase-00", "phase-01", "phase-03", "phase-05", "phase-08"]:
            assert phase in html

    def test_ssl_provider_shown(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        assert "certbot" in html

    def test_headscale_url_shown(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        assert "headscale" in html.lower()

    def test_empty_vms_no_crash(self):
        m = _forge_manifest()
        m["vms"] = []
        html = _hpm.build_forge_manifest_html(m, now_fn=_now)
        assert "pve01-cell" in html

    def test_no_backup_shows_warning(self):
        m = _forge_manifest()
        # No backup_config key
        html = _hpm.build_forge_manifest_html(m, now_fn=_now)
        assert "backup" in html.lower()

    def test_html_is_self_contained(self):
        html = _hpm.build_forge_manifest_html(_forge_manifest(), now_fn=_now)
        # No external CSS or JS links
        assert '<link rel="stylesheet"' not in html
        assert "cdn.jsdelivr" not in html
        assert "googleapis.com" not in html


# ===========================================================================
# Spawn manifest HTML
# ===========================================================================

class TestSpawnManifestHtml:

    def test_returns_html_string(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _spawn_plan(), now_fn=_now)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_hostname(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _spawn_plan(), now_fn=_now)
        assert "broodling-01" in html

    def test_contains_cell_id(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _spawn_plan(), now_fn=_now)
        assert "pve01-cell" in html

    def test_contains_vmid_block(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _spawn_plan(), now_fn=_now)
        assert "200" in html or "vmid" in html.lower()

    def test_contains_services(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _spawn_plan(), now_fn=_now)
        assert "k3s-worker" in html
        assert "longhorn-node" in html

    def test_contains_excluded_services(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _spawn_plan(), now_fn=_now)
        assert "pbs-datastore" in html

    def test_contains_operator_checklist(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _spawn_plan(), now_fn=_now)
        assert "bash spawn.sh" in html

    def test_contains_package_contents(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _spawn_plan(), now_fn=_now)
        assert "spawn-manifest.json" in html
        assert "phase-00-preflight.sh" in html

    def test_interactive_mode_noted(self):
        plan = _spawn_plan()
        plan["execution_mode"] = "interactive"
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), plan, now_fn=_now)
        assert "interactive" in html.lower()

    def test_no_plan_no_crash(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), None, now_fn=_now)
        assert "pve01-cell" in html

    def test_wan_mode_shows_headscale_note(self):
        plan = _spawn_plan()
        plan["network_mode"] = "wan"
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), plan, now_fn=_now)
        assert "Headscale" in html or "headscale" in html


# ===========================================================================
# Phoenix manifest HTML
# ===========================================================================

class TestPhoenixManifestHtml:

    def test_returns_html_string(self):
        html = _hpm.build_phoenix_manifest_html(_phoenix_playbook(), now_fn=_now)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_hostname(self):
        html = _hpm.build_phoenix_manifest_html(_phoenix_playbook(), now_fn=_now)
        assert "pve01" in html

    def test_contains_cell_id(self):
        html = _hpm.build_phoenix_manifest_html(_phoenix_playbook(), now_fn=_now)
        assert "pve01-cell" in html

    def test_contains_vmids(self):
        html = _hpm.build_phoenix_manifest_html(_phoenix_playbook(), now_fn=_now)
        assert "101" in html
        assert "102" in html

    def test_contains_estimated_minutes(self):
        html = _hpm.build_phoenix_manifest_html(_phoenix_playbook(), now_fn=_now)
        assert "45" in html

    def test_contains_waves_table(self):
        html = _hpm.build_phoenix_manifest_html(_phoenix_playbook(), now_fn=_now)
        assert "Wave" in html
        assert "Network Reconstruction" in html or "wave" in html.lower()

    def test_contains_operator_checklist(self):
        html = _hpm.build_phoenix_manifest_html(_phoenix_playbook(), now_fn=_now)
        assert "bash run-all.sh" in html

    def test_danger_warning_present(self):
        html = _hpm.build_phoenix_manifest_html(_phoenix_playbook(), now_fn=_now)
        assert "destroy" in html.lower() or "danger" in html.lower() or "destroyed" in html.lower()

    def test_restoration_scope_shown(self):
        html = _hpm.build_phoenix_manifest_html(_phoenix_playbook(), now_fn=_now)
        assert "full" in html

    def test_partial_scope_shows_deferred(self):
        pb = _phoenix_playbook()
        pb["restoration_scope"] = "partial"
        pb["deferred_services"] = ["vault", "gitea"]
        html = _hpm.build_phoenix_manifest_html(pb, now_fn=_now)
        assert "vault" in html or "deferred" in html.lower()


# ===========================================================================
# Architecture pattern: AD-047 integration
# ===========================================================================

def _current_spawn_plan():
    """Spawn plan in the format actually produced by spawn_planner.py (current format)."""
    return {
        "cell_id": "cell-alpha",
        "hostname": "pve02",
        "domain": "home.example.com",
        "lan_ip": "192.168.1.15",
        "disposition": {
            "execution_mode": "autonomous",
            "network_mode": "lan",
            "services": ["k3s-worker", "longhorn"],
            "excluded": [],
        },
        "storage": {"pool_name": "rpool", "topology": "mirror", "disk_ids": ["/dev/sda", "/dev/sdb"]},
        "vms": [
            {"name": "k3s-worker-01", "vmid": 200, "ip": "192.168.1.50"},
            {"name": "k3s-worker-02", "vmid": 201, "ip": "192.168.1.51"},
        ],
        "k3s": {"role": "worker", "server_url": "https://192.168.1.102:6443"},
        "k3s_role": "worker",
        "hatchery": {"proxmox_cluster_address": "192.168.1.10"},
    }


class TestSpawnManifestCurrentPlanFormat:
    """Verify build_spawn_manifest_html handles the current spawn_planner.py output format."""

    def test_hostname_from_current_plan(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _current_spawn_plan(), now_fn=_now)
        assert "pve02" in html

    def test_exec_mode_from_disposition(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _current_spawn_plan(), now_fn=_now)
        assert "autonomous" in html

    def test_vmids_from_vms_list(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _current_spawn_plan(), now_fn=_now)
        assert "200" in html and "201" in html

    def test_k3s_role_from_nested_k3s(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _current_spawn_plan(), now_fn=_now)
        assert "worker" in html.lower()

    def test_zfs_topology_from_storage(self):
        html = _hpm.build_spawn_manifest_html(_spawn_manifest(), _current_spawn_plan(), now_fn=_now)
        assert "mirror" in html


class TestAD047ArchitecturePattern:

    def test_forge_package_contents_includes_html_manifest(self):
        from assemble_forge_package import package_contents
        m = _forge_manifest()
        contents = package_contents(m)
        assert "forge-manifest.html" in contents

    def test_html_manifest_is_self_contained_all_three_types(self):
        for fn, args in [
            (_hpm.build_forge_manifest_html, (_forge_manifest(),)),
            (_hpm.build_spawn_manifest_html, (_spawn_manifest(), _spawn_plan())),
            (_hpm.build_phoenix_manifest_html, (_phoenix_playbook(),)),
        ]:
            html = fn(*args, now_fn=_now)
            assert '<link rel="stylesheet"' not in html, f"{fn.__name__} has external CSS"
            assert "cdn.jsdelivr" not in html
            assert html.startswith("<!DOCTYPE html>")
            assert 'charset="UTF-8"' in html
