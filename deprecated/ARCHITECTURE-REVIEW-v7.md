# Architecture Review — v7.1
## Self-Documenting, Self-Assessing, Self-Recovering Infrastructure Platform

Date: 2026-06-02 UTC (updated from v7.0 — adds Hatchery/Stargate/Phase 12.E spawn bootstrap)
Status: Current
Supersedes: v7.0 (2026-05-31), v6.0, v5.0, v4.0 (all retired to deprecated/)

> **Note (2026-06-03):** References to ODS/ODT workbooks and `ods-update.sh` throughout
> this document describe an earlier design. The active codebase generates HTML documents
> only; ODS/ODT renderers are preserved in `doc-gen/renderers/deprecated/` for reference.
> ARCHITECTURE.md AD-055 captures this change.

---

## 1. Foundational Philosophy

This architecture review begins with a philosophical reset before any technical
decision is made.

**The platform's primary product is not virtual machines.**

The platform exists to produce:
- Reproducibility — any component can be rebuilt from repository state
- Recoverability — any failure mode has a documented, tested recovery path
- Documentation — everything that exists has a documented reason for existing
- Operational understanding — the platform continuously knows its own state
- Architecture validation — reality is continuously compared to intent

Applications (Nextcloud, Immich, Forgejo, monitoring) are workloads that run on
the platform and benefit from its documentation and recovery capabilities. They are
not the reason the platform exists.

**This distinction has concrete architectural consequences:**

- The documentation engine and assessment engine are deployed before any user
  application workload
- A user workload that cannot be documented or assessed is not fit for deployment
  on this platform
- Recovery capability is a deployment prerequisite, not a post-deployment concern
- The platform continuously earns the right to host workloads by maintaining its
  own understanding of itself

---

## 2. Review Scope

v6.0 established the four intelligence phases, the k3s strategy, the Flux CD
GitOps recommendation, the bootstrap repository structure, the ODS workbook
standard, and the failure package design. These decisions are retained where sound.

v7.0 adds:

1. The **Infrastructure Assessment Engine** as an explicit first-class subsystem
2. Formal **scoring systems** (five scores with defined computation and thresholds)
3. A **rebalancing strategy** (Phase 1: detect/document/recommend; Phase 2: evaluate
   automation with explicit safeguards)
4. A more complete **source of truth governance model**
5. A **12-phase roadmap** with full per-phase specification
6. A deeper **challenge and criticism** section identifying hidden assumptions

---

## 3. What v6.0 Got Right (Retained)

**Four intelligence phases with distinct runtimes.** Phase A (pre-k3s, stdlib
Python) and Phases B/C/D (k3s workloads) are correctly separated. This review
formalises Phase B as the Documentation Engine and introduces Phase B.5 as the
Assessment Engine.

**k3s as the application platform.** The rationale stands: scheduling, failover,
HA, standard workload definition format, rich API surface. See Section 6 for
the updated GitOps comparison.

**Flux CD as the GitOps engine.** The recovery bootstrapping advantage is decisive.
`flux bootstrap` on a fresh cluster, pointed at Forgejo, reconciles the entire
platform automatically. This advantage grows as the platform matures.

**ODS as the machine-updatable workbook standard.** ODS via stdlib zipfile + XML
is the correct choice: no dependencies, human-readable in LibreOffice, machine-
writable from shell scripts via Python.

**Recovery packages as self-contained, offline-capable artifacts.** The recovery
package must not require Forgejo, the internet, or the k3s cluster to execute
Phases 1–3 of recovery.

**Failure packages structured for LLM analysis.** The self-improvement loop
(failure → package → LLM analysis → bootstrap repository update) is the
mechanism by which the platform learns from its own failures.

---

## 4. What v6.0 Left Incomplete

**The Assessment Engine was implicit.** v6.0 described the documentation engine
consuming APIs from Proxmox and Kubernetes, but did not design a distinct
assessment subsystem that evaluates the quality and completeness of what it finds.
Documenting reality and *evaluating* whether reality matches intent are different
concerns requiring different architecture.

**Scoring systems were absent.** Without formal scores and thresholds, the platform
produces documentation but provides no signal about whether anything needs
attention. Scores are what convert documentation into operational intelligence.

**The rebalancing strategy was unaddressed.** When the assessment engine detects
suboptimal placement, missing backups, or capacity risk, what happens? v6.0 was
silent. v7.0 defines a careful two-phase approach.

**Source of truth governance was underdeveloped.** The hierarchy was stated but
not governed. Who can update metadata? What happens when two sources disagree?
What triggers a reassessment?

---

## 5. Core Architecture

### 5.1 Platform Stack

| Layer | Technology | Role |
|---|---|---|
| Hypervisor | Proxmox VE | VM hosting, storage, networking, snapshots |
| IaC | OpenTofu | Proxmox infrastructure declaration |
| Configuration | Ansible | VM and service configuration |
| Provisioning | Cloud-Init | VM first-boot identity and networking |
| Git hosting | Forgejo (VM, pre-k3s) | All repositories — the source of truth |
| GitOps | Flux CD | Continuous reconciliation from Git to k3s |
| Orchestration | k3s | All application workloads |
| Documentation | Documentation Engine (k3s) | Phase B intelligence |
| Assessment | Assessment Engine (k3s) | Platform self-evaluation |
| Recovery | Recovery Generator (k3s) | Phase C/D intelligence |
| Secrets | KeePassXC-compatible | Secret references (paths only, never values) |
| Workbooks | ODS (machine-updated) | Execution and assessment records |

### 5.2 Architecture Hierarchy

```
Federation
└── Infrastructure Cell  [independently recoverable unit]
    └── Proxmox Cluster
        ├── Proxmox Host Node(s)
        │   ├── Platform VMs  [pre-k3s, always-on]
        │   │   ├── forgejo-vm         Forgejo Git hosting (must exist before k3s)
        │   │   └── operations-vm      Phase A toolchain + emergency access
        │   └── k3s Node VMs
        │       ├── k3s-server-01..N   Control plane
        │       └── k3s-worker-01..N   Workload nodes
        │
        └── k3s Cluster
            ├── platform/              Core platform services
            │   ├── flux-system        GitOps engine
            │   ├── cert-manager       TLS management
            │   └── ingress-nginx      HTTP routing
            │
            ├── intelligence/          Platform intelligence workloads
            │   ├── documentation/     Documentation Engine (Phase B)
            │   ├── assessment/        Assessment Engine (Phase B.5)
            │   └── recovery/          Recovery Generator (Phase C/D)
            │
            ├── monitoring/            Observability
            │   ├── prometheus
            │   ├── grafana
            │   └── loki
            │
            └── applications/          User workloads (AFTER intelligence layer)
                ├── nextcloud
                ├── immich
                └── ...
```

### 5.3 Deployment Ordering (enforced by Flux dependency graph)

```
1. Platform services (cert-manager, ingress, flux-system)
2. Documentation Engine               ← GATE 1: platform is documented
3. Assessment Engine                  ← GATE 2: platform is assessed
4. Recovery Generator                 ← GATE 3: platform is recoverable
5. Monitoring stack                   ← GATE 4: platform is observable
[No user workload deploys before all four gates pass]
6. User applications
```

---

## 6. GitOps: Flux CD vs ArgoCD

### Comparison

| Concern | Flux CD | ArgoCD |
|---|---|---|
| Recovery bootstrapping | `flux bootstrap` on fresh cluster → full reconciliation | Requires ArgoCD installed before it can reconcile anything |
| Resource footprint | ~200MB RAM | ~500MB+ RAM |
| UI dependency | CLI-first; Weave GitOps UI optional | UI is a primary interface |
| Multi-tenancy | Native via Kustomize + RBAC | More complex tenant isolation |
| Forgejo compatibility | Native GitRepository source type | Native Git source type |
| Secret management | SOPS integration native | Sealed Secrets or external |
| FOSS status | CNCF graduated | CNCF incubating |
| Helm support | Flux HelmController | ArgoCD ApplicationSet |
| Drift detection | Flux detects and corrects drift automatically | ArgoCD shows drift; auto-sync optional |

### Decision: Flux CD

The recovery bootstrapping advantage is decisive for this platform's use case.
On a fresh cluster (disaster recovery scenario), `flux bootstrap git --url=...`
pointed at the Forgejo bootstrap repository reconciles the entire intelligence
layer automatically. This means the assessment engine, documentation engine, and
recovery generator are all operational within minutes of the cluster forming,
without any additional operator intervention.

ArgoCD requires ArgoCD to already be installed before it can reconcile ArgoCD.
This bootstrap paradox is solvable but adds a manual step that Flux eliminates.

**Flux CD is confirmed as the GitOps engine.**

---

## 7. Four Intelligence Layers — Detailed Design

### Layer A — Bootstrap Intelligence

