#!/usr/bin/env python3
"""
Cloud-Init snippet generator — Phase B, Layer A.

Reads plans/ and generates per-VM Cloud-Init user-data and network-config
snippets ready for upload to Proxmox as snippets storage entries.

Delegates to the existing generators in proxmox-bootstrap/:
    generate-user-data.py     — cloud-init user-data (packages, SSH keys, runcmd)
    generate-network-configs.py — cloud-init network-config (static IP)

Outputs:
    snippets/{vm_name}-user-data.yaml
    snippets/{vm_name}-network-config.yaml

Usage:
    python3 generators/cloud-init-gen.py
    python3 generators/cloud-init-gen.py --plans plans/ --out snippets/
    python3 generators/cloud-init-gen.py --dry-run

Requires: plans/naming-plan.json, plans/network-plan.json (optional)
Prerequisite: readiness_validator.py must pass (not RED)
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

BOOTSTRAP_DIR = Path(__file__).parent.parent


def _load_module(rel_path: str, mod_name: str):
    spec = importlib.util.spec_from_file_location(
        mod_name, BOOTSTRAP_DIR / rel_path
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Bootstrap-state bridge
# ---------------------------------------------------------------------------

def _naming_plan_to_bootstrap_state(naming_plan: dict, network_plan: dict | None) -> dict:
    """
    Translate naming-plan.json into the bootstrap-state.json format that
    generate-user-data.py and generate-network-configs.py expect.

    This bridges Phase 2 plan outputs to the legacy bootstrap-state schema
    without requiring any changes to the existing generators.
    """
    cell_id = naming_plan.get("cell_id", "unknown-cell")
    hostname = naming_plan.get("hostname", "pve01")
    search_domain = naming_plan.get("search_domain", "internal")
    host_ip = naming_plan.get("host_ip", "UNRESOLVED")
    kp_root = naming_plan.get("kp_root", "Infrastructure")

    gateway = "UNRESOLVED"
    nameservers = ["8.8.8.8"]
    if network_plan:
        validated = network_plan.get("validated_topology", {})
        gateway = validated.get("gateway", "UNRESOLVED")
        nameservers = validated.get("nameservers", ["8.8.8.8"])

    vms = []
    for vm in naming_plan.get("vms", []):
        vms.append({
            "name": vm["name"],
            "vmid": vm.get("vmid", 0),
            "role": vm.get("role", vm["name"]),
            "initial_ip": vm.get("ip", "UNRESOLVED"),
            "fqdn": vm.get("fqdn", f"{vm['name']}.{search_domain}"),
            "initial_user": "ubuntu",
            "extra_packages": [],
            "workspace_path": f"/opt/{cell_id}",
            "ssh_key_reference": f"{kp_root}/VMs/{vm['name']}/SSH",
        })

    return {
        "cell_id": cell_id,
        "host_identity": {
            "hostname": hostname,
            "ip": host_ip,
        },
        "network_topology": {
            "search_domain": search_domain,
            "gateway": gateway,
            "nameservers": nameservers,
        },
        "vm_defaults": {
            "timezone": "UTC",
            "initial_user": "ubuntu",
            "workspace_base_path": f"/opt/{cell_id}",
        },
        "keepass_config": {
            "root_path": kp_root,
        },
        "vms": vms,
        "secret_registry": naming_plan.get("secret_registry", []),
    }


# ---------------------------------------------------------------------------
# Generation logic (testable without filesystem)
# ---------------------------------------------------------------------------

def generate_cloud_init(
    naming_plan: dict,
    network_plan: dict | None = None,
) -> dict[str, str]:
    """
    Generate Cloud-Init YAML strings for each VM.

    Returns dict keyed by output filename:
        {
            "forgejo-user-data.yaml": "...",
            "forgejo-network-config.yaml": "...",
            ...
        }
    """
    bootstrap_state = _naming_plan_to_bootstrap_state(naming_plan, network_plan)

    try:
        ud_mod = _load_module("generate-user-data.py", "generate_user_data")
        nc_mod = _load_module("generate-network-configs.py", "generate_network_configs")
    except Exception as e:
        raise RuntimeError(f"Failed to load existing generators: {e}") from e

    search_domain = bootstrap_state["network_topology"]["search_domain"]
    gateway = bootstrap_state["network_topology"]["gateway"]
    nameservers = bootstrap_state["network_topology"]["nameservers"]

    result: dict[str, str] = {}

    for vm in bootstrap_state["vms"]:
        # user-data
        try:
            user_data = ud_mod.generate_user_data(vm, bootstrap_state)
            result[f"{vm['name']}-user-data.yaml"] = user_data
        except Exception as e:
            result[f"{vm['name']}-user-data.yaml"] = (
                f"# ERROR generating user-data for {vm['name']}: {e}\n"
            )

        # network-config
        try:
            network_config = nc_mod.generate_network_config(
                vm_name=vm["name"],
                ip_address=vm["initial_ip"],
                gateway=gateway,
                nameservers=nameservers,
                search_domain=search_domain,
            )
            result[f"{vm['name']}-network-config.yaml"] = network_config
        except Exception as e:
            result[f"{vm['name']}-network-config.yaml"] = (
                f"# ERROR generating network-config for {vm['name']}: {e}\n"
            )

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]

    plans_dir = BOOTSTRAP_DIR / "plans"
    out_dir = BOOTSTRAP_DIR / "snippets"
    validation_dir = BOOTSTRAP_DIR / "validation"

    i = 0
    while i < len(args):
        if args[i] == "--plans" and i + 1 < len(args):
            plans_dir = Path(args[i + 1]); i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out_dir = Path(args[i + 1]); i += 2
        else:
            i += 1

    rv = _load_module("validation/readiness_validator.py", "readiness_validator")
    result = rv.run_readiness(plans_dir, validation_dir)
    if not result["ready_to_generate"]:
        print("ERROR: Readiness check FAILED — resolve RED checks before generating")
        sys.exit(1)

    naming_plan = _load_json(plans_dir / "naming-plan.json")
    network_plan = None
    network_path = plans_dir / "network-plan.json"
    if network_path.exists():
        network_plan = _load_json(network_path)

    outputs = generate_cloud_init(naming_plan, network_plan)

    for filename, content in outputs.items():
        dest = out_dir / filename
        if dry_run:
            print(f"  [dry-run] would write: {dest}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            print(f"  Written: {dest}")

    print(f"\ncloud-init-gen: {len(outputs)} file(s) generated")
    if any("ERROR" in c for c in outputs.values()):
        print("  WARNING: some snippets contain errors — check output files")


if __name__ == "__main__":
    main()
