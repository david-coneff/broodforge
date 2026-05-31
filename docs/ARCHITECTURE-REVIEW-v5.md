# Architecture Review — v5.0
## Federated Infrastructure Digital Twin Platform

Date: 2026-05-31
Status: Proposed — supersedes v4.0
Replaces: docs/ARCHITECTURE-REVIEW-v4.md (retained for reference)

---

## 1. Review Mandate

This review was commissioned with an explicit instruction: do not assume the existing
architecture is correct. Challenge all assumptions. Evaluate whether the project should
evolve beyond an assessment engine into a federated infrastructure digital twin platform.

The v4.0 architecture is evaluated for what it got right, what it got wrong, and what
it is structurally incapable of modeling. The outcome is a ground-up redesign that retains
valid decisions from v4.0 while replacing insufficient ones and introducing the concepts
required for the stated long-term objective.

---

## 2. What v4.0 Got Right

These decisions are retained without modification.

**The six-layer lifecycle model is correct.** The sequence Infrastructure Definition →
Provisioning → Configuration Management → Service Deployment → Assessment → Documentation
accurately reflects how infrastructure is built and how it must be reconstructed.
It generalizes cleanly to the federation model introduced in this review.

**The seven-state model is directionally correct.** Declared, Bootstrap, Configured,
Service, Observed, Historical, and Recovery State address real categories of infrastructure
knowledge. The model needs expansion, not replacement.

**Service Contracts as the primary dependency source is correct.** Declared contracts
are more reliable than heuristics. This principle extends to federation-level dependency
modeling: trust relationships between cells must also be declared, not inferred.

**The Secret Registry tracks references only.** This is the right boundary.
It extends naturally to federation scope: a secret may be held in a vault managed by
a different cell, and the registry must capture which cell holds it.

**UNRESOLVED is a first-class field state.** Silent gaps are worse than visible ones.
This principle applies at every level — node, cell, and federation.

**Reconstruction is the objective.** Every state category, metadata field, and generated
artifact should be evaluated against: "Does this enable reconstruction from repository
state after complete infrastructure loss?" This remains the primary test.

---

## 3. What v4.0 Got Wrong

These are structural problems that require correction, not extension.

### 3.1 The Single-Cell Assumption Is Implicit and Pervasive

Every schema, every assessment tier, every doc-gen output assumes exactly one environment:
one Proxmox host, one set of VMs, one set of repositories. There is no `cell_id` in any
schema. There is no concept of a relationship between environments. This is a structural
limitation that cannot be patched incrementally — it must be designed out from the schema
layer upward before federation can be added.

### 3.2 Recovery State Is Not a State Category

The seven-state model includes "Recovery State" as one of seven infrastructure state
categories. This is a category error. Recovery State (workbooks, runbooks, readiness
reports, restore sequences) is a class of generated output, not a description of
infrastructure reality. Infrastructure does not "have" a recovery state the way it has
declared state or observed state.

Corrected: Recovery State is reclassified as the Documentation Layer output. The state
model is expanded with genuine infrastructure state categories that were missing.

### 3.3 The Six-Layer Lifecycle Is Node-Centric

The six-layer model correctly models how a single node's VMs are built and configured.
It does not model how cells relate to each other, how federation trust is established,
or how a cell's operational existence depends on other cells. The model needs a
federation awareness layer above Infrastructure Definition and a horizontal trust layer
that spans all six layers.

### 3.4 Bootstrap State Is Too Narrowly Scoped

Bootstrap State in v4.0 covers Cloud-Init, base images, and deployment provenance. It
does not cover hardware bootstrap (BIOS settings, firmware, storage controller
configuration, RAID configuration). For a physical host, the hardware layer must reach
a known state before the platform layer can be installed. Hardware State is a genuine
first-class concern for reconstruction, not a footnote.

### 3.5 Service State Does Not Model External Dependencies

v4.0 Service State models services running inside the environment. It does not model
dependencies on external infrastructure: DNS providers, SMTP relays, certificate
authorities, identity providers, domain registrars. These are recovery concerns.
If the environment depends on an external identity provider and that provider is
unreachable during recovery, the entire service layer may be non-functional even if
internal reconstruction is complete.

### 3.6 Historical State Should Be a Service, Not a Category

