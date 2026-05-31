# Architecture Review — v4.0
## Infrastructure Lifecycle, Cloud-Init, and Reproducible Reconstruction

Date: 2026-05-30
Status: Adopted

---

## 1. Review Summary

The previously proposed architecture modeled infrastructure primarily as:

```
OpenTofu → Ansible → Applications
```

This review concludes that model is **insufficient** for the stated objectives of:

- Complete destroy-and-recreate reproducibility from repository state
- Automated documentation generation across the full infrastructure lifecycle
- Automated recovery sequencing from first principles

The gap is the **provisioning layer**: the sequence of steps that takes a freshly created VM
from empty disk to a state where Ansible can run on it. This layer — Cloud-Init templates,
snippets, first-boot configuration, network identity, base image selection — is currently
unmodeled, untracked, and would be the primary obstacle to automated reconstruction.

A secondary gap is **service state**: the distinction between "software is installed and
configured" (Ansible's domain) and "the application is running with its data, credentials,
and integrations" (a separate and more complex recovery concern).

**Verdict:** The architecture should be reorganized around the complete infrastructure
lifecycle. The seven-state model and six-layer lifecycle model proposed in the review request
are both adopted, with additional refinements described in this document.

---

## 2. The Provisioning Gap

Consider the disaster scenario: Proxmox host destroyed, all VMs destroyed, configuration
state lost. Available assets: repositories, backups, assessment history.

### What the previous model could reconstruct

- OpenTofu workspace exists → VM definitions can be replayed
- Ansible repository exists → software configuration can be replayed
- Backup exists → data can be restored

### What the previous model cannot reconstruct without manual intervention

1. **Which Ubuntu ISO was used** — checksum, version, download source
2. **Cloud-Init user-data** — initial user, SSH keys, hostname, packages, disk setup
3. **Cloud-Init network-config** — static IP assignment on first boot
4. **Cloud-Init vendor-data / snippets** — Proxmox-specific bootstrap hooks
5. **VM template provenance** — which base template each VM was cloned from
6. **First-boot ordering** — which VMs must be provisioned before others
   (e.g., DNS before all others, storage before consumers)
7. **Bootstrap credentials** — initial SSH key placement, sudo configuration
8. **Network identity** — what IP was assigned, what hostname was set, what bridge was used

Without these, an operator must manually reconstruct first-boot state from memory or
documents. This is where disaster recovery fails in practice: not at the Ansible step,
but at the step that gets a bare VM to the point where Ansible can reach it.

### Conclusion

Cloud-Init templates, snippets, and deployment metadata must be elevated to first-class
managed assets tracked as **Bootstrap State**.

---

