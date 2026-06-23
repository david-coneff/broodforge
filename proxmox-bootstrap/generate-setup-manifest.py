#!/usr/bin/env python3
"""
generate-setup-manifest.py — Setup manifest generator for broodforge.

Reads bootstrap-state.json (and optionally service-contracts.yaml, dns-registry.yaml)
and produces a human-readable Markdown manifest documenting the complete setup.
Can also export a JSON suitable for import into SETUP-GUIDE.html.

The manifest serves as a permanent record of:
  - All configured values (hostname, IPs, pool names, etc.)
  - Which fields were autonomously configured vs. manually set
  - Service contracts and VM roles
  - Network profile and external connectivity settings
  - Backup destinations and security configuration

Usage:
  python3 generate-setup-manifest.py --state bootstrap-state.json [--output manifest.md]
  python3 generate-setup-manifest.py --state bootstrap-state.json --format json [--output manifest.json]
  python3 generate-setup-manifest.py --state bootstrap-state.json --open  # open in browser
"""

import argparse
import json
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(obj, *keys, default="(not set)"):
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
    return obj if obj is not None else "(not set)"


def _ts(iso: str) -> str:
    """Format an ISO timestamp nicely."""
    if not iso or iso == "(not set)":
        return "(not set)"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, TypeError):
        return str(iso)


def _auto(value, auto: bool = True) -> str:
    """Format a value with an [auto] tag if appropriate."""
    if value in (None, "(not set)", ""):
        return "_(not set)_"
    tag = " `[auto]`" if auto else ""
    return f"`{value}`{tag}"


def _section(title: str) -> str:
    return f"\n## {title}\n"


def _subsection(title: str) -> str:
    return f"\n### {title}\n"


def _row(label: str, value: str, note: str = "") -> str:
    note_str = f"  _{note}_" if note else ""
    return f"| **{label}** | {value} |{note_str}\n"


def _table_header(*cols) -> str:
    header = "| " + " | ".join(cols) + " |\n"
    sep    = "|" + "|".join(["---"] * len(cols)) + "|\n"
    return header + sep


# ---------------------------------------------------------------------------
# Manifest sections
# ---------------------------------------------------------------------------

def _section_header(state: dict) -> list[str]:
    cell_id     = _get(state, "cell_id")
    declared_at = _ts(_get(state, "declared_at"))
    schema_ver  = _get(state, "schema_version")
    generated   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return [
        "# Broodforge Setup Manifest",
        "",
        f"> **Cell:** `{cell_id}`  |  "
        f"**Schema:** `{schema_ver}`  |  "
        f"**Declared:** {declared_at}  |  "
        f"**Generated:** {generated}",
        "",
        "_This document is auto-generated from bootstrap-state.json._  ",
        "_Fields marked `[auto]` were configured autonomously by broodforge._  ",
        "_Import into SETUP-GUIDE.html via the ⬆ Import button to pre-fill the interactive guide._",
        "",
    ]


def _section_host(state: dict) -> list[str]:
    hi = state.get("host_identity") or {}
    state.get("network_topology") or {}

    lines = [_section("Host Identity")]
    lines.append(_table_header("Field", "Value"))
    lines.append(_row("Hostname",       _auto(_get(hi, "hostname"))))
    lines.append(_row("FQDN",           _auto(_get(hi, "fqdn"))))
    lines.append(_row("Domain",         _auto(_get(hi, "domain"))))
    lines.append(_row("Proxmox version",_auto(_get(hi, "proxmox_version"))))
    lines.append(_row("Cell ID",        _auto(_get(state, "cell_id"))))
    lines.append("")
    return lines


