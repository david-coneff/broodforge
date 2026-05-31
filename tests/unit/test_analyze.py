#!/usr/bin/env python3
"""
Integration tests for assessment/tier1/analyze.py.
Builds a simulated collector output directory and verifies manifest.json output.

Run: python3 tests/unit/test_analyze.py
"""

import json
import sys
import unittest
import shutil
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "assessment" / "tier1"))
sys.path.insert(0, str(REPO_ROOT / "data-model"))

from analyze import build_manifest
from validate import validate_file


def write(path: Path, content: str) -> None:
    path.write_text(content)


class BaseAnalyzeTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        # Empty log files
        (self.tmpdir / "collection_errors.log").write_text("")
        (self.tmpdir / "collection_warnings.log").write_text("")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def build(self) -> dict:
        return build_manifest(self.tmpdir)


class TestCPUParsing(BaseAnalyzeTest):
    def test_lscpu_json(self):
        write(self.tmpdir / "lscpu_json.json", json.dumps({"lscpu": [
            {"field": "Architecture:", "data": "x86_64"},
            {"field": "Model name:", "data": "Intel Xeon E5-2620"},
            {"field": "Socket(s):", "data": "2"},
            {"field": "Core(s) per socket:", "data": "6"},
            {"field": "Thread(s) per core:", "data": "2"},
            {"field": "CPU(s):", "data": "24"},
            {"field": "Virtualization:", "data": "VT-x"},
        ]}))
        m = self.build()
        self.assertEqual(m["cpu"]["model"], "Intel Xeon E5-2620")
        self.assertEqual(m["cpu"]["total_threads"], 24)
        self.assertEqual(m["cpu"]["sockets"], 2)
        self.assertEqual(m["cpu"]["virtualization"], "VT-x")

    def test_lscpu_text_fallback(self):
        write(self.tmpdir / "lscpu.txt", (
            "Architecture:            x86_64\n"
            "Model name:              AMD EPYC 7502\n"
            "Socket(s):               1\n"
            "Core(s) per socket:      32\n"
            "Thread(s) per core:      2\n"
            "CPU(s):                  64\n"
        ))
        m = self.build()
        self.assertEqual(m["cpu"]["model"], "AMD EPYC 7502")
        self.assertEqual(m["cpu"]["total_threads"], 64)

    def test_cpuinfo_fallback(self):
        write(self.tmpdir / "cpuinfo.txt", (
            "processor\t: 0\n"
            "model name\t: ARMv7 Processor\n"
            "processor\t: 1\n"
            "model name\t: ARMv7 Processor\n"
        ))
        m = self.build()
        self.assertEqual(m["cpu"]["total_threads"], 2)
        self.assertEqual(m["cpu"]["model"], "ARMv7 Processor")

    def test_no_cpu_data_returns_safe_default(self):
        m = self.build()
        self.assertGreaterEqual(m["cpu"]["total_threads"], 1)
        self.assertIn("total_threads", m["cpu"])


class TestMemoryParsing(BaseAnalyzeTest):
    def test_free_bytes_output(self):
        write(self.tmpdir / "memory.txt", (
            "               total        used        free      shared  buff/cache   available\n"
            "Mem:     68719476736  5368709120  56624701440    4194304   6726066176  62914560000\n"
            "Swap:              0           0           0\n"
        ))
        m = self.build()
        self.assertAlmostEqual(m["memory"]["total_gb"], 64.0, places=0)
        self.assertEqual(m["memory"]["swap_total_gb"], 0.0)

    def test_meminfo_fallback(self):
        write(self.tmpdir / "meminfo.txt", (
            "MemTotal:       32768000 kB\n"
            "MemAvailable:   28000000 kB\n"
            "SwapTotal:       4096000 kB\n"
        ))
        m = self.build()
        self.assertAlmostEqual(m["memory"]["total_gb"], 31.25, delta=0.5)

    def test_numa_nodes_from_lscpu(self):
        write(self.tmpdir / "lscpu.txt", "NUMA node(s):  2\n")
        write(self.tmpdir / "meminfo.txt", "MemTotal: 65536000 kB\n")
        m = self.build()
        self.assertEqual(m["memory"]["numa_nodes"], 2)