## 3. Adopted Architecture: Six-Layer Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1 — Infrastructure Definition                           │
│  OpenTofu workspaces · Resource declarations · Variables        │
│  Modules · Provider configurations · Network topology as code  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ qm create / qm clone
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 2 — Infrastructure Provisioning                         │
│  VM templates · Cloud-Init user-data · Cloud-Init network-config│
│  Cloud-Init vendor-data · Bootstrap snippets                    │
│  Base image registry · Template provenance · First-boot ordering│
└───────────────────────────┬─────────────────────────────────────┘
                            │ first boot completes, SSH available
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3 — Configuration Management                            │
│  Ansible inventory · Playbooks · Roles · Collections           │
│  Group vars · Host vars · Configuration repositories           │
└───────────────────────────┬─────────────────────────────────────┘
                            │ software installed, services configured
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 4 — Service Deployment                                  │
│  Application containers · Databases · Reverse proxies          │
│  Service integrations · Secret references · DNS registration   │
│  Backup job registration · Service contracts (ports, URLs)     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ environment running
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 5 — Assessment and Validation                           │
│  Tier 1 bootstrap assessment · Tier 2 full assessment          │
│  Drift detection · Dependency validation · Capacity validation │
│  Provenance verification · Service contract verification       │
└───────────────────────────┬─────────────────────────────────────┘
                            │ structured state model
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  Layer 6 — Documentation and Recovery Intelligence             │
│  Bootstrap documentation · Operational documentation           │
│  Recovery documentation · Dependency graphs                    │
│  Restore sequences · Recovery readiness reports                │
└─────────────────────────────────────────────────────────────────┘
```

**This is a strict dependency chain.** Each layer's artifacts are prerequisites for the
layer below it. Documentation is not a side product — it is a layer that consumes outputs
from all other layers.

---

## 4. Adopted State Model: Seven Categories

### State 1 — Declared State
**Source:** OpenTofu repositories
**Contains:**
- VM resource declarations (vmid, cores, memory, disk, network)
- Storage resource declarations
- Network topology declarations (bridges, VLANs, firewall rules)
- Variable definitions and module definitions
- `terraform.tfstate` / OpenTofu state files
- Provider configurations

**Required for reconstruction:** Yes — defines what VMs exist and their hardware configuration.

### State 2 — Bootstrap State  *(new)*
**Source:** Bootstrap repositories (new) / Proxmox snippets storage
**Contains:**
- Cloud-Init user-data templates (per VM or per role)
- Cloud-Init network-config templates (static IP assignments)
- Cloud-Init vendor-data / Proxmox snippets
- Base image registry: ISO checksums, download URLs, version pins
- VM template definitions: which template was used for which VM
- Template build manifests: what is in each template (packages, configuration)
- First-boot package lists
- Initial SSH authorized keys (by reference, not by value)
- Bootstrap credential references (KeePass paths for initial passwords)
- First-boot ordering constraints

**Required for reconstruction:** Yes — without this, VMs cannot reach a state where
Ansible can run on them.

**Schema location:** `data-model/bootstrap-state-schema.json`

### State 3 — Configured State
**Source:** Ansible / Inventory repositories
**Contains:**
- Ansible inventory (hosts, groups, variables)
- Playbook manifests (which playbooks apply to which hosts)
- Role assignments
- Collection dependencies (requirements.yml)
- Configuration repositories (git URLs + pinned commits)
- Group variables and host variables

**Required for reconstruction:** Yes — defines software configuration applied to each VM.

### State 4 — Service State  *(new)*
**Source:** Service metadata repositories + assessment (observed)
**Contains:**
- Running service inventory (name, VM, port, protocol, URL)
- Service dependency declarations (what each service requires to function)
- Service contracts (what each service exposes)
- Database schemas and migration state
- Reverse proxy configurations
- Secret references (KeePass paths for each service's credentials)
- Backup job assignments (which backup job covers which service)
- DNS registrations (hostname → IP mappings)
- Service ownership metadata

**Required for reconstruction:** Partially — service contracts and dependency declarations
enable correct recovery ordering; secret references enable automated recovery steps.

**Schema location:** `data-model/service-state-schema.json`

### State 5 — Observed State
**Source:** Tier 1 and Tier 2 assessment packages
**Contains:** (unchanged from v3.0)
Hardware, network, VMs, containers, software, services, dependencies

**Required for reconstruction:** As verification — confirms post-recovery state matches
expected state.

### State 6 — Historical State
**Source:** Assessment history store
**Contains:** (unchanged from v3.0)
Timestamped snapshots, drift records, capacity evolution, dependency evolution

**Required for reconstruction:** Indirectly — provides reference state for verifying
recovery completeness.

### State 7 — Recovery State
**Source:** Generated documentation artifacts
**Contains:** (unchanged from v3.0)
Recovery workbooks, runbooks, restore sequences, dependency graphs, readiness reports

**Required for reconstruction:** Yes — these are the operator-facing artifacts.

---

## 5. Cloud-Init Integration Strategy

### 5.1 Where Cloud-Init fits

Cloud-Init is the bridge between Layer 1 (Infrastructure Definition) and Layer 3
(Configuration Management). It executes once, on first boot, and:

1. Sets hostname and network identity
2. Creates initial user accounts and places SSH authorized keys
3. Installs prerequisite packages (python3, git, qemu-guest-agent)
4. Runs initial disk configuration
5. Optionally executes a bootstrap script (git clone + ansible-pull pattern)

After Cloud-Init completes, the VM is reachable by Ansible and the configuration layer
takes over.

### 5.2 Cloud-Init artifact types

```
snippets/
  user-data/
    infra-bootstrap.yaml      # user-data for infra-bootstrap VM
    forgejo.yaml              # user-data for forgejo VM
    inventory.yaml            # etc.
    base-ubuntu.yaml          # shared base (included by others)
  network-config/
    infra-bootstrap.yaml      # static IP: 192.168.1.20/24, gw 192.168.1.1
    forgejo.yaml              # static IP: 192.168.1.21/24
    inventory.yaml
    assessment-engine.yaml
  vendor-data/
    proxmox-hooks.yaml        # Proxmox-specific first-boot hooks
