# Recovery Documentation Generation Report

Generated:        2026-05-31T03:22:45Z
Mode:             recovery
Assessment tier:  2
Assessment date:  2026-05-29T02:05:00Z
Host:             pve01

## Dependency Graph
  Nodes:          9
  Edges:          19
  Restore waves:  5
  Estimated time: 220 minutes

## Restore Waves
  Wave 1: Physical host — must be restored first
    - pve01 (Proxmox 8.2-1)
  Wave 2: Storage layer — must be available before VMs can start
    - local (dir, 44.1 GB free)
    - local-zfs (zfspool, 160.4 GB free)
    - rpool (ZFS mirror, 412.8 GB free)
    - vmbr0 (bridge, 192.168.1.10/24)
  Wave 3: Restore 2 component(s) — no mutual dependencies
    - forgejo (VM 101)
    - infra-bootstrap (VM 100)
  Wave 4: Restore: inventory (VM 102)
    - inventory (VM 102)
  Wave 5: Restore: assessment-engine (VM 103)
    - assessment-engine (VM 103)

## Readiness
  Overall: YELLOW — 3 component(s) with minor gaps
  YELLOW   pve01 (Proxmox 8.2-1)
  GREEN    rpool (ZFS mirror, 412.8 GB free)
  GREEN    local (dir, 44.1 GB free)
  GREEN    local-zfs (zfspool, 160.4 GB free)
  GREEN    vmbr0 (bridge, 192.168.1.10/24)
  GREEN    infra-bootstrap (VM 100)
  YELLOW   forgejo (VM 101)
  GREEN    inventory (VM 102)
  YELLOW   assessment-engine (VM 103)

## Single Points of Failure
  - pve01 (Proxmox 8.2-1)
  - rpool (ZFS mirror, 412.8 GB free)
  - vmbr0 (bridge, 192.168.1.10/24)
  - forgejo (VM 101)

## Gaps (4)
  [YELLOW] pve01 (Proxmox 8.2-1): Restore procedure never tested for host:pve01
  [YELLOW] forgejo (VM 101): Backup is 9 days old (threshold: 7 days for vm)
  [YELLOW] forgejo (VM 101): Restore procedure never tested for vm:forgejo
  [YELLOW] assessment-engine (VM 103): Restore procedure never tested for vm:assessment-engine