class TestStorageParsing(BaseAnalyzeTest):
    def test_lsblk_json_two_ssds(self):
        write(self.tmpdir / "lsblk_json.json", json.dumps({"blockdevices": [
            {"name": "sda", "size": "1000204886016", "type": "disk", "rota": "0",
             "model": "Samsung 870 EVO", "tran": "sata", "wwn": "0xABC", "mountpoint": None, "children": []},
            {"name": "sdb", "size": "1000204886016", "type": "disk", "rota": "0",
             "model": "Samsung 870 EVO", "tran": "sata", "wwn": "0xDEF", "mountpoint": None, "children": []},
        ]}))
        m = self.build()
        devices = m["storage"]["block_devices"]
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0]["name"], "sda")
        self.assertFalse(devices[0]["rotational"])
        self.assertAlmostEqual(devices[0]["size_gb"], 931.5, delta=1.0)

    def test_rotational_hdd(self):
        write(self.tmpdir / "lsblk_json.json", json.dumps({"blockdevices": [
            {"name": "sda", "size": "4000787030016", "type": "disk", "rota": "1",
             "model": "WD Red 4TB", "tran": "sata", "wwn": None, "mountpoint": None, "children": []},
        ]}))
        m = self.build()
        self.assertTrue(m["storage"]["block_devices"][0]["rotational"])

    def test_zfs_mirror_topology(self):
        write(self.tmpdir / "zpool_list.txt", "rpool\t984064278528\t869768118272\tONLINE\n")
        write(self.tmpdir / "zpool_status.txt", (
            "  pool: rpool\n"
            " state: ONLINE\n"
            "config:\n\n"
            "\tNAME        STATE     READ WRITE CKSUM\n"
            "\trpool       ONLINE       0     0     0\n"
            "\t  mirror    ONLINE       0     0     0\n"
            "\t    sda     ONLINE       0     0     0\n"
            "\t    sdb     ONLINE       0     0     0\n"
            "\nerrors: No known data errors\n"
        ))
        m = self.build()
        pool = m["storage"]["zfs_pools"][0]
        self.assertEqual(pool["topology"], "mirror")
        self.assertIn("sda", pool["devices"])
        self.assertIn("sdb", pool["devices"])

    def test_zfs_raidz1_topology(self):
        write(self.tmpdir / "zpool_list.txt", "tank\t3000000000000\t2000000000000\tONLINE\n")
        write(self.tmpdir / "zpool_status.txt", (
            "  pool: tank\n"
            " state: ONLINE\n"
            "config:\n\n"
            "\ttank       ONLINE       0     0     0\n"
            "\t  raidz1   ONLINE       0     0     0\n"
            "\t    sda    ONLINE       0     0     0\n"
            "\t    sdb    ONLINE       0     0     0\n"
            "\t    sdc    ONLINE       0     0     0\n"
        ))
        m = self.build()
        pool = m["storage"]["zfs_pools"][0]
        self.assertEqual(pool["topology"], "raidz1")
        self.assertEqual(len(pool["devices"]), 3)

    def test_pvesm_storage_parsing(self):
        write(self.tmpdir / "pvesm_status.txt", (
            "Name             Type     Status           Total            Used       Available        %\n"
            "local            dir      active       53660876800      9663676416   43997200384   18.00%\n"
            "local-zfs        zfspool  active      869768118272    137438953472  732329164800   15.81%\n"
        ))
        m = self.build()
        pve = m["storage"]["pve_storage"]
        self.assertEqual(len(pve), 2)
        self.assertEqual(pve[0]["name"], "local")
        self.assertTrue(pve[0]["active"])
        self.assertEqual(pve[1]["type"], "zfspool")

    def test_no_storage_data_returns_empty_lists(self):
        m = self.build()
        self.assertEqual(m["storage"]["block_devices"], [])
        self.assertEqual(m["storage"]["zfs_pools"], [])