```

### 5.3 Proxmox snippet storage integration

Proxmox stores Cloud-Init snippets in a designated storage location
(typically `local:snippets/`). These must be:

1. Tracked in a git repository (Bootstrap State repository)
2. Applied to VMs via OpenTofu (`cicustom` attribute)
3. Recorded in the Bootstrap State manifest with their effective content hash
4. Assessed by the Tier 2 collector (verify snippets match repository state)

### 5.4 Bootstrap State manifest fields

```json
{
  "schema_version": "1.0",
  "vms": [
    {
      "vmid": 100,
      "name": "infra-bootstrap",
      "template_name": "ubuntu-2204-base",
      "template_checksum": "sha256:abc123...",
      "cloudinit": {
        "user_data_path": "snippets/user-data/infra-bootstrap.yaml",
        "user_data_hash": "sha256:def456...",
        "network_config_path": "snippets/network-config/infra-bootstrap.yaml",
        "network_config_hash": "sha256:789...",
        "vendor_data_path": null
      },
      "initial_ip": "192.168.1.20",
      "initial_hostname": "infra-bootstrap",
      "bridge": "vmbr0",
      "initial_user": "ubuntu",
      "ssh_key_reference": "Infrastructure/ssh/infra-bootstrap-deploy-key",
      "password_reference": "Infrastructure/proxmox/vm-100-password"
    }
  ],
  "base_images": [
    {
      "name": "ubuntu-2204-base",
      "source_iso": "ubuntu-22.04.4-live-server-amd64.iso",
      "source_url": "https://releases.ubuntu.com/22.04/ubuntu-22.04.4-live-server-amd64.iso",
      "checksum": "sha256:45f873de9f8cb637345d6e66a583762730bbea30277ef7b32c9c3bd6700a32b2",
      "created_at": "2026-04-01T10:00:00Z",
      "included_packages": ["python3", "qemu-guest-agent", "openssh-server", "cloud-init"]
    }
  ]
}
```

---

## 6. Additional Architectural Elements

The review identified the following elements as required beyond Cloud-Init that were
not present in the previous architecture. Each is treated as a first-class concern.

### 6.1 Deployment Provenance

**Problem:** Without a record of *how* each VM was deployed, reconstruction cannot
be automated. "We used Ansible" is insufficient; we need "we used Ansible version X,
playbook at commit Y, with inventory at commit Z, applied at time T."

**Solution:** A **Deployment Provenance Record** is created each time a VM is provisioned
or reprovisioned. It captures:

```json
{
  "vmid": 101,
  "name": "forgejo",
  "deployed_at": "2026-05-01T10:00:00Z",
  "tofu_workspace": "proxmox-vms",
  "tofu_commit": "a1b2c3d",
  "template_name": "ubuntu-2204-base",
  "template_checksum": "sha256:45f873...",
  "cloudinit_user_data_hash": "sha256:def456...",
  "cloudinit_network_config_hash": "sha256:789...",
  "ansible_playbook": "site.yml",
  "ansible_commit": "d4e5f6",
  "ansible_inventory_commit": "g7h8i9",
  "deployed_by": "operator-name"
}
```

Provenance records are stored in the Bootstrap State repository and indexed in the
assessment manifest. The assessment engine verifies that current state matches provenance
records and flags divergence.

### 6.2 Secret Registry

**Problem:** Secrets cannot be stored in repositories. But documentation and recovery
procedures must reference secrets precisely. "The password is somewhere in KeePass"
is not sufficient for automated or semi-automated recovery.

**Solution:** A **Secret Registry** tracks *references* to secrets (not the secrets
themselves). Every component that requires a secret declares it by reference.

```yaml
# secret-registry.yaml (tracked in Bootstrap State repo)
secrets:
  - id: pve01-root-password
    description: "Proxmox host root password"
    keepass_path: "Infrastructure/proxmox/pve01-root"
    required_by: ["host:pve01"]
    required_for: ["ssh-access", "pve-api-auth"]

  - id: vm-101-service-account
    description: "Forgejo service account password"
    keepass_path: "Infrastructure/forgejo/service-account"
    required_by: ["vm:forgejo"]
    required_for: ["post-restore-validation"]

  - id: infra-bootstrap-deploy-key
    description: "SSH deploy key for infra-bootstrap VM"
    keepass_path: "Infrastructure/ssh/deploy-keys/infra-bootstrap"
    type: "ssh-private-key"
    required_by: ["vm:infra-bootstrap"]
    required_for: ["ansible-execution"]
