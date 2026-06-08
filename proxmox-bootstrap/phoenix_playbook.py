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

import random
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Phoenix session temporary credential (Phase 1.J, AD-060(d))
#
# AD-060 names phoenix recovery as the SECOND of its two narrow, explicitly-
# bounded exceptions to the firm "no autonomous full-root pathway" constraint
# — by direct operator instruction, the SAME pattern as node-spawning's
# Cloud-Init temporary credential (AD-039: generated pre-install, used only
# for discovery, discarded the instant the KeePass-managed replacement lands)
# extended to phoenix: a temporary root credential SCOPED TO THE PHOENIX
# SETUP SESSION ONLY, with a hard, generated-runbook-recorded requirement
# that the operator rotates it the moment the session completes.
#
# This mirrors spawn_planner.generate_temp_password / _image_builder.
# generate_install_passphrase: a fresh, readable, single-use Capital.word.
# word.N passphrase, `random.Random(seed)`-seeded only for deterministic
# tests. It is NEVER written to KeePass, NEVER the cell's permanent root
# credential, and NEVER reused across sessions.
# ---------------------------------------------------------------------------

_PHOENIX_SESSION_WORDS = [
    "anchor", "beacon", "cinder", "dawn", "ember", "flare", "grove", "haven",
    "iris", "jet", "knoll", "loom", "moss", "nest", "oak", "pine",
    "quill", "reed", "sage", "thorn", "urn", "vale", "wren", "yarrow",
]


def generate_phoenix_session_credential(seed: Optional[int] = None) -> str:
    """
    Generate a fresh, readable, single-use root passphrase scoped to ONE
    phoenix recovery session (AD-060(d)).

    Mirrors spawn_planner.generate_temp_password (AD-039) and
    _image_builder.generate_install_passphrase (AD-043/Phase 1.H) — same
    Capital.word.word.N shape, same `random.Random(seed)` test-determinism
    convention. `seed` exists only for tests; production callers must never
    pass one. This value is valid for THIS recovery session only — see
    `phoenix_session_credential_section` for the rotation-requirement record
    that travels with it in the generated playbook.
    """
    rng = random.Random(seed)
    w1 = _PHOENIX_SESSION_WORDS[rng.randint(0, len(_PHOENIX_SESSION_WORDS) - 1)]
    w2 = _PHOENIX_SESSION_WORDS[rng.randint(0, len(_PHOENIX_SESSION_WORDS) - 1)]
    n = rng.randint(1, 9)
    return f"{w1.capitalize()}.phoenix.{w2}.{n}"