The infrastructure does not "have" historical state the way it has declared state.
Historical state is an observational record maintained by an external service (the
assessment engine's history store). The distinction matters enormously at federation
scale: one cell may hold the historical assessment archive for another cell, and
the architecture must model this explicitly rather than assuming history is co-located
with the environment it describes.

---

## 4. Verdict

**The architecture should evolve into a Federated Infrastructure Digital Twin Platform.**

The rationale is not merely that federation is useful. It is that the primary design
objective — "a replacement administrator inherits this environment years from now and
can reconstruct it from available information" — cannot be fully satisfied by a
single-environment model.

In a real disaster scenario:
- The failed environment cannot assess itself.
- Documentation may be stored elsewhere.
- Backup metadata may be on a separate PBS cell.
- The reconstruction coordinator runs from a surviving cell.
- Recovery assistance comes from cells that trust the failed one.

A single-environment architecture cannot model any of this. It produces documentation
that is useful when recovery conditions are ideal (the environment is partially intact,
the administrator is familiar with it). It fails when conditions are worst (total loss,
unfamiliar inheritor, years of accumulated state change).

The Digital Twin Platform is the architecture that survives the worst case.

---

## 5. Core Concepts

### 5.1 Infrastructure Cell

An Infrastructure Cell is an independently deployable and independently recoverable
infrastructure unit. It is the primary architectural object of the platform.

A cell has:
- A stable, unique identity (cell_id)
- Its own repositories (infrastructure, bootstrap, configuration, service contracts)
- Its own assessment history
- Its own documentation
- Its own recovery procedures
- Its own declared capabilities
- Defined relationships with other cells (operational, trust, recovery)

A cell may contain:
- A single Proxmox node
- A Proxmox cluster
- A PBS deployment
- A storage appliance
- An identity platform
- A monitoring platform
- A future Kubernetes deployment
- Any other independently recoverable infrastructure unit

A cell is the unit at which recovery readiness is evaluated, recovery procedures are
generated, and federated reconstruction assistance is offered or received.

### 5.2 Federation

A Federation is a collection of Infrastructure Cells maintaining controlled, declared
relationships. The Federation is the top-level architectural object.

A federation has:
- A stable identity (federation_id)
- A registry of member cells
- Declared inter-cell relationships (by type)
- Federation-level documentation
- Federation-level recovery readiness assessment
- Federation-level reconstruction coordination capability

Federation relationships are directed and typed. Cell A trusting Cell B for backup
access does not imply Cell B trusting Cell A for anything. Every relationship is
explicitly declared, has a defined scope, and can be revoked.

### 5.3 The Digital Twin

The Digital Twin is the persistent, continuously updated structured representation of
the federation and all its cells. It is not the assessment engine. The assessment engine
is one of several inputs that feed the twin.

The Digital Twin is:
- The authoritative source of truth for infrastructure state across all cells
- Updated by assessment, by repository ingestion, by deployment events, by operator input
- The source from which all documentation is generated
- The basis for all recovery readiness evaluation
- The basis for all federated reconstruction planning

All generated outputs (workbooks, runbooks, readiness reports, reconstruction playbooks)
derive from the Digital Twin. Two operators running the same generation command against
the same twin state produce identical output.

### 5.4 Recovery Relationships

Recovery Relationships are a distinct category from Operational Dependencies.

Operational Dependency: Cell A depends on Cell B's DNS service to function.
Recovery Relationship: Cell C holds Cell A's backup archives.

These are different graphs. Operational dependency traversal determines what must be
running for the environment to function. Recovery relationship traversal determines
what resources are available and must be accessed during reconstruction.

Recovery relationships include:
- Backup hosting (Cell C stores backups for Cell A)
- Documentation hosting (Cell D stores generated documentation for Cell A)
- History hosting (Cell E stores assessment history for Cell A)
- Execution capability (Cell F can execute reconstruction workflows for Cell A)
- Workload hosting (Cell G can temporarily host VMs belonging to Cell A)
- Coordination (Cell H can act as recovery coordinator for Cell A)

---

## 6. Revised Architecture Hierarchy

```
Federation
│   Identity, trust registry, inter-cell relationship map,
│   federation-level documentation and readiness
│
└── Infrastructure Cell  [primary recovery unit]
    │   Cell identity, capabilities, repository set, cell-level documentation,
    │   cell-level readiness, inter-cell relationships
    │
    └── Cluster  [may be single-node]
        │   Cluster identity, membership, Corosync topology, quorum,
        │   shared storage, shared services, cluster-level documentation
        │
        └── Node
            │   Hardware inventory, platform configuration, roles,
            │   node-level documentation and readiness
            │
            ├── Platform
            │   │   Proxmox config, package repositories, certificates,
            │   │   firewall, users, API tokens
            │   │
            ├── Storage
            │   │   ZFS pools, Ceph, CephFS, RBD, datastores,
            │   │   replication targets, backup storage
            │   │
            ├── Network
            │   │   Bridges, bonds, VLANs, SDN, routing, firewall
            │   │
            └── Infrastructure  [VMs and containers]
                │
                └── Services
                    │
                    └── Data
```

Each level of the hierarchy:
- Has its own state representation in the Digital Twin
- Has its own documentation class (workbook + runbook)
- Has its own recovery readiness score
- Can fail independently
- Can be recovered independently where its dependencies permit

---

## 7. Revised State Model — Eighteen Categories

The v4.0 seven-state model is expanded to eighteen categories organized into four
functional groups. Recovery State is reclassified as a documentation output class.

### Group A — Infrastructure Reality (what physically exists and how it is configured)

#### State 1 — Hardware State  *(new)*
Source: Physical assessment, vendor APIs, IPMI/iDRAC, manual entry

- Hardware inventory (CPU model, core count, socket count)
- Memory configuration (DIMMs, slots, ECC status)
- Storage controllers (HBA model, firmware, RAID configuration)
- Physical disk inventory (model, serial, capacity, interface, health)
- Network interfaces (model, ports, firmware, MAC addresses)
- BIOS/UEFI settings (boot order, virtualization flags, IOMMU)
- Firmware versions (BMC, HBA, NIC, storage controller)
- UPS integration (model, runtime, battery health)
- Physical location (rack, unit, datacenter, site)
- Vendor metadata (warranty, support contract, EOL date)

Schema: `data-model/hardware-state-schema.json`

Required for reconstruction: Yes — hardware configuration must be verified before
platform installation. BIOS settings, IOMMU, virtualization flags, and boot order
must match the expected state before Proxmox installation proceeds.

#### State 2 — Platform State  *(new)*
Source: Proxmox API, host assessment, configuration repositories

- Proxmox version and patch level
- Kernel version and parameters
- Package repositories (APT sources, pinned versions)
- SSL/TLS certificates (issuer, expiry, SANs)
- Host-level firewall configuration
- Host users and API tokens (references only, not values)
- Cron jobs and scheduled tasks
- Syslog and audit configuration
- NTP configuration
- Locale and timezone

Schema: `data-model/platform-state-schema.json`

Required for reconstruction: Yes — platform configuration beyond the Proxmox installer
defaults must be reproduced. Certificate placement, repository configuration, and
user/token setup are prerequisites for Ansible and OpenTofu access.

#### State 3 — Cluster State  *(new)*
Source: Proxmox cluster API, Corosync configuration, Ceph status

- Cluster identity (cluster name, UUID)
- Current membership (nodes, join dates)
- Historical membership (nodes added/removed, dates)
- Corosync topology (ring configuration, transport)
- Quorum configuration (votes, expected votes)
- Cluster networking (corosync interfaces, cluster network CIDR)
- Shared resources (cluster-level storage, shared VLANs)
- Cluster services (HA manager, migration policies)
- Cluster purpose (production, development, DR, edge)
- Recovery role (primary, secondary, witness)
- Federation role (coordinator, member, isolated)
- Historical evolution (when cluster formed, how it grew)

Schema: `data-model/cluster-state-schema.json`

Required for reconstruction: Yes — cluster reformation after node failure requires
exact knowledge of topology, quorum configuration, and historical membership.

#### State 4 — Storage State  *(new)*
Source: ZFS CLI, Ceph status API, Proxmox storage API

- ZFS pool topology (vdevs, mirrors, RAIDz, spares)
- ZFS pool properties (compression, ashift, recordsize)
- ZFS dataset hierarchy (datasets, volumes, snapshots, properties)
- Ceph cluster identity (FSID, cluster name)
- Ceph topology (OSDs, MONs, MGRs, MDSs)
- CephFS filesystems (name, pools, mount points)
- RBD pools and images
- Proxmox datastore definitions (type, path, content types)
- Storage replication (targets, schedules, current lag)
- Storage performance metrics (IOPS, latency, throughput baseline)

Schema: `data-model/storage-state-schema.json`

Required for reconstruction: Yes — ZFS pool import requires knowing the exact vdev
topology. Ceph reconstruction requires knowing the full OSD layout. Storage replication
relationships define recovery dependencies.

#### State 5 — Network State  *(new)*
Source: Network assessment, OpenTofu state, Proxmox network API

- Physical interfaces (name, MAC, speed, bonding membership)
- Bonds (mode, members, LACP settings)
- Bridges (name, ports, STP settings)
- VLANs (IDs, member interfaces, purpose)
- SDN zones and VNets (type, VXLAN parameters)
- Static routes (destination, gateway, interface)
- Host-level firewall rules (chains, rules, aliases)
- IP address assignments (host and bridge addresses)
- MTU configuration
- Network topology diagram metadata

Schema: Extends `data-model/declared-state-schema.json` (network section)

### Group B — Deployment Knowledge (how infrastructure was built and what it should be)

#### State 6 — Declared State  *(retained from v4.0)*
Source: OpenTofu repositories

- VM resource declarations (vmid, cores, memory, disk, network)
- Storage resource declarations
- Network topology declarations
- OpenTofu workspace versions and commit hashes
- Provider configurations
- Variable definitions

Schema: `data-model/declared-state-schema.json`

#### State 7 — Bootstrap State  *(expanded from v4.0)*
Source: Bootstrap repository

- Cloud-Init user-data (per VM, content + hash)
- Cloud-Init network-config (per VM, static IP, gateway, DNS)
- Cloud-Init vendor-data / Proxmox snippets
- Base image registry (ISO, checksum, download URL, version)
- VM template registry (template name, base image, build manifest)
- Deployment provenance records (complete build receipt per VM)
- First-boot ordering constraints
- Bootstrap credential references (KeePass paths)
- Hardware bootstrap requirements (BIOS flags required for this deployment)

Schema: `data-model/bootstrap-state-schema.json`

#### State 8 — Configured State  *(retained from v4.0)*
Source: Ansible / inventory repositories

- Ansible inventory (hosts, groups, variables)
- Playbook manifests and role assignments
- Collection dependencies
- Configuration repositories (git URLs + pinned commits)
- Group variables and host variables

Schema: `data-model/configured-state-schema.json`

#### State 9 — Service State  *(retained from v4.0)*
Source: Service metadata repositories + Tier 2 assessment

- Running service inventory (name, VM, port, protocol, URL)
- Service contracts (interfaces provided and required)
- Database schemas and migration state
- Secret references per service
- Backup job assignments
- DNS registrations

Schema: `data-model/service-state-schema.json`

#### State 10 — External Dependency State  *(new)*
Source: Manual declaration, DNS provider APIs, certificate provider APIs

- DNS providers (provider, zones managed, API access cell reference)
- DDNS services (provider, update mechanism, credentials reference)
- Domain registrars (registrar, domains, expiry dates, credentials reference)
- SMTP providers (provider, relay host, credentials reference)
- Certificate providers (CA, ACME endpoint, certificate inventory, expiry dates)
- Identity providers (provider type, SSO integration, credentials reference)
- External APIs (service name, provider, rate limits, credentials reference)
- CDN / reverse proxy services (provider, zones, credentials reference)

Schema: `data-model/external-dependency-state-schema.json`

Required for reconstruction: Yes — service restoration may fail if external dependencies
are unreachable or if credentials for external services are unknown. Certificate
expiry during recovery is a documented failure mode.

### Group C — Operational State (what is currently running and how it is performing)

#### State 11 — Observed State  *(retained from v4.0)*
Source: Tier 1 and Tier 2 assessment

- Hardware inventory (observed)
- Network inventory (observed)
- VM and container inventory (observed)
- Software and service inventory (observed)
- Dependency inventory (observed relationships)
- Capacity utilisation

Schema: `data-model/observed-state-schema.json`

#### State 12 — Data Protection State  *(new)*
Source: PBS API, backup job assessment, Tier 2 assessment

- PBS server inventory (hostname, version, datastore configuration)
- Backup datastore topology (path, garbage collection, prune policies)
- Backup job inventory (VM, schedule, datastore, retention)
- Last backup timestamp and status per VM
- Backup verification status (last verified, result)
- Offsite replication (sync targets, schedule, lag)
- Tape or cold storage integration (if applicable)
- Recovery time objective declarations (per VM)
- Recovery point objective declarations (per VM)
- Backup encryption configuration (key references)

Schema: `data-model/data-protection-state-schema.json`

Required for reconstruction: Directly — the recovery sequence depends on knowing which
PBS server holds which backups, what the most recent verified restore point is, and
whether offsite copies exist.

#### State 13 — Observability State  *(new)*
Source: Monitoring platform API, assessment, configuration repositories

- Monitoring stack inventory (tool, version, VM/host)
- Metrics collection targets (what is monitored, by which agent)
- Alert rule inventory (rule name, condition, severity, notification target)
- Dashboards (name, URL, purpose)
- Log aggregation configuration (targets, retention)
- Alerting channels (notification destinations, references to credentials)
- SLA / uptime targets (per service)
- Current alert status snapshot (active alerts at assessment time)

Schema: `data-model/observability-state-schema.json`

#### State 14 — Secret Reference State  *(elevated from Bootstrap State)*
Source: Secret Registry, assessment, manual declaration

Previously embedded within Bootstrap State. Elevated to a standalone state category
because secret references span all other state categories and must be queryable
independently.

- Secret inventory (id, description, KeePass path, owning cell)
- Required-by declarations (which component requires which secret)
- Required-for declarations (which operation the secret enables)
- Secret type (password, SSH key, API token, certificate private key)
- Rotation metadata (last rotated, rotation schedule, rotation procedure)
- Recovery path (how to obtain this secret if KeePass is inaccessible)
- Federation scope (which cell's secret store holds this secret)

Schema: `data-model/secret-reference-state-schema.json`

### Group D — Coordination State (how cells and federations are structured and related)

#### State 15 — Capability State  *(new)*
Source: Cell self-declaration, assessment verification

Capability State declares what an Infrastructure Cell is capable of doing. This is
the enabling model for federated reconstruction: when Cell A fails, the recovery
coordinator queries the federation's capability registry to find which cell can help.

Capabilities are declared and then verified by assessment. A cell claims a capability;
the assessment engine verifies that the capability is actually present and functional.

Capability categories:

```
Compute Capabilities
  - can_host_vms: can provision and run VMs
  - can_host_containers: can run LXC containers
  - available_ram_for_recovery: spare RAM available for temporary workloads
  - available_cpu_for_recovery: spare CPU threads for temporary workloads
  - available_storage_for_recovery: spare storage for temporary VM disks

Storage Capabilities
  - can_provide_pbs_service: can act as a Proxmox Backup Server
  - can_provide_ceph_service: participates in a Ceph cluster
  - can_store_backup_archives: can store backup archives for other cells
  - can_store_assessment_history: can store assessment history for other cells
  - can_store_documentation: can host generated documentation for other cells

Execution Capabilities
  - can_execute_opentofu: has OpenTofu installed and configured
  - can_execute_ansible: has Ansible installed and configured
  - can_execute_reconstruction_playbooks: has reconstruction executor installed
  - can_act_as_recovery_coordinator: can manage cross-cell recovery workflows

Network Capabilities
  - can_route_to_cells: list of reachable cell IDs
  - can_provide_dns: can serve DNS for other cells
  - can_provide_dhcp: can provide DHCP services

Assessment Capabilities
  - can_assess_tier1: can perform Tier 1 assessment on target cells
  - can_assess_tier2: can perform Tier 2 assessment on target cells
  - can_receive_assessment_from: list of cell IDs authorized to assess this cell
```

Schema: `data-model/capability-state-schema.json`

#### State 16 — Federation State  *(new)*
Source: Federation registry, cell self-declaration, trust establishment procedures

- Federation identity (federation_id, name, description)
- Member cell registry (cell_id, cell_name, cell_type, join_date)
- Inter-cell trust relationships (directed, typed, scoped)
- Trust relationship types:
  - api_trust: Cell A can call Cell B's API
  - ssh_trust: Cell A can SSH to Cell B (with which user)
  - assessment_trust: Cell A can run assessments of Cell B
  - monitoring_trust: Cell A can scrape metrics from Cell B
  - backup_trust: Cell A can write backups to Cell B
  - documentation_trust: Cell A can read documentation from Cell B
  - recovery_trust: Cell A can initiate recovery workflows on Cell B
  - execution_trust: Cell A can execute reconstruction playbooks on Cell B
  - workload_trust: Cell A can temporarily provision workloads on Cell B
  - delegation_trust: Cell A can delegate its recovery coordination to Cell B
- Trust relationship metadata (established date, last verified, expiry)
- Federation-level secret references (inter-cell API tokens, SSH keys)
- Recovery relationship map (who holds what for whom)

Schema: `data-model/federation-state-schema.json`

#### State 17 — Historical State  *(retained, reclassified)*
Source: Assessment history store (may reside in a different cell)

- Timestamped observed-state snapshots (cell-scoped)
- Drift records between snapshots
- Capacity evolution records
- Dependency evolution records
- Historical assessment metadata (who ran it, from which cell, using which tier)
- Cross-cell history relationships (which cell holds history for which other cell)

Schema: `data-model/historical-state-schema.json`

Note: The hosting cell for historical state may differ from the cell being described.
Federation State declares where each cell's history is stored.

#### State 18 — Recovery State  [RECLASSIFIED — NOT A STATE CATEGORY]

Recovery State is removed from the state model. It was a category error.
Recovery documentation (workbooks, runbooks, readiness reports, restore sequences,
reconstruction playbooks) is the OUTPUT of the Documentation Layer. It derives from
all seventeen state categories above. It does not describe the infrastructure — it
describes what to do when the infrastructure fails.

Recovery documentation is defined in Section 10 (Documentation Generation Architecture).

---

## 8. The Digital Twin Architecture

### 8.1 What the Digital Twin Is

The Digital Twin is the persistent, authoritative, continuously updated structured
representation of the federation and all its cells. It is not an assessment snapshot.
It is not a report. It is the living model of infrastructure reality.

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Digital Twin Platform                           │
│                                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│  │  Cell Twin  │  │  Cell Twin  │  │  Cell Twin  │  ...            │
│  │   Cell A    │  │   Cell B    │  │   Cell C    │                 │
│  │             │  │             │  │             │                 │
│  │ 17 states   │  │ 17 states   │  │ 17 states   │                 │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘                 │
│         │                │                │                         │
│         └────────────────┴────────────────┘                         │
│                          │                                          │
│               ┌──────────┴──────────┐                              │
│               │  Federation Layer   │                              │
│               │  Relationship map   │                              │
│               │  Capability index   │                              │
│               │  Recovery graph     │                              │
│               └─────────────────────┘                              │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.2 Twin Update Sources

The Digital Twin is updated from multiple sources on different cadences:

| Source | Trigger | Cadence | Updates |
|---|---|---|---|
| Tier 1 Assessment | Manual / scheduled | Weekly / on change | Hardware, Platform, Observed |
| Tier 2 Assessment | Manual / scheduled | Daily / on change | All observed state categories |
| Repository ingestion | Git webhook / scheduled | On push / hourly | Declared, Bootstrap, Configured, Service |
| Deployment event | Hook on tofu apply / ansible run | On deployment | Bootstrap (provenance), Configured |
| Operator declaration | CLI / web interface | On demand | Capability, Federation, External Deps, Secrets |
| PBS API | Scheduled | Daily | Data Protection |
| Monitoring API | Scheduled | Hourly | Observability |
| External provider APIs | Scheduled | Daily | External Deps (cert expiry, DNS) |

### 8.3 Twin Consistency Model

The Digital Twin is not transactional. Different state categories are updated at
different times by different sources. The twin explicitly tracks:

- Last updated timestamp per state category per cell
- Update source per state category
- Confidence level per field (OBSERVED, DECLARED, DERIVED, INFERRED, STALE)
- Staleness threshold per category (Hardware: 30 days; Observed: 7 days; Data Protection: 1 day)

Fields beyond their staleness threshold are surfaced as STALE in all generated outputs.
STALE is a new field class alongside AUTO, DERIVED, HUMAN, and UNRESOLVED.

### 8.4 Twin Storage Architecture

```
twin/
  federation/
    federation-state.json         Federation identity and cell registry
    relationships.json            All inter-cell relationships
    capabilities-index.json       Capability index across all cells
    recovery-graph.json           Recovery relationship graph
  cells/
    <cell_id>/
      identity.json               Cell identity and metadata
      hardware-state.json         State 1
      platform-state.json         State 2
      cluster-state.json          State 3
      storage-state.json          State 4
      network-state.json          State 5
      declared-state.json         State 6
      bootstrap-state.json        State 7
      configured-state.json       State 8
      service-state.json          State 9
      external-dependency-state.json  State 10
      observed-state.json         State 11
      data-protection-state.json  State 12
      observability-state.json    State 13
      secret-reference-state.json State 14
      capability-state.json       State 15
      federation-state.json       State 16 (cell's view)
      staleness-manifest.json     Last-updated + confidence per field
  history/
    <cell_id>/
      snapshots/                  Timestamped observed-state archives
      drift-records/              Field-level diff records
      index.json                  Snapshot index
```

---

## 9. Dependency Discovery Architecture

### 9.1 Dependency Graph Types

Five distinct dependency graph types must be maintained. Each has different semantics,
different traversal algorithms, and different uses in documentation and recovery planning.

#### Type 1 — Operational Dependencies
*What must be running for the environment to function.*

Edge semantics: "Component A requires Component B to operate."
Graph type: Directed acyclic graph (cycles indicate a misconfiguration).
Primary source: Service Contracts (declared).
Fallback sources: Network topology, systemd dependencies, name heuristics.
Use: Restore wave ordering, failure impact analysis, BLOCKED propagation in readiness scores.

```
Example:
  DNS Service → Identity Provider → Forgejo → CI/CD Pipeline
  ZFS Pool → Datastore → VM Disk → VM → Application
```

#### Type 2 — Recovery Dependencies
*What must be accessible to execute recovery.*

Edge semantics: "Recovering Component A requires access to Resource B."
Graph type: Directed graph (may have cycles across cells — Cell A needs Cell B's backups,
Cell B needs Cell A's documentation).
Primary source: Data Protection State, Federation State declarations.
Use: Recovery sequence planning, cross-cell recovery coordination, federated reconstruction.

```
Example:
  Recovering Cell A requires:
    → Cell B (holds Cell A's backup archives)
    → Cell C (holds Cell A's assessment history)
    → Cell D (holds Cell A's generated documentation)
    → Cell E (can execute reconstruction playbooks for Cell A)
```

#### Type 3 — Trust Dependencies
*Which cells must trust each other for operations to succeed.*

Edge semantics: "Operation X on Component A requires Cell P to trust Cell Q."
Graph type: Directed multigraph (multiple trust types between same pair).
Primary source: Federation State.
Use: Trust gap detection, federation readiness assessment, pre-recovery validation.

```
Example:
  Running Tier 2 assessment of Cell A from Cell B requires:
    → Cell A grants assessment_trust to Cell B
    → Cell B has ssh_trust or api_trust to Cell A
```

#### Type 4 — Execution Dependencies
*What execution capabilities are required and which cell provides them.*

Edge semantics: "Reconstructing Component A requires execution capability C on Cell X."
Graph type: Bipartite graph (reconstruction tasks ↔ cell capabilities).
Primary source: Capability State, Federation State.
Use: Federated reconstruction planning, coordinator selection.

```
Example:
  Reconstructing Cell A's VMs requires:
    → Cell with can_execute_opentofu capability
    → Cell with network route to Cell A's target hardware
    → Cell with can_act_as_recovery_coordinator capability
```

#### Type 5 — Failure Domain Dependencies
*What fails together when a component fails.*

Edge semantics: "Failure of Component A causes Component B to fail or degrade."
Graph type: Directed graph with failure propagation weights.
Primary source: Derived from Operational Dependencies + Cluster State + Storage State.
Use: Failure impact analysis, SPOF identification, blast radius calculation.

```
Example:
  Single ZFS pool → All VMs on that pool → All services in those VMs
  Single cluster node → HA-dependent VMs → Services in those VMs
  Network bridge failure → All VMs on that bridge → All services
```

### 9.2 Cross-Cell Dependency Resolution

When a dependency edge crosses a cell boundary, the dependency resolver must:

1. Identify the target cell from the Federation State cell registry
2. Verify the trust relationship required for the dependency type
3. Query the target cell's twin state (or use cached data with staleness check)
4. Evaluate whether the cross-cell dependency is recoverable independently

Cross-cell dependencies are annotated with:
- `cell_id` of the providing cell
- Trust relationship type required
- Whether the dependency can be substituted during recovery
- Which other cells could satisfy this dependency (alternatives)

---

## 10. Documentation Generation Architecture

### 10.1 Documentation Hierarchy

Documentation is generated at each level of the architecture hierarchy.
All outputs derive from the Digital Twin. No level's documentation is manually authored.

```
Federation Level
  ├── Federation Workbook      — All cells, all relationships, federation readiness
  └── Federation Runbook       — Federation-level recovery coordination procedures

Cell Level
  ├── Cell Workbook            — Full cell state across all 17 categories
  ├── Cell Runbook             — Cell-level reconstruction from scratch
  ├── Bootstrap Workbook       — Node construction and VM provisioning
  ├── Bootstrap Runbook        — Step-by-step bootstrap procedures
  ├── Operational Workbook     — Current state, drift, capacity, health
  ├── Operational Runbook      — Day-to-day administration procedures
  ├── Recovery Workbook        — Recovery readiness, dependency graph, restore plan
  └── Recovery Runbook         — Step-by-step recovery procedures

Cluster Level
  ├── Cluster Workbook         — Cluster topology, membership, shared resources
  └── Cluster Runbook          — Cluster reformation and reconstruction procedures

Node Level
  ├── Node Workbook            — Hardware, platform, storage, network state
  └── Node Runbook             — Node-level restore and configuration procedures

Supporting Artifacts
  ├── Dependency Workbook      — All five dependency graph types, visualised
  ├── Recovery Readiness Report — Scored readiness at all levels
  ├── Validation Sheets        — Post-recovery verification checklists
  ├── Command Reference Sheets — Pre-populated operational commands
  └── Reconstruction Playbooks — Executable reconstruction scripts (generated)
```

### 10.2 Generation Pipeline

All documentation is generated by the same engine from the same Digital Twin state.
The generation pipeline:

```
Digital Twin (authoritative state)
    │
    ├── State Resolver        — Resolves all state categories for target scope
    │   (cell, cluster, node, or federation scope)
    │
    ├── Field Classifier      — Classifies each field:
    │   AUTO, DERIVED, HUMAN, UNRESOLVED, STALE
    │
    ├── Dependency Resolver   — Builds all five dependency graphs for scope
    │
    ├── Readiness Scorer      — Scores readiness at all applicable levels
    │
    ├── Template Engine       — Applies document templates to resolved fields
    │
    └── Renderer              — Produces ODS, ODT, MD, JSON, executable scripts
```

### 10.3 Observe → Decide → Act → Record → Validate

All generated documentation follows this procedural structure:

**Observe:** Automated section — populated from Digital Twin state.
Pre-populated technical information. The operator reads, does not enter.

**Decide:** Semi-automated section — derived recommendations with rationale.
The operator reviews DERIVED fields and confirms or overrides.

**Act:** Procedure section — pre-populated commands with known values substituted.
Placeholders appear only for genuinely undiscoverable information.

**Record:** Post-action section — operator records actual values, deviations, timestamps.
These records become inputs to the next assessment cycle.

**Validate:** Verification section — pre-populated validation commands and expected outputs.
The operator runs commands and records results. Failures indicate a problem.

---

## 11. Failure Domain Architecture

### 11.1 Failure Domain Taxonomy

```
Failure Domain Level    │ Scope                    │ Recovery Boundary
────────────────────────┼──────────────────────────┼──────────────────────────────
Service                 │ Single application        │ Service restart / failover
Container               │ LXC instance              │ Container restore from backup
VM                      │ Single virtual machine    │ VM restore or recreation
Node                    │ Physical host             │ Host restore + VM migration
Multi-Node              │ Subset of cluster         │ Cluster rebalancing + HA
Cluster                 │ Full cluster              │ Full cluster reconstruction
Storage                 │ ZFS pool / Ceph cluster   │ Pool rebuild or restore
PBS                     │ Backup server             │ PBS rebuild + archive verify
Network                 │ Bridge / VLAN / SDN zone  │ Network reconfiguration
Cell                    │ Infrastructure Cell       │ Full cell reconstruction
Multi-Cell              │ Multiple cells            │ Coordinated cell recovery
Federation Partition    │ Cell connectivity loss    │ Federation re-establishment
Datacenter-Wide         │ All cells at one site     │ DR site activation
```

### 11.2 Failure Propagation Rules

Each failure domain has defined propagation rules that the recovery planner uses:

- **Storage failure** propagates to all VMs on that storage, then to all services in those VMs.
- **Node failure** propagates to all non-HA VMs on that node. HA VMs migrate (if possible).
- **Cluster failure** propagates to all cluster-managed resources (HA, shared storage, SDN).
- **Cell failure** propagates to all cells with operational dependencies on the failed cell,
  and activates recovery relationships for cells that provide recovery assistance.
- **Federation partition** does not propagate in terms of failure but activates partition-
  tolerant recovery modes where defined.

### 11.3 Blast Radius Calculation

The Failure Domain model enables blast radius calculation:
- Given a failure at level X, enumerate all components affected by propagation rules.
- Identify which of those components have recovery assets (backups, alternatives).
- Identify which have no recovery path (true loss).
- Identify which have cross-cell dependencies that require federation coordination.

Blast radius is calculated at assessment time and stored in the Digital Twin.
It is re-evaluated whenever Dependency State or Federation State changes.

---

## 12. Recovery Readiness Architecture

### 12.1 Readiness Scoring Hierarchy

Recovery readiness is evaluated independently at each level.

```
Service Readiness         — Is this service recoverable?
VM Readiness              — Is this VM recoverable? (all its services?)
Node Readiness            — Is this node reconstructable?
Cluster Readiness         — Is this cluster reconstructable?
Cell Readiness            — Is this cell fully reconstructable?
Federation Readiness      — Can the federation survive loss of any single cell?
```

Each level produces an independent score: GREEN / YELLOW / ORANGE / RED / BLOCKED / UNKNOWN

A higher-level score is never better than its worst component score. Federation Readiness
cannot be GREEN if any cell is RED.

### 12.2 Expanded Scoring Inputs

The v4.0 scoring inputs are retained and the following are added:

**Hardware layer (new):**
| Input | Score if missing/failed |
|---|---|
| BIOS/firmware version documented | YELLOW |
| Hardware bootstrap requirements declared | YELLOW |
| Physical disk health SMART data within threshold | ORANGE |
| UPS runtime adequate for graceful shutdown | YELLOW |
| Hardware vendor warranty/support active | YELLOW (informational) |

**Cluster layer (new):**
| Input | Score if missing/failed |
|---|---|
| Cluster identity and UUID recorded | ORANGE |
| Corosync topology documented | ORANGE |
| Quorum configuration documented | ORANGE |
| Historical cluster membership recorded | YELLOW |

**Storage layer (new):**
| Input | Score if missing/failed |
|---|---|
| ZFS pool topology fully documented | ORANGE |
| Ceph FSID recorded | RED (cannot rejoin cluster without it) |
| Ceph OSD layout documented | ORANGE |
| Storage replication lag within threshold | YELLOW |
| Backup encryption keys recoverable | RED if not |

**External dependencies (new):**
| Input | Score if missing/failed |
|---|---|
| Certificate expiry > 30 days | ORANGE if ≤30 days |
| DNS provider credentials in secret registry | ORANGE |
| External identity provider accessible | ORANGE if unreachable |
| Domain registrar expiry > 90 days | YELLOW if ≤90 days |

**Data protection (new):**
| Input | Score if missing/failed |
|---|---|
| RTO/RPO declared per VM | YELLOW |
| Backup age within declared RPO | RED if exceeded |
| Offsite copy exists | YELLOW if not |
| Backup encryption key recoverable | RED if not |
| PBS itself has a recovery plan | ORANGE if not |

**Capability layer (new):**
| Input | Score if missing/failed |
|---|---|
| Recovery coordinator cell declared | ORANGE |
| Execution cell (can run reconstruction) reachable | ORANGE |
| Temporary workload hosting available | YELLOW |
| Assessment cell (can assess recovering cell) reachable | YELLOW |

**Federation layer (new):**
| Input | Score if missing/failed |
|---|---|
| Recovery relationships declared and verified | ORANGE |
| Trust relationships current and verified | YELLOW |
| Cross-cell backup relationships tested | YELLOW |
| Federated reconstruction tested | YELLOW |

### 12.3 SPOF and Circular Dependency Detection

The recovery planner identifies:

**Single Points of Failure:** Components with no recovery alternative. A RED SPOF is
a hard blocker. An ORANGE SPOF is a risk requiring documentation.

**Circular Recovery Dependencies:** Cell A needs Cell B's help to recover, and Cell B
needs Cell A's help to recover. These must be detected and resolved in the recovery
plan (one cell must be designated the recovery initiator).

**Missing Capability Coverage:** No available cell has the capability required to
assist recovery. These are federation-level gaps requiring remediation.

---

## 13. Federated Reconstruction Architecture

### 13.1 Reconstruction Scenario

Cell A fails catastrophically. Replacement hardware is obtained and a fresh Proxmox
installation is completed. Available assets are assessment history, generated
documentation, and repositories. Cell B remains operational.

### 13.2 Reconstruction Coordination Model

```
Phase 0 — Activation
  Cell B detects Cell A failure (monitoring relationship, or operator notification)
  Cell B queries Federation State for Cell A's recovery relationships
  Cell B acts as Recovery Coordinator (if it has delegation_trust from Cell A)
  Cell B assembles Recovery Package for Cell A:
    → Historical State (from wherever it is stored, per Federation State)
    → Generated Documentation (last known good set)
    → Repository references (from Cell A's Federation State)
    → Secret references (from Cell A's Secret Reference State)
    → Backup locations (from Cell A's Data Protection State)
    → Capability requirements (from Cell A's Capability State)

Phase 1 — Environment Assessment
  Recovery Coordinator identifies which capabilities are needed for Cell A's reconstruction
  Recovery Coordinator queries Capability Index for available cells
  Recovery Coordinator establishes required trust relationships with available cells
  Recovery Coordinator assigns roles:
    → Execution Cell: runs reconstruction playbooks
    → Backup Source Cell: provides backup archives
    → Temporary Hosting Cell: hosts Cell A's critical workloads during reconstruction
    → Documentation Cell: serves Cell A's documentation during reconstruction

Phase 2 — Foundation Reconstruction (hardware layer)
  Reconstruction Playbook Wave -1 (pre-OS):
    → Verify hardware meets declared Hardware State requirements
    → Apply BIOS/UEFI settings from Hardware State
    → Verify storage controller configuration
    → Confirm network connectivity to Recovery Coordinator
  Install Proxmox from declared Platform State:
    → Known version, known repository configuration
    → Platform State applied from declared configuration

Phase 3 — Platform Reconstruction (platform layer)
  Reconstruction Playbook Wave 0 (platform):
    → Apply Proxmox platform configuration from Platform State
    → Install certificates from Secret Reference State
    → Configure API tokens and users (from references)
    → Configure repositories (from Platform State)
    → Apply network topology from Network State
    → Import ZFS pools from Storage State topology
    → Verify Proxmox API accessible to Recovery Coordinator

Phase 4 — Bootstrap Reconstruction (provisioning layer)
  Reconstruction Playbook Wave 0.5 (templates):
    → Download base ISOs from Bootstrap State image registry
    → Verify checksums
    → Create VM templates from Bootstrap State build manifests
    → Upload Cloud-Init snippets from Bootstrap State repository
    → Verify snippets match recorded hashes

Phase 5 — VM Reconstruction (per dependency wave)
  For each wave in the Operational Dependency graph:
    → Create VM from Declared State (tofu apply or qm create from provenance)
    → Attach Cloud-Init from Bootstrap State
    → Start VM, wait for first-boot completion
    → Run Ansible from Configured State (pinned commit)
    → Restore data from backup (from Data Protection State)
    → Validate Service Contract (from Service State)
    → Register with Observability (from Observability State)
    → Update DNS (from External Dependency State or local DNS State)

Phase 6 — Validation
  Run Tier 2 Assessment of reconstructed Cell A
  Compare to last known good Historical State snapshot
  Evaluate all Service Contracts
  Update Digital Twin with post-recovery observed state
  Generate Recovery Completion Report
  Announce Cell A as operational to Federation

Phase 7 — Recovery Cleanup
  Release temporary workload hosting from assisting cells
  Re-establish normal trust relationships
  Update Recovery Relationships in Federation State
  Schedule post-recovery reconstruction drill review
```

### 13.3 Reconstruction Playbook Generation

Reconstruction Playbooks are generated from the Digital Twin. The generation is
deterministic: the same twin state always produces the same playbooks.

Playbooks are organized by phase and wave:
```
reconstruction/<cell_id>/
  phase-0-activation/
    00-assemble-recovery-package.sh
    01-identify-capabilities.sh
    02-establish-trust.sh
  phase-1-hardware/
    10-verify-hardware.sh
    11-apply-bios-settings.sh
  phase-2-platform/
    20-install-proxmox.sh         # parameterized from Platform State
    21-configure-repositories.sh
    22-install-certificates.sh
    23-configure-network.sh       # from Network State
    24-import-storage.sh          # from Storage State
  phase-3-bootstrap/
    30-download-isos.sh           # from Bootstrap State image registry
    31-build-templates.sh
    32-upload-snippets.sh
  phase-4-N-vms/
    40-<vmname>-create.sh         # from Declared State + Bootstrap State
    40-<vmname>-configure.sh      # from Configured State
    40-<vmname>-restore.sh        # from Data Protection State
    40-<vmname>-validate.sh       # from Service State contracts
  run-all.sh                      # orchestrated full reconstruction
  RECONSTRUCTION-RUNBOOK.md       # human-readable version of the above
```

---

## 14. Metadata Architecture

### 14.1 Universal Metadata Fields

Every state document in the Digital Twin carries a common metadata envelope:

```json
{
  "schema_version": "...",
  "state_category": "hardware-state",
  "cell_id": "proxmox-cell-a",
  "cluster_id": "proxmox-cluster-01",
  "federation_id": "homelab",
  "collected_at": "2026-05-31T00:00:00Z",
  "collected_by": "tier2-assessment",
  "collecting_cell_id": "assessment-cell",
  "confidence": "OBSERVED",
  "staleness_threshold_days": 30,
  "last_verified_at": "2026-05-31T00:00:00Z"
}
```

`cell_id` is mandatory on every state document. This fixes the v4.0 structural problem
of implicit single-cell scope. Every schema is updated to require it.

### 14.2 Field Confidence Levels

| Confidence | Meaning | Example |
|---|---|---|
| DECLARED | Comes from a repository or declared configuration | VM cores from OpenTofu |
| OBSERVED | Measured directly during assessment | Actual RAM from /proc/meminfo |
| DERIVED | Calculated from other fields | Available RAM = Total - Used |
| INFERRED | Best-guess from incomplete data | Template used inferred from name |
| HUMAN | Entered by operator | KeePass path for a secret |
| STALE | Was OBSERVED/DECLARED but past staleness threshold | Assessment > 30 days old |
| UNRESOLVED | Cannot be determined | No assessment data at all |

### 14.3 Cell Identity Schema

```json
{
  "cell_id": "proxmox-cell-a",
  "cell_name": "Proxmox Primary Cell",
  "cell_type": "proxmox-single-node",
  "federation_id": "homelab",
  "joined_federation_at": "2026-01-01T00:00:00Z",
  "primary_operator": "dave",
  "purpose": "primary-compute",
  "criticality": "HIGH",
  "recovery_priority": 1,
  "repositories": {
    "infrastructure": "https://forgejo.internal/infra/proxmox-infrastructure",
    "bootstrap": "https://forgejo.internal/infra/proxmox-bootstrap",
    "configuration": "https://forgejo.internal/infra/proxmox-ansible",
    "assessment_engine": "https://forgejo.internal/infra/proxmox-assessment-engine",
    "reconstruction": "https://forgejo.internal/infra/proxmox-reconstruction"
  },
  "assessment_history_cell_id": "assessment-cell",
  "documentation_cell_id": "documentation-cell",
  "primary_backup_cell_id": "pbs-cell",
  "recovery_coordinator_cell_id": "assessment-cell"
}
```

---

## 15. Repository Architecture

```
# Per-cell repositories (in cell's Forgejo instance)

<cell-id>-assessment-engine/       Assessment + Digital Twin Platform
  assessment/
    tier1/                          Bootstrap assessment (stdlib, no deps)
    tier2/                          Full assessment (full engine)
    tier3/                          Federation assessment (cross-cell)
  twin/                             Digital Twin state store
    federation/
    cells/<cell_id>/
  doc-gen/                          Documentation generation engine
    engine.py                       Multi-scope CLI
    renderers/                      All output format renderers
  history/                          Local history store
  reports/                          Generated documentation outputs
  data-model/                       All 17+ JSON schemas

<cell-id>-infrastructure/           Infrastructure Definition (OpenTofu)
  tofu/
    host/                           Host-level resources
    vms/                            VM resources
    network/                        Network topology as code
    storage/                        Storage definitions

<cell-id>-bootstrap/                Bootstrap State
  snippets/
    user-data/
    network-config/
    vendor-data/
  images/registry.yaml
  templates/
  provenance/
  secret-registry.yaml
  dns-registry.yaml
  service-contracts/
  hardware-requirements.yaml        NEW — BIOS/firmware requirements

<cell-id>-configuration/            Configured State (Ansible)
  inventory/
  playbooks/
  roles/
  collections/

<cell-id>-reconstruction/           Reconstruction Playbooks (generated)
  <cell_id>/
    phase-0/ through phase-N/
    run-all.sh
    RECONSTRUCTION-RUNBOOK.md

# Federation-level repository (shared, accessible to all cells)

federation-registry/                Federation State
  cells/
    <cell_id>/
      identity.json
      capabilities.json
      relationships.json
  federation-state.json
  capability-index.json
  recovery-graph.json
```

### 15.1 Assessment Tier Extension

**Tier 1 — Bootstrap Assessment** (unchanged)
Collects Hardware + Platform + Observed State on a fresh host.
Constraints: single shell script, stdlib only, no network required.

**Tier 2 — Full Assessment** (expanded)
Collects all 17 state categories for a single cell.
Reads: Proxmox API, all repositories, PBS API, monitoring API, external provider APIs.
Adds: Hardware State, Cluster State, Storage State, External Deps, Data Protection, Observability.

**Tier 3 — Federation Assessment** (new)
Collects Federation State and cross-cell relationships.
Verifies trust relationships are current and mutual.
Verifies capability declarations match observed reality.
Verifies recovery relationships are intact (backup archives accessible, history readable).
Produces Federation Readiness Report.
Runs from: a designated assessment cell with federation-scope trust.

---

## 16. Architecture Decision Records — v5.0

### AD-013: Infrastructure Cell is the primary architectural object
**Date:** 2026-05-31
**Decision:** Infrastructure Cell replaces the implicit single-environment assumption
throughout the architecture. Every schema, every assessment, every documentation output
is cell-scoped. `cell_id` is a mandatory field in all state documents.
**Rationale:** Single-environment assumptions cannot be patched into federation capability.
The cell concept must be foundational, not retrofitted.

### AD-014: Federation is a first-class object, not an extension
**Date:** 2026-05-31
**Decision:** Federation State, the capability index, the recovery relationship graph,
and the inter-cell trust model are managed as first-class architectural objects with
their own schemas, their own assessment tier, and their own documentation class.
**Rationale:** Federation relationships are too complex and too critical to recovery
coordination to be modeled as secondary attributes of cell state.

### AD-015: Recovery State removed from the state model
**Date:** 2026-05-31
**Decision:** Recovery State is reclassified from a state category to a documentation
output class. It does not describe infrastructure reality; it describes what to do
when infrastructure fails. The state model is for infrastructure reality only.
**Rationale:** Category error in v4.0. Mixing generated artifacts with observed state
creates confusion about authoritativeness and update mechanisms.

### AD-016: Eighteen state categories replace seven
**Date:** 2026-05-31
**Decision:** The state model expands from seven to seventeen categories (plus the
reclassified Recovery State output class). New categories: Hardware, Platform, Cluster,
Storage, Network (standalone), External Dependency, Data Protection, Observability,
Secret Reference (standalone), Capability, Federation State.
**Rationale:** The seven-category model was insufficient to support full hardware
reconstruction, cluster-aware recovery, external dependency tracking, federated
capability matching, and cross-cell recovery coordination.

### AD-017: Five dependency graph types
**Date:** 2026-05-31
**Decision:** The architecture maintains five distinct dependency graphs: Operational,
Recovery, Trust, Execution, and Failure Domain. Each has different semantics and
different uses. They are stored and traversed independently.
**Rationale:** Conflating operational dependencies with recovery dependencies produces
incorrect recovery sequencing. Cross-cell recovery requires explicit modeling of
which cell provides which recovery capability for which other cell.

### AD-018: Capability State enables dynamic recovery planning
**Date:** 2026-05-31
**Decision:** Each cell declares its capabilities (compute, storage, execution, network,
assessment). Capabilities are verified at assessment time. The capability index is
maintained at federation scope and used by reconstruction planners to identify which
available cell can assist recovery.
**Rationale:** Federated reconstruction requires knowing what help is available before
committing to a recovery plan. Undeclared or unverified capabilities are dangerous
assumptions during a disaster recovery event.

### AD-019: Tier 3 Federation Assessment
**Date:** 2026-05-31
**Decision:** A new assessment tier (Tier 3) covers federation-scope state: trust
relationship verification, capability verification, cross-cell recovery relationship
testing, and federation readiness scoring. It runs from a designated assessment cell
with federation-scope trust.
**Rationale:** Single-cell assessment cannot verify cross-cell relationships. Federation
readiness requires exercising the trust and recovery relationships, not merely declaring them.

### AD-020: Digital Twin is the authoritative source for all generated outputs
**Date:** 2026-05-31
**Decision:** All documentation, all readiness reports, and all reconstruction playbooks
are generated from the Digital Twin. No output is manually authored. Operators provide
input only for fields that are genuinely undiscoverable.
**Rationale:** Manually authored documentation diverges from reality. Generated
documentation is always consistent with the current twin state. Reproducibility is
guaranteed by the twin's deterministic generation model.

### AD-021: Staleness is a first-class field confidence level
**Date:** 2026-05-31
**Decision:** STALE is added as a field confidence level alongside AUTO, DERIVED, HUMAN,
and UNRESOLVED. Each state category has a declared staleness threshold. Fields past
their threshold are marked STALE in the twin and in all generated outputs.
**Rationale:** An UNRESOLVED field was never populated. A STALE field was populated but
is no longer current. These are different problems requiring different remediation.
STALE fields have known historical values that may or may not still be accurate.

---

## 17. Implementation Roadmap — v5.0

Phases 6–12 from the v4.0 roadmap address single-cell work that is still required.
They are retained, annotated as "Cell-Scoped Foundation," and must be completed before
Federation-Scoped work begins.

All single-cell phases are updated to require `cell_id` in all schemas from the start.
This is the minimum structural change required to make single-cell work federation-ready.

### Cell-Scoped Foundation (Phases 6–12, updated)

**Phase 6 — Bootstrap State** *(add cell_id to all schemas)*
Hardware requirements schema added (6.1). Otherwise unchanged from v4.0 roadmap.

**Phase 7 — Service State** *(add cell_id, add external dependency tracking)*
External Dependency State schema added (7.1 extension).

**Phase 8 — Network Topology as Code** *(unchanged)*

**Phase 9 — Reconstruction Playbooks** *(update for cell-scoped generation)*
Playbooks organized under `reconstruction/<cell_id>/` from the start.

**Phase 10 — Operational Documentation** *(unchanged)*

**Phase 11 — Capacity Model** *(unchanged)*

**Phase 12 — Full Reconstruction Drill** *(single-cell scope)*

### New Phases — Expanded State Categories

**Phase 13 — Hardware and Platform State**
- 13.1: Hardware State schema (`hardware-state-schema.json`)
- 13.2: Hardware State Tier 1 collector (BIOS, firmware, storage controller, disks)
- 13.3: Platform State schema (`platform-state-schema.json`)
- 13.4: Platform State Tier 2 collector (Proxmox config, certs, packages)
- 13.5: Hardware requirements declaration in Bootstrap State
- 13.6: Pre-reconstruction hardware verification in Reconstruction Playbooks
- 13.7: Hardware and Platform readiness scoring additions

**Phase 14 — Cluster and Storage State**
- 14.1: Cluster State schema (`cluster-state-schema.json`)
- 14.2: Cluster State collector (Proxmox cluster API, Corosync, HA)
- 14.3: Storage State schema (`storage-state-schema.json`)
- 14.4: Storage State collector (ZFS topology, Ceph layout, datastores, replication)
- 14.5: Ceph FSID and OSD layout in readiness scorer (RED if missing)
- 14.6: Cluster and Storage reconstruction waves in Playbook generator

**Phase 15 — External Dependency and Data Protection State**
- 15.1: External Dependency State schema
- 15.2: External Dependency collector (cert expiry, DNS provider, SMTP)
- 15.3: Data Protection State schema (`data-protection-state-schema.json`)
- 15.4: Data Protection collector (PBS API, backup job inventory, verification status)
- 15.5: RTO/RPO declaration and compliance scoring
- 15.6: External dependency and data protection readiness scoring additions

**Phase 16 — Observability and Secret Reference State**
- 16.1: Observability State schema
- 16.2: Observability State collector (monitoring stack, alert rules, dashboards)
- 16.3: Secret Reference State elevated to standalone schema
- 16.4: Secret registry expanded: owning cell, federation scope, rotation metadata
- 16.5: Cross-cell secret reference resolution in doc-gen

### New Phases — Digital Twin Platform

**Phase 17 — Digital Twin Foundation**
- 17.1: Cell Identity schema and registry
- 17.2: Twin storage layout (`twin/` directory structure)
- 17.3: Twin state writer (all collectors write to twin, not just history/)
- 17.4: Staleness manifest (per-field confidence and last-updated tracking)
- 17.5: Twin consistency checker (identifies stale, missing, conflicting state)
- 17.6: `cell_id` added to all existing schemas (migration)

**Phase 18 — Capability State**
- 18.1: Capability State schema (`capability-state-schema.json`)
- 18.2: Capability declaration format (operator-declared)
- 18.3: Capability verification in Tier 2 assessment (verify declared capabilities)
- 18.4: Capability index builder (federation-scope aggregation)
- 18.5: Capability-based readiness scoring additions

### New Phases — Federation Architecture

**Phase 19 — Federation State and Trust Model**
- 19.1: Federation State schema (`federation-state-schema.json`)
- 19.2: Cell identity and federation registry
- 19.3: Trust relationship schema and declaration format
- 19.4: Trust relationship verification procedure (CLI + automated check)
- 19.5: Recovery relationship schema and declaration format
- 19.6: Recovery relationship verification (can backup cell be reached? can history be read?)
- 19.7: Federation State collector (Tier 3 assessment — cross-cell)

**Phase 20 — Federation Documentation Generation**
- 20.1: Federation Workbook renderer (all cells, all relationships)
- 20.2: Federation Runbook renderer (federation-level recovery coordination)
- 20.3: Cell Workbook and Runbook (full 17-state view per cell)
- 20.4: Cluster Workbook and Runbook
- 20.5: Dependency Workbook (all five graph types, multi-cell scope)
- 20.6: Command Reference Sheets (pre-populated for all known values)

### New Phases — Failure Domains and Readiness

**Phase 21 — Failure Domain Modeling**
- 21.1: Failure domain taxonomy schema
- 21.2: Failure propagation rules engine
- 21.3: Blast radius calculator (given failure at level X, what is affected?)
- 21.4: SPOF detection (single points with no recovery alternative)
- 21.5: Circular recovery dependency detection (Cell A needs Cell B needs Cell A)
- 21.6: Failure domain integration in readiness reports

**Phase 22 — Multi-Level Readiness Assessment**
- 22.1: Hardware-level readiness scoring
- 22.2: Cluster-level readiness scoring
- 22.3: Cell-level readiness scoring (aggregation across all state categories)
- 22.4: Federation-level readiness scoring (aggregation across all cells)
- 22.5: Federation Readiness Report (the top-level recovery health report)
- 22.6: Tier 3 assessment integration with multi-level readiness

### New Phases — Federated Reconstruction

**Phase 23 — Federated Reconstruction Planning**
- 23.1: Recovery coordinator model (which cell coordinates Cell A's reconstruction)
- 23.2: Recovery package assembly (gathering all assets needed for Cell A reconstruction)
- 23.3: Capability matching (which available cells can fulfill Cell A's recovery needs)
- 23.4: Multi-phase reconstruction playbook generator (all 7 phases)
- 23.5: Cross-cell trust establishment automation (pre-recovery trust setup)
- 23.6: Temporary workload migration planning (which workloads move where during recovery)

**Phase 24 — Continuous Assessment and Twin Maintenance**
- 24.1: Scheduled assessment framework (cron-driven, cell-scoped)
- 24.2: Repository ingestion hooks (git webhook → twin update on push)
- 24.3: Deployment event hooks (tofu apply → provenance record → twin update)
- 24.4: Staleness alerting (notify when state categories exceed staleness threshold)
- 24.5: Twin diff reporting (what changed in the twin since last report)

**Phase 25 — Reconstruction Validation**
- 25.1: Reconstruction drill framework (scheduled full-destroy + reconstruct test)
- 25.2: Reconstruction time measurement and RTO validation
- 25.3: Automated post-reconstruction assessment and comparison
- 25.4: Gap identification and remediation tracking from drills
- 25.5: Federation reconstruction drill (multi-cell coordinated scenario)

---

## 18. Architectural Risks

**Risk 1 — Complexity Explosion**
Severity: HIGH
The federation model introduces substantial complexity. If the single-cell foundation
is not solid before federation work begins, federation will amplify every gap.
Mitigation: Enforce phase ordering. No federation work until Phases 6–12 and 13–18
are complete and validated. The `cell_id` migration in Phase 17.6 is the gate.

**Risk 2 — Capability Declaration Drift**
Severity: MEDIUM
Cells declare capabilities that are then used for recovery planning. If declared
capabilities are not verified, recovery plans may depend on capabilities that no
longer exist. An unused capability (e.g., `can_execute_reconstruction_playbooks`)
may be removed without updating the declaration.
Mitigation: Tier 3 assessment must verify capability declarations. Unverified
capabilities are marked STALE and excluded from recovery planning after threshold.

**Risk 3 — Trust Relationship Staleness**
Severity: HIGH
Trust relationships between cells are established once and may not be re-verified.
An SSH key rotated in one cell may invalidate trust with another cell without
triggering an alert.
Mitigation: Trust relationship verification is a Tier 3 assessment step.
Trust relationships have an explicit expiry and must be re-verified periodically.
Expired trust is surfaced as ORANGE in federation readiness scoring.

**Risk 4 — Circular Recovery Dependencies**
Severity: MEDIUM
Cell A uses Cell B's backup storage. Cell B uses Cell A's DNS. If both fail
simultaneously, neither can recover without the other.
Mitigation: Circular recovery dependency detection is built into Phase 21.
Circular dependencies must be resolved in the recovery plan by designating an
initiator and establishing an external dependency (e.g., local fallback DNS).

**Risk 5 — External Dependency Unmodeled**
Severity: MEDIUM
External dependencies (certificate providers, DNS registrars, SMTP relays) are
outside the federation's control. They may be unavailable during a recovery event.
Mitigation: External Dependency State explicitly models these and their recovery
paths. Recovery documentation includes explicit external dependency verification
steps before proceeding with reconstruction.

**Risk 6 — Historical State Unavailable During Recovery**
Severity: HIGH
If Cell A's historical assessment archives are stored on Cell A and Cell A fails
catastrophically, the recovery coordinator has no verified baseline to compare
against after reconstruction.
Mitigation: Historical state hosting is declared in Federation State. The default
should be to store historical state on a different cell than the one being described.
Phase 17 enforces this: the `assessment_history_cell_id` in Cell Identity must
differ from the cell's own `cell_id`.

**Risk 7 — Reconstruction Playbook Staleness**
Severity: MEDIUM
Reconstruction playbooks are generated from the Digital Twin. If the twin is stale,
the generated playbooks are wrong. An operator who runs a stale playbook during
recovery may make the situation worse.
Mitigation: Playbooks carry a generation timestamp and twin state hash. Running a
playbook that is older than the staleness threshold requires explicit operator
confirmation. The twin's staleness manifest provides this data.

---

## 19. Architectural Gaps (Acknowledged, Not Yet Scoped)

The following are real gaps that are acknowledged but intentionally deferred beyond
Phase 25. They are listed to ensure they are not forgotten.

**Gap 1 — Non-Proxmox Infrastructure**
The architecture is designed around Proxmox with hooks for future extension.
Kubernetes, bare-metal non-Proxmox, and cloud-hosted infrastructure are not modeled.
The cell abstraction is compatible with these environments but the state categories
and assessment tiers are Proxmox-specific.

**Gap 2 — Real-Time State**
The Digital Twin is periodically updated. It is not a real-time mirror. For operational
monitoring use cases (alerting, capacity management), the twin's staleness model is
insufficient. This would require event streaming integration.

**Gap 3 — Active Reconstruction Automation**
The architecture generates reconstruction playbooks but does not automatically execute
them. Full autonomous reconstruction would require an execution engine, state machine,
and rollback capability. This is a significant additional system.

**Gap 4 — Multi-Site / Multi-Federation**
The architecture models one federation. Multiple federations with trust relationships
between them is not modeled. This would require a meta-federation or federation-of-
federations model.

**Gap 5 — Compliance and Audit**
The architecture tracks infrastructure state and generates documentation. It does not
model compliance requirements, audit trails for changes, or regulatory reporting.

**Gap 6 — Cost and Resource Optimization**
The architecture tracks capacity but does not model cost or optimize resource allocation
across cells in the federation.

---

## 20. Recommended Future Enhancements

Following completion of Phase 25:

1. **Active Reconstruction Executor** — An execution engine that can drive the
   generated reconstruction playbooks with state machine tracking, progress reporting,
   and rollback capability.

2. **Event-Driven Twin Updates** — Replace periodic assessment with event-driven
   updates for high-change state categories (service health, backup status).

3. **Reconstruction Simulation** — A dry-run mode that traverses the reconstruction
   playbook against the twin state and identifies failures without touching real
   infrastructure.

4. **Non-Proxmox Cell Support** — Assessment tiers and state schemas for Kubernetes,
   bare-metal Linux, and cloud-hosted infrastructure.

5. **Federation Web Interface** — A read-only web dashboard derived from the Digital
   Twin showing real-time federation health, readiness scores, and dependency maps.

6. **Automated Reconstruction Drills** — Scheduled, fully automated reconstruction
   exercises using spare hardware or cloud burst capacity, with automated comparison
   and gap reporting.

---

## 21. Summary

The v4.0 architecture was a significant improvement over v3.0. Its core decisions —
six-layer lifecycle, service contracts, secret registry, reproducible documentation —
are sound and are retained.

v4.0 is insufficient for the stated long-term objective because it cannot model:
- Cells that assist each other during recovery
- Hardware-level reconstruction requirements
- Cluster topology and reformation
- External dependency tracking and recovery impact
- Capability-based dynamic recovery planning
- Federation-level recovery coordination
- Trust relationships and their verification
- Failure domain propagation across cell boundaries

The v5.0 architecture addresses all of these by:
1. Introducing Infrastructure Cell and Federation as first-class objects
2. Expanding the state model from 7 to 17 categories
3. Defining five dependency graph types with distinct semantics
4. Introducing Capability State for dynamic recovery planning
5. Defining a seven-phase federated reconstruction model
6. Expanding documentation generation to all levels of the hierarchy
7. Introducing Tier 3 Federation Assessment
8. Establishing the Digital Twin as the authoritative source for all outputs

The single most important near-term action is **adding `cell_id` to all schemas**
(Phase 17.6 migration). This single change makes all existing single-cell work
federation-ready and prevents a costly structural refactor later.

The question posed in the mandate — "If a replacement administrator inherits this
environment years from now, can they reconstruct it from available information?" —
is answerable in the affirmative only when:

- Hardware requirements are documented
- Every deployment decision has a provenance record
- Every secret has a retrieval path
- Every dependency is declared
- Every recovery relationship is verified
- Every capability is tested
- Every reconstruction step is generated and validated
- And a surviving cell is ready to coordinate the reconstruction of a failed one.

The Federated Infrastructure Digital Twin Platform is the architecture that makes
this possible.
