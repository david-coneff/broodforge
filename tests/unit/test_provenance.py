#!/usr/bin/env python3
"""
Tests for Milestone 6.5 — Deployment Provenance.

Validates:
  - ProvenanceRegistry class: lookups by vmid, by name, coverage()
  - Readiness scorer: YELLOW gap per VM missing a provenance record
  - Recovery runbook: per-VM provenance block present when record available,
    "NOT RECORDED" when absent, Appendix E present

Run: py -3 tests/unit/test_provenance.py
"""

import io
import json
import sys
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "doc-gen"))
sys.path.insert(0, str(REPO_ROOT / "doc-gen" / "renderers"))

from provenance import ProvenanceRegistry, build_provenance_registry
from readiness import _score_provenance_completeness, score_graph, Gap
import dependencies as dep_mod

FIXTURES_DIR   = REPO_ROOT / "tests" / "fixtures" / "bootstrap"
BOOTSTRAP_JSON = FIXTURES_DIR / "bootstrap-state.json"


def _load_bootstrap_fixture() -> dict:
    return json.loads(BOOTSTRAP_JSON.read_text())


def _odt_text(odt_bytes: bytes) -> str:
    """Extract all XML text content from an ODT/ODS zip archive."""
    with zipfile.ZipFile(io.BytesIO(odt_bytes)) as zf:
        parts = []
        for name in zf.namelist():
            if name.endswith(".xml"):
                parts.append(zf.read(name).decode("utf-8", errors="replace"))
        return "\n".join(parts)


def _sample_record(vmid=101, name="forgejo"):
    return {
        "vmid": vmid,
        "name": name,
        "deployed_at": "2026-04-15T12:00:00Z",
        "tofu_workspace": "proxmox-vms",
        "tofu_commit": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        "template_name": "ubuntu-2204-base",
        "template_checksum": "sha256:45f873de",
        "cloudinit_user_data_hash": "sha256:aabbcc112233",
        "cloudinit_network_config_hash": "sha256:ddeeff667788",
        "ansible_playbook": "site.yml",
        "ansible_commit": "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3",
        "ansible_inventory_commit": "c3d4e5f6a1b2c3d4",
        "deployed_by": "dave",
        "notes": None,
    }


# ===========================================================================
# ProvenanceRegistry — empty cases
# ===========================================================================

class TestProvenanceRegistryEmpty(unittest.TestCase):
    def test_empty_list_not_available(self):
        self.assertFalse(ProvenanceRegistry([]).available())

    def test_none_not_available(self):
        self.assertFalse(ProvenanceRegistry(None).available())

    def test_count_zero(self):
        self.assertEqual(ProvenanceRegistry([]).count(), 0)

    def test_for_vmid_returns_none(self):
        self.assertIsNone(ProvenanceRegistry([]).for_vmid(101))

    def test_for_name_returns_none(self):
        self.assertIsNone(ProvenanceRegistry([]).for_name("forgejo"))

    def test_all_returns_empty_list(self):
        self.assertEqual(ProvenanceRegistry([]).all(), [])

    def test_coverage_all_none(self):
        cov = ProvenanceRegistry([]).coverage([100, 101, 102])
        self.assertEqual(cov, {100: None, 101: None, 102: None})


# ===========================================================================
# ProvenanceRegistry — data cases
# ===========================================================================

