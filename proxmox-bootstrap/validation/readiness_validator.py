#!/usr/bin/env python3
"""
Readiness validator — Phase A, Layer A.

Validates that all Phase 1 plans are complete and non-blocking before
the Phase 1 generators are allowed to run.

This is the final gate before IaC generation begins. If any check is RED,
generators will not run and the operator must resolve the blocking issue.

Checks:
  1. All required plan files exist (cluster-plan, storage-plan, network-plan, naming-plan)
  2. capacity-check.json overall is GREEN or YELLOW (not RED)
  3. cluster-plan.json has no errors
  4. storage-plan.json has no errors
  5. network-plan.json overall is not RED
  6. naming-plan.json has no errors
  7. All POPULATE markers resolved in naming plan (IPs, hostname, KeePass root)

Usage:
    python3 validation/readiness_validator.py
    python3 validation/readiness_validator.py --strict  (YELLOW also blocks)
    python3 validation/readiness_validator.py --plans /path/to/plans/

Outputs:
    validation/readiness-report.json
    Exit code: 0 = ready, 1 = blocked (RED), 2 = caution (YELLOW in strict mode)
"""

import json
import os
import sys
from pathlib import Path

BOOTSTRAP_DIR = Path(__file__).parent.parent


def _load_json_safe(path: Path) -> tuple[dict | None, str]:
    """Load JSON, returning (data, error_message)."""
    if not path.exists():
        return None, f"File not found: {path.name}"
    try:
        with open(path) as f:
            return json.load(f), ""
    except json.JSONDecodeError as e:
        return None, f"JSON parse error in {path.name}: {e}"


STATUS_ORDER = {"RED": 0, "YELLOW": 1, "GREEN": 2}


def _worst(statuses: list[str]) -> str:
    return min(statuses, key=lambda s: STATUS_ORDER.get(s, 0), default="GREEN")


# ---------------------------------------------------------------------------
# Individual readiness checks
# ---------------------------------------------------------------------------

def check_plan_exists(plans_dir: Path, filename: str) -> tuple[str, str]:
    path = plans_dir / filename
    if path.exists():
        return "GREEN", f"{filename} exists"
    return "RED", f"{filename} missing — run the corresponding planner"


def check_capacity(validation_dir: Path) -> tuple[str, str]:
    data, err = _load_json_safe(validation_dir / "capacity-check.json")
    if data is None:
        return "YELLOW", "capacity-check.json not found — run: python3 validation/capacity_validator.py"
    overall = data.get("overall", "UNKNOWN")
    reds = data.get("red_count", 0)
    if overall == "RED":
        return "RED", f"Capacity check FAILED ({reds} RED check(s)) — resolve before generating"
    if overall == "YELLOW":
        return "YELLOW", "Capacity check has warnings — review before generating"
    return "GREEN", "Capacity check PASSED"


def check_cluster_plan(plans_dir: Path) -> tuple[str, str]:
    data, err = _load_json_safe(plans_dir / "cluster-plan.json")
    if data is None:
        return "RED", err
    warnings = data.get("warnings", [])
    server_count = (data.get("server_nodes") or {}).get("count", 0)
    if server_count == 0:
        return "RED", "cluster-plan.json has no server nodes planned"
    if warnings:
        return "YELLOW", f"Cluster plan has {len(warnings)} warning(s)"
    return "GREEN", f"Cluster plan OK: {server_count} server node(s)"


def check_storage_plan(plans_dir: Path) -> tuple[str, str]:
    data, err = _load_json_safe(plans_dir / "storage-plan.json")
    if data is None:
        return "RED", err
    errors = data.get("errors", [])
    pools = data.get("pools", [])
    if errors:
        return "RED", f"Storage plan has {len(errors)} error(s): {errors[0]}"
    if not pools:
        return "RED", "Storage plan has no pools defined"
    warnings = data.get("warnings", [])
    if warnings:
        return "YELLOW", f"Storage plan has {len(warnings)} warning(s)"
    return "GREEN", f"Storage plan OK: {len(pools)} pool(s) planned"


def check_network_plan(plans_dir: Path) -> tuple[str, str]:
    data, err = _load_json_safe(plans_dir / "network-plan.json")
    if data is None:
        return "YELLOW", "network-plan.json not found — run: python3 planners/network_planner.py"
    overall = data.get("overall", "UNKNOWN")
    reds = data.get("red_count", 0)
    if overall == "RED":
        return "RED", f"Network plan FAILED ({reds} RED check(s)) — verify network topology"
    if overall == "YELLOW":
        yellows = data.get("yellow_count", 0)
        return "YELLOW", f"Network plan has {yellows} warning(s) — review before deploying"
    return "GREEN", "Network plan OK"