**Runtime:** Pre-k3s. Pure Python stdlib. Runs on the operator's machine or the
Proxmox host shell. No cluster, no documentation, no recovery package assumed.

**Purpose:** Build the first-ever environment from bare metal + bootstrap repository
+ human operator.

#### Discovery Subsystem

```
bootstrap/discovery/
  discover-hardware.py    → discovery/hardware.json
    Collects: CPU (model, cores, threads, socket count, architecture)
              RAM (total, ECC status, DIMM slots/populated)
              Storage (drives: model, serial, capacity, type, interface, SMART health)
              NICs (model, ports, speed, MAC, bonding capability)
    Sources:  /proc/cpuinfo, /proc/meminfo, lshw -json, dmidecode, smartctl, ip -j link
    Proxmox:  pveversion, pvecm status

  discover-network.py     → discovery/network.json
    Collects: Bridges (name, ports, STP), VLANs, bonds, physical NICs,
              default route, DNS servers, existing IP allocations
    Sources:  ip -j link, ip -j route, ip -j addr, brctl show, /etc/network/interfaces

  discover-storage.py     → discovery/storage.json
    Collects: ZFS pools (name, topology, vdevs, health, capacity, free),
              block devices (lsblk -J), Proxmox datastores (pvesm status -json)
    Sources:  zpool list -j, zpool status, lsblk -J, pvesm status

  discover-proxmox.py     → discovery/proxmox.json
    Collects: Existing VMs (vmid, name, status, resources, node),
              existing backups (PBS inventory), cluster status, HA configuration
    Sources:  pvesh get /nodes, pvesh get /cluster/status, qm list, pct list
```

#### Planner Subsystem

```
bootstrap/planners/
  cluster-planner.py      → plans/cluster-plan.json
    Inputs:   discovery/hardware.json + metadata/k3s-cluster.yaml
    Logic:
      total_ram_gb → workload capacity after system overhead
      core_count → control plane + worker allocation
      node_count → if 1 physical host: single-node k3s (no HA)
                   if 3+ physical hosts: 3-server embedded etcd HA
      ha_threshold: configurable in metadata (default: 3 physical hosts)
    Output:   {server_nodes: N, worker_nodes: M, ram_per_node_gb: X,
               storage_class: "local-path|longhorn", ha_enabled: bool}

  storage-planner.py      → plans/storage-plan.json
    Inputs:   discovery/storage.json + metadata/hardware-profile.yaml
    Logic:
      disk_count == 2: mirror
      disk_count in [3,4,5]: raidz1
      disk_count in [6,7,8]: raidz2
      disk_count >= 9: raidz3 or nested
      mixed SSD/HDD: separate pools, metadata on SSD
    Output:   ZFS pool topology recommendation

  network-planner.py      → plans/network-plan.json
    Inputs:   discovery/network.json + metadata/network-topology.yaml
    Logic:    Validate declared topology vs discovered hardware
              Flag mismatches (declared VLAN not present on hardware)
              Suggest bridge/bond topology from NIC discovery

  naming-planner.py       → plans/naming-plan.json
    Inputs:   metadata/cell-identity.yaml + metadata/vm-roles.yaml
    Logic:    Apply naming convention from suggest-names.py
              Generate: VM names, hostnames, IPs, KeePass paths, repo names
              Validate uniqueness and convention compliance
```

#### Generator Subsystem

```
bootstrap/generators/
  tofu-vars.py            → opentofu/environments/*/terraform.auto.tfvars
    From: plans/cluster-plan.json + metadata/vm-roles.yaml
    Produces: VM sizing variables (vcpus, ram, disk) for each VM role

  cloud-init-gen.py       → cloud-init/user-data/*.yaml
    From: metadata/ + plans/naming-plan.json + secret-registry.yaml
    Calls: generate-user-data.py (existing) + generate-network-configs.py
    Produces: Complete Cloud-Init snippet set

  ansible-inventory-gen.py → ansible/inventory/hosts.yaml
    From: plans/naming-plan.json + opentofu state (after provisioning)
    Produces: Ansible inventory with groups: proxmox_hosts, k3s_servers,
              k3s_workers, forgejo, operations

  k3s-config-gen.py       → ansible/roles/k3s-server/files/config.yaml
    From: plans/cluster-plan.json + metadata/k3s-cluster.yaml
    Produces: k3s server and agent configuration files

  flux-bootstrap-gen.py   → ansible/roles/flux-bootstrap/files/
    From: metadata/cell-identity.yaml + Forgejo repository URLs
    Produces: Flux bootstrap command and initial HelmRepository sources
```

#### Validator Subsystem

```
bootstrap/validation/
  capacity-validator.py   → validation/capacity-check.json
    Checks: sum(VM RAM requirements) ≤ available host RAM × 0.85
            sum(VM disk requirements) ≤ pool capacity × 0.70
            k3s control plane RAM ≥ 2GB per server node

  readiness-validator.py  → validation/readiness-report.json
    Checks: All generated artifacts exist and pass schema validation
            Secret Registry has entries for all declared secrets
            All declared VMs have Cloud-Init snippets generated
            Network topology validated against hardware discovery
    Gate:   Deployment blocked if any RED findings

  naming-validator.py     → validation/naming-report.json
    Checks: All names comply with naming convention
            No duplicate VM IDs or IPs within the cell
            KeePass paths follow declared convention
```

---

### Layer B — Documentation Engine

**Runtime:** k3s Deployment (always-on) + CronJob (scheduled regeneration).

**Purpose:** Continuously understand and document the running environment.

#### Data Collectors (each a separate CronJob or sidecar)

```
Proxmox Collector    → Queries Proxmox API (pvesh)
  Collects: VM inventory, resource utilization, storage pool status,
            backup job status, network topology, task history
  Schedule: Every 5 minutes

k3s Collector        → Queries Kubernetes API
  Collects: Node inventory, pod inventory, deployment status, PVC status,
            events (last 1 hour), resource requests vs limits
  Schedule: Every 2 minutes

OpenTofu Collector   → Reads terraform.tfstate (remote backend)
  Collects: Declared infrastructure vs provisioned infrastructure
            Detects unmanaged resources (VMs not in OpenTofu state)
  Schedule: Every 15 minutes

Flux Collector       → Queries Flux CD API
  Collects: HelmRelease status, reconciliation timestamps, drift alerts,
            GitRepository sync status
  Schedule: Every 5 minutes

Git Collector        → Queries Forgejo API
  Collects: Repository inventory, last commit timestamps, branch status,
            open issues/PRs relevant to infrastructure
  Schedule: Every 30 minutes

Metadata Collector   → Reads bootstrap/metadata/ from Forgejo
  Collects: All declared metadata (cell-identity, vm-roles, k3s-cluster,
            service-catalog, backup-policy, recovery-priority)
  Schedule: Every 60 minutes or on webhook from Forgejo push
```

#### Documentation Generator (triggered by collectors)

```
Outputs committed to Forgejo docs/ repository:

  architecture.md         Full architecture description (intent-aware)
  inventory.md            All resources (VMs, pods, services) with status
  dependency-map.md       Service dependency graph (Mermaid format)
  service-map.md          All services: ports, URLs, health, dependencies
  topology.yaml           Machine-readable topology (for rendering)
  topology.svg            Rendered topology diagram (via Mermaid CLI)
  changelog.md            Changes since last assessment (diff from previous)
  drift-report.md         Declared vs observed divergence summary

Format rule: Every field includes WHAT + WHY + WHICH POLICY
  Wrong: "3 control-plane nodes"
  Right: "3 control-plane nodes [policy: k3s-cluster.yaml#ha-control-plane,
          reason: etcd quorum requires 3 servers when node_count ≥ 3,
          current_node_count: 3, threshold: 3]"
```

---

### Layer B.5 — Infrastructure Assessment Engine

**Runtime:** k3s Deployment (API server) + multiple CronJobs (assessors).

**Purpose:** Evaluate whether reality matches intended architecture. Produce scored,
actionable reports. This is distinct from the Documentation Engine: documentation
describes what is; assessment evaluates whether what is is correct.

#### Assessment Categories

**Category 1: Resource Health**
```
Checks:
  per-node CPU utilization (WARN: >70% sustained, CRIT: >90%)
  per-node memory utilization (WARN: >80%, CRIT: >95%)
  ZFS pool capacity (WARN: >70% full, CRIT: >85%)
  ZFS pool health (CRIT: DEGRADED or FAULTED)
  k3s node resource pressure (Kubernetes node conditions)
  k3s pod restart rates (WARN: >3 restarts/hour)
  PVC utilization per volume
  etcd database size (WARN: >4GB for embedded etcd)
```