def _section_network(state: dict) -> list[str]:
    nt      = state.get("network_topology") or {}
    profile = nt.get("profile", "lan")
    wan     = nt.get("wan_config") or {}
    lan     = nt.get("lan_config") or {}

    lines = [_section(f"Network — Profile: `{profile.upper()}`")]
    lines.append(_table_header("Field", "Value"))
    lines.append(_row("Profile",          f"`{profile}` ({'LAN-only' if profile=='lan' else 'WAN-capable'})"))
    lines.append(_row("Management CIDR",  _auto(_get(nt, "management_cidr"))))
    lines.append(_row("Gateway",          _auto(_get(nt, "gateway"))))
    lines.append(_row("Nameservers",      _auto(", ".join(_get(nt, "nameservers", default=[]) or []))))
    lines.append(_row("Search domain",    _auto(_get(nt, "search_domain"))))
    lines.append(_row("Bridge name",      _auto("vmbr0")))

    if profile == "wan":
        lines += ["", "**WAN configuration:**", ""]
        lines.append(_table_header("Field", "Value"))
        lines.append(_row("Domain",               _auto(_get(wan, "domain"), auto=False)))
        lines.append(_row("DNS provider",          _auto(_get(wan, "dns_provider"), auto=False)))
        lines.append(_row("DDNS enabled",          _auto(str(_get(wan, "ddns_enabled", default=False)))))
        lines.append(_row("DDNS update interval",  _auto(f"{_get(wan, 'ddns_update_interval_min', default=5)} min")))
        lines.append(_row("Headscale enabled",     _auto(str(_get(wan, "headscale_enabled", default=False)))))
        lines.append(_row("Headscale URL",         _auto(_get(nt, "headscale_url"))))
        lines.append(_row("TLS provider",          _auto(_get(wan, "tls_provider"))))
        lines.append(_row("TLS cert path",         _auto(_get(nt, "ssl_cert_path"))))
        lines.append(_row("Router port forward",   "Port 8080 → this host (manual setup required)"))
    else:
        lines.append(_row("TLS mode",  _auto(_get(lan, "tls_mode", default="self-signed"))))
    lines.append("")
    return lines


def _section_storage(state: dict) -> list[str]:
    sc = state.get("storage_config") or {}
    lines = [_section("Storage")]
    lines.append(_table_header("Field", "Value"))
    lines.append(_row("VM disks datastore", _auto(_get(sc, "vm_disks"))))
    lines.append(_row("ISO storage",        _auto(_get(sc, "isos"))))
    lines.append(_row("Snippets storage",   _auto(_get(sc, "snippets"))))
    lines.append("")
    return lines


def _section_vms(state: dict) -> list[str]:
    vms        = state.get("vms") or []
    dns_reg    = state.get("dns_registry") or []
    contracts  = state.get("service_contracts") or []
    prov_reg   = state.get("provenance_records") or []

    # Build IP lookup
    ip_by_vmid = {}
    for entry in dns_reg:
        if entry.get("vmid") is not None:
            ip_by_vmid[int(entry["vmid"])] = entry.get("ip", "?")

    # Build contract lookup
    contract_by_vm = {c.get("vm"): c for c in contracts if c.get("vm")}

    # Build provenance lookup
    prov_by_vmid = {}
    for r in prov_reg:
        if r.get("vmid") is not None:
            prov_by_vmid[int(r["vmid"])] = r

    lines = [_section("Virtual Machines")]
    if not vms:
        lines.append("_No VMs declared in bootstrap-state.json._\n")
        return lines

    lines.append(_table_header("VMID", "Name", "Role", "IP", "Template", "Backup job"))
    for vm in vms:
        vmid     = vm.get("vmid", "?")
        name     = vm.get("name", "?")
        role     = vm.get("role", "?")
        ip       = ip_by_vmid.get(int(vmid), "?") if vmid != "?" else "?"
        tmpl     = vm.get("template_name", "?")
        contract = contract_by_vm.get(name)
        backup   = contract.get("backup_job", "null") if contract else "?"
        lines.append(f"| `{vmid}` | `{name}` | {role} | `{ip}` | `{tmpl}` | {backup} |\n")

    # Provenance sub-table
    if prov_by_vmid:
        lines += ["", "**Deployment provenance:**", ""]
        lines.append(_table_header("VMID", "Name", "Deployed at", "OpenTofu workspace", "Ansible commit"))
        for vmid_int, prov in sorted(prov_by_vmid.items()):
            lines.append(f"| `{vmid_int}` | `{prov.get('name','?')}` | "
                         f"{_ts(prov.get('deployed_at',''))} | "
                         f"`{prov.get('tofu_workspace','?')}` | "
                         f"`{str(prov.get('ansible_commit','?'))[:12]}` |\n")
    lines.append("")
    return lines


