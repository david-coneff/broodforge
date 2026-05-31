# Documentation Generation Report

Generated:        2026-05-31T10:54:03Z
Mode:             bootstrap
Assessment tier:  1
Assessment date:  2026-05-30T14:23:00Z
Template version: bootstrap-v1.0
Host:             pve01

## Field Summary

Total fields: 36
  AUTO          18  (50%)
  DERIVED       11  (30%)
  HUMAN          7  (19%)
  UNRESOLVED     0  (0%)
## Human Input Required (7)

- human.root_password_location: Enter KeePass path for root password, e.g. Infrastructure/proxmox/pve01-root
- human.recovery_passphrase: Enter KeePass path for disk encryption passphrase (if applicable)
- human.vm_ip_address: Enter static IP for infra-bootstrap VM. Suggested: 192.168.1.20–192.168.1.30/24
- human.vm_name: Enter VM name (recommended: infra-bootstrap)
- human.vm_username: Enter OS username (recommended: ubuntu)
- human.vm_password_location: Enter KeePass path for VM password
- human.iso_location: Enter ISO path in Proxmox, e.g. local:iso/ubuntu-22.04-live-server-amd64.iso

## Drift Since Last Assessment
No field changes detected.

## Derived Recommendations

- derived.zfs_topology: mirror
  Rationale: Two SSDs detected (sda, sdb). ZFS mirror recommended: full redundancy, no write penalty vs. single device.  ⚠ Existing ZFS pool(s) detected: rpool. Verify topology matches recommendation before proceeding.
  ⚠ Existing ZFS pool(s) detected: rpool. Verify topology matches recommendation before proceeding.
- derived.vm_id: 100
  Rationale: No existing VMs or containers. Starting at VM ID 100 (Proxmox convention).
- derived.vm_ram: 8 GB
  Rationale: Host has 64 GB RAM. 8 GB allocated (standard allocation).
- derived.vm_cores: 4
  Rationale: Host has 48 logical CPUs. 4 vCPUs allocated for infra-bootstrap VM.
- derived.vm_disk: 64 GB
  Rationale: 64 GB disk recommended (pool: rpool, 810 GB free).
- derived.vm_bridge: vmbr1
  Rationale: vmbr0 is already in use. Recommend vmbr1 as the next available bridge name.
- derived.vm_ip_plan: 192.168.1.20–192.168.1.30/24
  Rationale: Host IP is 192.168.1.10/24. Suggested VM range: 192.168.1.20–192.168.1.30/24 (same subnet, avoids host address).