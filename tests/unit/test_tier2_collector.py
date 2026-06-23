#!/usr/bin/env python3
"""
Tests for Milestone 6.7 — Tier 2 Bootstrap State Collector.

Validates:
  - parse_qm_list: correct parsing of `qm list` output
  - parse_qm_config: key/value extraction, skips comments and pending lines
  - _iso_to_base_image_name: ISO filename → normalized name
  - _infer_template_name: extract template name from VM description/notes
  - _extract_iso_name: find ISO in template config fields
  - collect_templates / collect_provenance_records: integration with mocked SSH
  - merge_into_state: existing entries preserved, new entries appended, correct counts
  - Dry-run: correct JSON printed, state file not modified
  - CLI argument parsing

Run: py -3 tests/unit/test_tier2_collector.py
"""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from collect_tier2 import (
    SSHClient,
    _extract_iso_name,
    _infer_template_name,
    _iso_to_base_image_name,
    _merge_list_by_key,
    build_arg_parser,
    collect_provenance_records,
    collect_templates,
    load_state,
    main,
    merge_into_state,
    parse_qm_config,
    parse_qm_list,
    save_state,
)

# ===========================================================================
# Fixtures — raw qm output strings
# ===========================================================================

QM_LIST_OUTPUT = """\
      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID
       100 forgejo              running    2048              50.00 1234
       101 operations           running    2048              20.00 1235
       110 k3s-server-01        running    4096              80.00 1236
      9000 ubuntu-2204-base     stopped    2048              20.00 0
"""

QM_LIST_ONLY_TEMPLATE = """\
      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID
      9000 ubuntu-2204-base     stopped    2048              20.00 0
"""

QM_LIST_EMPTY = """\
      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID
"""

QM_CONFIG_TEMPLATE = """\
boot: order=scsi0
cores: 2
cpu: x86-64-v2-AES
description: template: ubuntu-2204-base\\nsource: ubuntu-22.04.4-live-server-amd64.iso
ide2: local:iso/ubuntu-22.04.4-live-server-amd64.iso,media=cdrom
memory: 2048
name: ubuntu-2204-base
ostype: l26
scsi0: local-lvm:vm-9000-disk-0,size=20G
scsihw: virtio-scsi-pci
template: 1
"""

QM_CONFIG_TEMPLATE_NO_ISO = """\
boot: order=scsi0
cores: 2
memory: 2048
name: ubuntu-2204-base
ostype: l26
scsi0: local-lvm:vm-9000-disk-0,size=20G
template: 1
"""

QM_CONFIG_VM = """\
boot: order=scsi0
cores: 2
description: template: ubuntu-2204-base\\ndeployed by: ansible
memory: 2048
name: forgejo
ostype: l26
scsi0: local-lvm:vm-100-disk-0,size=50G
"""

QM_CONFIG_VM_NO_TEMPLATE = """\
boot: order=scsi0
cores: 2
memory: 2048
name: operations
ostype: l26
scsi0: local-lvm:vm-101-disk-0,size=20G
"""

STAT_OUTPUT_EPOCH = "1713168000\n"  # 2024-04-15T08:00:00Z


# ===========================================================================
# TestParseQmList
# ===========================================================================

class TestParseQmList(unittest.TestCase):
    def test_parses_running_vms(self):
        vms = parse_qm_list(QM_LIST_OUTPUT)
        self.assertEqual(len(vms), 4)

    def test_vmid_types(self):
        vms = parse_qm_list(QM_LIST_OUTPUT)
        for vm in vms:
            self.assertIsInstance(vm["vmid"], int)

    def test_vm_fields(self):
        vms = parse_qm_list(QM_LIST_OUTPUT)
        forgejo = next(v for v in vms if v["vmid"] == 100)
        self.assertEqual(forgejo["name"], "forgejo")
        self.assertEqual(forgejo["status"], "running")

    def test_template_entry_included(self):
        vms = parse_qm_list(QM_LIST_OUTPUT)
        vmids = [v["vmid"] for v in vms]
        self.assertIn(9000, vmids)

    def test_empty_output(self):
        vms = parse_qm_list(QM_LIST_EMPTY)
        self.assertEqual(vms, [])

    def test_header_line_skipped(self):
        vms = parse_qm_list(QM_LIST_OUTPUT)
        self.assertFalse(any(v["vmid"] == 0 for v in vms))

    def test_blank_lines_skipped(self):
        vms = parse_qm_list("\n\n" + QM_LIST_OUTPUT + "\n\n")
        self.assertEqual(len(vms), 4)


