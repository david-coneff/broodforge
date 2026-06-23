#!/usr/bin/env python3
"""
Tests for Phase 12.E.4 — Spawn Hardware Discovery.

Covers:
  - _parse_lsblk(): parses disk info from lsblk output
  - _parse_ip_link(): parses NIC info from ip -j link JSON
  - _parse_meminfo(): parses RAM from /proc/meminfo
  - _parse_cpu_model(): extracts CPU name from lscpu
  - _parse_nproc(): parses core count
  - zfs_topology_for_profile(): recommends topology from disk count
  - discover_hardware(): with mocked SSH runner
  - hardware_profile_to_dict() / dict_to_hardware_profile(): round-trip
  - HardwareProfile properties (disk_count, ssd_count, hdd_count, etc.)
"""

import json
import unittest

from spawn_hardware_discovery import (
    DiskInfo,
    HardwareProfile,
    NicInfo,
    _parse_cpu_model,
    _parse_ip_link,
    _parse_lsblk,
    _parse_meminfo,
    _parse_nproc,
    dict_to_hardware_profile,
    discover_hardware,
    hardware_profile_to_dict,
    zfs_topology_for_profile,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

LSBLK_OUTPUT = """\
sda 500107862016 1 Samsung SSD 870
sdb 500107862016 1 Samsung SSD 870
sdc 8001563222016 0 WDC WD80EFZX
sda1 499000000000 1
"""

IP_LINK_JSON = json.dumps([
    {"ifname": "lo",   "link_type": "loopback", "address": "00:00:00:00:00:00", "operstate": "UNKNOWN"},
    {"ifname": "eno1", "link_type": "ether",    "address": "aa:bb:cc:dd:ee:01", "operstate": "UP"},
    {"ifname": "eno2", "link_type": "ether",    "address": "aa:bb:cc:dd:ee:02", "operstate": "DOWN"},
    {"ifname": "vmbr0","link_type": "ether",    "address": "aa:bb:cc:dd:ee:03", "operstate": "UP"},
])

MEMINFO = """\
MemTotal:       33554432 kB
MemFree:        16777216 kB
MemAvailable:   20000000 kB
"""

LSCPU = """\
Architecture:     x86_64
CPU(s):           8
Model name:       Intel(R) Core(TM) i7-12700 @ 2.1GHz
CPU MHz:          2100.000
"""


def _mock_runner(responses: dict):
    """responses: {substring_in_cmd: (rc, stdout, stderr)}"""
    def runner(cmd, env=None):
        cmd_str = " ".join(cmd)
        for key, val in responses.items():
            if key in cmd_str:
                return val
        return 0, "", ""
    return runner


# ---------------------------------------------------------------------------
# _parse_lsblk
# ---------------------------------------------------------------------------

class TestParseLsblk(unittest.TestCase):

    def setUp(self):
        self.disks = _parse_lsblk(LSBLK_OUTPUT)

    def test_top_level_disks_only(self):
        # sda1 is a partition and should be excluded
        names = [d.name for d in self.disks]
        self.assertNotIn("/dev/sda1", names)

    def test_all_top_level_disks_found(self):
        names = [d.name for d in self.disks]
        self.assertIn("/dev/sda", names)
        self.assertIn("/dev/sdb", names)
        self.assertIn("/dev/sdc", names)

    def test_rotational_vs_ssd(self):
        sda = next(d for d in self.disks if d.name == "/dev/sda")
        sdc = next(d for d in self.disks if d.name == "/dev/sdc")
        # sda ROTA=1 → HDD; sdc ROTA=0 → SSD
        self.assertTrue(sda.rotational)    # sda: ROTA=1
        self.assertFalse(sdc.rotational)   # sdc: ROTA=0

    def test_size_converted_to_gb(self):
        sda = next(d for d in self.disks if d.name == "/dev/sda")
        self.assertAlmostEqual(sda.size_gb, 465.8, delta=1.0)

    def test_model_captured(self):
        sda = next(d for d in self.disks if d.name == "/dev/sda")
        self.assertIn("Samsung", sda.model)

    def test_empty_input_returns_empty(self):
        self.assertEqual(_parse_lsblk(""), [])


# ---------------------------------------------------------------------------
# _parse_ip_link
# ---------------------------------------------------------------------------

class TestParseIpLink(unittest.TestCase):

    def setUp(self):
        self.nics = _parse_ip_link(IP_LINK_JSON)

    def test_loopback_excluded(self):
        self.assertFalse(any(n.name == "lo" for n in self.nics))

    def test_bridge_excluded(self):
        self.assertFalse(any(n.name == "vmbr0" for n in self.nics))

    def test_physical_nics_included(self):
        names = [n.name for n in self.nics]
        self.assertIn("eno1", names)
        self.assertIn("eno2", names)

    def test_mac_captured(self):
        eno1 = next(n for n in self.nics if n.name == "eno1")
        self.assertEqual(eno1.mac, "aa:bb:cc:dd:ee:01")

    def test_state_captured(self):
        eno1 = next(n for n in self.nics if n.name == "eno1")
        self.assertEqual(eno1.state, "up")

    def test_invalid_json_returns_empty(self):
        self.assertEqual(_parse_ip_link("not-json"), [])


# ---------------------------------------------------------------------------
# Other parsers
# ---------------------------------------------------------------------------

class TestOtherParsers(unittest.TestCase):

    def test_meminfo_parses_correctly(self):
        ram = _parse_meminfo(MEMINFO)
        self.assertAlmostEqual(ram, 32.0, places=0)

    def test_meminfo_empty_returns_zero(self):
        self.assertEqual(_parse_meminfo(""), 0.0)

    def test_cpu_model_extracted(self):
        model = _parse_cpu_model(LSCPU)
        self.assertIn("i7-12700", model)

    def test_cpu_model_empty_returns_unknown(self):
        self.assertEqual(_parse_cpu_model(""), "(unknown)")

    def test_nproc_parses_integer(self):
        self.assertEqual(_parse_nproc("8\n"), 8)

    def test_nproc_invalid_returns_zero(self):
        self.assertEqual(_parse_nproc("not-a-number"), 0)


# ---------------------------------------------------------------------------
# zfs_topology_for_profile
# ---------------------------------------------------------------------------

class TestZfsTopology(unittest.TestCase):

    def _profile(self, n_disks: int) -> HardwareProfile:
        disks = [DiskInfo(f"/dev/sd{chr(97+i)}", 500, True) for i in range(n_disks)]
        return HardwareProfile("test", 4, "CPU", 32, disks=disks)

    def test_one_disk_stripe(self):
        self.assertEqual(zfs_topology_for_profile(self._profile(1)), "stripe")

    def test_two_disks_mirror(self):
        self.assertEqual(zfs_topology_for_profile(self._profile(2)), "mirror")

    def test_three_disks_raidz1(self):
        self.assertEqual(zfs_topology_for_profile(self._profile(3)), "raidz1")

    def test_four_disks_raidz2(self):
        self.assertEqual(zfs_topology_for_profile(self._profile(4)), "raidz2")

    def test_seven_disks_raidz3(self):
        self.assertEqual(zfs_topology_for_profile(self._profile(7)), "raidz3")


# ---------------------------------------------------------------------------
# HardwareProfile properties
# ---------------------------------------------------------------------------

class TestHardwareProfileProperties(unittest.TestCase):

    def setUp(self):
        self.profile = dict_to_hardware_profile({
            "hostname": "pve02",
            "cpu_cores": 8,
            "cpu_model": "Intel i7",
            "ram_gb": 32.0,
            "disks": [
                {"name": "/dev/sda", "size_gb": 500, "rotational": True,  "model": "HDD"},
                {"name": "/dev/sdb", "size_gb": 500, "rotational": True,  "model": "HDD"},
                {"name": "/dev/sdc", "size_gb": 250, "rotational": False, "model": "SSD"},
                {"name": "/dev/sdd", "size_gb": 1,   "rotational": True,  "model": "tiny"},  # < 10 GB
            ],
            "nics": [{"name": "eno1", "mac": "aa:bb:cc:dd:ee:01", "state": "up"}],
        })

    def test_disk_count_all(self):
        self.assertEqual(self.profile.disk_count, 4)

    def test_usable_disks_excludes_small(self):
        self.assertEqual(len(self.profile.usable_disks), 3)

    def test_hdd_count(self):
        self.assertEqual(self.profile.hdd_count, 2)

    def test_ssd_count(self):
        self.assertEqual(self.profile.ssd_count, 1)

    def test_total_disk_gb(self):
        self.assertAlmostEqual(self.profile.total_disk_gb, 1250.0, delta=1)


# ---------------------------------------------------------------------------
# discover_hardware with mocked SSH
# ---------------------------------------------------------------------------

class TestDiscoverHardware(unittest.TestCase):

    def _runner(self, success=True):
        if not success:
            return _mock_runner({})  # everything fails (rc=0, empty output)
        return _mock_runner({
            "hostname":     (0, "pve02\n", ""),
            "nproc":        (0, "8\n", ""),
            "lscpu":        (0, LSCPU, ""),
            "/proc/meminfo":(0, MEMINFO, ""),
            "lsblk":        (0, LSBLK_OUTPUT, ""),
            "ip -j link":   (0, IP_LINK_JSON, ""),
        })

    def test_successful_discovery(self):
        profile, errors = discover_hardware("192.168.1.50", runner_fn=self._runner(True))
        self.assertEqual(errors, [])
        self.assertEqual(profile.hostname, "pve02")
        self.assertEqual(profile.cpu_cores, 8)
        self.assertGreater(profile.ram_gb, 0)
        self.assertGreater(len(profile.disks), 0)

    def test_ssh_failure_returns_errors(self):
        def failing_runner(cmd, env=None):
            return 255, "", "Connection refused"
        profile, errors = discover_hardware("192.168.1.50", runner_fn=failing_runner)
        self.assertGreater(len(errors), 0)

    def test_profile_hostname_fallback_to_host_arg(self):
        def empty_runner(cmd, env=None):
            if "hostname" in " ".join(cmd):
                return 1, "", "error"
            return 0, "", ""
        profile, _ = discover_hardware("192.168.1.99", runner_fn=empty_runner)
        self.assertEqual(profile.hostname, "192.168.1.99")


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestSerialization(unittest.TestCase):

    def test_round_trip(self):
        profile = HardwareProfile(
            hostname="pve02", cpu_cores=8, cpu_model="i7", ram_gb=32.0,
            disks=[DiskInfo("/dev/sda", 500, True, "Model A")],
            nics=[NicInfo("eno1", "aa:bb:cc:dd:ee:01")],
        )
        d       = hardware_profile_to_dict(profile)
        rebuilt = dict_to_hardware_profile(d)
        self.assertEqual(rebuilt.hostname, profile.hostname)
        self.assertEqual(rebuilt.cpu_cores, profile.cpu_cores)
        self.assertEqual(len(rebuilt.disks), 1)
        self.assertEqual(rebuilt.disks[0].name, "/dev/sda")

    def test_dict_has_derived_fields(self):
        profile = HardwareProfile("h", 4, "CPU", 16,
                                  disks=[DiskInfo("/dev/sda", 500, True)])
        d = hardware_profile_to_dict(profile)
        self.assertIn("derived", d)
        self.assertIn("zfs_topology", d["derived"])
        self.assertEqual(d["derived"]["zfs_topology"], "stripe")

    def test_empty_profile_round_trip(self):
        profile = HardwareProfile("", 0, "", 0.0)
        d       = hardware_profile_to_dict(profile)
        rebuilt = dict_to_hardware_profile(d)
        self.assertEqual(rebuilt.hostname, "")
        self.assertEqual(rebuilt.disk_count, 0)


if __name__ == "__main__":
    unittest.main()
