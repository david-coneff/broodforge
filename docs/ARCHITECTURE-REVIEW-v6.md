# Architecture Review — v6.0
## Self-Documenting, Self-Recovering Infrastructure Platform

Date: 2026-05-31 15:57:35 UTC (2026-05-31 09:57:35 MDT)
Status: Proposed — supersedes v5.0
Replaces: docs/ARCHITECTURE-REVIEW-v5.md (retained for reference)

---

## 1. Review Mandate and Scope

This review was commissioned as a complete architectural reset, not an incremental
revision. The following instruction was explicit: do not patch the existing design.

The previous architecture (v5.0) produced a solid single-cell assessment and
documentation engine. This review evaluates whether that foundation can evolve into
a self-building, self-understanding, self-documenting, and self-recovering platform
incorporating k3s, GitOps, and a continuous improvement loop.

**New constraints added by this review:**
- k3s as the primary container orchestration platform
- GitOps as the deployment paradigm
- Four distinct intelligence phases (Bootstrap, Operational, Recovery, Execution)
- ODS workbooks as the machine-updatable execution record format
- Failure packages structured for LLM-assisted analysis
- A self-improvement loop from recovery failure to improved future recovery

---

## 2. What the Previous Architecture Got Right

These decisions are retained without modification.

**The cell/federation model is correct.** An Infrastructure Cell as the primary
recoverable unit generalises cleanly to multi-node k3s. A k3s cluster is a cell.
The federation model handles relationships between cells.

**Metadata-driven design is correct.** Infrastructure intent declared in versioned
YAML files, never in documentation. This review strengthens and formalises the
metadata hierarchy.

**The assessment/documentation separation is correct.** Observed state (what is)
versus declared state (what should be) versus generated artifacts (derived outputs).
This three-way distinction survives the architectural revision intact.

**The secret reference model is correct.** Secret Registry tracks KeePass paths,
never values. Extended in this revision to cover k3s secrets and GitOps credentials.

**ODS as the workbook format is correct.** This review formalises ODS as the
standard for all machine-updatable execution records across all phases.

**The naming convention is correct.** `YYYY-MM-DD_HH_MM_SS` with `_{hash}` for
files; `YYYY-MM-DD HH:MM:SS UTC (local)` for document display. Applied consistently.

---

## 3. What the Previous Architecture Got Wrong or Left Incomplete

**Wrong: Podman/Docker as the application runtime.**
Podman is fine for pre-k3s bootstrap VMs. It is insufficient as a long-term
application platform. It provides no scheduling, no automatic failover, no
replication, no HA, and no standard workload definition format. k3s resolves all of
these without the operational overhead of full Kubernetes.

**Wrong: No clear separation between bootstrap and operational concerns.**
The previous architecture conflated provisioning intelligence (what to build) with
operational intelligence (what is running). This becomes acutely important with
k3s: the systems that exist before the cluster exists are fundamentally different
from the systems that run on the cluster.

**Wrong: Documentation as a VM-level concern.**
Running the documentation engine as a Podman container on a single VM creates a SPOF
and prevents the engine from consuming Kubernetes APIs. The documentation engine must
be a k3s workload to observe the full infrastructure.

**Missing: GitOps.**
The previous architecture assumed direct Ansible application. GitOps (continuous
reconciliation from Git) is a better long-term model: all desired state is declared
in Git, a GitOps agent applies it, and divergence is detected and corrected
automatically. This also gives the documentation engine a clean API to query.

**Missing: The self-improvement loop.**
The previous architecture had no mechanism for recovery failures to feed back into
improved future recovery. This is the most important missing capability.

**Missing: k3s-level intelligence.**
No assessment, no recovery documentation, and no reconstruction playbooks for the
k3s layer. Node failures, pod disruptions, persistent volume failures, and cluster
control plane failures are all unaddressed.

---

## 4. Verdict

**The platform should evolve into a four-phase intelligence system built on:**
- Proxmox (hypervisor and VM infrastructure only)
- k3s (all application workloads)
- Flux CD (GitOps engine)
- Forgejo (single Git provider, hosted on k3s)
- Documentation engine (first k3s workload, before all user services)
- ODS workbooks (machine-updatable human-readable execution records)

The previous assessment engine framework is retained as Phase A (Bootstrap
Intelligence) and extended through Phases B, C, and D.

---

## 5. The Four Intelligence Phases

### Phase A — Bootstrap Intelligence
**Purpose:** Build the first-ever environment from bare metal.
**Assumes:** No documentation, no Kubernetes, no GitOps, no recovery package.
**Only:** Bare metal + Proxmox installation + bootstrap repository + human operator.
**Answers:** What hardware exists? What resources exist? What should be built?
**Produces:** Provisioned Proxmox cluster with k3s ready to deploy.
**Runtime:** Pre-k3s. Runs on the operator's machine or the Proxmox host itself.

### Phase B — Operational Intelligence
**Purpose:** Understand and document a running environment continuously.
**Assumes:** k3s running, GitOps active, documentation engine deployed.
**Answers:** What exists? Why does it exist? What changed? What depends on what?
**Produces:** Living inventory, architecture documentation, dependency maps,
             service maps, topology diagrams, drift reports.
**Runtime:** k3s workload. Runs on schedule and on-event.

### Phase C — Recovery Intelligence
**Purpose:** Generate recovery knowledge from operational understanding.
**Answers:** What must be restored? What can be recreated? In what order?
**Produces:** Recovery documentation, recovery procedures, recovery validation
             plans, recovery checkpoints, recovery readiness scores.
**Runtime:** k3s workload. Triggered by Phase B on change and on schedule.

### Phase D — Execution Intelligence
**Purpose:** Generate and execute recovery workflows.
**Answers:** How can recovery be automated? How is progress tracked? How do failures
            improve future attempts?
**Produces:** Recovery scripts, validation scripts, ODS workbooks (machine-updated),
             progress tracking, failure analysis packages, improved bootstrap state.
**Runtime:** Both k3s workload (generation) and standalone scripts (execution,
            because execution runs when the cluster may not exist).

---

## 6. k3s Architecture Decision

### Why k3s

k3s is chosen over Docker/Podman standalone for the following reasons:

**Scheduling:** k3s provides automatic workload scheduling across nodes. Podman
cannot reschedule a container if its host fails.

**Failover:** k3s detects node failures and restarts workloads on surviving nodes
automatically. This is not possible with Podman.

**Replication:** k3s natively expresses replica counts, rolling updates, and
health-based traffic routing. Podman has no equivalent.

**Standard workload definition:** Kubernetes manifests (Deployments, StatefulSets,
CronJobs, PersistentVolumeClaims) are industry-standard and portable. Compose files
are not.

**GitOps compatibility:** Flux CD and ArgoCD work natively with Kubernetes manifests.
There is no mature GitOps engine for Podman Compose.

**API surface:** The Kubernetes API provides a rich, queryable source of truth for
the documentation engine. Podman's API is limited and non-standard.

### k3s vs Full Kubernetes

k3s is chosen over full Kubernetes (RKE2, kubeadm) because:
- Single binary, no etcd dependency (uses embedded SQLite/etcd)
- Installs in seconds, not minutes
- Production-grade for homelab/private-cloud scale
- Handles single-node startup without modification
- Multi-node scaling by adding agents — no cluster upgrade required

### k3s vs Podman Purely

Podman is retained for one specific use case: the pre-k3s bootstrap VMs
(Forgejo, the initial automation VM) that must exist before k3s is deployed.
Once k3s exists, all new workloads go on k3s.

### Single-Node to Multi-Node Path

```
Phase 3: Single k3s server (control-plane + worker combined)
         Embedded SQLite, no HA
         Acceptable for initial deployment

Phase 9: Multi-node k3s with embedded etcd HA
         3 server nodes (control plane) + N agent nodes
         External load balancer for API server
         Longhorn for distributed persistent storage
```

### Alternatives Considered