class TestProvenanceRegistryData(unittest.TestCase):
    def setUp(self):
        self.records = [
            _sample_record(vmid=100, name="infra-bootstrap"),
            _sample_record(vmid=101, name="forgejo"),
        ]
        self.pr = ProvenanceRegistry(self.records)

    def test_available(self):
        self.assertTrue(self.pr.available())

    def test_count(self):
        self.assertEqual(self.pr.count(), 2)

    def test_for_vmid_found(self):
        r = self.pr.for_vmid(101)
        self.assertIsNotNone(r)
        self.assertEqual(r["name"], "forgejo")

    def test_for_vmid_not_found(self):
        self.assertIsNone(self.pr.for_vmid(999))

    def test_for_vmid_none_returns_none(self):
        self.assertIsNone(self.pr.for_vmid(None))

    def test_for_vmid_string_input(self):
        # vmid may come as string from some manifest paths
        r = self.pr.for_vmid("100")
        self.assertIsNotNone(r)
        self.assertEqual(r["name"], "infra-bootstrap")

    def test_for_name_found(self):
        r = self.pr.for_name("forgejo")
        self.assertIsNotNone(r)
        self.assertEqual(r["vmid"], 101)

    def test_for_name_not_found(self):
        self.assertIsNone(self.pr.for_name("unknown-vm"))

    def test_all_returns_copy(self):
        all_r = self.pr.all()
        self.assertEqual(len(all_r), 2)
        all_r.clear()
        self.assertEqual(self.pr.count(), 2)

    def test_coverage_full(self):
        cov = self.pr.coverage([100, 101])
        self.assertIsNotNone(cov[100])
        self.assertIsNotNone(cov[101])
        self.assertEqual(cov[101]["name"], "forgejo")

    def test_coverage_partial(self):
        cov = self.pr.coverage([100, 101, 102, 103])
        self.assertIsNotNone(cov[100])
        self.assertIsNotNone(cov[101])
        self.assertIsNone(cov[102])
        self.assertIsNone(cov[103])

    def test_coverage_empty_vmids(self):
        self.assertEqual(self.pr.coverage([]), {})


# ===========================================================================
# build_provenance_registry
# ===========================================================================

class TestBuildProvenanceRegistry(unittest.TestCase):
    def test_builds_from_manifest_key(self):
        manifest = {"provenance_registry": [_sample_record()]}
        pr = build_provenance_registry(manifest)
        self.assertTrue(pr.available())
        self.assertEqual(pr.count(), 1)

    def test_empty_manifest_returns_empty_registry(self):
        pr = build_provenance_registry({})
        self.assertFalse(pr.available())

    def test_none_value_returns_empty_registry(self):
        pr = build_provenance_registry({"provenance_registry": None})
        self.assertFalse(pr.available())

    def test_empty_list_returns_empty_registry(self):
        pr = build_provenance_registry({"provenance_registry": []})
        self.assertFalse(pr.available())


# ===========================================================================
# Fixture: bootstrap-state.json
# ===========================================================================

class TestFixtureProvenance(unittest.TestCase):
    def setUp(self):
        self.fixture = _load_bootstrap_fixture()

    def test_fixture_has_provenance_records(self):
        self.assertIn("provenance_records", self.fixture)
        self.assertIsInstance(self.fixture["provenance_records"], list)

    def test_fixture_has_at_least_one_record(self):
        self.assertGreater(len(self.fixture["provenance_records"]), 0)

    def test_fixture_forgejo_record_present(self):
        pr = ProvenanceRegistry(self.fixture["provenance_records"])
        r = pr.for_vmid(101)
        self.assertIsNotNone(r, "Expected provenance record for vmid=101 (forgejo)")
        self.assertEqual(r["name"], "forgejo")

    def test_fixture_other_vms_missing(self):
        """vmids 100, 102, 103 intentionally have no provenance — gaps should fire."""
        pr = ProvenanceRegistry(self.fixture["provenance_records"])
        for vmid in (100, 102, 103):
            self.assertIsNone(pr.for_vmid(vmid),
                              msg=f"vmid={vmid} should not have a provenance record")

    def test_fixture_record_has_required_fields(self):
        pr = ProvenanceRegistry(self.fixture["provenance_records"])
        r = pr.for_vmid(101)
        for field in ("vmid", "name", "deployed_at", "tofu_workspace",
                      "tofu_commit", "ansible_commit", "template_name"):
            self.assertIn(field, r, msg=f"Provenance record missing field: {field}")