# ===========================================================================
# TestParseQmConfig
# ===========================================================================

class TestParseQmConfig(unittest.TestCase):
    def test_parses_key_value(self):
        config = parse_qm_config(9000, QM_CONFIG_TEMPLATE)
        self.assertEqual(config.get("template"), "1")
        self.assertEqual(config.get("name"), "ubuntu-2204-base")

    def test_skips_comment_lines(self):
        output = "#pending: something\nname: myvm\n"
        config = parse_qm_config(100, output)
        self.assertNotIn("pending", config)
        self.assertEqual(config["name"], "myvm")

    def test_skips_blank_lines(self):
        output = "\n\nname: myvm\n\n"
        config = parse_qm_config(100, output)
        self.assertEqual(config["name"], "myvm")

    def test_value_with_colon(self):
        output = "description: template: ubuntu-2204-base\n"
        config = parse_qm_config(100, output)
        self.assertEqual(config["description"], "template: ubuntu-2204-base")

    def test_is_template(self):
        config = parse_qm_config(9000, QM_CONFIG_TEMPLATE)
        self.assertEqual(config.get("template"), "1")

    def test_is_not_template(self):
        config = parse_qm_config(100, QM_CONFIG_VM)
        self.assertNotEqual(config.get("template"), "1")


# ===========================================================================
# TestIsoToBaseImageName
# ===========================================================================

class TestIsoToBaseImageName(unittest.TestCase):
    def test_ubuntu_iso(self):
        self.assertEqual(
            _iso_to_base_image_name("ubuntu-22.04.4-live-server-amd64.iso"),
            "ubuntu-2204-base"
        )

    def test_debian_iso(self):
        self.assertEqual(
            _iso_to_base_image_name("debian-12.5.0-amd64-netinst.iso"),
            "debian-12-base"
        )

    def test_talos_iso(self):
        self.assertEqual(
            _iso_to_base_image_name("talos-v1.7.0-metal-amd64.iso"),
            "talos-17-base"
        )

    def test_unknown_iso_fallback(self):
        result = _iso_to_base_image_name("custom-os-x86.iso")
        self.assertTrue(result.endswith("-base"))

    def test_short_ubuntu_version(self):
        result = _iso_to_base_image_name("ubuntu-20.04.6-live-server-amd64.iso")
        self.assertEqual(result, "ubuntu-2004-base")


# ===========================================================================
# TestInferTemplateName
# ===========================================================================

class TestInferTemplateName(unittest.TestCase):
    def test_found_in_description(self):
        config = {"description": "template: ubuntu-2204-base\nsome other info"}
        self.assertEqual(_infer_template_name(config), "ubuntu-2204-base")

    def test_found_in_notes(self):
        config = {"notes": "template: ubuntu-2204-base"}
        self.assertEqual(_infer_template_name(config), "ubuntu-2204-base")

    def test_not_found_returns_none(self):
        config = {"description": "no template info here"}
        self.assertIsNone(_infer_template_name(config))

    def test_empty_config_returns_none(self):
        self.assertIsNone(_infer_template_name({}))

    def test_case_insensitive_key(self):
        config = {"description": "Template: ubuntu-2204-base"}
        self.assertEqual(_infer_template_name(config), "ubuntu-2204-base")


# ===========================================================================
# TestExtractIsoName
# ===========================================================================

class TestExtractIsoName(unittest.TestCase):
    def test_found_in_ide2(self):
        config = {"ide2": "local:iso/ubuntu-22.04.4-live-server-amd64.iso,media=cdrom"}
        result = _extract_iso_name(config)
        self.assertEqual(result, "ubuntu-22.04.4-live-server-amd64.iso")

    def test_found_in_description(self):
        config = {"description": "source: ubuntu-22.04.4-live-server-amd64.iso"}
        result = _extract_iso_name(config)
        self.assertEqual(result, "ubuntu-22.04.4-live-server-amd64.iso")

    def test_not_found_returns_none(self):
        config = {"name": "mytemplate", "memory": "2048"}
        self.assertIsNone(_extract_iso_name(config))

    def test_found_in_sata0(self):
        config = {"sata0": "local:iso/debian-12.5.0-amd64.iso,media=cdrom"}
        result = _extract_iso_name(config)
        self.assertEqual(result, "debian-12.5.0-amd64.iso")