**Category 2: Architectural Drift**
```
Checks:
  VMs present in Proxmox but not in OpenTofu state (unmanaged VMs)
  VMs in OpenTofu state but not running in Proxmox (missing VMs)
  k3s workloads not declared in GitOps repository (shadow deployments)
  GitOps drift: reconciliation failures > threshold
  VM names not following naming convention from metadata
  VM placement not following declared placement policy
  Services running on wrong nodes (if placement policy declared)
  Metadata fields missing or stale (>30 days without update)
```

**Category 3: Recovery Readiness**
```
Checks:
  PBS backup age per VM (WARN: >RPO threshold, CRIT: >2×RPO)
  PBS backup job failures in last 7 days
  PBS datastore availability and capacity
  Recovery package age (WARN: >7 days, CRIT: >14 days)
  Recovery package schema validation pass/fail
  Recovery script syntax validation (shellcheck)
  Last successful recovery test date (WARN: >90 days, CRIT: >180 days)
  Secret registry completeness (all declared secrets have KeePass paths)
  External backup availability (last successful offsite transfer)
  Velero backup status per PVC (if Velero deployed)
```

**Category 4: Documentation Coverage**
```
Checks:
  Resources with no corresponding metadata entry
  Metadata entries with required fields missing
  Services with no service contract declaration
  Resources undocumented for >7 days (new resource, no metadata update)
  Topology diagram age (WARN: >24 hours since last regeneration)
  Runbooks missing for critical recovery phases
  Recovery workbook fields with HUMAN placeholders still unfilled
```

**Category 5: Placement Compliance**
```
Checks:
  k3s control-plane node count vs policy (3 servers required if 3+ hosts)
  Control-plane nodes distributed across physical hosts (not all on same host)
  Storage class vs workload type (stateful workloads on appropriate PVCs)
  High-availability declarations met (replica counts, pod anti-affinity)
  Backup colocation policy (backup server not on same host as backed-up VMs)
  Network redundancy (bonded NICs if policy requires)
```

#### Scoring Systems

All scores are 0–100. GREEN ≥ 80, YELLOW 60–79, ORANGE 40–59, RED < 40.

**Score 1: Architecture Compliance Score (ACS)**
```
ACS = weighted_average([
    drift_score         × 0.35,   # Architectural Drift category
    placement_score     × 0.30,   # Placement Compliance category
    naming_score        × 0.20,   # Naming policy compliance
    metadata_score      × 0.15,   # Metadata completeness for infra resources
])

Each sub-score: 100 − (penalty_per_violation × violation_count)
  Critical violations: −25 points each (unmanaged VM, shadow deployment)
  Major violations:    −10 points each (naming violation, placement deviation)
  Minor violations:    −3 points each (stale metadata, missing optional field)
```

**Score 2: Recovery Readiness Score (RRS)**
```
RRS = weighted_average([
    backup_freshness    × 0.30,   # Backup age vs RPO
    artifact_coverage   × 0.25,   # Recovery package completeness
    test_history        × 0.20,   # Last verified recovery test
    secret_coverage     × 0.15,   # Secret registry completeness
    external_backup     × 0.10,   # Offsite backup availability
])

Absolute blockers (any one makes RRS = 0):
  - Any VM with no backup in > 2 × RPO
  - Recovery package older than 14 days
  - Critical secret with no KeePass path
```

**Score 3: Documentation Coverage Score (DCS)**
```
DCS = (documented_resources / total_resources) × 100
    × quality_multiplier

quality_multiplier:
  All documented resources have complete mandatory fields: 1.0
  >10% have missing mandatory fields: 0.7
  >25% have missing mandatory fields: 0.5

Bonus: Intent-aware fields populated (WHY + WHICH POLICY): +5 (max 100)
```

**Score 4: Capacity Risk Score (CRS)**
```
CRS = 100 − risk_score   (lower raw risk = higher score = better)

risk_score = max(
    cpu_utilization_risk,
    memory_utilization_risk,
    storage_utilization_risk,
    etcd_size_risk,
)

Where each risk maps: <50% util → 0, 70% → 30, 80% → 60, 90% → 80, 95%+ → 100
```

**Score 5: Operational Stability Score (OSS)** *(new in v7.0)*
```
OSS = weighted_average([
    pod_restart_rate    × 0.30,   # Low restarts = stable
    reconciliation_lag  × 0.25,   # Flux keeping up = stable
    event_error_rate    × 0.25,   # Low k8s error events = stable
    uptime_ratio        × 0.20,   # VM uptime vs declared availability
])
```

**Composite Platform Health Score (PHS)**
```
PHS = weighted_average([
    ACS × 0.25,
    RRS × 0.30,    # Recovery readiness is most critical
    DCS × 0.20,
    CRS × 0.15,
    OSS × 0.10,
])
```

All scores are computed per assessment run and stored in the Assessment Store
(PostgreSQL on k3s). Historical scores enable trend analysis.

#### Assessment Engine Architecture

```
intelligence/assessment/
  assessment-api/        Kubernetes Deployment (always-on)
    REST API:
      GET /scores                    Current PHS and all sub-scores
      GET /scores/history?days=30    Score history
      GET /findings                  All active findings with severity
      GET /findings/{category}       Findings by category
      GET /reports/latest            Latest assessment report (JSON)
      GET /reports/{date}            Historical report
      POST /assessments/trigger      Force immediate reassessment
    Storage:             PostgreSQL StatefulSet (or SQLite for single-node)
    Auth:                Bearer token (stored in k3s Secret, referenced in Secret Registry)

  assessors/             CronJobs (one per category, configurable schedule)
    assess-resource-health.py       Every 5 minutes
    assess-architectural-drift.py   Every 15 minutes
    assess-recovery-readiness.py    Every 60 minutes
    assess-documentation-coverage.py Every 30 minutes
    assess-placement-compliance.py  Every 30 minutes

  report-generator.py   CronJob (daily + on-demand)
    Generates:
      assessment-report-{YYYY-MM-DD_HH_MM_SS}-{hash}.ods  (ODS workbook)
      assessment-report-{YYYY-MM-DD_HH_MM_SS}-{hash}.md   (Markdown summary)
    Commits to Forgejo docs/assessments/

  alert-manager.py      Deployment (monitors scores, triggers alerts)
    Alerts when: any score drops below threshold for >15 minutes
    Channels: Prometheus alerting (→ Grafana), Forgejo issue creation
    Never: takes autonomous action on infrastructure
```

---

### Layer C — Recovery Intelligence

**Runtime:** k3s CronJob (scheduled) + triggered by Documentation Engine webhook.

**Purpose:** Generate recovery knowledge — not execute it.

#### Recovery Intelligence Outputs

For each infrastructure component, Recovery Intelligence produces:

```
RESTORE vs RECREATE decision (per component):
  forgejo-vm:     RESTORE (data) + RECREATE (app via Ansible)
  k3s-server-VM:  RECREATE (stateless — OpenTofu + Ansible)
  k3s-etcd:       RESTORE (snapshot) if HA; RECREATE (via GitOps) if single-node
  k3s-PVCs:       RESTORE (Velero backup)
  k3s-manifests:  RECREATE (Flux GitOps reconciliation)
  generated docs: RECREATE (Documentation Engine regenerates)
  metadata:       RESTORE (Git pull from Forgejo or mirror)
  ODS workbooks:  RESTORE (external backup — execution audit trail)
```

Recovery Intelligence also maintains the **Recovery Dependency Graph** — the
sequence in which components must be restored. This is distinct from the
operational dependency graph (which services depend on which) because recovery
ordering has different constraints:

```
Recovery wave ordering:
  Wave 0:  Physical hardware verification
  Wave 1:  Proxmox host (network, storage, API)
  Wave 2:  Forgejo VM (Git hosting — required for GitOps)
  Wave 3:  k3s control plane
  Wave 4:  Flux CD bootstrap (reconciles everything below)
  Wave 5:  Platform services (cert-manager, ingress)
  Wave 5:  Assessment Engine + Documentation Engine
  Wave 6:  Monitoring stack
  Wave 7:  User applications

Note: Within Wave 5, Documentation + Assessment Engine deploy before monitoring
      because they are intelligence-layer workloads, not observability workloads.
```

---

### Layer D — Execution Intelligence

**Runtime:** k3s CronJob (for package generation); standalone scripts (for execution).

**Key design principle:** Execution scripts must run when the cluster does not exist.
They are designed for the worst case — total loss of k3s. They use only bash + Python
stdlib, have no k3s or Helm dependencies, and embed all required configuration.

See Section 12 (Recovery Package) for the full script structure.

---

## 8. Rebalancing Strategy

The Assessment Engine detects suboptimal placement, capacity imbalance, and policy
violations. The question is: what should happen next?

### Phase 1: Detect, Document, Recommend (implemented immediately)

The Assessment Engine never takes autonomous action on infrastructure. All findings
produce:

