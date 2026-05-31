# Milestone 5 Design Document
## Assessment Engine → Documentation Generator

Version: 1.0
Date: 2026-05-30
Status: Design

---

## 1. Purpose

This document specifies the design for Phase 5 of the Assessment Engine project:
the transition from _assessment engine that produces reports_ to _assessment engine
that produces documentation_.

The primary outcome of Phase 5 is that bootstrap and recovery documentation are
generated artifacts of the assessment ecosystem rather than separately maintained
files. Technical infrastructure information is populated automatically. Operators
provide only information that cannot be discovered.

---

## 2. Problem Statement

### Current state

- `proxmox-audit-package-v1` collects raw data and produces a `summary.md`.
- Workbook and runbook documents (Stage 01–12) are manually authored.
- Technical fields (IP addresses, RAM, storage topology, VM IDs) are transcribed
  by hand from the host into documents.
- Documents go stale as the infrastructure changes.
- There is no formal connection between what the assessment engine observes and
  what the documentation says.

### Target state

```
Bootstrap Assessment
        │
        ▼
  manifest.json  (structured observed state)
        │
        ▼
  doc-gen/engine.py
        │
        ├──► Bootstrap Workbook   (Stages 01–03, pre-populated)
        └──► Bootstrap Runbook    (Stages 01–03, pre-populated)

Infrastructure Deployment
        │
Full Assessment Engine
        │
        ▼
  manifest.json  (five-state model)
        │
        ▼
  doc-gen/engine.py
        │
        ├──► Recovery Workbook
        ├──► Recovery Runbook
        ├──► Dependency Graph
        ├──► Restore Sequence
        └──► Recovery Readiness Report
```

---

## 3. Architecture Revisions

### 3.1 Two-Tier Assessment Model

The existing audit package becomes Tier 1. The existing assessment engine becomes
the foundation of Tier 2.

**Tier 1 constraints (must be maintained):**
- Entry point is a single shell script copied to the host
- Requires only bash and python3 (stdlib only)
- No network access required
- Runs on a freshly installed Proxmox host
- Produces a self-contained tar.gz archive

**Tier 2 additions:**
- Proxmox API access (via token or password auth)
- SSH access to managed hosts
- Read access to Forgejo repositories
- Read access to OpenTofu state
- Read access to Ansible inventory
- Produces the full five-state model

### 3.2 Structured Manifest Format

Both tiers produce a `manifest.json` as their primary structured output.
The manifest is the contract between the assessment layer and the doc-gen layer.

The doc-gen layer never reads raw collector files (lscpu.txt, etc.) directly.
It reads only `manifest.json`. Raw files are retained for audit and debugging.

### 3.3 Field Classification System

All doc-gen templates reference fields by classification:

```
AUTO      Populated directly from manifest.json
DERIVED   Computed by an analyzer module from manifest data
HUMAN     Cannot be discovered; operator must fill in
UNRESOLVED Data was expected but not found; explanation required
```

UNRESOLVED is a first-class output state. Missing data is never silently dropped.

---

## 4. Data Model Revisions

### 4.1 Tier 1 Manifest Schema (observed-state-schema.json)

```json
{
  "schema_version": "1.0",
  "assessment_tier": 1,
  "collected_at": "2026-05-30T14:23:00Z",
  "host": {
    "hostname": "pve01",
    "fqdn": "pve01.internal",
    "proxmox_version": "8.2-1",
    "uptime_seconds": 3600
  },
  "cpu": {
    "model": "Intel(R) Core(TM) i9-13900K",
    "architecture": "x86_64",
    "sockets": 1,
    "cores_per_socket": 24,
    "threads_per_core": 2,
    "total_threads": 48
  },
  "memory": {
    "total_gb": 64,
    "available_gb": 61,
    "swap_total_gb": 0
  },
  "storage": {
    "block_devices": [
      {
        "name": "sda",
        "type": "disk",
        "size_gb": 1000,
        "rotational": false,
        "model": "Samsung SSD 870 EVO",
        "transport": "sata"
      }
    ],
    "zfs_pools": [
      {
        "name": "rpool",
        "state": "ONLINE",
        "topology": "mirror",
        "total_gb": 932,
        "free_gb": 810,
        "devices": ["sda", "sdb"]
      }
    ],
    "pve_storage": [
      {
        "name": "local",
        "type": "dir",
        "path": "/var/lib/vz",
        "total_gb": 50,
        "free_gb": 40,
        "content": ["iso", "backup", "template"]
      }
    ]
  },
  "network": {
    "interfaces": [
      {
        "name": "enp2s0",
        "mac": "aa:bb:cc:dd:ee:ff",
        "state": "UP",
        "addresses": ["192.168.1.10/24"]
      }
    ],
    "bridges": [
      {
        "name": "vmbr0",
        "ports": ["enp2s0"],
        "addresses": ["192.168.1.10/24"],
        "comment": "LAN bridge"
      }
    ],
    "vlans": [],
    "default_gateway": "192.168.1.1",
    "dns_servers": ["1.1.1.1", "8.8.8.8"]
  },
  "vms": [
    {
      "vmid": 100,
      "name": "existing-vm",
      "status": "running",
      "cores": 2,
      "memory_mb": 2048,
      "disk_gb": 32
    }
  ],
  "containers": [],
  "software": {
    "installed_packages": [
      {"name": "git", "version": "1:2.39.2-1"},
      {"name": "python3", "version": "3.11.2-1"}
    ],
    "automation_readiness": {
      "git": true,
      "python3": true,
      "ansible": false,
      "terraform": false,
      "curl": true,
      "wget": true
    }
  },
  "collection_errors": [],
  "collection_warnings": []
}
```