| Option | Verdict | Reason |
|---|---|---|
| Docker Compose only | Rejected | No scheduling, failover, or HA |
| Podman + Quadlets | Rejected | Same limitations; no standard GitOps support |
| Full k8s (kubeadm) | Rejected | Operational overhead disproportionate to scale |
| RKE2 | Viable alternative | More complex than k3s; consider if STIG compliance required |
| MicroK8s | Viable alternative | Snap-based; less portable; good for Ubuntu-centric setups |
| k3s | **Selected** | Best fit for homelab scale, single-binary simplicity, production-grade |

---

## 7. GitOps Architecture Decision

### Why GitOps

Without GitOps, infrastructure and applications are applied imperatively (operator
runs Ansible, operator applies manifests). This creates drift: the running state
diverges from what Git describes, and nobody notices until something breaks.

GitOps inverts this: a GitOps agent continuously reconciles the running state to
match Git. Drift is detected and corrected automatically. Every change is a Git
commit. Rollback is `git revert`.

### Flux CD vs ArgoCD

**Flux CD is selected.** Reasons:

| Concern | Flux CD | ArgoCD |
|---|---|---|
| Bootstrapping | Can bootstrap itself into a new cluster | Requires a running cluster to install into |
| Resource usage | ~200MB RAM | ~500MB+ RAM |
| UI dependency | CLI-first; optional UI | UI is a core component |
| Multi-tenancy | Native via Kustomize + RBAC | More complex |
| Forgejo compatibility | Native Git source support | Native Git source support |
| FOSS | Yes (CNCF graduated) | Yes (CNCF incubating) |
| Recovery scenario | Flux can bootstrap from a Git repo on a fresh cluster | Requires ArgoCD to be deployed before it can reconcile |

The Flux bootstrapping advantage is critical for the recovery use case: on a fresh
cluster, a single `flux bootstrap` command pulls all state from Forgejo and
reconciles the cluster to its documented state.

### GitOps Source of Truth

```
Forgejo (self-hosted Git)
  └── platform-config/          GitOps declarations (Flux HelmReleases, Kustomizations)
  └── <app>-manifests/          Per-application Kubernetes manifests
  └── infrastructure-tofu/      OpenTofu workspace (Proxmox IaC)
  └── bootstrap/                Phase A bootstrap toolchain (this project)
  └── metadata/                 Infrastructure intent metadata (YAML)
  └── docs/                     Generated documentation outputs
  └── recovery-packages/        Generated recovery artifacts
```

### GitOps Workflow

```
Developer/Operator commits to Forgejo
    ↓
Flux CD detects change (polling or webhook)
    ↓
Flux applies manifest to k3s
    ↓
k3s reconciles running state
    ↓
Documentation engine detects change
    ↓
Updated documentation committed back to Forgejo
    ↓
Updated recovery package generated
```

---

## 8. Source of Truth Hierarchy

```
AUTHORITATIVE (changes drive everything else)
  Level 1 — Metadata YAML files (git-versioned intent declarations)
             What should exist, why, and under what policies.
             Never generated. Always human or tooling authored.

  Level 2 — Git repositories (declared state)
             OpenTofu workspaces, Kubernetes manifests, Ansible playbooks,
             Cloud-Init snippets, bootstrap-state.json.
             Authoritative for how things are built and configured.

  Level 3 — OpenTofu state (provisioned infrastructure state)
             What Proxmox VMs and resources actually exist and their IDs.
             Authoritative for the infrastructure layer.

  Level 4 — k3s / Kubernetes API (live running state)
             What pods, deployments, and services are actually running.
             Authoritative for the application layer.

DERIVED (generated from authoritative sources — never edited directly)
  Level 5 — Generated documentation
             Inventory, architecture docs, dependency maps, topology diagrams.
             Regenerated on change. Never the source of truth.

  Level 6 — Generated recovery packages
             Recovery scripts, runbooks, ODS workbooks.
             Regenerated on change. Used for execution, not for declaration.

  Level 7 — ODS workbook execution records
             Machine-updated at runtime. Records what happened during recovery.
             Not authoritative for state — authoritative for execution history.

DISPOSABLE (can be deleted and regenerated)
  Level 8 — Cached manifests, rendered templates, intermediate artifacts.
             Safe to delete. Will be regenerated.
```

**Key invariant:** Generated documentation (Level 5+) must never be edited
directly. All changes flow through Level 1–4 and are propagated downward.

### Required External Backups

| Artifact | Backup required | Reason |
|---|---|---|
| Metadata YAML files | Yes — external Git mirror | Primary source of intent |
| Bootstrap repository | Yes — external Git mirror | Required to rebuild from scratch |
| OpenTofu state | Yes — remote backend or encrypted archive | Required to manage existing infra |
| k3s persistent volumes | Yes — Velero + external storage | Application data |
| Generated docs/packages | No | Regenerated from authoritative sources |
| ODS execution records | Yes — for audit trail | Not regenerable after the fact |

---

## 9. Architecture Hierarchy (Revised)

```
Federation
└── Infrastructure Cell  [independently recoverable unit]
    └── Proxmox Cluster
        └── Proxmox Node(s)
            ├── Platform (Proxmox OS, networking, storage)
            ├── Infrastructure VMs (pre-k3s bootstrap services)
            │   ├── forgejo-vm        Git hosting (Forgejo)
            │   └── bootstrap-vm      Phase A toolchain runner
            └── k3s Cluster
                ├── Control Plane Node(s)
                │   └── k3s server (API, etcd, scheduler, controller)
                ├── Worker Node(s)
                │   └── k3s agent
                └── Workloads (Kubernetes namespaces)
                    ├── platform/           Core platform services
                    │   ├── flux-system     GitOps engine
                    │   ├── cert-manager    TLS certificate management
                    │   └── ingress-nginx   Ingress controller
                    ├── documentation/      Phase B/C/D intelligence
                    │   ├── doc-engine      Assessment + documentation generator
                    │   └── recovery-gen    Recovery package generator
                    ├── monitoring/         Observability
                    │   ├── prometheus
                    │   ├── grafana
                    │   └── loki
                    └── applications/       User workloads (after documentation)
                        ├── nextcloud
                        ├── immich
                        └── ...
```

---

## 10. Bootstrap Repository Structure

The bootstrap repository is the only external dependency required to rebuild
everything from nothing. It must be self-contained and offline-capable.