1. A finding entry in the Assessment Store (with severity, component, description)
2. An updated score with explanation
3. A recommendation entry (what should be done and why)
4. Optionally: a Forgejo issue created automatically with the recommendation

**Examples of Phase 1 outputs:**

```
Finding: UNMANAGED_VM
  Severity: MAJOR
  Component: pve-host-01 / vm-104
  Description: VM 104 (name: 'old-test') exists in Proxmox but not in OpenTofu state
  Recommendation: Either import into OpenTofu state (tofu import) or decommission
  Action required: HUMAN

Finding: BACKUP_AGE_EXCEEDED
  Severity: CRITICAL
  Component: forgejo-vm
  Description: Last successful backup 38 hours ago; RPO declared as 24 hours
  Recommendation: Verify PBS backup job 'pbs-daily-vms' is healthy; check PBS logs
  Action required: HUMAN

Finding: CAPACITY_WARNING
  Severity: MAJOR
  Component: k3s-worker-01 / memory
  Description: Memory utilization 84% (6.7GB / 8GB); threshold 80%
  Recommendation: Consider migrating low-priority workloads to k3s-worker-02
                  or adding a worker node
  Action required: HUMAN
```

### Phase 2: Evaluate Automation (deferred — post Phase 12)

Autonomous remediation introduces risks that must be carefully evaluated before
any implementation:

**Risk 1 — Autonomous migrations can cause downtime.**
Migrating a VM while it has active connections disrupts users. The Assessment Engine
must never trigger a migration without human approval or pre-approved maintenance
windows.

**Risk 2 — Cascading effects are non-obvious.**
Moving a VM that was providing a performance buffer elsewhere may fix one problem
while creating another. Static analysis cannot reliably predict cascading effects.

**Risk 3 — Automation without rollback is dangerous.**
Any autonomous action must have a defined rollback procedure. If the automation
fails mid-migration, what is the recovery path? This must be answered before
Phase 2 automation is implemented.

**Phase 2 safeguards (when eventually implemented):**
- All automated actions require a maintenance window declaration in metadata
- All automated actions are dry-run first and the result reviewed
- All automated actions produce a failure package if they fail
- Rollback procedures must exist and be tested before automation is enabled
- A "circuit breaker" halts all automation if PHS drops below 60 during an action

---

## 9. Source of Truth Governance

### Hierarchy

```
TIER 1 — AUTHORITATIVE INTENT (changes propagate downward)
  metadata/*.yaml files (git-versioned YAML in bootstrap repository)
  Who may update: Human operators with write access to Forgejo bootstrap repo
  Change process: Commit → Forgejo → Documentation Engine webhook → regeneration
  What it declares: What should exist, why, under which policies

TIER 2 — AUTHORITATIVE DECLARED STATE
  opentofu/*.tf + terraform.tfstate (infrastructure declaration)
  kubernetes manifests in GitOps repositories
  Who may update: Human operators; automation via Flux CD reconciliation
  What it declares: What has been provisioned and configured

TIER 3 — AUTHORITATIVE OBSERVED STATE
  Proxmox API (what VMs are actually running)
  Kubernetes API (what pods/deployments/services are actually running)
  Who may update: Not editable — reflects reality
  Conflict with Tier 2: Assessment Engine detects and reports as drift

TIER 4 — DERIVED ARTIFACTS (generated — never edited directly)
  Generated documentation (docs/)
  Generated recovery packages (recovery-packages/)
  Assessment reports
  ODS workbooks (exception: execution records are written by scripts at runtime)

TIER 5 — DISPOSABLE ARTIFACTS
  Rendered diagrams (SVG from Mermaid)
  Cached API responses
  Intermediate build artifacts
```

### Governance Rules

**Rule 1: Generated artifacts are never the source of truth.**
If documentation says "3 control-plane nodes" and metadata says "single-node until
3 physical hosts", the metadata wins. The documentation should be regenerated.

**Rule 2: Conflicts between tiers trigger Assessment Engine findings.**
Tier 2 vs Tier 3 conflict → Architectural Drift finding.
Tier 1 vs Tier 2 conflict → Schema Compliance finding.
Both require human resolution.

**Rule 3: Metadata updates must trigger full regeneration.**
Any commit to metadata/ triggers: documentation regeneration, assessment re-run,
recovery package regeneration. The Forgejo webhook implements this.

**Rule 4: Tier 3 (observed) cannot override Tier 1 (intent).**
If a VM is running that is not in metadata, it is an unmanaged resource (an
Architectural Drift finding), not a metadata update trigger. Metadata declares
intent; reality is what happened. The Assessment Engine surfaces the gap.

**Required external backups by tier:**
```
Tier 1 (metadata):        External Git mirror — daily push to GitHub/Codeberg
Tier 2 (tofu state):      Remote backend on Forgejo + encrypted archive offsite
Tier 2 (k8s manifests):   Part of Forgejo Git mirror
Tier 3 (observed):        Not backed up — reassessed from live APIs
Tier 4 (generated docs):  Not backed up — regenerated on demand
Tier 4 (ODS exec records): Backed up — audit trail, not regenerable after the fact
```

---

## 10. Documentation Engine — Detailed Design

### Intent-Aware Documentation Model

Every documentation field follows this template:

```yaml
# In documentation output:
field: control_plane_count
value: 3
source: kubernetes-api
observed_at: "2026-05-31 14:00:00 UTC"
intent:
  declared_value: 3
  policy_id: "k3s-cluster#ha-control-plane"
  policy_file: "metadata/k3s-cluster.yaml"
  policy_reason: "etcd quorum requires minimum 3 server nodes for HA"
  policy_threshold: "node_count >= 3 physical hosts"
  current_trigger: "3 physical hosts detected"
drift: none
```

In Markdown output, this renders as:

> **Control Plane Nodes:** 3  
> *Policy: `k3s-cluster#ha-control-plane` — etcd quorum requires 3 server nodes
> when 3 or more physical hosts exist. Current trigger: 3 physical hosts detected.*

### Documentation Outputs (committed to Forgejo docs/ on each regeneration)

```
docs/
  architecture/
    architecture.md         Intent-aware architecture description
    decisions.md            All ADRs (AD-001 through AD-N)
    changelog.md            Changes since previous generation

  inventory/
    inventory.md            All resources (VMs, nodes, services, PVCs)
    inventory.json          Machine-readable version

  topology/
    dependency-map.mmd      Mermaid source for dependency graph
    dependency-map.svg      Rendered dependency graph
    service-map.md          All services with ports, URLs, health status
    network-topology.md     Network bridge/VLAN topology
    storage-topology.md     ZFS pool + Proxmox datastore topology

  assessments/              (written by Assessment Engine)
    latest-scores.json      Current PHS and sub-scores
    latest-report.ods       Most recent ODS assessment report
    score-history.csv       Score trends over time

  runbooks/
    operations/             Day-to-day operational runbooks
    recovery/               Recovery phase runbooks (generated by Phase C)

  recovery/                 (written by Recovery Generator)
    recovery-package.tar.gz Latest recovery package
    readiness-report.ods    Recovery readiness ODS workbook
```

---

## 11. Recovery Package Design

### recovery-package-{cell_id}_{ts}_{hash}.tar.gz

Self-contained. Offline-capable. No internet required, no Forgejo required for
execution of Phases 1–3.

```
├── MANIFEST.json           Package metadata, checksums, generation context
│
├── metadata/               Complete metadata/ snapshot (Tier 1 snapshot)
│   └── *.yaml
│
├── context/                Recovery context from Assessment Engine
│   ├── scores.json         PHS + all sub-scores at generation time
│   ├── findings.json       All active findings at generation time
│   ├── inventory.json      Complete infrastructure inventory
│   └── topology.json       Dependency graph and recovery waves
│
├── opentofu/               OpenTofu state and configs
│   ├── terraform.tfstate   State snapshot (Tier 2 snapshot)
│   └── environments/       Embedded TF configs (no Forgejo access needed)
│
├── manifests/              Kubernetes manifests (embedded, no GitOps needed)
│   └── (per-namespace emergency manifests for k3s emergency bootstrap)
│
├── runbooks/               Phase runbooks (Markdown)
│   ├── 00-pre-recovery-checklist.md
│   ├── 01-hardware-verification.md
│   ├── 02-proxmox-restoration.md
│   ├── 03-forgejo-restoration.md
│   ├── 04-k3s-cluster.md
│   ├── 05-gitops-bootstrap.md
│   ├── 06-intelligence-layer.md   Documentation + Assessment engines
│   ├── 07-monitoring.md
│   └── 08-applications.md
│
├── workbooks/
│   ├── recovery-workbook.ods      Master recovery execution record
│   └── readiness-report.ods       Pre-recovery scores and findings
│
├── scripts/
│   ├── lib/
│   │   ├── checkpoint.sh          Checkpoint tracking (file-based)
│   │   ├── validation.sh          Post-step validation functions
│   │   ├── ods-update.sh          ODS workbook machine-update (wraps Python)
│   │   └── failure-package.sh     Auto failure package generation
│   │
│   ├── recover-phase-01-hardware.sh
│   ├── recover-phase-02-proxmox.sh
│   ├── recover-phase-03-forgejo.sh
│   ├── recover-phase-04-k3s.sh
│   ├── recover-phase-05-gitops.sh
│   ├── recover-phase-06-intelligence.sh
│   ├── recover-phase-07-monitoring.sh
│   ├── recover-phase-08-applications.sh
│   └── run-all.sh                 Orchestrated recovery entry point
│
├── validation/
│   ├── validate-proxmox.sh
│   ├── validate-k3s.sh
│   ├── validate-gitops.sh
│   └── validate-intelligence.sh
│
├── secrets/
│   └── secret-registry.yaml      KeePass paths only (no values)
│
└── logs/                          Empty — populated during recovery execution
```