```

The readiness scorer checks the Secret Registry for each component in the recovery
sequence and flags `UNRESOLVED` for any required secret without a KeePass path.
Generated recovery documentation pre-populates secret retrieval steps from the registry.

### 6.3 Network Topology as Code

**Problem:** Network configuration (bridges, VLANs, firewall rules, static routes) is
currently captured as observed state but not declared state. If the host is destroyed,
the network must be reconstructed before any VMs can be provisioned — but there is no
authoritative source for the network definition.

**Solution:** Network topology is promoted to **Declared State** and stored alongside
OpenTofu definitions. Proxmox network config (`/etc/network/interfaces`) is generated
from code rather than manually edited.

```hcl
# network.tf
resource "proxmox_network_bridge" "vmbr0" {
  node    = "pve01"
  name    = "vmbr0"
  address = "192.168.1.10/24"
  gateway = "192.168.1.1"
  ports   = ["enp2s0"]
}
```

The assessment engine verifies that observed network configuration matches declared
network configuration and flags divergence.

### 6.4 Service Contracts

**Problem:** Service dependencies are currently discovered by heuristics (VM name
matching, network topology analysis). Heuristics are unreliable for novel deployments
and produce incorrect restore sequences for services with non-obvious dependencies.

**Solution:** Each service declares an explicit **Service Contract**:

```yaml
# service-contracts/forgejo.yaml
service: forgejo
vm: forgejo
provided_interfaces:
  - protocol: https
    port: 3000
    url_pattern: "https://forgejo.internal"
    health_check: "GET /api/healthz"

required_interfaces:
  - service: postgresql
    protocol: postgresql
    port: 5432
    critical: true
  - service: smtp
    protocol: smtp
    port: 587
    critical: false