```
bootstrap/
├── README.md                    Entry point and operator guide
│
├── metadata/                    AUTHORITATIVE infrastructure intent
│   ├── cell-identity.yaml       Cell ID, federation membership, criticality
│   ├── hardware-profile.yaml    Declared hardware capabilities
│   ├── network-topology.yaml    Management network, VLANs, bridges
│   ├── vm-roles.yaml            Which VMs exist, their purpose, sizing
│   ├── k3s-cluster.yaml         Cluster topology, node roles, storage class
│   ├── service-catalog.yaml     What services exist and their dependencies
│   ├── backup-policy.yaml       RPO/RTO per service, backup destinations
│   └── recovery-priority.yaml   Recovery ordering and HA requirements
│
├── discovery/                   Phase A: hardware and environment discovery
│   ├── discover-hardware.sh     CPU, RAM, disk, NIC inventory
│   ├── discover-network.sh      Bridge detection, VLAN enumeration
│   ├── discover-storage.sh      ZFS pools, disk topology
│   ├── discover-proxmox.sh      Existing VMs, templates, backups
│   └── report-generator.py     Produces discovery-report.json
│
├── planners/                    Phase A: sizing and planning from discovery
│   ├── cluster-planner.py      k3s node count from RAM/CPU
│   ├── storage-planner.py      Pool topology from disk count/type
│   ├── network-planner.py      Bridge/VLAN plan from topology metadata
│   └── naming-planner.py      VM/service names from metadata conventions
│
├── generators/                  Phase A: generate IaC from plans + metadata
│   ├── tofu-vars/              Generated OpenTofu variable files
│   ├── cloud-init/             Generated Cloud-Init snippets (per VM)
│   ├── ansible-inventory/      Generated Ansible inventories
│   └── k3s-config/             Generated k3s server/agent configs
│
├── opentofu/                    Proxmox infrastructure-as-code
│   ├── modules/
│   │   ├── vm/                  VM resource module
│   │   ├── network/             Bridge and VLAN module
│   │   └── storage/             Pool and datastore module
│   ├── environments/
│   │   ├── bootstrap/           Phase A: Forgejo + bootstrap VMs
│   │   └── k3s-nodes/           Phase 3: k3s server + agent VMs
│   └── backend.tf               Remote state backend configuration
│
├── ansible/                     Configuration management
│   ├── inventory/               Generated inventories (from generators/)
│   ├── roles/
│   │   ├── common/              Base configuration, users, SSH, NTP
│   │   ├── proxmox-host/        Proxmox post-install configuration
│   │   ├── forgejo/             Forgejo installation and configuration
│   │   ├── k3s-server/          k3s server node setup
│   │   ├── k3s-agent/           k3s agent node setup
│   │   └── flux-bootstrap/      Flux CD initial bootstrap
│   └── playbooks/
│       ├── 00-preflight.yaml    Connectivity and prerequisite checks
│       ├── 01-proxmox.yaml      Proxmox host configuration
│       ├── 02-bootstrap-vms.yaml Forgejo + bootstrap VM setup
│       ├── 03-k3s-cluster.yaml  k3s cluster provisioning
│       └── 04-flux-bootstrap.yaml GitOps engine installation
│
├── cloud-init/                  Cloud-Init snippets (managed, generated)
│   ├── user-data/               Per-VM user-data (generated)
│   ├── network-config/          Per-VM network-config (generated)
│   └── vendor-data/             Proxmox vendor-data
│
├── validation/                  Pre-deployment checks
│   ├── capacity-check.py        Verifies hardware meets metadata requirements
│   ├── network-check.py         Validates network reachability
│   ├── dependency-check.py      Validates all declared dependencies resolvable
│   └── readiness-check.py       Produces deployment-readiness.json
│
├── recovery/                    Phase C/D: recovery artifacts and scripts
│   ├── packages/                Generated recovery-package.tar.gz (per cell)
│   ├── scripts/                 Generated executable recovery scripts
│   │   ├── recover-phase-01-proxmox.sh
│   │   ├── recover-phase-02-bootstrap-vms.sh
│   │   ├── recover-phase-03-k3s-cluster.sh
│   │   ├── recover-phase-04-gitops.sh
│   │   ├── recover-phase-05-platform-services.sh
│   │   ├── recover-phase-06-documentation.sh
│   │   └── recover-phase-07-applications.sh
│   ├── workbooks/               ODS workbooks (human + machine-updated)
│   └── validation/              Post-recovery validation scripts
│
├── workbooks/                   ODS workbook templates and generators
│   ├── templates/               ODS template files
│   ├── bootstrap-workbook.py    Phase A: bootstrap procedure workbook
│   ├── recovery-workbook.py     Phase D: recovery execution workbook
│   └── ods-updater.py           Machine update library (used by scripts)
│
├── docs/                        Generated documentation outputs
│   ├── architecture/
│   ├── inventory/
│   ├── dependency-maps/
│   ├── runbooks/
│   └── topology/
│
├── secrets/                     Secret registry (KeePass paths only)
│   └── secret-registry.yaml
│
├── init-bootstrap-state.py      Entry point: discovers + generates bootstrap-state.json
├── setup-secrets.py             KeePass integration + deploy key generation
├── setup-external-backup.py     GitHub/encrypted-archive external backup
├── generate-network-configs.py  Network-config snippet generator
├── generate-user-data.py        User-data snippet generator
├── suggest-names.py             Naming convention engine
├── roles.py                     VM role catalog + consolidation modes
└── backup.py                    Archive naming + encryption utilities
```

---

## 11. Bootstrap Intelligence Design

Phase A runs before any Kubernetes, before any GitOps. It is pure Python (stdlib
only) running on the operator's machine or the Proxmox host shell.

### Discovery Layer

```
discovery/discover-hardware.sh
  Collects: CPU model/cores/threads, RAM (total/ECC), disk inventory
            (model/serial/size/type/interface), NIC (model/ports/speed)
  Source:   /proc, lshw, dmidecode, smartctl, ip link
  Output:   discovery/hardware-report.json

discovery/discover-network.sh
  Collects: Bridges (name/ports/STP), VLANs, bonds, routes, DNS servers
  Source:   ip link, ip route, brctl, /etc/network/interfaces
  Output:   discovery/network-report.json

discovery/discover-storage.sh
  Collects: ZFS pools (topology/health/free), block devices, Proxmox datastores
  Source:   zpool list, zpool status, pvesm status, lsblk
  Output:   discovery/storage-report.json

discovery/discover-proxmox.sh
  Collects: Running VMs/CTs, templates, backups, current resource utilisation
  Source:   Proxmox API (pvesh), qm list, pct list
  Output:   discovery/proxmox-report.json
```

### Planner Layer

```
planners/cluster-planner.py
  Inputs:   hardware-report.json + metadata/k3s-cluster.yaml
  Logic:    total_ram → how many k3s nodes fit
            core_count → appropriate control-plane/worker split
            HA policy → single vs 3-server control plane threshold
  Output:   plans/cluster-plan.json

planners/storage-planner.py
  Inputs:   storage-report.json + metadata/hardware-profile.yaml
  Logic:    disk_count, disk_type → recommend ZFS topology
            (mirror for 2, raidz for 3-5, raidz2 for 6+)
  Output:   plans/storage-plan.json
```

### Generator Layer

```
generators/ reads plans/ + metadata/ and produces:
  tofu-vars/terraform.tfvars     VM sizing from cluster-plan.json
  cloud-init/<vm>.yaml           Per-VM snippets (via generate-user-data.py)
  cloud-init/network-<vm>.yaml   Per-VM network-config
  ansible-inventory/hosts.yaml   Ansible inventory from provisioned VMs
  k3s-config/server-config.yaml  k3s server configuration
  k3s-config/agent-config.yaml   k3s agent configuration
```

### Validation Layer

Before any deployment begins:

```
validation/capacity-check.py
  Verifies: metadata/vm-roles.yaml RAM requirements ≤ available RAM
            metadata/k3s-cluster.yaml disk requirements ≤ pool capacity
  Produces: validation/capacity-check-report.json

validation/readiness-check.py
  Verifies: All generated artifacts exist and validate against schemas
            Secret Registry entries complete for all required secrets
            Network topology reachable
  Produces: validation/readiness-report.json
  Gate:     Deployment does not proceed if readiness-report contains RED items
```

---

## 12. Minimum Viable Initial Deployment

**The first objective is not hosting applications. The first objective is
creating a self-documenting cluster.**

### Pre-k3s Infrastructure VMs (Phase A output)

```
forgejo-vm     (VM 100)  Forgejo Git hosting
               All repositories live here. Cannot be on k3s because k3s
               Git pulls FROM Forgejo. Forgejo must exist before k3s.
               RAM: 2GB minimum. Persistent volume on ZFS.

bootstrap-vm   (VM 101)  Phase A toolchain runner
               Runs: init-bootstrap-state.py, setup-secrets.py,
               generate-network-configs.py, generate-user-data.py
               Runs: ansible playbooks for k3s provisioning
               After k3s is operational: retained for emergency access
               RAM: 2GB. Ephemeral — can be recreated from bootstrap repo.
```

### Minimum k3s Cluster (Phase 3 output)

```
k3s-server-01  (VM 110)  Single k3s server (control plane + worker combined)
               RAM: 4GB minimum (2GB for control plane, 2GB for workloads)
               Embedded SQLite (no HA — acceptable for initial deployment)
               Storage: local-path provisioner initially, Longhorn after Phase 9

Total minimum VM count: 3
Total minimum RAM: 8GB
Total minimum vCPUs: 6
```

