#!/usr/bin/env python3
"""
phoenix_playbook.py — Phoenix playbook generator (Phase 9).

Generates a structured phoenix playbook from bootstrap-state.json and
an optional hardware profile for the replacement machine.

Provides:
  PhoenixPlaybookGenerator — builds the playbook dict from manifest data
  build_phoenix_playbook(manifest, options) — public factory function

A phoenix playbook is organized into restoration waves:
  Wave 0   — Network reconstruction (bridges from network_topology_declared)
  Wave 1   — ZFS pool restore / creation on replacement hardware
  Wave 2   — Proxmox host configuration (hostname, /etc/hosts, datastores)
  Wave 3   — VM restore from PBS backup (identity-preserving: same VMIDs, IPs)
  Wave 4   — k3s cluster membership restore
  Wave 5   — Post-restore validation

Waves 0.5 (template rebuild) and per-VM RECREATE steps are added by later
Phase 9 milestones (9.4, 9.5).

Stdlib only. SSH commands in generated playbooks use the system ssh binary.
"""

from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _zfs_topology_from_disk_count(disk_count: int) -> str:
    """Return a sensible ZFS topology based on disk count."""
    if disk_count <= 1:
        return "stripe"       # single disk — no redundancy
    if disk_count == 2:
        return "mirror"
    if disk_count == 3:
        return "raidz1"
    if disk_count <= 6:
        return "raidz2"
    return "raidz3"


# ---------------------------------------------------------------------------
# PhoenixPlaybookGenerator
# ---------------------------------------------------------------------------

