"""
Tests for Phase 4: node assessment report, combined report, and CLI commands.
"""

from __future__ import annotations

import json

from engine.cli import build_parser, cmd_full_report, cmd_report
from engine.report import _bytes, _uptime, generate_report
from engine.report_combined import generate_combined_report

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _full_assessment() -> dict:
    return {
        "schema_version": "1.0",
        "timestamp": "2024-06-01T12:00:00+00:00",
        "hostname": "pve01.lab",
        "hardware": {
            "cpu": {
                "model": "Intel(R) Xeon(R) E-2236",
                "vendor": "GenuineIntel",
                "sockets": 1,
                "cores_per_socket": 6,
                "threads_per_core": 2,
                "total_cores": 6,
                "total_threads": 12,
                "architecture": "x86_64",
                "flags": ["vmx", "aes", "avx2", "sse4_2"],
            },
            "memory": {
                "total_bytes": 34359738368,
                "ecc_enabled": True,
                "dimms": [
                    {
                        "slot": "DIMM_A1",
                        "size_bytes": 17179869184,
                        "type": "DDR4",
                        "speed_mhz": 2666,
                        "manufacturer": "Micron",
                        "ecc": True,
                    },
                    {
                        "slot": "DIMM_B1",
                        "size_bytes": 17179869184,
                        "type": "DDR4",
                        "speed_mhz": 2666,
                        "manufacturer": "Micron",
                        "ecc": True,
                    },
                ],
            },
            "system": {
                "manufacturer": "Supermicro",
                "product_name": "SYS-E300-9D",
                "serial_number": "S123456",
            },
            "baseboard": {
                "manufacturer": "Supermicro",
                "product_name": "X11SCH-F",
                "version": "1.01",
            },
        },
        "firmware": {
            "bios": {
                "vendor": "American Megatrends",
                "version": "3.3",
                "release_date": "12/15/2022",
            },
            "uefi": True,
        },
        "storage": {
            "disks": [
                {
                    "name": "sda",
                    "model": "Samsung 870 EVO",
                    "type": "SSD",
                    "interface": "SATA",
                    "size_bytes": 500107862016,
                    "smart_status": "PASSED",
                },
                {
                    "name": "nvme0n1",
                    "model": "WD Black SN850",
                    "type": "NVMe",
                    "interface": "NVME",
                    "size_bytes": 1000204886016,
                    "smart_status": "PASSED",
                },
            ],
            "zfs_pools": [
                {
                    "name": "tank",
                    "state": "ONLINE",
                    "health": "ONLINE",
                    "size_bytes": 8001563222016,
                    "alloc_bytes": 2000390242304,
                    "free_bytes": 6001172979712,
                    "fragmentation_pct": 5.0,
                    "dedup_ratio": 1.0,
                }
            ],
            "lvm_volume_groups": [
                {
                    "name": "pve",
                    "size_bytes": 500000000000,
                    "free_bytes": 200000000000,
                    "pv_count": 1,
                    "lv_count": 3,
                }
            ],
        },
        "network": {
            "interfaces": [
                {
                    "name": "eth0",
                    "type": "physical",
                    "state": "UP",
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "mtu": 1500,
                    "speed_mbps": 1000,
                    "addresses": [
                        {"address": "192.168.1.10", "prefix_len": 24, "family": "inet"}
                    ],
                },
                {
                    "name": "vmbr0",
                    "type": "bridge",
                    "state": "UP",
                    "mac": "aa:bb:cc:dd:ee:ff",
                    "mtu": 1500,
                    "addresses": [
                        {"address": "192.168.1.1", "prefix_len": 24, "family": "inet"}
                    ],
                },
            ]
        },
        "os": {
            "name": "Debian GNU/Linux",
            "version": "12 (bookworm)",
            "kernel_version": "6.5.11-7-pve",
            "architecture": "x86_64",
            "uptime_seconds": 864000,
        },
        "virtualization": {
            "proxmox": {
                "version": "8.1.4",
                "kernel": "6.5.11-7-pve",
                "node_name": "pve01",
                "cluster_name": "homelab",
                "cluster_members": ["pve01", "pve02"],
            },
            "vms": [
                {"vmid": 100, "name": "debian12", "type": "qemu", "status": "running"},
                {"vmid": 101, "name": "win11",    "type": "qemu", "status": "stopped"},
                {"vmid": 200, "name": "ct-nginx", "type": "lxc",  "status": "running"},
            ],
            "storage_pools": [
                {"name": "local",     "type": "dir",     "content": ["iso", "backup"], "enabled": True},
                {"name": "local-zfs", "type": "zfspool", "content": ["images"],        "enabled": True},
            ],
        },
        "guests": [
            {
                "hostname": "web01",
                "inventory_name": "web01",
                "groups": ["webservers"],
                "collection_method": "ansible-facts",
                "collection_timestamp": "2024-06-01T12:00:00+00:00",
                "operating_system": {"distribution": "Debian", "distribution_version": "12"},
                "running_services": ["nginx.service", "ssh.service"],
                "docker_containers": [{"name": "app", "image": "myapp:1.0", "status": "running"}],
                "configuration_method": "ansible",
            }
        ],
    }