### First k3s Workloads (in order — Phase 4)

```
1. cert-manager          (platform namespace)   TLS for all services
2. ingress-nginx         (platform namespace)   HTTP routing
3. flux-system           (flux-system namespace) GitOps engine
4. doc-engine            (documentation namespace) Phase B/C intelligence
5. prometheus + grafana  (monitoring namespace)  Observability
   --- GATE: documentation system must be running before any user services ---
6. nextcloud, immich, etc. (applications namespace) User workloads
```

**Why documentation before monitoring?**
The documentation engine generates the recovery procedures. Without it, a failure
during application deployment cannot be recovered from reliably. The monitoring
stack is important but does not block recovery — the documentation system does.

---

## 13. Documentation Engine Architecture

The documentation engine is the first k3s workload. It runs as a CronJob (scheduled
assessment) and as a Deployment (always-on API for query).

### Inputs

```
Proxmox API          → VM inventory, resource utilisation, backup status
k3s API              → Pod inventory, deployment status, PVC status, events
OpenTofu state       → Declared infrastructure (from Forgejo remote backend)
Flux CD state        → GitOps reconciliation status, drift
Ansible inventory    → Configured state (from Forgejo bootstrap repo)
bootstrap-state.json → Declared intent (from Forgejo bootstrap repo)
metadata/ YAML files → Infrastructure intent and policies
Forgejo API          → Repository inventory, commit history
```

### Outputs

```
Generated documentation (committed to Forgejo docs/ repository):
  inventory.md              Complete infrastructure inventory
  architecture.md           Current architecture description
  dependency-map.md         Service dependency graph
  service-map.md            All services, ports, URLs, health status
  topology-diagram.yaml     Machine-readable topology (rendered to SVG)
  changelog.md              What changed since last assessment
  drift-report.md           Declared vs observed divergence

Recovery artifacts (committed to Forgejo recovery-packages/):
  recovery-package.tar.gz   Complete recovery package (Phase C output)
  recovery-workbook.ods     ODS workbook for recovery execution (Phase D output)
  readiness-report.ods      Recovery readiness scored by component
```

### Intent-Aware Documentation

Documentation must capture not only STATE but INTENT.

```yaml
# metadata/k3s-cluster.yaml — declares intent
control_plane:
  ha_policy: "single-node-until-3-physical-hosts"
  reason: "HA control plane requires etcd quorum; 3 servers needed"

# Documentation engine produces:
# "There is 1 control plane node (k3s-server-01).
#  Policy: single-node until 3 physical Proxmox hosts are available.
#  Reason: etcd quorum requires 3 server nodes.
#  Next threshold: add second Proxmox host to trigger 3-server upgrade."
```

Every generated documentation field includes:
- **What** exists (observed state)
- **Why** it exists (metadata policy reference)
- **Which metadata** created it (policy ID + version)

---

## 14. Recovery Package Design

### recovery-package.tar.gz

Generated by Phase C. Self-contained and offline-capable.

```
recovery-package-{cell_id}_{YYYY-MM-DD_HH_MM_SS}_{hash}.tar.gz
│
├── manifest.json              Package metadata: generation time, cell_id,
│                              schema version, contents inventory, checksums
│
├── metadata/                  Complete metadata/ directory snapshot
│   ├── cell-identity.yaml
│   ├── k3s-cluster.yaml
│   ├── service-catalog.yaml
│   └── ...
│
├── inventories/               Ansible inventories at time of generation
│   ├── hosts.yaml
│   └── group_vars/
│
├── topology/                  Infrastructure topology snapshots
│   ├── proxmox-inventory.json
│   ├── k3s-nodes.json
│   ├── k3s-workloads.json
│   └── dependency-graph.json
│
├── manifests/                 Kubernetes manifests (snapshot from GitOps repo)
│   └── (per-namespace manifests)
│
├── opentofu-state/            OpenTofu state snapshot
│   └── terraform.tfstate
│
├── runbooks/                  Markdown runbooks per recovery phase
│   ├── 00-pre-recovery-checklist.md
│   ├── 01-proxmox-restore.md
│   ├── 02-bootstrap-vms.md
│   ├── 03-k3s-cluster.md
│   ├── 04-gitops-restore.md
│   ├── 05-platform-services.md
│   ├── 06-documentation-engine.md
│   └── 07-applications.md
│
├── workbooks/                 ODS workbooks
│   ├── recovery-workbook.ods      Master recovery execution workbook
│   └── readiness-report.ods       Pre-recovery readiness scores
│
├── scripts/                   Executable recovery scripts
│   ├── recover-phase-01-proxmox.sh
│   ├── recover-phase-02-bootstrap-vms.sh
│   ├── recover-phase-03-k3s.sh
│   ├── recover-phase-04-gitops.sh
│   ├── recover-phase-05-platform.sh
│   ├── recover-phase-06-docs.sh
│   ├── recover-phase-07-apps.sh
│   ├── run-all.sh                  Orchestrated full recovery
│   └── lib/
│       ├── checkpoint.sh           Checkpoint tracking functions
│       ├── validation.sh           Post-step validation functions
│       ├── ods-update.sh           ODS workbook update functions
│       └── failure-package.sh      Failure package generation
│
├── validation/                Post-recovery validation scripts
│   ├── validate-proxmox.sh
│   ├── validate-k3s.sh
│   ├── validate-gitops.sh
│   └── validate-applications.sh
│
├── logs/                      Empty at generation — populated during recovery
└── secrets-registry.yaml      KeePass path references (not values)
```

---

## 15. Executable Recovery Design

### Recovery Script Structure

All recovery scripts share a common structure:

```bash
#!/bin/bash
# recover-phase-03-k3s.sh — Phase 3: k3s cluster restoration
# Part of recovery-package for cell: {cell_id}
# Generated: {YYYY-MM-DD_HH_MM_SS UTC}
# Recovery package: {package_filename}

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/checkpoint.sh"
source "$SCRIPT_DIR/lib/validation.sh"
source "$SCRIPT_DIR/lib/ods-update.sh"
source "$SCRIPT_DIR/lib/failure-package.sh"

PHASE="03-k3s"
WORKBOOK="$SCRIPT_DIR/../workbooks/recovery-workbook.ods"
LOG_FILE="$SCRIPT_DIR/../logs/phase-03-$(date -u +%Y-%m-%d_%H_%M_%S).log"

# Redirect all output to log
exec > >(tee -a "$LOG_FILE") 2>&1

checkpoint_start "$PHASE" "k3s Cluster Recovery"
ods_update_phase_start "$WORKBOOK" "$PHASE"

# ─── Step 1: Verify prerequisites ──────────────────────────────────
checkpoint_step "$PHASE" "01-prereq" "Verifying prerequisites"
ods_update_step "$WORKBOOK" "$PHASE" "01-prereq" "IN_PROGRESS"

validate_proxmox_api || {
    failure_package_generate "$PHASE" "01-prereq" "Proxmox API unreachable"
    ods_update_step "$WORKBOOK" "$PHASE" "01-prereq" "FAILED"
    exit 1
}

ods_update_step "$WORKBOOK" "$PHASE" "01-prereq" "PASSED"
checkpoint_complete "$PHASE" "01-prereq"

# ─── Step 2: Deploy k3s server VM ──────────────────────────────────
checkpoint_step "$PHASE" "02-deploy-vm" "Deploying k3s-server-01 VM"
ods_update_step "$WORKBOOK" "$PHASE" "02-deploy-vm" "IN_PROGRESS"

cd "$SCRIPT_DIR/../../opentofu/environments/k3s-nodes"
tofu init && tofu apply -auto-approve || {
    failure_package_generate "$PHASE" "02-deploy-vm" "OpenTofu apply failed"
    ods_update_step "$WORKBOOK" "$PHASE" "02-deploy-vm" "FAILED"
    exit 1
}

ods_update_step "$WORKBOOK" "$PHASE" "02-deploy-vm" "PASSED"
checkpoint_complete "$PHASE" "02-deploy-vm"

# ... (additional steps follow same pattern)

checkpoint_phase_complete "$PHASE"
ods_update_phase_complete "$WORKBOOK" "$PHASE"
echo "Phase 03 complete. Proceed to: recover-phase-04-gitops.sh"
```