startup_after: [postgresql]
backup_job: vm-101-daily
secret_references: [forgejo-admin-password, forgejo-db-password]
owner: infrastructure
```

Service contracts replace dependency heuristics as the primary source of dependency
graph edges in Tier 2 assessments. Heuristics remain as a fallback and validation layer.

### 6.5 Template Registry

**Problem:** VM templates are ephemeral artifacts on the Proxmox host. If the host is
destroyed, templates are lost. If templates are not versioned, there is no guarantee
that a recreated VM uses the same base image as the original.

**Solution:** A **Template Registry** tracks:
- ISO checksums and download sources for all base images
- Template build manifests (what packages are pre-installed)
- Template creation dates and version history
- Which VMs were created from which template

Templates are rebuilt from their manifests as part of the reconstruction sequence
(Wave 0 — before any VM is created).

### 6.6 DNS and Service Registry

**Problem:** Services reference each other by hostname. During recovery, DNS must be
functional before service-to-service communication can be verified. The DNS state
is not currently tracked as a managed asset.

**Solution:** A **DNS Registry** tracks authoritative hostname→IP mappings. This is
distinct from observed DNS (which may be stale) and provides the ground truth for
recovery documentation commands.

```yaml
dns_registry:
  - hostname: pve01.internal
    ip: 192.168.1.10
    role: proxmox-host

  - hostname: forgejo.internal
    ip: 192.168.1.21
    vm: forgejo
    vmid: 101

  - hostname: assessment.internal
    ip: 192.168.1.23
    vm: assessment-engine
    vmid: 103
```

Recovery runbooks pre-populate commands with IP addresses from the DNS registry
rather than leaving them as `[VM_IP]` placeholders where the correct value is known.

### 6.7 Reconstruction Playbooks

**Problem:** Ansible playbooks configure existing VMs. They do not reconstruct VMs
from nothing. In a full-destroy scenario, there is no existing VM to configure.

**Solution:** **Reconstruction Playbooks** are distinct from configuration playbooks.
They are the operator-facing or automation-facing scripts that replay the full deployment
sequence for a component from scratch:

```
reconstruction-playbooks/
  00-host-restore.sh        # restore Proxmox host from backup
  01-storage-verify.sh      # verify ZFS pool import
  02-network-configure.sh   # apply network topology from code
  03-templates-rebuild.sh   # recreate VM templates from registry
  04-forgejo-provision.sh   # create VM + cloud-init + ansible
  05-inventory-provision.sh
  06-assessment-provision.sh
  run-all.sh                # orchestrated full reconstruction
