#!/usr/bin/env python3
"""
Capacity validator — Phase A, Layer A.

Validates that the discovered hardware meets the minimum requirements declared
in metadata/hardware-profile.yaml and that the cluster plan fits within
available resources.

A GREEN result is required before any VM provisioning begins.

Usage:
    python3 validation/capacity_validator.py
    python3 validation/capacity_validator.py --plan plans/cluster-plan.json
                                              --hardware discovery/hardware-report.json
                                              --metadata metadata/hardware-profile.yaml
    python3 validation/capacity_validator.py --strict   (fail on warnings, not just errors)

Outputs:
    validation/capacity-check.json    structured results
    Exit code: 0 = GREEN (pass), 1 = RED (fail), 2 = YELLOW (pass with warnings)
"""

import json
import os
import re
import sys
from pathlib import Path

BOOTSTRAP_DIR = Path(__file__).parent.parent


def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _load_yaml_value(path: Path, key: str, default=None):
    """Extract a single top-level value from a YAML file using text search."""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.split("#")[0].strip()
                if line.startswith(f"{key}:"):
                    val = line.split(":", 1)[1].strip().strip('"').strip("'")
                    if val.lower() == "true":
                        return True
                    if val.lower() == "false":
                        return False
                    try:
                        return int(val)
                    except ValueError:
                        try:
                            return float(val)
                        except ValueError:
                            return val or default
    except (OSError, IOError):
        pass
    return default


# ---------------------------------------------------------------------------
# Check functions — each returns (status, message)
# status: "GREEN", "YELLOW", "RED"
# ---------------------------------------------------------------------------

def check_ram(hardware: dict, min_ram_gb: int) -> tuple[str, str]:
    total_gb = (hardware.get("memory") or {}).get("total_gb") or 0
    if total_gb == 0:
        return "YELLOW", "RAM not detected — verify manually"
    if total_gb < min_ram_gb:
        return "RED", (f"RAM {total_gb}GB < minimum {min_ram_gb}GB required")
    if total_gb < min_ram_gb * 1.25:
        return "YELLOW", (f"RAM {total_gb}GB meets minimum {min_ram_gb}GB but headroom is low")
    return "GREEN", f"RAM {total_gb}GB >= minimum {min_ram_gb}GB"


def check_cpu(hardware: dict, min_cores: int) -> tuple[str, str]:
    threads = (hardware.get("cpu") or {}).get("total_threads") or 0
    if threads == 0:
        return "YELLOW", "CPU thread count not detected — verify manually"
    if threads < min_cores:
        return "RED", f"CPU threads {threads} < minimum {min_cores}"
    return "GREEN", f"CPU {threads} threads >= minimum {min_cores}"


def check_storage(hardware: dict, min_disk_gb: float) -> tuple[str, str]:
    disks = hardware.get("disks") or []
    if not disks:
        return "YELLOW", "No disks detected — verify manually"
    # Calculate approximate total usable capacity
    # Simple heuristic: sum of all disk sizes
    total_gb = sum(_disk_size_gb(d) for d in disks)
    if total_gb == 0:
        return "YELLOW", "Disk sizes not parseable — verify manually"
    if total_gb < min_disk_gb:
        return "RED", f"Total disk {total_gb:.0f}GB < minimum {min_disk_gb}GB"
    return "GREEN", f"Total disk {total_gb:.0f}GB >= minimum {min_disk_gb}GB"


def check_virtualization(hardware: dict, vtx_required: bool) -> tuple[str, str]:
    if not vtx_required:
        return "GREEN", "Virtualization not required by metadata"
    virt = (hardware.get("cpu") or {}).get("virtualization")
    if not virt:
        return "YELLOW", "Virtualization flag not detected — verify BIOS setting manually"
    return "GREEN", f"Virtualization detected: {virt}"


def check_nic_count(hardware: dict, min_nics: int = 1) -> tuple[str, str]:
    nics = hardware.get("nics") or []
    if len(nics) < min_nics:
        return "RED", f"NICs detected: {len(nics)}, minimum: {min_nics}"
    return "GREEN", f"NICs detected: {len(nics)}"


def check_plan_fits_ram(plan: dict) -> tuple[str, str]:
    total_vm_ram = plan.get("total_vm_ram_mb", 0)
    hw_ram = (plan.get("hardware_summary") or {}).get("total_ram_mb", 0)
    if hw_ram == 0:
        return "YELLOW", "Hardware RAM unknown — cannot verify plan fits"
    remaining = hw_ram - total_vm_ram
    pct_used = (total_vm_ram / hw_ram * 100) if hw_ram else 0
    if remaining < 0:
        return "RED", (f"Plan requires {total_vm_ram}MB RAM but only {hw_ram}MB available. "
                       f"Deficit: {abs(remaining)}MB")
    if pct_used > 85:
        return "YELLOW", (f"Plan uses {pct_used:.0f}% of RAM ({total_vm_ram}MB/{hw_ram}MB). "
                          f"Headroom: {remaining}MB — may be tight for workloads.")
    return "GREEN", (f"Plan uses {pct_used:.0f}% of RAM ({total_vm_ram}MB/{hw_ram}MB). "
                     f"Workload headroom: {remaining}MB")