### 4.2 Five-State Manifest (Tier 2 extension)

Tier 2 extends the Tier 1 manifest with additional top-level keys:

```json
{
  "schema_version": "2.0",
  "assessment_tier": 2,
  "declared_state": {
    "tofu_workspaces": [...],
    "resource_count": 0,
    "last_apply_at": null
  },
  "configured_state": {
    "ansible_inventory": {...},
    "managed_hosts": [...],
    "managed_groups": [...],
    "role_assignments": [...]
  },
  "dependency_graph": {
    "nodes": [...],
    "edges": [...],
    "restore_waves": [...]
  },
  "backup_inventory": {
    "pbs_jobs": [...],
    "vzdump_schedules": [...],
    "last_verified_restore": null
  },
  "readiness": {
    "overall_score": "YELLOW",
    "components": [...]
  }
}
```

### 4.3 Field Map Format (bootstrap-fields.yaml)

```yaml
# Field map: bootstrap workbook
# Each entry maps a document field to a manifest path and classification.

fields:
  - id: host.hostname
    label: "Hostname"
    class: AUTO
    manifest_path: "host.hostname"
    document_locations:
      - sheet: "Stage 01 — Host Preparation"
        cell: "C5"

  - id: cpu.model
    label: "CPU Model"
    class: AUTO
    manifest_path: "cpu.model"
    document_locations:
      - sheet: "Stage 02 — Host Assessment"
        cell: "C8"

  - id: memory.total_gb
    label: "Total RAM (GB)"
    class: AUTO
    manifest_path: "memory.total_gb"
    document_locations:
      - sheet: "Stage 02 — Host Assessment"
        cell: "C9"

  - id: derived.infra_vm_ram_recommendation
    label: "Recommended RAM for infra-bootstrap VM"
    class: DERIVED
    analyzer: "vm_sizing.infra_bootstrap_ram"
    document_locations:
      - sheet: "Stage 03 — Infra Bootstrap VM"
        cell: "C12"

  - id: derived.storage_topology_recommendation
    label: "Recommended ZFS topology"
    class: DERIVED
    analyzer: "storage.zfs_topology_recommendation"
    document_locations:
      - sheet: "Stage 01 — Host Preparation"
        cell: "C20"

  - id: derived.next_available_vmid
    label: "Next available VM ID"
    class: DERIVED
    analyzer: "vm_ids.next_available"
    document_locations:
      - sheet: "Stage 03 — Infra Bootstrap VM"
        cell: "C10"

  - id: human.root_password_location
    label: "Root password location (KeePass path)"
    class: HUMAN
    prompt: "Enter the KeePass path where the root password will be stored"
    document_locations:
      - sheet: "Stage 01 — Host Preparation"
        cell: "C35"

  - id: unresolved.dmidecode_serial
    label: "Hardware serial number"
    class: UNRESOLVED
    condition: "software.dmidecode_available == false"
    reason: "dmidecode was not available or returned no output"
    collection_guidance: "Run: dmidecode -s system-serial-number as root"
    readiness_impact: "LOW — informational only"
```

---

## 5. Assessment Package Revisions

### 5.1 Tier 1 Rebuild

