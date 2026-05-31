# Talos Linux — Alternative OS for k3s VMs

Status: **Optional — not the default.** Ubuntu 22.04 is the current and default OS
for all k3s node VMs. Talos is declared as a supported alternative in the data model
and will be fully wired into reconstruction playbooks in Milestone 9.T.

---

## What Talos Is

Talos Linux is an immutable, minimal OS designed exclusively for running Kubernetes.
It has no SSH, no shell, no package manager, and no user accounts. The entire OS is
read-only. All configuration is applied via a declarative machine config over a secure
gRPC API (`talosctl`). Upgrades are atomic: swap the OS image, roll back if bad.

## Why It Is an Option Here

- For multi-node HA (Phase 11 onward), Talos's immutability and atomic upgrades
  reduce operational drift across nodes.
- It eliminates the Ansible provisioning layer for k3s nodes (replaced by `talosctl apply-config`).
- Machine configs are fully declarative YAML — fits the GitOps model already in use.

## Why Ubuntu Is the Default

- The existing Cloud-Init template library, Ansible roles (`common`, `k3s-server`),
  and snippet system are all Ubuntu-specific. Switching before those are mature would
  require replacing significant completed work.
- Talos's no-SSH constraint means Ansible does not apply — a different operational model,
  not a superset.
- On a single-node homelab, the drift problem Talos solves is minimal. One node rebuilt
  from scratch via OpenTofu + Ansible in minutes achieves the same outcome.

## How to Activate Talos (When Ready)

Set `os_variant: talos` on the relevant node entry in
[`proxmox-bootstrap/metadata/k3s-cluster.yaml`](../proxmox-bootstrap/metadata/k3s-cluster.yaml):

```yaml
server_nodes:
  - vm_name: k3s-server-01
    os_variant: talos   # changed from: ubuntu
```

This is the single flag that drives all downstream tooling (once 9.T milestones are complete):
- Playbook generator emits `talosctl apply-config` steps instead of Ansible plays.
- Recovery runbook renders Talos-specific reconstruction instructions.
- Readiness scorer checks for machine configs in `talos-configs/` directory.

---

## Prerequisites Before Switching

These must be completed before `os_variant: talos` is production-ready:

### Infrastructure
- [ ] Talos ISO downloaded and verified (check https://github.com/siderolabs/talos/releases)
- [ ] `talos-1x-base` Proxmox template built (VMID 9001) — see `build-talos-template.sh` (9.T.2)
- [ ] `talosctl` installed on the operations VM
- [ ] Machine configs generated via `generate-talos-config.py` (9.T.3) and committed to repo

### Data Model
- [ ] `talos-1x-base` entry in `bootstrap-state.json` template registry
- [ ] `talos-1x-base` base_image entry (Talos ISO name + SHA512 checksum)
- [ ] `os_variant` field added to bootstrap-state-schema.json (9.T.5)

### Tooling
- [ ] Milestone 9.T fully implemented (reconstruction playbook OS-variant awareness)

### What You Give Up
- Ansible roles (`common`, `k3s-server`) do not apply — Talos manages the OS.
  Any configuration currently done via Ansible (sysctl, chrony, package installs)
  must be moved into Talos machine config patches or Kubernetes DaemonSets.
- Cloud-Init snippets are not used — Talos ignores them.
- SSH-based emergency access is unavailable — use `talosctl` console access instead.

---

## Data Model Fields

### `k3s-cluster.yaml` — `os_variant` per node

```yaml
server_nodes:
  - vm_name: k3s-server-01
    os_variant: ubuntu    # ubuntu (default) | talos
```

```yaml
worker_nodes:
  - vm_name: k3s-worker-01
    os_variant: ubuntu    # must match server_nodes os_variant for consistent tooling
```

### `vm-roles.yaml` — `template` field

Ubuntu: `template: ubuntu-2204-base`
Talos:  `template: talos-1x-base`

### `bootstrap-state.json` — template registry

```json
"templates": [
  {
    "name": "ubuntu-2204-base",
    "base_image": "ubuntu-2204-base",
    "proxmox_template_id": 9000,
    "os_variant": "ubuntu",
    ...
  },
  {
    "name": "talos-1x-base",
    "base_image": "talos-1x-base-iso",
    "proxmox_template_id": 9001,
    "os_variant": "talos",
    "created_at": "POPULATE",
    "additional_packages": [],
    "build_notes": "Talos Linux — no cloud-init, no SSH, talosctl only"
  }
]
```

---

## Recommended Adoption Path

1. **Now (Phase 6–8):** Keep Ubuntu. Complete bootstrap state, service state, and
   network topology milestones using the existing Ubuntu toolchain.

2. **Phase 9 (Reconstruction Playbooks):** Implement 9.T milestones. The playbook
   generator and recovery runbook become os_variant-aware without requiring an actual
   Talos deployment.

3. **Phase 11 (HA expansion):** If adding a second physical host, evaluate switching
   k3s nodes to Talos at that point. Multi-node drift management is where Talos's
   immutability provides measurable benefit.

4. **Never mandatory:** `os_variant: ubuntu` remains fully supported. Talos is an
   option, not a migration target.