# ===========================================================================
# TestMergeListByKey
# ===========================================================================

class TestMergeListByKey(unittest.TestCase):
    def test_adds_new_entry(self):
        existing = [{"vmid": 100, "name": "forgejo"}]
        incoming = [{"vmid": 101, "name": "operations"}]
        merged, added = _merge_list_by_key(existing, incoming, "vmid")
        self.assertEqual(added, 1)
        self.assertEqual(len(merged), 2)

    def test_does_not_duplicate_existing(self):
        existing = [{"vmid": 100, "name": "forgejo"}]
        incoming = [{"vmid": 100, "name": "forgejo-new"}]
        merged, added = _merge_list_by_key(existing, incoming, "vmid")
        self.assertEqual(added, 0)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["name"], "forgejo")  # original preserved

    def test_empty_existing(self):
        incoming = [{"vmid": 100}]
        merged, added = _merge_list_by_key([], incoming, "vmid")
        self.assertEqual(added, 1)
        self.assertEqual(len(merged), 1)

    def test_empty_incoming(self):
        existing = [{"vmid": 100}]
        merged, added = _merge_list_by_key(existing, [], "vmid")
        self.assertEqual(added, 0)
        self.assertEqual(len(merged), 1)

    def test_multiple_adds(self):
        existing = [{"name": "a"}]
        incoming = [{"name": "b"}, {"name": "c"}]
        merged, added = _merge_list_by_key(existing, incoming, "name")
        self.assertEqual(added, 2)
        self.assertEqual(len(merged), 3)


# ===========================================================================
# TestMergeIntoState
# ===========================================================================

class TestMergeIntoState(unittest.TestCase):
    def _sample_provenance(self, vmid):
        return {"vmid": vmid, "name": f"vm-{vmid}", "deployed_at": "2026-01-01T00:00:00Z"}

    def _sample_template(self, tmpl_id):
        return {"name": f"tmpl-{tmpl_id}", "proxmox_template_id": tmpl_id,
                "base_image": "ubuntu-2204-base", "created_at": "2026-01-01T00:00:00Z"}

    def _sample_base_image(self, name):
        return {"name": name, "source_iso": f"{name}.iso", "created_at": "2026-01-01T00:00:00Z"}

    def test_all_new_entries_added(self):
        state = {}
        updated, summary = merge_into_state(
            state,
            [self._sample_provenance(100)],
            [self._sample_template(9000)],
            [self._sample_base_image("ubuntu-2204-base")],
        )
        self.assertEqual(summary["provenance_records_added"], 1)
        self.assertEqual(summary["templates_added"], 1)
        self.assertEqual(summary["base_images_added"], 1)

    def test_existing_entries_not_overwritten(self):
        state = {
            "provenance_records": [{"vmid": 100, "name": "forgejo", "tofu_commit": "abc123"}],
            "templates": [],
            "base_images": [],
        }
        incoming_prov = [{"vmid": 100, "name": "forgejo-renamed", "tofu_commit": "NEW"}]
        updated, summary = merge_into_state(state, incoming_prov, [], [])

        self.assertEqual(summary["provenance_records_added"], 0)
        # Original entry must be untouched
        self.assertEqual(updated["provenance_records"][0]["name"], "forgejo")
        self.assertEqual(updated["provenance_records"][0]["tofu_commit"], "abc123")

    def test_totals_correct(self):
        state = {
            "provenance_records": [self._sample_provenance(100)],
            "templates": [self._sample_template(9000)],
            "base_images": [self._sample_base_image("ubuntu-2204-base")],
        }
        incoming_prov = [self._sample_provenance(101)]
        updated, summary = merge_into_state(state, incoming_prov, [], [])
        self.assertEqual(summary["provenance_records_total"], 2)
        self.assertEqual(summary["templates_total"], 1)
        self.assertEqual(summary["base_images_total"], 1)

    def test_original_state_not_mutated(self):
        state = {"provenance_records": [self._sample_provenance(100)]}
        orig_len = len(state["provenance_records"])
        merge_into_state(state, [self._sample_provenance(101)], [], [])
        self.assertEqual(len(state["provenance_records"]), orig_len)

    def test_missing_arrays_treated_as_empty(self):
        state = {"cell_id": "test-cell"}  # no provenance_records etc.
        updated, summary = merge_into_state(
            state,
            [self._sample_provenance(100)],
            [self._sample_template(9000)],
            [self._sample_base_image("ubuntu-2204-base")],
        )
        self.assertEqual(summary["provenance_records_added"], 1)
        self.assertIn("provenance_records", updated)


