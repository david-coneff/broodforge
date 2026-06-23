"""Tests for Phase 2 parsers (hardware, storage, network, proxmox)."""




# Import parsers to trigger @register_parser decorators
import engine.modules  # noqa: F401
from engine.modules.hardware_parser import parse_hardware
from engine.modules.network_parser import parse_network
from engine.modules.proxmox_parser import parse_proxmox
from engine.modules.storage_parser import parse_storage

# ===========================================================================
# Hardware parser
# ===========================================================================

HW_RAW = {
    "cpu": {
        "model": "Intel(R) Xeon(R) E-2236",
        "vendor": "GenuineIntel",
        "sockets": 1,
        "cores_per_socket": 6,
        "threads_per_core": 2,
        "total_cores": 6,
        "total_threads": 12,
        "architecture": "x86_64",
        "flags": ["vmx", "aes", "avx2"],
    },
    "memory": {
        "total_bytes": 34359738368,
        "dimms": [
            {
                "slot": "DIMM_A1",
                "size_bytes": 17179869184,
                "type": "DDR4",
                "speed_mhz": 2666,
                "manufacturer": "Micron",
                "part_number": "MTA18ASF2G72PDZ",
                "ecc": True,
            }
        ],
        "ecc_enabled": True,
    },
    "system": {
        "Manufacturer": "Supermicro",
        "Product Name": "SYS-E300-9D",
        "Serial Number": "S123456",
        "UUID": "aaaabbbb-cccc-dddd-eeee-ffffgggghhhh",
    },
    "baseboard": {
        "Manufacturer": "Supermicro",
        "Product Name": "X11SCH-F",
        "Serial Number": "BB987",
        "Version": "1.01",
    },
}


def test_hw_cpu_model():
    result = parse_hardware(HW_RAW)
    assert result["hardware"]["cpu"]["model"] == "Intel(R) Xeon(R) E-2236"


def test_hw_cpu_flags():
    result = parse_hardware(HW_RAW)
    assert "vmx" in result["hardware"]["cpu"]["flags"]


def test_hw_memory_total():
    result = parse_hardware(HW_RAW)
    assert result["hardware"]["memory"]["total_bytes"] == 34359738368


def test_hw_memory_ecc():
    result = parse_hardware(HW_RAW)
    assert result["hardware"]["memory"]["ecc_enabled"] is True


def test_hw_dimm_count():
    result = parse_hardware(HW_RAW)
    assert len(result["hardware"]["memory"]["dimms"]) == 1


def test_hw_system_manufacturer():
    result = parse_hardware(HW_RAW)
    assert result["hardware"]["system"]["manufacturer"] == "Supermicro"


def test_hw_baseboard_product():
    result = parse_hardware(HW_RAW)
    assert result["hardware"]["baseboard"]["product_name"] == "X11SCH-F"


def test_hw_empty_raw():
    result = parse_hardware({})
    assert result == {}


def test_hw_partial_raw():
    result = parse_hardware({"cpu": {"model": "TestCPU", "total_cores": 4}})
    assert result["hardware"]["cpu"]["model"] == "TestCPU"
    assert "memory" not in result.get("hardware", {})


# ===========================================================================
# Storage parser
# ===========================================================================

