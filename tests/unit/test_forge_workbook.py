"""
test_forge_workbook.py — Tests for html_forge_workbook.py (HTML forge workbook).

NOTE: forge_workbook.py (ODS) is deprecated → proxmox-bootstrap/deprecated/.
      The active output format is HTML via html_forge_workbook.py.

Covers functional content assertions: identity, hardware, storage topology,
network info, validation phases — plus HTML structure.
"""

import importlib.util
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

# Load html_forge_workbook via importlib
_spec = importlib.util.spec_from_file_location(
    "html_forge_workbook",
    os.path.join(_ROOT, "proxmox-bootstrap", "html_forge_workbook.py"),
)
_hfw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hfw)
build_forge_workbook_html = _hfw.build_forge_workbook_html

from forge_validator import ForgeValidationFinding

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _hardware():
    return {
        "cpu_model": "Intel Core i9-12900K",
        "cpu_cores": 16,
        "ram_gb": 32,
        "disks": [
            {"name": "sda", "size_gb": 500, "model": "SAMSUNG 870 EVO",
             "rotational": False, "removable": False},
            {"name": "sdb", "size_gb": 500, "model": "SAMSUNG 870 EVO",
             "rotational": False, "removable": False},
        ],
        "nics": [
            {"name": "enp3s0", "mac": "aa:bb:cc:dd:ee:ff", "speed_mbps": 1000},
        ],
        "derived": {"disk_count": 2, "usable_disks": 2, "ssd_count": 2, "hdd_count": 0},
    }


def _manifest(
    hostname="pve01",
    domain="home.example.com",
    profile="lan",
    setup_mode="autonomous",
    wan_config=None,
    timezone=None,
):
    m = {
        "cell_id": f"{hostname}-cell",
        "host_identity": {
            "hostname": hostname,
            "domain": domain,
            "fqdn": f"{hostname}.{domain}",
        },
        "network_topology": {
            "profile": profile,
            "management_cidr": "192.168.1.0/24",
            "gateway": "192.168.1.1",
        },
        "storage_config": {
            # datastore_name must be inside zfs_pool for html_forge_workbook
            "zfs_pool": {"pool_name": "rpool", "topology": "mirror",
                         "datastore_name": "local-zfs"},
        },
        "setup_mode": setup_mode,
    }
    if timezone:
        m.setdefault("vm_defaults", {})["timezone"] = timezone
    if wan_config:
        m["network_topology"]["wan_config"] = wan_config
    return m


def _html(**kw) -> str:
    # Pass hardware_profile explicitly so hardware section populates
    hw = kw.pop("hw", _hardware())
    return build_forge_workbook_html(_manifest(**kw), hardware_profile=hw)


# ---------------------------------------------------------------------------
# HTML structure
# ---------------------------------------------------------------------------

class TestHtmlStructure(unittest.TestCase):
    def test_returns_string(self):
        self.assertIsInstance(_html(), str)

    def test_is_valid_html(self):
        html = _html()
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("</html>", html)

    def test_self_contained(self):
        self.assertNotIn("cdn.", _html())

    def test_has_checkboxes(self):
        self.assertIn('type="checkbox"', _html())


# ---------------------------------------------------------------------------
# Identity / overview content
# ---------------------------------------------------------------------------

class TestIdentityContent(unittest.TestCase):
    def test_hostname_in_content(self):
        self.assertIn("pve01", _html(hostname="pve01"))

    def test_cell_id_in_content(self):
        self.assertIn("pve01-cell", _html(hostname="pve01"))

    def test_domain_in_content(self):
        self.assertIn("home.example.com", _html(domain="home.example.com"))

    def test_setup_mode_in_content(self):
        self.assertIn("group-manual", _html(setup_mode="group-manual"))

    def test_timezone_shown_when_present(self):
        self.assertIn("America/Denver", _html(timezone="America/Denver"))

    def test_warnings_shown_when_present(self):
        m = _manifest()
        m["setup_warnings"] = ["CIDR overlap: 10.0.0.0/8 vs 10.96.0.0/12"]
        html = build_forge_workbook_html(m, hardware_profile=_hardware())
        self.assertIn("CIDR overlap", html)

    def test_wan_config_content(self):
        wan = {"dns_provider": "cloudflare", "headscale_url": "https://pve01.home.example.com:8080",
               "tls_provider": "certbot"}
        html = _html(profile="wan", wan_config=wan)
        self.assertIn("cloudflare", html)
        self.assertIn("certbot", html)


