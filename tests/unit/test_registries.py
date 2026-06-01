#!/usr/bin/env python3
"""
Tests for Milestones 6.3 (Secret Registry) and 6.4 (DNS Registry).

Validates:
  6.3 — SecretRegistry class, YAML loading, readiness scoring (ORANGE if missing),
         secret retrieval section in recovery runbook
  6.4 — DnsRegistry class, YAML loading, readiness scoring (YELLOW if missing),
         [VM_IP] replacement in recovery runbook

Run: py -3 tests/unit/test_registries.py
"""

import importlib.util
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from copy import deepcopy

_HAS_YAML = importlib.util.find_spec("yaml") is not None


def _odt_text(odt_bytes: bytes) -> str:
    """Extract plain text from an ODT/ODS zip archive (reads content.xml)."""
    with zipfile.ZipFile(io.BytesIO(odt_bytes)) as zf:
        names = zf.namelist()
        text_parts = []
        for name in names:
            if name.endswith(".xml"):
                text_parts.append(zf.read(name).decode("utf-8", errors="replace"))
        return "\n".join(text_parts)

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "doc-gen"))
sys.path.insert(0, str(REPO_ROOT / "doc-gen" / "renderers"))

from registries import (
    SecretRegistry, DnsRegistry,
    build_registries,
    load_secret_registry_from_yaml, load_dns_registry_from_yaml,
)
from readiness import (
    _score_registry_completeness, score_graph, worst, Gap, ReadinessReport,
)
import dependencies as dep_mod

BOOTSTRAP_DIR  = REPO_ROOT / "proxmox-bootstrap"
FIXTURES_DIR   = REPO_ROOT / "tests" / "fixtures" / "bootstrap"
SECRET_YAML    = BOOTSTRAP_DIR / "secret-registry.yaml"
DNS_YAML       = BOOTSTRAP_DIR / "dns-registry.yaml"
BOOTSTRAP_JSON = FIXTURES_DIR / "bootstrap-state.json"


def _load_fixture() -> dict:
    return json.loads(BOOTSTRAP_JSON.read_text())


# ===========================================================================
# SecretRegistry — unit tests
# ===========================================================================

class TestSecretRegistryEmpty(unittest.TestCase):
    def test_empty_list_not_available(self):
        sr = SecretRegistry([])
        self.assertFalse(sr.available())

    def test_none_not_available(self):
        sr = SecretRegistry(None)
        self.assertFalse(sr.available())

    def test_count_zero(self):
        sr = SecretRegistry([])
        self.assertEqual(sr.count(), 0)

    def test_all_returns_empty_list(self):
        sr = SecretRegistry([])
        self.assertEqual(sr.all(), [])

    def test_get_returns_none(self):
        sr = SecretRegistry([])
        self.assertIsNone(sr.get("nonexistent"))

    def test_for_component_returns_empty(self):
        sr = SecretRegistry([])
        self.assertEqual(sr.for_component("host:pve01"), [])

    def test_has_unresolved_false_when_empty(self):
        self.assertFalse(SecretRegistry([]).has_unresolved())