The existing `audit.sh` / `analyze.py` pair is replaced by a modular structure.

**`bootstrap.sh` (entry point)**
```bash
#!/usr/bin/env bash
# Bootstrap Assessment — Tier 1
# Usage: ./bootstrap.sh
# Requirements: bash, python3 (stdlib only)

set -euo pipefail

TS=$(date +%Y-%m-%d_%H_%M_%S)
OUTDIR="bootstrap_${TS}"
mkdir -p "${OUTDIR}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COLLECTORS_DIR="${SCRIPT_DIR}/collectors"

echo "[bootstrap] Starting Tier 1 assessment: ${TS}"

# Run each collector; errors are captured, not fatal
for collector in cpu memory storage network proxmox software; do
    echo "[bootstrap] Collecting: ${collector}"
    bash "${COLLECTORS_DIR}/${collector}.sh" "${OUTDIR}" 2>>"${OUTDIR}/collection_errors.log" || \
        echo "WARNING: ${collector} collector reported errors" >> "${OUTDIR}/collection_warnings.log"
done

echo "[bootstrap] Building manifest"
python3 "${SCRIPT_DIR}/analyze.py" "${OUTDIR}"

tar -czf "${OUTDIR}.tar.gz" "${OUTDIR}"
echo "[bootstrap] Archive: ${OUTDIR}.tar.gz"
echo "[bootstrap] Complete."
```

**`collectors/storage.sh` (example modular collector)**
```bash
#!/usr/bin/env bash
# Storage collector for Tier 1 bootstrap assessment
OUTDIR="${1:-.}"

lsblk -J -o NAME,SIZE,TYPE,ROTA,MODEL,TRAN > "${OUTDIR}/lsblk_json.json" 2>&1 || \
    lsblk -o NAME,SIZE,TYPE,ROTA,MODEL > "${OUTDIR}/lsblk.txt" 2>&1 || true

df -h > "${OUTDIR}/df.txt" 2>&1 || true

# ZFS
if command -v zpool &>/dev/null; then
    zpool status -P > "${OUTDIR}/zpool_status.txt" 2>&1 || true
    zpool list -j 2>/dev/null > "${OUTDIR}/zpool_list_json.json" || \
        zpool list > "${OUTDIR}/zpool_list.txt" 2>&1 || true
    zfs list -o name,used,avail,refer,mountpoint > "${OUTDIR}/zfs_list.txt" 2>&1 || true
fi

# Proxmox storage
if command -v pvesm &>/dev/null; then
    pvesm status > "${OUTDIR}/pvesm_status.txt" 2>&1 || true
fi
```

**`analyze.py` (manifest builder)**

The manifest builder reads all collector outputs and produces a schema-validated
`manifest.json`. It uses only Python 3 stdlib.

Key responsibilities:
- Parse lsblk JSON or text output into structured device list
- Parse `ip addr` output into structured interface list
- Parse `zpool list`/`zpool status` into pool topology
- Parse `qm list` and `pct list` into VM/CT inventories
- Detect collection errors and populate `collection_errors[]`
- Classify any expected-but-missing data as UNRESOLVED with reason
- Write `manifest.json`

### 5.2 Tier 2 Collector Additions

Tier 2 adds the following collector modules to the existing assessment engine:

| Module | Source | Data Collected |
|---|---|---|
| `api.py` | Proxmox REST API | Full VM/CT configs, node resources, cluster state |
| `repositories.py` | Forgejo API | Repo list, commit metadata, file contents |
| `ansible.py` | Filesystem / Forgejo | Inventory hosts/groups, role assignments |
| `tofu.py` | OpenTofu state files | Resource declarations, state, outputs |
| `backups.py` | PBS API + vzdump logs | Backup jobs, retention, last run, size |
| `dependencies.py` | All sources | Service graph, storage graph, network graph |

---

## 6. Bootstrap Documentation Generation Design

### 6.1 Workflow

```
1. User installs Proxmox
2. User copies bootstrap assessment package to host
3. User runs: ./bootstrap.sh
4. User copies bootstrap_<timestamp>.tar.gz to workstation
5. User runs: python3 doc-gen/engine.py --mode bootstrap --archive bootstrap_<timestamp>.tar.gz
6. doc-gen writes:
     reports/bootstrap_<timestamp>/
       Stage-01_Host-Preparation_Workbook.ods
       Stage-01_Host-Preparation_Runbook.odt
       Stage-02_Host-Assessment_Workbook.ods
       Stage-02_Host-Assessment_Runbook.odt
       Stage-03_Infra-Bootstrap-VM_Workbook.ods
       Stage-03_Infra-Bootstrap-VM_Runbook.odt
       Command-Reference.ods
       generation-report.md
7. User opens workbooks; HUMAN fields require input, everything else is pre-filled
```

