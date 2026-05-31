# Assessment Engine — Architecture

Version: 5.0
Last updated: 2026-05-31
Review document: docs/ARCHITECTURE-REVIEW-v5.md

---

## Overview

The Proxmox Assessment Engine is the foundation of a Federated Infrastructure Digital
Twin Platform. Its objective is to enable complete, automated, and verifiable
reconstruction of any cell in the federation from repository state alone — even years
after initial deployment, even by a replacement administrator with no prior knowledge,
even when the failed cell cannot assist in its own recovery.

Documentation is a generated artifact. Recovery procedures are derived from structured
state. All outputs derive from the Digital Twin.

---

## Core Concepts

### Infrastructure Cell
The primary architectural object. An independently deployable and independently
recoverable infrastructure unit. A cell may be a single Proxmox node, a Proxmox
cluster, a PBS deployment, a storage appliance, or any other independently recoverable
unit. Every schema, every assessment, every documentation output is cell-scoped.

### Federation
A collection of Infrastructure Cells maintaining controlled, declared relationships.
The top-level architectural object. Federation State tracks cell registry, inter-cell
relationships (typed and directed), capability index, and recovery relationship graph.

### Digital Twin
The persistent, authoritative, continuously updated structured representation of the
federation and all its cells. The Digital Twin is the source from which all
documentation, all readiness reports, and all reconstruction playbooks are generated.

### Recovery Relationships
Distinct from Operational Dependencies. Cell C holds Cell A's backups. Cell D can
execute reconstruction playbooks for Cell A. Cell E can temporarily host Cell A's
workloads. These are recovery relationships — a separate dependency graph from
operational dependencies.

---

## Architecture Hierarchy

```
Federation
└── Infrastructure Cell  [primary recovery unit]
    └── Cluster  [may be single-node]
        └── Node
            ├── Platform
            ├── Storage
            ├── Network
            └── Infrastructure (VMs/Containers)
                └── Services
                    └── Data
```

Each level has its own state representation in the Digital Twin, its own documentation
class, its own recovery readiness score, and can be recovered independently where
dependencies permit.

---

## Six-Layer Infrastructure Lifecycle

```
Layer 1 — Infrastructure Definition
  OpenTofu · Resources · Variables · Network topology as code
  ↓

Layer 2 — Infrastructure Provisioning
  Cloud-Init user-data · Cloud-Init network-config · Proxmox snippets
  VM templates · Base image registry · Deployment provenance
  Hardware requirements · First-boot ordering
  ↓

Layer 3 — Configuration Management
  Ansible inventory · Playbooks · Roles · Collections
  ↓

Layer 4 — Service Deployment
  Service contracts · Secret references · DNS registration
  Backup job registration · External dependency registration
  ↓

Layer 5 — Assessment and Validation
  Tier 1, 2, and 3 assessment · Drift detection
  Dependency validation · Capacity validation · Trust verification
  ↓

Layer 6 — Documentation and Recovery Intelligence
  Digital Twin maintenance · All documentation classes
  Dependency graphs · Readiness reports · Reconstruction playbooks
```

---

## Seventeen-State Model

### Group A — Infrastructure Reality

| # | State | Source | Schema |
|---|---|---|---|
| 1 | Hardware State | Physical assessment, IPMI, vendor APIs | `hardware-state-schema.json` |
| 2 | Platform State | Proxmox API, host assessment | `platform-state-schema.json` |
| 3 | Cluster State | Proxmox cluster API, Corosync | `cluster-state-schema.json` |
| 4 | Storage State | ZFS CLI, Ceph API, Proxmox storage API | `storage-state-schema.json` |
| 5 | Network State | Network assessment, OpenTofu | (extends declared-state-schema) |

### Group B — Deployment Knowledge

| # | State | Source | Schema |
|---|---|---|---|
| 6 | Declared State | OpenTofu repositories | `declared-state-schema.json` |
| 7 | Bootstrap State | Bootstrap repository | `bootstrap-state-schema.json` |
| 8 | Configured State | Ansible / inventory repositories | `configured-state-schema.json` |
| 9 | Service State | Service metadata repositories + assessment | `service-state-schema.json` |
| 10 | External Dependency State | Manual declaration, provider APIs | `external-dependency-state-schema.json` |

### Group C — Operational State

| # | State | Source | Schema |
|---|---|---|---|
| 11 | Observed State | Tier 1 and Tier 2 assessment | `observed-state-schema.json` |
| 12 | Data Protection State | PBS API, backup job assessment | `data-protection-state-schema.json` |
| 13 | Observability State | Monitoring platform API | `observability-state-schema.json` |
| 14 | Secret Reference State | Secret Registry, declarations | `secret-reference-state-schema.json` |

### Group D — Coordination State

| # | State | Source | Schema |
|---|---|---|---|
| 15 | Capability State | Cell self-declaration + assessment | `capability-state-schema.json` |
| 16 | Federation State | Federation registry, trust establishment | `federation-state-schema.json` |
| 17 | Historical State | Assessment history store | `historical-state-schema.json` |

**Note:** Recovery documentation (workbooks, runbooks, readiness reports, reconstruction
playbooks) is generated OUTPUT from the above seventeen states. It is not a state
category. See Documentation Generation section.

---

## Assessment Tiers

### Tier 1 — Bootstrap Assessment
**Purpose:** Observed state from a freshly installed Proxmox host.
**Constraints:** Single shell script, Python 3 stdlib only, no network required.
**Collects:** Hardware State (partial), Platform State (partial), Observed State.
**Output:** manifest.json + .tar.gz archive