def _minimal_assessment() -> dict:
    return {
        "schema_version": "1.0",
        "timestamp": "2024-01-01T00:00:00+00:00",
        "hostname": "pve01.lab",
    }


# ===========================================================================
# Node report – generate_report()
# ===========================================================================

class TestNodeReport:
    def test_returns_string(self):
        assert isinstance(generate_report(_full_assessment()), str)

    def test_json_format(self):
        result = generate_report(_full_assessment(), fmt="json")
        parsed = json.loads(result)
        assert parsed["hostname"] == "pve01.lab"

    def test_header(self):
        r = generate_report(_full_assessment())
        assert "Node Assessment Report" in r
        assert "pve01.lab" in r
        assert "2024-06-01" in r

    def test_node_summary_section(self):
        r = generate_report(_full_assessment())
        assert "Node Summary" in r
        assert "Supermicro" in r
        assert "Intel(R) Xeon(R) E-2236" in r

    def test_hardware_cpu(self):
        r = generate_report(_full_assessment())
        assert "Hardware" in r
        assert "CPU" in r
        assert "GenuineIntel" in r
        assert "x86_64" in r

    def test_hardware_cpu_flags(self):
        r = generate_report(_full_assessment())
        assert "vmx" in r
        assert "avx2" in r

    def test_hardware_memory(self):
        r = generate_report(_full_assessment())
        assert "Memory" in r
        assert "32.0 GB" in r
        assert "ECC" in r
        assert "Micron" in r

    def test_hardware_dimm_table(self):
        r = generate_report(_full_assessment())
        assert "DIMM_A1" in r
        assert "DDR4" in r

    def test_hardware_system_board(self):
        r = generate_report(_full_assessment())
        assert "SYS-E300-9D" in r
        assert "X11SCH-F" in r

    def test_firmware_section(self):
        r = generate_report(_full_assessment())
        assert "Firmware" in r
        assert "American Megatrends" in r
        assert "3.3" in r
        assert "UEFI" in r

    def test_storage_disks(self):
        r = generate_report(_full_assessment())
        assert "Storage" in r
        assert "sda" in r
        assert "Samsung 870 EVO" in r
        assert "PASSED" in r

    def test_storage_zfs(self):
        r = generate_report(_full_assessment())
        assert "ZFS" in r
        assert "tank" in r
        assert "ONLINE" in r

    def test_storage_lvm(self):
        r = generate_report(_full_assessment())
        assert "LVM" in r
        assert "pve" in r

    def test_network_section(self):
        r = generate_report(_full_assessment())
        assert "Network" in r
        assert "eth0" in r
        assert "vmbr0" in r
        assert "192.168.1.10" in r

    def test_os_section(self):
        r = generate_report(_full_assessment())
        assert "Operating System" in r
        assert "Debian GNU/Linux" in r
        assert "6.5.11-7-pve" in r

    def test_os_uptime(self):
        r = generate_report(_full_assessment())
        assert "10d" in r  # 864000 seconds = 10 days

    def test_proxmox_section(self):
        r = generate_report(_full_assessment())
        assert "Proxmox VE" in r
        assert "8.1.4" in r
        assert "homelab" in r

    def test_proxmox_vms(self):
        r = generate_report(_full_assessment())
        assert "debian12" in r
        assert "ct-nginx" in r
        assert "QEMU VMs" in r
        assert "LXC Containers" in r

    def test_proxmox_storage_pools(self):
        r = generate_report(_full_assessment())
        assert "local-zfs" in r
        assert "zfspool" in r

    def test_minimal_assessment_no_crash(self):
        r = generate_report(_minimal_assessment())
        assert "pve01.lab" in r

    def test_no_recommendations(self):
        r = generate_report(_full_assessment()).lower()
        for word in ("recommend", "upgrade", "replace", "should", "consider", "suggest"):
            assert word not in r, f"Report must not contain '{word}'"

    def test_no_secrets(self):
        a = _full_assessment()
        a["hardware"]["system"]["serial_number"] = "S123456"
        r = generate_report(a)
        # Serial numbers are facts, they should appear; passwords should not
        assert "S123456" in r