### Checkpoint System

```bash
# lib/checkpoint.sh
# Checkpoints are stored as files in logs/checkpoints/
# Recovery can resume from the last successful checkpoint

checkpoint_start() {
    local phase="$1" label="$2"
    mkdir -p "$SCRIPT_DIR/../logs/checkpoints"
    echo "{\"phase\":\"$phase\",\"label\":\"$label\",\"started\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" \
        > "$SCRIPT_DIR/../logs/checkpoints/$phase.start"
}

checkpoint_complete() {
    local phase="$1" step="$2"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        > "$SCRIPT_DIR/../logs/checkpoints/$phase-$step.done"
}

is_checkpoint_done() {
    local phase="$1" step="$2"
    [[ -f "$SCRIPT_DIR/../logs/checkpoints/$phase-$step.done" ]]
}
```

Recovery scripts check `is_checkpoint_done` before each step and skip completed
steps. This makes recovery **resumable**: if a script fails mid-way, re-running it
skips everything that already succeeded.

---

## 16. ODS Workbook Design

ODS (OpenDocument Spreadsheet) is the standard format for all machine-updatable
execution records. It is human-readable in LibreOffice and machine-writable via
the stdlib `zipfile` + XML approach already implemented in this project.

### Recovery Workbook Sheet Structure

```
Sheet 1: Overview
  Cell B1: Cell ID
  Cell B2: Recovery package timestamp
  Cell B3: Overall recovery status (PENDING / IN_PROGRESS / COMPLETE / FAILED)
  Cell B4: Current phase
  Cell B5: Operator name
  Cell B6: Recovery start time
  Table: Phase status summary (phase, status, start, end, duration)

Sheet 2: Phase-N (one sheet per recovery phase)
  Column A: Step ID
  Column B: Step description
  Column C: Status (PENDING / IN_PROGRESS / PASSED / FAILED / SKIPPED)
  Column D: Start timestamp
  Column E: End timestamp
  Column F: Notes / error message
  Column G: Validation result

Sheet 3: Validation
  All post-recovery validation results
  Column A: Check name
  Column B: Expected
  Column C: Actual
  Column D: Result (PASS / FAIL)
  Column E: Notes

Sheet 4: Failure Log
  Any failures encountered
  Column A: Timestamp
  Column B: Phase
  Column C: Step
  Column D: Error type
  Column E: Error message
  Column F: Failure package path

Sheet 5: Readiness (pre-recovery assessment)
  Component readiness scores from Phase C
  One row per component with score, gaps, blockers
```

### Machine Update Protocol

```python
# lib/ods_updater.py (used by recovery scripts via shell wrapper)
# Updates specific cells in an ODS file without opening LibreOffice

def update_step_status(ods_path: str, phase: str, step: str,
                       status: str, notes: str = "") -> None:
    """Update a step's status cell in the recovery workbook."""
    # ... stdlib zipfile + XML manipulation
    # Same approach as existing workbook.py renderer

def update_phase_complete(ods_path: str, phase: str,
                          end_time: str, duration_seconds: int) -> None:
    """Mark a phase as complete and record timing."""
```

---

## 17. Failure Analysis Package Design

When any recovery step fails, the failure package is generated automatically by
`lib/failure-package.sh` before the script exits.

### failure-package.tar.gz

```
failure-package-{cell_id}_{phase}_{step}_{YYYY-MM-DD_HH_MM_SS}_{hash}.tar.gz
│
├── summary.md                 Structured failure summary (LLM-optimised)
├── execution-history.md       Timeline of all steps attempted
│
├── context/
│   ├── cell-identity.yaml     What cell this is
│   ├── recovery-phase.txt     Which phase failed
│   ├── step.txt               Which step failed
│   ├── manifest.json          Recovery package metadata
│   └── workbook-state.ods     ODS workbook at time of failure
│
├── logs/
│   ├── script-stdout.log      Full script output
│   ├── script-stderr.log      Error output
│   ├── proxmox-tasks.json     Recent Proxmox task log
│   ├── tofu-log.txt           OpenTofu output if applicable
│   ├── ansible-log.txt        Ansible output if applicable
│   └── k3s-events.json        kubectl get events --all-namespaces
│
├── system/
│   ├── df.txt                 Disk usage
│   ├── free.txt               Memory usage
│   ├── ip-route.txt           Network routes
│   └── proxmox-status.txt     pveversion + pvecm status
│
└── validation-failures/
    └── (output of whichever validation script failed)
```

### summary.md Structure

The summary is specifically structured for LLM submission:

```markdown
# Recovery Failure Summary

**Cell:** {cell_id}
**Phase:** {phase} — {phase_label}
**Step:** {step_id} — {step_label}
**Timestamp:** {YYYY-MM-DD HH:MM:SS UTC}
**Recovery Package:** {package_filename}

## What Was Being Attempted
{One paragraph description of this recovery step}

## What Failed
{Exact error message or last 50 lines of stderr}

## System State at Failure
- Proxmox API: {reachable/unreachable}
- k3s API: {reachable/unreachable/not-yet-deployed}
- Last successful checkpoint: {phase}-{step}
- Workbook phase status: {status}

## Preceding Steps (completed successfully)
{Bulleted list of completed steps before failure}

## Relevant Log Excerpt
```
{Last 100 lines of script output}
```

## Attached Files
- script-stdout.log, script-stderr.log
- proxmox-tasks.json
- k3s-events.json (if k3s exists)
- workbook-state.ods

## Suggested LLM Prompt
"The following recovery script failed at step {step_id}.
 The error was: {error_summary}.
 The system state is described above.
 Please analyze the likely cause and suggest remediation steps."
```

---

## 18. Self-Improvement Loop

```
Recovery Attempt (Phase D)
    │
    ▼
Failure Detected
    │
    ├── failure-package.sh runs automatically
    │   └── failure-package.tar.gz generated
    │
    ▼
Human + LLM Analysis
    │   Human downloads failure package
    │   Submits summary.md + logs to LLM
    │   Identifies root cause
    │
    ▼
Bootstrap Repository Updated
    │   Root cause fix committed to bootstrap/
    │   Options:
    │     metadata/ updated (policy changed)
    │     scripts/ updated (step logic fixed)
    │     validation/ updated (better pre-checks)
    │     recovery/scripts/ updated (improved recovery step)
    │
    ▼
Recovery Package Regenerated
    │   Documentation engine (Phase C) regenerates package
    │   New package includes improved scripts
    │
    ▼
Future Recovery Uses Improved Scripts
```

**Key mechanism:** Recovery scripts are generated from templates + metadata.
Fixing the template or the metadata fixes all future recovery packages. The
failure package provides enough context for the fix to be precise.

**Long-term:** As failure packages accumulate, patterns emerge. Common failure
modes can be pre-empted by improved validation (Phase A readiness checks) before
the next recovery attempt.

---

## 19. Backup Strategy

### RESTORE vs RECREATE distinction

| Layer | Strategy | Method |
|---|---|---|
| Proxmox host | **RESTORE** from PBS backup | `qmrestore` or ISO + playbook |
| Forgejo VM | **RESTORE** data + **RECREATE** app | PBS backup for data volume; Ansible for app |
| k3s server VM | **RECREATE** | OpenTofu + Ansible; stateless node |
| k3s etcd state | **RESTORE** if HA; **RECREATE** via GitOps if not | `etcdctl snapshot restore` or Flux reconcile |
| k3s PVCs (app data) | **RESTORE** | Velero backup to external storage |
| k3s manifests | **RECREATE** | Flux GitOps pulls from Forgejo and applies |
| OpenTofu state | **RESTORE** | Remote backend (Forgejo-hosted HTTP backend) |
| Metadata YAML | **RECREATE** | Lives in Forgejo; restored when Forgejo is restored |
| Generated docs | **RECREATE** | Documentation engine regenerates on demand |
| Recovery packages | **RECREATE** | Phase C regenerates from metadata + state |
| ODS execution records | **RESTORE** | External backup — audit trail, not regenerable |

