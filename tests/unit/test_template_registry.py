#!/usr/bin/env python3
"""
Tests for Milestone 6.6 — Template Registry and Base Image Tracking.

Validates:
  - TemplateRegistry class: available, counts, get, all, template_for_vmid
  - Readiness scorer: ORANGE gap when template registry is missing
  - Recovery runbook: Appendix F present, template/base-image details render

Run: py -3 tests/unit/test_template_registry.py
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

from template_registry import TemplateRegistry, build_template_registry
from readiness import _score_template_registry_completeness, score_graph

FIXTURES_DIR   = REPO_ROOT / "tests" / "fixtures" / "bootstrap"
BOOTSTRAP_JSON = FIXTURES_DIR / "bootstrap-state.json"


def _load_bootstrap_fixture() -> dict:
    return json.loads(BOOTSTRAP_JSON.read_text())


def _odt_text(odt_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(odt_bytes)) as zf:
        parts = []
        for name in zf.namelist():
            if name.endswith(".xml"):
                parts.append(zf.read(name).decode("utf-8", errors="replace"))
        return "\n".join(parts)


def _sample_base_image(name="ubuntu-2204-base"):
    return {
        "name": name,
        "source_iso": "ubuntu-22.04.4-live-server-amd64.iso",
        "source_url": "https://releases.ubuntu.com/22.04/ubuntu-22.04.4-live-server-amd64.iso",
        "checksum": "sha256:45f873de9f8cb637345d6e66a583762730bbea30277ef7b32c9c3bd6700a32b2",
        "created_at": "2026-04-01T10:00:00Z",
        "included_packages": ["python3", "qemu-guest-agent", "openssh-server", "cloud-init"],
        "notes": None,
    }


def _sample_template(name="ubuntu-2204-base", base_image="ubuntu-2204-base", tmpl_id=9000):
    return {
        "name": name,
        "base_image": base_image,
        "proxmox_template_id": tmpl_id,
        "created_at": "2026-04-01T11:00:00Z",
        "additional_packages": [],
        "build_notes": "Minimal base template — no additional packages beyond ISO defaults",
    }


# ===========================================================================
# TemplateRegistry — empty cases
# ===========================================================================

class TestTemplateRegistryEmpty(unittest.TestCase):
    def test_empty_lists_not_available(self):
        self.assertFalse(TemplateRegistry([], []).available())

    def test_none_inputs_not_available(self):
        self.assertFalse(TemplateRegistry(None, None).available())

    def test_base_image_count_zero(self):
        self.assertEqual(TemplateRegistry([], []).base_image_count(), 0)

    def test_template_count_zero(self):
        self.assertEqual(TemplateRegistry([], []).template_count(), 0)

    def test_get_base_image_returns_none(self):
        self.assertIsNone(TemplateRegistry([], []).get_base_image("ubuntu-2204-base"))

    def test_get_template_returns_none(self):
        self.assertIsNone(TemplateRegistry([], []).get_template("ubuntu-2204-base"))

    def test_all_base_images_empty(self):
        self.assertEqual(TemplateRegistry([], []).all_base_images(), [])

    def test_all_templates_empty(self):
        self.assertEqual(TemplateRegistry([], []).all_templates(), [])

    def test_template_for_vmid_returns_none(self):
        self.assertIsNone(TemplateRegistry([], []).template_for_vmid(101, []))

    def test_only_base_images_is_available(self):
        tr = TemplateRegistry([_sample_base_image()], [])
        self.assertTrue(tr.available())

    def test_only_templates_is_available(self):
        tr = TemplateRegistry([], [_sample_template()])
        self.assertTrue(tr.available())


# ===========================================================================
# TemplateRegistry — data cases
# ===========================================================================

class TestTemplateRegistryData(unittest.TestCase):
    def setUp(self):
        self.bi = _sample_base_image("ubuntu-2204-base")
        self.tmpl = _sample_template("ubuntu-2204-base", "ubuntu-2204-base", 9000)
        self.tr = TemplateRegistry([self.bi], [self.tmpl])

    def test_available(self):
        self.assertTrue(self.tr.available())

    def test_base_image_count(self):
        self.assertEqual(self.tr.base_image_count(), 1)

    def test_template_count(self):
        self.assertEqual(self.tr.template_count(), 1)

    def test_get_base_image_found(self):
        bi = self.tr.get_base_image("ubuntu-2204-base")
        self.assertIsNotNone(bi)
        self.assertEqual(bi["source_iso"], "ubuntu-22.04.4-live-server-amd64.iso")

    def test_get_base_image_not_found(self):
        self.assertIsNone(self.tr.get_base_image("debian-12"))

    def test_get_template_found(self):
        t = self.tr.get_template("ubuntu-2204-base")
        self.assertIsNotNone(t)
        self.assertEqual(t["proxmox_template_id"], 9000)

    def test_get_template_not_found(self):
        self.assertIsNone(self.tr.get_template("debian-12"))

    def test_all_base_images_returns_copy(self):
        all_bi = self.tr.all_base_images()
        self.assertEqual(len(all_bi), 1)
        all_bi.clear()
        self.assertEqual(self.tr.base_image_count(), 1)

    def test_all_templates_returns_copy(self):
        all_t = self.tr.all_templates()
        self.assertEqual(len(all_t), 1)
        all_t.clear()
        self.assertEqual(self.tr.template_count(), 1)

    def test_template_for_vmid_found(self):
        vm_list = [{"vmid": 101, "name": "forgejo", "template_name": "ubuntu-2204-base"}]
        t = self.tr.template_for_vmid(101, vm_list)
        self.assertIsNotNone(t)
        self.assertEqual(t["proxmox_template_id"], 9000)

    def test_template_for_vmid_not_in_list(self):
        vm_list = [{"vmid": 200, "name": "other", "template_name": "ubuntu-2204-base"}]
        t = self.tr.template_for_vmid(101, vm_list)
        self.assertIsNone(t)

    def test_template_for_vmid_no_template_name(self):
        vm_list = [{"vmid": 101, "name": "forgejo"}]
        t = self.tr.template_for_vmid(101, vm_list)
        self.assertIsNone(t)

    def test_template_for_vmid_template_name_not_in_registry(self):
        vm_list = [{"vmid": 101, "name": "forgejo", "template_name": "debian-12"}]
        t = self.tr.template_for_vmid(101, vm_list)
        self.assertIsNone(t)

    def test_template_for_vmid_string_vmid(self):
        vm_list = [{"vmid": 101, "name": "forgejo", "template_name": "ubuntu-2204-base"}]
        t = self.tr.template_for_vmid("101", vm_list)
        self.assertIsNotNone(t)

    def test_template_for_vmid_invalid_vmid(self):
        t = self.tr.template_for_vmid("bad", [{"vmid": 101, "template_name": "ubuntu-2204-base"}])
        self.assertIsNone(t)

    def test_template_for_vmid_empty_vm_list(self):
        self.assertIsNone(self.tr.template_for_vmid(101, []))

    def test_multiple_templates(self):
        bi2 = _sample_base_image("debian-12")
        t2  = _sample_template("debian-12", "debian-12", 9001)
        tr = TemplateRegistry([self.bi, bi2], [self.tmpl, t2])
        self.assertEqual(tr.template_count(), 2)
        self.assertEqual(tr.base_image_count(), 2)
        self.assertEqual(tr.get_template("debian-12")["proxmox_template_id"], 9001)
        self.assertEqual(tr.get_base_image("debian-12")["source_iso"],
                         "ubuntu-22.04.4-live-server-amd64.iso")  # reused fixture name


# ===========================================================================
# build_template_registry
# ===========================================================================

class TestBuildTemplateRegistry(unittest.TestCase):
    def test_builds_from_manifest_keys(self):
        manifest = {
            "base_images": [_sample_base_image()],
            "templates":   [_sample_template()],
        }
        tr = build_template_registry(manifest)
        self.assertTrue(tr.available())
        self.assertEqual(tr.template_count(), 1)
        self.assertEqual(tr.base_image_count(), 1)

    def test_empty_manifest_returns_empty_registry(self):
        tr = build_template_registry({})
        self.assertFalse(tr.available())

    def test_none_values_return_empty_registry(self):
        tr = build_template_registry({"base_images": None, "templates": None})
        self.assertFalse(tr.available())

    def test_empty_lists_return_empty_registry(self):
        tr = build_template_registry({"base_images": [], "templates": []})
        self.assertFalse(tr.available())

    def test_only_base_images_available(self):
        tr = build_template_registry({"base_images": [_sample_base_image()], "templates": []})
        self.assertTrue(tr.available())
        self.assertEqual(tr.base_image_count(), 1)
        self.assertEqual(tr.template_count(), 0)


# ===========================================================================
# Fixture: bootstrap-state.json
# ===========================================================================

class TestLoadFromFixture(unittest.TestCase):
    def setUp(self):
        self.fixture = _load_bootstrap_fixture()

    def test_fixture_has_base_images(self):
        self.assertIn("base_images", self.fixture)
        self.assertIsInstance(self.fixture["base_images"], list)

    def test_fixture_has_templates(self):
        self.assertIn("templates", self.fixture)
        self.assertIsInstance(self.fixture["templates"], list)

    def test_fixture_base_image_count(self):
        self.assertGreater(len(self.fixture["base_images"]), 0)

    def test_fixture_template_count(self):
        self.assertGreater(len(self.fixture["templates"]), 0)

    def test_fixture_base_image_has_required_fields(self):
        bi = self.fixture["base_images"][0]
        for field in ("name", "source_iso", "checksum", "created_at", "included_packages"):
            self.assertIn(field, bi, msg=f"base_image missing field: {field}")

    def test_fixture_template_has_required_fields(self):
        t = self.fixture["templates"][0]
        for field in ("name", "base_image", "proxmox_template_id", "created_at"):
            self.assertIn(field, t, msg=f"template missing field: {field}")

    def test_fixture_ubuntu_base_image_retrievable(self):
        tr = build_template_registry({
            "base_images": self.fixture["base_images"],
            "templates":   self.fixture["templates"],
        })
        bi = tr.get_base_image("ubuntu-2204-base")
        self.assertIsNotNone(bi)
        self.assertIn("qemu-guest-agent", bi["included_packages"])

    def test_fixture_ubuntu_template_retrievable(self):
        tr = build_template_registry({
            "base_images": self.fixture["base_images"],
            "templates":   self.fixture["templates"],
        })
        t = tr.get_template("ubuntu-2204-base")
        self.assertIsNotNone(t)
        self.assertEqual(t["proxmox_template_id"], 9000)


# ===========================================================================
# Readiness scorer — template registry completeness
# ===========================================================================

class TestTemplateCompletenessScoring(unittest.TestCase):
    def test_no_templates_produces_orange_gap(self):
        gaps = _score_template_registry_completeness({})
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "ORANGE")
        self.assertEqual(gaps[0].gap_type, "MISSING_TEMPLATE_REGISTRY")

    def test_empty_templates_list_produces_orange_gap(self):
        gaps = _score_template_registry_completeness({"templates": []})
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "ORANGE")

    def test_none_templates_produces_orange_gap(self):
        gaps = _score_template_registry_completeness({"templates": None})
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "ORANGE")

    def test_templates_present_no_gap(self):
        gaps = _score_template_registry_completeness({"templates": [_sample_template()]})
        self.assertEqual(gaps, [])

    def test_gap_component_id(self):
        gaps = _score_template_registry_completeness({})
        self.assertEqual(gaps[0].component_id, "infrastructure:registries")

    def test_score_graph_includes_template_gap(self):
        """score_graph must include MISSING_TEMPLATE_REGISTRY when templates absent."""
        fixture_t2 = json.loads(
            (REPO_ROOT / "tests/fixtures/tier2/manifest.json").read_text()
        )
        import dependencies as dep_mod
        manifest = deepcopy(fixture_t2)
        manifest.pop("templates", None)
        manifest.pop("base_images", None)

        graph = dep_mod.build_graph(manifest)
        report = score_graph(graph, manifest)

        tmpl_gaps = [g for g in report.registry_gaps
                     if g.gap_type == "MISSING_TEMPLATE_REGISTRY"]
        self.assertEqual(len(tmpl_gaps), 1)
        self.assertEqual(tmpl_gaps[0].severity, "ORANGE")

    def test_score_graph_no_template_gap_when_present(self):
        """No MISSING_TEMPLATE_REGISTRY gap when templates populated."""
        fixture_t2 = json.loads(
            (REPO_ROOT / "tests/fixtures/tier2/manifest.json").read_text()
        )
        import dependencies as dep_mod
        manifest = deepcopy(fixture_t2)
        manifest["templates"] = [_sample_template()]

        graph = dep_mod.build_graph(manifest)
        report = score_graph(graph, manifest)

        tmpl_gaps = [g for g in report.registry_gaps
                     if g.gap_type == "MISSING_TEMPLATE_REGISTRY"]
        self.assertEqual(tmpl_gaps, [])

    def test_overall_score_worsened_by_template_gap(self):
        """An otherwise GREEN graph worsens to ORANGE when template registry missing."""
        from dependencies import DependencyGraph, Node, RestoreWave
        from readiness import BackupInventory
        # Minimal graph with no backup data (will be YELLOW already); confirm ORANGE added
        node = Node(id="host:pve01", type="host", label="PVE01", metadata={})
        graph = DependencyGraph(nodes=[node], edges=[],
                                restore_waves=[RestoreWave(1, ["host:pve01"], "Host")])
        manifest = {
            "host": {"hostname": "pve01"},
            "secret_registry": [{"id": "s1"}],
            "dns_registry": [{"hostname": "h1", "ip": "1.2.3.4"}],
            "provenance_registry": [],
            # no templates
        }
        report = score_graph(graph, manifest)
        scores = {g.gap_type: g.severity for g in report.registry_gaps}
        self.assertEqual(scores.get("MISSING_TEMPLATE_REGISTRY"), "ORANGE")


# ===========================================================================
# Recovery runbook — Appendix F rendering
# ===========================================================================

class TestRunbookTemplateAppendix(unittest.TestCase):
    def _base_manifest(self, include_templates=True):
        fixture = _load_bootstrap_fixture()
        manifest = {
            "host": {"hostname": "pve01", "proxmox_version": "8.1.3"},
            "network": {"default_gateway": "192.168.1.1", "dns_servers": ["192.168.1.1"]},
            "secret_registry": fixture["secrets"],
            "dns_registry":    fixture["dns_registry"],
        }
        if include_templates:
            manifest["base_images"] = fixture["base_images"]
            manifest["templates"]   = fixture["templates"]
        return manifest

    def _single_vm_graph(self):
        from dependencies import DependencyGraph, Node, RestoreWave
        vm = Node(id="vm:forgejo", type="vm", label="Forgejo",
                  metadata={"vmid": 101, "name": "forgejo"})
        return DependencyGraph(
            nodes=[vm], edges=[],
            restore_waves=[RestoreWave(1, ["vm:forgejo"], "VMs")]
        )

    def _render(self, manifest):
        from recovery_runbook import build_recovery_runbook
        from timestamps import now_utc_iso
        import dependencies as dep_mod
        graph = self._single_vm_graph()
        readiness = score_graph(graph, manifest)
        meta = {"generated_at": now_utc_iso(), "tier": 1, "template_version": "recovery-v1.0"}
        return _odt_text(build_recovery_runbook(manifest, graph, readiness, meta))

    def test_appendix_f_present(self):
        content = self._render(self._base_manifest(include_templates=True))
        self.assertIn("Appendix F", content)
        self.assertIn("Template Registry", content)

    def test_template_name_appears(self):
        content = self._render(self._base_manifest(include_templates=True))
        self.assertIn("ubuntu-2204-base", content)

    def test_proxmox_template_id_appears(self):
        content = self._render(self._base_manifest(include_templates=True))
        self.assertIn("9000", content)

    def test_base_image_iso_appears(self):
        content = self._render(self._base_manifest(include_templates=True))
        self.assertIn("ubuntu-22.04.4-live-server-amd64.iso", content)

    def test_checksum_appears(self):
        content = self._render(self._base_manifest(include_templates=True))
        self.assertIn("sha256:45f873de", content)

    def test_appendix_f_fallback_when_no_templates(self):
        content = self._render(self._base_manifest(include_templates=False))
        self.assertIn("Appendix F", content)
        self.assertIn("bootstrap-state.json", content)

    def test_appendix_f_appears_after_appendix_e(self):
        content = self._render(self._base_manifest(include_templates=True))
        pos_e = content.find("Appendix E")
        pos_f = content.find("Appendix F")
        self.assertGreater(pos_e, 0, "Appendix E must be present")
        self.assertGreater(pos_f, pos_e, "Appendix F must appear after Appendix E")


if __name__ == "__main__":
    unittest.main(verbosity=2)