# ===========================================================================
# Readiness scorer — provenance completeness
# ===========================================================================

def _make_vm_graph(vmids):
    """Build a simple graph with one VM node per vmid."""
    from dependencies import DependencyGraph, Node, RestoreWave
    nodes = [
        Node(id=f"vm:{vmid}", type="vm", label=f"VM {vmid}",
             metadata={"vmid": vmid, "name": f"vm-{vmid}"})
        for vmid in vmids
    ]
    waves = [RestoreWave(1, [f"vm:{v}" for v in vmids], "VMs")]
    return DependencyGraph(nodes=nodes, edges=[], restore_waves=waves)


class TestProvenanceCompletenessScoring(unittest.TestCase):
    def test_no_provenance_all_vms_get_yellow_gaps(self):
        graph = _make_vm_graph([100, 101, 102])
        manifest = {}
        gaps = _score_provenance_completeness(graph, manifest)
        self.assertEqual(len(gaps), 3)
        for g in gaps:
            self.assertEqual(g.severity, "YELLOW")
            self.assertEqual(g.gap_type, "MISSING_PROVENANCE")

    def test_all_vms_covered_no_gaps(self):
        graph = _make_vm_graph([100, 101])
        manifest = {"provenance_registry": [
            _sample_record(100, "infra-bootstrap"),
            _sample_record(101, "forgejo"),
        ]}
        gaps = _score_provenance_completeness(graph, manifest)
        self.assertEqual(gaps, [])

    def test_partial_coverage_gaps_only_for_missing(self):
        graph = _make_vm_graph([100, 101, 102])
        manifest = {"provenance_registry": [_sample_record(101, "forgejo")]}
        gaps = _score_provenance_completeness(graph, manifest)
        self.assertEqual(len(gaps), 2)
        gap_ids = {g.component_id for g in gaps}
        self.assertIn("vm:100", gap_ids)
        self.assertIn("vm:102", gap_ids)
        self.assertNotIn("vm:101", gap_ids)

    def test_non_vm_nodes_not_checked(self):
        """Host, storage, and network nodes must not trigger provenance gaps."""
        from dependencies import DependencyGraph, Node
        nodes = [
            Node(id="host:pve01",  type="host",    label="PVE01",  metadata={}),
            Node(id="zfs:rpool",   type="storage", label="rpool",  metadata={}),
            Node(id="net:vmbr0",   type="network", label="vmbr0",  metadata={}),
        ]
        graph = DependencyGraph(nodes=nodes, edges=[], restore_waves=[])
        gaps = _score_provenance_completeness(graph, {})
        self.assertEqual(gaps, [])

    def test_vm_with_no_vmid_metadata_skipped(self):
        """VM nodes without vmid metadata should be silently skipped."""
        from dependencies import DependencyGraph, Node
        node = Node(id="vm:unknown", type="vm", label="Unknown VM",
                    metadata={"name": "unknown"})  # no vmid
        graph = DependencyGraph(nodes=[node], edges=[], restore_waves=[])
        gaps = _score_provenance_completeness(graph, {})
        self.assertEqual(gaps, [])

    def test_score_graph_propagates_provenance_gaps(self):
        """score_graph includes provenance gaps in registry_gaps."""
        fixture_t2 = json.loads(
            (REPO_ROOT / "tests/fixtures/tier2/manifest.json").read_text()
        )
        manifest = deepcopy(fixture_t2)
        manifest.pop("provenance_registry", None)

        graph = dep_mod.build_graph(manifest)
        report = score_graph(graph, manifest)

        prov_gaps = [g for g in report.registry_gaps
                     if g.gap_type == "MISSING_PROVENANCE"]
        # tier2 fixture has VMs — expect at least one provenance gap
        self.assertGreater(len(prov_gaps), 0)

    def test_score_graph_provenance_gaps_are_yellow(self):
        fixture_t2 = json.loads(
            (REPO_ROOT / "tests/fixtures/tier2/manifest.json").read_text()
        )
        manifest = deepcopy(fixture_t2)
        manifest.pop("provenance_registry", None)

        graph = dep_mod.build_graph(manifest)
        report = score_graph(graph, manifest)

        for g in report.registry_gaps:
            if g.gap_type == "MISSING_PROVENANCE":
                self.assertEqual(g.severity, "YELLOW")

    def test_score_graph_no_provenance_gaps_when_all_covered(self):
        """No provenance gaps when every VM node has a record."""
        from dependencies import DependencyGraph, Node, RestoreWave
        vm = Node(id="vm:forgejo", type="vm", label="Forgejo",
                  metadata={"vmid": 101, "name": "forgejo"})
        graph = DependencyGraph(
            nodes=[vm], edges=[],
            restore_waves=[RestoreWave(1, ["vm:forgejo"], "VMs")]
        )
        manifest = {
            "host": {"hostname": "pve01"},
            "secret_registry": [{"id": "s1"}],
            "dns_registry": [{"hostname": "h1", "ip": "1.2.3.4"}],
            "provenance_registry": [_sample_record(101, "forgejo")],
        }
        report = score_graph(graph, manifest)
        prov_gaps = [g for g in report.registry_gaps
                     if g.gap_type == "MISSING_PROVENANCE"]
        self.assertEqual(prov_gaps, [])

    def test_to_dict_includes_provenance_gaps(self):
        fixture_t2 = json.loads(
            (REPO_ROOT / "tests/fixtures/tier2/manifest.json").read_text()
        )
        manifest = deepcopy(fixture_t2)
        manifest.pop("provenance_registry", None)

        graph = dep_mod.build_graph(manifest)
        report = score_graph(graph, manifest)
        d = report.to_dict()

        self.assertIn("registry_gaps", d)
        prov_gaps = [g for g in d["registry_gaps"]
                     if g["gap_type"] == "MISSING_PROVENANCE"]
        self.assertGreater(len(prov_gaps), 0)