### ODS Recovery Workbook Structure

```
Sheet: Overview
  Cell B1: Cell ID
  Cell B2: Recovery package timestamp
  Cell B3: Platform Health Score at generation time
  Cell B4: Recovery Readiness Score at generation time
  Cell B5: Overall recovery status
  Cell B6: Current phase
  Table rows: Phase summary (phase_id, label, status, start, end, duration)

Sheet: Phase-N (one per recovery phase, N = 01 through 08)
  Col A: Step ID
  Col B: Step description
  Col C: RESTORE / RECREATE / VERIFY
  Col D: Status (PENDING / IN_PROGRESS / PASSED / FAILED / SKIPPED)
  Col E: Start timestamp
  Col F: End timestamp
  Col G: Operator notes
  Col H: Validation result

Sheet: Findings (pre-recovery assessment state)
  All Assessment Engine findings active at package generation time

Sheet: Validation Log
  All post-step validation outputs

Sheet: Failure Log
  Any failures with timestamps and failure package references

Sheet: Score History
  Score at generation time + scores from any previous recovery attempts
```

---

## 12. Failure Analysis Package

### failure-package-{cell_id}_{phase}_{step}_{ts}_{hash}.tar.gz

Generated automatically by `failure-package.sh` when any script step fails.

```
├── summary.md              LLM-optimised failure summary (see template below)
├── execution-history.md    Timeline of all steps with timestamps and results
│
├── context/
│   ├── cell-identity.yaml
│   ├── phase.txt           "recover-phase-04-k3s / step-02-provision-vms"
│   ├── recovery-package-manifest.json
│   └── workbook-state.ods  Workbook state at time of failure
│
├── logs/
│   ├── script-stdout.log   All script output
│   ├── script-stderr.log   Error output only
│   ├── tofu-output.log     OpenTofu output (if step involved tofu)
│   ├── ansible-output.log  Ansible output (if step involved ansible)
│   ├── proxmox-tasks.json  pvesh get /nodes/{node}/tasks (last 50)
│   └── k8s-events.json     kubectl get events -A --sort-by=.metadata.creationTimestamp
│
├── system/
│   ├── df-output.txt
│   ├── free-output.txt
│   ├── ip-route.txt
│   └── proxmox-status.txt  pveversion + pvecm status
│
└── validation-output/      Output of the validation function that detected failure
```

### summary.md Template

```markdown
# Recovery Failure Summary

**Generated:** {YYYY-MM-DD HH:MM:SS UTC (local)}
**Cell:** {cell_id}
**Phase:** {phase_number} — {phase_label}
**Step:** {step_id} — {step_label}
**Recovery Package:** {package_filename}
**Platform Health Score at failure:** {PHS}
**Recovery Readiness Score at failure:** {RRS}

## What Was Being Attempted
{One paragraph: what this step does and why it is necessary for recovery}

## The Failure
**Last command executed:**
```
{command}
```
**Error output (last 50 lines):**
```
{stderr_tail}
```
**Exit code:** {exit_code}

## System State
- Proxmox API: {reachable / unreachable}
- k3s API: {reachable / unreachable / not-yet-deployed}
- Forgejo: {reachable / unreachable / not-yet-restored}
- Last successful checkpoint: {phase}-{step}

## Completed Steps (succeeded before this failure)
{Bulleted list of completed phase+step with timestamps}

## Active Findings at Time of Failure
{Top 5 findings from Assessment Engine at package generation time}

## Suggested LLM Prompt
"I am performing disaster recovery on a Proxmox + k3s homelab.
Phase {phase_number} ({phase_label}), step {step_id} ({step_label}) failed.
The error was: {one_line_error_summary}.
System state: {proxmox_status}, {k3s_status}, {forgejo_status}.
Attached are the full logs and system state. Please:
1. Identify the most likely root cause.
2. Suggest specific remediation steps.
3. Identify any recovery preconditions that may not have been met."

## Attached Files
- logs/script-stdout.log
- logs/script-stderr.log
{additional files if applicable}
```

---

## 13. Continuous Improvement Loop

```
Recovery or Deployment Attempt
    │
    ▼
Step fails → failure-package.sh executes automatically
    │
    ├── failure-package-{id}.tar.gz generated in <30 seconds
    ├── ODS workbook updated: step status = FAILED, failure package path recorded
    ├── Failure logged to Assessment Engine (if reachable)
    └── Recovery script exits with non-zero code
    │
    ▼
Human downloads failure package
    │
    ├── Reads summary.md (designed to be immediately useful without LLM)
    ├── Optionally: submits to LLM using embedded suggested prompt
    └── Identifies: root cause category
        │
        ├── Metadata error → update metadata/ + commit to Forgejo
        ├── Script error → update recovery/scripts/ + commit
        ├── Validation too strict → update validation/ + commit
        ├── Hardware assumption wrong → update hardware-profile.yaml + commit
        └── Environment-specific issue → document in docs/known-issues.md + commit
    │
    ▼
Bootstrap repository commit made
    │
    ├── Forgejo webhook triggers Documentation Engine
    ├── Documentation Engine triggers Assessment Engine reassessment
    └── Recovery Generator regenerates recovery package with improved scripts
    │
    ▼
Future recovery attempt uses improved scripts
    │
    └── Over time: failure rate per phase decreases
                  Recovery Readiness Score increases
                  Known issue patterns documented in metadata
```

**Long-term mechanism:** As failure packages accumulate, patterns become visible.
Multiple failures in `recover-phase-03-forgejo` with similar error messages indicate
a systemic issue (e.g., Forgejo version incompatibility in PBS backup). The
Assessment Engine can be extended to detect these patterns and raise proactive findings.

---

## 14. Architectural Challenges and Resolutions

### Challenge 1 — The Assessment Engine assesses itself

**Problem:** The Assessment Engine evaluates whether the intelligence layer is
healthy. But if the Assessment Engine itself is unhealthy, it cannot assess itself.
This creates a blind spot for the most critical component.

**Resolution:**
- The Assessment Engine exposes a `/health` endpoint that Kubernetes liveness and
  readiness probes check independently of the engine's own logic
- Prometheus scrapes the Assessment Engine's metrics — monitoring detects assessment
  engine failures independently of the engine itself
- A simple shell script in the recovery package validates that the assessment API
  is responding correctly without depending on the API's own assessment logic
- The failure mode is explicitly documented: "If Assessment Engine is not reporting,
  treat RRS and ACS as UNKNOWN (not GREEN)"

### Challenge 2 — Forgejo is a pre-k3s VM and therefore a recovery prerequisite

**Problem:** Forgejo must exist before k3s (k3s GitOps pulls from Forgejo).
This makes Forgejo the most critical infrastructure dependency. If Forgejo is
catastrophically lost and PBS backup is unavailable, the entire platform is
inaccessible.

**Resolution:**
- Forgejo VM has the most aggressive backup policy (2× daily PBS snapshots)
- Forgejo repositories are mirrored to external Git providers (GitHub, Codeberg)
  via daily push — external Git is the fallback source for Flux bootstrap
- Recovery packages embed the k3s manifests needed for Phase 6 (intelligence layer)
  directly — no Forgejo access required for Phases 1–5
- The operations-vm (second pre-k3s VM) has a cached clone of all Forgejo repos
  updated nightly — provides emergency read-only access without Forgejo
- Recovery Phase 3 explicitly restores Forgejo before any k3s work
- The failure scenario "Forgejo permanently lost + PBS unavailable" has a documented
  recovery path: bootstrap from external Git mirror + Velero application data restore

### Challenge 3 — ODS workbook updates from shell scripts are fragile

**Problem:** Updating a binary ODS file from a bash script requires Python + stdlib
zipfile XML manipulation. If the update code has a bug, it may corrupt the workbook,
potentially losing the execution audit trail.