### Backup Layers

```
Layer 1 — Proxmox PBS (VM-level)
  Coverage: All VMs (Forgejo, bootstrap-vm, k3s nodes)
  Schedule: Daily VM snapshots
  Retention: 7 daily, 4 weekly
  Offsite:   rclone sync to cloud storage (naming convention from backup.py)

Layer 2 — Velero (Kubernetes PVC-level)
  Coverage: All k3s PersistentVolumeClaims
  Schedule: Daily
  Destination: S3-compatible storage (MinIO on Forgejo VM, or external)
  Retention: 14 daily

Layer 3 — Git mirrors (repository-level)
  Coverage: All Forgejo repositories
  Method:   git bundle / Forgejo API export
  Schedule: Daily push to external Git provider (GitHub, Codeberg)
  Format:   Each repo as a timestamped bundle

Layer 4 — OpenTofu state (state-level)
  Coverage: terraform.tfstate for all workspaces
  Method:   Remote backend on Forgejo (HTTP backend)
            Backed up as part of Layer 1 (Forgejo VM)

Layer 5 — Encrypted config archive (bootstrap-level)
  Coverage: bootstrap-state.json, secret-registry.yaml, generated configs
  Method:   setup-external-backup.py (GPG encrypted, timestamped)
  Destination: Cloud storage (rclone)
  Schedule: After each significant change + nightly
```

---

## 20. Architecture Risks and Weak Points

### Risk 1 — Forgejo as a pre-k3s VM creates a SPOF
**Severity:** HIGH
**Problem:** Forgejo must exist before k3s. If the Forgejo VM fails catastrophically
and PBS backup is unavailable, the entire GitOps system is inaccessible.
**Mitigation:**
- Forgejo VM is backed up by PBS (daily + weekly)
- Forgejo repositories are mirrored to external Git providers daily
- On recovery, Forgejo VM is restored from PBS or recreated from Ansible + data restore
- Recovery scripts do NOT depend on Forgejo being reachable — they embed required
  manifests and configurations in the recovery package at generation time
- **Critical design rule:** The recovery package must be self-contained and must NOT
  require Forgejo to be online to execute Phase 1–4.

### Risk 2 — Circular dependency: documentation engine needs k3s, k3s needs documentation
**Severity:** MEDIUM
**Problem:** The documentation engine (Phase B) runs on k3s. But until k3s exists,
no documentation is generated. Phase A (bootstrap intelligence) must produce
sufficient documentation to enable Phase 3 (k3s deployment) without Phase B.
**Mitigation:**
- Phase A generates a bootstrap-report.json (hardware/network/plan) without k3s
- Phase A generates bootstrap runbooks (the existing doc-gen --mode bootstrap)
- Phase B documentation is enhanced once k3s is running
- There is no circular dependency — Phase A → Phase 3 → Phase B is sequential

### Risk 3 — k3s adds complexity before value is delivered
**Severity:** MEDIUM
**Problem:** k3s introduces etcd, kube-apiserver, CNI, CSI, and ingress before any
user workload runs. This is significant complexity for a homelab.
**Mitigation:**
- k3s with embedded SQLite (initial phase) is simpler than it appears
- Single binary, single service, single command to install
- The documentation engine is the first workload — immediate value
- Multi-node HA is deferred to Phase 9 — not required initially
- If operator preference is simplicity, Phase 6 applications can be deferred
  indefinitely while the self-documenting system still delivers full value

### Risk 4 — Flux CD bootstrapping requires Forgejo to be reachable
**Severity:** MEDIUM
**Problem:** `flux bootstrap` requires Git to be reachable. If Forgejo is not yet
restored when Phase 4 (GitOps) runs, Flux cannot bootstrap.
**Mitigation:**
- Recovery scripts explicitly enforce ordering: Forgejo restored before Flux bootstrap
- Checkpoint system prevents Phase 4 from running until Phase 2 (Forgejo) is verified
- If Forgejo is permanently lost: temporary bootstrap from external Git mirror
  (GitHub), then migrate back to Forgejo once it is restored

### Risk 5 — ODS machine-update complexity
**Severity:** LOW
**Problem:** Updating ODS files from shell scripts requires Python + stdlib zipfile
manipulation. This is non-trivial and may produce corrupted files if not careful.
**Mitigation:**
- `ods-update.sh` wraps `ods_updater.py` which uses the existing workbook.py approach
- ODS updates are append-only (status columns) — minimal manipulation
- Workbook is backed up before each update; failures roll back to backup
- Recovery can proceed without workbook updates if ODS update fails — it logs to file

### Risk 6 — LLM-optimised failure packages may not be consumed
**Severity:** LOW
**Problem:** Failure packages are only useful if the operator actually submits them
for analysis. If the operator ignores them, the self-improvement loop is broken.
**Mitigation:**
- Phase D generates a summary.md that is immediately readable without LLM
- The failure package filename appears in the recovery workbook — hard to ignore
- Long-term: a monitoring alert triggers when failure packages accumulate without
  corresponding bootstrap repository commits (indicating unaddressed failures)

### Risk 7 — Single-node k3s has no failover
**Severity:** MEDIUM
**Problem:** Phase 3 deploys a single-node k3s. If that VM fails, all k3s workloads
go down — including the documentation engine.
**Mitigation:**
- The most recent recovery package is stored externally (not just in k3s)
- Recovery package is regenerated daily and pushed to Forgejo + external backup
- Single-node k3s is explicitly documented as non-HA; Phase 9 adds multi-node
- If documentation engine is down, the last recovery package is still usable

---

## 21. Architecture Decision Records — v6.0

### AD-022: k3s as primary application platform
k3s replaces Podman/Docker as the runtime for all application workloads. Podman
is retained only for pre-k3s bootstrap VMs (Forgejo, bootstrap-vm).

### AD-023: Flux CD as GitOps engine
Flux CD is selected over ArgoCD. Primary reason: Flux can bootstrap itself into a
fresh cluster from a Git repository — critical for the recovery use case.

### AD-024: Forgejo as the sole Git provider
All repositories (infrastructure, bootstrap, configuration, manifests, documentation)
live on the self-hosted Forgejo instance. External Git providers (GitHub) are used
only as mirrors for disaster recovery — not as primary sources.

### AD-025: ODS as the standard workbook format
All machine-updatable execution records use ODS format. Recovery scripts update ODS
workbooks in real-time using the existing stdlib zipfile + XML approach. ODS is
both human-readable (LibreOffice) and machine-writable (no external dependencies).

### AD-026: Metadata YAML as the primary source of infrastructure intent
Infrastructure intent (what should exist, why, under what policy) is declared in
versioned YAML files in the metadata/ directory. Documentation and recovery artifacts
are generated FROM metadata. Generated artifacts never become the source of truth.

### AD-027: Four intelligence phases with distinct runtimes
Phase A (Bootstrap) runs before k3s exists. Phases B/C/D run as k3s workloads.
This separation is enforced architecturally: Phase A tools are stdlib-only Python;
Phases B/C/D are containerised services. Never conflate pre-k3s and post-k3s concerns.

### AD-028: Documentation engine is the first k3s workload
No user service (Nextcloud, Immich, media, monitoring) is deployed before the
documentation engine is running and has generated its first recovery package. The
cluster must understand itself before it hosts anything.

### AD-029: Recovery packages are self-contained and offline-capable
A recovery package must work without internet access and without Forgejo being
reachable. It embeds everything required for Phases 1–4 of recovery. Only Phase 4+
(GitOps) requires Forgejo; the package contains manifests for emergency offline use.