def _section_dns(state: dict) -> list[str]:
    dns = state.get("dns_registry") or []
    lines = [_section("DNS Registry")]
    if not dns:
        lines.append("_No DNS registry entries._\n")
        return lines
    lines.append(_table_header("Hostname", "IP", "VMID", "Role"))
    for e in dns:
        vmid = str(e.get("vmid", "—"))
        lines.append(f"| `{e.get('hostname','?')}` | `{e.get('ip','?')}` | {vmid} | {e.get('role','?')} |\n")
    lines.append("")
    return lines


def _section_secrets(state: dict) -> list[str]:
    secrets = state.get("secrets") or []
    lines   = [_section("Secret Registry")]
    if not secrets:
        lines.append("_No secrets declared._\n")
        return lines
    lines.append(_table_header("ID", "Type", "KeePass path", "Required by"))
    for s in secrets:
        sid   = s.get("id", "?")
        stype = s.get("secret_type", "?")
        kpath = s.get("keepass_path") or "_(not recorded)_"
        req   = ", ".join(s.get("required_by") or []) or "—"
        lines.append(f"| `{sid}` | {stype} | `{kpath}` | {req} |\n")
    lines.append("")
    return lines


def _section_backup(state: dict) -> list[str]:
    bc = state.get("backup_config") or {}
    lines = [_section("Backup Configuration")]
    if not bc:
        lines.append("_Backup not configured — run setup-backup.py._\n")
        return lines

    layers = bc.get("layers") or {}
    ck_tag = bc.get("checkpoint_tag", "checkpoint")
    lines.append(_table_header("Layer", "Enabled", "Destinations", "Last backup"))
    for lname, lcfg in layers.items():
        if not lcfg:
            continue
        enabled = "✓" if lcfg.get("enabled") else "✗"
        dests   = ", ".join(d.get("id", "?") for d in (lcfg.get("destinations") or []))
        last    = _ts(lcfg.get("last_backup_at", ""))
        lines.append(f"| {lname} | {enabled} | {dests or '—'} | {last} |\n")
    lines.append(f"\nCheckpoint tag: `{ck_tag}`\n")
    return lines


def _section_service_contracts(state: dict) -> list[str]:
    contracts = state.get("service_contracts") or []
    lines     = [_section("Service Contracts")]
    if not contracts:
        lines.append("_No service contracts declared._\n")
        return lines
    lines.append(_table_header("Service", "VM", "Provided interfaces", "Required interfaces", "Backup job"))
    for c in contracts:
        prov = ", ".join(
            f"{i.get('protocol')}:{i.get('port')}" for i in (c.get("provided_interfaces") or [])
        ) or "—"
        req = ", ".join(
            f"{r.get('service')} ({r.get('protocol')}:{r.get('port')})"
            for r in (c.get("required_interfaces") or [])
        ) or "—"
        lines.append(f"| `{c.get('service','?')}` | `{c.get('vm','?')}` | {prov} | {req} | {c.get('backup_job','null')} |\n")
    lines.append("")
    return lines