**Resolution:**
- All ODS updates are atomic: the script reads the ODS, updates the in-memory
  representation, writes to a temp file, validates the temp file opens (via Python),
  then replaces the original only if validation passes
- Every ODS update function takes a backup of the original before modifying
- If the ODS update itself fails, recovery continues — the workbook failure is
  logged to a plaintext fallback log (recovery-fallback.log)
- The ODS update code is covered by tests in the existing test suite (test_backup.py)
- ODS corruption is treated as a non-fatal failure during recovery

### Challenge 4 — The scoring system is gameable

**Problem:** If operators learn the scoring algorithm, they can optimize for the
score rather than for actual readiness. E.g., running a recovery test once every
89 days to stay just inside the threshold rather than maintaining genuine capability.

**Resolution:**
- Scores are accompanied by finding details — a score of 95 with 3 critical findings
  still visible is less trustworthy than a score of 75 with 0 critical findings
- Score history is tracked — a score that suddenly drops from 90 to 40 and recovers
  in 24 hours may indicate gaming rather than genuine remediation
- The Phase 12 governance review explicitly evaluates score trends alongside findings
- The ultimate test is the Phase 10 reconstruction drill — scores are validated
  against actual recovery success

### Challenge 5 — Documentation Engine commit frequency creates Git noise

**Problem:** The Documentation Engine regenerates documentation on every change
detection and commits to Forgejo. If Flux is reconciling changes frequently, this
could produce dozens of documentation commits per day, polluting Git history.

**Resolution:**
- Documentation commits are batched: the engine queues changes for 10 minutes,
  then commits once with a consolidated commit message
- Documentation is committed to a dedicated docs/ repository (not the same
  repository as manifests), minimizing cross-concern noise
- The docs/ repository uses a protected branch with the Documentation Engine as
  the only authorized committer — human commits go to a feature branch and are
  merged via PR
- Score history and assessment reports have their own repository (docs-assessments/)
  to further separate frequent assessment writes from architectural documentation

### Challenge 6 — Single-node k3s has no compute failover

**Problem:** In Phase 3 (initial deployment), k3s runs as a single node. If that
VM fails, all k3s workloads — including the documentation engine and assessment
engine — go down. The platform's intelligence layer is unavailable precisely when
it is most needed (during incident response).

**Resolution:**
- The most recent recovery package is stored in four places simultaneously:
  1. Forgejo docs/recovery/ (k3s-hosted, first to go down)
  2. operations-vm filesystem (pre-k3s VM, survives k3s failure)
  3. External backup (cloud storage, offline-capable)
  4. PBS snapshot of k3s VM (Proxmox-hosted, survives k3s failure)
- Phase 9 (multi-node scaling) adds a second k3s worker — the intelligence layer
  moves to 2-replica Deployments with pod anti-affinity
- Phase 11 (HA control plane) adds 3-server embedded etcd — full HA for the
  intelligence layer
- Single-node is explicitly documented as a development/bootstrapping configuration,
  not a production configuration

### Challenge 7 — The "applications secondary" philosophy may conflict with user needs

**Problem:** The architectural philosophy states applications are secondary to
the platform. In practice, users care more about Nextcloud being up than about
the Assessment Engine's compliance score. This creates tension in prioritization.

**Resolution:**
- The philosophy applies to deployment ORDER and architectural prioritization —
  not to operational prioritization
- In production: if Nextcloud goes down, it is treated as a P1 incident regardless
  of the platform's self-documentation status
- The phrase "applications are secondary" means: the platform will not deploy
  applications until its intelligence layer is operational. Once deployed,
  applications are full first-class citizens with equal recovery priority
- The Assessment Engine scores application workloads with the same rigor as
  platform workloads — there is no second-class tier at runtime

---

## 15. Architecture Decision Records — v7.0

### AD-032: Infrastructure Assessment Engine as first-class subsystem
The Assessment Engine is not a feature of the Documentation Engine. It is a
separate subsystem with its own k3s Deployment, its own storage (PostgreSQL),
its own API, and its own assessment schedules. Conflating documentation and
assessment creates an engine that does both poorly.

### AD-033: Five scoring dimensions with composite Platform Health Score
Five scores (ACS, RRS, DCS, CRS, OSS) aggregate into a composite PHS. Scores
use weighted averages with absolute blockers for critical conditions. Historical
score tracking enables trend analysis and gaming detection.

### AD-034: Phase 1 rebalancing is detect/document/recommend only
The Assessment Engine never takes autonomous infrastructure action. All findings
produce human-reviewable recommendations. Automation (Phase 2) is explicitly
deferred until after Phase 12 and requires additional safeguards.

### AD-035: intelligence/ namespace deploys before applications/ namespace
All intelligence-layer workloads (documentation engine, assessment engine,
recovery generator) are deployed before any user application. Flux CD dependency
declarations enforce this ordering.

### AD-036: Failure packages are generated before script exit
`failure-package.sh` is sourced at the top of every recovery script. If any
step fails (`set -e`), the error trap fires, generates the failure package, updates
the ODS workbook, and then exits. Failure analysis capability must not itself fail.

### AD-037: ODS updates are atomic with plaintext fallback
Every ODS update creates a backup, modifies a temp file, validates the temp file,
then atomically replaces the original. If the ODS update fails, recovery continues
and logs to recovery-fallback.log. The audit trail is important; recovery is more
important.

### AD-038: Documentation commits are batched to reduce Git noise
Documentation Engine batches commit frequency: minimum 10 minutes between commits.
Assessment reports have a dedicated repository (docs-assessments/) separate from
architectural documentation.

---

## 16. Twelve-Phase Implementation Roadmap

---

### Phase 0 — Metadata Model and Architecture Governance

**Objectives:**
Define the complete metadata schema before any infrastructure is built. All
subsequent phases consume metadata — errors here propagate everywhere.

**Deliverables:**
- metadata/ YAML schemas: cell-identity, hardware-profile, network-topology,
  vm-roles, k3s-cluster, service-catalog, backup-policy, recovery-priority,
  placement-policy, naming-convention
- JSON Schema definitions for all metadata files (for validation)
- Bootstrap repository skeleton (all directories, README, .gitignore)
- Source of truth governance document (who can update what, conflict resolution)
- Architecture Decision Records AD-001 through AD-038
- External backup strategy: provider, schedule, retention confirmed
- Secret registry initial entries (KeePass paths for all anticipated secrets)
- Naming convention document and naming-planner.py

**Risks:** Metadata schema gaps require retroactive updates. Over-engineering metadata
before real infrastructure is understood.
**Mitigation:** Start with minimum viable fields; use `additionalProperties: true`
in schemas to allow extension without breaking validation.

**Dependencies:** None (this is Phase 0).

**Validation:**
- All metadata schemas validate against JSON Schema using validate.py
- README produces a working skeleton when followed by a new operator
- naming-planner.py produces valid names for a test hardware profile

**Documentation outputs:** ARCHITECTURE.md (v7.0), ROADMAP.md (v7.0), all ADRs,
metadata schema documentation, naming convention guide

**Workbook outputs:** None

**Recovery outputs:** None

---

### Phase 1 — Bootstrap Intelligence Framework

**Objectives:**
Implement the complete Phase A discovery → plan → generate → validate pipeline.
An operator with bare metal + Proxmox should be able to run the bootstrap framework
and produce a deployment-ready configuration.

**Deliverables:**
- discovery/ scripts: hardware, network, storage, Proxmox discovery
- planners/: cluster-planner, storage-planner, network-planner, naming-planner
- generators/: tofu-vars, cloud-init, ansible-inventory, k3s-config, flux-bootstrap
- validation/: capacity, network, naming, readiness validators
- Updated init-bootstrap-state.py (consumes discovery reports)
- Updated suggest-names.py (k3s naming conventions)
- Updated roles.py (k3s-server and k3s-worker roles added)
- Tests: discovery → plan → generate → validate pipeline coverage

**Risks:** Discovery scripts produce incorrect data on non-standard hardware.
Planners produce configurations that fail provisioning.

**Dependencies:** Phase 0 (metadata schemas).

**Validation:**
- Run full pipeline on a test hardware profile (JSON fixture)
- readiness-report.json produced with no RED findings
- All generated artifacts validate against their schemas
- Shell scripts pass shellcheck

**Documentation outputs:** Bootstrap discovery report, hardware profile documentation

**Workbook outputs:** Bootstrap planning workbook (ODS) — Phase A toolchain output

**Recovery outputs:** None (no infrastructure yet)

---

### Phase 2 — Proxmox Automation

**Objectives:**
Automate Proxmox host post-install configuration and deploy pre-k3s infrastructure
VMs (Forgejo, operations-vm) using OpenTofu + Ansible.

