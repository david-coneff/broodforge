# proxmox-bootstrap — Bootstrap State Repository

This repository is the **Bootstrap State** for an Infrastructure Cell. It tracks
all assets required to provision VMs from a freshly installed Proxmox host to a state
where Ansible can manage them.

Cell ID: `proxmox-cell-a`

---

## What Is Tracked Here

| Asset | Location | Purpose |
|---|---|---|
| Cloud-Init user-data | `snippets/user-data/` | Initial user, SSH keys, packages, hostname |
| Cloud-Init network-config | `snippets/network-config/` | Static IP assignment on first boot |
| Cloud-Init vendor-data | `snippets/vendor-data/` | Proxmox-specific first-boot hooks |
| Base image registry | `images/registry.yaml` | ISO checksums, download URLs, template names |
| VM template manifests | `templates/` | What is in each Proxmox VM template |
| Deployment provenance | `provenance/` | Build receipts per VM deployment |
| Secret registry | `secret-registry.yaml` | KeePass path references — never values |
| DNS registry | `dns-registry.yaml` | Hostname-to-IP mappings for all VMs |
| Service contracts | `service-contracts/` | Interfaces provided/required per service |
| Bootstrap state manifest | `bootstrap-state.json` | Machine-readable aggregation of all the above |
| Hardware requirements | embedded in `bootstrap-state.json` | BIOS flags required before Proxmox install |

---

## Directory Layout

```
proxmox-bootstrap/
  snippets/
    user-data/
      infra-bootstrap.yaml    Cloud-Init user-data for infra-bootstrap VM
      forgejo.yaml
      inventory.yaml
      assessment-engine.yaml
      base-ubuntu.yaml        Shared base included by all user-data files
    network-config/
      infra-bootstrap.yaml    Static IP: 192.168.1.20/24, gw 192.168.1.1
      forgejo.yaml            Static IP: 192.168.1.21/24
      inventory.yaml          Static IP: 192.168.1.22/24
      assessment-engine.yaml  Static IP: 192.168.1.23/24
    vendor-data/
      proxmox-hooks.yaml      Proxmox-specific first-boot hooks (used by infra-bootstrap)
  images/
    registry.yaml             ISO registry: checksums, source URLs, template names
  templates/
    ubuntu-2204-base.yaml     Template build manifest for ubuntu-2204-base
  provenance/
    vm-101-forgejo.json       Deployment provenance record for forgejo
  service-contracts/
    forgejo.yaml              Service contract for Forgejo
    assessment-engine.yaml    Service contract for Assessment Engine
  secret-registry.yaml        Secret reference registry (KeePass paths only)
  dns-registry.yaml           DNS hostname-to-IP registry
  bootstrap-state.json        Machine-readable Bootstrap State manifest
  hardware-requirements.yaml  BIOS and firmware requirements
```

---

## Usage

This repository is read by:
- `assessment/tier2/collectors/bootstrap_state.py` — Tier 2 assessment verifies
  deployed snippet hashes match this repository's state
- `doc-gen/engine.py` — Documentation generator reads this to pre-populate commands
  with actual IPs (from dns-registry), actual snippet paths, actual secret KeePass
  paths (from secret-registry)

Snippet content must match what is uploaded to Proxmox snippet storage.
Use `pvesm` or the Proxmox UI to upload snippets from `snippets/`.

---

## Design Constraints

- This repository never stores secret values — only KeePass path references
- Every VM provisioned from this cell must have an entry in `snippets/`,
  `dns-registry.yaml`, and `secret-registry.yaml`
- Provenance records are written at deployment time by the deployment operator or
  by the OpenTofu/Ansible pipeline
- `bootstrap-state.json` is the machine-readable aggregation — update it whenever
  any file in this repository changes