```

These playbooks are generated from the state model (declared + bootstrap + configured)
and validated by the assessment engine. They are the executable form of the recovery
runbook.

### 6.8 Capacity Model

**Problem:** A recovery attempt may fail because the replacement host has insufficient
resources to run all restored VMs simultaneously. The readiness scorer does not currently
validate capacity.

**Solution:** The **Capacity Model** tracks historical resource usage per VM and validates
that the target recovery host can accommodate the full restored workload:

- Total RAM required vs. available
- Total disk required vs. available pool space
- CPU density (VMs per physical core ratio)
- Storage IOPS demand vs. pool capability

Recovery readiness reports include a capacity validation section. ORANGE or RED flags
are raised if the target host cannot accommodate the workload.

---

## 7. Documentation Architecture: Three Classes

The previous architecture generated two documentation types (bootstrap, recovery).
The review confirms that **three independent documentation classes** are required,
sharing a common metadata model.

### Class A — Bootstrap Documentation

**Purpose:** Guide construction of automation infrastructure from a newly installed
Proxmox host. Assumes: host installed, no VMs, no Ansible.

**Generated from:**
- Tier 1 bootstrap assessment (observed state)
- Declared State (OpenTofu definitions)
- Bootstrap State (Cloud-Init templates, template registry, DNS registry)

**Contents:**
- Stage 01: Host preparation (ZFS, network)
- Stage 02: Template creation (base image, cloud-init snippet setup)
- Stage 03–N: VM provisioning (one stage per VM, using cloud-init + ansible)

**Key improvement over v3.0:** Cloud-Init snippets are pre-populated from Bootstrap State,
not left as human-input fields. The operator sees "Cloud-Init user-data: \[content from
infra-bootstrap.yaml\]" rather than "enter cloud-init configuration here."

### Class B — Operational Documentation

**Purpose:** Guide administration of a running environment. Assumes: environment fully
deployed.

**Generated from:**
- Current Tier 2 assessment
- Historical assessments (for drift context)

**Contents:**
- Current infrastructure inventory
- Drift summary (what has changed since last assessment)
- Capacity trends
- Dependency map (current)
- Service health summary

**New in v4.0:** Operational documentation did not exist in v3.0.

### Class C — Recovery Documentation

**Purpose:** Guide reconstruction from failure conditions. Assumes: varying levels of
destruction (partial or complete).

**Generated from:**
- Historical assessments (most recent verified state)
- Declared State (OpenTofu definitions)
- Bootstrap State (Cloud-Init, template registry)
- Configured State (Ansible repositories)
- Service State (service contracts, DNS registry, secret registry)
- Backup metadata

**Contents:**
- Recovery readiness assessment
- Dependency graph
- Restore sequence (waves)
- Per-component restore procedures with pre-populated commands
- Secret retrieval steps (from Secret Registry)
- Validation checkpoints
- Capacity validation

**Key improvement over v3.0:** Recovery commands now include:
- Exact IP addresses (from DNS Registry)
- Exact Cloud-Init snippet paths (from Bootstrap State)
- Exact secret KeePass paths (from Secret Registry)
- Exact Ansible playbook commands (from Configured State)

rather than `[VM_IP]`, `[CLOUD_INIT_PATH]`, `[KEEPASS_PATH]` placeholders.

### Shared Metadata Model

All three documentation classes consume the same underlying structured metadata.
A single `doc-gen/engine.py` produces all three classes. The difference is which
state inputs are loaded and which templates are rendered.

---

## 8. Metadata Requirements

The following metadata categories must be captured to support the full objective.

### 8.1 Infrastructure metadata (Declared State)
- VM resource specifications (vmid, cores, memory, disk, storage pool, bridge)
- Network topology (bridges, VLANs, firewall rules, static routes)
- Storage topology (ZFS pool configuration, PVE storage definitions)
- OpenTofu workspace versions and commit hashes

### 8.2 Bootstrap metadata (Bootstrap State)
- Cloud-Init user-data per VM (content + hash)
- Cloud-Init network-config per VM (static IP, gateway, DNS)
- Cloud-Init vendor-data / Proxmox snippets
- Base image registry (ISO, checksum, source URL, included packages)
- Template registry (template name, base image, creation date, packages)
- First-boot package lists
- Bootstrap ordering constraints
- Deployment provenance records (see §6.1)

### 8.3 Identity and access metadata (Bootstrap + Service State)
- SSH key references (KeePass paths, not values)
- Initial credential references (KeePass paths)
- Service account references (KeePass paths)
- Sudo/privilege escalation configuration

### 8.4 Configuration metadata (Configured State)
- Ansible inventory at time of last apply
- Playbook versions (git commits) at time of last apply
- Collection versions (requirements.yml hash)
- Configuration drift from last apply

### 8.5 Service metadata (Service State)
- Service contracts (interfaces provided + required)
- DNS registrations (hostname → IP)
- Backup job assignments (which job covers which service)
- Secret references per service (KeePass paths)
- Service ownership (operator/team)
- Last verified health check timestamp

### 8.6 Assessment metadata (Observed State)
- Observed infrastructure at assessment time
- Collection errors and warnings
- Assessment tier and coverage level
- Drift from previous assessment

### 8.7 Recovery metadata (Recovery State)
- Dependency graph (nodes, edges, edge types)
- Restore waves (ordered, annotated)
- Readiness scores per component
- Gaps with remediation guidance
- SPOF list
- Capacity validation results

---

## 9. Repository Structure Recommendations

```
# Repositories managed in Forgejo

broodforge/     (this repository)
  assessment/                  Tier 1 + Tier 2 collectors
  doc-gen/                     Documentation generation engine
  data-model/                  Schemas
  history/                     Assessment snapshots
  reports/                     Generated documentation

proxmox-infrastructure/        (NEW — Infrastructure Definition)
  tofu/
    proxmox-host/              Host-level resources (bridges, storage)
    proxmox-vms/               VM resources
    proxmox-network/           Network topology as code
  README.md