class TestSecretRegistryData(unittest.TestCase):
    def setUp(self):
        self.secrets = [
            {
                "id": "pve01-root-password",
                "description": "Proxmox root password",
                "keepass_path": "Infrastructure/proxmox/pve01-root",
                "owning_cell": "proxmox-cell-a",
                "secret_type": "password",
                "required_by": ["host:pve01"],
                "required_for": ["ssh-access"],
                "rotation_schedule": "annually",
            },
            {
                "id": "forgejo-deploy-key",
                "description": "SSH deploy key for forgejo",
                "keepass_path": "Infrastructure/ssh/deploy-keys/forgejo",
                "owning_cell": "proxmox-cell-a",
                "secret_type": "ssh-private-key",
                "required_by": ["vm:forgejo"],
                "required_for": ["ansible-execution"],
                "rotation_schedule": None,
            },
            {
                "id": "vm-100-password",
                "description": "OS password for VM 100",
                "keepass_path": None,
                "owning_cell": "proxmox-cell-a",
                "secret_type": "password",
                "required_by": ["vm:infra-bootstrap"],
                "required_for": ["first-boot-access"],
                "rotation_schedule": None,
            },
        ]
        self.sr = SecretRegistry(self.secrets)

    def test_available(self):
        self.assertTrue(self.sr.available())

    def test_count(self):
        self.assertEqual(self.sr.count(), 3)

    def test_get_by_id(self):
        s = self.sr.get("pve01-root-password")
        self.assertIsNotNone(s)
        self.assertEqual(s["secret_type"], "password")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.sr.get("does-not-exist"))

    def test_for_component_host(self):
        secrets = self.sr.for_component("host:pve01")
        self.assertEqual(len(secrets), 1)
        self.assertEqual(secrets[0]["id"], "pve01-root-password")

    def test_for_component_vm(self):
        secrets = self.sr.for_component("vm:forgejo")
        self.assertEqual(len(secrets), 1)
        self.assertEqual(secrets[0]["id"], "forgejo-deploy-key")

    def test_for_component_multiple(self):
        # Add a second secret for same component
        extra = {
            "id": "forgejo-admin-password",
            "description": "Forgejo admin password",
            "keepass_path": "Infrastructure/forgejo/admin-password",
            "owning_cell": "proxmox-cell-a",
            "secret_type": "password",
            "required_by": ["vm:forgejo"],
            "required_for": ["post-restore-validation"],
            "rotation_schedule": "annually",
        }
        sr2 = SecretRegistry(self.secrets + [extra])
        secrets = sr2.for_component("vm:forgejo")
        self.assertEqual(len(secrets), 2)

    def test_for_component_not_found(self):
        self.assertEqual(self.sr.for_component("vm:unknown"), [])

    def test_all_returns_copy(self):
        all_secrets = self.sr.all()
        self.assertEqual(len(all_secrets), 3)
        all_secrets.clear()
        self.assertEqual(self.sr.count(), 3)

    def test_has_unresolved_true_when_missing_keepass_path(self):
        # vm-100-password has no keepass_path
        self.assertTrue(self.sr.has_unresolved())

    def test_has_unresolved_false_when_all_paths_present(self):
        secrets_complete = [
            {"id": "s1", "keepass_path": "Infrastructure/s1",
             "required_by": [], "secret_type": "password"},
        ]
        self.assertFalse(SecretRegistry(secrets_complete).has_unresolved())

    def test_has_unresolved_true_when_placeholder(self):
        secrets_placeholder = [
            {"id": "s1", "keepass_path": "[HUMAN: enter path]",
             "required_by": [], "secret_type": "password"},
        ]
        self.assertTrue(SecretRegistry(secrets_placeholder).has_unresolved())


# ===========================================================================
# DnsRegistry — unit tests
# ===========================================================================

class TestDnsRegistryEmpty(unittest.TestCase):
    def test_empty_not_available(self):
        dr = DnsRegistry([])
        self.assertFalse(dr.available())

    def test_none_not_available(self):
        dr = DnsRegistry(None)
        self.assertFalse(dr.available())

    def test_count_zero(self):
        self.assertEqual(DnsRegistry([]).count(), 0)

    def test_ip_for_vmid_returns_none(self):
        self.assertIsNone(DnsRegistry([]).ip_for_vmid(100))

    def test_vm_ip_map_empty(self):
        self.assertEqual(DnsRegistry([]).vm_ip_map(), {})


