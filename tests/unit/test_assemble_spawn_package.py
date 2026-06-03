#!/usr/bin/env python3
"""Tests for Phase 12.E.7 + 12.E.7a — Spawn package assembler and KeePass gate."""

import sys, unittest, tarfile, tempfile, json
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "proxmox-bootstrap"))

from assemble_spawn_package import (
    assemble_spawn_package,
    package_contents,
    _package_name,
    KEEPASS_GATE_SH,
    CHECKPOINT_SH,
)

PLAN = {
    "cell_id": "cell-alpha",
    "hostname": "pve02",
    "package_id": "spawn-cell-alpha-pve02-ts",
    "generated_at": "2026-06-01T12:00:00Z",
    "disposition": {"execution_mode": "autonomous"},
    "k3s": {"role": "worker"},
}

MANIFEST = {
    "cell_id": "cell-alpha",
    "reserved_vmids": [100, 101],
    "reserved_ips": ["192.168.1.10"],
    "proxmox_cluster_address": "192.168.1.10",
}

_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_artifacts_dir(tmp: Path, include_ha: bool = False) -> Path:
    """Create a minimal artifacts directory with shell scripts and sub-dirs."""
    d = tmp / "artifacts"
    d.mkdir()
    (d / "spawn.sh").write_text("#!/usr/bin/env bash\necho spawn\n")
    (d / "phase-00-preflight.sh").write_text("#!/usr/bin/env bash\necho p00\n")
    (d / "phase-00-host.sh").write_text("#!/usr/bin/env bash\necho p00h\n")
    (d / "phase-01-proxmox.sh").write_text("#!/usr/bin/env bash\necho p01\n")
    (d / "phase-02-vms.sh").write_text("#!/usr/bin/env bash\necho p02\n")
    (d / "phase-03-cloudinit.sh").write_text("#!/usr/bin/env bash\necho p03\n")
    (d / "phase-04-k3s.sh").write_text("#!/usr/bin/env bash\necho p04\n")
    if include_ha:
        (d / "phase-05-ha.sh").write_text("#!/usr/bin/env bash\necho p05\n")
    (d / "phase-06-verify.sh").write_text("#!/usr/bin/env bash\necho p06\n")

    ot = d / "opentofu"
    ot.mkdir()
    (ot / "spawn-pve02.auto.tfvars").write_text('vmid = 200\n')

    ci = d / "cloud-init" / "snippets" / "user-data"
    ci.mkdir(parents=True)
    (ci / "k3s-worker-01.yaml").write_text("#cloud-config\n")

    ans = d / "ansible"
    ans.mkdir()
    (ans / "spawn-pve02.ini").write_text("[pve02]\npve02 ansible_host=192.168.1.15\n")

    return d


class TestPackageNaming(unittest.TestCase):
    def test_includes_cell_id(self):
        name = _package_name(PLAN, _NOW)
        self.assertIn("cell-alpha", name)

    def test_includes_hostname(self):
        name = _package_name(PLAN, _NOW)
        self.assertIn("pve02", name)

    def test_includes_timestamp(self):
        name = _package_name(PLAN, _NOW)
        self.assertIn("2026-06-01", name)

    def test_ends_with_tar_gz(self):
        name = _package_name(PLAN, _NOW)
        self.assertTrue(name.endswith(".tar.gz"))

    def test_unknown_fallback(self):
        name = _package_name({}, _NOW)
        self.assertIn("unknown-cell", name)
        self.assertIn("unknown", name)