# ===========================================================================
# TestCollectTemplates — mocked SSH
# ===========================================================================

def _make_ssh_mock(responses: dict):
    """Return a mock SSHClient whose run() returns responses keyed by command substring."""
    mock = MagicMock(spec=SSHClient)
    def _run(cmd):
        for key, val in responses.items():
            if key in cmd:
                return val
        return ""
    mock.run.side_effect = _run
    return mock


class TestCollectTemplates(unittest.TestCase):
    def test_detects_template_vmid(self):
        ssh = _make_ssh_mock({
            "qm list": QM_LIST_ONLY_TEMPLATE,
            "qm config 9000": QM_CONFIG_TEMPLATE,
            "stat": STAT_OUTPUT_EPOCH,
        })
        templates, base_images = collect_templates(ssh)
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]["proxmox_template_id"], 9000)
        self.assertEqual(templates[0]["name"], "ubuntu-2204-base")

    def test_extracts_base_image_from_iso(self):
        ssh = _make_ssh_mock({
            "qm list": QM_LIST_ONLY_TEMPLATE,
            "qm config 9000": QM_CONFIG_TEMPLATE,
            "stat": STAT_OUTPUT_EPOCH,
        })
        templates, base_images = collect_templates(ssh)
        self.assertEqual(len(base_images), 1)
        self.assertIn("ubuntu-22.04.4-live-server-amd64.iso", base_images[0]["source_iso"])

    def test_no_base_image_when_no_iso(self):
        ssh = _make_ssh_mock({
            "qm list": QM_LIST_ONLY_TEMPLATE,
            "qm config 9000": QM_CONFIG_TEMPLATE_NO_ISO,
            "stat": STAT_OUTPUT_EPOCH,
        })
        templates, base_images = collect_templates(ssh)
        self.assertEqual(len(templates), 1)
        self.assertEqual(len(base_images), 0)

    def test_non_template_vms_excluded(self):
        ssh = _make_ssh_mock({
            "qm list": QM_LIST_OUTPUT,
            "qm config 100": QM_CONFIG_VM,
            "qm config 101": QM_CONFIG_VM_NO_TEMPLATE,
            "qm config 110": QM_CONFIG_VM,
            "qm config 9000": QM_CONFIG_TEMPLATE,
            "stat": STAT_OUTPUT_EPOCH,
        })
        templates, _ = collect_templates(ssh)
        vmids = [t["proxmox_template_id"] for t in templates]
        self.assertIn(9000, vmids)
        self.assertNotIn(100, vmids)
        self.assertNotIn(101, vmids)
        self.assertNotIn(110, vmids)


class TestCollectProvenanceRecords(unittest.TestCase):
    def test_collects_non_template_vms(self):
        ssh = _make_ssh_mock({
            "qm list": QM_LIST_OUTPUT,
            "qm config 100": QM_CONFIG_VM,
            "qm config 101": QM_CONFIG_VM_NO_TEMPLATE,
            "qm config 110": QM_CONFIG_VM,
            "qm config 9000": QM_CONFIG_TEMPLATE,
            "stat": STAT_OUTPUT_EPOCH,
        })
        records = collect_provenance_records(ssh)
        vmids = [r["vmid"] for r in records]
        self.assertIn(100, vmids)
        self.assertIn(101, vmids)
        self.assertIn(110, vmids)
        self.assertNotIn(9000, vmids)

    def test_template_name_populated_from_description(self):
        ssh = _make_ssh_mock({
            "qm list": "      VMID NAME   STATUS\n       100 forgejo running\n",
            "qm config 100": QM_CONFIG_VM,
            "stat": STAT_OUTPUT_EPOCH,
        })
        records = collect_provenance_records(ssh)
        self.assertEqual(records[0]["template_name"], "ubuntu-2204-base")

    def test_template_name_none_when_absent(self):
        ssh = _make_ssh_mock({
            "qm list": "      VMID NAME   STATUS\n       101 operations running\n",
            "qm config 101": QM_CONFIG_VM_NO_TEMPLATE,
            "stat": STAT_OUTPUT_EPOCH,
        })
        records = collect_provenance_records(ssh)
        self.assertIsNone(records[0]["template_name"])

    def test_required_fields_present(self):
        ssh = _make_ssh_mock({
            "qm list": "      VMID NAME   STATUS\n       100 forgejo running\n",
            "qm config 100": QM_CONFIG_VM,
            "stat": STAT_OUTPUT_EPOCH,
        })
        records = collect_provenance_records(ssh)
        r = records[0]
        for field in ("vmid", "name", "deployed_at", "tofu_workspace",
                      "tofu_commit", "template_name", "ansible_commit", "deployed_by"):
            self.assertIn(field, r, msg=f"provenance record missing field: {field}")


