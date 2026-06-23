#!/usr/bin/env python3
"""
Tests for generate-setup-manifest.py — setup manifest generator.

Covers:
  - build_markdown(): section headers, content from bootstrap-state.json
  - to_import_json(): flat key-value dict for SETUP-GUIDE.html import
  - Individual section builders: host, network, storage, VMs, DNS, secrets,
      backup, service contracts, external deps, reconstruction drills
  - LAN and WAN profile rendering differences
  - Empty-state handling (missing sections produce graceful fallbacks)
"""

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

# Import from the script (strip .py for importability — it's a direct-run script,
# so we import by path manipulation)
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "generate_setup_manifest",
    REPO_ROOT / "proxmox-bootstrap" / "generate-setup-manifest.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

build_markdown    = _mod.build_markdown
to_import_json    = _mod.to_import_json
_section_host     = _mod._section_host
_section_network  = _mod._section_network
_section_storage  = _mod._section_storage
_section_vms      = _mod._section_vms
_section_dns      = _mod._section_dns
_section_secrets  = _mod._section_secrets
_section_backup   = _mod._section_backup


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_STATE = {
    "schema_version": "1.0",
    "cell_id": "proxmox-cell-a",
    "declared_at": "2026-06-01T00:00:00Z",
    "host_identity": {
        "hostname": "pve01",
        "fqdn":     "pve01.home.example.com",
        "domain":   "home.example.com",
        "proxmox_version": "8.1.3",
    },
    "network_topology": {
        "profile":         "lan",
        "management_cidr": "192.168.1.0/24",
        "gateway":         "192.168.1.1",
        "nameservers":     ["192.168.1.1", "8.8.8.8"],
        "search_domain":   "internal",
        "lan_config":      {"tls_mode": "self-signed", "dnsmasq_enabled": True},
        "wan_config":      None,
    },
    "storage_config": {
        "vm_disks": "local-zfs",
        "isos":     "local:iso",
        "snippets": "local:snippets",
    },
    "vms": [
        {"vmid": 100, "name": "infra-bootstrap", "role": "infra-bootstrap",
         "template_name": "ubuntu-2204-base"},
        {"vmid": 101, "name": "forgejo", "role": "forgejo",
         "template_name": "ubuntu-2204-base"},
    ],
    "dns_registry": [
        {"hostname": "pve01.internal", "ip": "192.168.1.10", "vmid": None, "role": "proxmox-host"},
        {"hostname": "infra.internal", "ip": "192.168.1.20", "vmid": 100, "role": "infra-bootstrap"},
        {"hostname": "forgejo.internal", "ip": "192.168.1.21", "vmid": 101, "role": "forgejo"},
    ],
    "secrets": [
        {"id": "pve01-root-password", "secret_type": "password",
         "keepass_path": "Infrastructure/pve01/root-password",
         "owning_cell": "proxmox-cell-a", "required_by": ["host:pve01"]},
    ],
    "service_contracts": [
        {"service": "forgejo", "vm": "forgejo",
         "provided_interfaces": [{"protocol": "https", "port": 3000}],
         "required_interfaces": [],
         "backup_job": "pbs-daily-vms"},
    ],
    "external_dependencies": [
        {"id": "cloudflare-dns", "name": "Cloudflare DNS", "type": "dns_provider",
         "endpoint": "https://1.1.1.1", "status": "reachable"},
    ],
    "backup_config": {
        "layers": {
            "secrets": {"enabled": True, "destinations": [{"id": "local-usb"}],
                        "last_backup_at": "2026-06-01T03:00:00Z"},
            "config":  {"enabled": True, "destinations": [{"id": "b2-cloud"}],
                        "last_backup_at": "2026-06-01T03:00:00Z"},
        },
        "checkpoint_tag": "checkpoint",
    },
    "reconstruction_drills": [
        {"drill_id": "proxmox-cell-a_2026-06-01_drill", "outcome": "success",
         "started_at": "2026-06-01T10:00:00Z",
         "total_estimated_minutes": 80, "total_actual_minutes": 92},
    ],
}

WAN_STATE = {
    **BASE_STATE,
    "network_topology": {
        **BASE_STATE["network_topology"],
        "profile":        "wan",
        "headscale_url":  "https://pve01.home.example.com:8080",
        "ssl_cert_path":  "/etc/letsencrypt/live/pve01.home.example.com/fullchain.pem",
        "lan_config":     None,
        "wan_config": {
            "domain":          "home.example.com",
            "dns_provider":    "cloudflare",
            "ddns_enabled":    True,
            "ddns_update_interval_min": 5,
            "headscale_enabled": True,
            "tls_provider":    "certbot-cloudflare",
        },
    },
}


# ---------------------------------------------------------------------------
# build_markdown
# ---------------------------------------------------------------------------