### Tier 2 — Full Assessment
**Purpose:** Complete state assessment of a deployed cell.
**Reads:** Proxmox API, all repositories, PBS API, monitoring API, external APIs.
**Collects:** All seventeen state categories (with varying confidence levels).
**Output:** Full seventeen-state manifest + dependency graphs + readiness report

### Tier 3 — Federation Assessment
**Purpose:** Cross-cell relationship verification and federation readiness.
**Reads:** All cells' twin state, inter-cell trust relationships, capability index.
**Collects:** Federation State, trust relationship verification, capability verification,
             recovery relationship testing.
**Output:** Federation Readiness Report + updated federation capability index

---

## Five Dependency Graph Types

| Graph | Edge Meaning | Use |
|---|---|---|
| Operational | A requires B to function | Restore wave ordering, BLOCKED propagation |
| Recovery | Recovering A requires access to B | Cross-cell recovery coordination |
| Trust | Operation X requires Cell P to trust Cell Q | Trust gap detection |
| Execution | Reconstructing A requires capability C on Cell X | Coordinator selection |
| Failure Domain | Failure of A causes B to fail | Blast radius, SPOF detection |

---

## Documentation Generation

All documentation is generated from the Digital Twin. No level's documentation is
manually authored.

```
Federation Level:   Federation Workbook · Federation Runbook
Cell Level:         Cell Workbook · Cell Runbook
                    Bootstrap Workbook · Bootstrap Runbook
                    Operational Workbook · Operational Runbook
                    Recovery Workbook · Recovery Runbook
Cluster Level:      Cluster Workbook · Cluster Runbook
Node Level:         Node Workbook · Node Runbook
Supporting:         Dependency Workbook · Recovery Readiness Report
                    Validation Sheets · Command Reference Sheets
                    Reconstruction Playbooks (executable, generated)
```

All documents follow: **Observe → Decide → Act → Record → Validate**

---

## Recovery Readiness Scoring

Readiness is evaluated at six levels: Service, VM, Node, Cluster, Cell, Federation.

Score hierarchy: GREEN < YELLOW < ORANGE < UNKNOWN < BLOCKED < RED

A higher-level score is never better than its worst component score.

Field confidence levels: DECLARED · OBSERVED · DERIVED · INFERRED · HUMAN · STALE · UNRESOLVED

---

## Federated Reconstruction — Seven Phases

When a cell fails catastrophically:

```
Phase 0 — Activation        Recovery coordinator assembles recovery package
Phase 1 — Environment       Identifies available cells and assigns roles
Phase 2 — Foundation        Hardware verification + Proxmox installation
Phase 3 — Platform          Platform config, certificates, network, storage
Phase 4 — Bootstrap         ISO download, template rebuild, snippet upload
Phase 5 — VM Reconstruction Per dependency wave: create, configure, restore, validate
Phase 6 — Validation        Tier 2 assessment, contract validation, twin update
Phase 7 — Cleanup           Release temp hosting, re-establish trust, schedule review
```

---

## Repository Layout

```
<cell-id>-assessment-engine/    This repository (per cell)
  assessment/tier1/             Bootstrap assessment
  assessment/tier2/             Full assessment engine
  assessment/tier3/             Federation assessment
  twin/                         Digital Twin state store
  doc-gen/                      Documentation generation engine
  history/                      Local history store
  reports/                      Generated documentation
  data-model/                   All 17+ JSON schemas

<cell-id>-infrastructure/       Infrastructure Definition (OpenTofu)
<cell-id>-bootstrap/            Bootstrap State (Cloud-Init, registries, secrets, DNS)
<cell-id>-configuration/        Configured State (Ansible)
<cell-id>-reconstruction/       Reconstruction Playbooks (generated)

federation-registry/            Federation State (shared across all cells)
```

---

## Key Design Principles

1. **Reconstruction is the objective.** Every decision is evaluated against:
   "Does this enable reconstruction from repository state after complete infrastructure loss?"

2. **Documentation is generated, not authored.** Operators provide only what cannot
   be discovered automatically.

3. **Cell scope is universal.** Every schema carries `cell_id`. No single-environment
   assumptions anywhere in the data model.

4. **The Digital Twin is the source of truth.** All outputs derive from the twin.
   Operators never author outputs directly.

5. **Recovery relationships are explicit.** Which cell holds what for whom is declared
   and verified, not assumed.

6. **Missing information is surfaced, never silently omitted.** UNRESOLVED fields
   include reason, collection guidance, and readiness impact.

7. **Staleness is visible.** Fields past their staleness threshold are marked STALE.
   STALE is different from UNRESOLVED — it has a historical value that may be stale.

8. **Historical snapshots are reproducible.** Same twin state always produces same outputs.

9. **Readiness scoring is honest.** RED means recovery will likely fail. ORANGE means
   it will be difficult. YELLOW means it will be slower than it should be.

10. **Trust is declared and verified.** Inter-cell trust relationships have expiry,
    are verified at Tier 3 assessment, and expired trust degrades federation readiness.

---

## Architecture Decision Records

Full ADR history: `.ai/decisions.md`

Key additions in v5.0:

- **AD-013:** Infrastructure Cell is the primary architectural object; `cell_id` mandatory
- **AD-014:** Federation is a first-class object with its own schemas and assessment tier
- **AD-015:** Recovery State reclassified from state category to documentation output class
- **AD-016:** Seventeen state categories replace seven
- **AD-017:** Five dependency graph types with distinct semantics
- **AD-018:** Capability State enables dynamic recovery planning
- **AD-019:** Tier 3 Federation Assessment for cross-cell relationship verification
- **AD-020:** Digital Twin is the authoritative source for all generated outputs
- **AD-021:** Staleness is a first-class field confidence level
