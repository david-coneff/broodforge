"""
test_forge_assembler.py — Tests for Phase 1.F.1/1.F.2:
  assemble_forge_package.py  — forge package assembler
  forge_scripts.py           — forge phase script generators
"""

import json
import tarfile
from pathlib import Path

import assemble_forge_package as _afp
import forge_scripts as _fs

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _manifest(cell_id="pve01-cell", hostname="pve01", profile="lan"):
    return {
        "schema_version": "1.0",
        "cell_id": cell_id,
        "generated_at": "2026-06-01T12:00:00+00:00",
        "setup_mode": "autonomous",
        "host_identity": {
            "hostname": hostname,
            "domain": "home.example.com",
            "fqdn": f"{hostname}.home.example.com",
            "cell_id": cell_id,
        },
        "network_topology": {
            "profile": profile,
            "management_cidr": "192.168.1.0/24",
            "gateway": "192.168.1.1",
        },
    }


# ===========================================================================
# forge_scripts.py — script generators
# ===========================================================================

class TestForgeScripts:
    def test_checkpoint_sh_content(self):
        content = _fs.FORGE_CHECKPOINT_SH
        assert "checkpoint_done" in content
        assert "checkpoint_start" in content
        assert "is_done" in content

    def test_keepass_gate_content(self):
        content = _fs.FORGE_KEEPASS_GATE_SH
        assert "forge_keepass_gate" in content
        assert "keepassxc-cli" in content

    def test_generate_forge_sh_returns_string(self):
        s = _fs.generate_forge_sh(_manifest())
        assert isinstance(s, str)

    def test_forge_sh_contains_all_phases(self):
        s = _fs.generate_forge_sh(_manifest())
        for phase in [
            "phase-00-discover.sh", "phase-01-plan.sh", "phase-02-validate.sh",
            "phase-03-host.sh", "phase-04-vms.sh", "phase-05-k3s.sh",
            "phase-06-gitops.sh", "phase-07-intelligence.sh", "phase-08-verify.sh",
        ]:
            assert phase in s, f"{phase} missing from forge.sh"

    def test_forge_sh_has_shebang(self):
        s = _fs.generate_forge_sh(_manifest())
        assert s.startswith("#!/usr/bin/env bash")

    def test_forge_sh_contains_cell_id(self):
        s = _fs.generate_forge_sh(_manifest(cell_id="testcell"))
        assert "testcell" in s

    def test_phase_00_hardware_discovery(self):
        s = _fs.generate_phase_00_sh(_manifest())
        assert "hardware" in s.lower() or "discover" in s.lower()

    def test_phase_01_planner(self):
        s = _fs.generate_phase_01_sh(_manifest())
        assert "forge-planner" in s or "forge_planner" in s

    def test_phase_02_validator(self):
        s = _fs.generate_phase_02_sh(_manifest())
        assert "forge_validator" in s

    def test_phase_02_no_file_dunder_in_heredoc(self):
        # __file__ is undefined in python3 - <<'PYEOF' heredocs; must use SCRIPT_DIR env.
        # Check that the Python code uses os.environ.get("SCRIPT_DIR") not __file__.
        s = _fs.generate_phase_02_sh(_manifest())
        assert "os.environ" in s and "SCRIPT_DIR" in s
        assert 'abspath(__file__)' not in s

    def test_phase_02_blocks_on_red(self):
        s = _fs.generate_phase_02_sh(_manifest())
        assert "sys.exit(1)" in s

    def test_phase_03_no_file_dunder_in_heredoc(self):
        # Phase 03 passphrase suggestion heredoc must not use __file__ (undefined in stdin mode).
        s = _fs.generate_phase_03_sh(_manifest())
        assert 'abspath(__file__)' not in s

    def test_phase_03_hostname_set(self):
        s = _fs.generate_phase_03_sh(_manifest())
        assert "hostnamectl" in s

    def test_phase_03_nag_suppress(self):
        s = _fs.generate_phase_03_sh(_manifest())
        assert "pve-suppress-nag" in s

    def test_phase_03_dnsmasq(self):
        s = _fs.generate_phase_03_sh(_manifest())
        assert "dnsmasq" in s

    def test_phase_03_keepass_init(self):
        s = _fs.generate_phase_03_sh(_manifest())
        assert "keepass" in s.lower()

    def test_phase_03_wan_profile_includes_headscale(self):
        s = _fs.generate_phase_03_sh(_manifest(profile="wan"))
        assert "headscale" in s.lower()

    def test_phase_03_lan_profile_no_headscale_block(self):
        s = _fs.generate_phase_03_sh(_manifest(profile="lan"))
        # LAN profile should not run headscale setup
        # The WAN block is conditional on NETWORK_PROFILE=wan
        assert "NETWORK_PROFILE='lan'" in s

    def test_phase_04_tofu(self):
        s = _fs.generate_phase_04_sh(_manifest())
        assert "tofu" in s

    def test_phase_05_k3s_ansible(self):
        s = _fs.generate_phase_05_sh(_manifest())
        assert "ansible-playbook" in s or "k3s" in s

    def test_phase_05_exports_worker_token_before_heredoc(self):
        # N-001: _worker_token and _server_token must be exported so the
        # python3 heredoc subprocess can read them via os.environ[].
        s = _fs.generate_phase_05_sh(_manifest())
        assert "export _worker_token" in s, "export _worker_token missing — heredoc will raise KeyError"
        assert "export _server_token" in s, "export _server_token missing — heredoc will raise KeyError"

    def test_phase_05_export_precedes_heredoc(self):
        # Guards ordering: export must appear before the python3 heredoc block.
        s = _fs.generate_phase_05_sh(_manifest())
        export_pos = s.index("export _worker_token")
        heredoc_pos = s.index("python3 - <<PYEOF")
        assert export_pos < heredoc_pos, "export must come before the python3 heredoc"

    def test_phase_06_exits_2_when_credentials_missing(self):
        # N-002: phase-06 must exit 2 (NOT_IMPLEMENTED) when Forgejo credentials
        # are absent — so forge.sh sets _forge_incomplete=1 and reaches the
        # FORGE_INCOMPLETE banner instead of aborting with "FAIL phase-06".
        s = _fs.generate_phase_06_sh(_manifest())
        # Find the credential-missing block and confirm exit 2
        assert "exit 2" in s, "phase-06 should exit 2 (NOT_IMPLEMENTED) when credentials missing"

    def test_phase_06_flux(self):
        s = _fs.generate_phase_06_sh(_manifest())
        assert "flux" in s

    def test_phase_07_intelligence(self):
        s = _fs.generate_phase_07_sh(_manifest())
        assert "bootstrap-state" in s or "assessment" in s.lower()

    def test_phase_08_verify(self):
        s = _fs.generate_phase_08_sh(_manifest())
        assert "kubectl" in s
        assert "Ready" in s

    def test_phase_08_git_commit(self):
        s = _fs.generate_phase_08_sh(_manifest())
        assert "git commit" in s

    # R3-001: phase-08 must exit 2 (NOT_IMPLEMENTED) when k3s is absent
    def test_phase_08_exits_2_when_k3s_absent(self):
        s = _fs.generate_phase_08_sh(_manifest())
        assert "exit 2" in s, "phase-08 must exit 2 when k3s is not installed"

    def test_phase_08_k3s_absent_detection(self):
        s = _fs.generate_phase_08_sh(_manifest())
        assert "/etc/rancher/k3s/k3s.yaml" in s, "phase-08 must check for k3s yaml to detect absent cluster"

    def test_phase_08_fatal_exit_1_preserved(self):
        # exit 1 path (cluster broken) must still exist alongside exit 2 (k3s absent)
        s = _fs.generate_phase_08_sh(_manifest())
        assert "exit 1" in s or "checkpoint_failed" in s, "fatal path for degraded cluster must be retained"

    # R3-004: forge_keepass_gate must be called in phase-05 and phase-06
    def test_phase_05_calls_keepass_gate_before_kdbx_get(self):
        s = _fs.generate_phase_05_sh(_manifest())
        gate_pos = s.find("forge_keepass_gate")
        kdbx_pos = s.find("kdbx_get")
        assert gate_pos != -1, "phase-05 must call forge_keepass_gate"
        assert kdbx_pos != -1, "phase-05 must have kdbx_get"
        assert gate_pos < kdbx_pos, "forge_keepass_gate must appear before kdbx_get in phase-05"

    def test_phase_06_calls_keepass_gate_before_kdbx_get(self):
        s = _fs.generate_phase_06_sh(_manifest())
        gate_pos = s.find("forge_keepass_gate")
        kdbx_pos = s.find("kdbx_get")
        assert gate_pos != -1, "phase-06 must call forge_keepass_gate"
        assert kdbx_pos != -1, "phase-06 must have kdbx_get"
        assert gate_pos < kdbx_pos, "forge_keepass_gate must appear before kdbx_get in phase-06"

    def test_keepass_gate_has_session_file_support(self):
        # R3-004/R4-001: gate must persist both FORGE_KDBX_PATH and password to session file
        g = _fs.FORGE_KEEPASS_GATE_SH
        assert "_FORGE_SESSION_FILE" in g, "gate must define session file variable"
        assert "install -m 600" in g or "chmod 600" in g, "session file must be 0600"
        # R4-001: session file must store FORGE_KDBX_PATH (line 1) alongside password (line 2)
        assert "FORGE_KDBX_PATH" in g, "gate must reference FORGE_KDBX_PATH in session file"
        # Resume path must export FORGE_KDBX_PATH so kdbx_get can use it in subprocess
        resume_start = g.find("Session resumed")
        assert resume_start != -1, "gate must have a 'session resumed' message"
        resume_section = g[:resume_start]
        assert "export FORGE_KDBX_PATH" in resume_section, \
            "session resume must export FORGE_KDBX_PATH so kdbx_get can use it"

    def test_forge_sh_cleans_up_session_file(self):
        # R3-004: forge.sh must remove the session file on exit
        s = _fs.generate_forge_sh(_manifest())
        assert "FORGE_SESSION_FILE" in s or "broodforge-forge.session" in s, \
            "forge.sh must reference the session file for cleanup"
        assert "trap" in s, "forge.sh must use trap for cleanup"

    def test_write_all_forge_scripts(self, tmp_path):
        written = _fs.write_all_forge_scripts(_manifest(), str(tmp_path))
        assert "forge.sh" in written
        assert len(written) >= 10  # 9 phases + forge.sh + 2 lib scripts