class TestNetworkParsing(BaseAnalyzeTest):
    def test_ip_addr_json(self):
        write(self.tmpdir / "ip_addr_json.json", json.dumps([
            {"ifname": "lo", "mtu": 65536, "operstate": "UNKNOWN",
             "address": "00:00:00:00:00:00",
             "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]},
            {"ifname": "vmbr0", "mtu": 1500, "operstate": "UP",
             "address": "aa:bb:cc:dd:ee:01",
             "addr_info": [{"family": "inet", "local": "10.0.0.10", "prefixlen": 24}]},
        ]))
        m = self.build()
        ifaces = {i["name"]: i for i in m["network"]["interfaces"]}
        self.assertIn("vmbr0", ifaces)
        self.assertIn("10.0.0.10/24", ifaces["vmbr0"]["addresses"])

    def test_default_gateway_from_json(self):
        write(self.tmpdir / "ip_route_json.json", json.dumps([
            {"dst": "default", "gateway": "10.0.0.1", "dev": "vmbr0"},
            {"dst": "10.0.0.0/24", "dev": "vmbr0"},
        ]))
        m = self.build()
        self.assertEqual(m["network"]["default_gateway"], "10.0.0.1")

    def test_default_gateway_text_fallback(self):
        write(self.tmpdir / "ip_route.txt", (
            "default via 192.168.50.1 dev eth0 proto static\n"
            "192.168.50.0/24 dev eth0 proto kernel scope link\n"
        ))
        m = self.build()
        self.assertEqual(m["network"]["default_gateway"], "192.168.50.1")

    def test_bridge_parsed_from_interfaces(self):
        write(self.tmpdir / "network_interfaces.txt", (
            "auto vmbr0\n"
            "iface vmbr0 inet static\n"
            "    address 192.168.1.10\n"
            "    netmask 24\n"
            "    bridge-ports enp2s0\n"
            "    bridge-stp off\n"
        ))
        m = self.build()
        self.assertEqual(len(m["network"]["bridges"]), 1)
        bridge = m["network"]["bridges"][0]
        self.assertEqual(bridge["name"], "vmbr0")
        self.assertIn("enp2s0", bridge["ports"])

    def test_vlan_aware_bridge(self):
        write(self.tmpdir / "network_interfaces.txt", (
            "auto vmbr0\n"
            "iface vmbr0 inet manual\n"
            "    bridge-ports enp0s3\n"
            "    bridge-vlan-aware yes\n"
        ))
        m = self.build()
        self.assertEqual(len(m["network"]["bridges"]), 1)
        self.assertTrue(m["network"]["bridges"][0]["vlan_aware"])

    def test_dns_from_resolv_conf(self):
        write(self.tmpdir / "resolv_conf.txt", (
            "nameserver 1.1.1.1\n"
            "nameserver 8.8.8.8\n"
            "search example.com local\n"
        ))
        m = self.build()
        self.assertIn("1.1.1.1", m["network"]["dns_servers"])
        self.assertIn("8.8.8.8", m["network"]["dns_servers"])
        self.assertIn("example.com", m["network"]["dns_search"])


class TestVMsAndContainers(BaseAnalyzeTest):
    def test_no_vms(self):
        write(self.tmpdir / "qm_list.txt", "      VMID NAME   STATUS   MEM(MB)    BOOTDISK(GB) PID\n")
        m = self.build()
        self.assertEqual(m["vms"], [])

    def test_vms_parsed(self):
        write(self.tmpdir / "qm_list.txt", (
            "      VMID NAME          STATUS     MEM(MB)    BOOTDISK(GB) PID\n"
            "       100 forgejo       running    4096              100.00 12345\n"
            "       101 monitoring    stopped    2048               32.00 0\n"
        ))
        m = self.build()
        self.assertEqual(len(m["vms"]), 2)
        self.assertEqual(m["vms"][0]["vmid"], 100)
        self.assertEqual(m["vms"][0]["name"], "forgejo")
        self.assertEqual(m["vms"][0]["status"], "running")
        self.assertEqual(m["vms"][1]["status"], "stopped")

    def test_containers_parsed(self):
        write(self.tmpdir / "pct_list.txt", (
            "VMID       Status     Lock         Name\n"
            "200        running                 pihole\n"
        ))
        m = self.build()
        self.assertEqual(len(m["containers"]), 1)
        self.assertEqual(m["containers"][0]["ctid"], 200)
        self.assertEqual(m["containers"][0]["name"], "pihole")


class TestSoftwareParsing(BaseAnalyzeTest):
    def test_packages_parsed(self):
        write(self.tmpdir / "dpkg_list.txt", (
            "git\t1:2.39.2\tinstall ok installed\n"
            "python3\t3.11.2\tinstall ok installed\n"
            "vim\t2:9.0\tinstall ok installed\n"
            "oldpkg\t1.0\tdeinstall ok config-files\n"
        ))
        m = self.build()
        pkg_names = [p["name"] for p in m["software"]["installed_packages"]]
        self.assertIn("git", pkg_names)
        self.assertIn("python3", pkg_names)
        self.assertNotIn("oldpkg", pkg_names)  # deinstalled — filtered out

    def test_automation_readiness_from_tool_versions(self):
        write(self.tmpdir / "tool_versions.txt", (
            "git git version 2.39.2\n"
            "python3 Python 3.11.2\n"
            "ansible ansible [core 2.15.0]\n"
        ))
        m = self.build()
        r = m["software"]["automation_readiness"]
        self.assertTrue(r["git"])
        self.assertTrue(r["python3"])
        self.assertTrue(r["ansible"])
        self.assertFalse(r["terraform"])

    def test_automation_readiness_fallback_to_packages(self):
        write(self.tmpdir / "dpkg_list.txt", (
            "git\t2.39.2\tinstall ok installed\n"
            "curl\t7.88.1\tinstall ok installed\n"
        ))
        # No tool_versions.txt — falls back to packages
        m = self.build()
        r = m["software"]["automation_readiness"]
        self.assertTrue(r["git"])
        self.assertTrue(r["curl"])
        self.assertFalse(r["ansible"])

    def test_running_services(self):
        write(self.tmpdir / "systemctl_list.txt", (
            "pveproxy.service   loaded active running PVE API\n"
            "ssh.service        loaded active running OpenSSH\n"
        ))
        m = self.build()
        self.assertIn("pveproxy.service", m["software"]["running_services"])
        self.assertIn("ssh.service", m["software"]["running_services"])


class TestHostParsing(BaseAnalyzeTest):
    def test_pveversion_multiline(self):
        write(self.tmpdir / "pveversion.txt", (
            "proxmox-ve: 8.2-1 (running kernel: 6.8.4-2-pve)\n"
            "pve-manager: 8.2.1\n"
        ))
        write(self.tmpdir / "hostname.txt", "pve01.internal")
        m = self.build()
        self.assertEqual(m["host"]["proxmox_version"], "8.2-1")
        self.assertEqual(m["host"]["hostname"], "pve01")
        self.assertEqual(m["host"]["fqdn"], "pve01.internal")

    def test_uptime_parsed(self):
        write(self.tmpdir / "uptime.txt", "86400.12 72000.00\n")
        m = self.build()
        self.assertEqual(m["host"]["uptime_seconds"], 86400)

    def test_no_pveversion_flagged(self):
        m = self.build()
        errs = [e["message"] for e in m["collection_errors"]]
        self.assertTrue(any("pveversion" in e.lower() or "proxmox" in e.lower() for e in errs))

    def test_kernel_from_uname(self):
        write(self.tmpdir / "uname.txt", "Linux pve01 6.8.4-2-pve #1 SMP x86_64 GNU/Linux\n")
        m = self.build()
        self.assertEqual(m["host"]["kernel_version"], "6.8.4-2-pve")


class TestSchemaCompliance(BaseAnalyzeTest):
    """Every manifest produced by build_manifest must pass schema validation."""

    def _full_fixture(self):
        """Write a realistic collector output directory."""
        write(self.tmpdir / "lscpu_json.json", json.dumps({"lscpu": [
            {"field": "Architecture:", "data": "x86_64"},
            {"field": "Model name:", "data": "Intel Core i7-12700"},
            {"field": "Socket(s):", "data": "1"},
            {"field": "Core(s) per socket:", "data": "12"},
            {"field": "Thread(s) per core:", "data": "2"},
            {"field": "CPU(s):", "data": "24"},
        ]}))
        write(self.tmpdir / "memory.txt",
              "               total        used        free      shared  buff/cache   available\n"
              "Mem:     34359738368  4294967296  26843545600    4194304   3221225472  30064771072\n"
              "Swap:              0           0           0\n")
        write(self.tmpdir / "lsblk_json.json", json.dumps({"blockdevices": [
            {"name": "nvme0n1", "size": "512110190592", "type": "disk", "rota": "0",
             "model": "Samsung 980 PRO", "tran": "nvme", "wwn": None, "mountpoint": None, "children": []}
        ]}))
        write(self.tmpdir / "ip_addr_json.json", json.dumps([
            {"ifname": "vmbr0", "mtu": 1500, "operstate": "UP",
             "address": "aa:bb:cc:dd:ee:ff",
             "addr_info": [{"family": "inet", "local": "10.0.0.5", "prefixlen": 24}]}
        ]))
        write(self.tmpdir / "ip_route_json.json", json.dumps([
            {"dst": "default", "gateway": "10.0.0.1", "dev": "vmbr0"}
        ]))
        write(self.tmpdir / "hostname.txt", "pve02")
        write(self.tmpdir / "pveversion.txt", "pve-manager: 8.2.1 (running kernel: 6.8.4-2-pve)\n")
        write(self.tmpdir / "uname.txt", "Linux pve02 6.8.4-2-pve #1 SMP x86_64\n")
        write(self.tmpdir / "uptime.txt", "3600.00 3200.00\n")
        write(self.tmpdir / "timezone.txt", "Europe/London\n")
        write(self.tmpdir / "qm_list.txt", "      VMID NAME   STATUS   MEM(MB) BOOTDISK PID\n")
        write(self.tmpdir / "pct_list.txt", "VMID Status Lock Name\n")
        write(self.tmpdir / "collected_at.txt", "2026-05-30T12:00:00Z")

    def test_empty_dir_still_validates(self):
        m = build_manifest(self.tmpdir)
        out = self.tmpdir / "manifest.json"
        out.write_text(json.dumps(m))
        schema_path = REPO_ROOT / "data-model" / "observed-state-schema.json"
        ok, errors = validate_file(out, schema_path)
        self.assertTrue(ok, msg=f"Schema errors: {[str(e) for e in errors]}")

    def test_full_fixture_validates(self):
        self._full_fixture()
        m = build_manifest(self.tmpdir)
        out = self.tmpdir / "manifest.json"
        out.write_text(json.dumps(m))
        schema_path = REPO_ROOT / "data-model" / "observed-state-schema.json"
        ok, errors = validate_file(out, schema_path)
        self.assertTrue(ok, msg=f"Schema errors: {[str(e) for e in errors]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