def phoenix_session_credential_section(
    hostname: str,
    credential: Optional[str] = None,
    seed: Optional[int] = None,
    now_fn=None,
) -> dict:
    """
    Build the `temporary_session_credential` playbook section AD-060(d)
    requires: the freshly-generated session-scoped passphrase plus an
    explicit, generated-output rotation-requirement record.

    THE BOUNDARY THIS ENFORCES (read before editing): this credential is
    (a) generated fresh per phoenix session — never reused, never the cell's
    permanent KeePass-managed root, (b) valid only for the bounded phoenix
    setup-phase window named here, (c) required — IN THE GENERATED OUTPUT,
    not merely in a side document — to be rotated the instant the session
    ends, before the operator resumes normal operations. broodforge records
    this requirement; it does not, and structurally cannot, perform the
    rotation itself (that would require exactly the autonomous full-root
    pathway AD-060 forbids) — rotation is the operator's action, via the
    cell's normal KeePass-managed credential-rotation flow.
    """
    cred = credential if credential is not None else generate_phoenix_session_credential(seed=seed)
    gen_at = (now_fn or _now_utc)()
    return {
        "schema_version": "1.0",
        "scope": "phoenix-setup-session-only",
        "hostname": hostname,
        "generated_at": gen_at,
        "credential": cred,
        "credential_format": "Capital.phoenix.word.N (AD-039/AD-043 readable-passphrase pattern)",
        "valid_window": (
            "From the start of this phoenix recovery session until the "
            "replacement node's KeePass-managed root credential is restored "
            "(Wave 2 — host configuration). NEVER valid before or after."
        ),
        "rotation_requirement": {
            "required": True,
            "statement": (
                "ROTATE THIS CREDENTIAL THE MOMENT THIS RECOVERY SESSION "
                "COMPLETES — before resuming normal operations. This is a "
                "session-scoped temporary credential (AD-060(d)), never the "
                "cell's permanent root keystore. Use the cell's normal "
                "KeePass-managed root-credential rotation flow (the same one "
                "phase-03 installs during forging) to replace it."
            ),
            "mechanism": "operator-run KeePass-managed root-credential rotation (forge phase-03 flow)",
            "enforced_by": "operator discipline + this recorded requirement — broodforge "
                           "does not and cannot autonomously verify or perform rotation "
                           "(doing so would itself be the autonomous full-root pathway "
                           "AD-060 forbids)",
        },
        "constraint": {
            "ad": "AD-060",
            "statement": (
                "This is one of AD-060's two narrow, explicitly-named exceptions "
                "to the firm 'no autonomous full-root pathway' constraint — a "
                "temporary, single-session, soon-discarded credential, never "
                "the cell's permanent keystore. broodforge generates and records "
                "it; it never reads or wields a permanent hypervisor root "
                "credential against a live hypervisor."
            ),
        },
        "notes": [
            "Never written to KeePass. Never reused across sessions. Shown once, "
            "in this generated output, for the operator to use during recovery only.",
            "Mirrors AD-039's Cloud-Init discovery password: generated pre-use, "
            "used only for the bounded recovery window, discarded/rotated immediately.",
        ],
    }


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

    # ── 9.4 — Wave 0.5: template rebuild ──────────────────────────────────

    def _os_variant_for_vm(self, vm_name: str) -> str:
        """
        Read os_variant from k3s-cluster.yaml server_nodes or default to 'ubuntu'.
        Returns 'ubuntu' | 'talos'.
        """
        k3s = self._manifest.get("k3s_cluster") or {}
        for node_list in (k3s.get("server_nodes") or [], k3s.get("worker_nodes") or []):
            for node in node_list:
                if node.get("vm") == vm_name:
                    return node.get("os_variant", "ubuntu")
        return "ubuntu"

    def _wave_05_template_rebuild(self) -> dict:
        """
        Wave 2.5 — Template rebuild.

        Rebuilds the base Proxmox VM template so that stateless VMs can be
        cloned from a known-good image. Must run after storage is available
        (Wave 1) and before VM recreation steps in Wave 3.

        Ubuntu path: download ISO → create VM → install via Cloud-Init → convert to template.
        Talos path: download Talos ISO → create VM → apply machine config → convert to template.
        Variant is read from k3s-cluster.yaml server_nodes[].os_variant.
        """
        tmpl_reg    = self._manifest.get("templates") or []
        base_images = self._manifest.get("base_images") or []
        storage     = self._storage_config()

        # Determine which os_variants are needed
        vms          = self._vms()
        needs_ubuntu = any(self._os_variant_for_vm(v.get("name","")) == "ubuntu" for v in vms) \
                       or not vms   # default: ubuntu
        needs_talos  = any(self._os_variant_for_vm(v.get("name","")) == "talos" for v in vms)

        steps = []

        # ── Ubuntu template rebuild ──────────────────────────────────────
        if needs_ubuntu:
            ubuntu_tmpl = next((t for t in tmpl_reg if "ubuntu" in (t.get("name","")).lower()), None)
            ubuntu_img  = next((i for i in base_images if "ubuntu" in (i.get("name","")).lower()), None)
            tmpl_id     = (ubuntu_tmpl.get("proxmox_template_id") or 9000) if ubuntu_tmpl else 9000
            iso_name    = ubuntu_img.get("source_iso", "[UBUNTU_ISO]") if ubuntu_img else "[UBUNTU_ISO]"
            iso_url     = ubuntu_img.get("source_url", "[UBUNTU_ISO_URL]") if ubuntu_img else "[UBUNTU_ISO_URL]"
            iso_storage = storage.get("isos", "local:iso")

            steps.append({
                "id": "2.5.1",
                "action": f"Rebuild Ubuntu VM template (VMID {tmpl_id})",
                "commands": [
                    f"# Download Ubuntu base ISO if not present:",
                    f"ls {iso_storage.replace(':','/')}/{iso_name} 2>/dev/null ||",
                    f"  wget -P /var/lib/vz/template/iso/ {iso_url}",
                    f"",
                    f"# Create a new VM from the ISO:",
                    f"qm create {tmpl_id} --name ubuntu-2204-base --memory 2048 --cores 2",
                    f"  --scsi0 local-zfs:32 --ide2 {iso_storage}/{iso_name},media=cdrom",
                    f"  --boot order=ide2 --ostype l26 --serial0 socket --vga serial0",
                    f"",
                    f"# Install OS via console, then install qemu-guest-agent:",
                    f"# apt install -y qemu-guest-agent cloud-init && shutdown -h now",
                    f"",
                    f"# Convert to template:",
                    f"qm template {tmpl_id}",
                ],
                "validation": [
                    f"qm list | grep {tmpl_id}  # Expected: template listed",
                    f"qm config {tmpl_id} | grep template  # Expected: template: 1",
                ],
                "method": "RECREATE",
                "on_failure": "human",
                "secret_refs": [],
            })

        # ── Talos template rebuild (9.T.7) ──────────────────────────────
        if needs_talos:
            talos_tmpl  = next((t for t in tmpl_reg if t.get("os_variant") == "talos"
                                or "talos" in (t.get("name","")).lower()), None)
            talos_img   = next((i for i in base_images if i.get("os_variant") == "talos"
                                or "talos" in (i.get("name","")).lower()), None)
            talos_id    = (talos_tmpl.get("proxmox_template_id") or 9001) if talos_tmpl else 9001
            iso_name    = talos_img.get("source_iso", "[TALOS_ISO]") if talos_img else "[TALOS_ISO]"
            iso_url     = talos_img.get("source_url", "[TALOS_ISO_URL]") if talos_img else "[TALOS_ISO_URL]"
            iso_storage = storage.get("isos", "local:iso")

            steps.append({
                "id": "2.5.2",
                "action": f"Rebuild Talos Linux VM template (VMID {talos_id})",
                "commands": [
                    f"# Run the Talos template builder (handles ISO download + VM creation):",
                    f"bash proxmox-bootstrap/build-talos-template.sh \\",
                    f"  --storage {iso_storage.split(':')[0]} \\",
                    f"  --vmid {talos_id}",
                    f"",
                    f"# The script prints manual steps to complete template creation.",
                    f"# Follow the printed instructions, then verify:",
                ],
                "validation": [
                    f"qm list | grep {talos_id}  # Expected: template listed",
                    f"qm config {talos_id} | grep template  # Expected: template: 1",
                    f"ls talos-configs/controlplane.yaml  # Talos machine configs must exist",
                ],
                "method": "RECREATE",
                "on_failure": "human",
                "secret_refs": [],
            })

        return {
            "wave": 2.5,
            "name": "Template Rebuild",
            "description": (
                "Rebuild Proxmox VM template(s) from base ISO so that stateless VMs "
                "can be cloned and configured via IaC rather than restored from backup. "
                "Must complete before Wave 3 RECREATE steps."
            ),
            "estimated_minutes": 20 + (15 if needs_talos else 0),
            "prerequisites": ["Wave 2 — host configured and storage registered"],
            "steps": steps,
        }

    # ── 9.5 — RECREATE vs RESTORE decision ────────────────────────────────

    def _vm_is_stateless(self, vm: dict) -> bool:
        """
        Return True if this VM should be RECREATED (from IaC) rather than
        RESTORED (from PBS backup).

        A VM is stateless if its service contract declares backup_job=null AND
        provenance shows it was deployed via OpenTofu (has tofu_workspace).
        Stateless VMs (infra-bootstrap, assessment-engine) hold no persistent data
        and can be fully rebuilt from the bootstrap repository.
        """
        vm_name  = vm.get("name", "")
        contracts = self._manifest.get("service_contracts") or []
        contract  = next((c for c in contracts if c.get("vm") == vm_name), None)

        has_no_backup = contract is not None and contract.get("backup_job") is None
        prov_reg      = self._manifest.get("provenance_registry") or []
        prov          = next((r for r in prov_reg if r.get("vmid") == vm.get("vmid")), None)
        has_provenance = prov is not None and bool(prov.get("tofu_workspace"))

        return has_no_backup and has_provenance

    def _wave_3_vms(self) -> dict:
        """
        Wave 3 — VM restoration.
        Each VM is either RESTORED (from PBS backup) or RECREATED (from IaC + Ansible),
        based on whether it is stateless (9.5).
        """
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
                vmid       = vm.get("vmid", "?")
                vm_name    = vm.get("name", "unknown")
                vm_ip      = self._vm_ip(vmid)
                stateless  = self._vm_is_stateless(vm)
                provenance = next(
                    (r for r in (self._manifest.get("provenance_registry") or [])
                     if r.get("vmid") == vmid), None
                )

                os_variant = self._os_variant_for_vm(vm_name)
                if stateless and provenance:
                    # RECREATE — rebuild from IaC (9.5)
                    tofu_ws   = provenance.get("tofu_workspace", "opentofu")
                    ans_c     = (provenance.get("ansible_commit") or "HEAD")[:12]
                    tmpl_name = provenance.get("template_name", "ubuntu-2204-base")
                    talos_cfg = (provenance.get("talos_machine_config") or
                                 f"talos-configs/patches/{vm_name}.yaml")

                    if os_variant == "talos":
                        # 9.T.7 — Talos RECREATE path: talosctl instead of Ansible
                        steps.append({
                            "id": f"3.{i}",
                            "action": f"Recreate Talos VM {vmid} ({vm_name}) from IaC — stateless, talosctl provisioning",
                            "commands": [
                                f"# VM: {vm_name}  VMID: {vmid}  IP: {vm_ip}",
                                f"# Method: RECREATE (stateless Talos node — tofu_workspace={tofu_ws})",
                                f"# Template: {tmpl_name}  Machine config: {talos_cfg}",
                                f"",
                                f"# Apply OpenTofu to create the VM:",
                                f"tofu -chdir={tofu_ws}/ apply -target=proxmox_vm_qemu.{vm_name} -auto-approve",
                                f"",
                                f"# Apply Talos machine config (boots from talos-1x-base template):",
                                f"talosctl apply-config --insecure --nodes {vm_ip} \\",
                                f"  --file talos-configs/controlplane.yaml \\",
                                f"  --patch @{talos_cfg}",
                                f"",
                                f"# Wait for Talos to be ready:",
                                f"talosctl --nodes {vm_ip} --talosconfig talos-configs/talosconfig \\",
                                f"  health --wait-timeout 5m",
                            ],
                            "validation": [
                                f"qm status {vmid}  # Expected: status running",
                                f"talosctl --nodes {vm_ip} --talosconfig talos-configs/talosconfig \\",
                                f"  get members  # Expected: node listed",
                            ],
                            "method": "RECREATE",
                            "on_failure": "human",
                            "secret_refs": [],
                        })
                    else:
                        # Ubuntu RECREATE path (original)
                        steps.append({
                            "id": f"3.{i}",
                            "action": f"Recreate VM {vmid} ({vm_name}) from IaC — stateless, no PBS restore needed",
                            "commands": [
                                f"# VM: {vm_name}  VMID: {vmid}  IP: {vm_ip}",
                                f"# Method: RECREATE (stateless — tofu_workspace={tofu_ws})",
                                f"# Template: {tmpl_name}  Ansible commit: {ans_c}",
                                f"",
                                f"# Apply OpenTofu to create the VM:",
                                f"tofu -chdir={tofu_ws}/ apply -target=proxmox_vm_qemu.{vm_name} -auto-approve",
                                f"",
                                f"# Wait for Cloud-Init to complete first boot:",
                                f"sleep 30 && ssh ubuntu@{vm_ip} 'sudo cloud-init status --wait'",
                                f"",
                                f"# Configure via Ansible:",
                                f"ansible-playbook -i inventory/ site.yml --limit {vm_name}",
                            ],
                            "validation": [
                                f"qm status {vmid}  # Expected: status running",
                                f"ssh ubuntu@{vm_ip}  # Expected: login succeeds",
                            ],
                            "method": "RECREATE",
                            "on_failure": "human",
                            "secret_refs": [
                                s for s in (vm.get("ssh_key_reference", ""),
                                            vm.get("password_reference", ""))
                                if s
                            ],
                        })
                else:
                    # RESTORE — from PBS backup (default)
                    prov_str = ""
                    if provenance:
                        prov_str = (
                            f"  # Provenance: deployed {provenance.get('deployed_at','?')} "
                            f"template={provenance.get('template_name','?')}"
                        )
                    # 9.T.7 — validation differs for Talos (no SSH; use talosctl)
                    if os_variant == "talos":
                        talos_cfg = (provenance.get("talos_machine_config") if provenance else None) or \
                                    f"talos-configs/patches/{vm_name}.yaml"
                        restore_validation = [
                            f"qm status {vmid}  # Expected: status running",
                            f"talosctl --nodes {vm_ip} --talosconfig talos-configs/talosconfig \\",
                            f"  get members  # Expected: node listed",
                        ]
                        restore_note = (
                            f"# NOTE: Talos node — no SSH access. Use talosctl for post-restore ops."
                        )
                    else:
                        restore_validation = [
                            f"qm status {vmid}  # Expected: status running",
                            f"ssh ubuntu@{vm_ip}  # Expected: login succeeds",
                        ]
                        restore_note = ""

                    commands = [
                        f"# VM: {vm_name}  VMID: {vmid}  IP: {vm_ip}",
                        prov_str,
                    ]
                    if restore_note:
                        commands.append(restore_note)
                    commands += [
                        f"# Locate most recent PBS backup:",
                        f"qmrestore /path/to/backup/{vmid}-latest.vma.zst {vmid} --storage local-zfs",
                        f"qm start {vmid}",
                    ]

                    steps.append({
                        "id": f"3.{i}",
                        "action": f"Restore VM {vmid} ({vm_name}) from PBS backup",
                        "commands": commands,
                        "validation": restore_validation,
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
        include_session_credential: bool = True,
        session_credential_seed: Optional[int] = None,
    ) -> dict:
        """
        Build and return the complete phoenix playbook dict.

        `include_session_credential` (default True) adds the
        `temporary_session_credential` section AD-060(d) requires — a fresh,
        session-scoped temporary root passphrase plus its hard,
        generated-output rotation requirement (see
        `phoenix_session_credential_section`). Set False only for callers
        that manage that section themselves; broodforge's own generation
        paths should always include it. `session_credential_seed` exists only
        for deterministic tests — production callers must never pass one.
        """
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
            self._wave_05_template_rebuild(),   # 9.4 — between host config and VM restore
            self._wave_3_vms(),                 # 9.5 — RESTORE or RECREATE per VM
            self._wave_4_k3s(),
        ]

        total_minutes = sum(w.get("estimated_minutes") or 0 for w in waves)

        session_credential = (
            phoenix_session_credential_section(
                hostname, seed=session_credential_seed, now_fn=self._now,
            )
            if include_session_credential else None
        )

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
            "temporary_session_credential": session_credential,
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
    include_session_credential: bool = True,
    session_credential_seed: Optional[int] = None,
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
        include_session_credential: include the AD-060(d) `temporary_session_credential`
                            section (default True — see PhoenixPlaybookGenerator.build)
        session_credential_seed: deterministic-test seed only; never set in production

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
        include_session_credential=include_session_credential,
        session_credential_seed=session_credential_seed,
    )
