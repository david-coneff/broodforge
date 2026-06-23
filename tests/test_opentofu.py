"""
Tests for Phase 6: OpenTofu state parsing, comparison engine,
comparison report, schema validation, and CLI commands.
"""

from __future__ import annotations

import contextlib
import io
import json

from engine.cli import build_parser, cmd_compare, cmd_opentofu_ingest
from engine.compare import ComparisonResult, _guest_key, _resource_key, compare
from engine.opentofu import _detect_tool, _normalise_provider, ingest_state, parse_state_file
from engine.report_compare import generate_comparison_report
from engine.schema import validate_assessment

# ===========================================================================
# Fixtures
# ===========================================================================

MINIMAL_STATE = {
    "version": 4,
    "terraform_version": "1.6.0",
    "serial": 12,
    "lineage": "abc-123",
    "resources": [],
}

PROXMOX_STATE = {
    "version": 4,
    "terraform_version": "1.6.0",
    "serial": 42,
    "lineage": "xyz-456",
    "resources": [
        {
            "type": "proxmox_vm_qemu",
            "name": "web01",
            "provider": 'provider["registry.terraform.io/telmate/proxmox"]',
            "instances": [
                {
                    "attributes": {
                        "name": "web01",
                        "target_node": "pve01",
                        "vmid": 100,
                        "cores": 2,
                        "memory": 4096,
                        "disk": [{"size": "32G"}],
                        "network": [{"model": "virtio", "bridge": "vmbr0"}],
                        "tags": "webserver;production",
                    }
                }
            ],
        },
        {
            "type": "proxmox_vm_qemu",
            "name": "db01",
            "provider": 'provider["registry.terraform.io/telmate/proxmox"]',
            "instances": [
                {
                    "attributes": {
                        "name": "db01",
                        "target_node": "pve01",
                        "vmid": 101,
                        "cores": 4,
                        "memory": 8192,
                        "disk": [{"size": "64G"}],
                        "network": [{"model": "virtio", "bridge": "vmbr0"}],
                    }
                }
            ],
        },
        {
            "type": "proxmox_lxc",
            "name": "ct-nginx",
            "provider": 'provider["registry.terraform.io/telmate/proxmox"]',
            "instances": [
                {
                    "attributes": {
                        "hostname": "ct-nginx",
                        "target_node": "pve01",
                        "vmid": 200,
                        "cores": 1,
                        "memory": 512,
                        "rootfs": [{"size": "8G"}],
                        "network": [{"bridge": "vmbr0"}],
                    }
                }
            ],
        },
        {
            "type": "null_resource",
            "name": "always_run",
            "provider": 'provider["registry.terraform.io/hashicorp/null"]',
            "instances": [{"attributes": {}}],
        },
        {
            "type": "proxmox_vm_qemu",
            "name": "tainted_vm",
            "provider": 'provider["registry.terraform.io/telmate/proxmox"]',
            "instances": [
                {
                    "status": "tainted",
                    "attributes": {
                        "name": "tainted_vm",
                        "target_node": "pve01",
                        "vmid": 999,
                        "cores": 2,
                        "memory": 2048,
                    },
                }
            ],
        },
        # Resource with count = 0 (no instances)
        {
            "type": "proxmox_vm_qemu",
            "name": "disabled_vm",
            "provider": 'provider["registry.terraform.io/telmate/proxmox"]',
            "instances": [],
        },
    ],
}

OPENTOFU_STATE = {
    "version": 4,
    "terraform_version": "OpenTofu v1.6.0",
    "serial": 1,
    "resources": [],
}


def _write_state(tmp_path, state_dict, name="terraform.tfstate"):
    f = tmp_path / name
    f.write_text(json.dumps(state_dict))
    return f


def _base_assessment():
    return {
        "schema_version": "1.0",
        "timestamp": "2024-06-01T12:00:00+00:00",
        "hostname": "pve01.lab",
    }


def _guest(hostname, groups=None, os_dist="Debian", method="ansible-facts"):
    return {
        "hostname": hostname,
        "inventory_name": hostname,
        "groups": groups or [],
        "collection_method": method,
        "collection_timestamp": "2024-06-01T12:00:00+00:00",
        "operating_system": {"distribution": os_dist, "distribution_version": "12"},
    }


# ===========================================================================
# State file parsing
# ===========================================================================