### 6.2 DERIVED Field Analyzers

**`vm_sizing.infra_bootstrap_ram(manifest)`**
```
if manifest.memory.total_gb >= 128: recommend 16GB
elif manifest.memory.total_gb >= 64: recommend 8GB
elif manifest.memory.total_gb >= 32: recommend 4GB
else: recommend 2GB, warn "host RAM is low"
```

**`storage.zfs_topology_recommendation(manifest)`**
```
ssd_count = count of non-rotational block devices
if ssd_count >= 4: recommend raidz1 + hot spare
elif ssd_count == 3: recommend raidz1
elif ssd_count == 2: recommend mirror
elif ssd_count == 1: recommend single (no redundancy, warn)
else: no ZFS-capable devices detected, flag as UNRESOLVED
```

**`vm_ids.next_available(manifest)`**
```
used_ids = set of vmid from manifest.vms + manifest.containers
candidate = 100
while candidate in used_ids: candidate += 1
return candidate
```

**`network.recommend_bridge(manifest)`**
```
existing_bridges = manifest.network.bridges
if "vmbr0" not in existing_bridges: recommend vmbr0
else: recommend next available vmbr{n}
```

### 6.3 Bootstrap Workbook Structure

Each generated workbook follows the Observe → Decide → Act → Record → Validate structure
established in the Stage 01–03 examples.

**Stage 01 — Host Preparation Workbook**

| Section | Fields | Classification |
|---|---|---|
| Host Identification | Hostname, IP, Proxmox version | AUTO |
| Hardware Summary | CPU, RAM, storage devices | AUTO |
| ZFS Configuration | Topology recommendation, pool name, devices | DERIVED |
| Network Configuration | Bridge name, VLAN plan | DERIVED + HUMAN |
| Validation Checklist | SSH access, web UI access | HUMAN (checkbox) |
| Notes | Operator notes | HUMAN |

**Stage 02 — Host Assessment Workbook**

| Section | Fields | Classification |
|---|---|---|
| CPU Inventory | Model, cores, threads, architecture | AUTO |
| Memory Inventory | Total, available, NUMA topology | AUTO |
| Storage Inventory | All block devices with sizes and models | AUTO |
| Network Inventory | All interfaces, bridges, IPs | AUTO |
| VM Inventory | All existing VMs with IDs and states | AUTO |
| Container Inventory | All existing containers | AUTO |
| Software Inventory | Key packages and versions | AUTO |
| Service Inventory | Running systemd services | AUTO |
| Assessment Gaps | UNRESOLVED fields with guidance | AUTO |

**Stage 03 — Infra Bootstrap VM Workbook**

| Section | Fields | Classification |
|---|---|---|
| VM Configuration | VM ID (next available), cores, RAM (DERIVED) | DERIVED |
| Storage Allocation | Disk size recommendation based on pool free | DERIVED |
| Network Assignment | Bridge and IP recommendation | DERIVED |
| Validation | VM boots, SSH accessible | HUMAN (checkbox) |

### 6.4 Bootstrap Runbook Structure

Each generated runbook follows the format from Stage 01–03 examples:

- **Purpose** — what this stage accomplishes (static template text)
- **Prerequisites** — conditions that must be true before starting (mix of AUTO facts + static)
- **Observed State** — AUTO-populated from assessment
- **Decisions Required** — HUMAN fields only
- **Steps** — commands pre-populated where addresses/IDs/sizes are known
- **Validation** — checkpoints with expected outputs (partially AUTO)
- **Recovery** — what to do if a step fails (static + DERIVED risk flags)

Example — Stage 03 runbook step (comparison):

_Before (manual):_
```
Step 3.4: Create the infra-bootstrap VM
  qm create 100 --name infra-bootstrap --memory 8192 --cores 4 ...
```