proxmox-bootstrap/             (NEW — Bootstrap State)
  snippets/
    user-data/                 Cloud-Init user-data per VM
    network-config/            Cloud-Init network-config per VM
    vendor-data/               Proxmox-specific hooks
  templates/
    ubuntu-2204-base.yaml      Template build manifest
  images/
    registry.yaml              ISO registry (checksums, sources)
  provenance/
    vm-100-infra-bootstrap.json
    vm-101-forgejo.json
    ...
  secret-registry.yaml         Secret reference registry
  dns-registry.yaml            DNS hostname→IP registry
  service-contracts/           One .yaml per service

proxmox-inventory/             (Existing — Configured State)
  hosts.yaml
  group_vars/
  host_vars/

proxmox-ansible/               (Existing — Configuration)
  site.yml
  roles/
  collections/

proxmox-reconstruction/        (NEW — Reconstruction Playbooks)
  playbooks/
    00-host-restore.sh
    01-storage-verify.sh
    02-network-configure.sh
    03-templates-rebuild.sh
    04-N-vm-provision.sh
  run-all.sh
  README.md
```

---

## 10. Recovery Architecture

The complete recovery sequence in v4.0:

```
Failure Event
    │
    ▼
Recovery Readiness Report
    │
    ├── RED/BLOCKED? → Resolve blockers before proceeding
    │
    ▼
Wave 0 — Pre-VM Infrastructure
    ├── Restore Proxmox host (from backup or fresh install + config)
    ├── Import ZFS pool
    ├── Apply network topology (from proxmox-infrastructure repo)
    └── Verify Proxmox API accessible