class TestBuildMarkdown(unittest.TestCase):

    def setUp(self):
        self.md = build_markdown(BASE_STATE)

    def test_has_title(self):
        self.assertIn("Broodforge Setup Manifest", self.md)

    def test_has_cell_id(self):
        self.assertIn("proxmox-cell-a", self.md)

    def test_has_all_major_sections(self):
        for section in ("Host Identity", "Network", "Storage",
                        "Virtual Machines", "DNS Registry", "Secret Registry",
                        "Backup Configuration", "Service Contracts"):
            self.assertIn(section, self.md, f"Missing section: {section}")

    def test_vm_table_present(self):
        self.assertIn("infra-bootstrap", self.md)
        self.assertIn("forgejo", self.md)

    def test_ip_addresses_in_output(self):
        self.assertIn("192.168.1.21", self.md)

    def test_secret_keepass_path_in_output(self):
        self.assertIn("Infrastructure/pve01/root-password", self.md)

    def test_backup_destinations_shown(self):
        self.assertIn("local-usb", self.md)
        self.assertIn("b2-cloud", self.md)

    def test_reconstruction_drill_shown(self):
        self.assertIn("SUCCESS", self.md)

    def test_auto_tag_present(self):
        self.assertIn("[auto]", self.md)

    def test_wan_profile_shows_headscale(self):
        md = build_markdown(WAN_STATE)
        self.assertIn("headscale", md.lower())
        self.assertIn("pve01.home.example.com:8080", md)

    def test_lan_profile_no_headscale_url(self):
        # LAN profile should not show headscale URL
        self.assertNotIn(":8080", self.md)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

class TestSectionHost(unittest.TestCase):

    def test_hostname_present(self):
        content = "".join(_section_host(BASE_STATE))
        self.assertIn("pve01", content)

    def test_fqdn_present(self):
        content = "".join(_section_host(BASE_STATE))
        self.assertIn("pve01.home.example.com", content)

    def test_empty_host_identity_graceful(self):
        content = "".join(_section_host({}))
        self.assertIn("(not set)", content)


class TestSectionNetwork(unittest.TestCase):

    def test_lan_profile_shown(self):
        content = "".join(_section_network(BASE_STATE))
        self.assertIn("LAN-only", content)
        self.assertIn("192.168.1.0/24", content)

    def test_wan_profile_shown(self):
        content = "".join(_section_network(WAN_STATE))
        self.assertIn("WAN-capable", content)
        self.assertIn("cloudflare", content)
        self.assertIn("certbot-cloudflare", content)

    def test_gateway_present(self):
        content = "".join(_section_network(BASE_STATE))
        self.assertIn("192.168.1.1", content)


class TestSectionVMs(unittest.TestCase):

    def test_vm_table_has_all_vms(self):
        content = "".join(_section_vms(BASE_STATE))
        self.assertIn("infra-bootstrap", content)
        self.assertIn("forgejo", content)

    def test_vm_ip_shown(self):
        content = "".join(_section_vms(BASE_STATE))
        self.assertIn("192.168.1.21", content)

    def test_empty_vms_graceful(self):
        state = {**BASE_STATE, "vms": []}
        content = "".join(_section_vms(state))
        self.assertIn("No VMs", content)


class TestSectionDNS(unittest.TestCase):

    def test_all_entries_shown(self):
        content = "".join(_section_dns(BASE_STATE))
        self.assertIn("pve01.internal", content)
        self.assertIn("forgejo.internal", content)

    def test_empty_registry_graceful(self):
        content = "".join(_section_dns({**BASE_STATE, "dns_registry": []}))
        self.assertIn("No DNS", content)


class TestSectionSecrets(unittest.TestCase):

    def test_secret_id_shown(self):
        content = "".join(_section_secrets(BASE_STATE))
        self.assertIn("pve01-root-password", content)

    def test_keepass_path_shown(self):
        content = "".join(_section_secrets(BASE_STATE))
        self.assertIn("Infrastructure/pve01/root-password", content)

    def test_missing_keepass_path_shown(self):
        state = {**BASE_STATE, "secrets": [
            {"id": "no-path", "secret_type": "password", "keepass_path": None, "required_by": []}
        ]}
        content = "".join(_section_secrets(state))
        self.assertIn("not recorded", content)


class TestSectionBackup(unittest.TestCase):

    def test_layer_names_shown(self):
        content = "".join(_section_backup(BASE_STATE))
        self.assertIn("secrets", content)
        self.assertIn("config", content)

    def test_destination_ids_shown(self):
        content = "".join(_section_backup(BASE_STATE))
        self.assertIn("local-usb", content)

    def test_no_backup_config_graceful(self):
        content = "".join(_section_backup({}))
        self.assertIn("setup-backup.py", content)


# ---------------------------------------------------------------------------
# to_import_json
# ---------------------------------------------------------------------------