_After (generated):_
```
Step 3.4: Create the infra-bootstrap VM
  [AUTO] Next available VM ID: 104 (IDs 100–103 are in use)
  [DERIVED] Recommended RAM: 8192 MB (host has 64 GB; standard allocation)
  [DERIVED] Storage pool: rpool (largest free pool; 810 GB available)

  qm create 104 --name infra-bootstrap --memory 8192 --cores 4 \
    --net0 virtio,bridge=vmbr0 --scsi0 rpool:32 \
    --ostype l26 --serial0 socket --vga serial0
```

---

## 7. Recovery Documentation Generation Design

### 7.1 Workflow

```
1. Full Assessment Engine runs (Tier 2)
2. manifest.json produced (five-state model)
3. User runs: python3 doc-gen/engine.py --mode recovery --archive assessment_<timestamp>.tar.gz
4. doc-gen writes:
     reports/recovery_<timestamp>/
       Recovery-Workbook.ods
       Recovery-Runbook.odt
       Dependency-Graph.dot
       Dependency-Graph.png  (if graphviz available)
       Restore-Sequence.md
       Recovery-Readiness-Report.ods
       generation-report.md
```

### 7.2 Recovery Workbook Structure

**Sheet: Infrastructure Overview**
- All AUTO fields from five-state manifest
- Last assessment date (AUTO)
- Drift summary since last assessment (DERIVED)

**Sheet: Restore Sequence**
- Generated from topological sort of dependency graph
- Restore waves listed in order
- Each wave: components, estimated time, dependencies
- All field values AUTO-populated from manifest

**Sheet: Component Recovery Details**
For each recoverable component (one section per component):
- Component name, type, last known state (AUTO)
- Backup location and recency (AUTO from backup_inventory)
- Restore procedure reference (DERIVED → links to runbook section)
- Readiness score (DERIVED)
- HUMAN fields: passphrase locations, physical media locations

**Sheet: Recovery Readiness**
- Per-component readiness scores (DERIVED)
- Gap list: each UNRESOLVED field with reason and impact
- Missing backup warnings
- Single points of failure
- Recovery blockers (RED components that others depend on)

### 7.3 Dependency Graph

Built by `dependencies.py` from four source types:

```
Type        Source                      Example edge
────────────────────────────────────────────────────────────────
DEPENDS_ON  OpenTofu depends_on         tofu:forgejo → tofu:vm_forgejo
NETWORK     API + service probing       vm:assessment-engine → vm:forgejo
STORAGE     pvesm / zfs topology        vm:all → zfs:rpool
SERVICE     systemd Requires/After      svc:docker → svc:network
```

Graph output (dependency-graph.json):
```json
{
  "nodes": [
    {"id": "pve:host", "type": "host", "label": "pve01", "readiness": "GREEN"},
    {"id": "zfs:rpool", "type": "storage", "label": "rpool (mirror)", "readiness": "GREEN"},
    {"id": "vm:forgejo", "type": "vm", "label": "forgejo (VM 101)", "readiness": "YELLOW"},
    {"id": "vm:assessment", "type": "vm", "label": "assessment-engine (VM 103)", "readiness": "GREEN"}
  ],
  "edges": [
    {"from": "vm:forgejo", "to": "zfs:rpool", "type": "STORAGE", "label": "primary storage"},
    {"from": "vm:assessment", "to": "vm:forgejo", "type": "NETWORK", "label": "git remote"},
    {"from": "vm:assessment", "to": "zfs:rpool", "type": "STORAGE", "label": "primary storage"}
  ],
  "restore_waves": [
    {"wave": 1, "components": ["pve:host"], "note": "Physical host must come first"},
    {"wave": 2, "components": ["zfs:rpool"], "note": "Storage must be available before VMs"},
    {"wave": 3, "components": ["vm:forgejo"], "note": "Git infrastructure before dependents"},
    {"wave": 4, "components": ["vm:assessment"], "note": "Assessment engine after Forgejo"}
  ]
}
```

### 7.4 Restore Sequence Generation

The restore sequence is derived by:

1. Build directed graph of dependencies
2. Topological sort (Kahn's algorithm)
3. Group sorted nodes into waves (nodes in the same wave have no mutual dependencies)
4. Annotate each wave with rationale (DERIVED from edge labels)
5. Generate step-by-step restore procedure per component

Each restore step includes:
- The component being restored (AUTO)
- Backup source and date (AUTO from backup_inventory)
- Pre-conditions (AUTO from dependency edges)
- Restore commands (AUTO + HUMAN for passphrases)
- Validation steps (AUTO + HUMAN checkboxes)

### 7.5 Recovery Runbook Structure

The recovery runbook is structured parallel to the workbook but oriented toward
operators executing the recovery rather than planning it.

**Section 1: Recovery Situation Overview**
- Infrastructure summary as of last assessment (AUTO)
- What is known to be affected (HUMAN — operator fills in at incident start)
- Estimated recovery time (DERIVED from readiness scores + component count)

**Section 2: Pre-Recovery Checklist**
- Verify physical host access (HUMAN checkbox)
- Verify backup media access (HUMAN checkbox, location from AUTO field)
- Verify passwords/passphrases available (HUMAN checkbox, KeePass path from AUTO field)
- Verify network access (HUMAN checkbox)

**Section 3: Restore Wave N** (one section per wave)
- Components in this wave (AUTO)
- Dependency rationale (DERIVED)
- Step-by-step commands (AUTO-populated addresses, IDs, pool names)
- Expected output for each command (AUTO where deterministic)
- Failure handling (DERIVED risk flags + static fallback guidance)

**Section 4: Validation**
- End-to-end service validation (AUTO-populated service URLs, IPs)
- Assessment engine re-run to confirm observed state (static instruction)

---

## 8. Recovery Readiness Scoring Design

### 8.1 Scoring Model

Each component receives a score. Score is the worst of all applicable inputs.

```
Input                           Weight    Scoring rule
────────────────────────────────────────────────────────────────────────
Backup present                  HIGH      No backup = RED
Backup recency (< 7 days)       HIGH      > 30 days = ORANGE, > 7 days = YELLOW
Backup verified (restore test)  MEDIUM    Never tested = YELLOW
Restore procedure exists        MEDIUM    Missing = ORANGE
Dependency info complete        MEDIUM    Incomplete = YELLOW
Config documentation complete   LOW       Missing = YELLOW
Last restore test < 90 days     LOW       > 90 days = YELLOW
```

### 8.2 Cascade Scoring

If component A depends on component B and B is RED, A becomes BLOCKED.

BLOCKED propagates transitively: if A is BLOCKED and C depends on A, C becomes BLOCKED.

The readiness report surfaces the root RED components that are causing cascades,
so operators know where to focus remediation effort.

### 8.3 Recovery Readiness Report Structure

```
Recovery Readiness Report — Generated 2026-05-30

Overall Score: YELLOW

Component Scores:
  GREEN   pve01 (Proxmox host)
  GREEN   rpool (ZFS mirror storage)
  YELLOW  forgejo (VM 101) — backup age 12 days
  GREEN   assessment-engine (VM 103)

Gaps Requiring Attention:
  [YELLOW] forgejo: Last backup 12 days ago (threshold: 7 days)
           Action: Run manual backup or verify scheduled backup is running
           Impact: Recovery point objective may not be met

  [YELLOW] forgejo: No verified restore test on record
           Action: Perform restore test to isolated environment
           Impact: Restore procedure is unvalidated

Missing Information:
  [UNRESOLVED] forgejo: KeePass path for service account password
               Why: Not discoverable from infrastructure scan
               How to collect: Record in KeePass and update inventory
               Readiness impact: MEDIUM — needed for post-restore validation

Single Points of Failure:
  rpool: All VMs depend on this ZFS pool. No offsite backup detected.
         Recommendation: Configure PBS replication or offsite vzdump.
```

---

## 9. Historical State Integration Design

### 9.1 Snapshot Index

`history/index.json` maintains a list of all stored assessment archives:

```json
{
  "snapshots": [
    {
      "id": "bootstrap_2026-05-01_10_00_00",
      "tier": 1,
      "collected_at": "2026-05-01T10:00:00Z",
      "archive_path": "history/snapshots/bootstrap_2026-05-01_10_00_00.tar.gz",
      "manifest_path": "history/snapshots/bootstrap_2026-05-01_10_00_00/manifest.json",
      "doc_generation_ids": ["bootstrap_2026-05-01_10_00_00"]
    }
  ]
}
```

### 9.2 Drift Detection

`analyzers/drift.py` compares two manifests and produces a drift record:

```json
{
  "from_snapshot": "...",
  "to_snapshot": "...",
  "diffs": [
    {
      "path": "network.bridges[0].addresses[0]",
      "from": "192.168.1.10/24",
      "to": "192.168.1.20/24",
      "severity": "HIGH",
      "documentation_impact": "IP address changed — recovery runbook commands are stale"
    }
  ]
}
```

### 9.3 Documentation Drift Detection

When regenerating documentation from a new assessment, the doc-gen engine compares
the new manifest against the manifest used for the previous generation.

For each field that has changed, the generation report includes:
- The field that changed
- Old value vs. new value
- Which document sections are affected
- Whether the previous documentation is now stale

### 9.4 Reproducibility

Requirement: `doc-gen/engine.py --archive history/snapshots/X.tar.gz` must produce
the same output today as it would have on the day snapshot X was collected
(modulo template version, which is pinned per snapshot in the index).

This means:
- No network calls during doc generation (all data from manifest)
- No current-date-dependent logic in templates
- Template version is recorded in the snapshot index

---

## 10. Metadata Schema Revisions

### 10.1 Generation Metadata

Each doc-gen run produces a `generation-report.md` alongside the output documents:

```markdown
# Documentation Generation Report

Generated: 2026-05-30T14:30:00Z
Mode: bootstrap
Archive: bootstrap_2026-05-30_14_23_00.tar.gz
Template version: bootstrap-v1.2
Assessment tier: 1

## Field Summary
Total fields: 87
  AUTO:       54  (62%)
  DERIVED:    18  (21%)
  HUMAN:       9  (10%)
  UNRESOLVED:  6   (7%)

## UNRESOLVED Fields (6)
1. hardware.serial_number — dmidecode not available
2. storage.sdc.model — lsblk returned no model for sdc
   ...

## HUMAN Fields Requiring Operator Input (9)
1. Stage 01 / C35 — Root password KeePass path
2. Stage 01 / C36 — Recovery passphrase KeePass path
   ...

## Derived Recommendations
- ZFS topology: mirror (2 SSDs detected: sda, sdb)
- Infra bootstrap VM RAM: 8 GB (host has 64 GB)
- Next available VM ID: 100 (no existing VMs)
- Recommended bridge: vmbr0 (not in use)
```

---

## 11. Repository Layout Revisions

The repository restructuring required for Phase 5:

```
broodforge/
  # Existing (revised)
  assessment/
    tier1/             ← replaces audit.sh + analyze.py at root level
    tier2/             ← existing engine, reorganized

  # New
  data-model/          ← JSON schemas for all five state types
  doc-gen/             ← documentation generation engine
  history/             ← assessment history store (was implicit)
  docs/                ← project documentation (this file lives here)
  tests/fixtures/      ← sample manifests for testing doc-gen
```

---

## 12. Implementation Phases

### Phase 5.1 — Data Model Formalization (2–3 days)
- Write all five JSON schemas with examples
- Write schema validator in Python stdlib
- Add fixture archives to `tests/fixtures/`
- Update existing assessment outputs to produce manifest.json

### Phase 5.2 — Tier 1 Rebuild (3–4 days)
- Refactor audit.sh into modular collectors
- Build manifest builder (analyze.py)
- Test on Proxmox 8.x host (or VM)
- Validate manifest against schema

### Phase 5.3 — Bootstrap Doc Gen (5–7 days)
- Implement doc-gen/engine.py (bootstrap mode)
- Implement ODS renderer
- Implement ODT renderer
- Build bootstrap field maps
- Implement DERIVED analyzers (4 analyzers)
- Build Stage 01–03 templates
- End-to-end test with fixture archive

### Phase 5.4 — Recovery Doc Gen (7–10 days)
- Extend doc-gen engine with recovery mode
- Build dependency graph builder
- Implement topological sort + restore wave grouping
- Build recovery field maps
- Build recovery templates (workbook, runbook, readiness report)
- End-to-end test with fixture five-state archive

### Phase 5.5 — Readiness Scoring (3–4 days)
- Implement scoring model
- Implement cascade scoring
- Integrate with recovery doc gen
- Write tests for scoring edge cases

### Phase 5.6 — Historical State Integration (4–5 days)
- Implement snapshot index
- Implement drift detector
- Implement documentation drift detection
- Wire historical state into doc gen
- Verify reproducibility requirement

**Total estimated effort: 24–33 working days**

---

## 13. Example Generated Bootstrap Artifacts

### 13.1 Example: Auto-populated Stage 02 Workbook Row

Assessment collected: CPU = `Intel Core i9-13900K`, 24 cores, 48 threads, 64 GB RAM

Generated workbook cell C8 (CPU Model): `Intel(R) Core(TM) i9-13900K`
Generated workbook cell C9 (Total RAM): `64 GB`
Generated workbook cell C10 (Core count): `24 physical / 48 logical`
Generated workbook cell C11 (Architecture): `x86_64`

Before Phase 5: operator transcribed these manually from `lscpu` output.
After Phase 5: cells pre-filled; operator validates and signs off.

### 13.2 Example: DERIVED Storage Recommendation

Assessment collected: 2 SSDs detected (sda: Samsung 870 EVO 1TB, sdb: Samsung 870 EVO 1TB)

Generated workbook cell D20 (ZFS Topology): `mirror`
Generated workbook note: `Two non-rotational block devices detected (sda, sdb). ZFS mirror
recommended. Provides redundancy with no write penalty vs. single device.`

### 13.3 Example: UNRESOLVED Field Handling

Assessment ran without dmidecode available.

Generated workbook cell C6 (Hardware Serial):
`[UNRESOLVED] dmidecode was not available during assessment.
To collect: run "dmidecode -s system-serial-number" as root.
Readiness impact: LOW — informational only. Does not affect recovery.`

The field is visible and explained. The operator can fill it in if desired.
It is never silently blank.

### 13.4 Example: HUMAN Field Prompt

Generated workbook cell C35 (Root password location):
`[HUMAN INPUT REQUIRED] Enter the KeePass database path where the root password
will be stored. Example: Infrastructure/proxmox/pve01-root`

---

## 14. Example Generated Recovery Artifacts

### 14.1 Example: Restore Sequence (generated from dependency graph)

```
Recovery Restore Sequence — pve01
Generated: 2026-05-30
Assessment basis: assessment_2026-05-29_02_00_00

Wave 1 — Physical Infrastructure
  Component: pve01 (Proxmox host)
  Backup: PBS job pve01-full, last run 2026-05-29 02:00 (1 day ago)
  Readiness: GREEN
  Steps: Restore from Proxmox ISO; restore ZFS pool from backup; validate SSH access

Wave 2 — Storage Layer
  Component: rpool (ZFS mirror, sda+sdb)
  Note: Storage must be available before VM restore
  Steps: Verify ZFS pool imported; run zpool status; validate health

Wave 3 — Core Infrastructure VMs
  Component: forgejo (VM 101)
  Backup: PBS job vm-101-daily, last run 2026-05-28 03:00 (2 days ago)
  Readiness: YELLOW (backup age 2 days; threshold 1 day for tier-1 services)
  Dependencies: rpool (Wave 2)
  Steps: qmrestore /path/to/backup 101; qm start 101; validate git clone works

Wave 4 — Dependent Services
  Component: assessment-engine (VM 103)
  Backup: PBS job vm-103-daily, last run 2026-05-29 03:00 (1 day ago)
  Readiness: GREEN
  Dependencies: forgejo (Wave 3), rpool (Wave 2)
  Steps: qmrestore /path/to/backup 103; qm start 103; validate assessment run
```

### 14.2 Example: Recovery Readiness Report Summary

```
Overall readiness: YELLOW

GREEN  (2): pve01, assessment-engine
YELLOW (1): forgejo — backup age 2 days (threshold 1 day for tier-1 services)
ORANGE (0):
RED    (0):
BLOCKED(0):

Action required before recovery exercise:
1. Verify forgejo backup schedule is running daily
2. Record forgejo service account password in KeePass (UNRESOLVED field)
3. Perform restore test for forgejo VM to isolated environment (never tested)
```

---

## 15. Success Criteria

Phase 5 is complete when:

1. `./bootstrap.sh` on a fresh Proxmox host produces a valid `manifest.json`
2. `python3 doc-gen/engine.py --mode bootstrap --archive <file>` produces:
   - A Stage 01–03 workbook with ≥ 60% of fields pre-filled (AUTO + DERIVED)
   - A Stage 01–03 runbook with all infrastructure-specific command parameters populated
   - Zero silently missing fields (all gaps are UNRESOLVED with explanation)
3. `python3 doc-gen/engine.py --mode recovery --archive <file>` produces:
   - A recovery workbook
   - A recovery runbook with pre-populated restore commands
   - A dependency graph
   - A restore sequence ordered by dependency
   - A readiness report with per-component scores
4. The generated Stage 02 workbook requires no manual transcription of:
   CPU, RAM, storage, network, VM list, container list, package list, service list
5. Historical snapshots are reproducible (regression test passes)
6. All UNRESOLVED fields include reason, collection guidance, and readiness impact