class PhoenixPlaybookGenerator:
    """
    Generates a phoenix playbook from bootstrap-state.json manifest data.

    Usage:
        gen = PhoenixPlaybookGenerator(manifest)
        playbook = gen.build(restoration_scope="full")
    """

    def __init__(
        self,
        manifest: dict,
        hardware_profile: Optional[dict] = None,
        cell_id: Optional[str] = None,
        generated_by: Optional[str] = None,
        now_fn=None,
    ):
        self._manifest    = manifest
        self._hw          = hardware_profile or {}
        self._cell_id     = cell_id or manifest.get("cell_id", "unknown-cell")
        self._generated_by = generated_by
        self._now         = now_fn or _now_utc

    # ── Accessors ──────────────────────────────────────────────────────────

    def _host(self) -> dict:
        return self._manifest.get("host_identity") or self._manifest.get("host", {})

    def _hostname(self) -> str:
        return (self._host().get("hostname") or
                self._host().get("hostname") or "unknown-host")

    def _vms(self) -> list[dict]:
        return self._manifest.get("vms", []) or []

    def _dns_registry(self) -> list[dict]:
        return self._manifest.get("dns_registry", []) or []

    def _secret_registry(self) -> list[dict]:
        return (self._manifest.get("secret_registry") or
                self._manifest.get("secrets") or [])

    def _ntd(self) -> dict:
        """network_topology_declared section."""
        return self._manifest.get("network_topology_declared") or {}

    def _declared_bridges(self) -> list[dict]:
        return self._ntd().get("bridges") or []

    def _storage_config(self) -> dict:
        return self._manifest.get("storage_config") or {}

    def _vm_ip(self, vmid) -> str:
        for entry in self._dns_registry():
            try:
                if entry.get("vmid") is not None and int(entry["vmid"]) == int(vmid):
                    return entry.get("ip", "[VM_IP]")
            except (TypeError, ValueError):
                pass
        return "[VM_IP]"

    def _zfs_pool(self) -> str:
        """Infer the ZFS pool name from storage_config or default to 'rpool'."""
        vm_disks = self._storage_config().get("vm_disks", "")
        if vm_disks and "-" in vm_disks:
            # e.g. "local-zfs" → not a pool name; try the declared bridges or default
            pass
        # Try to extract from pool name convention
        return "rpool"

    def _replacement_disks(self) -> list[str]:
        """Return list of disk IDs from hardware profile, or placeholders."""
        disks = self._hw.get("disks") or []
        if disks:
            return [d.get("name") or d.get("id") or f"/dev/sd{chr(97+i)}"
                    for i, d in enumerate(disks) if d.get("size_gb", 0) > 10]
        return ["/dev/sda"]

    def _zfs_topology(self) -> str:
        disk_count = len(self._replacement_disks())
        return _zfs_topology_from_disk_count(disk_count)

    # ── Wave builders ──────────────────────────────────────────────────────

    def _wave_0_network(self) -> dict:
        """Wave 0 — Network reconstruction from declared topology."""
        bridges = self._declared_bridges()
        steps = []

        if not bridges:
            steps.append({
                "id": "0.1",
                "action": "Network topology not declared — manual bridge setup required",
                "commands": [
                    "# Review /etc/network/interfaces on the failed node's last backup",
                    "# or proxmox-bootstrap/metadata/network-topology.yaml",
                    "# Recreate bridges manually then run:",
                    "ifreload -a",
                ],
                "validation": ["ip link show type bridge"],
                "method": "CONFIGURE",
                "on_failure": "human",
                "secret_refs": [],
            })
        else:
            steps.append({
                "id": "0.1",
                "action": "Verify /etc/network/interfaces matches declared topology",
                "commands": [
                    "# Review declared topology in proxmox-bootstrap/metadata/network-topology.yaml",
                    "# Ensure /etc/network/interfaces contains the following bridges:",
                ] + [
                    f"# Bridge: {b['name']}  ports={b.get('ports', [])}  "
                    f"ip={b.get('ip', 'none')}  vlan-aware={b.get('vlan_aware', False)}"
                    for b in bridges
                ],
                "validation": [],
                "method": "VERIFY",
                "on_failure": "human",
                "secret_refs": [],
            })
            for i, bridge in enumerate(bridges, 2):
                bname  = bridge["name"]
                bports = bridge.get("ports") or []
                bip    = bridge.get("ip")
                bgw    = bridge.get("gateway")
                bvlan  = bridge.get("vlan_aware", False)

                cmds = [f"ip link show {bname}"]
                if bip:
                    cmds.append(f"ip addr show {bname}")

                recon_cmds = [
                    "# If bridge is missing — reconstruct from /etc/network/interfaces:",
                    f"# Add stanza for {bname} with bridge-ports {' '.join(bports) or 'none'}",
                    "ifreload -a",
                ]

                val = [f"ip link show {bname}  # Expected: state UP"]
                if bip:
                    val.append(f"ip addr show {bname}  # Expected: inet {bip}")
                if bgw:
                    val.append(f"ping -c 3 {bgw}  # Expected: gateway reachable")

                steps.append({
                    "id": f"0.{i}",
                    "action": f"Verify bridge {bname}"
                              + (" (management)" if bridge.get("management_bridge") else ""),
                    "commands": cmds + recon_cmds,
                    "validation": val,
                    "method": "VERIFY",
                    "on_failure": "abort",
                    "secret_refs": [],
                })

        return {
            "wave": 0,
            "name": "Network Reconstruction",
            "description": (
                "Rebuild Proxmox host network bridges. All VMs reference bridges "
                "by name — bridges must exist before VM restoration begins."
            ),
            "estimated_minutes": 10,
            "prerequisites": [],
            "steps": steps,
        }

    def _wave_1_storage(self) -> dict:
        """Wave 1 — ZFS pool recreation on replacement hardware."""
        pool_name = self._zfs_pool()
        disks     = self._replacement_disks()
        topology  = self._zfs_topology()

        return {
            "wave": 1,
            "name": "Storage Pool Reconstruction",
            "description": (
                f"Recreate ZFS pool '{pool_name}' using {topology} topology "
                f"on replacement hardware. Pool name must match original "
                f"to preserve datastore registrations and VM disk paths."
            ),
            "estimated_minutes": 15,
            "prerequisites": ["Wave 0 — network must be UP for backup access"],
            "steps": [
                {
                    "id": "1.1",
                    "action": "Scan replacement hardware disks",
                    "commands": [
                        "lsblk -o NAME,SIZE,TYPE,ROTA,MODEL",
                        "# Identify disks to use for the ZFS pool",
                        "# Confirm disk IDs match the hardware profile",
                    ],
                    "validation": ["lsblk  # Verify expected disks are visible"],
                    "method": "VERIFY",
                    "on_failure": "human",
                    "secret_refs": [],
                },
                {
                    "id": "1.2",
                    "action": f"Import or recreate ZFS pool '{pool_name}'",
                    "commands": [
                        f"# Try importing existing pool first (if disks survived):",
                        f"zpool import {pool_name}",
                        f"",
                        f"# If import fails — recreate from replacement disks:",
                        f"# Topology: {topology}   Disks: {' '.join(disks)}",
                        f"# WARNING: This destroys any data on listed disks",
                        f"# zpool create {pool_name} {topology} {' '.join(disks)}",
                    ],
                    "validation": [
                        f"zpool status {pool_name}  # Expected: state ONLINE",
                        f"zpool list {pool_name}",
                    ],
                    "method": "RESTORE",
                    "on_failure": "abort",
                    "secret_refs": [],
                },
                {
                    "id": "1.3",
                    "action": "Register pool as Proxmox datastore",
                    "commands": [
                        f"pvesm add zfspool local-zfs --pool {pool_name} --sparse 1",
                        f"pvesm status  # Verify local-zfs is active",
                    ],
                    "validation": [f"pvesm status | grep local-zfs"],
                    "method": "CONFIGURE",
                    "on_failure": "abort",
                    "secret_refs": [],
                },
            ],
        }

    def _wave_2_host(self) -> dict:
        """Wave 2 — Proxmox host configuration."""
        hostname = self._hostname()
        host_ip  = None
        for entry in self._dns_registry():
            if entry.get("vmid") is None and entry.get("role") == "proxmox-host":
                host_ip = entry.get("ip")
                break

        return {
            "wave": 2,
            "name": "Proxmox Host Configuration",
            "description": "Restore hostname, /etc/hosts, and Proxmox configuration. Must match original to preserve cluster membership and VM config references.",
            "estimated_minutes": 10,
            "prerequisites": ["Wave 1 — storage pool must be ONLINE"],
            "steps": [
                {
                    "id": "2.1",
                    "action": f"Set hostname to '{hostname}'",
                    "commands": [
                        f"hostnamectl set-hostname {hostname}",
                        f"# Update /etc/hosts:",
                        f"# 127.0.0.1   localhost",
                        f"# {host_ip or '[HOST_IP]'}   {hostname}.internal {hostname}",
                    ],
                    "validation": [
                        "hostname  # Expected: " + hostname,
                        f"ping -c 1 {hostname}  # Expected: resolves to {host_ip or '[HOST_IP]'}",
                    ],
                    "method": "CONFIGURE",
                    "on_failure": "abort",
                    "secret_refs": [],
                },
                {
                    "id": "2.2",
                    "action": "Verify Proxmox services are running",
                    "commands": [
                        "systemctl status pve-cluster pveproxy pvedaemon",
                        "pvesh get /nodes",
                    ],
                    "validation": [
                        "pveversion -v  # Expected: version matches pre-failure version",
                    ],
                    "method": "VERIFY",
                    "on_failure": "human",
                    "secret_refs": [],
                },
            ],
        }

    def _wave_3_vms(self) -> dict:
        """Wave 3 — VM restore from PBS backup (identity-preserving)."""
        vms   = self._vms()
        steps = []

        if not vms:
            steps.append({
                "id": "3.0",
                "action": "No VMs declared in bootstrap-state.json",
                "commands": ["# Check bootstrap-state.json for VM declarations"],
                "validation": ["qm list"],
                "method": "VERIFY",
                "on_failure": "human",
                "secret_refs": [],
            })
        else:
            for i, vm in enumerate(vms, 1):
                vmid     = vm.get("vmid", "?")
                vm_name  = vm.get("name", "unknown")
                vm_ip    = self._vm_ip(vmid)
                provenance = next(
                    (r for r in (self._manifest.get("provenance_registry") or [])
                     if r.get("vmid") == vmid), None
                )
                prov_str = ""
                if provenance:
                    prov_str = (
                        f"  # Provenance: deployed {provenance.get('deployed_at','?')} "
                        f"template={provenance.get('template_name','?')}"
                    )

                steps.append({
                    "id": f"3.{i}",
                    "action": f"Restore VM {vmid} ({vm_name}) from PBS backup",
                    "commands": [
                        f"# VM: {vm_name}  VMID: {vmid}  IP: {vm_ip}",
                        prov_str,
                        f"# Locate most recent PBS backup:",
                        f"qmrestore /path/to/backup/{vmid}-latest.vma.zst {vmid} --storage local-zfs",
                        f"qm start {vmid}",
                    ],
                    "validation": [
                        f"qm status {vmid}  # Expected: status running",
                        f"ssh ubuntu@{vm_ip}  # Expected: login succeeds",
                    ],
                    "method": "RESTORE",
                    "on_failure": "human",
                    "secret_refs": [
                        s for s in (vm.get("ssh_key_reference", ""),
                                    vm.get("password_reference", ""))
                        if s
                    ],
                })

        return {
            "wave": 3,
            "name": "VM Restoration",
            "description": "Restore VMs from PBS backup with identity preserved (same VMIDs, same IPs). VMs must come back with their original VMIDs so that k3s membership and inter-VM references remain valid.",
            "estimated_minutes": 30 * max(len(vms), 1),
            "prerequisites": ["Wave 2 — host configured", "PBS backup storage accessible"],
            "steps": steps,
        }

    def _wave_4_k3s(self) -> dict:
        """Wave 4 — k3s cluster membership restore."""
        hostname = self._hostname()
        return {
            "wave": 4,
            "name": "k3s Cluster Membership",
            "description": "Restore k3s node membership. Node name is derived from hostname — must match original for cluster certificates to remain valid.",
            "estimated_minutes": 15,
            "prerequisites": ["Wave 3 — k3s VMs must be running"],
            "steps": [
                {
                    "id": "4.1",
                    "action": "Verify k3s nodes report this host",
                    "commands": [
                        "kubectl get nodes -o wide",
                        f"kubectl describe node {hostname}",
                    ],
                    "validation": [
                        f"kubectl get node {hostname}  # Expected: Ready",
                    ],
                    "method": "VERIFY",
                    "on_failure": "human",
                    "secret_refs": [],
                },
                {
                    "id": "4.2",
                    "action": "Verify Flux CD reconciliation",
                    "commands": [
                        "flux check",
                        "flux get kustomizations",
                    ],
                    "validation": [
                        "flux get kustomizations  # Expected: all Applied=True Ready=True",
                    ],
                    "method": "VERIFY",
                    "on_failure": "human",
                    "secret_refs": [],
                },
            ],
        }

    def _validation_checklist(self, vms: list[dict]) -> list[str]:
        items = [
            "All ZFS pools ONLINE (zpool status)",
            "All declared bridges UP (ip link show type bridge)",
            f"Proxmox web UI accessible at https://{self._hostname()}:8006",
            "All VMs running (qm list | grep running)",
        ]
        for vm in vms:
            vmid = vm.get("vmid", "?")
            name = vm.get("name", "vm")
            vm_ip = self._vm_ip(vmid)
            items.append(f"SSH to {name} (vmid={vmid}) at {vm_ip} succeeds")
        items += [
            "k3s nodes all Ready (kubectl get nodes)",
            "Flux reconciliation complete (flux get kustomizations)",
            "Assessment Engine produces GREEN readiness score",
            "Update bootstrap-state.json with phoenix completion record",
            "Commit updated bootstrap-state.json to Forgejo",
        ]
        return items

    # ── Main build ─────────────────────────────────────────────────────────

    def build(
        self,
        restoration_scope: str = "full",
        deferred_services: Optional[list[str]] = None,
    ) -> dict:
        """Build and return the complete phoenix playbook dict."""
        hostname = self._hostname()
        vms      = self._vms()
        vmids    = [vm["vmid"] for vm in vms if vm.get("vmid") is not None]
        bridge_names = [b["name"] for b in self._declared_bridges()]

        # k3s role from bootstrap state (simple heuristic for now)
        k3s_vms = [vm for vm in vms if "k3s" in (vm.get("role") or "").lower()
                   or "k3s" in (vm.get("name") or "").lower()]
        k3s_role = "server" if any("server" in (v.get("role","") + v.get("name","")).lower()
                                    for v in k3s_vms) else ("worker" if k3s_vms else "none")

        # DNS entry for host LAN IP
        lan_ip = None
        for entry in self._dns_registry():
            if entry.get("vmid") is None and entry.get("role") == "proxmox-host":
                lan_ip = entry.get("ip")
                break

        waves = [
            self._wave_0_network(),
            self._wave_1_storage(),
            self._wave_2_host(),
            self._wave_3_vms(),
            self._wave_4_k3s(),
        ]

        total_minutes = sum(w.get("estimated_minutes") or 0 for w in waves)

        return {
            "schema_version":          "1.0",
            "cell_id":                 self._cell_id,
            "generated_at":            self._now(),
            "generated_by":            self._generated_by,
            "target_node": {
                "hostname":        hostname,
                "fqdn":            self._host().get("fqdn"),
                "proxmox_version": self._host().get("proxmox_version"),
                "role":            "hatchery",
                "k3s_role":        k3s_role,
            },
            "identity": {
                "lan_ip":          lan_ip,
                "tailnet_ip":      None,   # populated by Headscale at collection time
                "proxmox_node_id": hostname,
                "k3s_node_name":   hostname,
                "vmids":           vmids,
                "bridge_names":    bridge_names,
                "zfs_pool_name":   self._zfs_pool(),
            },
            "hardware_profile":        self._hw or None,
            "restoration_scope":       restoration_scope,
            "deferred_services":       deferred_services or [],
            "waves":                   waves,
            "estimated_total_minutes": total_minutes,
            "validation_checklist":    self._validation_checklist(vms),
        }


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def build_phoenix_playbook(
    manifest: dict,
    hardware_profile: Optional[dict] = None,
    restoration_scope: str = "full",
    deferred_services: Optional[list[str]] = None,
    cell_id: Optional[str] = None,
    generated_by: Optional[str] = None,
    now_fn=None,
) -> dict:
    """
    Build a phoenix playbook from a bootstrap-state.json manifest.

    Args:
        manifest:           bootstrap-state.json dict (with injected registries)
        hardware_profile:   hardware-profile-{hostname}.json for replacement machine
        restoration_scope:  'full' | 'partial' | 'deferred'
        deferred_services:  service names to exclude from this pass (partial scope)
        cell_id:            override cell_id (uses manifest value if None)
        generated_by:       attribution string for the playbook header

    Returns:
        Phoenix playbook dict conforming to phoenix-playbook-schema.json
    """
    gen = PhoenixPlaybookGenerator(
        manifest=manifest,
        hardware_profile=hardware_profile,
        cell_id=cell_id,
        generated_by=generated_by,
        now_fn=now_fn,
    )
    return gen.build(
        restoration_scope=restoration_scope,
        deferred_services=deferred_services,
    )
