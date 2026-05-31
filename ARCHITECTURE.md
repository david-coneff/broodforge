# Self-Documenting, Self-Recovering Infrastructure Platform — Architecture

Version: 6.0
Date: 2026-05-31 16:14:22 UTC (2026-05-31 10:14:22 MDT)
Full review: docs/ARCHITECTURE-REVIEW-v6.md

---

## Platform Stack

| Layer | Technology | Role |
|---|---|---|
| Hypervisor | Proxmox VE | VM hosting, storage, networking, snapshots |
| IaC | OpenTofu | Proxmox VM provisioning |
| Provisioning | Cloud-Init + Ansible | VM configuration and k3s setup |
| Git hosting | Forgejo (VM, pre-k3s) | All repositories — source of truth |
| GitOps | Flux CD | Continuous reconciliation from Git to k3s |
| Orchestration | k3s | All application workloads |
| Documentation | doc-engine (k3s workload) | Phase B/C/D intelligence |
| Workbooks | ODS (machine-updated) | Execution records for recovery |

---

## The Four Intelligence Phases

```
Phase A — Bootstrap Intelligence   (pre-k3s, stdlib Python, runs on operator machine)
  Purpose:  Build the first-ever environment from bare metal
  Produces: Provisioned Proxmox + pre-k3s VMs + k3s-ready infrastructure

Phase B — Operational Intelligence (k3s workload, runs continuously)
  Purpose:  Understand and document a running environment
  Produces: Living inventory, architecture docs, dependency maps, drift reports

Phase C — Recovery Intelligence    (k3s workload, triggered by Phase B)
  Purpose:  Generate recovery knowledge
  Produces: Recovery documentation, readiness scores, recovery packages

Phase D — Execution Intelligence   (k3s workload for generation; standalone for execution)
  Purpose:  Generate and execute recovery workflows
  Produces: Recovery scripts, ODS workbooks, failure packages, improvement loop
```

---

## Source of Truth Hierarchy

```
AUTHORITATIVE
  1. Metadata YAML files (infrastructure intent — never generated)
  2. Git repositories (declared state — OpenTofu, manifests, configs)
  3. OpenTofu state (provisioned infrastructure)
  4. k3s / Kubernetes API (live running state)

DERIVED (never edit directly — regenerate from 1–4)
  5. Generated documentation
  6. Generated recovery packages and scripts
  7. ODS workbook execution records (exception: these are the execution audit trail)

DISPOSABLE (safe to delete and regenerate)
  8. Cached manifests, rendered templates, intermediate artifacts
```

---

## Architecture Hierarchy

```
Federation
└── Infrastructure Cell
    └── Proxmox Cluster
        └── Proxmox Node(s)
            ├── Pre-k3s VMs
            │   ├── forgejo-vm      Forgejo Git hosting
            │   └── bootstrap-vm    Phase A toolchain
            └── k3s Cluster
                ├── Control Plane (1 server initially; 3 for HA after Phase 9)
                ├── Worker Nodes
                └── Namespaces
                    ├── platform/       cert-manager, ingress, flux
                    ├── documentation/  doc-engine (Phase B/C/D) ← FIRST WORKLOAD
                    ├── monitoring/     Prometheus, Grafana, Loki
                    └── applications/   User services (after documentation)
```

---

## Bootstrap Repository Structure

```
bootstrap/
├── metadata/           AUTHORITATIVE infrastructure intent YAML
├── discovery/          Phase A: hardware/network/storage/Proxmox discovery
├── planners/           Phase A: cluster/storage/network/naming planning
├── generators/         Phase A: OpenTofu vars, Cloud-Init, Ansible inventory
├── opentofu/           Proxmox IaC (modules + environments)
├── ansible/            Configuration management (roles + playbooks)
├── cloud-init/         Generated Cloud-Init snippets
├── validation/         Pre-deployment readiness checks
├── recovery/           Phase C/D: packages, scripts, workbooks
├── workbooks/          ODS templates and generators
├── docs/               Generated documentation outputs
└── secrets/            Secret registry (KeePass paths only)
```

---

## Minimum Viable Initial Deployment

**Objective: create a self-documenting cluster — before any user service.**

```
Pre-k3s (Phase 2):
  forgejo-vm      (VM 100)  2GB RAM  Git hosting
  bootstrap-vm    (VM 101)  2GB RAM  Phase A toolchain

k3s initial (Phase 3):
  k3s-server-01   (VM 110)  4GB RAM  Single-node k3s

First k3s workloads (in order — Phase 4):
  1. cert-manager, ingress-nginx, flux-system  (platform)
  2. doc-engine                                 (documentation) ← GATE
  3. prometheus, grafana, loki                  (monitoring)
  [GATE: documentation system must be running before any user services]
  4. nextcloud, immich, etc.                    (applications)
```

---

## Key Architecture Decisions

| AD | Decision |
|---|---|
| AD-022 | k3s as primary application platform (over Podman) |
| AD-023 | Flux CD as GitOps engine (over ArgoCD — bootstraps into fresh cluster) |
| AD-024 | Forgejo as sole Git provider; external Git providers are mirrors only |
| AD-025 | ODS as standard machine-updatable workbook format |
| AD-026 | Metadata YAML as primary source of infrastructure intent |
| AD-027 | Four intelligence phases with distinct runtimes (pre/post k3s) |
| AD-028 | Documentation engine is the first k3s workload |
| AD-029 | Recovery packages are self-contained and offline-capable |
| AD-030 | Failure packages are structured for LLM analysis |
| AD-031 | Documentation captures STATE and INTENT (what + why + which policy) |

---

## Core Principles

1. **Reconstruction is the objective.** Every artifact is evaluated against:
   "Does this enable reconstruction after complete infrastructure loss?"

2. **Documentation captures intent, not just state.** Not "3 control plane nodes"
   but "3 control plane nodes because HA policy requires quorum."

3. **Documentation engine before all user services.** The cluster must understand
   itself before it hosts anything for users.

4. **Recovery packages are offline-capable.** A recovery package must work without
   internet access and without Forgejo being reachable.

5. **Failure drives improvement.** Every recovery failure generates a structured
   failure package. Every failure package should result in a bootstrap repository
   commit that prevents that failure mode from occurring again.

6. **GitOps is the deployment paradigm.** All desired state is in Git. Flux applies
   it continuously. Drift is detected and corrected automatically.

7. **Generated artifacts are never the source of truth.** Documentation, recovery
   packages, and ODS workbooks are derived from metadata + Git. They are never
   edited directly.

Full architectural rationale: docs/ARCHITECTURE-REVIEW-v6.md