class TestAssembleBasicContents(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        artifacts = _make_artifacts_dir(tmp)
        self.pkg = assemble_spawn_package(PLAN, MANIFEST, artifacts, tmp / "out", now=_NOW)
        self.contents = package_contents(self.pkg)

    def tearDown(self):
        self._tmp.cleanup()

    def test_package_file_exists(self):
        self.assertTrue(self.pkg.exists())

    def test_spawn_manifest_present(self):
        self.assertIn("spawn-manifest.json", self.contents)

    def test_spawn_plan_present(self):
        self.assertIn("spawn-plan.json", self.contents)

    def test_checkpoint_lib_present(self):
        self.assertIn("lib/checkpoint.sh", self.contents)

    def test_keepass_gate_present(self):
        self.assertIn("lib/keepass-gate.sh", self.contents)

    def test_spawn_sh_present(self):
        self.assertIn("spawn.sh", self.contents)

    def test_phase_00_preflight_present(self):
        self.assertIn("phase-00-preflight.sh", self.contents)

    def test_phase_00_host_present(self):
        self.assertIn("phase-00-host.sh", self.contents)

    def test_phase_06_verify_present(self):
        self.assertIn("phase-06-verify.sh", self.contents)

    def test_tfvars_present(self):
        any_tfvars = any("opentofu" in c for c in self.contents)
        self.assertTrue(any_tfvars)

    def test_cloud_init_present(self):
        any_ci = any("cloud-init" in c for c in self.contents)
        self.assertTrue(any_ci)

    def test_ansible_present(self):
        any_ans = any("ansible" in c for c in self.contents)
        self.assertTrue(any_ans)

    def test_no_kdbx_by_default(self):
        self.assertFalse(any("kdbx" in c for c in self.contents))


class TestManifestJsonInPackage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        artifacts = _make_artifacts_dir(tmp)
        pkg = assemble_spawn_package(PLAN, MANIFEST, artifacts, tmp / "out", now=_NOW)
        with tarfile.open(pkg, "r:gz") as tar:
            self._manifest_bytes = tar.extractfile("spawn-manifest.json").read()
            self._plan_bytes     = tar.extractfile("spawn-plan.json").read()

    def tearDown(self):
        self._tmp.cleanup()

    def test_manifest_is_valid_json(self):
        data = json.loads(self._manifest_bytes)
        self.assertEqual(data["cell_id"], "cell-alpha")

    def test_plan_is_valid_json(self):
        data = json.loads(self._plan_bytes)
        self.assertEqual(data["hostname"], "pve02")


class TestKeePassEmbedding(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        artifacts = _make_artifacts_dir(tmp)
        # Create a fake kdbx file
        kdbx = tmp / "vault.kdbx"
        kdbx.write_bytes(b"FAKE_KDBX_DATA")
        pkg = assemble_spawn_package(
            PLAN, MANIFEST, artifacts, tmp / "out", kdbx_path=kdbx, now=_NOW
        )
        self.contents = package_contents(pkg)

    def tearDown(self):
        self._tmp.cleanup()

    def test_kdbx_embedded(self):
        self.assertTrue(any("kdbx" in c for c in self.contents))

    def test_kdbx_filename_preserved(self):
        self.assertTrue(any("vault.kdbx" in c for c in self.contents))


class TestKeePassGateContent(unittest.TestCase):
    def test_unlock_function_present(self):
        self.assertIn("keepass_unlock_gate()", KEEPASS_GATE_SH)

    def test_find_db_function_present(self):
        self.assertIn("keepass_find_db()", KEEPASS_GATE_SH)

    def test_kdbx_get_function_present(self):
        self.assertIn("kdbx_get()", KEEPASS_GATE_SH)

    def test_master_password_prompt(self):
        self.assertIn("Master password:", KEEPASS_GATE_SH)

    def test_unlocked_flag_idempotent(self):
        self.assertIn("KDBX_UNLOCKED", KEEPASS_GATE_SH)

    def test_embedded_db_check(self):
        self.assertIn("kdbx/*.kdbx", KEEPASS_GATE_SH)

    def test_keepassxc_cli_used(self):
        self.assertIn("keepassxc-cli", KEEPASS_GATE_SH)

    def test_export_credentials(self):
        self.assertIn("export KDBX_PATH KDBX_MASTER_PASSWORD", KEEPASS_GATE_SH)

    def test_no_secret_echoed_to_stdout(self):
        # Master password read must use -s (silent) flag
        self.assertIn("-rsp", KEEPASS_GATE_SH)

    def test_abort_on_db_not_found(self):
        self.assertIn("exit 1", KEEPASS_GATE_SH)


class TestCheckpointLibContent(unittest.TestCase):
    def test_checkpoint_start_present(self):
        self.assertIn("checkpoint_start()", CHECKPOINT_SH)

    def test_checkpoint_done_present(self):
        self.assertIn("checkpoint_done()", CHECKPOINT_SH)

    def test_is_done_present(self):
        self.assertIn("is_done()", CHECKPOINT_SH)

    def test_checkpoint_failed_exits(self):
        self.assertIn("exit 1", CHECKPOINT_SH)

    def test_checkpoint_dir_created(self):
        self.assertIn("CHECKPOINT_DIR", CHECKPOINT_SH)

    def test_checkpoint_reset_present(self):
        self.assertIn("checkpoint_reset()", CHECKPOINT_SH)


class TestPackageContentsList(unittest.TestCase):
    def test_returns_list(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        artifacts = _make_artifacts_dir(tmp)
        pkg = assemble_spawn_package(PLAN, MANIFEST, artifacts, tmp / "out", now=_NOW)
        result = package_contents(pkg)
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        self._tmp.cleanup()


class TestHaPhaseConditional(unittest.TestCase):
    def test_ha_phase_included_when_present(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        artifacts = _make_artifacts_dir(tmp, include_ha=True)
        pkg = assemble_spawn_package(PLAN, MANIFEST, artifacts, tmp / "out", now=_NOW)
        contents = package_contents(pkg)
        self.assertIn("phase-05-ha.sh", contents)
        self._tmp.cleanup()

    def test_ha_phase_absent_when_not_generated(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        artifacts = _make_artifacts_dir(tmp, include_ha=False)
        pkg = assemble_spawn_package(PLAN, MANIFEST, artifacts, tmp / "out", now=_NOW)
        contents = package_contents(pkg)
        self.assertNotIn("phase-05-ha.sh", contents)
        self._tmp.cleanup()


class TestWorkbookEmbedded(unittest.TestCase):
    def test_workbook_html_in_package(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        artifacts = _make_artifacts_dir(tmp)
        pkg = assemble_spawn_package(PLAN, MANIFEST, artifacts, tmp / "out", now=_NOW)
        contents = package_contents(pkg)
        self.assertTrue(any(c.endswith(".html") for c in contents))
        self._tmp.cleanup()

    def test_workbook_name_includes_hostname(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        artifacts = _make_artifacts_dir(tmp)
        pkg = assemble_spawn_package(PLAN, MANIFEST, artifacts, tmp / "out", now=_NOW)
        contents = package_contents(pkg)
        html = [c for c in contents if c.endswith(".html")]
        self.assertTrue(any("pve02" in c for c in html))
        self._tmp.cleanup()


class TestOutputDirCreated(unittest.TestCase):
    def test_creates_output_dir(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        artifacts = _make_artifacts_dir(tmp)
        out = tmp / "nested" / "output"
        self.assertFalse(out.exists())
        assemble_spawn_package(PLAN, MANIFEST, artifacts, out, now=_NOW)
        self.assertTrue(out.exists())
        self._tmp.cleanup()


PLAN_WITH_VMS = {
    "cell_id": "cell-alpha",
    "hostname": "pve02",
    "package_id": "spawn-cell-alpha-pve02-ts",
    "generated_at": "2026-06-01T12:00:00Z",
    "disposition": {"execution_mode": "autonomous"},
    "k3s": {"role": "worker"},
    "vms": [{"name": "pve02-vm01", "vmid": 200, "ip": "192.168.1.50",
             "cores": 2, "memory_mb": 4096, "disk_gb": 40}],
}


class TestInternalScriptGeneration(unittest.TestCase):
    """When artifacts_dir=None, assemble_spawn_package generates scripts internally."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.pkg = assemble_spawn_package(PLAN_WITH_VMS, MANIFEST, artifacts_dir=None,
                                          output_dir=tmp / "out", now=_NOW)
        self.contents = package_contents(self.pkg)

    def tearDown(self):
        self._tmp.cleanup()

    def test_package_created(self):
        self.assertTrue(self.pkg.exists())

    def test_spawn_manifest_present(self):
        self.assertIn("spawn-manifest.json", self.contents)

    def test_spawn_plan_present(self):
        self.assertIn("spawn-plan.json", self.contents)

    def test_lib_checkpoint_present(self):
        self.assertIn("lib/checkpoint.sh", self.contents)

    def test_spawn_sh_generated(self):
        self.assertIn("spawn.sh", self.contents)

    def test_phase_00_preflight_generated(self):
        self.assertIn("phase-00-preflight.sh", self.contents)

    def test_phase_06_verify_generated(self):
        self.assertIn("phase-06-verify.sh", self.contents)

    def test_opentofu_tfvars_generated(self):
        self.assertTrue(any("opentofu" in c and ".tfvars" in c for c in self.contents))

    def test_cloud_init_generated(self):
        self.assertTrue(any("cloud-init" in c for c in self.contents))

    def test_ansible_inventory_generated(self):
        self.assertTrue(any("ansible" in c for c in self.contents))

    def test_no_phase_05_ha_for_worker(self):
        # Worker nodes should not have the HA phase
        self.assertNotIn("phase-05-ha.sh", self.contents)

    def test_phase_05_ha_included_for_server(self):
        """Server nodes with VMs should get phase-05-ha.sh generated."""
        import tempfile
        ha_plan = dict(PLAN_WITH_VMS, k3s={"role": "server"})
        with tempfile.TemporaryDirectory() as tmp:
            pkg = assemble_spawn_package(ha_plan, MANIFEST, artifacts_dir=None,
                                         output_dir=Path(tmp) / "out", now=_NOW)
            contents = package_contents(pkg)
        self.assertIn("phase-05-ha.sh", contents)

    def test_wan_mode_spawn_sh_includes_tailscale_join(self):
        """WAN network_mode should add tailscale-join phase to spawn.sh."""
        import tempfile, tarfile as tf
        wan_plan = dict(PLAN_WITH_VMS, disposition={"execution_mode": "autonomous",
                                                     "network_mode": "wan"})
        with tempfile.TemporaryDirectory() as tmp:
            pkg = assemble_spawn_package(wan_plan, MANIFEST, artifacts_dir=None,
                                         output_dir=Path(tmp) / "out", now=_NOW)
            with tf.open(pkg, "r:gz") as tar:
                spawn_sh = tar.extractfile("spawn.sh").read().decode()
        self.assertIn("tailscale-join", spawn_sh)

    def test_wan_mode_package_contains_tailscale_join_sh(self):
        """WAN package must contain tailscale-join.sh (not just reference it in spawn.sh)."""
        import tempfile
        wan_plan = dict(PLAN_WITH_VMS, disposition={"execution_mode": "autonomous",
                                                     "network_mode": "wan"})
        with tempfile.TemporaryDirectory() as tmp:
            pkg = assemble_spawn_package(wan_plan, MANIFEST, artifacts_dir=None,
                                         output_dir=Path(tmp) / "out", now=_NOW)
            contents = package_contents(pkg)
        self.assertIn("tailscale-join.sh", contents)

    def test_lan_mode_package_excludes_tailscale_join_sh(self):
        """LAN package must NOT contain tailscale-join.sh."""
        with tempfile.TemporaryDirectory() as tmp:
            pkg = assemble_spawn_package(PLAN_WITH_VMS, MANIFEST, artifacts_dir=None,
                                         output_dir=Path(tmp) / "out", now=_NOW)
            contents = package_contents(pkg)
        self.assertNotIn("tailscale-join.sh", contents)


class TestCLISpawnManifestGeneration(unittest.TestCase):
    """CLI converts bootstrap-state.json to a proper spawn manifest with hatchery_url.
    When given a pre-existing spawn-manifest.json, it is used as-is."""

    def _run_assembler(self, state_dict, plan_dict, tmp):
        import subprocess
        state_path = Path(tmp) / "state.json"
        plan_path  = Path(tmp) / "spawn-plan.json"
        state_path.write_text(json.dumps(state_dict))
        plan_path.write_text(json.dumps(plan_dict))
        result = subprocess.run(
            [sys.executable,
             str(REPO_ROOT / "proxmox-bootstrap" / "assemble-spawn-package.py"),
             "--plan", str(plan_path),
             "--state", str(state_path),
             "--output-dir", tmp],
            capture_output=True, text=True, timeout=15,
        )
        return result

    def test_cli_generates_hatchery_url_from_bootstrap_state(self):
        """When --state is a bootstrap-state.json, the CLI calls read_hatchery_state
        to generate a spawn manifest with hatchery_url and receiver_token fields."""
        import subprocess
        import tarfile as tf
        import tempfile

        bootstrap_state = {
            "cell_id": "cell-alpha",
            "host_identity": {
                "hostname": "pve01",
                "fqdn": "pve01.home.example.com",
            },
            "network_topology": {"profile": "lan"},
            "vms": [],
        }
        plan = {
            "cell_id": "cell-alpha",
            "hostname": "pve02",
            "disposition": {"execution_mode": "autonomous"},
            "k3s": {"role": "worker"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "bootstrap-state.json"
            plan_path  = Path(tmp) / "spawn-plan.json"
            state_path.write_text(json.dumps(bootstrap_state))
            plan_path.write_text(json.dumps(plan))

            result = subprocess.run(
                [sys.executable,
                 str(REPO_ROOT / "proxmox-bootstrap" / "assemble-spawn-package.py"),
                 "--plan", str(plan_path),
                 "--state", str(state_path),
                 "--output-dir", tmp],
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            # Find the generated package
            packages = list(Path(tmp).glob("spawn-package-*.tar.gz"))
            self.assertEqual(len(packages), 1)

            with tf.open(packages[0], "r:gz") as tar:
                manifest_bytes = tar.extractfile("spawn-manifest.json").read()
            manifest_data = json.loads(manifest_bytes)

            # read_hatchery_state generates hatchery_url from host_identity.fqdn
            self.assertIn("hatchery_url", manifest_data)
            self.assertIn("pve01.home.example.com", manifest_data.get("hatchery_url", ""))

    def test_cli_uses_pregenerated_spawn_manifest_as_is(self):
        """When --state is a pre-generated spawn manifest (has hatchery_url at top level),
        it is used as-is without regenerating through read_hatchery_state."""
        import tarfile as tf
        import tempfile

        # Pre-generated spawn manifest (already has hatchery_url + receiver_token)
        spawn_manifest = {
            "cell_id": "cell-alpha",
            "schema_version": "1.0",
            "hatchery_url": "http://custom-hatchery:9321",
            "receiver_token": "my-secret-token",
            "hatchery": {"hostname": "pve01", "fqdn": "pve01.example.com"},
        }
        plan = {
            "cell_id": "cell-alpha",
            "hostname": "pve02",
            "disposition": {"execution_mode": "autonomous"},
            "k3s": {"role": "worker"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            result = self._run_assembler(spawn_manifest, plan, tmp)
            self.assertEqual(result.returncode, 0, msg=result.stderr)

            packages = list(Path(tmp).glob("spawn-package-*.tar.gz"))
            self.assertEqual(len(packages), 1)

            with tf.open(packages[0], "r:gz") as tar:
                manifest_bytes = tar.extractfile("spawn-manifest.json").read()
            manifest_data = json.loads(manifest_bytes)

            # Spawn manifest should be used as-is (custom hatchery_url preserved)
            self.assertEqual(manifest_data.get("hatchery_url"), "http://custom-hatchery:9321")
            self.assertEqual(manifest_data.get("receiver_token"), "my-secret-token")


if __name__ == "__main__":
    unittest.main()