# ---------------------------------------------------------------------------
# Hardware content
# ---------------------------------------------------------------------------

class TestHardwareContent(unittest.TestCase):
    def test_ram_shown(self):
        self.assertIn("32", _html())

    def test_disk_names_shown(self):
        html = _html()
        self.assertIn("sda", html)
        self.assertIn("sdb", html)

    def test_nic_shown(self):
        # HTML workbook shows NIC count not individual NIC name
        self.assertIn("NIC", _html())

    def test_no_hardware_profile_graceful(self):
        html = build_forge_workbook_html(_manifest(), hardware_profile=None)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("not yet collected", html)

    def test_red_finding_shown(self):
        findings = [ForgeValidationFinding("RED", "ram_gb", "Not enough RAM", 8, 16)]
        html = build_forge_workbook_html(_manifest(), hardware_profile=_hardware(),
                                         validation_findings=findings)
        # Finding message appears; severity shown as callout class
        self.assertIn("Not enough RAM", html)
        self.assertIn("error", html.lower())

    def test_yellow_finding_shown(self):
        findings = [ForgeValidationFinding("YELLOW", "nics", "Only 1 NIC detected", 1, 2)]
        html = build_forge_workbook_html(_manifest(), hardware_profile=_hardware(),
                                         validation_findings=findings)
        self.assertIn("Only 1 NIC detected", html)
        self.assertIn("warning", html.lower())


# ---------------------------------------------------------------------------
# Storage content
# ---------------------------------------------------------------------------

class TestStorageContent(unittest.TestCase):
    def test_zfs_topology_mirror_shown(self):
        self.assertIn("mirror", _html())

    def test_pool_name_shown(self):
        self.assertIn("rpool", _html())

    def test_datastore_shown(self):
        self.assertIn("local-zfs", _html())


# ---------------------------------------------------------------------------
# Network content
# ---------------------------------------------------------------------------

class TestNetworkContent(unittest.TestCase):
    def test_management_cidr_shown(self):
        self.assertIn("192.168.1.0/24", _html())

    def test_gateway_shown(self):
        self.assertIn("192.168.1.1", _html())

    def test_dnsmasq_mentioned(self):
        self.assertIn("dnsmasq", _html())

    def test_wan_headscale_url_shown(self):
        wan = {"headscale_url": "https://pve01.home.example.com:8080"}
        html = _html(profile="wan", wan_config=wan)
        self.assertIn("https://pve01.home.example.com:8080", html)


# ---------------------------------------------------------------------------
# Validation / phase listing
# ---------------------------------------------------------------------------

class TestValidationContent(unittest.TestCase):
    def test_all_phases_listed(self):
        html = _html()
        for phase in ["phase-00", "phase-01", "phase-02", "phase-03",
                      "phase-04", "phase-05", "phase-06", "phase-07", "phase-08"]:
            self.assertIn(phase, html, f"{phase} not in HTML output")

    def test_flux_check_mentioned(self):
        self.assertIn("Flux", _html())


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_minimal_manifest_does_not_crash(self):
        html = build_forge_workbook_html({}, hardware_profile=None)
        self.assertIn("<!DOCTYPE html>", html)

    def test_different_hostnames_differ(self):
        h1 = _html(hostname="pve01")
        h2 = _html(hostname="pve99")
        self.assertIn("pve01", h1)
        self.assertIn("pve99", h2)
        self.assertNotIn("pve99", h1)


if __name__ == "__main__":
    unittest.main()
