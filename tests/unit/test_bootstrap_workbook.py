#!/usr/bin/env python3
"""
Tests for bootstrap workbook registry helpers and HTML workbook generation.

Covers:
  - registry_ip_for_bootstrap_vm(): DNS registry lookup for infra-bootstrap VM
  - registry_iso_path(): ISO path derivation from base_images + storage_config
  - build_bootstrap_workbook_html(): Stage 03 pre-population from registries

NOTE: The ODS workbook (workbook.py) is deprecated. Tests now use
html_bootstrap.py — the active output format.
"""

import unittest

from html_bootstrap import (
    build_bootstrap_workbook_html,
    registry_ip_for_bootstrap_vm,
    registry_iso_path,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DNS_ENTRIES = [
    {"hostname": "pve01.internal", "ip": "192.168.1.10", "vmid": None, "role": "proxmox-host"},
    {"hostname": "infra-bootstrap.internal", "ip": "192.168.1.20", "vmid": 100,
     "role": "infra-bootstrap"},
    {"hostname": "forgejo.internal", "ip": "192.168.1.21", "vmid": 101, "role": "forgejo"},
]

BASE_IMAGES = [
    {
        "name": "ubuntu-2204-base",
        "source_iso": "ubuntu-22.04.4-live-server-amd64.iso",
        "source_url": "https://releases.ubuntu.com/22.04/ubuntu-22.04.4-live-server-amd64.iso",
        "checksum": "sha256:abc123",
        "created_at": "2026-04-01T10:00:00Z",
    }
]

STORAGE_CONFIG = {
    "snippets": "local:snippets",
    "isos": "local:iso",
    "vm_disks": "local-zfs",
}

MINIMAL_MANIFEST = {
    "host": {"hostname": "pve01", "fqdn": "pve01.internal"},
}

FULL_MANIFEST = {
    "host": {"hostname": "pve01", "fqdn": "pve01.internal"},
    "dns_registry": DNS_ENTRIES,
    "base_images": BASE_IMAGES,
    "bootstrap_state_storage": STORAGE_CONFIG,
}

META = {
    "generated_at": "2026-06-01T00:00:00Z",
    "generated_at_display": "2026-06-01 00:00:00 UTC",
}


# ---------------------------------------------------------------------------
# registry_ip_for_bootstrap_vm
# ---------------------------------------------------------------------------

class TestRegistryIpForBootstrapVm(unittest.TestCase):

    def test_returns_ip_by_role(self):
        manifest = {"dns_registry": DNS_ENTRIES}
        self.assertEqual(registry_ip_for_bootstrap_vm(manifest), "192.168.1.20")

    def test_returns_ip_by_hostname_prefix(self):
        entries = [{"hostname": "infra-bootstrap.internal", "ip": "10.0.0.5",
                    "vmid": None, "role": "other"}]
        manifest = {"dns_registry": entries}
        self.assertEqual(registry_ip_for_bootstrap_vm(manifest), "10.0.0.5")

    def test_fallback_to_vmid_100(self):
        entries = [{"hostname": "bootstrap.internal", "ip": "10.0.0.9",
                    "vmid": 100, "role": "custom-role"}]
        manifest = {"dns_registry": entries}
        self.assertEqual(registry_ip_for_bootstrap_vm(manifest), "10.0.0.9")

    def test_returns_none_when_no_registry(self):
        self.assertIsNone(registry_ip_for_bootstrap_vm({}))

    def test_returns_none_when_empty_registry(self):
        self.assertIsNone(registry_ip_for_bootstrap_vm({"dns_registry": []}))

    def test_returns_none_when_no_matching_entry(self):
        entries = [{"hostname": "forgejo.internal", "ip": "192.168.1.21",
                    "vmid": 101, "role": "forgejo"}]
        self.assertIsNone(registry_ip_for_bootstrap_vm({"dns_registry": entries}))

    def test_skips_entry_with_no_ip(self):
        entries = [
            {"hostname": "infra-bootstrap.internal", "ip": None, "vmid": 100,
             "role": "infra-bootstrap"},
            {"hostname": "infra-bootstrap-v2.internal", "ip": "10.0.0.99",
             "vmid": 200, "role": "infra-bootstrap"},
        ]
        result = registry_ip_for_bootstrap_vm({"dns_registry": entries})
        self.assertEqual(result, "10.0.0.99")


# ---------------------------------------------------------------------------
# registry_iso_path
# ---------------------------------------------------------------------------

class TestRegistryIsoPath(unittest.TestCase):

    def test_builds_path_from_base_image_and_storage(self):
        manifest = {"base_images": BASE_IMAGES, "bootstrap_state_storage": STORAGE_CONFIG}
        self.assertEqual(registry_iso_path(manifest),
                         "local:iso/ubuntu-22.04.4-live-server-amd64.iso")

    def test_defaults_isos_store_when_storage_config_absent(self):
        manifest = {"base_images": BASE_IMAGES}
        result = registry_iso_path(manifest)
        self.assertEqual(result, "local:iso/ubuntu-22.04.4-live-server-amd64.iso")

    def test_uses_storage_config_key(self):
        manifest = {
            "base_images": BASE_IMAGES,
            "bootstrap_state_storage": {"isos": "cephfs:iso"},
        }
        self.assertEqual(registry_iso_path(manifest),
                         "cephfs:iso/ubuntu-22.04.4-live-server-amd64.iso")

    def test_returns_none_when_no_base_images(self):
        self.assertIsNone(registry_iso_path({}))
        self.assertIsNone(registry_iso_path({"base_images": []}))

    def test_returns_none_when_source_iso_missing(self):
        manifest = {"base_images": [{"name": "ubuntu-2204-base"}]}
        self.assertIsNone(registry_iso_path(manifest))


# ---------------------------------------------------------------------------
# build_bootstrap_workbook_html — Stage 03 registry pre-population
# ---------------------------------------------------------------------------

class TestHtmlBootstrapWorkbookStage03(unittest.TestCase):

    def _html(self, manifest):
        return build_bootstrap_workbook_html(manifest, META)

    def test_returns_valid_html(self):
        html = self._html(FULL_MANIFEST)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("</html>", html)

    def test_ip_pre_populated_from_dns_registry(self):
        html = self._html(FULL_MANIFEST)
        self.assertIn("192.168.1.20", html)

    def test_iso_path_pre_populated_from_template_registry(self):
        html = self._html(FULL_MANIFEST)
        self.assertIn("ubuntu-22.04.4-live-server-amd64.iso", html)

    def test_ssh_check_uses_real_ip(self):
        html = self._html(FULL_MANIFEST)
        self.assertIn("ssh ubuntu@192.168.1.20", html)
        self.assertNotIn("ssh ubuntu@[VM_IP]", html)

    def test_fallback_to_placeholder_without_registry(self):
        html = self._html(MINIMAL_MANIFEST)
        self.assertIn("[VM_IP]", html)

    def test_no_crash_with_empty_dns_registry(self):
        manifest = {**MINIMAL_MANIFEST, "dns_registry": []}
        html = self._html(manifest)
        self.assertIn("<!DOCTYPE html>", html)

    def test_no_crash_with_empty_base_images(self):
        manifest = {**MINIMAL_MANIFEST, "base_images": []}
        html = self._html(manifest)
        self.assertIn("<!DOCTYPE html>", html)

    def test_stage_03_section_present(self):
        html = self._html(FULL_MANIFEST)
        self.assertIn("Stage 03", html)

    def test_partial_registry_dns_only(self):
        manifest = {**MINIMAL_MANIFEST, "dns_registry": DNS_ENTRIES}
        html = self._html(manifest)
        # IP pre-populated from registry
        self.assertIn("192.168.1.20", html)
        # No base_images → no ISO path rendered
        self.assertNotIn("ubuntu-22.04.4", html)

    def test_partial_registry_templates_only(self):
        manifest = {
            **MINIMAL_MANIFEST,
            "base_images": BASE_IMAGES,
            "bootstrap_state_storage": STORAGE_CONFIG,
        }
        html = self._html(manifest)
        self.assertIn("ubuntu-22.04.4-live-server-amd64.iso", html)
        self.assertIn("[VM_IP]", html)

    def test_checkboxes_present(self):
        html = self._html(FULL_MANIFEST)
        self.assertIn('type="checkbox"', html)

    def test_self_contained(self):
        html = self._html(FULL_MANIFEST)
        self.assertNotIn("cdn.", html)


if __name__ == "__main__":
    unittest.main()