### AD-030: Failure packages are structured for LLM analysis
When a recovery step fails, a structured failure package is generated automatically.
The package includes a summary.md with an embedded suggested LLM prompt. The
self-improvement loop depends on this package being actionable without deep
operator expertise.

### AD-031: Documentation captures STATE and INTENT
Every significant documentation field includes: what exists, why it exists, and
which metadata policy created it. Intent-aware documentation is the difference
between "3 control plane nodes" and "3 control plane nodes because HA policy
requires quorum once multiple physical hosts exist."

---

## 22. Phased Implementation Roadmap

### Phase 0 — Architecture and Metadata Design

**Objective:** Define the metadata schema and bootstrap repository structure before
any code is written or any infrastructure is deployed.

**Deliverables:**
- metadata/ YAML schemas (cell-identity, hardware-profile, network-topology,
  vm-roles, k3s-cluster, service-catalog, backup-policy, recovery-priority)
- Bootstrap repository structure (all directories created, README authored)
- Source of truth hierarchy documented and agreed
- Architecture decision records (AD-022 through AD-031)
- External backup strategy confirmed (provider, schedule, retention)

**Risks:** Metadata schema gaps discovered later require regenerating all artifacts.
**Validation:** All metadata schemas validate against JSON Schema; README produces a
working deployment when followed by a new operator.
**Documentation outputs:** ARCHITECTURE.md (v6.0), ROADMAP.md (v6.0), metadata schemas
**Recovery outputs:** None yet
**Workbook outputs:** None yet

---

### Phase 1 — Bootstrap Intelligence Framework

**Objective:** Implement the Phase A discovery, planning, generation, and validation
pipeline that runs before any VM is provisioned.

**Deliverables:**
- discovery/ scripts (hardware, network, storage, Proxmox)
- planners/ (cluster-planner, storage-planner, network-planner, naming-planner)
- generators/ (OpenTofu vars, Cloud-Init, Ansible inventory, k3s config)
- validation/ (capacity, network, dependency, readiness checks)
- Extend existing init-bootstrap-state.py to consume discovery reports
- Extend existing suggest-names.py with k3s naming conventions
- Tests: 50+ covering discovery→plan→generate→validate pipeline

**Risks:** Discovery scripts miss edge cases (unusual hardware, non-standard Proxmox
config). Validation is too strict and blocks valid configurations.
**Dependencies:** Phase 0 metadata schemas
**Validation:** Run full pipeline on bare metal; readiness-report.json shows GREEN
**Documentation outputs:** bootstrap-discovery-report.md, hardware-profile.md
**Recovery outputs:** None yet (no infrastructure to recover)
**Workbook outputs:** Bootstrap planning workbook (ODS)

---

### Phase 2 — Proxmox Automation

**Objective:** Fully automate Proxmox host post-install configuration and pre-k3s
VM provisioning using OpenTofu + Ansible.

**Deliverables:**
- OpenTofu modules: vm/, network/, storage/
- OpenTofu environment: bootstrap/ (Forgejo VM + bootstrap-vm)
- Ansible roles: common, proxmox-host, forgejo, k3s-server, k3s-agent
- Ansible playbooks: 00-preflight through 02-bootstrap-vms
- Forgejo deployed, operational, all repositories imported
- bootstrap-state.json validated and pushed to Forgejo
- External backup configured and tested

**Risks:** Proxmox API incompatibility between versions. Network topology mismatch
between declared and actual hardware.
**Dependencies:** Phase 1 (bootstrap intelligence, generators)
**Validation:** Forgejo accessible; all repositories cloned; backup tested
**Documentation outputs:** Proxmox inventory, network topology map
**Recovery outputs:** recover-phase-01-proxmox.sh, recover-phase-02-bootstrap-vms.sh
**Workbook outputs:** Bootstrap workbook (ODS) with Phase 1-2 steps completed

---

### Phase 3 — Initial k3s Deployment

**Objective:** Deploy a single-node k3s cluster, install core platform services,
and verify the cluster is operational.

**Deliverables:**
- OpenTofu environment: k3s-nodes/ (k3s-server-01 VM)
- Ansible role: k3s-server (single-node, embedded SQLite)
- Ansible playbook: 03-k3s-cluster
- Core platform services deployed:
  - cert-manager
  - ingress-nginx
  - local-path-provisioner
- All services healthy; Kubernetes API accessible
- Flux CD installed (pre-GitOps — manual kubectl apply at this stage)

**Risks:** k3s networking conflicts with Proxmox host networking. Storage class not
compatible with workload PVC requirements.
**Dependencies:** Phase 2 (Proxmox automation, Forgejo operational)
**Validation:** `kubectl get nodes` shows Ready; cert-manager issues test certificate;
ingress returns 200 for health endpoint.
**Documentation outputs:** k3s cluster topology, node inventory
**Recovery outputs:** recover-phase-03-k3s.sh
**Workbook outputs:** k3s deployment workbook (ODS)

---

### Phase 4 — Documentation Engine

**Objective:** Deploy the documentation engine as the first k3s workload. The
cluster must understand itself before hosting user services.

**Deliverables:**
- Documentation engine containerised (from existing doc-gen codebase)
- Kubernetes manifests: Deployment + CronJob + ConfigMap + Service
- Assessment collectors: Proxmox API, k3s API, OpenTofu state, Git repos
- Generated outputs: inventory, architecture, dependency map, service map
- First recovery package generated and pushed to Forgejo + external backup
- ODS readiness workbook generated

**Risks:** Proxmox API credentials not available inside k3s. Documentation engine
produces incomplete output if bootstrap-state.json is not yet fully populated.
**Dependencies:** Phase 3 (k3s operational), Phase 2 (Forgejo operational)
**Validation:** Documentation engine generates complete inventory; recovery package
validated against schema; ODS workbook opens in LibreOffice without errors.
**Documentation outputs:** ALL documentation types (inventory, architecture, dependency
map, service map, topology, runbooks)
**Recovery outputs:** First complete recovery-package.tar.gz; all Phase 1–4 scripts
**Workbook outputs:** recovery-workbook.ods, readiness-report.ods

---

### Phase 5 — GitOps Integration

**Objective:** Transition from manual manifest application to Flux CD continuous
reconciliation. All infrastructure state managed through Git.

**Deliverables:**
- Forgejo repositories restructured for GitOps:
  - platform-config/ (Flux HelmReleases and Kustomizations)
  - Each application gets its own manifests repository
- Flux CD bootstrapped against Forgejo platform-config/
- All Phase 3/4 services converted to Flux-managed HelmReleases
- Deployment workflow: commit to Forgejo → Flux applies → doc engine detects → docs updated
- Drift detection: Flux alerts on reconciliation failures
- Flux CD webhook configured to trigger documentation engine on change

**Risks:** Flux reconciliation loop conflicts with manually applied manifests.
Forgejo webhook reliability.
**Dependencies:** Phase 4 (documentation engine), Phase 3 (k3s operational)
**Validation:** Commit a change to platform-config/; verify Flux applies it within
60 seconds; verify documentation engine generates updated docs within 5 minutes.
**Documentation outputs:** GitOps workflow diagram, repository dependency map
**Recovery outputs:** recover-phase-04-gitops.sh updated with Flux bootstrap commands
**Workbook outputs:** Updated recovery workbook with GitOps restoration steps

---

### Phase 6 — Application Platform

**Objective:** Deploy user services using GitOps. Documentation engine runs before
any user service is deployed.

**Deployment order enforced by Flux dependency graph:**
```
1. monitoring/ (Prometheus, Grafana, Loki)
2. storage/ (if Longhorn needed for multi-VM PVCs)
3. applications/
   - nextcloud
   - immich
   - jellyfin
   - additional user services
```

**Deliverables:**
- Per-application manifest repositories in Forgejo
- Flux HelmReleases for each application
- Per-application service contracts (YAML, in metadata/)
- Documentation engine extended to document application layer
- Recovery procedures extended for each application