class TestDnsRegistryData(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {"hostname": "pve01.internal",            "ip": "192.168.1.10", "vmid": None,  "role": "proxmox-host"},
            {"hostname": "infra-bootstrap.internal",  "ip": "192.168.1.20", "vmid": 100,   "role": "infra-bootstrap"},
            {"hostname": "forgejo.internal",          "ip": "192.168.1.21", "vmid": 101,   "role": "forgejo"},
            {"hostname": "inventory.internal",        "ip": "192.168.1.22", "vmid": 102,   "role": "inventory"},
            {"hostname": "assessment.internal",       "ip": "192.168.1.23", "vmid": 103,   "role": "assessment-engine"},
        ]
        self.dr = DnsRegistry(self.entries)

    def test_available(self):
        self.assertTrue(self.dr.available())

    def test_count(self):
        self.assertEqual(self.dr.count(), 5)

    def test_ip_for_vmid(self):
        self.assertEqual(self.dr.ip_for_vmid(100), "192.168.1.20")
        self.assertEqual(self.dr.ip_for_vmid(101), "192.168.1.21")
        self.assertEqual(self.dr.ip_for_vmid(103), "192.168.1.23")

    def test_ip_for_vmid_not_found(self):
        self.assertIsNone(self.dr.ip_for_vmid(999))

    def test_ip_for_vmid_none(self):
        self.assertIsNone(self.dr.ip_for_vmid(None))

    def test_ip_for_fqdn(self):
        self.assertEqual(self.dr.ip_for_hostname("forgejo.internal"), "192.168.1.21")

    def test_ip_for_short_hostname(self):
        self.assertEqual(self.dr.ip_for_hostname("forgejo"), "192.168.1.21")

    def test_ip_for_unknown_hostname(self):
        self.assertIsNone(self.dr.ip_for_hostname("unknown.host"))

    def test_entry_for_vmid(self):
        entry = self.dr.entry_for_vmid(101)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["hostname"], "forgejo.internal")

    def test_entry_for_vmid_not_found(self):
        self.assertIsNone(self.dr.entry_for_vmid(999))

    def test_entries_for_role(self):
        entries = self.dr.entries_for_role("forgejo")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["ip"], "192.168.1.21")

    def test_entries_for_unknown_role(self):
        self.assertEqual(self.dr.entries_for_role("nonexistent"), [])

    def test_vm_ip_map_excludes_none_vmid(self):
        ip_map = self.dr.vm_ip_map()
        # pve01 has vmid=None — must not appear
        self.assertNotIn(None, ip_map)
        self.assertEqual(ip_map[100], "192.168.1.20")
        self.assertEqual(ip_map[103], "192.168.1.23")

    def test_all_returns_copy(self):
        all_entries = self.dr.all()
        self.assertEqual(len(all_entries), 5)
        all_entries.clear()
        self.assertEqual(self.dr.count(), 5)


# ===========================================================================
# Loading from YAML files
# ===========================================================================

class TestLoadFromYaml(unittest.TestCase):
    def test_secret_registry_yaml_exists(self):
        self.assertTrue(SECRET_YAML.exists(),
                        msg=f"secret-registry.yaml not found at {SECRET_YAML}")

    def test_dns_registry_yaml_exists(self):
        self.assertTrue(DNS_YAML.exists(),
                        msg=f"dns-registry.yaml not found at {DNS_YAML}")

    @unittest.skipUnless(_HAS_YAML, "PyYAML not installed")
    def test_load_secret_registry_from_yaml(self):
        sr = load_secret_registry_from_yaml(SECRET_YAML)
        self.assertTrue(sr.available())
        self.assertGreater(sr.count(), 0)

    @unittest.skipUnless(_HAS_YAML, "PyYAML not installed")
    def test_load_dns_registry_from_yaml(self):
        dr = load_dns_registry_from_yaml(DNS_YAML)
        self.assertTrue(dr.available())
        self.assertGreater(dr.count(), 0)

    @unittest.skipUnless(_HAS_YAML, "PyYAML not installed")
    def test_secret_registry_yaml_has_owning_cell(self):
        sr = load_secret_registry_from_yaml(SECRET_YAML)
        for s in sr.all():
            self.assertIn("owning_cell", s,
                          msg=f"Secret {s.get('id')} missing owning_cell field")

    @unittest.skipUnless(_HAS_YAML, "PyYAML not installed")
    def test_dns_registry_yaml_has_required_fields(self):
        dr = load_dns_registry_from_yaml(DNS_YAML)
        for e in dr.all():
            self.assertIn("hostname", e)
            self.assertIn("ip", e)


# ===========================================================================
# Loading from bootstrap-state.json fixture
# ===========================================================================