# ===========================================================================
# assemble_forge_package.py — assembler
# ===========================================================================

class TestPackageName:
    def test_contains_cell_id(self):
        from datetime import datetime, timezone
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        name = _afp.package_name(_manifest(), now=now)
        assert "pve01-cell" in name

    def test_contains_timestamp(self):
        from datetime import datetime, timezone
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        name = _afp.package_name(_manifest(), now=now)
        assert "2026-06-01" in name

    def test_ends_with_tar_gz(self):
        name = _afp.package_name(_manifest())
        assert name.endswith(".tar.gz")

    def test_starts_with_forge_package(self):
        name = _afp.package_name(_manifest())
        assert name.startswith("forge-package-")


class TestPackageContents:
    def test_returns_list(self):
        items = _afp.package_contents(_manifest())
        assert isinstance(items, list)

    def test_contains_forge_sh(self):
        items = _afp.package_contents(_manifest())
        assert "forge.sh" in items

    def test_contains_manifest(self):
        items = _afp.package_contents(_manifest())
        assert "forge-manifest.json" in items

    def test_contains_workbook(self):
        items = _afp.package_contents(_manifest())
        assert "forge-workbook.html" in items

    def test_contains_lib_scripts(self):
        items = _afp.package_contents(_manifest())
        assert "lib/checkpoint.sh" in items
        assert "lib/pve-suppress-nag.sh" in items

    def test_embed_kdbx_adds_entry(self):
        items = _afp.package_contents(_manifest(), embed_kdbx=True)
        assert any(".kdbx" in i for i in items)

    def test_no_kdbx_by_default(self):
        items = _afp.package_contents(_manifest(), embed_kdbx=False)
        assert not any(".kdbx" in i for i in items)


