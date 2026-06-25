"""
test_phase13_hardware_platform.py — Tests for Phase 13: Hardware and Platform State.

Covers:
  13.1  data-model/hardware-state-schema.json
  13.2  hardware_state_collector.py — parsers, dataclasses, compute_hardware_health
  13.3  data-model/platform-state-schema.json
  13.4  platform_state_collector.py — parsers, dataclasses, compute_platform_health
  13.7  readiness.py — _score_hardware_state_completeness, _score_platform_state_completeness
"""

import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

import hardware_state_collector as _hw
import platform_state_collector as _ps

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_LSBLK_JSON = json.dumps({
    "blockdevices": [
        {"name": "sda", "size": "500107862016", "model": "SAMSUNG 870 EVO",
         "serial": "S1234567", "rota": False, "rm": False, "tran": "sata",
         "fstype": None, "pttype": "gpt", "type": "disk"},
        {"name": "sdb", "size": "500107862016", "model": "SAMSUNG 870 EVO",
         "serial": "S7654321", "rota": False, "rm": False, "tran": "sata",
         "fstype": None, "pttype": "gpt", "type": "disk"},
        {"name": "sda1", "size": "1073741824", "model": None,
         "serial": None, "rota": False, "rm": False, "tran": None,
         "fstype": "vfat", "pttype": None, "type": "part"},  # partition — should be skipped
    ]
})

_LSCPU_OUTPUT = """\
Architecture:            x86_64
CPU(s):                  12
Thread(s) per core:      2
Core(s) per socket:      6
Socket(s):               1
Vendor ID:               GenuineIntel
Model name:              Intel(R) Core(TM) i7-8700 CPU @ 3.20GHz
CPU MHz:                 3200
CPU max MHz:             4600
Virtualization:          VT-x
"""

_MEMINFO = """\
MemTotal:       32768000 kB
MemFree:         8192000 kB
MemAvailable:   16384000 kB
"""

_IP_LINK_JSON = json.dumps([
    {"ifindex": 1, "ifname": "lo", "flags": ["LOOPBACK"], "link_type": "loopback",
     "address": "00:00:00:00:00:00"},
    {"ifindex": 2, "ifname": "enp3s0", "flags": ["BROADCAST", "MULTICAST", "UP"],
     "link_type": "ether", "address": "aa:bb:cc:dd:ee:ff"},
    {"ifindex": 3, "ifname": "vmbr0", "flags": ["BROADCAST", "MULTICAST", "UP"],
     "link_type": "ether", "address": "aa:bb:cc:dd:ee:00"},  # bridge — should be skipped
])

_DPKG_OUTPUT = """\
proxmox-ve\t7.4-3\tamd64
dnsmasq\t2.90-1\tamd64
headscale\t0.22.3\tamd64
"""

_SYSTEMCTL_OUTPUT = """\
LoadState=loaded
ActiveState=active
UnitFileState=enabled
SubState=running
MainPID=1234
"""


# ===========================================================================
# 13.1 — hardware-state-schema.json
# ===========================================================================

