# BroodForge HashiCorp Replacement Gap Analysis

Source: `BroodForge_HashiCorp_Functional_Replacement_Specification.zip`

This document cross-references the canonical stack against what currently exists in
`proxmox-bootstrap/` and proposes the remaining roadmap phases (3.Q onward).
Merge into ROADMAP.md after the ROADMAP.md revert is complete.

---

## Coverage Map

| HashiCorp Capability | Replacement | Status | File(s) |
|---|---|---|---|
| Terraform | OpenTofu | ⚠ Partial | `spawn_iac_generator.py` generates configs; no lifecycle runner |
| Vault | OpenBao | 🔲 Planned | Phase 3.L |
| Consul Service Discovery | CoreDNS | ⚠ Partial | `setup_dnsmasq.py`; no custom CoreDNS manager |
| Consul Connect | Linkerd | ✅ Done | `linkerd_manager.py` |
| Nomad | Kubernetes | ✅ Done | Kubernetes throughout |
| Packer | Proxmox + Cloud-Init + OpenTofu + Ansible | ⚠ Partial | Image builder exists; Ansible missing |
| Boundary | Headscale + Teleport | ⚠ Partial | `setup_headscale.py` done; Teleport missing |
| Waypoint | FluxCD | ✅ Done | `flux_manager.py` |
| Sentinel | OPA | ⚠ Partial | `kyverno_manager.py` (k8s admission); OPA/Conftest for IaC missing |

## Canonical Stack Coverage

| Component | Role | Status | Notes |
|---|---|---|---|
| Proxmox | Hypervisor | ✅ Core | |
| OpenTofu | IaC provisioning | ⚠ Partial | Generator exists; lifecycle runner missing |
| Ansible | Config management | 🔲 Missing | No Ansible manager; post-boot config gap |
| Cloud-Init | Node initialization | ✅ Done | `generate-user-data.py`, `forge-build-node-iso.sh` |
| Forgejo | Source control (GitOps) | 🔲 Missing | Currently uses GitHub |
| OpenBao | Secrets broker | 🔲 Planned | Phase 3.L |
| KeePassXC | Human root store | ✅ Done | `credential_hierarchy.py`, `forge-lib.sh` |
| Kubernetes | Orchestration | ✅ Done | Throughout |
| FluxCD | GitOps | ✅ Done | `flux_manager.py` |
| Authentik | Identity/SSO | ✅ Done | Phase 2.A |
| Headscale | Overlay network | ✅ Done | `setup_headscale.py` |
| Teleport | Privileged access | 🔲 Missing | No Teleport manager |
| CoreDNS | Service discovery | ⚠ Partial | Default k8s CoreDNS; no custom config manager |
| Linkerd | Service mesh | ✅ Done | `linkerd_manager.py` |
| Ceph | Storage platform | ⚠ Unclear | `storage_manager.py` — needs verification vs Longhorn |
| Restic | Backup | ✅ Done | `backup_manager.py`, `backup_engine.py` |
| Prometheus | Metrics | ✅ Done | Phase 2.C |
| Grafana | Dashboards | ✅ Done | Phase 2.C |
| OPA | Policy engine | ⚠ Partial | Kyverno for k8s admission; OPA/Conftest for IaC missing |
| Control Nexus | Federation controller | 🔲 Future epic | `federation_manager.py` covers cell federation; Control Nexus is broader |

---

## Proposed New Phases

### Phase 3.Q — OpenTofu Lifecycle Manager

**Goal:** Complete the IaC story. `spawn_iac_generator.py` already generates OpenTofu
configs from spawn plans; there is no manager that runs them (plan/apply/drift/destroy).

**Design:**
- `proxmox-bootstrap/opentofu_manager.py` — lifecycle runner:
  `plan()`, `apply()`, `show()`, `drift_check()`, `destroy()`
- State backend: local state in forge working directory OR Forgejo-hosted HTTP backend
  (use local until Forgejo is available; see Phase 3.S)
- Phoenix gate: `apply()` requires a BackupManifest snapshot before proceeding (same
  pattern as `upgrade_manager.py`)
- Drift detection: scheduled `drift_check()` run; findings surfaced in dashboard
- PAP compliance: no credentials in OpenTofu variable files; all secrets via OpenBao
  provider (after Phase 3.L) or environment-injected at run time from KeePass gate
- `scripts/forge-tofu-plan.sh` and `forge-tofu-apply.sh` wrappers with KeePass gate

**Files to create:**
- `proxmox-bootstrap/opentofu_manager.py`
- `scripts/forge-tofu-plan.sh`, `forge-tofu-apply.sh`

**Dependencies:** Phase 3.L (OpenBao) for secret injection; `spawn_iac_generator.py`
already provides input configs.

---

### Phase 3.R — Ansible Configuration Manager

**Goal:** Fill the post-boot configuration gap. After a node joins via Headscale and
Kubernetes, Ansible configures it (packages, system settings, compliance baselines).
Completes the Packer replacement stack alongside Cloud-Init + OpenTofu.