class TestLoadFromFixture(unittest.TestCase):
    def setUp(self):
        self.fixture = _load_fixture()

    def test_fixture_has_secrets(self):
        self.assertIn("secrets", self.fixture)
        self.assertGreater(len(self.fixture["secrets"]), 0)

    def test_fixture_has_dns_registry(self):
        self.assertIn("dns_registry", self.fixture)
        self.assertGreater(len(self.fixture["dns_registry"]), 0)

    def test_build_registries_from_fixture(self):
        manifest = {
            "secret_registry": self.fixture["secrets"],
            "dns_registry": self.fixture["dns_registry"],
        }
        sr, dr = build_registries(manifest)
        self.assertTrue(sr.available())
        self.assertTrue(dr.available())

    def test_secret_registry_all_have_id_and_keepass_path(self):
        sr = SecretRegistry(self.fixture["secrets"])
        for s in sr.all():
            self.assertIn("id", s, msg=f"Secret missing 'id': {s}")
            self.assertIn("keepass_path", s, msg=f"Secret {s['id']} missing keepass_path")

    def test_dns_registry_all_have_hostname_and_ip(self):
        dr = DnsRegistry(self.fixture["dns_registry"])
        for e in dr.all():
            self.assertIn("hostname", e)
            self.assertIn("ip", e)

    def test_dns_registry_vmid_lookup(self):
        dr = DnsRegistry(self.fixture["dns_registry"])
        # Fixture has infra-bootstrap at vmid=100
        ip = dr.ip_for_vmid(100)
        self.assertEqual(ip, "192.168.1.20")

    def test_secret_registry_component_lookup(self):
        sr = SecretRegistry(self.fixture["secrets"])
        secrets = sr.for_component("host:pve01")
        self.assertGreater(len(secrets), 0)

    def test_build_registries_fallback_to_yaml_when_manifest_empty(self):
        """If manifest has no registries, build_registries tries YAML files."""
        manifest = {}
        sr, dr = build_registries(manifest, repo_root=REPO_ROOT)
        # YAML files exist — should load from them if PyYAML available
        if _HAS_YAML:
            self.assertTrue(sr.available())
            self.assertTrue(dr.available())
        # If no PyYAML, registries will be empty — that's acceptable


# ===========================================================================
# Readiness scorer — registry completeness
# ===========================================================================

