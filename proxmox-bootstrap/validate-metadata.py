#!/usr/bin/env python3
"""
Metadata YAML validator.

Validates all files in proxmox-bootstrap/metadata/ against their required
structure. Checks required keys, POPULATE markers, cross-file consistency,
and naming convention compliance.

Usage:
    python3 proxmox-bootstrap/validate-metadata.py
    python3 proxmox-bootstrap/validate-metadata.py --file metadata/cell-identity.yaml
    python3 proxmox-bootstrap/validate-metadata.py --check-populate
        (flags all POPULATE fields that still need human input)

Requirements: PyYAML  (pip install pyyaml)
Fallback:     Without PyYAML, runs structural checks via text scanning only.
"""

import re
import sys
from pathlib import Path

METADATA_DIR = Path(__file__).parent / "metadata"
BOOTSTRAP_DIR = Path(__file__).parent

# Try to import PyYAML; fall back to text-only checks
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ---------------------------------------------------------------------------
# Required key specifications per metadata file
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {
    "cell-identity.yaml": [
        "cell_id", "cell_name", "cell_type", "federation_id",
        "federation_role", "criticality", "recovery_priority",
        "architecture_version", "repositories", "capabilities",
    ],
    "hardware-profile.yaml": [
        "minimum_requirements", "declared_hardware",
        "assessment_thresholds",
    ],
    "network-topology.yaml": [
        "management_network", "proxmox_host", "bridges",
        "vm_nic_interface", "k3s_networking", "dns_registry",
    ],
    "vm-roles.yaml": [
        "consolidation_mode", "vmid_base", "pre_k3s_vms", "k3s_vms",
        "resource_summary",
    ],
    "k3s-cluster.yaml": [
        "cluster_name", "ha_policy", "server_nodes", "storage",
        "networking", "deployment_waves", "etcd",
    ],
    "service-catalog.yaml": [
        "platform_vms", "k3s_platform", "k3s_intelligence",
        "k3s_monitoring",
    ],
    "backup-policy.yaml": [
        "backup_providers", "components", "rrs_thresholds",
    ],
    "recovery-priority.yaml": [
        "recovery_phases", "rto_targets", "single_points_of_failure",
    ],
    "placement-policy.yaml": [
        "proxmox_placement", "k3s_placement", "compliance_checks",
    ],
    "naming-convention.yaml": [
        "cell", "proxmox_hosts", "vms", "hostnames",
        "ip_assignments", "keepass_paths", "repositories",
        "archive_filenames",
    ],
}

REQUIRED_FILES = list(REQUIRED_KEYS.keys())


# ---------------------------------------------------------------------------
# POPULATE marker detection
# ---------------------------------------------------------------------------

def find_populate_fields(text: str, filename: str) -> list[tuple[int, str]]:
    """Return list of (line_number, line_text) for all POPULATE markers."""
    findings = []
    for i, line in enumerate(text.splitlines(), 1):
        if "POPULATE:" in line or "POPULATE " in line:
            findings.append((i, line.strip()))
    return findings


# ---------------------------------------------------------------------------
# YAML-based validation
# ---------------------------------------------------------------------------

def validate_yaml_keys(data: dict, required_keys: list[str],
                       filename: str) -> list[str]:
    """Check that all required top-level keys are present."""
    errors = []
    for key in required_keys:
        if key not in data:
            errors.append(f"  MISSING required key: '{key}'")
    return errors


def validate_cell_identity(data: dict) -> list[str]:
    """Additional validation for cell-identity.yaml."""
    errors = []
    cell_id = data.get("cell_id", "")
    if cell_id and not re.match(r'^[a-z0-9][a-z0-9-]*[a-z0-9]$', cell_id):
        errors.append(f"  cell_id '{cell_id}' must be kebab-case (lowercase, hyphens only)")
    if data.get("recovery_priority") is not None:
        try:
            p = int(data["recovery_priority"])
            if p < 1:
                errors.append("  recovery_priority must be >= 1")
        except (TypeError, ValueError):
            errors.append("  recovery_priority must be an integer")
    return errors


def validate_k3s_cluster(data: dict) -> list[str]:
    """Additional validation for k3s-cluster.yaml."""
    errors = []
    ha_policy = data.get("ha_policy", {})
    if ha_policy:
        threshold = ha_policy.get("control_plane_ha_threshold")
        if threshold is not None and threshold < 3:
            errors.append("  ha_policy.control_plane_ha_threshold must be >= 3 (etcd quorum)")
    return errors


def validate_backup_policy(data: dict) -> list[str]:
    """Additional validation for backup-policy.yaml."""
    errors = []
    components = data.get("components", [])
    for comp in components:
        name = comp.get("name", "?")
        rpo = comp.get("rpo_hours")
        strategy = comp.get("recovery_strategy", "")
        if strategy == "RESTORE" and rpo is None:
            errors.append(f"  Component '{name}': RESTORE strategy requires rpo_hours")
    return errors


EXTRA_VALIDATORS = {
    "cell-identity.yaml": validate_cell_identity,
    "k3s-cluster.yaml": validate_k3s_cluster,
    "backup-policy.yaml": validate_backup_policy,
}


# ---------------------------------------------------------------------------
# Cross-file consistency checks
# ---------------------------------------------------------------------------