class TestHardwareStateSchema:
    def _schema(self):
        path = os.path.join(_ROOT, "data-model", "hardware-state-schema.json")
        with open(path) as f:
            return json.load(f)

    def test_schema_loads(self):
        s = self._schema()
        assert s["title"] == "Hardware State"

    def test_required_fields(self):
        s = self._schema()
        assert "cell_id" in s["required"]
        assert "node_hostname" in s["required"]
        assert "collected_at" in s["required"]

    def test_disk_entry_has_health(self):
        s = self._schema()
        disk = s["definitions"]["disk_entry"]["properties"]
        assert "health" in disk

    def test_nic_entry_has_speed(self):
        s = self._schema()
        nic = s["definitions"]["nic_entry"]["properties"]
        assert "speed_mbps" in nic

    def test_valid_minimal_doc(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")  # noqa: I001
        s = self._schema()
        doc = {
            "schema_version": "1.0",
            "cell_id": "test-cell",
            "node_hostname": "pve01",
            "collected_at": "2026-06-01T12:00:00+00:00",
        }
        jsonschema.validate(doc, s)

    def test_missing_cell_id_fails(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")  # noqa: I001
        s = self._schema()
        doc = {
            "schema_version": "1.0",
            "node_hostname": "pve01",
            "collected_at": "2026-06-01T12:00:00+00:00",
        }
        try:
            jsonschema.validate(doc, s)
            raise AssertionError("Should have raised")
        except jsonschema.ValidationError:
            pass


# ===========================================================================
# 13.3 — platform-state-schema.json
# ===========================================================================

class TestPlatformStateSchema:
    def _schema(self):
        path = os.path.join(_ROOT, "data-model", "platform-state-schema.json")
        with open(path) as f:
            return json.load(f)

    def test_schema_loads(self):
        s = self._schema()
        assert s["title"] == "Platform State"

    def test_required_fields(self):
        s = self._schema()
        assert "cell_id" in s["required"]

    def test_cert_entry_has_not_after(self):
        s = self._schema()
        cert = s["definitions"]["cert_entry"]["properties"]
        assert "not_after" in cert

    def test_valid_minimal_doc(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")  # noqa: I001
        s = self._schema()
        doc = {
            "schema_version": "1.0",
            "cell_id": "test-cell",
            "node_hostname": "pve01",
            "collected_at": "2026-06-01T12:00:00+00:00",
        }
        jsonschema.validate(doc, s)


# ===========================================================================
# 13.2 — hardware_state_collector parsers
# ===========================================================================

class TestParseLsblk:
    def test_returns_list(self):
        disks = _hw._parse_lsblk(_LSBLK_JSON)
        assert isinstance(disks, list)

    def test_excludes_partitions(self):
        disks = _hw._parse_lsblk(_LSBLK_JSON)
        names = [d.name for d in disks]
        assert "sda1" not in names

    def test_includes_disks(self):
        disks = _hw._parse_lsblk(_LSBLK_JSON)
        names = [d.name for d in disks]
        assert "sda" in names
        assert "sdb" in names

    def test_size_converted_to_gib(self):
        disks = _hw._parse_lsblk(_LSBLK_JSON)
        sda = next(d for d in disks if d.name == "sda")
        assert sda.size_gb is not None
        assert 400 < sda.size_gb < 500

    def test_ssd_detected(self):
        disks = _hw._parse_lsblk(_LSBLK_JSON)
        sda = next(d for d in disks if d.name == "sda")
        assert sda.rotational is False

    def test_model_set(self):
        disks = _hw._parse_lsblk(_LSBLK_JSON)
        sda = next(d for d in disks if d.name == "sda")
        assert sda.model == "SAMSUNG 870 EVO"

    def test_invalid_json_returns_empty(self):
        disks = _hw._parse_lsblk("not json")
        assert disks == []


class TestParseLscpu:
    def test_returns_cpu_info(self):
        cpu = _hw._parse_lscpu(_LSCPU_OUTPUT)
        assert isinstance(cpu, _hw.CpuInfo)

    def test_model_parsed(self):
        cpu = _hw._parse_lscpu(_LSCPU_OUTPUT)
        assert "i7-8700" in (cpu.model or "")

    def test_logical_cores_parsed(self):
        cpu = _hw._parse_lscpu(_LSCPU_OUTPUT)
        assert cpu.logical_cores == 12

    def test_physical_cores_derived(self):
        cpu = _hw._parse_lscpu(_LSCPU_OUTPUT)
        assert cpu.physical_cores == 6  # 12 logical / 2 threads per core / 1 socket

    def test_virtualization_parsed(self):
        cpu = _hw._parse_lscpu(_LSCPU_OUTPUT)
        assert cpu.virtualization == "VT-x"

    def test_architecture_parsed(self):
        cpu = _hw._parse_lscpu(_LSCPU_OUTPUT)
        assert cpu.architecture == "x86_64"


class TestParseMeminfo:
    def test_total_gib_parsed(self):
        total, used = _hw._parse_meminfo(_MEMINFO)
        assert total is not None
        assert 28 <= total <= 35  # 32768000 kB ≈ 31-32 GiB depending on rounding

    def test_used_gib_derived(self):
        total, used = _hw._parse_meminfo(_MEMINFO)
        assert used is not None

    def test_empty_returns_none(self):
        total, used = _hw._parse_meminfo("")
        assert total is None


class TestParseIpLinkJson:
    def test_returns_list(self):
        nics = _hw._parse_ip_link_json(_IP_LINK_JSON)
        assert isinstance(nics, list)

    def test_loopback_excluded(self):
        nics = _hw._parse_ip_link_json(_IP_LINK_JSON)
        names = [n.name for n in nics]
        assert "lo" not in names

    def test_bridge_excluded(self):
        nics = _hw._parse_ip_link_json(_IP_LINK_JSON)
        names = [n.name for n in nics]
        assert "vmbr0" not in names

    def test_physical_nic_included(self):
        nics = _hw._parse_ip_link_json(_IP_LINK_JSON)
        names = [n.name for n in nics]
        assert "enp3s0" in names

    def test_mac_set(self):
        nics = _hw._parse_ip_link_json(_IP_LINK_JSON)
        nic = next(n for n in nics if n.name == "enp3s0")
        assert nic.mac == "aa:bb:cc:dd:ee:ff"

    def test_invalid_json_returns_empty(self):
        nics = _hw._parse_ip_link_json("not json")
        assert nics == []


# ===========================================================================
# HardwareStateDocument + compute_hardware_health
# ===========================================================================

class TestHardwareStateDocument:
    def _doc(self, **kw):
        return _hw.HardwareStateDocument(
            cell_id="test-cell",
            node_hostname="pve01",
            collected_at="2026-06-01T12:00:00+00:00",
            **kw
        )

    def test_defaults(self):
        doc = self._doc()
        assert doc.disks == []
        assert doc.nics == []

    def test_hardware_state_to_dict(self):
        doc = self._doc()
        d = _hw.hardware_state_to_dict(doc)
        assert d["schema_version"] == "1.0"
        assert d["cell_id"] == "test-cell"

    def test_compute_health_no_disks(self):
        doc = self._doc()
        health = _hw.compute_hardware_health(doc)
        assert health["disk_health_summary"] == "UNKNOWN"
        assert health["overall_status"] == "UNKNOWN"

    def test_compute_health_all_passed(self):
        doc = self._doc(disks=[
            _hw.DiskEntry(name="sda", health="PASSED"),
            _hw.DiskEntry(name="sdb", health="PASSED"),
        ])
        health = _hw.compute_hardware_health(doc)
        assert health["disk_health_summary"] == "ALL_PASSED"
        assert health["overall_status"] == "HEALTHY"

    def test_compute_health_disk_failed(self):
        doc = self._doc(disks=[
            _hw.DiskEntry(name="sda", health="FAILED"),
        ])
        health = _hw.compute_hardware_health(doc)
        assert health["disk_health_summary"] == "FAILURES"
        assert health["overall_status"] == "CRITICAL"

    def test_compute_health_disk_warning(self):
        doc = self._doc(disks=[
            _hw.DiskEntry(name="sda", health="WARNING"),
        ])
        health = _hw.compute_hardware_health(doc)
        assert health["disk_health_summary"] == "WARNINGS"
        assert health["overall_status"] == "DEGRADED"

    def test_temperature_warning(self):
        doc = self._doc(disks=[
            _hw.DiskEntry(name="sda", health="PASSED", temperature_c=60),
        ])
        health = _hw.compute_hardware_health(doc)
        assert health["temperature_warnings"]


# ===========================================================================
# 13.4 — platform_state_collector parsers
# ===========================================================================

class TestParseDpkgQuery:
    def test_returns_list(self):
        pkgs = _ps._parse_dpkg_query(_DPKG_OUTPUT)
        assert isinstance(pkgs, list)
        assert len(pkgs) == 3

    def test_package_name_parsed(self):
        pkgs = _ps._parse_dpkg_query(_DPKG_OUTPUT)
        names = [p.name for p in pkgs]
        assert "proxmox-ve" in names

    def test_version_parsed(self):
        pkgs = _ps._parse_dpkg_query(_DPKG_OUTPUT)
        pve = next(p for p in pkgs if p.name == "proxmox-ve")
        assert pve.version == "7.4-3"

    def test_architecture_parsed(self):
        pkgs = _ps._parse_dpkg_query(_DPKG_OUTPUT)
        pve = next(p for p in pkgs if p.name == "proxmox-ve")
        assert pve.architecture == "amd64"


class TestParseSystemctlShow:
    def test_returns_service_unit(self):
        svc = _ps._parse_systemctl_show("dnsmasq", _SYSTEMCTL_OUTPUT)
        assert isinstance(svc, _ps.ServiceUnit)

    def test_name_set(self):
        svc = _ps._parse_systemctl_show("dnsmasq", _SYSTEMCTL_OUTPUT)
        assert svc.name == "dnsmasq"

    def test_active_true(self):
        svc = _ps._parse_systemctl_show("dnsmasq", _SYSTEMCTL_OUTPUT)
        assert svc.active is True

    def test_enabled_true(self):
        svc = _ps._parse_systemctl_show("dnsmasq", _SYSTEMCTL_OUTPUT)
        assert svc.enabled is True

    def test_failed_service(self):
        out = "LoadState=loaded\nActiveState=failed\nUnitFileState=enabled\nSubState=failed\n"
        svc = _ps._parse_systemctl_show("broken", out)
        assert svc.active is False
        assert svc.active_state == "failed"


# ===========================================================================
# PlatformStateDocument + compute_platform_health
# ===========================================================================

class TestPlatformStateDocument:
    def _doc(self, **kw):
        return _ps.PlatformStateDocument(
            cell_id="test-cell",
            node_hostname="pve01",
            collected_at="2026-06-01T12:00:00+00:00",
            **kw
        )

    def test_defaults(self):
        doc = self._doc()
        assert doc.packages == []
        assert doc.services == []

    def test_platform_state_to_dict(self):
        doc = self._doc()
        d = _ps.platform_state_to_dict(doc)
        assert d["schema_version"] == "1.0"
        assert d["cell_id"] == "test-cell"

    def test_compute_health_no_issues(self):
        doc = self._doc()
        health = _ps.compute_platform_health(doc)
        assert "overall_status" in health
        assert health["services_failed"] == []

    def test_compute_health_failed_service(self):
        svc = _ps.ServiceUnit(name="broken", active=False, active_state="failed")
        doc = self._doc(services=[svc])
        health = _ps.compute_platform_health(doc)
        assert "broken" in health["services_failed"]
        assert health["overall_status"] == "DEGRADED"

    def test_compute_health_security_updates(self):
        doc = self._doc(apt_security_updates=5)
        health = _ps.compute_platform_health(doc)
        assert health["security_updates_pending"]


# ===========================================================================
# 13.7 — readiness scoring
# ===========================================================================

from readiness import _score_hardware_state_completeness, _score_platform_state_completeness


class TestScoreHardwareStateCompleteness:
    def test_no_hardware_state_yellow(self):
        gaps = _score_hardware_state_completeness({})
        assert gaps
        assert gaps[0].severity == "YELLOW"

    def test_no_hardware_state_gap_type(self):
        gaps = _score_hardware_state_completeness({})
        assert gaps[0].gap_type == "MISSING_HARDWARE_STATE"

    def test_present_hardware_state_no_yellow(self):
        manifest = {
            "hardware_state": {
                "collected_at": "2026-06-01T12:00:00+00:00",
                "hardware_health": {"overall_status": "HEALTHY"},
            }
        }
        gaps = _score_hardware_state_completeness(manifest)
        assert not any(g.gap_type == "MISSING_HARDWARE_STATE" for g in gaps)

    def test_stale_hardware_state_orange(self):
        manifest = {
            "hardware_state": {
                "collected_at": "2025-01-01T00:00:00+00:00",  # very old
                "hardware_health": {"overall_status": "HEALTHY"},
            }
        }
        gaps = _score_hardware_state_completeness(manifest)
        assert any(g.severity == "ORANGE" and "STALE" in g.gap_type for g in gaps)

    def test_critical_hardware_health_orange(self):
        manifest = {
            "hardware_state": {
                "collected_at": "2026-06-01T12:00:00+00:00",
                "hardware_health": {"overall_status": "CRITICAL"},
            }
        }
        gaps = _score_hardware_state_completeness(manifest)
        assert any(g.severity == "ORANGE" and "CRITICAL" in g.gap_type for g in gaps)

    def test_degraded_hardware_health_yellow(self):
        manifest = {
            "hardware_state": {
                "collected_at": "2026-06-01T12:00:00+00:00",
                "hardware_health": {"overall_status": "DEGRADED"},
            }
        }
        gaps = _score_hardware_state_completeness(manifest)
        assert any(g.severity == "YELLOW" and "DEGRADED" in g.gap_type for g in gaps)

    def test_healthy_no_gaps(self):
        manifest = {
            "hardware_state": {
                "collected_at": "2026-06-01T12:00:00+00:00",
                "hardware_health": {"overall_status": "HEALTHY"},
            }
        }
        gaps = _score_hardware_state_completeness(manifest)
        assert not gaps


class TestScorePlatformStateCompleteness:
    def test_no_platform_state_yellow(self):
        gaps = _score_platform_state_completeness({})
        assert gaps
        assert gaps[0].severity == "YELLOW"

    def test_no_platform_state_gap_type(self):
        gaps = _score_platform_state_completeness({})
        assert gaps[0].gap_type == "MISSING_PLATFORM_STATE"

    def test_present_platform_state_healthy(self):
        manifest = {
            "platform_state": {
                "platform_health": {
                    "overall_status": "HEALTHY",
                    "services_failed": [],
                    "certs_expiring_soon": [],
                    "security_updates_pending": False,
                }
            }
        }
        gaps = _score_platform_state_completeness(manifest)
        assert not gaps

    def test_failed_services_yellow(self):
        manifest = {
            "platform_state": {
                "platform_health": {
                    "overall_status": "DEGRADED",
                    "services_failed": ["broken.service"],
                    "certs_expiring_soon": [],
                    "security_updates_pending": False,
                }
            }
        }
        gaps = _score_platform_state_completeness(manifest)
        assert any(g.gap_type == "SERVICES_FAILED" for g in gaps)

    def test_certs_expiring_yellow(self):
        manifest = {
            "platform_state": {
                "platform_health": {
                    "overall_status": "DEGRADED",
                    "services_failed": [],
                    "certs_expiring_soon": ["/etc/pve/local/pve-ssl.pem"],
                    "security_updates_pending": False,
                }
            }
        }
        gaps = _score_platform_state_completeness(manifest)
        assert any(g.gap_type == "CERT_EXPIRY_SOON" for g in gaps)

    def test_security_updates_yellow(self):
        manifest = {
            "platform_state": {
                "platform_health": {
                    "overall_status": "DEGRADED",
                    "services_failed": [],
                    "certs_expiring_soon": [],
                    "security_updates_pending": True,
                }
            }
        }
        gaps = _score_platform_state_completeness(manifest)
        assert any(g.gap_type == "SECURITY_UPDATES_PENDING" for g in gaps)