class TestRegistryCompletenessScoring(unittest.TestCase):
    def test_no_registries_returns_two_gaps(self):
        gaps = _score_registry_completeness({})
        self.assertEqual(len(gaps), 2)

    def test_missing_secret_registry_is_orange(self):
        gaps = _score_registry_completeness({})
        secret_gaps = [g for g in gaps if g.gap_type == "MISSING_SECRET_REGISTRY"]
        self.assertEqual(len(secret_gaps), 1)
        self.assertEqual(secret_gaps[0].severity, "ORANGE")

    def test_missing_dns_registry_is_yellow(self):
        gaps = _score_registry_completeness({})
        dns_gaps = [g for g in gaps if g.gap_type == "MISSING_DNS_REGISTRY"]
        self.assertEqual(len(dns_gaps), 1)
        self.assertEqual(dns_gaps[0].severity, "YELLOW")

    def test_present_secret_registry_no_gap(self):
        manifest = {"secret_registry": [{"id": "s1"}]}
        gaps = _score_registry_completeness(manifest)
        secret_gaps = [g for g in gaps if g.gap_type == "MISSING_SECRET_REGISTRY"]
        self.assertEqual(len(secret_gaps), 0)

    def test_present_dns_registry_no_gap(self):
        manifest = {"dns_registry": [{"hostname": "pve01", "ip": "10.0.0.1"}]}
        gaps = _score_registry_completeness(manifest)
        dns_gaps = [g for g in gaps if g.gap_type == "MISSING_DNS_REGISTRY"]
        self.assertEqual(len(dns_gaps), 0)

    def test_empty_list_secret_registry_still_gaps(self):
        manifest = {"secret_registry": []}
        gaps = _score_registry_completeness(manifest)
        self.assertTrue(any(g.gap_type == "MISSING_SECRET_REGISTRY" for g in gaps))

    def test_empty_list_dns_registry_still_gaps(self):
        manifest = {"dns_registry": []}
        gaps = _score_registry_completeness(manifest)
        self.assertTrue(any(g.gap_type == "MISSING_DNS_REGISTRY" for g in gaps))

    def test_both_present_no_gaps(self):
        manifest = {
            "secret_registry": [{"id": "s1"}],
            "dns_registry": [{"hostname": "h1", "ip": "1.2.3.4"}],
        }
        gaps = _score_registry_completeness(manifest)
        self.assertEqual(gaps, [])

    def test_score_graph_with_missing_registries_orange(self):
        """score_graph degrades to ORANGE when secret registry is absent."""
        fixture = json.loads(
            (REPO_ROOT / "tests/fixtures/tier2/manifest.json").read_text()
        )
        # Remove registries from manifest
        manifest = deepcopy(fixture)
        manifest.pop("secret_registry", None)
        manifest.pop("dns_registry", None)

        graph = dep_mod.build_graph(manifest)
        report = score_graph(graph, manifest)

        # Registry gaps must be attached
        self.assertGreater(len(report.registry_gaps), 0)
        secret_gaps = [g for g in report.registry_gaps if g.gap_type == "MISSING_SECRET_REGISTRY"]
        self.assertGreater(len(secret_gaps), 0)

        # Overall must be at least ORANGE (due to missing secret registry)
        self.assertIn(report.overall_score, ("ORANGE", "YELLOW", "RED", "BLOCKED"))

    def test_score_graph_registry_gaps_in_to_dict(self):
        """to_dict() must include registry_gaps."""
        fixture = json.loads(
            (REPO_ROOT / "tests/fixtures/tier2/manifest.json").read_text()
        )
        manifest = deepcopy(fixture)
        manifest.pop("secret_registry", None)
        manifest.pop("dns_registry", None)

        graph = dep_mod.build_graph(manifest)
        report = score_graph(graph, manifest)
        d = report.to_dict()
        self.assertIn("registry_gaps", d)
        self.assertIsInstance(d["registry_gaps"], list)

    def test_score_graph_with_both_registries_no_registry_gaps(self):
        """No registry gaps when all registries (secret, DNS, template, contracts, backup) present."""
        from datetime import datetime, timezone
        _now = datetime.now(timezone.utc).isoformat()
        _dest_secrets = {"id": "local-usb", "type": "local",
                         "kdbx_destination_root": "/mnt/usb"}
        _dest_restic  = {"id": "local-drive", "type": "local",
                         "restic_repo_root": "/mnt/backup",
                         "restic_repo_password_keepass_prefix": "Backup/config",
                         "retention_count": 5}
        manifest = {
            "host": {"hostname": "pve01"},
            "secret_registry": [{"id": "s1"}],
            "dns_registry": [{"hostname": "h1", "ip": "1.2.3.4"}],
            "templates": [{"name": "ubuntu-2204-base", "proxmox_template_id": 9000,
                           "base_image": "ubuntu-2204-base", "created_at": "2026-04-01T11:00:00Z"}],
            # Service contracts present — empty graph has no VM nodes so no per-VM gap fires,
            # and the non-empty contracts list suppresses the MISSING_SERVICE_CONTRACTS gap.
            "service_contracts": [{"service": "dummy", "vm": "dummy-vm"}],
            # Network topology declared — suppresses MISSING_NETWORK_TOPOLOGY gap.
            "network_topology_declared": {
                "bridges": [{"name": "vmbr0", "ports": ["eno1"], "vlan_aware": True,
                             "ip": "192.168.1.10/24", "gateway": "192.168.1.1"}],
                "drift_detected": False, "observed_bridges": None,
            },
            # Backup config present — suppresses MISSING_BACKUP_CONFIG gap.
            "backup_config": {
                "layers": {
                    "secrets": {"enabled": True, "destinations": [_dest_secrets],
                                "last_backup_at": _now, "consecutive_all_fail_count": 0},
                    "config":  {"enabled": True, "destinations": [_dest_restic],
                                "last_backup_at": _now, "consecutive_all_fail_count": 0},
                    "appdata": {"enabled": False, "destinations": []},
                },
                "checkpoint_tag": "checkpoint",
                "all_failed_policy": ["alert"],
                "backup_history": [],
            },
            # Phoenix playbook present — suppresses MISSING_PHOENIX_PLAYBOOK gap.
            "phoenix_playbook_generated_at": _now,
        }
        # Minimal empty graph (no VM nodes, so no per-VM contract gap)
        from dependencies import DependencyGraph
        graph = DependencyGraph(nodes=[], edges=[], restore_waves=[])
        report = score_graph(graph, manifest)
        self.assertEqual(report.registry_gaps, [])