def cross_file_checks(all_data: dict[str, dict]) -> list[str]:
    """Validate consistency between metadata files."""
    errors = []

    all_data.get("cell-identity.yaml", {})
    network = all_data.get("network-topology.yaml", {})
    k3s = all_data.get("k3s-cluster.yaml", {})
    naming = all_data.get("naming-convention.yaml", {})

    # network-topology search_domain should match k3s hostnames pattern
    search_domain = (network.get("management_network") or {}).get("search_domain")
    if search_domain and naming:
        naming_sd = (naming.get("hostnames") or {}).get("search_domain")
        if naming_sd and naming_sd != search_domain:
            errors.append(
                f"  INCONSISTENCY: network-topology.yaml search_domain='{search_domain}' "
                f"!= naming-convention.yaml hostnames.search_domain='{naming_sd}'"
            )

    # k3s networking cidrs should not overlap with management network
    mgmt_cidr = (network.get("management_network") or {}).get("cidr", "")
    k3s_net = k3s.get("networking", {})
    pod_cidr = k3s_net.get("pod_cidr", "")
    k3s_net.get("service_cidr", "")
    if mgmt_cidr and "POPULATE" not in mgmt_cidr:
        if pod_cidr and not pod_cidr.startswith("10.") and mgmt_cidr.startswith(pod_cidr.split(".")[0]):
            errors.append(f"  POTENTIAL OVERLAP: pod_cidr '{pod_cidr}' may overlap with mgmt '{mgmt_cidr}'")

    return errors


# ---------------------------------------------------------------------------
# Text-only fallback checks (no PyYAML)
# ---------------------------------------------------------------------------

def text_check_required_keys(text: str, required_keys: list[str],
                              filename: str) -> list[str]:
    """Minimal check: verify required keys appear in the file text."""
    errors = []
    for key in required_keys:
        pattern = rf"^{re.escape(key)}\s*:"
        if not re.search(pattern, text, re.MULTILINE):
            errors.append(f"  MISSING required key (text check): '{key}'")
    return errors


# ---------------------------------------------------------------------------
# Main validator
# ---------------------------------------------------------------------------

def validate_file(filepath: Path, check_populate: bool = False) -> tuple[bool, list[str]]:
    filename = filepath.name
    findings = []

    if not filepath.exists():
        return False, [f"  FILE NOT FOUND: {filepath}"]

    text = filepath.read_text(encoding="utf-8")

    # POPULATE check
    if check_populate:
        populates = find_populate_fields(text, filename)
        if populates:
            findings.append(f"  {len(populates)} POPULATE field(s) require human input:")
            for lineno, line in populates[:5]:
                findings.append(f"    Line {lineno}: {line[:80]}")
            if len(populates) > 5:
                findings.append(f"    ... and {len(populates) - 5} more")

    required = REQUIRED_KEYS.get(filename, [])

    if HAS_YAML:
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            return False, [f"  YAML PARSE ERROR: {e}"]

        findings.extend(validate_yaml_keys(data, required, filename))

        # Extra validators
        if filename in EXTRA_VALIDATORS:
            findings.extend(EXTRA_VALIDATORS[filename](data))

        return len([f for f in findings if "MISSING" in f or "ERROR" in f or
                    "INCONSISTENCY" in f or "OVERLAP" in f]) == 0, findings
    else:
        findings.extend(text_check_required_keys(text, required, filename))
        return len([f for f in findings if "MISSING" in f]) == 0, findings


def main():
    args = sys.argv[1:]
    check_populate = "--check-populate" in args
    args = [a for a in args if a != "--check-populate"]

    specific_file = None
    if "--file" in args:
        idx = args.index("--file")
        specific_file = Path(args[idx + 1])

    if not HAS_YAML:
        print("WARNING: PyYAML not installed. Running text-only structural checks.")
        print("         Install with: pip install pyyaml")
        print()

    if specific_file:
        files_to_check = [specific_file]
    else:
        files_to_check = [METADATA_DIR / f for f in REQUIRED_FILES]

    print("=" * 60)
    print("  Metadata Validation")
    print(f"  Directory: {METADATA_DIR}")
    print("=" * 60)
    print()

    overall_ok = True
    populate_count = 0
    all_data = {}

    for filepath in files_to_check:
        ok, findings = validate_file(filepath, check_populate)
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {filepath.name}")
        for finding in findings:
            print(finding)
            if "POPULATE" in finding:
                populate_count += 1
        if not ok:
            overall_ok = False

    # Cross-file consistency (YAML only)
    if HAS_YAML and not specific_file:
        print()
        print("  Cross-file consistency:")
        for filepath in files_to_check:
            if filepath.exists():
                try:
                    text = filepath.read_text(encoding="utf-8")
                    all_data[filepath.name] = yaml.safe_load(text) or {}
                except Exception as e:
                    print(f"  [WARN] Could not parse {filepath.name}: {e}")
        cross_errors = cross_file_checks(all_data)
        if cross_errors:
            print("  [WARN] Consistency issues found:")
            for e in cross_errors:
                print(e)
        else:
            print("  [PASS] No cross-file inconsistencies detected")

    print()
    if check_populate:
        print(f"  POPULATE fields requiring human input: {populate_count}")
    print(f"  Overall: {'PASS' if overall_ok else 'FAIL'}")
    print()
    sys.exit(0 if overall_ok else 1)


if __name__ == "__main__":
    main()
