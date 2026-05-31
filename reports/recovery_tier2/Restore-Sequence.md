# Restore Sequence
Host: pve01
Assessment: 2026-05-29T02:05:00Z
Total waves: 5
Estimated total time: 220 minutes

## Wave 1 — Physical host — must be restored first
Estimated time: 90 minutes
  - pve01 (Proxmox 8.2-1)

## Wave 2 — Storage layer — must be available before VMs can start
Estimated time: 50 minutes
  - local (dir, 44.1 GB free)
    Dependencies: pve01 (Proxmox 8.2-1)
  - local-zfs (zfspool, 160.4 GB free)
    Dependencies: pve01 (Proxmox 8.2-1)
  - rpool (ZFS mirror, 412.8 GB free)
    Dependencies: pve01 (Proxmox 8.2-1)
  - vmbr0 (bridge, 192.168.1.10/24)
    Dependencies: pve01 (Proxmox 8.2-1)

## Wave 3 — Restore 2 component(s) — no mutual dependencies
Estimated time: 40 minutes
  - forgejo (VM 101)
    Dependencies: pve01 (Proxmox 8.2-1), rpool (ZFS mirror, 412.8 GB free), vmbr0 (bridge, 192.168.1.10/24)
  - infra-bootstrap (VM 100)
    Dependencies: pve01 (Proxmox 8.2-1), rpool (ZFS mirror, 412.8 GB free), vmbr0 (bridge, 192.168.1.10/24)

## Wave 4 — Restore: inventory (VM 102)
Estimated time: 20 minutes
  - inventory (VM 102)
    Dependencies: pve01 (Proxmox 8.2-1), rpool (ZFS mirror, 412.8 GB free), vmbr0 (bridge, 192.168.1.10/24), forgejo (VM 101)

## Wave 5 — Restore: assessment-engine (VM 103)
Estimated time: 20 minutes
  - assessment-engine (VM 103)
    Dependencies: pve01 (Proxmox 8.2-1), rpool (ZFS mirror, 412.8 GB free), vmbr0 (bridge, 192.168.1.10/24), forgejo (VM 101), inventory (VM 102)