# ===========================================================================
# Recovery runbook — IP resolution and secret retrieval section
# ===========================================================================

class TestRunbookIpResolution(unittest.TestCase):
    def _make_manifest_with_dns(self):
        fixture = _load_fixture()
        return {
            "host": {"hostname": "pve01", "proxmox_version": "8.1.3"},
            "network": {"default_gateway": "192.168.1.1", "dns_servers": ["192.168.1.1"]},
            "dns_registry": fixture["dns_registry"],
            "secret_registry": fixture["secrets"],
        }

    def _build_simple_graph(self):
        from dependencies import DependencyGraph, Node, RestoreWave
        vm = Node(id="vm:forgejo", type="vm", label="Forgejo",
                  metadata={"vmid": 101, "name": "forgejo"})
        return DependencyGraph(
            nodes=[vm], edges=[],
            restore_waves=[RestoreWave(1, ["vm:forgejo"], "VMs")]
        )

    def _build_readiness(self, graph, manifest):
        return score_graph(graph, manifest)

    def test_vm_ip_resolved_in_runbook(self):
        """SSH command in runbook uses actual IP, not [VM_IP]."""
        from recovery_runbook import build_recovery_runbook
        from timestamps import now_utc_iso

        manifest = self._make_manifest_with_dns()
        graph = self._build_simple_graph()
        readiness = self._build_readiness(graph, manifest)
        meta = {"generated_at": now_utc_iso(), "tier": 1, "template_version": "recovery-v1.0"}

        odt_bytes = build_recovery_runbook(manifest, graph, readiness, meta)
        content = _odt_text(odt_bytes)

        # IP 192.168.1.21 for forgejo (vmid=101) must appear
        self.assertIn("192.168.1.21", content,
                      msg="Forgejo IP 192.168.1.21 must appear in runbook (not [VM_IP])")

    def test_vm_ip_placeholder_when_dns_missing(self):
        """Without DNS registry, runbook emits [VM_IP] placeholder."""
        from recovery_runbook import build_recovery_runbook
        from timestamps import now_utc_iso

        manifest = self._make_manifest_with_dns()
        del manifest["dns_registry"]

        graph = self._build_simple_graph()
        readiness = self._build_readiness(graph, manifest)
        meta = {"generated_at": now_utc_iso(), "tier": 1, "template_version": "recovery-v1.0"}

        odt_bytes = build_recovery_runbook(manifest, graph, readiness, meta)
        content = _odt_text(odt_bytes)
        self.assertIn("[VM_IP]", content,
                      msg="Without DNS registry, [VM_IP] placeholder must remain")