**Deliverables:**
- OpenTofu modules: vm/, network/, storage/
- OpenTofu environments: bootstrap/ (Forgejo + operations-vm)
- Ansible roles: common, proxmox-host, forgejo, operations-vm
- Ansible playbooks: 00-preflight through 02-bootstrap-vms
- Forgejo operational: all repositories imported, webhooks configured
- External backup configured and tested (setup-external-backup.py)
- Bootstrap-state.json validated, committed to Forgejo, and pushed externally

**Risks:** Proxmox API version incompatibilities. Network topology mismatch between
declared metadata and actual hardware. ZFS pool creation failures on non-standard
disk configurations.

**Dependencies:** Phase 1 (bootstrap framework).

**Validation:**
- Forgejo accessible via browser and API
- All repositories cloned and accessible
- External backup completes and produces valid archive
- Forgejo webhook to operations-vm test: commit → webhook received

**Documentation outputs:** Proxmox inventory, network topology map (generated by
nascent documentation process — pre-engine, scripts only)

**Workbook outputs:** Phase 2 deployment workbook (ODS)

**Recovery outputs:** recover-phase-02-proxmox.sh, recover-phase-03-forgejo.sh
(first recovery scripts — produced before any k3s exists)

---

### Phase 3 — Initial k3s Deployment

**Objectives:**
Deploy a single-node k3s cluster. Install core platform services. Verify the
Kubernetes API is accessible and platform services are healthy.

**Deliverables:**
- OpenTofu environment: k3s-nodes/ (k3s-server-01 VM, 4GB RAM minimum)
- Ansible role: k3s-server (single-node, embedded SQLite, no HA)
- Ansible playbook: 03-k3s-cluster
- Core platform services deployed (kubectl apply, not GitOps yet):
  - cert-manager
  - ingress-nginx
  - local-path-provisioner (default storage class)
- k3s kubeconfig secured and stored (reference in Secret Registry)

**Risks:** k3s networking conflicts with Proxmox bridge configuration.
cert-manager ACME challenges fail without working ingress.
Storage class not provisioning PVCs correctly.

**Dependencies:** Phase 2 (Forgejo operational, operations-vm accessible).

**Validation:**
- `kubectl get nodes` → Ready
- cert-manager issues a test certificate
- ingress-nginx returns 200 for /.well-known/health
- local-path-provisioner creates and mounts a test PVC

**Documentation outputs:** k3s cluster topology, node inventory (static markdown,
not yet automated)

**Workbook outputs:** k3s deployment workbook (ODS)

**Recovery outputs:** recover-phase-04-k3s.sh

---

### Phase 4 — Documentation Engine

**Objectives:**
Deploy the Documentation Engine as the FIRST k3s workload. The platform must
document itself before hosting anything else. By the end of Phase 4, the platform
produces a complete living inventory and architecture documentation.

**Deliverables:**
- Documentation Engine containerised (from existing doc-gen codebase)
- Kubernetes manifests: Deployment + CronJob + ConfigMap + RBAC + ServiceAccount
- Data collectors: Proxmox (via Proxmox API), k3s (via Kubernetes API),
  OpenTofu (remote state), Forgejo (API), metadata (Git pull)
- Intent-aware documentation generation (STATE + WHY + WHICH POLICY)
- Documentation committed to Forgejo docs/ on each generation
- Forgejo webhook from docs/ triggers notification (Prometheus metric)
- Topology diagram generation (Mermaid → SVG via Mermaid CLI in container)

**Risks:** Proxmox API credentials not injectable into k3s pods (Secret management).
Documentation Engine produces incomplete output if bootstrap-state.json is
not fully populated. Git commit identity for automated commits.

**Dependencies:** Phase 3 (k3s operational), Phase 2 (Forgejo operational).

**Validation:**
- Documentation Engine pod is Running
- docs/inventory.md committed to Forgejo with correct content
- docs/architecture.md contains intent-aware fields (WHY + WHICH POLICY)
- Mermaid topology diagram renders correctly
- Documentation regenerates within 15 minutes of a metadata commit

**Documentation outputs:** ALL documentation types first produced here:
inventory, architecture, dependency map, service map, topology diagram

**Workbook outputs:** None for this phase (Assessment Engine not yet deployed)

**Recovery outputs:** recover-phase-06-intelligence.sh (first version)

---

### Phase 5 — Infrastructure Assessment Engine

**Objectives:**
Deploy the Assessment Engine. The platform must evaluate itself before hosting
user workloads. By the end of Phase 5, all five scores are computed and actionable.

**Deliverables:**
- PostgreSQL StatefulSet (Assessment Store)
- Assessment API Deployment (REST API for score/finding queries)
- Assessor CronJobs: resource-health, architectural-drift, recovery-readiness,
  documentation-coverage, placement-compliance
- Report generator CronJob (daily ODS + Markdown)
- Alert manager Deployment (Prometheus metrics + Forgejo issue creation)
- Assessment scores integrated into Grafana dashboard
- First assessment report generated and committed to Forgejo

