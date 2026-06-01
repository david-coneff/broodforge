"""
test_forge_workbook.py — Tests for Phase 1.F.3: forge_workbook.py
"""

import io
import json
import sys
import os
import zipfile

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "proxmox-bootstrap"))

import forge_workbook as _fw
from forge_validator import ForgeValidationFinding


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _manifest(
    hostname="pve01",
    domain="home.example.com",
    profile="lan",
    setup_mode="autonomous",
    wan_config=None,
    timezone=None,
):
    m = {
        "schema_version": "1.0",
        "cell_id": f"{hostname}-cell",
        "generated_at": "2026-06-01T12:00:00+00:00",
        "setup_mode": setup_mode,
        "host_identity": {
            "hostname": hostname,
            "domain": domain,
            "fqdn": f"{hostname}.{domain}",
            "cell_id": f"{hostname}-cell",
        },
        "network_topology": {
            "profile": profile,
            "management_cidr": "192.168.1.0/24",
            "gateway": "192.168.1.1",
        },
    }
    if timezone:
        m["host_identity"]["timezone"] = timezone
    if wan_config:
        m["network_topology"]["wan_config"] = wan_config
    return m


def _hardware():
    return {
        "ram_gb": 32,
        "cpu_model": "Intel Core i7-8700",
        "cpu_cores": 6,
        "hostname": "pve01",
        "disks": [
            {"name": "sda", "size_gb": 500, "model": "SAMSUNG 870 EVO", "rotational": False, "removable": False},
            {"name": "sdb", "size_gb": 500, "model": "SAMSUNG 870 EVO", "rotational": False, "removable": False},
        ],
        "nics": [
            {"name": "enp3s0", "mac": "aa:bb:cc:dd:ee:ff", "speed_mbps": 1000},
        ],
        "derived": {"disk_count": 2, "usable_disks": 2, "ssd_count": 2, "hdd_count": 0},
    }


# ---------------------------------------------------------------------------
# ODS structure tests
# ---------------------------------------------------------------------------

class TestForgeWorkbookStructure:
    def _wb(self, **kw):
        return _fw.build_forge_workbook(_manifest(**kw))

    def test_returns_bytes(self):
        assert isinstance(self._wb(), bytes)

    def test_is_valid_zip(self):
        data = self._wb()
        assert zipfile.is_zipfile(io.BytesIO(data))

    def test_has_mimetype(self):
        data = self._wb()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
        assert "mimetype" in names

    def test_has_content_xml(self):
        data = self._wb()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
        assert "content.xml" in names

    def test_has_seven_sheets(self):
        data = self._wb()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            content = zf.read("content.xml").decode()
        import re
        sheet_names = re.findall(r'table:name="([^"]+)"', content)
        assert len(sheet_names) == 7

    def test_sheet_names(self):
        data = self._wb()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            content = zf.read("content.xml").decode()
        import re
        names = re.findall(r'table:name="([^"]+)"', content)
        assert "Overview" in names
        assert "Hardware" in names
        assert "Storage" in names
        assert "Network" in names
        assert "Identity" in names
        assert "Services" in names
        assert "Validation" in names


# ---------------------------------------------------------------------------
# Overview sheet
# ---------------------------------------------------------------------------

class TestOverviewSheet:
    def _content(self, **kw):
        data = _fw.build_forge_workbook(_manifest(**kw))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.read("content.xml").decode()

    def test_hostname_in_content(self):
        content = self._content(hostname="pve01")
        assert "pve01" in content

    def test_cell_id_in_content(self):
        content = self._content(hostname="pve01")
        assert "pve01-cell" in content

    def test_domain_in_content(self):
        content = self._content(domain="home.example.com")
        assert "home.example.com" in content

    def test_setup_mode_in_content(self):
        content = self._content(setup_mode="group-manual")
        assert "group-manual" in content

    def test_timezone_shown_when_present(self):
        content = self._content(timezone="America/Denver")
        assert "America/Denver" in content

    def test_warnings_shown_when_present(self):
        m = _manifest()
        m["setup_warnings"] = ["CIDR overlap: 10.0.0.0/8 vs 10.96.0.0/12"]
        data = _fw.build_forge_workbook(m)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            content = zf.read("content.xml").decode()
        assert "CIDR overlap" in content

    def test_wan_config_in_content(self):
        wan = {
            "dns_provider": "cloudflare",
            "headscale_url": "https://pve01.home.example.com:8080",
            "tls_provider": "certbot",
        }
        content = self._content(profile="wan", wan_config=wan)
        assert "cloudflare" in content
        assert "certbot" in content


# ---------------------------------------------------------------------------
# Hardware sheet
# ---------------------------------------------------------------------------