class TestToImportJson(unittest.TestCase):

    def setUp(self):
        self.data = to_import_json(BASE_STATE)

    def test_hostname_present(self):
        self.assertIn("host_identity.hostname", self.data)
        self.assertEqual(self.data["host_identity.hostname"], "pve01")

    def test_fqdn_present(self):
        self.assertIn("host_identity.fqdn", self.data)
        self.assertIn("pve01.home.example.com", self.data["host_identity.fqdn"])

    def test_management_cidr_present(self):
        self.assertIn("network_topology.management_cidr", self.data)
        self.assertEqual(self.data["network_topology.management_cidr"], "192.168.1.0/24")

    def test_forge_hostname_key_present(self):
        self.assertIn("forge-p03-hostname", self.data)

    def test_forgejo_vmid_ip_present(self):
        # forgejo has vmid 101, ip 192.168.1.21
        self.assertIn("forge-p04-forgejo", self.data)
        self.assertIn("101", self.data["forge-p04-forgejo"])

    def test_empty_values_excluded(self):
        # No (not set) strings in output
        for v in self.data.values():
            self.assertNotIn("(not set)", str(v))

    def test_wan_fields_present_for_wan_profile(self):
        data = to_import_json(WAN_STATE)
        self.assertIn("network_topology.headscale_url", data)
        self.assertIn(":8080", data["network_topology.headscale_url"])

    def test_backup_rows_present(self):
        self.assertIn("__backup_rows__", self.data)
        rows = self.data["__backup_rows__"]
        self.assertIsInstance(rows, list)
        self.assertGreater(len(rows), 0)

    def test_backup_rows_keepass_entry(self):
        rows = self.data["__backup_rows__"]
        kp = [r for r in rows if "keepass" in r.get("what", "").lower()
              or "kdbx" in r.get("what", "").lower()]
        self.assertGreater(len(kp), 0, "Should have a KeePass row")

    def test_backup_rows_config_state_entry(self):
        rows = self.data["__backup_rows__"]
        cfg = [r for r in rows if "bootstrap-state" in r.get("what", "").lower()]
        self.assertGreater(len(cfg), 0, "Should have a config-state row")

    def test_backup_rows_vm_entries(self):
        rows = self.data["__backup_rows__"]
        vm_rows = [r for r in rows if r.get("what", "").startswith("VM:")]
        # BASE_STATE has forgejo and infra-bootstrap
        self.assertGreaterEqual(len(vm_rows), 2, "Should have one row per VM")

    def test_backup_rows_all_have_source_manifest(self):
        rows = self.data["__backup_rows__"]
        for row in rows:
            self.assertEqual(row.get("source"), "manifest",
                             f"Row missing source=manifest: {row}")

    def test_backup_rows_have_required_keys(self):
        rows = self.data["__backup_rows__"]
        for row in rows:
            for key in ("what", "location", "credential", "notes", "source"):
                self.assertIn(key, row, f"Row missing key '{key}': {row}")

    def test_backup_rows_vm_includes_ip(self):
        rows = self.data["__backup_rows__"]
        forgejo_row = next((r for r in rows if "forgejo" in r.get("what", "")), None)
        self.assertIsNotNone(forgejo_row, "Should have a forgejo VM row")
        self.assertIn("192.168.1.21", forgejo_row["what"])

    def test_backup_rows_destination_layer_from_config(self):
        rows = self.data["__backup_rows__"]
        layer_rows = [r for r in rows if r.get("what", "").startswith("Backup layer:")]
        # BASE_STATE has secrets + config layers
        self.assertGreaterEqual(len(layer_rows), 2)
        dest_locs = " ".join(r.get("location", "") for r in layer_rows)
        self.assertIn("local-usb", dest_locs)
        self.assertIn("b2-cloud", dest_locs)


# ---------------------------------------------------------------------------
# Real fixture validation
# ---------------------------------------------------------------------------

class TestManifestFromFixture(unittest.TestCase):

    def test_fixture_produces_valid_markdown(self):
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
        state = json.loads(fixture_path.read_text(encoding="utf-8"))
        md = build_markdown(state)
        self.assertIn("Broodforge Setup Manifest", md)
        self.assertGreater(len(md), 500)

    def test_fixture_produces_valid_import_json(self):
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
        state = json.loads(fixture_path.read_text(encoding="utf-8"))
        data  = to_import_json(state)
        self.assertIsInstance(data, dict)
        self.assertGreater(len(data), 3)

    def test_fixture_backup_rows_present_and_populated(self):
        fixture_path = REPO_ROOT / "tests" / "fixtures" / "bootstrap" / "bootstrap-state.json"
        state = json.loads(fixture_path.read_text(encoding="utf-8"))
        data  = to_import_json(state)
        self.assertIn("__backup_rows__", data)
        rows = data["__backup_rows__"]
        self.assertIsInstance(rows, list)
        # KeePass + config state + at least 4 VMs from the fixture
        self.assertGreaterEqual(len(rows), 4)
        # All rows have required structure
        for row in rows:
            for key in ("what", "location", "credential", "notes", "source"):
                self.assertIn(key, row)


if __name__ == "__main__":
    unittest.main()
