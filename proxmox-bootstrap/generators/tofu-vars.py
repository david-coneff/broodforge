#!/usr/bin/env python3
"""
OpenTofu variables generator — Phase B, Layer A.

Reads plans/ and generates terraform.auto.tfvars for each VM so that
the OpenTofu modules can provision VMs without any hard-coded values.

Outputs one file per VM:
    opentofu/environments/{vm_name}/terraform.auto.tfvars

Plus a shared cell-level file:
    opentofu/environments/cell.auto.tfvars

Usage:
    python3 generators/tofu-vars.py
    python3 generators/tofu-vars.py --plans plans/ --out opentofu/environments/
    python3 generators/tofu-vars.py --dry-run

Requires: plans/naming-plan.json, plans/cluster-plan.json, plans/storage-plan.json
Prerequisite: readiness_validator.py must pass (not RED)
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

BOOTSTRAP_DIR = Path(__file__).parent.parent


def _load_readiness_validator():
    spec = importlib.util.spec_from_file_location(
        "readiness_validator",
        BOOTSTRAP_DIR / "validation" / "readiness_validator.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _hcl_value(v) -> str:
    """Format a Python value as an HCL literal."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(v)
    if isinstance(v, list):
        items = ", ".join(_hcl_value(i) for i in v)
        return f"[{items}]"
    return f'"{v}"'


def _write_tfvars(path: Path, variables: dict, header: str = "") -> None:
    lines = []
    if header:
        for line in header.splitlines():
            lines.append(f"# {line}" if line.strip() else "#")
    lines.append("")
    max_key = max((len(k) for k in variables), default=0)
    for k, v in variables.items():
        lines.append(f"{k:<{max_key}} = {_hcl_value(v)}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Generation logic (testable without filesystem)
# ---------------------------------------------------------------------------

def generate_tofu_vars(
    naming_plan: dict,
    cluster_plan: dict,
    storage_plan: dict,
    network_plan: dict | None = None,
) -> dict[str, dict]:
    """
    Generate HCL variable maps for each VM and a shared cell-level map.

    Returns a dict keyed by output filename suffix (relative to environments/):
        {
            "cell.auto.tfvars": {...},
            "forgejo/terraform.auto.tfvars": {...},
            ...
        }
    """
    result: dict[str, dict] = {}

    cell_id = naming_plan.get("cell_id", "unknown-cell")
    hostname = naming_plan.get("hostname", "pve01")
    host_ip = naming_plan.get("host_ip", "UNRESOLVED")
    search_domain = naming_plan.get("search_domain", "internal")

    # Extract network info from naming plan (it carries what was validated)
    gateway = "UNRESOLVED"
    nameservers: list[str] = []
    if network_plan:
        validated = network_plan.get("validated_topology", {})
        gateway = validated.get("gateway", "UNRESOLVED")
        nameservers = validated.get("nameservers", [])

    # Storage pool names for Proxmox datastore references
    pools = storage_plan.get("pools", [])
    primary_pool = next(
        (p["name"] for p in pools if p.get("purpose") == "primary"),
        pools[0]["name"] if pools else "rpool",
    )
    datastores = storage_plan.get("recommended_datastores", [])
    vm_datastore = next(
        (d["name"] for d in datastores if d.get("use") == "vm_disks"),
        "local-lvm",
    )

    # Cell-level variables shared across all VM modules
    result["cell.auto.tfvars"] = {
        "cell_id": cell_id,
        "proxmox_host": hostname,
        "proxmox_host_ip": host_ip,
        "search_domain": search_domain,
        "gateway": gateway,
        "nameservers": nameservers,
        "primary_pool": primary_pool,
        "vm_datastore": vm_datastore,
    }

    # Per-VM variables
    # Resource overrides come from cluster_plan pre_k3s_vms / server_nodes
    pre_k3s_resources = cluster_plan.get("pre_k3s_vms", {})
    server_resources = cluster_plan.get("server_nodes", {})

    for vm in naming_plan.get("vms", []):
        name = vm["name"]
        role = vm.get("role", name)
        vmid = vm.get("vmid", 0)
        ip = vm.get("ip", "UNRESOLVED")
        cidr_notation = vm.get("cidr_notation", "UNRESOLVED")
        fqdn = vm.get("fqdn", f"{name}.{search_domain}")

        # Resource lookup: planner gives us per-role sizing
        if role in ("forgejo",):
            res = pre_k3s_resources.get("forgejo", {})
        elif role in ("operations", "operations-vm"):
            res = pre_k3s_resources.get("operations", {})
        elif role in ("k3s-server",):
            res = server_resources
        else:
            res = {}

        vcpus = res.get("vcpus_each", res.get("vcpus", 2))
        ram_mb = res.get("ram_mb_each", res.get("ram_mb", 2048))
        disk_gb = res.get("disk_gb_each", res.get("disk_gb", 20))

        result[f"{name}/terraform.auto.tfvars"] = {
            "cell_id": cell_id,
            "vm_name": name,
            "vmid": vmid,
            "role": role,
            "fqdn": fqdn,
            "vm_ip": ip,
            "vm_cidr": cidr_notation,
            "gateway": gateway,
            "nameservers": nameservers,
            "search_domain": search_domain,
            "vcpus": vcpus,
            "ram_mb": ram_mb,
            "disk_gb": disk_gb,
            "bridge": "vmbr0",
            "template": "ubuntu-2204-base",
            "vm_datastore": vm_datastore,
        }

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    plans_dir = BOOTSTRAP_DIR / "plans"
    out_dir = BOOTSTRAP_DIR.parent / "opentofu" / "environments"
    validation_dir = BOOTSTRAP_DIR / "validation"

    i = 0
    while i < len(args):
        if args[i] == "--plans" and i + 1 < len(args):
            plans_dir = Path(args[i + 1]); i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out_dir = Path(args[i + 1]); i += 2
        else:
            i += 1

    # Readiness gate
    rv = _load_readiness_validator()
    result = rv.run_readiness(plans_dir, validation_dir)
    if not result["ready_to_generate"]:
        print("ERROR: Readiness check FAILED — resolve RED checks before generating")
        sys.exit(1)

    naming_plan = _load_json(plans_dir / "naming-plan.json")
    cluster_plan = _load_json(plans_dir / "cluster-plan.json")
    storage_plan = _load_json(plans_dir / "storage-plan.json")
    network_plan = None
    network_path = plans_dir / "network-plan.json"
    if network_path.exists():
        network_plan = _load_json(network_path)

    outputs = generate_tofu_vars(naming_plan, cluster_plan, storage_plan, network_plan)

    cell_id = naming_plan.get("cell_id", "unknown-cell")
    generated_at = naming_plan.get("generated_at", "")
    header = f"Generated by tofu-vars.py — {generated_at}\nCell: {cell_id}\nDo not edit manually — re-run generators/tofu-vars.py"

    for rel_path, variables in outputs.items():
        dest = out_dir / rel_path
        if dry_run:
            print(f"  [dry-run] would write: {dest}")
            for k, v in variables.items():
                print(f"    {k} = {_hcl_value(v)}")
        else:
            _write_tfvars(dest, variables, header)
            print(f"  Written: {dest}")

    print(f"\ntofu-vars: {len(outputs)} file(s) generated")


if __name__ == "__main__":
    main()