# ===========================================================================
# Helper functions
# ===========================================================================

class TestHelpers:
    def test_bytes_bytes(self):
        assert _bytes(512) == "512 B"

    def test_bytes_kb(self):
        assert "KB" in _bytes(2048)

    def test_bytes_mb(self):
        assert "MB" in _bytes(10 * 1024 * 1024)

    def test_bytes_gb(self):
        assert "GB" in _bytes(34359738368)

    def test_bytes_tb(self):
        assert "TB" in _bytes(8001563222016)

    def test_uptime_minutes(self):
        assert _uptime(300) == "5m"

    def test_uptime_hours(self):
        assert _uptime(7200) == "2h"

    def test_uptime_days(self):
        assert _uptime(864000) == "10d"

    def test_uptime_mixed(self):
        result = _uptime(90061)  # 1d 1h 1m 1s
        assert "1d" in result and "1h" in result

    def test_uptime_zero(self):
        assert _uptime(0) == "0m"


# ===========================================================================
# Combined report
# ===========================================================================

class TestCombinedReport:
    def test_returns_string(self):
        assert isinstance(generate_combined_report(_full_assessment()), str)

    def test_combined_title(self):
        r = generate_combined_report(_full_assessment())
        assert "Infrastructure Assessment Report" in r

    def test_contains_node_sections(self):
        r = generate_combined_report(_full_assessment())
        assert "Hardware" in r
        assert "Storage" in r
        assert "Network" in r
        assert "Proxmox VE" in r

    def test_contains_guest_sections(self):
        r = generate_combined_report(_full_assessment())
        assert "Guest Assessment" in r
        assert "web01" in r

    def test_separator_present(self):
        r = generate_combined_report(_full_assessment())
        assert "---" in r

    def test_minimal_assessment_no_crash(self):
        r = generate_combined_report(_minimal_assessment())
        assert "Infrastructure Assessment Report" in r

    def test_no_recommendations(self):
        r = generate_combined_report(_full_assessment()).lower()
        for word in ("recommend", "upgrade", "replace", "should", "consider", "suggest"):
            assert word not in r, f"Report must not contain '{word}'"


# ===========================================================================
# CLI – report / full-report
# ===========================================================================

class TestReportCLI:
    def _write(self, tmp_path, data):
        f = tmp_path / "a.json"
        f.write_text(json.dumps(data))
        return f

    def test_report_markdown_stdout(self, tmp_path, capsys):
        f = self._write(tmp_path, _full_assessment())
        args = build_parser().parse_args(["report", "--input", str(f)])
        rc = cmd_report(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert "Node Assessment Report" in out

    def test_report_json_format(self, tmp_path, capsys):
        f = self._write(tmp_path, _full_assessment())
        args = build_parser().parse_args(["report", "--input", str(f), "--format", "json"])
        rc = cmd_report(args)
        out = capsys.readouterr().out
        assert rc == 0
        parsed = json.loads(out)
        assert parsed["hostname"] == "pve01.lab"

    def test_report_to_file(self, tmp_path):
        f = self._write(tmp_path, _full_assessment())
        out_f = tmp_path / "report.md"
        args = build_parser().parse_args(["report", "--input", str(f), "--output", str(out_f)])
        cmd_report(args)
        assert out_f.exists()
        assert "Node Assessment Report" in out_f.read_text()

    def test_full_report_stdout(self, tmp_path, capsys):
        f = self._write(tmp_path, _full_assessment())
        args = build_parser().parse_args(["full-report", "--input", str(f)])
        rc = cmd_full_report(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert "Infrastructure Assessment Report" in out
        assert "Guest Assessment" in out

    def test_full_report_to_file(self, tmp_path):
        f = self._write(tmp_path, _full_assessment())
        out_f = tmp_path / "combined.md"
        args = build_parser().parse_args(["full-report", "--input", str(f), "--output", str(out_f)])
        cmd_full_report(args)
        assert out_f.exists()
        content = out_f.read_text()
        assert "Infrastructure Assessment Report" in content
        assert "Guest Assessment" in content