class TestParseStateFile:
    def test_empty_resources(self, tmp_path):
        f = _write_state(tmp_path, MINIMAL_STATE)
        result = parse_state_file(f)
        assert result.resources == []
        assert result.errors == []

    def test_meta_populated(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        result = parse_state_file(f)
        assert result.meta["terraform_version"] == "1.6.0"
        assert result.meta["serial"] == 42

    def test_resource_count(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        result = parse_state_file(f)
        # 4 instances (web01, db01, ct-nginx, null_resource, tainted_vm, disabled_vm=1 with no instances)
        assert len(result.resources) == 6

    def test_vm_attributes(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        result = parse_state_file(f)
        web01 = next(r for r in result.resources if r["resource_name"] == "web01")
        attrs = web01["attributes"]
        assert attrs["name"] == "web01"
        assert attrs["target_node"] == "pve01"
        assert attrs["vmid"] == 100
        assert attrs["cores"] == 2
        assert attrs["memory"] == 4096
        assert attrs["disk_size"] == "32G"

    def test_network_interfaces(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        result = parse_state_file(f)
        web01 = next(r for r in result.resources if r["resource_name"] == "web01")
        nics = web01["attributes"]["network_interfaces"]
        assert len(nics) == 1
        assert nics[0]["model"] == "virtio"
        assert nics[0]["bridge"] == "vmbr0"

    def test_tags_parsed(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        result = parse_state_file(f)
        web01 = next(r for r in result.resources if r["resource_name"] == "web01")
        assert "webserver" in web01["attributes"].get("tags", [])
        assert "production" in web01["attributes"].get("tags", [])

    def test_lxc_hostname(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        result = parse_state_file(f)
        ct = next(r for r in result.resources if r["resource_name"] == "ct-nginx")
        assert ct["attributes"]["name"] == "ct-nginx"

    def test_lxc_rootfs_disk(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        result = parse_state_file(f)
        ct = next(r for r in result.resources if r["resource_name"] == "ct-nginx")
        assert ct["attributes"]["disk_size"] == "8G"

    def test_tainted_resource(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        result = parse_state_file(f)
        tainted = next(r for r in result.resources if r["resource_name"] == "tainted_vm")
        assert tainted["taint"] is True
        assert tainted["status"] == "tainted"

    def test_normal_resource_not_tainted(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        result = parse_state_file(f)
        web01 = next(r for r in result.resources if r["resource_name"] == "web01")
        assert web01["taint"] is False
        assert web01["status"] == "declared"

    def test_provider_normalised(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        result = parse_state_file(f)
        web01 = next(r for r in result.resources if r["resource_name"] == "web01")
        assert web01["provider"] == "registry.terraform.io/telmate/proxmox"
        assert "provider[" not in web01["provider"]

    def test_missing_file_returns_error(self, tmp_path):
        result = parse_state_file(tmp_path / "nonexistent.tfstate")
        assert result.errors
        assert result.resources == []

    def test_invalid_json_returns_error(self, tmp_path):
        f = tmp_path / "bad.tfstate"
        f.write_text("not json")
        result = parse_state_file(f)
        assert result.errors
        assert result.resources == []


class TestDetectTool:
    def test_opentofu(self):
        assert _detect_tool({"terraform_version": "OpenTofu v1.6.0"}) == "opentofu"

    def test_terraform(self):
        assert _detect_tool({"terraform_version": "1.5.0"}) == "terraform"

    def test_empty_defaults_opentofu(self):
        assert _detect_tool({}) == "opentofu"


class TestNormaliseProvider:
    def test_strips_provider_brackets(self):
        assert _normalise_provider('provider["registry.terraform.io/telmate/proxmox"]') == \
               "registry.terraform.io/telmate/proxmox"

    def test_passthrough(self):
        assert _normalise_provider("hashicorp/null") == "hashicorp/null"


# ===========================================================================
# ingest_state
# ===========================================================================

class TestIngestState:
    def test_declared_resources_added(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        a = ingest_state(_base_assessment(), f)
        assert len(a["declared_resources"]) == 6

    def test_state_sources_declared_populated(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        a = ingest_state(_base_assessment(), f)
        declared = a["state_sources"]["declared"]
        assert declared["collected"] is True
        assert declared["terraform_version"] == "1.6.0"
        assert declared["serial"] == 42
        assert declared["resource_count"] == 6
        assert "terraform.tfstate" in declared["state_path"]

    def test_existing_assessment_preserved(self, tmp_path):
        f = _write_state(tmp_path, MINIMAL_STATE)
        base = {**_base_assessment(), "hardware": {"cpu": {"model": "Intel Xeon"}}}
        a = ingest_state(base, f)
        assert a["hardware"]["cpu"]["model"] == "Intel Xeon"

    def test_opentofu_tool_detected(self, tmp_path):
        f = _write_state(tmp_path, OPENTOFU_STATE)
        a = ingest_state(_base_assessment(), f)
        assert a["state_sources"]["declared"]["tool"] == "opentofu"

    def test_original_not_mutated(self, tmp_path):
        f = _write_state(tmp_path, MINIMAL_STATE)
        original = _base_assessment()
        ingest_state(original, f)
        assert "declared_resources" not in original


# ===========================================================================
# Schema validation
# ===========================================================================

class TestSchemaWithDeclared:
    def test_minimal_assessment_valid(self):
        assert validate_assessment(_base_assessment()) == []

    def test_with_declared_resources_valid(self, tmp_path):
        f = _write_state(tmp_path, PROXMOX_STATE)
        a = ingest_state(_base_assessment(), f)
        errors = validate_assessment(a)
        assert errors == [], f"Schema errors: {errors}"

    def test_declared_resource_required_fields(self, tmp_path):
        f = _write_state(tmp_path, MINIMAL_STATE)
        a = ingest_state(_base_assessment(), f)
        # Manually add an invalid declared resource (missing required fields)
        a["declared_resources"] = [{"resource_name": "broken"}]
        errors = validate_assessment(a)
        assert len(errors) > 0


# ===========================================================================
# Comparison engine
# ===========================================================================

def _assessment_with_all_layers():
    """Assessment with declared resources, configured+observed guests."""
    a = _base_assessment()
    a["declared_resources"] = [
        {
            "resource_type": "proxmox_vm_qemu",
            "resource_name": "web01",
            "provider": "registry.terraform.io/telmate/proxmox",
            "module": None,
            "instance_index": None,
            "taint": False,
            "status": "declared",
            "attributes": {"name": "web01", "target_node": "pve01", "vmid": 100, "cores": 2, "memory": 4096},
        },
        {
            "resource_type": "proxmox_vm_qemu",
            "resource_name": "db01",
            "provider": "registry.terraform.io/telmate/proxmox",
            "module": None,
            "instance_index": None,
            "taint": False,
            "status": "declared",
            "attributes": {"name": "db01", "target_node": "pve01", "vmid": 101, "cores": 4, "memory": 8192},
        },
        {
            "resource_type": "proxmox_vm_qemu",
            "resource_name": "ghost_vm",
            "provider": "registry.terraform.io/telmate/proxmox",
            "module": None,
            "instance_index": None,
            "taint": False,
            "status": "declared",
            "attributes": {"name": "ghost_vm", "target_node": "pve01", "vmid": 102},
        },
    ]
    a["guests"] = [
        _guest("web01", groups=["webservers"]),
        _guest("db01",  groups=["databases"]),
        _guest("mystery_host", groups=["ungrouped"]),  # observed but not declared
    ]
    a["state_sources"] = {
        "declared":   {"tool": "terraform", "state_path": "/infra/terraform.tfstate", "collected": True},
        "configured": {"tool": "ansible",   "inventory_path": "/inv/hosts.yml",       "collected": True},
        "observed":   {"tool": "broodforge", "collected": True},
    }
    return a


class TestCompare:
    def test_returns_result(self):
        assert isinstance(compare(_base_assessment()), ComparisonResult)

    def test_empty_assessment(self):
        result = compare(_base_assessment())
        assert result.summary()["declared_count"] == 0
        assert result.summary()["observed_count"] == 0

    def test_match_declared_and_observed(self):
        result = compare(_assessment_with_all_layers())
        matched_names = {m.name for m in result.matches}
        assert "web01" in matched_names
        assert "db01" in matched_names

    def test_declared_only(self):
        result = compare(_assessment_with_all_layers())
        declared_only_names = {r["attributes"]["name"] for r in result.declared_only}
        assert "ghost_vm" in declared_only_names

    def test_observed_only(self):
        result = compare(_assessment_with_all_layers())
        obs_only_names = {g["hostname"] for g in result.observed_only}
        assert "mystery_host" in obs_only_names

    def test_match_has_correct_layers(self):
        result = compare(_assessment_with_all_layers())
        web01 = next(m for m in result.matches if m.name == "web01")
        assert "declared" in web01.layers
        assert "observed" in web01.layers

    def test_summary_counts(self):
        result = compare(_assessment_with_all_layers())
        s = result.summary()
        assert s["declared_count"] == 3
        assert s["observed_count"] == 3
        assert s["matched_count"] >= 2
        assert s["declared_only_count"] >= 1
        assert s["observed_only_count"] >= 1

    def test_fqdn_short_hostname_matching(self):
        """Declared 'web01' should match observed 'web01.lab.example.com'."""
        a = _base_assessment()
        a["declared_resources"] = [{
            "resource_type": "proxmox_vm_qemu", "resource_name": "web01",
            "provider": "p", "module": None, "instance_index": None,
            "taint": False, "status": "declared",
            "attributes": {"name": "web01"},
        }]
        a["guests"] = [{
            "hostname": "web01.lab.example.com",
            "inventory_name": "web01",
            "groups": [], "collection_method": "ansible-facts",
            "collection_timestamp": "2024-01-01T00:00:00+00:00",
        }]
        result = compare(a)
        assert len(result.matches) == 1
        assert result.matches[0].name == "web01"

    def test_configured_only(self):
        """Hosts in inventory but not declared or observed."""
        a = _base_assessment()
        a["guests"] = [
            {
                "hostname": "orphan",
                "inventory_name": "orphan",
                "groups": [],
                "collection_method": "unreachable",
                "collection_timestamp": "2024-01-01T00:00:00+00:00",
            }
        ]
        # No declared_resources, no successful observations
        result = compare(a)
        # orphan is configured (in inventory) but not observed (unreachable) and not declared
        # It should appear in observed_only (it was in the guest list) or configured_only
        # Since guests list = configured hosts in our model, orphan is observed_only
        assert any(g["hostname"] == "orphan" for g in result.observed_only) or \
               "orphan" in result.configured_only


class TestResourceKey:
    def test_uses_name_attr(self):
        r = {"resource_name": "vm_resource", "instance_index": None,
             "attributes": {"name": "web01"}}
        assert _resource_key(r) == "web01"

    def test_falls_back_to_resource_name(self):
        r = {"resource_name": "my_vm", "instance_index": None, "attributes": {}}
        assert _resource_key(r) == "my_vm"

    def test_includes_index(self):
        r = {"resource_name": "vm", "instance_index": 0, "attributes": {}}
        assert _resource_key(r) == "vm[0]"

    def test_lowercased(self):
        r = {"resource_name": "VM", "instance_index": None, "attributes": {"name": "WEB01"}}
        assert _resource_key(r) == "web01"


class TestGuestKey:
    def test_uses_inventory_name(self):
        assert _guest_key({"inventory_name": "web01", "hostname": "web01.lab"}) == "web01"

    def test_short_hostname(self):
        assert _guest_key({"hostname": "db01.lab.example.com"}) == "db01"

    def test_empty(self):
        assert _guest_key({}) is None


# ===========================================================================
# Comparison report
# ===========================================================================

class TestComparisonReport:
    def test_returns_string(self):
        assert isinstance(generate_comparison_report(_base_assessment()), str)

    def test_header(self):
        r = generate_comparison_report(_base_assessment())
        assert "Declared vs Configured vs Observed" in r
        assert "pve01.lab" in r

    def test_state_layer_sources(self):
        r = generate_comparison_report(_assessment_with_all_layers())
        assert "State Layer Sources" in r
        assert "terraform" in r
        assert "ansible" in r

    def test_summary_section(self):
        r = generate_comparison_report(_assessment_with_all_layers())
        assert "Summary" in r
        assert "Declared resources" in r

    def test_matched_section(self):
        r = generate_comparison_report(_assessment_with_all_layers())
        assert "Matched Resources" in r
        assert "web01" in r
        assert "db01" in r

    def test_declared_only_section(self):
        r = generate_comparison_report(_assessment_with_all_layers())
        assert "Declared but Not Observed" in r
        assert "ghost_vm" in r

    def test_observed_only_section(self):
        r = generate_comparison_report(_assessment_with_all_layers())
        assert "Observed but Not Declared" in r
        assert "mystery_host" in r

    def test_all_declared_resources_table(self):
        r = generate_comparison_report(_assessment_with_all_layers())
        assert "All Declared Resources" in r
        assert "proxmox_vm_qemu" in r

    def test_no_recommendations(self):
        r = generate_comparison_report(_assessment_with_all_layers()).lower()
        for word in ("recommend", "upgrade", "replace", "should", "consider", "suggest"):
            assert word not in r, f"Found forbidden word: {word}"

    def test_empty_assessment_no_crash(self):
        r = generate_comparison_report(_base_assessment())
        assert "Declared vs Configured vs Observed" in r


# ===========================================================================
# CLI
# ===========================================================================

def _capture(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn()
    return rc, buf.getvalue()


class TestCLIOpenTofuIngest:
    def test_ingest_stdout(self, tmp_path):
        state_f = _write_state(tmp_path, PROXMOX_STATE)
        args = build_parser().parse_args(["opentofu-ingest", "--state", str(state_f)])
        rc, out = _capture(lambda: cmd_opentofu_ingest(args))
        assert rc == 0
        data = json.loads(out)
        assert len(data["declared_resources"]) == 6

    def test_ingest_to_file(self, tmp_path):
        state_f = _write_state(tmp_path, PROXMOX_STATE)
        out_f = tmp_path / "assessment.json"
        args = build_parser().parse_args([
            "opentofu-ingest", "--state", str(state_f), "--output", str(out_f)
        ])
        rc, _ = _capture(lambda: cmd_opentofu_ingest(args))
        assert rc == 0
        data = json.loads(out_f.read_text())
        assert len(data["declared_resources"]) == 6

    def test_ingest_merges_with_existing(self, tmp_path):
        state_f = _write_state(tmp_path, MINIMAL_STATE)
        existing_f = tmp_path / "existing.json"
        base = {**_base_assessment(), "hardware": {"cpu": {"model": "Intel Xeon"}}}
        existing_f.write_text(json.dumps(base))
        args = build_parser().parse_args([
            "opentofu-ingest", "--state", str(state_f),
            "--input", str(existing_f),
        ])
        rc, out = _capture(lambda: cmd_opentofu_ingest(args))
        assert rc == 0
        data = json.loads(out)
        assert data["hardware"]["cpu"]["model"] == "Intel Xeon"

    def test_ingest_missing_state_fails(self, tmp_path):
        args = build_parser().parse_args([
            "opentofu-ingest", "--state", str(tmp_path / "missing.tfstate")
        ])
        rc, _ = _capture(lambda: cmd_opentofu_ingest(args))
        assert rc == 1

    def test_ingest_reports_count(self, tmp_path, capsys):
        state_f = _write_state(tmp_path, PROXMOX_STATE)
        out_f = tmp_path / "a.json"
        args = build_parser().parse_args([
            "opentofu-ingest", "--state", str(state_f), "--output", str(out_f)
        ])
        cmd_opentofu_ingest(args)
        out = capsys.readouterr().out
        assert "6" in out


class TestCLICompare:
    def _make_assessment_file(self, tmp_path, state_path):
        a = _assessment_with_all_layers()
        f = tmp_path / "assessment.json"
        f.write_text(json.dumps(a))
        return f

    def test_compare_stdout(self, tmp_path):
        f = self._make_assessment_file(tmp_path, None)
        args = build_parser().parse_args(["compare", "--input", str(f)])
        rc, out = _capture(lambda: cmd_compare(args))
        assert rc == 0
        assert "Declared vs Configured vs Observed" in out

    def test_compare_to_file(self, tmp_path):
        f = self._make_assessment_file(tmp_path, None)
        out_f = tmp_path / "compare.md"
        args = build_parser().parse_args(["compare", "--input", str(f), "--output", str(out_f)])
        rc, _ = _capture(lambda: cmd_compare(args))
        assert rc == 0
        assert out_f.exists()
        assert "Declared vs Configured vs Observed" in out_f.read_text()

    def test_compare_shows_matches(self, tmp_path):
        f = self._make_assessment_file(tmp_path, None)
        args = build_parser().parse_args(["compare", "--input", str(f)])
        rc, out = _capture(lambda: cmd_compare(args))
        assert "web01" in out
        assert "ghost_vm" in out