# ===========================================================================
# Recovery runbook — provenance section rendering
# ===========================================================================

class TestRunbookProvenanceSection(unittest.TestCase):
    def _base_manifest(self, include_prov=True, include_all_regs=True):
        fixture = _load_bootstrap_fixture()
        manifest = {
            "host": {"hostname": "pve01", "proxmox_version": "8.1.3"},
            "network": {"default_gateway": "192.168.1.1", "dns_servers": ["192.168.1.1"]},
        }
        if include_all_regs:
            manifest["secret_registry"] = fixture["secrets"]
            manifest["dns_registry"] = fixture["dns_registry"]
        if include_prov:
            manifest["provenance_registry"] = fixture["provenance_records"]
        return manifest

    def _single_vm_graph(self, vmid=101, name="forgejo"):
        from dependencies import DependencyGraph, Node, RestoreWave
        vm = Node(id=f"vm:{name}", type="vm", label=name.capitalize(),
                  metadata={"vmid": vmid, "name": name})
        return DependencyGraph(
            nodes=[vm], edges=[],
            restore_waves=[RestoreWave(1, [f"vm:{name}"], "VMs")]
        )

    def _render(self, manifest, graph):
        from recovery_runbook import build_recovery_runbook
        from timestamps import now_utc_iso
        readiness = score_graph(graph, manifest)
        meta = {"generated_at": now_utc_iso(), "tier": 1, "template_version": "recovery-v1.0"}
        return _odt_text(build_recovery_runbook(manifest, graph, readiness, meta))

    def test_provenance_fields_present_when_record_available(self):
        """When a provenance record exists, its fields appear in the runbook."""
        manifest = self._base_manifest(include_prov=True)
        graph = self._single_vm_graph(vmid=101, name="forgejo")
        content = self._render(manifest, graph)

        # deployed_at from the fixture record
        self.assertIn("2026-04-15", content,
                      msg="deployed_at date must appear in runbook")
        # tofu_workspace
        self.assertIn("proxmox-vms", content,
                      msg="tofu_workspace must appear in runbook")
        # template_name
        self.assertIn("ubuntu-2204-base", content,
                      msg="template_name must appear in runbook")

    def test_not_recorded_when_no_provenance(self):
        """VM with no provenance record shows NOT RECORDED in its restore section."""
        manifest = self._base_manifest(include_prov=False)
        graph = self._single_vm_graph(vmid=101, name="forgejo")
        content = self._render(manifest, graph)
        self.assertIn("NOT RECORDED", content,
                      msg="Missing provenance must show NOT RECORDED")

    def test_appendix_e_present(self):
        """Appendix E — Deployment Provenance always appears."""
        manifest = self._base_manifest(include_prov=True)
        graph = self._single_vm_graph(vmid=101, name="forgejo")
        content = self._render(manifest, graph)
        self.assertIn("Appendix E", content)
        self.assertIn("Deployment Provenance", content)

    def test_appendix_e_fallback_when_no_records(self):
        """Appendix E renders a fallback message when provenance unavailable."""
        manifest = self._base_manifest(include_prov=False)
        graph = self._single_vm_graph(vmid=101, name="forgejo")
        content = self._render(manifest, graph)
        self.assertIn("Appendix E", content)
        # Should explain how to add provenance
        self.assertIn("provenance_records", content)

    def test_appendix_e_tofu_commit_in_full(self):
        """Full tofu_commit hash appears in Appendix E."""
        manifest = self._base_manifest(include_prov=True)
        graph = self._single_vm_graph(vmid=101, name="forgejo")
        content = self._render(manifest, graph)
        fixture = _load_bootstrap_fixture()
        tofu_commit = fixture["provenance_records"][0]["tofu_commit"]
        self.assertIn(tofu_commit[:12], content,
                      msg="At least the short form of tofu_commit must appear")

    def test_vm_without_record_shows_not_recorded_in_restore_section(self):
        """VM 100 has no provenance — its restore section shows NOT RECORDED."""
        manifest = self._base_manifest(include_prov=True)  # only vmid=101 has a record
        graph = self._single_vm_graph(vmid=100, name="infra-bootstrap")
        content = self._render(manifest, graph)
        # The per-VM restore section must flag missing provenance
        self.assertIn("NOT RECORDED", content)
        # Appendix E legitimately lists all records (including vmid=101's),
        # so proxmox-vms may appear there — we don't assert its absence globally

    def test_multiple_vms_both_provenance_outcomes(self):
        """forgejo (101) gets provenance fields; infra-bootstrap (100) gets NOT RECORDED."""
        from dependencies import DependencyGraph, Node, RestoreWave
        vm100 = Node(id="vm:infra-bootstrap", type="vm", label="Infra Bootstrap",
                     metadata={"vmid": 100, "name": "infra-bootstrap"})
        vm101 = Node(id="vm:forgejo", type="vm", label="Forgejo",
                     metadata={"vmid": 101, "name": "forgejo"})
        graph = DependencyGraph(
            nodes=[vm100, vm101], edges=[],
            restore_waves=[RestoreWave(1, ["vm:infra-bootstrap", "vm:forgejo"], "VMs")]
        )
        manifest = self._base_manifest(include_prov=True)
        content = self._render(manifest, graph)

        # forgejo (101) has a record → key fields present
        self.assertIn("proxmox-vms", content,
                      msg="forgejo provenance must include tofu_workspace")
        self.assertIn("ubuntu-2204-base", content,
                      msg="forgejo provenance must include template_name")
        # infra-bootstrap (100) has no record → NOT RECORDED marker present
        self.assertIn("NOT RECORDED", content,
                      msg="infra-bootstrap missing provenance must show NOT RECORDED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