def _section_external_deps(state: dict) -> list[str]:
    deps  = state.get("external_dependencies") or []
    lines = [_section("External Dependencies")]
    if not deps:
        lines.append("_No external dependencies declared._\n")
        return lines
    lines.append(_table_header("ID", "Type", "Endpoint", "Status", "Cert expiry"))
    for d in deps:
        cert   = d.get("certificate") or {}
        expiry = cert.get("expires_at", "—") if cert else "—"
        lines.append(f"| `{d.get('id','?')}` | {d.get('type','?')} | `{d.get('endpoint','?')}` | {d.get('status','?')} | {expiry} |\n")
    lines.append("")
    return lines


def _section_reconstruction_drills(state: dict) -> list[str]:
    drills = state.get("reconstruction_drills") or []
    lines  = [_section("Reconstruction Drills")]
    if not drills:
        lines.append("_No reconstruction drills recorded. See docs/RECONSTRUCTION-DRILL.md._\n")
        return lines
    lines.append(_table_header("Drill ID", "Started", "Outcome", "Estimated (min)", "Actual (min)"))
    for d in drills[:5]:  # show last 5
        lines.append(f"| `{d.get('drill_id','?')}` | {_ts(d.get('started_at',''))} | "
                     f"**{d.get('outcome','?').upper()}** | "
                     f"{d.get('total_estimated_minutes','?')} | "
                     f"{d.get('total_actual_minutes','?')} |\n")
    if len(drills) > 5:
        lines.append(f"_... and {len(drills)-5} earlier drill(s)._\n")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# JSON export for SETUP-GUIDE.html import
# ---------------------------------------------------------------------------