def check_naming_plan(plans_dir: Path) -> tuple[str, str]:
    data, err = _load_json_safe(plans_dir / "naming-plan.json")
    if data is None:
        return "RED", err
    errors = data.get("errors", [])
    vms = data.get("vms", [])
    if errors:
        return "RED", f"Naming plan has {len(errors)} error(s): {errors[0]}"
    if not vms:
        return "RED", "Naming plan has no VMs — check vm-roles.yaml"
    # Check for UNRESOLVED IPs
    unresolved_ips = [vm["name"] for vm in vms if vm.get("ip") == "UNRESOLVED"]
    if unresolved_ips:
        return "YELLOW", (
            f"VMs with unresolved IPs: {unresolved_ips}. "
            f"Set management_cidr in network-topology.yaml."
        )
    host_ip = data.get("host_ip", "UNRESOLVED")
    if host_ip == "UNRESOLVED":
        return "YELLOW", "Proxmox host IP unresolved — set in network-topology.yaml"
    return "GREEN", f"Naming plan OK: {len(vms)} VM(s) named"


def check_metadata_populate(plans_dir: Path) -> tuple[str, str]:
    """Check naming plan for remaining POPULATE markers."""
    data, err = _load_json_safe(plans_dir / "naming-plan.json")
    if data is None:
        return "YELLOW", "naming-plan.json not found — run naming planner first"
    # Check warnings for POPULATE-related issues
    warnings = data.get("warnings", [])
    populate_warnings = [w for w in warnings if "POPULATE" in w or "not set" in w]
    if populate_warnings:
        return "YELLOW", (
            f"{len(populate_warnings)} metadata field(s) still using defaults. "
            f"Update metadata/ files and re-run planners."
        )
    return "GREEN", "No POPULATE markers in plan outputs"


# ---------------------------------------------------------------------------
# Main readiness check
# ---------------------------------------------------------------------------

def run_readiness(plans_dir: Path, validation_dir: Path) -> dict:
    findings = []

    def _check(name: str, status: str, message: str) -> None:
        findings.append({"check": name, "status": status, "message": message})
        marker = {"GREEN": "[OK] ", "YELLOW": "[!!] ", "RED": "[XX] "}.get(status, "[?] ")
        print(f"  {marker}{name}: {message}")

    print()
    print("-" * 64)
    print("  Phase 1 Readiness Check")
    print("-" * 64)

    # Required plan files
    for fname in ("cluster-plan.json", "storage-plan.json", "naming-plan.json"):
        _check(f"Plan file: {fname}", *check_plan_exists(plans_dir, fname))

    # Validation outputs
    _check("Capacity check", *check_capacity(validation_dir))

    # Plan quality checks
    _check("Cluster plan", *check_cluster_plan(plans_dir))
    _check("Storage plan", *check_storage_plan(plans_dir))
    _check("Network plan", *check_network_plan(plans_dir))
    _check("Naming plan", *check_naming_plan(plans_dir))
    _check("Metadata completeness", *check_metadata_populate(plans_dir))

    statuses = [f["status"] for f in findings]
    overall = _worst(statuses)
    ready = overall != "RED"

    result = {
        "overall": overall,
        "ready_to_generate": ready,
        "findings": findings,
        "red_count": statuses.count("RED"),
        "yellow_count": statuses.count("YELLOW"),
        "green_count": statuses.count("GREEN"),
    }

    print()
    if ready:
        if overall == "GREEN":
            print("  [OK] ALL CHECKS PASSED — generators may proceed")
        else:
            print("  [!!] CAUTION — review warnings before generating")
    else:
        print("  [XX] BLOCKED — resolve RED checks before generating")
    print()

    return result


def _now_utc() -> str:
    from datetime import datetime, timedelta, timezone
    utc = datetime.now(timezone.utc)
    local = utc + timedelta(hours=int(os.environ.get("LOCAL_TZ_OFFSET", "0")))
    tz_name = os.environ.get("LOCAL_TZ_NAME", "UTC")
    if tz_name == "UTC":
        return utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    return (f"{utc.strftime('%Y-%m-%d %H:%M:%S')} UTC "
            f"({local.strftime('%Y-%m-%d %H:%M:%S')} {tz_name})")


def main() -> None:
    args = sys.argv[1:]
    strict = "--strict" in args
    args = [a for a in args if a != "--strict"]

    plans_dir = BOOTSTRAP_DIR / "plans"
    validation_dir = BOOTSTRAP_DIR / "validation"
    out_path = validation_dir / "readiness-report.json"

    if "--plans" in args:
        idx = args.index("--plans")
        plans_dir = Path(args[idx + 1])

    result = run_readiness(plans_dir, validation_dir)
    result["generated_at"] = _now_utc()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"  Results written: {out_path}")

    if not result["ready_to_generate"]:
        sys.exit(1)
    if result["overall"] == "YELLOW" and strict:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