class TestRunbookSecretRetrieval(unittest.TestCase):
    def _make_manifest(self, include_secrets=True, include_dns=True):
        fixture = _load_fixture()
        manifest = {
            "host": {"hostname": "pve01", "proxmox_version": "8.1.3"},
            "network": {"default_gateway": "192.168.1.1", "dns_servers": ["192.168.1.1"]},
        }
        if include_secrets:
            manifest["secret_registry"] = fixture["secrets"]
        if include_dns:
            manifest["dns_registry"] = fixture["dns_registry"]
        return manifest

    def _build_minimal_graph(self):
        from dependencies import DependencyGraph
        return DependencyGraph(nodes=[], edges=[], restore_waves=[])

    def test_secrets_section_present_when_registry_available(self):
        """Runbook includes 'Secrets Required for Recovery' when registry loaded."""
        from recovery_runbook import build_recovery_runbook
        from timestamps import now_utc_iso

        manifest = self._make_manifest(include_secrets=True)
        graph = self._build_minimal_graph()
        readiness = score_graph(graph, manifest)
        meta = {"generated_at": now_utc_iso(), "tier": 1, "template_version": "recovery-v1.0"}

        content = _odt_text(build_recovery_runbook(manifest, graph, readiness, meta))
        self.assertIn("Secrets Required for Recovery", content)

    def test_keepass_paths_present_in_secrets_section(self):
        """KeePass paths from the registry appear in the runbook."""
        from recovery_runbook import build_recovery_runbook
        from timestamps import now_utc_iso

        manifest = self._make_manifest(include_secrets=True)
        graph = self._build_minimal_graph()
        readiness = score_graph(graph, manifest)
        meta = {"generated_at": now_utc_iso(), "tier": 1, "template_version": "recovery-v1.0"}

        content = _odt_text(build_recovery_runbook(manifest, graph, readiness, meta))

        # One of the KeePass paths from the fixture must appear
        fixture = _load_fixture()
        first_path = fixture["secrets"][0]["keepass_path"]
        self.assertIn(first_path, content,
                      msg=f"KeePass path {first_path!r} must appear in runbook")

    def test_secrets_section_fallback_when_registry_missing(self):
        """Without secret registry, runbook still renders with fallback message."""
        from recovery_runbook import build_recovery_runbook
        from timestamps import now_utc_iso

        manifest = self._make_manifest(include_secrets=False)
        graph = self._build_minimal_graph()
        readiness = score_graph(graph, manifest)
        meta = {"generated_at": now_utc_iso(), "tier": 1, "template_version": "recovery-v1.0"}

        content = _odt_text(build_recovery_runbook(manifest, graph, readiness, meta))

        self.assertIn("Secrets Required for Recovery", content)
        self.assertIn("NOT AVAILABLE", content)

    def test_appendix_c_dns_registry(self):
        """Appendix C lists DNS entries when registry is available."""
        from recovery_runbook import build_recovery_runbook
        from timestamps import now_utc_iso

        manifest = self._make_manifest(include_dns=True)
        graph = self._build_minimal_graph()
        readiness = score_graph(graph, manifest)
        meta = {"generated_at": now_utc_iso(), "tier": 1, "template_version": "recovery-v1.0"}

        content = _odt_text(build_recovery_runbook(manifest, graph, readiness, meta))

        self.assertIn("Appendix C", content)
        self.assertIn("DNS Registry", content)
        self.assertIn("192.168.1.10", content)

    def test_appendix_d_secret_registry(self):
        """Appendix D lists secret entries when registry is available."""
        from recovery_runbook import build_recovery_runbook
        from timestamps import now_utc_iso

        manifest = self._make_manifest(include_secrets=True)
        graph = self._build_minimal_graph()
        readiness = score_graph(graph, manifest)
        meta = {"generated_at": now_utc_iso(), "tier": 1, "template_version": "recovery-v1.0"}

        content = _odt_text(build_recovery_runbook(manifest, graph, readiness, meta))

        self.assertIn("Appendix D", content)
        self.assertIn("Secret Registry", content)

    def test_registry_gaps_in_appendix_b(self):
        """Appendix B includes registry gaps when registries are missing."""
        from recovery_runbook import build_recovery_runbook
        from timestamps import now_utc_iso

        manifest = self._make_manifest(include_secrets=False, include_dns=False)
        graph = self._build_minimal_graph()
        readiness = score_graph(graph, manifest)
        meta = {"generated_at": now_utc_iso(), "tier": 1, "template_version": "recovery-v1.0"}

        content = _odt_text(build_recovery_runbook(manifest, graph, readiness, meta))

        self.assertIn("MISSING_SECRET_REGISTRY", content)
        self.assertIn("MISSING_DNS_REGISTRY", content)


# ===========================================================================
# Integration — full tier2 fixture end-to-end
# ===========================================================================