**Design:**
- `proxmox-bootstrap/ansible_manager.py` — playbook registry, inventory generation
  from `node_planner.py` state, run execution with subprocess + timeout
- Inventory is dynamic: generated from Headscale peer list + broodforge node state
- Playbook registry: each playbook registered with a name, target role, and idempotency
  guarantee flag
- Integrated into node lifecycle: after `node_planner.py` marks node `active`, Ansible
  phase is triggered automatically for configuration
- Vault/OpenBao integration: Ansible vault passwords retrieved via OpenBao (Phase 3.L)
- Run logs stored in broodforge state directory; failures surface in dashboard
- PAP compliance: no plaintext passwords in inventory or playbook vars; all via vault

**Files to create:**
- `proxmox-bootstrap/ansible_manager.py`
- `config/ansible/` — inventory template, site.yml, role definitions
- `scripts/forge-ansible-run.sh` — KeePass-gated wrapper

**Dependencies:** Phase 3.L (OpenBao for vault passwords), node lifecycle (Phase 1.Q).

---

### Phase 3.S — Forgejo Source Control Integration

**Goal:** Achieve "GitOps first" and "private by default" by hosting broodforge's
source of truth on a self-hosted Forgejo instance instead of GitHub.

**Why Forgejo matters:** FluxCD currently sources from GitHub. That's a public
dependency for a private-by-default stack. Forgejo + FluxCD over Headscale closes that.

**Design:**
- `proxmox-bootstrap/forgejo_manager.py` — provision Forgejo on governance VM or k8s;
  org/repo/webhook creation; mirror setup for upstream dependencies
- Forgejo runs in k8s (Helm chart); persistent storage via Ceph or Longhorn PVC
- FluxCD sources updated: `GitRepository` objects point to Forgejo over Headscale
- Webhook: Forgejo webhook fires `forge-render-docs.sh` on `.md` file push to keep
  HTML docs current without manual regeneration
- Authentication: Forgejo OIDC federated through Authentik (Phase 2.A) — single SSO
- Robot accounts for FluxCD and CI stored in OpenBao (Phase 3.L)
- Migration path: mirror GitHub repo into Forgejo; update FluxCD sources; test;
  GitHub becomes a read-only upstream mirror

**Files to create:**
- `proxmox-bootstrap/forgejo_manager.py`
- `config/forgejo/` — Helm values, webhook config
- `scripts/forge-init-forgejo.sh`

**Dependencies:** Phase 3.L (OpenBao for robot account storage), Phase 2.A (Authentik
for OIDC). Forgejo should land before OPA and Control Nexus since both need it as
a policy/config source.

---

### Phase 3.T — Teleport Access Management

**Goal:** Add privileged access management and session recording (Boundary replacement).
Headscale handles WireGuard overlay; Teleport handles certificate-based SSH, k8s API
access, session recording, and privileged access workflows.

**Design:**
- `proxmox-bootstrap/teleport_manager.py` — Teleport Auth/Proxy cluster init;
  node enrollment; k8s cluster registration; user provisioning via Authentik (OIDC)
- Teleport Auth runs on governance VM; Teleport Node agent runs on each spawned node
- k8s access: `teleport_manager.py` registers the cluster, generates kubeconfig for
  operator access through Teleport (no direct kubeconfig distribution)
- Session recording: all SSH and k8s `exec` sessions recorded and stored per compliance
  window; stored in Restic-backed archive
- Integration with Authentik: Teleport OIDC connector points to Authentik; role mapping
  from Authentik groups to Teleport roles
- KeePass gate: Teleport admin credentials stored in KeePass master; all other access
  via certificate (no passwords)

**Relationship to Headscale:** Headscale provides the WireGuard overlay (layer 3);
Teleport provides the access control and recording layer on top. Both coexist.

**Files to create:**
- `proxmox-bootstrap/teleport_manager.py`
- `scripts/forge-init-teleport.sh`
- `config/teleport/` — config template

**Dependencies:** Phase 2.A (Authentik OIDC), Phase 1.P (credential hierarchy).

---

### Phase 3.U — OPA/Conftest IaC Policy Validation

**Goal:** Add infrastructure-level policy validation (Sentinel replacement). Kyverno
already handles k8s admission control at runtime; OPA/Conftest validates IaC artifacts
before they are applied — OpenTofu plans, Helm values, k8s manifests.

**Why both OPA and Kyverno:**
- Kyverno = runtime admission (blocks bad resources from being created in k8s)
- OPA/Conftest = pre-apply policy (blocks bad OpenTofu plans and Helm values before
  they ever reach the cluster)
- These are complementary layers, not alternatives.

**Design:**
- `proxmox-bootstrap/opa_manager.py` — Conftest policy bundle management; run
  validation against OpenTofu plan JSON output; Rego policy registry
- PAP pattern integration: broodforge PAP audit patterns translated to Rego rules
  (e.g. "no credentials in env vars" becomes an OPA policy that validates k8s manifests)
