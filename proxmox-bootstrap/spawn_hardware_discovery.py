#!/usr/bin/env python3
"""
spawn_hardware_discovery.py — Hardware discovery for broodling spawn (Phase 12.E.4).

Runs from the operator's workstation (or hatchery) against a fresh broodling
via SSH to produce a hardware-profile-{hostname}.json that the spawn planner
uses to adapt the spawn package to the actual hardware.

Provides:
  HardwareProfile       — typed hardware description
  DiskInfo / NicInfo    — component sub-types
  discover_hardware(host, user, port, key, runner_fn) → HardwareProfile
  hardware_profile_to_dict(profile) → dict (for JSON serialization)
  dict_to_hardware_profile(d) → HardwareProfile (for JSON deserialization)
  zfs_topology_for_profile(profile) → str  (mirror / raidz1 / etc.)

Discovery is SSH-based: connects to the broodling, runs a set of read-only
shell commands, and parses the output. All subprocess calls are injectable
for testing without a live host.

Stdlib only.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class DiskInfo:
    name:       str               # e.g. /dev/sda
    size_gb:    float
    rotational: bool              # True = HDD, False = SSD
    model:      str = ""
    serial:     str = ""

    def is_ssd(self) -> bool:
        return not self.rotational


@dataclass
class NicInfo:
    name:  str                    # e.g. eno1
    mac:   str
    speed: Optional[int] = None   # Mbps; None if unknown
    state: str = "unknown"        # up | down | unknown


@dataclass
class HardwareProfile:
    hostname:   str
    cpu_cores:  int
    cpu_model:  str
    ram_gb:     float
    disks:      list[DiskInfo] = field(default_factory=list)
    nics:       list[NicInfo]  = field(default_factory=list)

    @property
    def disk_count(self) -> int:
        return len(self.disks)

    @property
    def usable_disks(self) -> list[DiskInfo]:
        """Disks larger than 10 GB (excludes boot media residue)."""
        return [d for d in self.disks if d.size_gb >= 10]

    @property
    def ssd_count(self) -> int:
        return sum(1 for d in self.usable_disks if d.is_ssd())

    @property
    def hdd_count(self) -> int:
        return sum(1 for d in self.usable_disks if not d.is_ssd())

    @property
    def total_disk_gb(self) -> float:
        return sum(d.size_gb for d in self.usable_disks)


# ---------------------------------------------------------------------------
# ZFS topology recommendation
# ---------------------------------------------------------------------------

def zfs_topology_for_profile(profile: HardwareProfile) -> str:
    """Return the recommended ZFS pool topology for this hardware profile."""
    n = len(profile.usable_disks)
    if n <= 1: return "stripe"
    if n == 2: return "mirror"
    if n == 3: return "raidz1"
    if n <= 6: return "raidz2"
    return "raidz3"


# ---------------------------------------------------------------------------
# SSH runner default
# ---------------------------------------------------------------------------

def _default_ssh_run(cmd: list, env=None) -> tuple[int, str, str]:
    import os
    full_env = {**os.environ, **env} if env else None
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30, env=full_env,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Parsers for command output
# ---------------------------------------------------------------------------

def _parse_lsblk(output: str) -> list[DiskInfo]:
    """
    Parse `lsblk -bno NAME,SIZE,ROTA,MODEL` output.
    Only top-level block devices (no partitions/children).
    """
    disks = []
    for line in output.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        name   = parts[0].strip()
        # Skip partitions and LVM volumes (contain digits in non-standard position)
        if re.search(r'\d', name) and not name.startswith("sd") and not name.startswith("nvme"):
            continue
        # Skip partitions: sdaN, sdbN, nvme0n1pN etc.
        if re.match(r'^(sd[a-z]+\d|nvme\d+n\d+p\d+)', name):
            continue
        try:
            size_bytes = int(parts[1].strip())
            rotational = parts[2].strip() == "1"
            model      = parts[3].strip() if len(parts) > 3 else ""
            size_gb    = round(size_bytes / (1024 ** 3), 1)
            disks.append(DiskInfo(
                name=f"/dev/{name}",
                size_gb=size_gb,
                rotational=rotational,
                model=model,
            ))
        except (ValueError, IndexError):
            continue
    return disks


def _parse_ip_link(output: str) -> list[NicInfo]:
    """
    Parse `ip -j link show` JSON output.
    Returns only physical NICs (skips lo, bridge, veth, vmbr*, bond*).
    """
    SKIP_PATTERNS = re.compile(r'^(lo|veth|vmbr|bond|docker|br-|dummy)')
    nics = []
    try:
        entries = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return []

    for entry in entries:
        ifname = entry.get("ifname", "")
        if SKIP_PATTERNS.match(ifname):
            continue
        link_type = entry.get("link_type", "")
        if link_type not in ("ether",):
            continue
        mac   = entry.get("address", "")
        state = entry.get("operstate", "unknown").lower()
        nics.append(NicInfo(name=ifname, mac=mac, state=state))
    return nics


def _parse_nproc(output: str) -> int:
    try:
        return int(output.strip())
    except (ValueError, TypeError):
        return 0


def _parse_cpu_model(output: str) -> str:
    for line in output.splitlines():
        if "Model name" in line:
            return line.split(":", 1)[1].strip()
    return "(unknown)"


def _parse_meminfo(output: str) -> float:
    for line in output.splitlines():
        if line.startswith("MemTotal:"):
            kb = int(line.split()[1])
            return round(kb / (1024 ** 2), 1)
    return 0.0


def _parse_hostname(output: str) -> str:
    return output.strip()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_hardware(
    host: str,
    user: str = "root",
    port: int = 22,
    key: Optional[str] = None,
    password: Optional[str] = None,
    runner_fn: Optional[Callable] = None,
) -> tuple[HardwareProfile, list[str]]:
    """
    SSH into the broodling and collect hardware information.

    Returns (HardwareProfile, list_of_errors).
    Errors are collection issues — a partial profile is returned even on errors.

    runner_fn: injectable for tests — fn(cmd, env) → (returncode, stdout, stderr)
    """
    run = runner_fn or _default_ssh_run
    errors: list[str] = []

    def _ssh(remote_cmd: str) -> tuple[bool, str]:
        """Run a command on the remote host. Returns (ok, stdout)."""
        ssh_env = None
        if password:
            # Password auth via sshpass. The password is passed through the
            # SSHPASS env var (read by `sshpass -e`), never on argv, so it does
            # not leak via ps/aux. BatchMode is omitted so the password is used.
            cmd = ["sshpass", "-e", "ssh",
                   "-o", "StrictHostKeyChecking=accept-new",
                   "-p", str(port)]
            ssh_env = {"SSHPASS": password}
        else:
            cmd = ["ssh",
                   "-o", "StrictHostKeyChecking=accept-new",
                   "-o", "BatchMode=yes",
                   "-p", str(port)]
        if key:
            cmd += ["-i", key]
        cmd += [f"{user}@{host}", remote_cmd]
        rc, out, err = run(cmd, ssh_env)
        if rc != 0:
            errors.append(f"Command '{remote_cmd}' failed (exit {rc}): {err.strip()}")
            return False, ""
        return True, out

    # Hostname
    ok, out = _ssh("hostname")
    hostname = _parse_hostname(out) if ok else host

    # CPU
    ok, out = _ssh("nproc")
    cpu_cores = _parse_nproc(out) if ok else 0

    ok, out = _ssh("lscpu")
    cpu_model = _parse_cpu_model(out) if ok else "(unknown)"

    # RAM
    ok, out = _ssh("cat /proc/meminfo")
    ram_gb = _parse_meminfo(out) if ok else 0.0

    # Disks
    ok, out = _ssh("lsblk -bno NAME,SIZE,ROTA,MODEL")
    disks = _parse_lsblk(out) if ok else []

    # NICs
    ok, out = _ssh("ip -j link show")
    nics = _parse_ip_link(out) if ok else []

    profile = HardwareProfile(
        hostname=hostname,
        cpu_cores=cpu_cores,
        cpu_model=cpu_model,
        ram_gb=ram_gb,
        disks=disks,
        nics=nics,
    )

    return profile, errors


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def hardware_profile_to_dict(profile: HardwareProfile) -> dict:
    return {
        "hostname":  profile.hostname,
        "cpu_cores": profile.cpu_cores,
        "cpu_model": profile.cpu_model,
        "ram_gb":    profile.ram_gb,
        "disks": [
            {"name": d.name, "size_gb": d.size_gb,
             "rotational": d.rotational, "model": d.model, "serial": d.serial}
            for d in profile.disks
        ],
        "nics": [
            {"name": n.name, "mac": n.mac, "speed": n.speed, "state": n.state}
            for n in profile.nics
        ],
        "derived": {
            "disk_count":      profile.disk_count,
            "usable_disks":    len(profile.usable_disks),
            "ssd_count":       profile.ssd_count,
            "hdd_count":       profile.hdd_count,
            "total_disk_gb":   profile.total_disk_gb,
            "zfs_topology":    zfs_topology_for_profile(profile),
        },
    }


def dict_to_hardware_profile(d: dict) -> HardwareProfile:
    disks = [
        DiskInfo(
            name=disk["name"], size_gb=disk["size_gb"],
            rotational=disk["rotational"], model=disk.get("model",""),
            serial=disk.get("serial",""),
        )
        for disk in (d.get("disks") or [])
    ]
    nics = [
        NicInfo(
            name=nic["name"], mac=nic["mac"],
            speed=nic.get("speed"), state=nic.get("state","unknown"),
        )
        for nic in (d.get("nics") or [])
    ]
    return HardwareProfile(
        hostname=d.get("hostname",""),
        cpu_cores=d.get("cpu_cores", 0),
        cpu_model=d.get("cpu_model",""),
        ram_gb=d.get("ram_gb", 0.0),
        disks=disks,
        nics=nics,
    )


# ---------------------------------------------------------------------------
# CLI — used by NODE-SPAWNING.md autonomous Step 2 (hardware discovery)
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import getpass
    import shutil
    import sys

    ap = argparse.ArgumentParser(
        description="Discover a broodling's hardware over SSH and write a "
                    "hardware-profile JSON for the spawn planner.",
    )
    ap.add_argument("--host", required=True, help="Broodling IP or hostname")
    ap.add_argument("--user", default="root", help="SSH user (default: root)")
    ap.add_argument("--port", type=int, default=22, help="SSH port (default: 22)")
    ap.add_argument("--key", default=None, help="SSH private key path (key-based auth)")
    ap.add_argument("--password", default=None,
                    help="SSH password (prefer --password-prompt; requires sshpass)")
    ap.add_argument("--password-prompt", action="store_true", dest="password_prompt",
                    help="Prompt for the SSH password (requires sshpass on this machine)")
    ap.add_argument("--output", required=True, help="Output hardware-profile JSON path")
    args = ap.parse_args()

    password = args.password
    if args.password_prompt:
        password = getpass.getpass(f"SSH password for {args.user}@{args.host}: ")

    if password and shutil.which("sshpass") is None:
        print("[discover] ERROR: password authentication requires 'sshpass' "
              "(e.g. 'apt install sshpass'); alternatively use --key for key-based SSH.",
              file=sys.stderr)
        sys.exit(2)

    profile, errors = discover_hardware(
        host=args.host, user=args.user, port=args.port, key=args.key, password=password,
    )
    for e in errors:
        print(f"[discover] WARNING: {e}", file=sys.stderr)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(hardware_profile_to_dict(profile), f, indent=2)

    print(f"[discover] hardware profile written to {args.output} "
          f"({profile.cpu_cores} cores, {profile.ram_gb:.1f} GB RAM, "
          f"{len(profile.disks)} disks, {len(profile.nics)} NICs)")
    if errors:
        print(f"[discover] {len(errors)} collection warning(s) — profile may be partial.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