class TestAssembleForgePackage:
    def _build(self, tmp_path, manifest=None, **kw):
        from datetime import datetime, timezone
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        m = manifest or _manifest()
        return _afp.assemble_forge_package(
            manifest=m, output_dir=tmp_path, now=now, **kw
        )

    def test_returns_path(self, tmp_path):
        pkg = self._build(tmp_path)
        assert isinstance(pkg, Path)

    def test_file_exists(self, tmp_path):
        pkg = self._build(tmp_path)
        assert pkg.exists()

    def test_is_tar_gz(self, tmp_path):
        pkg = self._build(tmp_path)
        assert tarfile.is_tarfile(str(pkg))

    def test_contains_manifest(self, tmp_path):
        pkg = self._build(tmp_path)
        with tarfile.open(str(pkg), "r:gz") as tar:
            names = tar.getnames()
        assert "forge-manifest.json" in names

    def test_manifest_content_correct(self, tmp_path):
        m = _manifest(cell_id="testcell")
        pkg = self._build(tmp_path, manifest=m)
        with tarfile.open(str(pkg), "r:gz") as tar:
            data = tar.extractfile("forge-manifest.json").read()
        loaded = json.loads(data)
        assert loaded["cell_id"] == "testcell"

    def test_contains_forge_sh(self, tmp_path):
        pkg = self._build(tmp_path)
        with tarfile.open(str(pkg), "r:gz") as tar:
            names = tar.getnames()
        assert "forge.sh" in names

    def test_contains_all_phase_scripts(self, tmp_path):
        pkg = self._build(tmp_path)
        with tarfile.open(str(pkg), "r:gz") as tar:
            names = tar.getnames()
        for n in range(9):
            phase_scripts = [x for x in names if f"phase-0{n}" in x or f"phase-{n:02d}" in x]
            assert phase_scripts, f"phase-{n:02d} script missing from archive"

    def test_contains_workbook_html(self, tmp_path):
        pkg = self._build(tmp_path)
        with tarfile.open(str(pkg), "r:gz") as tar:
            names = tar.getnames()
        assert "forge-workbook.html" in names

    def test_contains_lib_checkpoint(self, tmp_path):
        pkg = self._build(tmp_path)
        with tarfile.open(str(pkg), "r:gz") as tar:
            names = tar.getnames()
        assert "lib/checkpoint.sh" in names

    def test_contains_lib_nag_suppress(self, tmp_path):
        pkg = self._build(tmp_path)
        with tarfile.open(str(pkg), "r:gz") as tar:
            names = tar.getnames()
        assert "lib/pve-suppress-nag.sh" in names

    def test_no_kdbx_by_default(self, tmp_path):
        pkg = self._build(tmp_path)
        with tarfile.open(str(pkg), "r:gz") as tar:
            names = tar.getnames()
        assert not any(".kdbx" in n for n in names)

    def test_embed_kdbx(self, tmp_path):
        kdbx = tmp_path / "test.kdbx"
        kdbx.write_bytes(b"fake kdbx content")
        pkg = self._build(tmp_path, kdbx_path=kdbx)
        with tarfile.open(str(pkg), "r:gz") as tar:
            names = tar.getnames()
        assert any(".kdbx" in n for n in names)

    def test_package_name_in_output_dir(self, tmp_path):
        pkg = self._build(tmp_path)
        assert pkg.parent == tmp_path

    def test_different_cells_different_packages(self, tmp_path):
        from datetime import datetime, timezone
        now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        m1 = _manifest(cell_id="cell-a")
        m2 = _manifest(cell_id="cell-b")
        pkg1 = _afp.assemble_forge_package(m1, tmp_path, now=now)
        pkg2 = _afp.assemble_forge_package(m2, tmp_path, now=now)
        assert pkg1.name != pkg2.name