**Risks:** Applications have stateful data that increases recovery complexity. PVC
storage class selection affects backup strategy.
**Dependencies:** Phase 5 (GitOps), Phase 4 (documentation engine generating app docs)
**Validation:** All applications healthy per Kubernetes health checks; documentation
engine generates service map including all applications.
**Documentation outputs:** Application service map, dependency graph updated
**Recovery outputs:** recover-phase-07-applications.sh; per-application recovery runbooks
**Workbook outputs:** Per-application recovery workbook sheets

---

### Phase 7 — Recovery Artifact Generation

**Objective:** Automate complete recovery package generation and validation.

**Deliverables:**
- Phase C intelligence fully implemented:
  - Dependency graph analysis
  - Recovery ordering algorithm
  - Readiness scoring (from existing readiness.py, extended to k3s layer)
  - Gap detection (missing backups, missing secrets, missing metadata)
- Recovery package generator (Python, runs as k3s CronJob)
- All script templates implemented and tested against a test environment
- ODS workbook generator fully implemented
- Recovery package validation script (validates package schema + script syntax)
- External backup of recovery packages configured

**Risks:** Recovery scripts have untested assumptions that are only discovered during
an actual recovery. Script syntax errors discovered too late.
**Dependencies:** Phase 6 (all services for which recovery is generated), Phase 4
(documentation engine)
**Validation:** Full recovery package passes validation script; scripts pass shellcheck;
all referenced KeePass paths verified in secret registry; ODS workbook opens correctly.
**Documentation outputs:** Recovery readiness report, gap analysis report
**Recovery outputs:** Complete recovery-package.tar.gz with all phases
**Workbook outputs:** recovery-workbook.ods with all phases pre-populated

---

### Phase 8 — Executable Recovery Generation

**Objective:** Make recovery executable, checkpoint-based, resumable, and
failure-analysis-capable.

**Deliverables:**
- lib/checkpoint.sh — checkpoint tracking functions
- lib/validation.sh — post-step validation functions
- lib/ods-update.sh — ODS workbook machine-update functions (wrapping ods_updater.py)
- lib/failure-package.sh — automatic failure package generation
- All recovery scripts updated to use checkpoint + ODS update + failure package libs
- failure-package.tar.gz generation fully automated
- summary.md template implemented
- Self-improvement loop documented and validated (human + LLM analysis workflow)

**Risks:** ODS update from shell scripts is fragile. Checkpoint files accumulate and
are not cleaned up between attempts.
**Dependencies:** Phase 7 (recovery artifact generation)
**Validation:** Simulate a recovery failure; verify failure package is generated
automatically; verify summary.md is LLM-ready; verify re-run resumes from checkpoint.
**Documentation outputs:** Failure analysis workflow documentation
**Recovery outputs:** All recovery scripts with checkpoint + failure package support
**Workbook outputs:** recovery-workbook.ods with machine-update capability demonstrated

---

### Phase 9 — Multi-Node Scaling

**Objective:** Scale from single-node k3s to multi-node HA cluster when a second
physical Proxmox host is added.

**Deliverables:**
- Metadata trigger: when k3s-cluster.yaml node_count ≥ 3-server threshold,
  planners automatically generate 3-server HA topology plan
- OpenTofu: k3s-nodes environment updated to support N server + M agent nodes
- k3s migration: single-node SQLite → 3-server embedded etcd
- Longhorn deployed for distributed persistent storage (replaces local-path)
- Velero deployed for k3s PVC backup
- Documentation engine extended with multi-node topology visualisation
- Recovery procedures updated for multi-node cluster restoration

**Risks:** SQLite → etcd migration is destructive (requires cluster rebuild). Longhorn
adds storage complexity and potential performance impact.
**Dependencies:** Phase 8 (fully executable recovery — required before adding complexity)
**Validation:** Node failure simulation — verify workloads migrate; verify etcd quorum
maintained; verify Longhorn replication healthy.
**Documentation outputs:** Multi-node topology, HA documentation, Longhorn storage map
**Recovery outputs:** Updated recovery scripts for multi-node restoration
**Workbook outputs:** Multi-node recovery workbook

---

### Phase 10 — Disaster Recovery Validation

**Objective:** Validate that the entire self-reconstruction capability works under
realistic disaster conditions.

**Deliverables:**
- Full destruction drill: all k3s workloads destroyed, documentation engine down
- Recovery from external backup only (recovery package)
- Recovery time measured vs. declared RTO
- All gaps identified during drill addressed in bootstrap repository
- Second drill (optional) verifying improvements
- Scheduled quarterly drill procedure documented

**Validation criteria (all must pass):**
- Recovery package downloaded and verified in < 5 minutes
- k3s cluster operational in < 30 minutes
- Documentation engine generating docs in < 45 minutes
- All applications operational in < 2 hours
- No manual steps not covered by recovery scripts
- Workbook complete and accurate

**Risks:** First drill always finds gaps. Do not skip the drill.
**Dependencies:** Phase 9 (multi-node for realistic HA scenario)
**Documentation outputs:** Drill report, RTO/RPO compliance report
**Recovery outputs:** Improved recovery package incorporating drill findings
**Workbook outputs:** Drill execution workbook (completed ODS — the gold standard)

---

## 23. Relationship to Existing Work

The existing codebase (proxmox-bootstrap/, data-model/, doc-gen/) maps to this
architecture as follows:

| Existing component | Maps to |
|---|---|
| `proxmox-bootstrap/init-bootstrap-state.py` | Phase 1: Bootstrap Intelligence entry point |
| `proxmox-bootstrap/suggest-names.py` | Phase 1: Naming planner |
| `proxmox-bootstrap/roles.py` | Phase 1: VM role catalog (extend for k3s nodes) |
| `proxmox-bootstrap/generate-user-data.py` | Phase 1: Generator layer |
| `proxmox-bootstrap/generate-network-configs.py` | Phase 1: Generator layer |
| `proxmox-bootstrap/backup.py` | Phase 7/8: Recovery package archive naming |
| `proxmox-bootstrap/setup-external-backup.py` | Phase 2: External backup |
| `data-model/*.json` | Phase 0: Metadata schema foundation |
| `doc-gen/engine.py` | Phase 4: Documentation engine (containerise for k3s) |
| `doc-gen/drift.py` | Phase 4/5: Drift detection |
| `doc-gen/readiness.py` | Phase 7: Recovery readiness scorer |
| `doc-gen/renderers/*.py` | Phase 4/7: ODS/ODT renderer library |
| `history/` | Phase 4: Historical state store |

**No existing work is discarded.** The existing assessment engine becomes the Phase B
(Operational Intelligence) core, containerised and deployed as a k3s workload.
The schema framework becomes the metadata foundation for Phase 0.

---

## 24. Summary

The v6.0 architecture is a qualitative evolution from v5.0. The previous architecture
was a solid assessment-and-documentation engine for a single Proxmox cell. This
revision makes it a platform:

- **k3s** replaces Podman as the application runtime — scheduling, failover, HA
- **Flux CD** provides GitOps — continuous reconciliation from Git, not manual apply
- **Four intelligence phases** separate concerns that the previous architecture conflated
- **Documentation engine** becomes the first k3s workload — the cluster understands
  itself before hosting anything else
- **Executable recovery** with checkpoints, ODS workbook updates, and automatic
  failure package generation
- **Self-improvement loop** from failure → failure package → LLM analysis → improved
  bootstrap → better future recovery

The deepest principle remains unchanged from v4.0:

> Every state category, every metadata field, and every documentation artifact
> must be evaluated against: "Does this enable reconstruction from repository
> state after complete infrastructure loss?"

k3s and GitOps strengthen this principle significantly. A `flux bootstrap` command
on a fresh cluster, pointed at Forgejo, will reconcile the entire platform to its
documented state. Combined with the recovery package scripts, the entire system
can rebuild itself.