def to_import_json(state: dict) -> dict:
    """
    Build a flat key→value dict matching the data-autofill paths in SETUP-GUIDE.html
    and the data-key values of note inputs, for direct import.
    """
    hi = state.get("host_identity") or {}
    nt = state.get("network_topology") or {}
    wan = nt.get("wan_config") or {}

    out = {
        # host_identity fields
        "host_identity.hostname":       _get(hi, "hostname", default=""),
        "host_identity.domain":         _get(hi, "domain", default=""),
        "host_identity.fqdn":           _get(hi, "fqdn", default=""),
        # network_topology fields
        "network_topology.management_cidr": _get(nt, "management_cidr", default=""),
        "network_topology.gateway":         _get(nt, "gateway", default=""),
        "network_topology.headscale_url":   _get(nt, "headscale_url", default=""),
        # wan_config
        "wan_config.domain":       _get(wan, "domain", default=""),
        "wan_config.dns_provider": _get(wan, "dns_provider", default=""),
        # SETUP-GUIDE.html note-input keys
        "forge-pre-ip":          _get(hi, "hostname", default=""),  # host IP approximation
        "forge-pre-domain-val":  _get(hi, "domain", default=""),
        "forge-p03-hostname":    _get(hi, "hostname", default=""),
        "forge-p03-kdbx":       _get(state, "keepass_config", "root_path", default="/opt/broodforge/cluster.kdbx"),
        "spawn-hostname":        _get(hi, "hostname", default=""),
        "phoenix-hostname":      _get(hi, "hostname", default=""),
    }

    # Add VMs
    dns_reg = state.get("dns_registry") or []
    for vm in (state.get("vms") or []):
        name  = vm.get("name", "")
        vmid  = vm.get("vmid", "")
        ip    = next((e.get("ip") for e in dns_reg if e.get("vmid") == vmid), "")
        if name == "forgejo":
            out["forge-p04-forgejo"] = f"{vmid} / {ip}" if ip else str(vmid)
        key = f"vms.{name}.vmid_ip"
        out[key] = f"{vmid} / {ip}" if ip else str(vmid)

    # Build backup rows for the SETUP-GUIDE.html backup locations table
    backup_rows: list[dict] = []
    kc        = state.get("keepass_config") or {}
    kdbx_loc  = kc.get("database_hint") or "/opt/broodforge/cluster.kdbx"
    cell      = state.get("cell_id") or ""
    cell_pfx  = f"{cell}/" if cell else ""

    backup_rows.append({
        "source": "manifest",
        "what": "Cluster secrets (KeePass .kdbx)",
        "location": kdbx_loc,
        "credential": "",
        "notes": "rclone copy (file already AES-256 encrypted)",
    })
    backup_rows.append({
        "source": "manifest",
        "what": "Infrastructure state (bootstrap-state.json + snippets)",
        "location": "Forgejo repo" + (f" / offsite: {cell}" if cell else ""),
        "credential": "",
        "notes": "GPG-encrypted archive via backup.py",
    })

    bc = state.get("backup_config") or {}
    for lname, lcfg in (bc.get("layers") or {}).items():
        if not lcfg:
            continue
        dests = ", ".join(
            d.get("id") or d.get("path") or d.get("url") or "?"
            for d in (lcfg.get("destinations") or [])
        ) or "—"
        backup_rows.append({
            "source": "manifest",
            "what": f"Backup layer: {lname}",
            "location": dests,
            "credential": "",
            "notes": "enabled" if lcfg.get("enabled") else "disabled",
        })

    svc_contracts = state.get("service_contracts") or []
    for vm in (state.get("vms") or []):
        vmid = vm.get("vmid", "?")
        name = vm.get("name", "?")
        ip   = next((e.get("ip", "") for e in dns_reg if e.get("vmid") == vmid), "") \
               or vm.get("initial_ip", "")
        sc   = next((c for c in svc_contracts
                     if c.get("vm") == name or c.get("service") == name), None)
        bjob = f" (job: {sc['backup_job']})" if sc and sc.get("backup_job") else ""
        backup_rows.append({
            "source": "manifest",
            "what": f"VM: {name} (VMID {vmid})" + (f" — {ip}" if ip else ""),
            "location": f"PBS: {cell_pfx}VMID {vmid}{bjob}",
            "credential": "",
            "notes": vm.get("role") or "",
        })

    out["__backup_rows__"] = backup_rows

    return {k: v for k, v in out.items() if v and v != "(not set)"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_markdown(state: dict) -> str:
    lines = []
    lines += _section_header(state)
    lines += _section_host(state)
    lines += _section_network(state)
    lines += _section_storage(state)
    lines += _section_vms(state)
    lines += _section_dns(state)
    lines += _section_secrets(state)
    lines += _section_backup(state)
    lines += _section_service_contracts(state)
    lines += _section_external_deps(state)
    lines += _section_reconstruction_drills(state)
    lines += [
        "---",
        "",
        "_Generated by `generate-setup-manifest.py`. "
        "To update after changes: re-run with the current `bootstrap-state.json`._",
    ]
    return "".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate broodforge setup manifest")
    parser.add_argument("--state",  default="proxmox-bootstrap/bootstrap-state.json",
                        help="Path to bootstrap-state.json")
    parser.add_argument("--output", default="",
                        help="Output file path (default: setup-manifest.md or setup-manifest.json)")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown",
                        help="Output format (default: markdown)")
    parser.add_argument("--open",   action="store_true",
                        help="Open the generated file in the default application")
    args = parser.parse_args()

    state_path = Path(args.state)
    if not state_path.exists():
        print(f"Error: {args.state} not found", file=sys.stderr)
        sys.exit(1)

    state = json.loads(state_path.read_text(encoding="utf-8"))

    if args.format == "json":
        content    = json.dumps(to_import_json(state), indent=2)
        out_path   = Path(args.output or "setup-manifest.json")
    else:
        content    = build_markdown(state)
        out_path   = Path(args.output or "setup-manifest.md")

    out_path.write_text(content, encoding="utf-8")
    print(f"[manifest] Written: {out_path}  ({len(content):,} chars)")

    if args.open:
        webbrowser.open(str(out_path.resolve()))


if __name__ == "__main__":
    main()