# ===========================================================================
# TestStateFileIO
# ===========================================================================

class TestStateFileIO(unittest.TestCase):
    def test_load_existing_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"cell_id": "test"}, f)
            path = Path(f.name)
        try:
            state = load_state(path)
            self.assertEqual(state["cell_id"], "test")
        finally:
            path.unlink()

    def test_load_missing_file_returns_empty(self):
        state = load_state(Path("/nonexistent/bootstrap-state.json"))
        self.assertEqual(state, {})

    def test_save_and_reload(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = Path(f.name)
        try:
            save_state(path, {"cell_id": "saved"})
            reloaded = load_state(path)
            self.assertEqual(reloaded["cell_id"], "saved")
        finally:
            path.unlink()


# ===========================================================================
# TestDryRun
# ===========================================================================

class TestDryRun(unittest.TestCase):
    def _run_main_dry(self, state_content: dict) -> tuple[str, dict]:
        """Run main() in --dry-run mode and return (stdout_output, final_state_dict)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(state_content, f)
            state_path = Path(f.name)

        captured = io.StringIO()
        original_stdout = sys.stdout

        ssh_responses = {
            "qm list": QM_LIST_ONLY_TEMPLATE,
            "qm config 9000": QM_CONFIG_TEMPLATE,
            "stat": STAT_OUTPUT_EPOCH,
            "echo ok": "ok\n",
        }

        try:
            with patch("collect_tier2.SSHClient") as MockSSH:
                instance = MockSSH.return_value
                instance.test_connection.return_value = True
                instance.run.side_effect = lambda cmd: next(
                    (v for k, v in ssh_responses.items() if k in cmd), ""
                )
                sys.stdout = captured
                main([
                    "--host", "192.168.1.10",
                    "--state", str(state_path),
                    "--dry-run",
                ])
        finally:
            sys.stdout = original_stdout

        final_state = load_state(state_path)
        state_path.unlink()
        return captured.getvalue(), final_state

    def test_dry_run_does_not_modify_file(self):
        original = {"cell_id": "test", "templates": [], "base_images": []}
        _, final_state = self._run_main_dry(original)
        self.assertEqual(final_state["cell_id"], "test")
        self.assertEqual(final_state["templates"], [])

    def test_dry_run_prints_json(self):
        output, _ = self._run_main_dry({})
        self.assertIn('"templates"', output)

    def test_dry_run_prints_dry_run_label(self):
        output, _ = self._run_main_dry({})
        self.assertIn("dry-run", output.lower())


# ===========================================================================
# TestArgParser
# ===========================================================================

class TestArgParser(unittest.TestCase):
    def _parse(self, args):
        return build_arg_parser().parse_args(args)

    def test_host_required(self):
        with self.assertRaises(SystemExit):
            self._parse([])

    def test_defaults(self):
        args = self._parse(["--host", "192.168.1.10"])
        self.assertEqual(args.host, "192.168.1.10")
        self.assertEqual(args.user, "root")
        self.assertEqual(args.port, 22)
        self.assertIsNone(args.key)
        self.assertFalse(args.dry_run)
        self.assertFalse(args.verbose)

    def test_all_flags(self):
        args = self._parse([
            "--host", "10.0.0.1",
            "--user", "dave",
            "--port", "2222",
            "--key", "/home/dave/.ssh/id_ed25519",
            "--state", "/tmp/bs.json",
            "--dry-run",
            "--verbose",
        ])
        self.assertEqual(args.user, "dave")
        self.assertEqual(args.port, 2222)
        self.assertEqual(args.key, "/home/dave/.ssh/id_ed25519")
        self.assertTrue(args.dry_run)
        self.assertTrue(args.verbose)


if __name__ == "__main__":
    unittest.main(verbosity=2)