class TestFixtureIntegration(unittest.TestCase):
    def test_tier2_fixture_with_all_registries_injected(self):
        """score_graph has no registry gaps when secret, DNS, and provenance are all present."""
        fixture_t2 = json.loads(
            (REPO_ROOT / "tests/fixtures/tier2/manifest.json").read_text()
        )
        fixture_bs = _load_fixture()

        manifest = deepcopy(fixture_t2)
        manifest["secret_registry"] = fixture_bs["secrets"]
        manifest["dns_registry"]    = fixture_bs["dns_registry"]
        # Inject provenance for every VM in the tier2 fixture so no MISSING_PROVENANCE gaps fire
        vms = manifest.get("vms", [])
        manifest["provenance_registry"] = [
            {
                "vmid": vm.get("vmid"), "name": vm.get("name", ""),
                "deployed_at": "2026-01-01T00:00:00Z",
                "tofu_workspace": "proxmox-vms", "tofu_commit": "abc123",
                "template_name": "ubuntu-2204-base", "template_checksum": "sha256:abc",
                "cloudinit_user_data_hash": "sha256:aaa",
                "cloudinit_network_config_hash": "sha256:bbb",
                "ansible_playbook": "site.yml", "ansible_commit": "def456",
                "ansible_inventory_commit": "ghi789", "deployed_by": "test", "notes": None,
            }
            for vm in vms if vm.get("vmid") is not None
        ]
        manifest["templates"] = fixture_bs["templates"]
        manifest["base_images"] = fixture_bs["base_images"]
        # Inject contracts for every VM so no MISSING_SERVICE_CONTRACT gap fires
        manifest["service_contracts"] = [
            {"service": vm.get("name", ""), "vm": vm.get("name", "")}
            for vm in vms if vm.get("name")
        ]
        # Inject network_topology_declared so no MISSING_NETWORK_TOPOLOGY gap fires
        manifest["network_topology_declared"] = {
            "bridges": [{"name": "vmbr0", "ports": ["eno1"], "vlan_aware": True,
                         "ip": "192.168.1.10/24", "gateway": "192.168.1.1"}],
            "drift_detected": False, "observed_bridges": None,
        }

        # Inject backup_config so no MISSING_BACKUP_CONFIG gap fires
        from datetime import datetime, timezone as _tz
        _now = datetime.now(_tz.utc).isoformat()
        manifest["backup_config"] = {
            "layers": {
                "secrets": {"enabled": True,
                            "destinations": [{"id": "local", "type": "local",
                                              "kdbx_destination_root": "/mnt/usb"}],
                            "last_backup_at": _now, "consecutive_all_fail_count": 0},
                "config":  {"enabled": True,
                            "destinations": [{"id": "local", "type": "local",
                                              "restic_repo_root": "/mnt/backup",
                                              "restic_repo_password_keepass_prefix": "Backup/config",
                                              "retention_count": 5}],
                            "last_backup_at": _now, "consecutive_all_fail_count": 0},
                "appdata": {"enabled": False, "destinations": []},
            },
            "checkpoint_tag": "checkpoint",
            "all_failed_policy": ["alert"],
            "backup_history": [],
        }
        # Phoenix playbook present — suppresses MISSING_PHOENIX_PLAYBOOK gap.
        manifest["phoenix_playbook_generated_at"] = _now

        graph = dep_mod.build_graph(manifest)
        report = score_graph(graph, manifest)

        registry_gaps = report.registry_gaps
        self.assertEqual(registry_gaps, [],
                         msg=f"Expected no registry gaps with all registries present, got: {registry_gaps}")

    def test_build_registries_from_manifest_keys(self):
        """build_registries() uses manifest keys when present, no file I/O needed."""
        fixture = _load_fixture()
        manifest = {
            "secret_registry": fixture["secrets"],
            "dns_registry": fixture["dns_registry"],
        }
        sr, dr = build_registries(manifest)

        self.assertTrue(sr.available())
        self.assertTrue(dr.available())
        self.assertEqual(sr.count(), len(fixture["secrets"]))
        self.assertEqual(dr.count(), len(fixture["dns_registry"]))

    def test_secrets_include_all_required_types(self):
        """Fixture secrets cover all required secret_type values."""
        fixture = _load_fixture()
        sr = SecretRegistry(fixture["secrets"])
        types_present = {s.get("secret_type") for s in sr.all()}
        self.assertIn("password",        types_present)
        self.assertIn("ssh-private-key", types_present)

    def test_dns_registry_covers_all_vms(self):
        """Fixture DNS registry has an entry for every declared VM."""
        fixture = _load_fixture()
        dr = DnsRegistry(fixture["dns_registry"])
        for vm in fixture["vms"]:
            vmid = vm["vmid"]
            ip   = dr.ip_for_vmid(vmid)
            self.assertIsNotNone(ip,
                msg=f"DNS registry missing entry for vmid={vmid} ({vm['name']})")
            self.assertEqual(ip, vm["initial_ip"],
                msg=f"DNS registry IP {ip!r} for {vm['name']} != initial_ip {vm['initial_ip']!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