Wave 0.5 — Template Reconstruction
    ├── Download base ISOs (from images/registry.yaml)
    ├── Create VM templates (from templates/*.yaml)
    └── Upload Cloud-Init snippets (from snippets/)

Wave 1–N — VM Restoration (per dependency graph)
    ├── For each wave:
    │   ├── Create VM (tofu apply or qm create from provenance)
    │   ├── Attach Cloud-Init (from snippets, using network-config for IP)
    │   ├── Start VM, wait for first-boot
    │   ├── Run Ansible playbook (from proxmox-ansible, pinned commit)
    │   ├── Validate service contract
    │   └── Update DNS registry
    └── Proceed to next wave

Post-Recovery
    ├── Run Tier 2 assessment
    ├── Compare to pre-failure assessment
    ├── Validate all service contracts
    └── Update recovery readiness report
```

### Recovery readiness scoring additions (v4.0)

Additional scoring inputs beyond v3.0:

| Input | Score if missing |
|---|---|
| Cloud-Init snippet in repository | ORANGE |
| Cloud-Init snippet matches deployed version | YELLOW |
| Deployment provenance record exists | YELLOW |
| Service contract declared | YELLOW |
| Secret registry entry for all required secrets | ORANGE |
| DNS registry entry for VM | YELLOW |
| Reconstruction playbook exists and validated | YELLOW |
| Base image in template registry | ORANGE |
| Template rebuild tested | YELLOW |
| Capacity validation passes | ORANGE if fails |

---

## 11. Updated Implementation Roadmap

### Completed (v3.0 work)
- Phases 1–4: Core engine, history, Forgejo, bootstrap assessment package
- Milestone 5.1: Data model (five schemas)
- Milestone 5.2: Tier 1 bootstrap assessment rebuild
- Milestone 5.3: Bootstrap documentation generator
- Milestone 5.4: Recovery documentation generator
- Milestone 5.5: Recovery readiness scoring

### Remaining Phase 5
- Milestone 5.6: Historical State Integration

### Phase 6 — Bootstrap State (NEW)
- 6.1: Bootstrap State schema
- 6.2: Cloud-Init repository structure and templates
- 6.3: Secret Registry schema and collector
- 6.4: DNS Registry schema and collector
- 6.5: Template Registry schema
- 6.6: Deployment Provenance schema and recorder
- 6.7: Tier 2 Bootstrap State collector (reads snippets from Proxmox storage)
- 6.8: Bootstrap documentation generator update (pre-populate from Bootstrap State)

### Phase 7 — Service State (NEW)
- 7.1: Service State schema
- 7.2: Service Contract specification format
- 7.3: Service Contract collector (reads from proxmox-bootstrap/service-contracts/)
- 7.4: Service Contract validation (observed vs. declared)
- 7.5: Dependency graph updated to use Service Contracts as primary edge source
- 7.6: Recovery documentation updated with service contract validation steps

### Phase 8 — Network Topology as Code
- 8.1: Network topology schema
- 8.2: OpenTofu network resource declarations
- 8.3: Network topology collector (compare observed vs. declared)
- 8.4: Recovery documentation: Wave 0 network reconstruction from code

### Phase 9 — Reconstruction Playbooks
- 9.1: Reconstruction playbook schema and format
- 9.2: Reconstruction playbook generator (from state model)
- 9.3: Reconstruction playbook validator (dry-run / syntax check)
- 9.4: Integration with Wave 0.5 (template reconstruction automation)

### Phase 10 — Operational Documentation (NEW)
- 10.1: Operational documentation generator (drift summary, capacity trends, service health)
- 10.2: Scheduled operational doc refresh

### Phase 11 — Capacity Model
- 11.1: Capacity model schema
- 11.2: Capacity tracking in Tier 2 assessment
- 11.3: Capacity validation in recovery readiness scorer
- 11.4: Capacity trend analysis

### Phase 12 — Full Reconstruction Test
- 12.1: End-to-end reconstruction drill (full destroy + reconstruct from repos)
- 12.2: Reconstruction time measurement vs. estimate
- 12.3: Gap identification and remediation

---

## 12. Comparison: v3.0 vs. v4.0

| Concern | v3.0 | v4.0 |
|---|---|---|
| Cloud-Init | Not modeled | Bootstrap State, first-class |
| VM provisioning | Manual / implied | Bootstrap State + provenance |
| First-boot ordering | Not modeled | Bootstrap State constraints |
| Secret references | HUMAN fields | Secret Registry, auto-populated |
| Service dependencies | Heuristics | Service Contracts (declared) |
| Network topology | Observed only | Declared + observed + drift |
| VM templates | Not tracked | Template Registry |
| DNS / hostnames | Not tracked | DNS Registry, pre-populates commands |
| Reconstruction | Manual procedure | Reconstruction Playbooks (generated) |
| Capacity | Not validated | Capacity Model |
| Doc classes | 2 (bootstrap, recovery) | 3 (bootstrap, operational, recovery) |
| Recovery commands | `[VM_IP]` placeholders | Pre-populated from DNS Registry |
| State categories | 5 | 7 |

---

## 13. Summary Conclusions

1. **The lifecycle model is superior.** The six-layer model correctly identifies
   Cloud-Init as a distinct architectural layer between Infrastructure Definition and
   Configuration Management. The previous two-layer model skipped this entirely.

2. **The seven-state model is superior.** Bootstrap State and Service State address
   real gaps that would prevent automated reconstruction. The five-state model would
   leave an operator unable to reconstruct first-boot state from repository assets alone.

3. **Documentation should be three independent classes.** Bootstrap, Operational, and
   Recovery documentation serve different audiences, different phases, and different
   failure scenarios. They share a metadata model but are generated and consumed
   independently.

4. **Eight additional architectural elements are required** beyond Cloud-Init:
   Deployment Provenance, Secret Registry, Network Topology as Code, Service Contracts,
   Template Registry, DNS/Service Registry, Reconstruction Playbooks, and Capacity Model.
   Each addresses a specific gap in destroy-and-recreate reproducibility.

5. **The assessment engine's primary output should be reconstruction capability,**
   not reports. Every state category, every metadata field, and every documentation
   artifact should be evaluated against the question: "Does this enable automated or
   semi-automated reconstruction from repository state after a complete infrastructure loss?"
