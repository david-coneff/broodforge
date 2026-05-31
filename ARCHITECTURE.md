# Assessment Engine — Architecture

Version: 4.0
Last updated: 2026-05-30
Review document: docs/ARCHITECTURE-REVIEW-v4.md

---

## Overview

The Assessment Engine is the documentation and recovery intelligence layer of a
reproducible infrastructure platform. Its primary objective is to enable complete
destroy-and-recreate reconstruction of the environment from repository state alone.

Documentation is a generated artifact, not a manually maintained one. Recovery
procedures are derived from structured state, not authored by operators.

---

## Six-Layer Infrastructure Lifecycle

```
Layer 1 — Infrastructure Definition
  OpenTofu · Resources · Variables · Modules · Network topology as code
  ↓ (qm create / qm clone)

Layer 2 — Infrastructure Provisioning  [FIRST-CLASS]
  Cloud-Init user-data · network-config · vendor-data · Proxmox snippets
  VM templates · Base image registry · Template provenance
  First-boot ordering · Deployment provenance records
  ↓ (first boot completes, SSH available)

Layer 3 — Configuration Management
  Ansible inventory · Playbooks · Roles · Collections
  Group vars · Host vars · Configuration repositories
  ↓ (software installed, services configured)

Layer 4 — Service Deployment
  Service contracts · Secret references · DNS registration
  Backup job registration · Reverse proxies · Databases
  ↓ (environment running)

Layer 5 — Assessment and Validation
  Tier 1 bootstrap assessment · Tier 2 full assessment
  Drift detection · Dependency validation · Capacity validation
  ↓ (structured state model)

Layer 6 — Documentation and Recovery Intelligence
  Bootstrap docs · Operational docs · Recovery docs
  Dependency graphs · Restore sequences · Readiness reports
```

---

## Seven-State Model

### State 1 — Declared State
Source: OpenTofu repositories

- VM resource specifications (vmid, cores, memory, disk, bridge)
- Network topology declarations (bridges, VLANs, firewall rules)
- Storage topology (ZFS pools, PVE storage definitions)
- OpenTofu state files and workspace versions

Schema: `data-model/declared-state-schema.json`

### State 2 — Bootstrap State  *(v4.0)*
Source: Bootstrap repository (`proxmox-bootstrap/`)

- Cloud-Init user-data per VM (content + SHA256 hash)
- Cloud-Init network-config per VM (static IP, gateway, DNS)
- Cloud-Init vendor-data / Proxmox snippets
- Base image registry (ISO name, checksum, source URL)
- VM template registry (template name, base image, build manifest)
- Deployment provenance records (how each VM was built)
- Secret Registry (KeePass path references for all secrets)
- DNS Registry (hostname → IP mappings)
- Service Contracts (interfaces provided and required per service)
- First-boot ordering constraints

Schema: `data-model/bootstrap-state-schema.json`

### State 3 — Configured State
Source: Ansible / Inventory repositories

- Ansible inventory (hosts, groups, variables)
- Playbook manifests and role assignments
- Collection dependencies (requirements.yml)
- Configuration repositories (git URLs + pinned commits)

Schema: `data-model/configured-state-schema.json`

### State 4 — Service State  *(v4.0)*
Source: Service metadata repositories + Tier 2 assessment

- Running service inventory (name, VM, port, protocol, URL)
- Service dependency declarations (service contracts)
- Database schemas and migration state
- Secret references (KeePass paths per service)
- Backup job assignments
- DNS registrations
- Service ownership metadata
- Last verified health check timestamp

Schema: `data-model/service-state-schema.json`

### State 5 — Observed State
Source: Tier 1 and Tier 2 assessment packages

- Hardware inventory (CPU, RAM, storage)
- Network inventory (interfaces, bridges, VLANs, IPs)
- VM and container inventory
- Software and service inventory
- Dependency inventory (observed relationships)
- Capacity utilisation

Schema: `data-model/observed-state-schema.json`

### State 6 — Historical State
Source: Assessment history store

- Timestamped observed-state snapshots
- Drift records between snapshots
- Capacity and dependency evolution logs

Schema: `data-model/historical-state-schema.json`

### State 7 — Recovery State
Source: Generated documentation artifacts

- Recovery workbooks and runbooks
- Restore sequences and dependency graphs
- Recovery readiness reports and scores
- Capacity validation results

Schema: `data-model/recovery-state-schema.json`

---

## Assessment Tiers

### Tier 1 — Bootstrap Assessment
**Purpose:** Collect observed state from a freshly installed Proxmox host.
**Constraints:** Single shell script, Python 3 stdlib only, no network required.
**Output:** `manifest.json` (observed state) + `.tar.gz` archive

### Tier 2 — Full Assessment
**Purpose:** Deep analysis of a deployed environment across all seven state categories.
**Reads:** Proxmox API, Forgejo repositories, Ansible inventory, OpenTofu state,
         Bootstrap State repository, Service Contracts, backup inventory.