def check_plan_warnings(plan: dict) -> tuple[str, str]:
    warnings = plan.get("warnings") or []
    if not warnings:
        return "GREEN", "Cluster plan has no warnings"
    return "YELLOW", f"Cluster plan has {len(warnings)} warning(s): {'; '.join(warnings[:2])}"


def _disk_size_gb(disk: dict) -> float:
    raw = disk.get("size_raw") or disk.get("size_bytes")
    if isinstance(raw, (int, float)):
        return raw / (1024 ** 3)
    if isinstance(raw, str):
        m = re.match(r"([\d.]+)([TGMK]?)B?$", raw.strip().upper())
        if m:
            v = float(m.group(1))
            u = m.group(2)
            return v * {"T": 1024, "G": 1, "M": 1/1024, "K": 1/1048576, "": 1}.get(u, 1)
    return 0.0


# ---------------------------------------------------------------------------
# Main validator
# ---------------------------------------------------------------------------

STATUS_ORDER = {"RED": 0, "YELLOW": 1, "GREEN": 2}
STATUS_EMOJI = {"GREEN": "[OK]", "YELLOW": "[!!]", "RED": "[XX]"}


def run_validation(hardware: dict, plan: dict | None,
                   hw_profile: Path | None) -> dict:
    """Run all checks and return structured results."""

    # Read minimums from hardware-profile metadata (fallback to sensible defaults)
    min_ram_gb = 16
    min_cores = 4
    min_disk_gb = 200.0
    vtx_required = True
    min_nics = 1

    if hw_profile and hw_profile.exists():
        # Dive into minimum_requirements section (text parsing)
        text = hw_profile.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.split("#")[0].strip()
            if "ram_gb:" in line:
                m = re.search(r"ram_gb:\s*(\d+)", line)
                if m:
                    min_ram_gb = int(m.group(1))
            elif "cpu_cores:" in line:
                m = re.search(r"cpu_cores:\s*(\d+)", line)
                if m:
                    min_cores = int(m.group(1))
            elif "storage_gb:" in line:
                m = re.search(r"storage_gb:\s*([\d.]+)", line)
                if m:
                    min_disk_gb = float(m.group(1))
            elif "vtx_required:" in line:
                vtx_required = "true" in line.lower()

    checks = []

    def _add(name: str, status: str, message: str) -> None:
        checks.append({"check": name, "status": status, "message": message})
        print(f"  [{STATUS_EMOJI[status]}] {name}: {message}")

    print()
    print("-" * 64)
    print("  Capacity Validation")
    print("-" * 64)

    _add("RAM", *check_ram(hardware, min_ram_gb))
    _add("CPU", *check_cpu(hardware, min_cores))
    _add("Storage", *check_storage(hardware, min_disk_gb))
    _add("Virtualization", *check_virtualization(hardware, vtx_required))
    _add("NIC count", *check_nic_count(hardware, min_nics))

    if plan:
        _add("Plan fits RAM", *check_plan_fits_ram(plan))
        _add("Plan warnings", *check_plan_warnings(plan))

    # Overall score
    statuses = [c["status"] for c in checks]
    if "RED" in statuses:
        overall = "RED"
    elif "YELLOW" in statuses:
        overall = "YELLOW"
    else:
        overall = "GREEN"

    result = {
        "overall": overall,
        "checks": checks,
        "red_count": statuses.count("RED"),
        "yellow_count": statuses.count("YELLOW"),
        "green_count": statuses.count("GREEN"),
    }

    print()
    print(f"  Overall: {STATUS_EMOJI[overall]} {overall}")
    if overall == "RED":
        print("  Deployment BLOCKED. Resolve RED checks before provisioning.")
    elif overall == "YELLOW":
        print("  Deployment ALLOWED with caution. Review YELLOW checks.")
    else:
        print("  Deployment READY.")
    print()

    return result


def main() -> None:
    args = sys.argv[1:]
    strict = "--strict" in args
    args = [a for a in args if a != "--strict"]

    hw_path = BOOTSTRAP_DIR / "discovery" / "hardware-report.json"
    plan_path = BOOTSTRAP_DIR / "plans" / "cluster-plan.json"
    meta_path = BOOTSTRAP_DIR / "metadata" / "hardware-profile.yaml"
    out_path = BOOTSTRAP_DIR / "validation" / "capacity-check.json"

    i = 0
    while i < len(args):
        if args[i] == "--hardware" and i + 1 < len(args):
            hw_path = Path(args[i + 1]); i += 2
        elif args[i] == "--plan" and i + 1 < len(args):
            plan_path = Path(args[i + 1]); i += 2
        elif args[i] == "--metadata" and i + 1 < len(args):
            meta_path = Path(args[i + 1]); i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out_path = Path(args[i + 1]); i += 2
        else:
            i += 1

    if not hw_path.exists():
        print(f"Hardware report not found: {hw_path}")
        print("Run: python3 discovery/discover.py --collector hardware")
        sys.exit(1)

    hardware = _load_json(hw_path)
    plan = _load_json(plan_path) if plan_path.exists() else None

    result = run_validation(hardware, plan, meta_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"  Results written: {out_path}")

    if result["overall"] == "RED":
        sys.exit(1)
    elif result["overall"] == "YELLOW" and strict:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
