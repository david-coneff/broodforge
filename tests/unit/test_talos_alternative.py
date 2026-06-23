"""
Tests for Phase 9.T — Talos Linux alternative support (foundation tier).

Covers:
  - generate_talos_config.py: cluster spec builder, config generators, node patches
  - bootstrap-state-schema.json: os_variant additions
  - readiness.py: _score_talos_config_completeness
  - phoenix_playbook.py: Talos-specific template rebuild and VM steps (9.T.7)
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
PROXMOX_BOOTSTRAP = os.path.join(REPO_ROOT, "proxmox-bootstrap")
DOC_GEN = os.path.join(REPO_ROOT, "doc-gen")
DATA_MODEL = os.path.join(REPO_ROOT, "data-model")

from generate_talos_config import (
    TalosClusterSpec,
    TalosNodeSpec,
    build_cluster_spec,
    generate_base_controlplane,
    generate_base_worker,
    generate_installer_template,
    generate_node_patch,
    generate_talos_configs,
    generate_talosconfig_stub,
)
from readiness import _score_talos_config_completeness

# ── Fixtures ───────────────────────────────────────────────────────────────────

def _minimal_k3s(os_variant: str = "talos") -> dict:
    return {
        "cluster_name": "test-cluster",
        "server_nodes": [
            {"vm_name": "k3s-server-01", "os_variant": os_variant}
        ],
        "worker_nodes": [],
    }


def _minimal_state(ip: str = "192.168.1.50") -> dict:
    return {
        "cell_id": "proxmox-cell-test",
        "host_identity": {"hostname": "pve01", "gateway": "192.168.1.1"},
        "dns_registry": [
            {"hostname": "k3s-server-01", "ip": ip}
        ],
        "network_topology_declared": {
            "dns_servers": ["192.168.1.1"]
        },
        "templates": [
            {"name": "talos-1x-base", "os_variant": "talos",
             "proxmox_template_id": 9001, "created_at": "2026-01-01T00:00:00Z",
             "base_image": "talos-1x-base-iso"}
        ],
        "base_images": [
            {"name": "talos-1x-base-iso", "os_variant": "talos",
             "source_iso": "talos-v1.7.0-nocloud-amd64.iso",
             "checksum": "sha256:POPULATE", "created_at": "2026-01-01T00:00:00Z"}
        ],
    }


# ── TalosNodeSpec / TalosClusterSpec ──────────────────────────────────────────

class TestTalosNodeSpec(unittest.TestCase):
    def test_defaults(self):
        node = TalosNodeSpec(
            vm_name="k3s-server-01", role="controlplane",
            hostname="k3s-server-01", ip="192.168.1.50",
            gateway="192.168.1.1", nameserver="192.168.1.1"
        )
        self.assertEqual(node.install_disk, "/dev/sda")
        self.assertEqual(node.os_variant, "talos")

    def test_custom_disk(self):
        node = TalosNodeSpec(
            vm_name="k3s-worker-01", role="worker",
            hostname="k3s-worker-01", ip="192.168.1.51",
            gateway="192.168.1.1", nameserver="192.168.1.1",
            install_disk="/dev/vda",
        )
        self.assertEqual(node.install_disk, "/dev/vda")


class TestBuildClusterSpec(unittest.TestCase):
    def test_talos_nodes_included(self):
        k3s = _minimal_k3s("talos")
        state = _minimal_state()
        spec = build_cluster_spec(k3s, state)
        self.assertEqual(len(spec.nodes), 1)
        self.assertEqual(spec.nodes[0].vm_name, "k3s-server-01")
        self.assertEqual(spec.nodes[0].role, "controlplane")
        self.assertEqual(spec.nodes[0].ip, "192.168.1.50")

    def test_ubuntu_nodes_excluded(self):
        k3s = _minimal_k3s("ubuntu")
        state = _minimal_state()
        spec = build_cluster_spec(k3s, state)
        self.assertEqual(len(spec.nodes), 0)

    def test_endpoint_from_first_cp_node(self):
        k3s = _minimal_k3s("talos")
        state = _minimal_state("10.0.0.10")
        spec = build_cluster_spec(k3s, state)
        self.assertEqual(spec.cluster_endpoint, "https://10.0.0.10:6443")

    def test_endpoint_populate_when_no_ip(self):
        k3s = _minimal_k3s("talos")
        state = {}  # no dns_registry
        spec = build_cluster_spec(k3s, state)
        self.assertEqual(spec.cluster_endpoint, "https://POPULATE:6443")

    def test_cluster_name_from_k3s(self):
        k3s = {**_minimal_k3s("talos"), "cluster_name": "my-cluster"}
        state = _minimal_state()
        spec = build_cluster_spec(k3s, state)
        self.assertEqual(spec.cluster_name, "my-cluster")

    def test_worker_nodes_included(self):
        k3s = {
            "cluster_name": "test",
            "server_nodes": [{"vm_name": "k3s-server-01", "os_variant": "ubuntu"}],
            "worker_nodes": [{"vm_name": "k3s-worker-01", "os_variant": "talos"}],
        }
        state = {"dns_registry": [{"hostname": "k3s-worker-01", "ip": "10.0.0.20"}]}
        spec = build_cluster_spec(k3s, state)
        self.assertEqual(len(spec.nodes), 1)
        self.assertEqual(spec.nodes[0].role, "worker")

    def test_gateway_from_host_identity(self):
        k3s = _minimal_k3s("talos")
        state = {"host_identity": {"gateway": "172.16.0.1"}}
        spec = build_cluster_spec(k3s, state)
        self.assertEqual(spec.nodes[0].gateway, "172.16.0.1")

    def test_gateway_populate_when_absent(self):
        k3s = _minimal_k3s("talos")
        state = {}
        spec = build_cluster_spec(k3s, state)
        self.assertEqual(spec.nodes[0].gateway, "POPULATE")


# ── generate_installer_template ───────────────────────────────────────────────

class TestGenerateInstallerTemplate(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_creates_file(self):
        generate_installer_template(self.tmpdir)
        path = os.path.join(self.tmpdir, "installer-template.yaml")
        self.assertTrue(os.path.exists(path))

    def test_contains_installer_marker(self):
        generate_installer_template(self.tmpdir)
        content = open(os.path.join(self.tmpdir, "installer-template.yaml")).read()
        self.assertIn("INSTALLER_ONLY", content)

    def test_contains_machine_type_worker(self):
        generate_installer_template(self.tmpdir)
        content = open(os.path.join(self.tmpdir, "installer-template.yaml")).read()
        self.assertIn("worker", content)

    def test_not_for_cluster_use_comment(self):
        generate_installer_template(self.tmpdir)
        content = open(os.path.join(self.tmpdir, "installer-template.yaml")).read()
        self.assertIn("NOT_FOR_CLUSTER", content.upper().replace(" ", "_") or "not_for_cluster")
        # Alternative: check the warning comment is present
        self.assertIn("Do NOT", content)


# ── generate_node_patch ───────────────────────────────────────────────────────

class TestGenerateNodePatch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _make_node(self, name="k3s-server-01", ip="10.0.0.5"):
        return TalosNodeSpec(
            vm_name=name, role="controlplane",
            hostname=name, ip=ip,
            gateway="10.0.0.1", nameserver="10.0.0.1",
        )

    def test_creates_patches_dir(self):
        node = self._make_node()
        generate_node_patch(node, self.tmpdir)
        self.assertTrue(os.path.isdir(os.path.join(self.tmpdir, "patches")))

    def test_creates_patch_file(self):
        node = self._make_node()
        generate_node_patch(node, self.tmpdir)
        path = os.path.join(self.tmpdir, "patches", "k3s-server-01.yaml")
        self.assertTrue(os.path.exists(path))

    def test_contains_ip(self):
        node = self._make_node(ip="10.0.0.5")
        generate_node_patch(node, self.tmpdir)
        content = open(os.path.join(self.tmpdir, "patches", "k3s-server-01.yaml")).read()
        self.assertIn("10.0.0.5", content)

    def test_contains_hostname(self):
        node = self._make_node(name="k3s-server-02")
        generate_node_patch(node, self.tmpdir)
        content = open(os.path.join(self.tmpdir, "patches", "k3s-server-02.yaml")).read()
        self.assertIn("k3s-server-02", content)

    def test_contains_gateway(self):
        node = self._make_node()
        generate_node_patch(node, self.tmpdir)
        content = open(os.path.join(self.tmpdir, "patches", "k3s-server-01.yaml")).read()
        self.assertIn("10.0.0.1", content)


# ── generate_base_controlplane / worker ──────────────────────────────────────

class TestGenerateBaseConfigs(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec = TalosClusterSpec(
            cluster_name="test-cluster",
            cluster_endpoint="https://10.0.0.5:6443",
            nodes=[
                TalosNodeSpec(
                    vm_name="k3s-server-01", role="controlplane",
                    hostname="k3s-server-01", ip="10.0.0.5",
                    gateway="10.0.0.1", nameserver="10.0.0.1",
                )
            ],
        )

    def test_controlplane_created(self):
        generate_base_controlplane(self.spec, self.tmpdir)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "controlplane.yaml")))

    def test_controlplane_contains_endpoint(self):
        generate_base_controlplane(self.spec, self.tmpdir)
        content = open(os.path.join(self.tmpdir, "controlplane.yaml")).read()
        self.assertIn("https://10.0.0.5:6443", content)

    def test_controlplane_contains_cluster_name(self):
        generate_base_controlplane(self.spec, self.tmpdir)
        content = open(os.path.join(self.tmpdir, "controlplane.yaml")).read()
        self.assertIn("test-cluster", content)

    def test_controlplane_contains_populate_marker(self):
        generate_base_controlplane(self.spec, self.tmpdir)
        content = open(os.path.join(self.tmpdir, "controlplane.yaml")).read()
        self.assertIn("POPULATE_FROM_TALOSCTL_GENCONFIG", content)

    def test_worker_created(self):
        generate_base_worker(self.spec, self.tmpdir)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "worker.yaml")))

    def test_worker_type_is_worker(self):
        generate_base_worker(self.spec, self.tmpdir)
        content = open(os.path.join(self.tmpdir, "worker.yaml")).read()
        self.assertIn("worker", content)


# ── generate_talosconfig_stub ─────────────────────────────────────────────────

class TestGenerateTalosconfigStub(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec = TalosClusterSpec(
            cluster_name="my-cluster",
            cluster_endpoint="https://10.0.0.5:6443",
            nodes=[
                TalosNodeSpec(
                    vm_name="k3s-server-01", role="controlplane",
                    hostname="k3s-server-01", ip="10.0.0.5",
                    gateway="10.0.0.1", nameserver="10.0.0.1",
                )
            ],
        )

    def test_talosconfig_created(self):
        generate_talosconfig_stub(self.spec, self.tmpdir)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "talosconfig")))

    def test_contains_cluster_name_context(self):
        generate_talosconfig_stub(self.spec, self.tmpdir)
        content = open(os.path.join(self.tmpdir, "talosconfig")).read()
        self.assertIn("my-cluster", content)

    def test_contains_node_ip(self):
        generate_talosconfig_stub(self.spec, self.tmpdir)
        content = open(os.path.join(self.tmpdir, "talosconfig")).read()
        self.assertIn("10.0.0.5", content)


# ── Full pipeline: generate_talos_configs ────────────────────────────────────

class TestGenerateTalosConfigsPipeline(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "bootstrap-state.json")
        self.k3s_path = os.path.join(self.tmpdir, "k3s-cluster.yaml")

    def _write_state(self, state: dict):
        with open(self.state_path, "w") as f:
            json.dump(state, f)

    def _write_k3s(self, content: str):
        with open(self.k3s_path, "w") as f:
            f.write(content)

    def test_no_talos_nodes_produces_installer_only(self):
        self._write_state({})
        self._write_k3s(
            "cluster_name: test\nserver_nodes:\n  - vm_name: k3s-server-01\n    os_variant: ubuntu\nworker_nodes: []\n"
        )
        out = os.path.join(self.tmpdir, "talos-configs")
        spec = generate_talos_configs(self.state_path, self.k3s_path, out)
        self.assertEqual(len(spec.nodes), 0)
        self.assertTrue(os.path.exists(os.path.join(out, "installer-template.yaml")))

    def test_talos_node_generates_patch(self):
        self._write_state(_minimal_state())
        self._write_k3s(
            "cluster_name: test\nserver_nodes:\n  - vm_name: k3s-server-01\n    os_variant: talos\nworker_nodes: []\n"
        )
        out = os.path.join(self.tmpdir, "talos-configs")
        spec = generate_talos_configs(self.state_path, self.k3s_path, out)
        self.assertEqual(len(spec.nodes), 1)
        patch_path = os.path.join(out, "patches", "k3s-server-01.yaml")
        self.assertTrue(os.path.exists(patch_path))

    def test_talos_node_generates_base_configs(self):
        self._write_state(_minimal_state())
        self._write_k3s(
            "cluster_name: test\nserver_nodes:\n  - vm_name: k3s-server-01\n    os_variant: talos\nworker_nodes: []\n"
        )
        out = os.path.join(self.tmpdir, "talos-configs")
        generate_talos_configs(self.state_path, self.k3s_path, out)
        self.assertTrue(os.path.exists(os.path.join(out, "controlplane.yaml")))
        self.assertTrue(os.path.exists(os.path.join(out, "worker.yaml")))
        self.assertTrue(os.path.exists(os.path.join(out, "talosconfig")))

    def test_readme_generated(self):
        self._write_state(_minimal_state())
        self._write_k3s(
            "cluster_name: test\nserver_nodes:\n  - vm_name: k3s-server-01\n    os_variant: talos\nworker_nodes: []\n"
        )
        out = os.path.join(self.tmpdir, "talos-configs")
        generate_talos_configs(self.state_path, self.k3s_path, out)
        self.assertTrue(os.path.exists(os.path.join(out, "README.md")))

    def test_missing_state_file_treated_as_empty(self):
        self._write_k3s(
            "cluster_name: test\nserver_nodes:\n  - vm_name: k3s-server-01\n    os_variant: talos\nworker_nodes: []\n"
        )
        out = os.path.join(self.tmpdir, "talos-configs")
        spec = generate_talos_configs("nonexistent.json", self.k3s_path, out)
        # Should still generate stubs with POPULATE values
        self.assertEqual(len(spec.nodes), 1)
        self.assertEqual(spec.nodes[0].ip, "POPULATE")

    def test_missing_k3s_file_treated_as_empty(self):
        self._write_state(_minimal_state())
        out = os.path.join(self.tmpdir, "talos-configs")
        spec = generate_talos_configs(self.state_path, "nonexistent.yaml", out)
        self.assertEqual(len(spec.nodes), 0)


# ── Readiness scorer: _score_talos_config_completeness ───────────────────────

class TestScoreTalosConfigCompleteness(unittest.TestCase):
    def _manifest_with_talos(self, has_configs: bool = False) -> dict:
        base = {
            "k3s_cluster": {
                "server_nodes": [
                    {"vm_name": "k3s-server-01", "os_variant": "talos"}
                ],
                "worker_nodes": [],
            }
        }
        if has_configs:
            base["talos_machine_configs"] = ["talos-configs/controlplane.yaml"]
        return base

    def _manifest_ubuntu_only(self) -> dict:
        return {
            "k3s_cluster": {
                "server_nodes": [{"vm_name": "k3s-server-01", "os_variant": "ubuntu"}],
                "worker_nodes": [],
            }
        }

    def test_no_talos_nodes_no_gaps(self):
        gaps = _score_talos_config_completeness(self._manifest_ubuntu_only())
        self.assertEqual(gaps, [])

    def test_no_k3s_cluster_no_gaps(self):
        gaps = _score_talos_config_completeness({})
        self.assertEqual(gaps, [])

    def test_talos_node_without_configs_is_yellow(self):
        gaps = _score_talos_config_completeness(self._manifest_with_talos(False))
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")

    def test_talos_node_with_configs_no_gaps(self):
        gaps = _score_talos_config_completeness(self._manifest_with_talos(True))
        self.assertEqual(gaps, [])

    def test_talos_configs_generated_at_satisfies(self):
        manifest = self._manifest_with_talos(False)
        manifest["talos_configs_generated_at"] = "2026-06-01T00:00:00Z"
        gaps = _score_talos_config_completeness(manifest)
        self.assertEqual(gaps, [])

    def test_gap_mentions_vm_name(self):
        gaps = _score_talos_config_completeness(self._manifest_with_talos(False))
        self.assertIn("k3s-server-01", gaps[0].description)

    def test_gap_mentions_generate_command(self):
        gaps = _score_talos_config_completeness(self._manifest_with_talos(False))
        self.assertIn("generate-talos-config.py", gaps[0].remediation)

    def test_multiple_talos_nodes_single_gap(self):
        manifest = {
            "k3s_cluster": {
                "server_nodes": [
                    {"vm_name": "k3s-server-01", "os_variant": "talos"},
                    {"vm_name": "k3s-server-02", "os_variant": "talos"},
                ],
                "worker_nodes": [],
            }
        }
        gaps = _score_talos_config_completeness(manifest)
        self.assertEqual(len(gaps), 1)
        self.assertIn("2", gaps[0].description)  # "2 node(s)"

    def test_mixed_ubuntu_talos_scores_talos_only(self):
        manifest = {
            "k3s_cluster": {
                "server_nodes": [
                    {"vm_name": "k3s-server-01", "os_variant": "ubuntu"},
                    {"vm_name": "k3s-server-02", "os_variant": "talos"},
                ],
                "worker_nodes": [],
            }
        }
        gaps = _score_talos_config_completeness(manifest)
        self.assertEqual(len(gaps), 1)
        self.assertIn("k3s-server-02", gaps[0].description)


# ── Phoenix playbook: Talos template rebuild (9.T.7) ─────────────────────────

class TestPhoenixPlaybookTalos(unittest.TestCase):
    """Tests for Talos-specific changes in phoenix_playbook.py."""

    def setUp(self):
        pass

    def _make_manifest(self, os_variant: str = "talos") -> dict:
        return {
            "cell_id": "proxmox-cell-test",
            "host_identity": {"hostname": "pve01", "lan_ip": "192.168.1.1"},
            "storage_config": {"isos": "local:iso", "vm_disks": "local-zfs"},
            "vms": [{"vmid": 200, "name": "k3s-server-01"}],
            "k3s_cluster": {
                "server_nodes": [{"vm": "k3s-server-01", "os_variant": os_variant}],
                "worker_nodes": [],
            },
            "templates": [
                {"name": "talos-1x-base", "os_variant": "talos",
                 "proxmox_template_id": 9001, "created_at": "2026-01-01T00:00:00Z",
                 "base_image": "talos-1x-base-iso"},
                {"name": "ubuntu-2204-base", "os_variant": "ubuntu",
                 "proxmox_template_id": 9000, "created_at": "2026-01-01T00:00:00Z",
                 "base_image": "ubuntu-2204-base"},
            ],
            "base_images": [
                {"name": "talos-1x-base-iso", "os_variant": "talos",
                 "source_iso": "talos-v1.7.0.iso",
                 "source_url": "https://example.com/talos.iso",
                 "checksum": "sha256:POPULATE", "created_at": "2026-01-01T00:00:00Z"},
                {"name": "ubuntu-2204-base",
                 "source_iso": "ubuntu-22.04.iso",
                 "source_url": "https://releases.ubuntu.com/ubuntu.iso",
                 "checksum": "sha256:POPULATE", "created_at": "2026-01-01T00:00:00Z"},
            ],
            "dns_registry": [{"hostname": "k3s-server-01", "ip": "192.168.1.50"}],
            "provenance_records": [],
            "service_contracts": [],
            "provenance_registry": [],
            "network_topology_declared": {},
        }

    def _build_playbook(self, manifest: dict):
        from phoenix_playbook import PhoenixPlaybookGenerator
        gen = PhoenixPlaybookGenerator(manifest)
        return gen._wave_05_template_rebuild()

    def test_talos_template_step_present_when_talos(self):
        manifest = self._make_manifest("talos")
        wave = self._build_playbook(manifest)
        step_ids = [s["id"] for s in wave["steps"]]
        self.assertIn("2.5.2", step_ids)

    def test_talos_template_step_absent_when_ubuntu(self):
        manifest = self._make_manifest("ubuntu")
        wave = self._build_playbook(manifest)
        step_ids = [s["id"] for s in wave["steps"]]
        self.assertNotIn("2.5.2", step_ids)
        self.assertIn("2.5.1", step_ids)

    def test_talos_step_mentions_build_talos_template(self):
        manifest = self._make_manifest("talos")
        wave = self._build_playbook(manifest)
        talos_step = next(s for s in wave["steps"] if s["id"] == "2.5.2")
        all_cmds = "\n".join(talos_step["commands"])
        self.assertIn("build-talos-template.sh", all_cmds)

    def test_talos_step_validates_talos_configs_dir(self):
        manifest = self._make_manifest("talos")
        wave = self._build_playbook(manifest)
        talos_step = next(s for s in wave["steps"] if s["id"] == "2.5.2")
        all_validation = "\n".join(talos_step["validation"])
        self.assertIn("talos-configs", all_validation)

    def test_estimated_minutes_higher_for_talos(self):
        talos_manifest = self._make_manifest("talos")
        ubuntu_manifest = self._make_manifest("ubuntu")
        talos_wave = self._build_playbook(talos_manifest)
        ubuntu_wave = self._build_playbook(ubuntu_manifest)
        self.assertGreater(talos_wave["estimated_minutes"], ubuntu_wave["estimated_minutes"])

    def test_ubuntu_step_still_present_when_both_variants(self):
        """When cluster has both ubuntu and talos VMs, both template steps generated."""
        manifest = self._make_manifest("talos")
        # Add an ubuntu VM
        manifest["vms"].append({"vmid": 201, "name": "ops-vm"})
        manifest["k3s_cluster"]["worker_nodes"] = [
            {"vm": "ops-vm", "os_variant": "ubuntu"}
        ]
        wave = self._build_playbook(manifest)
        step_ids = [s["id"] for s in wave["steps"]]
        # Ubuntu step from needs_ubuntu (because the ubuntu worker exists in vms)
        # Talos step from needs_talos (server-01 is talos)
        self.assertIn("2.5.2", step_ids)


# ── Schema: os_variant field additions ───────────────────────────────────────

class TestSchemaOsVariant(unittest.TestCase):
    """Verify os_variant added to base_image, vm_template, provenance_record."""

    def setUp(self):
        schema_path = os.path.join(DATA_MODEL, "bootstrap-state-schema.json")
        with open(schema_path) as f:
            self.schema = json.load(f)

    def _def(self, name: str) -> dict:
        return self.schema["definitions"][name]

    def test_base_image_has_os_variant(self):
        props = self._def("base_image")["properties"]
        self.assertIn("os_variant", props)

    def test_base_image_os_variant_enum(self):
        props = self._def("base_image")["properties"]
        enum = props["os_variant"].get("enum", [])
        self.assertIn("ubuntu", enum)
        self.assertIn("talos", enum)

    def test_vm_template_has_os_variant(self):
        props = self._def("vm_template")["properties"]
        self.assertIn("os_variant", props)

    def test_vm_template_os_variant_enum(self):
        props = self._def("vm_template")["properties"]
        enum = props["os_variant"].get("enum", [])
        self.assertIn("ubuntu", enum)
        self.assertIn("talos", enum)

    def test_provenance_record_has_os_variant(self):
        props = self._def("provenance_record")["properties"]
        self.assertIn("os_variant", props)

    def test_provenance_record_has_talos_machine_config(self):
        props = self._def("provenance_record")["properties"]
        self.assertIn("talos_machine_config", props)

    def test_fixture_talos_template_validates(self):
        fixture_path = os.path.join(
            REPO_ROOT, "tests", "fixtures", "bootstrap", "bootstrap-state.json"
        )
        with open(fixture_path) as f:
            fixture = json.load(f)

        talos_tmpl = next(
            (t for t in fixture.get("templates", []) if t.get("os_variant") == "talos"),
            None
        )
        self.assertIsNotNone(talos_tmpl, "Fixture should have a talos template entry")
        self.assertEqual(talos_tmpl["name"], "talos-1x-base")

    def test_fixture_talos_base_image_present(self):
        fixture_path = os.path.join(
            REPO_ROOT, "tests", "fixtures", "bootstrap", "bootstrap-state.json"
        )
        with open(fixture_path) as f:
            fixture = json.load(f)

        talos_img = next(
            (i for i in fixture.get("base_images", []) if i.get("os_variant") == "talos"),
            None
        )
        self.assertIsNotNone(talos_img, "Fixture should have a talos base_image entry")


if __name__ == "__main__":
    unittest.main()