**Output:** Full seven-state `manifest.json` + dependency graph + readiness report

---

## Documentation Generation: Three Classes

### Class A — Bootstrap Documentation
**Generated from:** Tier 1 assessment + Declared State + Bootstrap State

Stages:
- Stage 01: Host preparation (ZFS, network from declared topology)
- Stage 02: Template creation (base image from registry, Cloud-Init snippet setup)
- Stage 03–N: VM provisioning (Cloud-Init pre-populated from Bootstrap State)

Key capability: Cloud-Init snippets, IPs, and credentials pre-populated from state.
Operators fill in only information that is genuinely undiscoverable.

### Class B — Operational Documentation  *(v4.0)*
**Generated from:** Current Tier 2 assessment + historical assessments

Contents:
- Current infrastructure inventory
- Drift summary since last assessment
- Capacity trends
- Dependency map (current state)
- Service health summary
- Secret registry completeness

### Class C — Recovery Documentation
**Generated from:** Historical assessments + Declared State + Bootstrap State +
                    Configured State + Service State + backup metadata

Contents:
- Recovery readiness report
- Dependency graph
- Restore sequence (waves, with pre-populated commands)
- Per-component restore procedures
- Secret retrieval steps (from Secret Registry)
- Cloud-Init and Ansible replay instructions
- Capacity validation
- Validation checkpoints

Key capability: Commands include exact IPs (DNS Registry), exact snippet paths
(Bootstrap State), exact secret references (Secret Registry). Minimal placeholders.

---

## Dependency Discovery

Sources used (in priority order):

1. **Service Contracts** (declared) — primary source; replaces heuristics
2. **OpenTofu `depends_on`** (declared) — infrastructure-level dependencies
3. **Network topology** (observed) — VM-to-VM communication
4. **Storage topology** (observed) — shared pool dependencies
5. **Service probing** (observed) — systemd Requires/After
6. **Name heuristics** (fallback) — pattern matching as last resort

---

## Recovery Readiness Scoring

Scoring inputs (v4.0 — expanded from v3.0):

| Input | Missing → |
|---|---|
| Backup present | RED |
| Backup age within threshold | YELLOW / ORANGE |
| Restore tested within 90 days | YELLOW |
| Failed backup run | RED |
| No offsite backup (host/storage) | YELLOW |
| Cloud-Init snippet in repository | ORANGE |
| Cloud-Init matches deployed version | YELLOW |
| Deployment provenance record exists | YELLOW |
| Service contract declared | YELLOW |
| Secret registry entry complete | ORANGE |
| DNS registry entry exists | YELLOW |
| Reconstruction playbook validated | YELLOW |
| Base image in template registry | ORANGE |
| Capacity validation passes | ORANGE if fails |

Score hierarchy: GREEN < YELLOW < ORANGE < UNKNOWN < BLOCKED < RED

BLOCKED propagates from RED through dependency edges (iterative until stable).

---

## Repository Layout

```
proxmox-assessment-engine/    (this repository)
  assessment/
    tier1/                    Bootstrap assessment package
    tier2/                    Full assessment engine
  data-model/                 JSON schemas (7 state types)
  doc-gen/
    engine.py                 Documentation generation CLI
    analyzers.py              DERIVED field analyzers
    dependencies.py           Dependency graph builder
    readiness.py              Recovery readiness scorer
    readiness_report.py       Standalone report generator
    field-maps/               Field classification maps
    renderers/                ODS, ODT, graph renderers
  history/                    Assessment snapshots
  reports/                    Generated documentation
  tests/

proxmox-infrastructure/       (Infrastructure Definition)
  tofu/

proxmox-bootstrap/            (Bootstrap State — new)
  snippets/
    user-data/
    network-config/
    vendor-data/
  templates/
  images/registry.yaml
  provenance/
  secret-registry.yaml
  dns-registry.yaml
  service-contracts/

proxmox-inventory/            (Configured State)
proxmox-ansible/              (Configuration)
proxmox-reconstruction/       (Reconstruction Playbooks — new)
```

---

## Architecture Decision Records

See `.ai/decisions.md` for full ADR history.

Key decisions added in v4.0:

- **AD-006:** Cloud-Init elevated to first-class Bootstrap State
- **AD-007:** Service Contracts replace dependency heuristics as primary edge source
- **AD-008:** Secret Registry tracks references only (never secret values)
- **AD-009:** DNS Registry pre-populates commands; eliminates `[VM_IP]` placeholders
- **AD-010:** Three documentation classes (bootstrap, operational, recovery)
- **AD-011:** Deployment Provenance Records enable reproducible reconstruction
- **AD-012:** Reconstruction Playbooks are generated artifacts, not manually authored