**Risks:** Assessment engine has false positives in early deployment (findings
that don't represent real problems). Scoring thresholds are misconfigured.

**Dependencies:** Phase 4 (Documentation Engine as assessment data source),
Phase 3 (k3s and PostgreSQL).

**Validation:**
- Assessment API returns all five scores (ACS, RRS, DCS, CRS, OSS)
- PHS computed correctly
- Grafana dashboard shows score history
- A deliberate violation (create unmanaged VM) appears as a finding within 15 minutes
- ODS assessment report opens in LibreOffice without errors

**Documentation outputs:** First assessment report (ODS + Markdown), score
history baseline established

**Workbook outputs:** assessment-report-{ts}.ods (first scored assessment)

**Recovery outputs:** Recovery package updated with assessment findings context

---

### Phase 6 — GitOps Integration

**Objectives:**
Transition from manual manifest application to Flux CD continuous reconciliation.
All platform state managed through Git. Documentation Engine detects and reports
all Flux-managed state.

**Deliverables:**
- Forgejo repositories restructured for GitOps:
  - platform-config/ (Flux sources, Kustomizations, HelmReleases)
  - Each intelligence workload in its own repository
- Flux CD bootstrapped against Forgejo platform-config/
- All Phase 3/4/5 services converted to Flux-managed HelmReleases
- Flux reconciliation status visible in Assessment Engine (Drift category)
- Documentation Engine extended to document GitOps state (Flux Collector)
- Forgejo → Flux webhook (immediate reconciliation on push)

**Risks:** Flux reconciliation loop conflicts with manually applied resources.
Flux bootstrap points at wrong repository. Secret management for Flux (Forgejo
credentials).

**Dependencies:** Phase 5 (Assessment Engine operational to detect GitOps drift).

**Validation:**
- Commit a change to platform-config/; Flux applies it within 60 seconds
- Flux Collector reports reconciliation status in Documentation Engine
- A failed reconciliation appears as a drift finding in Assessment Engine within
  15 minutes
- `flux get all` shows all HelmReleases as Ready

**Documentation outputs:** GitOps topology added to architecture docs, Flux
reconciliation status added to inventory

**Workbook outputs:** None

**Recovery outputs:** recover-phase-05-gitops.sh updated with Flux bootstrap commands

---

### Phase 7 — Application Platform

**Objectives:**
Deploy user workloads using GitOps. Gate: all four intelligence layer components
must be healthy (PHS ≥ 80) before any user application is approved for deployment.

**Deployment order:**
- monitoring/ (Prometheus, Grafana, Loki)
- applications/ (per service: create manifest repo → merge to Forgejo → Flux applies)

**Deliverables:**
- Per-application manifest repositories in Forgejo
- Flux HelmReleases for each application
- Per-application service contracts (metadata/service-catalog.yaml entries)
- Documentation Engine extended: application service map
- Assessment Engine extended: application workload health in Resource Health category
- Per-application recovery runbooks (generated by Recovery Generator)
- Velero deployed for PVC backup

**Risks:** Application data increases recovery complexity significantly. PVC storage
class choices affect backup strategy and performance. Applications that are not
12-factor compliant may bake configuration into volumes.

**Dependencies:** Phase 6 (GitOps), Phase 5 (Assessment Engine scoring PHS ≥ 80
as gate), Phase 4 (Documentation Engine documenting applications).

**Validation:**
- PHS ≥ 80 before any user application Flux source is created
- All applications healthy per Kubernetes readiness probes
- Assessment Engine generates service-map including all applications
- Velero backup job successful for all application PVCs

**Documentation outputs:** Application service map, updated dependency graph,
per-application runbooks

**Workbook outputs:** Per-application deployment workbook

**Recovery outputs:** recover-phase-08-applications.sh; per-application recovery runbooks

---

### Phase 8 — Recovery Artifact Generation

**Objectives:**
Automate complete recovery package generation and validation. By the end of Phase 8,
the recovery package is generated automatically, validated against schema, and
available offline.

**Deliverables:**
- Recovery Generator containerised as k3s CronJob
- Complete recovery package schema and generator (from Phase C design)
- All recovery scripts templated and generated (Phase D design)
- Script syntax validation (shellcheck in CI)
- ODS workbook generator for recovery-workbook.ods and readiness-report.ods
- Recovery package stored in: Forgejo docs/recovery/ + operations-vm + external backup
- Recovery package schema validation (new validator in validate.py)
- Assessment Engine: recovery package age and validity in Recovery Readiness category

**Risks:** Generated recovery scripts have untested assumptions only discovered
during actual recovery. Script templates use hardcoded paths that differ in real
deployments. Recovery package grows too large for practical distribution.

**Dependencies:** Phase 7 (all services for which recovery is generated),
Phase 5 (Assessment Engine for recovery readiness scoring).

**Validation:**
- Recovery package validates against schema
- All shell scripts pass shellcheck
- All referenced KeePass paths verified in secret-registry.yaml
- ODS workbook opens in LibreOffice without errors
- Recovery Readiness Score ≥ 70 after package generation

**Documentation outputs:** Recovery readiness report, gap analysis report

**Workbook outputs:** recovery-workbook.ods (first machine-generated version),
readiness-report.ods

**Recovery outputs:** Complete recovery-package.tar.gz with all phases

---

### Phase 9 — Executable Recovery Generation

**Objectives:**
Make recovery executable, checkpoint-based, resumable, and failure-analysis-capable.
Run a partial simulated recovery to validate the scripts work.

**Deliverables:**
- lib/checkpoint.sh — file-based checkpoint tracking (resumable)
- lib/validation.sh — post-step validation function library
- lib/ods-update.sh — ODS machine-update (atomic with plaintext fallback)
- lib/failure-package.sh — automatic failure package generation before exit
- All recovery scripts updated with checkpoint + ODS + failure-package libs
- Simulated recovery test: restore Forgejo VM from PBS + run recover-phase-03-forgejo.sh
- Failure package generation tested: simulate failure, verify package produced
- Assessment Engine: Phase 9 adds Operational Stability Score (OSS)

**Risks:** ODS update fragility (see Challenge 3). Checkpoint file management
across multiple recovery attempts.

**Dependencies:** Phase 8 (complete recovery artifact generation).

**Validation:**
- Simulate step failure; verify failure-package.tar.gz generated in <30 seconds
- Verify summary.md is complete and LLM-ready
- Simulate interrupted recovery; verify re-run resumes from last checkpoint
- Verify ODS workbook updated correctly during simulated recovery

**Documentation outputs:** Executable recovery documentation, checkpoint system design

**Workbook outputs:** Simulated recovery workbook (completed ODS from test run)

**Recovery outputs:** All recovery scripts with checkpoint + failure package support

---

### Phase 10 — Recovery Validation

**Objectives:**
Perform the first full destruction drill. Destroy the k3s cluster and all
application VMs. Recover from recovery package only. Document all gaps.

**Deliverables:**
- Full destruction: k3s VMs destroyed, application data deleted
- Recovery executed from latest recovery-package.tar.gz on operations-vm
- Recovery time measured per phase vs declared RTO
- All gaps identified in bootstrap repository commits
- Recovery Readiness Score measured before and after drill
- Drill results documented in docs/drills/

**Risks:** First drill always reveals gaps. Do not skip it.
First drill may reveal that RTO declarations are unrealistic.

**Dependencies:** Phase 9 (fully executable, resumable recovery).

**Validation Criteria (all must pass):**
- Recovery package downloaded and verified: < 5 minutes
- Forgejo operational: < 30 minutes
- k3s cluster operational: < 45 minutes
- Intelligence layer operational: < 60 minutes
- All applications operational: < 120 minutes
- No step required manual action not covered by recovery scripts
- ODS workbook complete and accurate
- Failure package NOT generated (no failures)

**Documentation outputs:** Drill report, RTO/RPO compliance report, gap analysis

**Workbook outputs:** Drill execution workbook (the gold standard completed ODS)

**Recovery outputs:** Improved recovery package incorporating drill findings

---

### Phase 11 — Multi-Node Scaling

**Objectives:**
Scale from single-node k3s to multi-node HA when a second physical Proxmox host
is added. Intelligence layer moves to replicated deployments.

**Deliverables:**
- metadata/k3s-cluster.yaml node_count threshold evaluation triggers planner
- OpenTofu k3s-nodes environment supports N-server + M-agent topology
- k3s migration: single-node SQLite → 3-server embedded etcd
- Longhorn deployed (distributed persistent storage across nodes)
- Velero updated to use Longhorn-aware backup
- Documentation Engine: multi-node topology visualization
- Assessment Engine: placement compliance checks updated for multi-node
- Intelligence layer workloads: 2+ replicas with pod anti-affinity
- Second physical host added: control-plane nodes distributed across hosts

**Risks:** SQLite → etcd migration is destructive (requires cluster rebuild; workload
downtime). Longhorn adds operational complexity and potential performance impact.
Control-plane distribution requires careful pod anti-affinity configuration.

**Dependencies:** Phase 10 (recovery capability validated before adding complexity).

**Validation:**
- Node failure simulation: workloads migrate within 120 seconds
- etcd quorum maintained with one server node removed
- Longhorn volume replication healthy (2+ replicas per PVC)
- Intelligence layer remains operational during node failure simulation

**Documentation outputs:** Multi-node topology, HA architecture documentation

**Workbook outputs:** Multi-node deployment workbook

**Recovery outputs:** Updated recovery scripts for multi-node cluster restoration

---

### Phase 12 — Architecture Governance and Continuous Improvement

**Objectives:**
Establish ongoing governance processes. The platform should continuously improve
its self-understanding, documentation quality, and recovery capability without
requiring major architectural changes.

**Deliverables:**
- Quarterly reconstruction drill procedure (documented and scheduled)
- Score trend dashboard in Grafana (PHS history, score degradation alerts)
- Governance review process (what triggers an architecture review)
- Failure package analysis workflow (documented LLM-assisted analysis procedure)
- Assessment Engine Pattern Detector (identifies recurring failure types in packages)
- Phase 2 rebalancing evaluation: proposal for which findings could be auto-remediated
  with appropriate safeguards, risk analysis, rollback procedures
- Documentation Engine coverage SLA: DCS ≥ 85 maintained continuously
- Recovery Readiness SLA: RRS ≥ 80 maintained continuously
- Alerts if PHS drops below 70 for >30 minutes

**Risks:** Governance processes become bureaucratic and are abandoned. Scores are
gamed rather than representing real readiness. Phase 2 automation proposals are
adopted without adequate safeguards.

**Dependencies:** Phase 11 (multi-node, full platform operational).

**Validation:**
- Second reconstruction drill completes faster than first (improvement demonstrated)
- PHS ≥ 80 sustained for 30 days without manual intervention
- 3 failure packages analyzed; all analysis resulted in bootstrap repository commits
- Phase 2 proposal reviewed and either approved with safeguards or rejected with
  documented reasoning

**Documentation outputs:** Governance document, score trend analysis, Phase 2 proposal

**Workbook outputs:** Governance review workbook (ODS), quarterly drill workbook

**Recovery outputs:** Final recovery package with all Phase 12 improvements

---

## 17. Summary

The v7.0 architecture formalises what was implicit in v6.0 and adds the critical
missing piece: a rigorous, scored, actionable self-evaluation capability.

The five architectural additions beyond v6.0:

1. **Infrastructure Assessment Engine** — a first-class subsystem that evaluates
   five categories (resource health, architectural drift, recovery readiness,
   documentation coverage, placement compliance) and produces five scores that
   aggregate into a composite Platform Health Score.

2. **Formal scoring systems** — five scores with defined computation, absolute
   blockers, and threshold-based alerting. Scores enable the platform to signal
   when attention is needed, not just produce documentation.

3. **Phase 1 rebalancing** — the Assessment Engine detects and recommends; it
   never acts autonomously. Phase 2 automation is explicitly deferred until after
   Phase 12 governance review, with defined safeguards required before implementation.

4. **Source of truth governance** — a four-tier hierarchy with explicit conflict
   resolution rules, update authority definitions, and trigger mechanisms for
   cascading regeneration.

5. **A 12-phase roadmap** — every phase specifies objectives, deliverables, risks,
   dependencies, validation procedures, and all three output types (documentation,
   workbooks, recovery).

The deepest principle, unchanged from v4.0:

> Every state category, every metadata field, and every documentation artifact
> must be evaluated against: "Does this enable reconstruction from repository
> state after complete infrastructure loss?"

The Assessment Engine operationalises this principle. The Recovery Readiness Score
answers, continuously and numerically, whether the platform could reconstruct
itself today. When the answer is no, it says why. When the answer becomes yes,
it records when the threshold was first crossed and what changed to get there.