STORAGE_RAW = {
    "disks": [
        {
            "name": "sda",
            "model": "Samsung 870 EVO",
            "serial": "S123",
            "size_bytes": 500107862016,
            "type": "SSD",
            "interface": "SATA",
            "wwn": "0x5002538e0x00aabb",
            "smart_status": "PASSED",
        },
        {
            "name": "nvme0n1",
            "model": "WD Black SN850",
            "serial": "WD999",
            "size_bytes": 1000204886016,
            "type": "NVMe",
            "interface": "NVME",
            "smart_status": "PASSED",
        },
    ],
    "zfs_pools": [
        {
            "name": "tank",
            "state": "ONLINE",
            "size_bytes": 8001563222016,
            "alloc_bytes": 2000390242304,
            "free_bytes": 6001172979712,
            "fragmentation_pct": 5.0,
            "dedup_ratio": 1.0,
            "health": "ONLINE",
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
}


def test_storage_disk_count():
    result = parse_storage(STORAGE_RAW)
    assert len(result["storage"]["disks"]) == 2


def test_storage_disk_fields():
    result = parse_storage(STORAGE_RAW)
    sda = result["storage"]["disks"][0]
    assert sda["name"] == "sda"
    assert sda["smart_status"] == "PASSED"
    assert sda["size_bytes"] == 500107862016


def test_storage_zfs_pool():
    result = parse_storage(STORAGE_RAW)
    pool = result["storage"]["zfs_pools"][0]
    assert pool["name"] == "tank"
    assert pool["health"] == "ONLINE"


def test_storage_lvm_vg():
    result = parse_storage(STORAGE_RAW)
    vg = result["storage"]["lvm_volume_groups"][0]
    assert vg["name"] == "pve"
    assert vg["lv_count"] == 3


def test_storage_empty_raw():
    result = parse_storage({})
    assert result == {}


def test_storage_no_zfs():
    raw = {"disks": STORAGE_RAW["disks"]}
    result = parse_storage(raw)
    assert "zfs_pools" not in result["storage"]


# ===========================================================================
# Network parser
# ===========================================================================

NET_RAW = {
    "interfaces": [
        {
            "name": "eth0",
            "mac": "aa:bb:cc:dd:ee:ff",
            "type": "physical",
            "mtu": 1500,
            "state": "UP",
            "speed_mbps": 1000,
            "addresses": [
                {"address": "192.168.1.10", "prefix_len": 24, "family": "inet"}
            ],
            "driver": "e1000e",
        },
        {
            "name": "vmbr0",
            "mac": "aa:bb:cc:dd:ee:ff",
            "type": "bridge",
            "mtu": 1500,
            "state": "UP",
            "bridge_members": ["eth0"],
            "addresses": [
                {"address": "192.168.1.1", "prefix_len": 24, "family": "inet"}
            ],
        },
        {
            "name": "lo",
            "mac": "00:00:00:00:00:00",
            "type": "loopback",
            "mtu": 65536,
            "state": "UP",
            "addresses": [
                {"address": "127.0.0.1", "prefix_len": 8, "family": "inet"}
            ],
        },
    ]
}


def test_network_interface_count():
    result = parse_network(NET_RAW)
    assert len(result["network"]["interfaces"]) == 3


def test_network_eth0_fields():
    result = parse_network(NET_RAW)
    eth0 = result["network"]["interfaces"][0]
    assert eth0["name"] == "eth0"
    assert eth0["state"] == "UP"
    assert eth0["driver"] == "e1000e"
    assert eth0["addresses"][0]["address"] == "192.168.1.10"


def test_network_bridge_members():
    result = parse_network(NET_RAW)
    vmbr0 = result["network"]["interfaces"][1]
    assert "eth0" in vmbr0["bridge_members"]


def test_network_empty_raw():
    result = parse_network({})
    assert result == {}


def test_network_empty_interfaces():
    result = parse_network({"interfaces": []})
    assert result == {}


# ===========================================================================
# Proxmox parser
# ===========================================================================

PVE_RAW = {
    "proxmox": {
        "version": "8.1.4",
        "kernel": "6.5.11-7-pve",
        "node_name": "pve01",
        "cluster_name": "homelab",
        "cluster_members": ["pve01", "pve02"],
    },
    "vms": [
        {"vmid": 100, "name": "debian12", "type": "qemu", "status": "running"},
        {"vmid": 200, "name": "ct-nginx", "type": "lxc", "status": "running"},
        {"vmid": 101, "name": "win11", "type": "qemu", "status": "stopped"},
    ],
    "storage_pools": [
        {
            "name": "local",
            "type": "dir",
            "content": ["iso", "vztmpl", "backup"],
            "enabled": True,
        },
        {
            "name": "local-zfs",
            "type": "zfspool",
            "content": ["images", "rootdir"],
            "enabled": True,
        },
    ],
}


def test_pve_version():
    result = parse_proxmox(PVE_RAW)
    assert result["virtualization"]["proxmox"]["version"] == "8.1.4"


def test_pve_cluster():
    result = parse_proxmox(PVE_RAW)
    pve = result["virtualization"]["proxmox"]
    assert pve["cluster_name"] == "homelab"
    assert "pve02" in pve["cluster_members"]


def test_pve_vm_count():
    result = parse_proxmox(PVE_RAW)
    assert len(result["virtualization"]["vms"]) == 3


def test_pve_vm_fields():
    result = parse_proxmox(PVE_RAW)
    vm = result["virtualization"]["vms"][0]
    assert vm["vmid"] == 100
    assert vm["type"] == "qemu"
    assert vm["status"] == "running"


def test_pve_storage_pools():
    result = parse_proxmox(PVE_RAW)
    pools = result["virtualization"]["storage_pools"]
    assert len(pools) == 2
    assert pools[1]["type"] == "zfspool"


def test_pve_empty_raw():
    result = parse_proxmox({})
    assert result == {}


def test_pve_no_cluster():
    raw = {
        "proxmox": {
            "version": "8.1.4",
            "kernel": "6.5.0-pve",
            "node_name": "standalone",
            "cluster_name": None,
            "cluster_members": [],
        }
    }
    result = parse_proxmox(raw)
    assert result["virtualization"]["proxmox"]["node_name"] == "standalone"


# ===========================================================================
# Integration: parse_raw_audit wires parsers end-to-end
# ===========================================================================

from engine.parser import parse_raw_audit


def test_end_to_end_assessment():
    raw = {
        "hardware": HW_RAW,
        "storage": STORAGE_RAW,
        "network": NET_RAW,
        "proxmox": PVE_RAW,
    }
    result = parse_raw_audit(raw)

    assert result["schema_version"] == "1.0"
    assert result["hardware"]["cpu"]["model"] == "Intel(R) Xeon(R) E-2236"
    assert len(result["storage"]["disks"]) == 2
    assert len(result["network"]["interfaces"]) == 3
    assert result["virtualization"]["proxmox"]["version"] == "8.1.4"


def test_end_to_end_failed_collector_skipped():
    raw = {
        "hardware": {"error": "dmidecode not found"},
        "storage": STORAGE_RAW,
    }
    result = parse_raw_audit(raw)
    assert "hardware" not in result
    assert len(result["storage"]["disks"]) == 2