- Gate integration: `opentofu_manager.apply()` calls Conftest validation before
  proceeding; fail on any policy violation
- Policy sources: stored in Forgejo (Phase 3.S); FluxCD syncs to governance VM
- OPA policy bundle: versioned bundle hosted on Forgejo; Conftest pulls at plan time

**Files to create:**
- `proxmox-bootstrap/opa_manager.py`
- `config/opa/policies/` — Rego policy files (translated from PAP patterns)
- `scripts/forge-conftest-validate.sh`

**Dependencies:** Phase 3.Q (OpenTofu — needs plan output to validate), Phase 3.S
(Forgejo — for policy bundle hosting).

---

### Phase 3.V — CoreDNS Configuration Manager

**Goal:** Manage custom CoreDNS configuration for split-horizon DNS, Headscale
MagicDNS integration, and service discovery across the overlay network.

**Current state:** CoreDNS runs as the default k8s cluster DNS. No custom
configuration is managed by broodforge — it uses whatever kubeadm/k3s/Talos deploys.

**Design:**
- `proxmox-bootstrap/coredns_manager.py` — manage Corefile patches via ConfigMap;
  register custom zones; configure forwarding rules
- Split-horizon DNS: internal zone (`.broodforge.local` or similar) resolves via
  CoreDNS inside the Headscale overlay; external DNS not aware of internal topology
- Headscale MagicDNS integration: CoreDNS configured to forward `.ts.net` / Headscale
  zone queries to Headscale's embedded DNS
- Wildcard ingress: `*.apps.<cluster>` wildcard entry pointing to ingress controller
- Service advertisements: when a new service is registered, `coredns_manager.py`
  updates the relevant zone record
- `setup_dnsmasq.py` (governance VM DNS) and `coredns_manager.py` (cluster DNS)
  complement each other; dnsmasq handles pre-k8s bootstrap; CoreDNS handles runtime

**Files to create:**
- `proxmox-bootstrap/coredns_manager.py`

**Dependencies:** Headscale (`setup_headscale.py`), k8s running.

---

### Phase 3.W — Control Nexus (Future Epic)

**Goal:** Federation controller providing multi-cell resource advertisement, allocation,
cluster discovery, and trust management. Extends `federation_manager.py` (which handles
cell-to-cell federation handshake) into a full coordination layer.

**What `federation_manager.py` already does:**
- PeerCell registration/deregistration
- Trust bundle sync
- Probe/health check

**What Control Nexus adds:**
- Resource advertisement: each cell publishes available compute/storage/capability
  to the nexus
- Resource allocation: workloads can be scheduled across cells based on advertisements
- Cluster discovery: new cells auto-discover the nexus via Headscale + a well-known
  Forgejo manifest
- Infrastructure memory: each cell's state is preserved in a distributed log;
  reconstruction drills can target any cell from any other
- API: REST API served by the nexus; consumed by `broodforge_dashboard.py` for
  federation panel

**Scope note:** This is a significant architectural undertaking and should be treated
as a multi-sprint epic. Implementation in discrete milestones:
1. Resource advertisement protocol (cell publishes state to nexus)
2. Cluster discovery (Forgejo-hosted manifest)
3. Resource allocation scheduler
4. Dashboard federation panel

**Dependencies:** Phase 3.S (Forgejo for discovery manifest), Phase 3.L (OpenBao for
cross-cell trust tokens), Phases 3.Q/3.R (OpenTofu/Ansible for cross-cell provisioning).

---

## Ceph vs Longhorn Reconciliation

`storage_manager.py` exists — needs audit to determine if it covers Ceph, Longhorn,
or both. The canonical spec says Ceph. The recommendation:

- **Longhorn**: k8s-native PVC storage for stateful workloads (databases, registries,
  monitoring data). Simple, already understood in the codebase.
- **Ceph**: VM-level block storage on Proxmox (Proxmox Ceph), shared storage for
  non-k8s workloads, and large-scale PVCs. More complex to operate.
- **Decision**: both coexist at different layers. `storage_manager.py` should be
  audited and if needed split into `longhorn_manager.py` and `ceph_manager.py`.

This is not a new roadmap phase but a clarification task within Phase 3 storage work.

---

## Recommended Phase Sequencing

```
3.L OpenBao          ← unlock secrets management first; everything depends on it
3.M Source Editor    ← doc tooling; independent
3.N TOTP QR          ← doc tooling; independent
3.O TOC Numbering    ← doc tooling; independent
3.P Setup Guide      ← doc migration; after 3.N
3.Q OpenTofu         ← depends on 3.L for secret injection
3.R Ansible          ← depends on 3.L for vault passwords
3.S Forgejo          ← depends on 3.L, 2.A; needed before OPA policy hosting
3.T Teleport         ← depends on 2.A, 1.P
3.U OPA/Conftest     ← depends on 3.Q, 3.S
3.V CoreDNS          ← relatively independent; do after basic cluster is stable
3.W Control Nexus    ← future epic; depends on 3.S, 3.L, 3.Q, 3.R
```