class TestHardwareSheet:
    def _content(self, hw=None, findings=None):
        data = _fw.build_forge_workbook(
            _manifest(), hardware_profile=hw or _hardware(), validation_findings=findings
        )
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.read("content.xml").decode()

    def test_ram_shown(self):
        assert "32" in self._content()

    def test_disk_names_shown(self):
        c = self._content()
        assert "sda" in c
        assert "sdb" in c

    def test_nic_shown(self):
        assert "enp3s0" in self._content()

    def test_no_hardware_profile_message(self):
        data = _fw.build_forge_workbook(_manifest(), hardware_profile=None)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            content = zf.read("content.xml").decode()
        assert "No hardware profile" in content or "not yet collected" in content

    def test_red_finding_shown(self):
        findings = [ForgeValidationFinding("RED", "ram_gb", "Not enough RAM", 8, 16)]
        c = self._content(findings=findings)
        assert "RED" in c
        assert "ram_gb" in c

    def test_yellow_finding_shown(self):
        findings = [ForgeValidationFinding("YELLOW", "nics", "Only 1 NIC", 1, 2)]
        c = self._content(findings=findings)
        assert "YELLOW" in c


# ---------------------------------------------------------------------------
# Storage sheet
# ---------------------------------------------------------------------------

class TestStorageSheet:
    def _content(self, hw=None):
        data = _fw.build_forge_workbook(_manifest(), hardware_profile=hw or _hardware())
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.read("content.xml").decode()

    def test_zfs_topology_mirror_two_disks(self):
        assert "mirror" in self._content()

    def test_zfs_topology_raidz1_three_disks(self):
        hw = _hardware()
        hw["disks"].append({"name": "sdc", "size_gb": 500, "model": "SSD",
                            "rotational": False, "removable": False})
        c = self._content(hw=hw)
        assert "raidz1" in c

    def test_pool_name_shown(self):
        assert "rpool" in self._content()

    def test_datastore_shown(self):
        assert "local-zfs" in self._content()

    def test_zfs_topology_helper_stripe(self):
        assert "stripe" in _fw._zfs_topology(1)

    def test_zfs_topology_helper_mirror(self):
        assert "mirror" in _fw._zfs_topology(2)

    def test_zfs_topology_helper_raidz1(self):
        assert "raidz1" in _fw._zfs_topology(4)

    def test_zfs_topology_helper_raidz2(self):
        assert "raidz2" in _fw._zfs_topology(6)

    def test_zfs_topology_helper_raidz3(self):
        assert "raidz3" in _fw._zfs_topology(9)

    def test_zfs_topology_helper_zero(self):
        assert "UNAVAILABLE" in _fw._zfs_topology(0)


# ---------------------------------------------------------------------------
# Network sheet
# ---------------------------------------------------------------------------

class TestNetworkSheet:
    def _content(self, **kw):
        data = _fw.build_forge_workbook(_manifest(**kw))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.read("content.xml").decode()

    def test_management_cidr_shown(self):
        assert "192.168.1.0/24" in self._content()

    def test_gateway_shown(self):
        assert "192.168.1.1" in self._content()

    def test_dnsmasq_mentioned(self):
        assert "dnsmasq" in self._content()

    def test_wan_headscale_url_shown(self):
        wan = {"headscale_url": "https://pve01.home.example.com:8080"}
        c = self._content(profile="wan", wan_config=wan)
        assert "https://pve01.home.example.com:8080" in c

    def test_lan_no_headscale(self):
        c = self._content(profile="lan")
        assert "headscale_url" not in c.lower() or "Headscale URL" not in c


# ---------------------------------------------------------------------------
# Validation sheet
# ---------------------------------------------------------------------------

class TestValidationSheet:
    def _content(self):
        data = _fw.build_forge_workbook(_manifest())
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.read("content.xml").decode()

    def test_all_phases_listed(self):
        c = self._content()
        for phase in [
            "phase-00", "phase-01", "phase-02", "phase-03",
            "phase-04", "phase-05", "phase-06", "phase-07", "phase-08",
        ]:
            assert phase in c, f"{phase} not found in content"

    def test_pending_status_initially(self):
        assert "PENDING" in self._content()

    def test_post_forge_checks(self):
        c = self._content()
        assert "kubectl" in c or "k3s node ready" in c

    def test_flux_check_mentioned(self):
        assert "Flux" in self._content() or "flux" in self._content()


# ---------------------------------------------------------------------------
# generate_forge_workbook_file
# ---------------------------------------------------------------------------

class TestGenerateForgeWorkbookFile:
    def test_writes_file(self, tmp_path):
        out = str(tmp_path / "forge-workbook.ods")
        _fw.generate_forge_workbook_file(_manifest(), out)
        assert os.path.exists(out)
        assert os.path.getsize(out) > 100

    def test_file_is_valid_ods(self, tmp_path):
        out = str(tmp_path / "forge-workbook.ods")
        _fw.generate_forge_workbook_file(_manifest(), out)
        assert zipfile.is_zipfile(out)
