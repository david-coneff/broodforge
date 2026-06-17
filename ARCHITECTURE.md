# Broodforge Architecture — Forging, Hatchery, Stargate

Codebase stamp: `2026-06-13_20-05-27_UTC_c0831145`
Date: 2026-06-13 UTC (AD-073–AD-090 added — AD-073: Kyverno; Phase 3: EventBus, capability engine,
execution broker, operational intelligence, incidents/advisories, secrets brokerage, governance integrity chain,
Control Nexus tiered dashboard, Portal; AD-083: codebase-hash stamp practice; AD-084: portal context indicator.)
Design history & rationale: docs/DESIGN-HISTORY.md
Full historical reviews (v4–v7): deprecated/
Stamp format: `YYYY-MM-DD_HH-MM-SS_<tz>_<shorthash>` — reproduce with `python3 proxmox-bootstrap/version_stamp.py`

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
| Workbooks | HTML (machine-generated via tessel-cli.js) | Execution records and recovery workbooks — self-contained, print-friendly; generated from Tessel Markdown (`.tessel.md`) sources |

---

## The Four Intelligence Phases

```
Phase A — Bootstrap Intelligence   (pre-k3s, stdlib Python, runs on operator machine)
  Process (first run):  Forging Process — produces forge package; deploys first node as hatchery
  Process (subsequent): Hatchery Process — produces spawn packages for broodlings
  Purpose:  Build the first-ever environment from bare metal; spawn additional nodes
  Produces: Forge package (first run) / spawn packages (subsequent runs)

Phase B — Operational Intelligence (k3s workload, runs continuously)
  Purpose:  Understand and document a running environment
  Produces: Living inventory, architecture docs, dependency maps, drift reports

Phase C — Recovery Intelligence    (k3s workload, triggered by Phase B)
  Process:  Stargate Process
  Purpose:  Generate phoenix packages — reconstituting a failed node's identity on new hardware
  Produces: Phoenix packages, readiness scores, recovery documentation

Phase D — Execution Intelligence   (k3s workload for generation; standalone for execution)
  Process:  Stargate Process (execution layer)
  Purpose:  Execute phoenix package scripts; capture failure packages for improvement loop
  Produces: Phoenix scripts (identity-preserving), HTML workbooks, failure packages, improvement loop
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
  6. Generated phoenix packages, spawn packages, and scripts
  7. HTML workbook execution records (exception: these are the execution audit trail)

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
├── workbooks/          HTML workbook generators
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

## Three Processes — Three Packages

```
FORGING PROCESS   → Forge package   → bare hardware becomes first hatchery
HATCHERY PROCESS  → Spawn package   → hatchery spawns broodlings (new identity, no conflict)
STARGATE PROCESS  → Phoenix package → failed node resurrected (identity preserved, hardware adapts)
```

The hatchery is what forging produces. Broodlings are what the hatchery process
spawns. Phoenix packages are what the stargate process generates for any node
— hatchery or broodling — that suffers catastrophic failure.

## Node Spawning — Hatchery Process / Stargate Process

The assessment engine reads the hatchery's current cluster state — all reserved
VMIDs, IPs, hostnames, k3s join tokens, cluster topology — and produces a
**spawn package**: a self-contained archive copied to the broodling after bare
Proxmox installation and executed there. The broodling never needs to query the
hatchery's API during execution; the manifest embedded in the package is the
point-in-time reservation snapshot it operates from.

### Hatchery Pre-Package Phase

*Runs on the hatchery before the package is sent to the broodling.*

#### Step 1 — Hardware Discovery (autonomous mode)

The hatchery is a trusted node on a secured LAN. Password-based SSH from the hatchery
to a fresh broodling is acceptable — no pre-exchanged key required. The spawn planner
generates a suggested temporary root password (readable passphrase format) before the
operator installs Proxmox. The operator uses that password during installation; the
hatchery connects automatically with it after install completes.

```bash
python3 spawn_hardware_discovery.py --host {broodling-ip} --user root --password-prompt
# → hardware-profile-{hostname}.json   (password-based via sshpass)
```

The temporary password is valid only until the spawn package's Cloud-Init phase
replaces it with a KeePass-managed credential. For interactive mode: no hardware
profile is needed on the hatchery; `spawn.sh` discovers hardware on the broodling at
runtime.

#### Step 2 — Assessment Engine: Cluster State Snapshot

Reads current cluster state and produces `spawn-manifest.json`, capturing all reserved
VMIDs, IPs, and hostnames, plus the Proxmox cluster join address and fingerprint and
k3s join tokens. This snapshot is the broodling's authoritative offline reference
during execution.

#### Step 3 — spawn-planner.py: Execution Mode & Service Selection

Execution mode is asked **first**, before any service selection:

- **Autonomous (default)** — triggers service selection on the hatchery; selection is
  locked into the package; `spawn.sh` runs end-to-end on the broodling unattended
  after the KeePass gate.
- **Interactive** — no service selection on the hatchery; the package includes all
  service scripts; `spawn.sh` presents the service menu on the broodling against actual
  hardware at runtime.

Service selection (autonomous mode only) offers three modes:

```
Mode 1 — Full mirror: select all services that fit this hardware
           Exclusions shown with reason; operator confirms or switches mode
Mode 2 — Select by group: Infrastructure / Platform / Intelligence /
           Monitoring / Applications — toggle whole groups, then fine-tune
Mode 3 — Select individually: every service listed with fit status:
  [✓] k3s-server        4 GB RAM req  /  14 GB avail
  [✓] prometheus        2 GB RAM req  /  fits
  [✗] loki              4 GB RAM req  /  insufficient
  Dependencies enforced (selecting nextcloud auto-selects longhorn if needed)
```

The intelligence baseline (Proxmox cluster membership, k3s worker, assessment/doc
engine visibility, `bootstrap-state.json` contribution) is always included and cannot
be deselected.

Disposition is stored as `disposition.execution_mode`, `disposition.services`
(autonomous only), and `disposition.excluded` (with fit reason, autonomous only) in
`spawn-plan.json`.

#### Step 4 — validate-spawn.py: Conflict Check

Conflict-checks all proposed allocations. RED on any VMID, IP, or hostname collision —
blocks package generation until resolved.

#### Step 5 — spawn-plan.json Assembly

Records the non-conflicting VMID block, IPs, hostnames, ZFS topology, bridge
definitions, only the VM roles / Cloud-Init / Ansible roles for selected services,
and k3s labels + taints derived from the service list (Flux schedules accordingly).

#### Step 6 — assemble-spawn-package.py: Package Assembly

Produces the self-contained archive delivered to the broodling:

```
spawn-package-{cell}-{hostname}-{ts}.tar.gz
  ├── spawn-manifest.json   (reservation snapshot — used offline)
  ├── spawn-plan.json       (disposition + conflict-validated allocations)
  ├── hardware-profile.json (disk IDs, NIC layout for host config)
  ├── scripts/spawn.sh + phase-00 through phase-06
  ├── opentofu/             (only disposition-declared VM roles)
  ├── cloud-init/           (snippets for disposition VMs only)
  ├── ansible/              (inventory additions + disposition-scoped role vars)
  └── spawn-workbook.html   (auditable execution record)
```

> Operator copies the package to the broodling — the only manual step after Proxmox install.

### Spawn Execution Phase

*Runs on the broodling. All phases use only the embedded manifest — no hatchery API calls.*

#### Host-Level Phases

These must complete before any VM can be created.

##### phase-00-host-bootstrap.sh

**[A] Hardware pre-flight — read-only, no changes made**

Re-scans actual hardware and diffs against the embedded `hardware-profile.json`:

```
├── Disk IDs in plan present + capacity matches
├── NIC names/MACs match profile (renumbering happens after kernel updates)
├── Available RAM ≥ plan VM total + 10% host overhead
├── No existing ZFS pool name conflicts with planned pool
├── No existing bridge name conflicts with planned bridges
└── Conflict re-validation vs spawn-manifest.json
    (catches any new hatchery reservations since package was built)
On mismatch → failure package with diff, exit without touching anything
On pass    → proceed to [B]
```

**[B] Host configuration — writes files, creates pool, activates network**

```
├── Set hostname + fix /etc/hosts   (pvecm add fails if host → 127.0.0.1)
├── Write bridge definitions        (/etc/network/interfaces from NIC layout)
├── ifreload -a                     (activate bridges without reboot)
├── zpool create                    (disk IDs confirmed by pre-flight)
├── pvesm add zfspool               (register pool as Proxmox datastore)
└── Configure apt repos
```

→ Broodling ready: bridges exist, storage registered, hostname correct.

##### phase-01-join-proxmox.sh

```bash
pvecm add <hatchery-address> --fingerprint <from manifest>
```

→ Broodling visible in Proxmox datacenter.

#### VM Provisioning Phases

Bridge and datastore names from phase-00 must exist before these run.

##### phase-02-vms.sh

```bash
tofu apply   # disposition-scoped tfvars; bridge/datastore names from phase-00
```

→ Disposition-declared VMs created on broodling.

##### phase-03-cloudinit.sh

Installs Cloud-Init snippets into the Proxmox snippet store, starts VMs (Cloud-Init
runs hostname, IP, SSH keys, packages), and polls for SSH readiness before proceeding.

#### Cluster Join Phases

These depend on VMs from phase-03 being reachable.

##### phase-04-join-k3s.sh

Ansible applies the `k3s-server` or `k3s-worker` role using the join token from the
manifest. → Broodling's k3s nodes join the hatchery cluster.

##### phase-05-promote-ha.sh *(conditional)*

Only runs if the broodling is the 3rd server node. Migrates from SQLite to embedded
etcd; distributes the control plane across hosts.

##### phase-06-verify.sh

Cluster health check: all disposition VMs running, conflict re-validation against live
state. On success, POSTs completion report to the hatchery receiver; `bootstrap-state.json`
updated on hatchery and committed to Forgejo.

#### Post-Spawn Automation

No operator action required after phase-06:

- **Flux CD** — schedules disposition-appropriate workloads on the broodling.
- **Assessment engine** — detects the broodling in the Proxmox API, scores against its declared disposition.
- **Doc engine** — regenerates topology with broodling included.

### Node Adaptation Model

**What adapts to each broodling's hardware:** ZFS pool topology (disk count/mix),
NIC bridge/bond layout, VM RAM sizing within available capacity,
IP/VMID/hostname allocations, services trimmed to what hardware can support.

**What stays identical across all nodes:** Naming convention, KeePass path structure,
Proxmox cluster membership, the intelligence collection baseline (assessment + doc
engine visibility), secret references.

### Disposition Model

A broodling's disposition is chosen at spawn time and recorded in `bootstrap-state.json`.
The assessment engine reads it — a broodling without `k3s-server` is not scored against
HA control-plane requirements. Disposition declares intent; the assessment engine scores
reality against that declared intent, not against the hatchery's full configuration.

**k3s topology decisions are disposition-driven, not just host-count-driven:**

| Disposition includes `control-plane`? | Result |
|---|---|
| No nodes with `control-plane` added | Workers only; existing control plane unchanged |
| 1st or 2nd server node added | Control plane grows; no topology change |
| 3rd server node added | SQLite → embedded etcd HA promotion; control plane distributed |

See Phase 12.E in [ROADMAP.md](ROADMAP.md) for full milestone detail.

---

## Key Architecture Decisions

| AD | Decision |
|---|---|
| AD-022 | k3s as primary application platform (over Podman) |
| AD-023 | Flux CD as GitOps engine (over ArgoCD — bootstraps into fresh cluster) |
| AD-024 | Forgejo as sole Git provider; external Git providers are mirrors only |
| AD-025 | HTML as standard machine-generated workbook format |
| AD-026 | Metadata YAML as primary source of infrastructure intent |
| AD-027 | Four intelligence phases with distinct runtimes (pre/post k3s) |
| AD-028 | Documentation engine is the first k3s workload |
| AD-029 | Phoenix packages are self-contained and offline-capable; identity is preserved even when underlying hardware changes |
| AD-030 | Failure packages are structured for LLM analysis |
| AD-031 | Documentation captures STATE and INTENT (what + why + which policy) |
| AD-039 | Node spawning produces a self-contained spawn package — assessment engine reads all hatchery reservations (VMIDs, IPs, hostnames, tokens) into a spawn manifest, operator selects the broodling's disposition (full mirror / by group / individually), conflict-checked scripts + hardware-adapted IaC are bundled into an archive the broodling runs after bare Proxmox install without querying the hatchery API |
| AD-040 | Initial deployment is forging — the forge package is a self-contained archive that takes bare Proxmox → operational hatchery via eight phases (discover → plan → validate → host → VMs → k3s → GitOps → intelligence); minimum viable forge deploys only the broodforge stack (doc engine + assessment engine), no user applications; user applications are added via GitOps after intelligence layer gates pass |
| AD-041 | Spawn packages support two execution modes. **Execution mode is asked first** on the hatchery, before any service selection: **Interactive** — no service selection at package-generation time; the package includes all available service scripts and spawn.sh presents the service menu on the broodling at runtime, evaluating actual hardware there. **Autonomous** (default) — triggers the service selection flow on the hatchery (full mirror / by group / individually); selected services are locked into the package; spawn.sh runs end-to-end on the broodling with no prompts beyond the KeePass unlock gate. Asking mode first means Interactive operators skip service selection entirely on the hatchery. |
| AD-042 | The KeePass database is **optionally** included in forge/spawn/phoenix packages. Including it does not compromise security because the database cannot be auto-unlocked — the operator must enter the master password at the KeePass unlock gate before any secret is accessed. If the database is not embedded, the installer prompts for a filesystem path (USB drive, local disk, or pre-agreed path) at run time. After the master password is entered once, the in-process secrets broker handles all subsequent lookups for the session without further operator input. No secret value is ever written to the node's filesystem in plain text. |
| AD-043 | User-facing password generation defaults to a readable passphrase format: `Capital.word.phrase.9` — leading capital letter, lowercase words, period separators, trailing single digit, 20-30 characters total. This format is human-memorable, typeable in a terminal without shell escaping, and satisfies most service requirements. For services that reject periods or special characters (detected automatically when a deployment phase fails with a credential error), broodforge offers to regenerate the affected credential as a plain alphanumeric password (same length, letters + digits only) and retries. Service-specific format restrictions are recorded in service-catalog.yaml and applied automatically in future deployments. For the KeePass master password, the operator may accept a generated passphrase, enter their own, or invoke KeePass's native generator. |
| AD-044 | Backup engine: **restic** (encryption mandatory for all non-KeePass layers; deduplication; versioned snapshots; retention policy; permanent checkpoint tagging). Transport: **rclone** as restic backend for providers not natively supported. Three layers: (1) KeePass DB — plain rclone copy, no restic layer (already AES-256 encrypted; restic would create an irrecoverable circular dependency); KeePass backup transport credentials stored in `forge-manifest.json`; (2) configuration state — all nodes' state, encrypted via restic; (3) application data volumes — opt-in, encrypted via restic. **Per-backup unique secrets**: each backup run rotates the restic repo password via `restic key add` + `key remove`; new password stored in KeePass at a timestamped path; secrets broker looks up the exact key per snapshot at restore time; KeePass entries for pruned snapshots cleaned up automatically; KeePass DB exempt. **Standard naming convention** (all names constructed programmatically): component prefixes `kdbx`, `cell-config`, `node-{hostname}`, `vm-{name}-{vmid}`, `ct-{name}-{ctid}`, `vol-{vm}-{vol}`, `svc-{name}`; timestamp `YYYY-MM-DD_HH_MM_SS` UTC; hash 8 hex chars (SHA-256 of content or snapshot ID prefix); restic repo paths `{root}/{cell_id}/{layer}/{component}/`; KeePass DB filenames `kdbx_{cell_id}_{timestamp}_{hash8}.kdbx`; snapshot set IDs `{cell_id}_{timestamp}_{run_hash8}`; restic snapshot tags `cell:`, `set:`, `component:`, `layer:`, `run:`; KeePass key paths `Backup/{layer}/{component}/{timestamp}/repo-password`. Destinations are an ordered chain of unlimited depth: each attempted, each upload verified, failures exposed, all-fail = RED. **Space-aware routing**: space probed before run; components routed to destinations with room (`primary` → `space_fallback` → `chunked_split`); chunked pieces linked by `snapshot_set_id`; restore assembles automatically via `backup_history` metadata. |
| AD-045 | Timezone preference is set by the operator during forging, stored in `bootstrap-state.json` as `vm_defaults.timezone`, and used by the documentation engine for all generated output. All timestamps display both UTC and local time to remain unambiguous across readers. The preference is updateable after forging without requiring a rebuild. |
| AD-046 | The forge package includes `lib/pve-suppress-nag.sh`, which patches the Proxmox web UI JavaScript to remove the non-enterprise subscription popup. Applied in phase-03 (host config). A dpkg post-invoke hook re-applies the patch when `proxmox-widget-toolkit` or `pve-manager` packages are updated, so the suppression survives Proxmox package upgrades. Proxmox Community Edition is fully functional without a subscription; this removes a commercial UI interruption. |
| AD-047 | **Headscale** (self-hosted Tailscale coordination server) is auto-configured during forge phase-03 (host config). The hatchery becomes both the spawning controller and the tailnet coordinator. Configuration: apt/binary install of headscale, systemd service, `broodforge` user/namespace created, hatchery registers with its own Headscale (`tailscale up --login-server https://hatchery:8080`), Headscale URL recorded in `bootstrap-state.json` as `network_topology.headscale_url`, Headscale API key stored in KeePass. Spawn packages in WAN mode embed a one-time Headscale auth key (generated via `headscale authkeys generate --expiration 1h`; not stored in KeePass). The broodling's `phase-00a` installs Tailscale and registers with the hatchery's Headscale before hardware discovery; after that, all SSH and cluster communication flows over the WireGuard tunnel the same as LAN. Broodlings remain permanent tailnet members after spawn; their tailnet IP is recorded in bootstrap-state.json alongside their LAN IP. LAN mode (same-subnet) uses direct SSH with the temporary root password and bypasses Tailscale entirely — Headscale is used only when the broodling is on a different network. |
| AD-048 | **Split-horizon DNS, DDNS, and TLS** — the hatchery runs **dnsmasq** (phase-03) for LAN DNS, generated from `dns-registry.yaml`. `host_identity.fqdn` is the single canonical address; spawn packages embed the FQDN and work from LAN and WAN without modification. Two supported DNS/TLS provider paths, chosen at forge time: (1) **Cloudflare** — `dns-lexicon` for DDNS, `certbot` + `python3-certbot-dns-cloudflare` for Let's Encrypt DNS-01 (wildcard cert `*.{domain}`), `certbot.timer` for auto-renewal, cert-manager ClusterIssuer with Cloudflare DNS-01 solver for k3s workloads; (2) **DuckDNS** — plain HTTPS GET for DDNS, `acme.sh` with built-in `dns_duckdns` solver for Let's Encrypt DNS-01 (wildcard cert `*.{subdomain}.duckdns.org`), acme.sh cron for auto-renewal, wildcard cert synced into k8s TLS secrets via `sync-cert-to-k8s.sh` (cert-manager not used for DuckDNS — no native DNS-01 support). Both paths: Headscale configured with TLS cert paths at forge time; SSL provider and cert paths stored in `bootstrap-state.json network_topology.ssl_*`. **Squarespace has no DNS API** — must delegate to Cloudflare. **inadyn archived Oct 2025 — not used.** See `docs/CLOUDFLARE-SETUP.md` and `docs/DUCKDNS-SETUP.md`. |
| AD-049 | **Guided Setup Framework** — all three deployment packages (forge, spawn, phoenix) offer four configuration modes, selectable at package-creation time or at execution time on the target node: (1) **Autonomous** (default) — all settings auto-calculated from discovery data; (2) **IP-Selective** — fully autonomous except the operator chooses IP addressing (management CIDR, gateway, per-VM IPs); (3) **Group-Manual** — a group-selector leader interface lets the operator choose which settings *groups* to configure manually (Network, Storage, VM Sizing, Identity, Security, k3s, Backup) while the rest are auto-configured; (4) **Full Manual** — operator walks through all settings with auto-suggestions at every step. At every manual prompt: the auto-suggestion is shown prominently; the operator may accept or override; if overriding, subsequent auto-suggestions are revised to be logically consistent with the choice (e.g., choosing a custom CIDR causes all subsequent IP suggestions to come from that CIDR); if the operator picks a value that conflicts with prior selections (duplicate VMID, overlapping subnet, RAM exceeds host), a warning is shown but the operator may proceed. The guidance modes are implemented by `proxmox-bootstrap/guided_setup.py` (GuidedSetupSession class + suggestion-revision engine + conflict detection) and integrated into forge-planner.py, spawn-planner.py, and phoenix package generation. |
| AD-050 | **Network Profiles** — two network deployment profiles selectable at forge time: **LAN-only (A)** — simple flat network, dnsmasq for local name resolution only (`.internal` domain), no Headscale, no external domain, self-signed TLS or none, spawn is LAN-only; **WAN-capable (B)** — split-horizon DNS (dnsmasq for LAN IPs, registrar/DDNS for WAN IP), Headscale for cross-network spawn, DDNS agent for dynamic WAN IPs, Let's Encrypt TLS via DNS-01. Profile stored in `network_topology.profile` in bootstrap-state.json. Autonomous or guided migration between profiles via `setup-network.py --migrate-to [lan|wan]`. Migration from LAN→WAN involves 7 steps (6 autonomous, 1 manual: router port forwarding). Migration from WAN→LAN involves 4 steps (all autonomous). `generate_dnsmasq_config()` renders correct dnsmasq config for both profiles from `dns_registry`. `setup_network.py` provides `LanNetworkConfig`, `WanNetworkConfig`, validation, auto-suggestion with field revision, migration plan generation, and state serialization. |
| AD-051 | **Human-readable HTML manifest alongside every machine-readable manifest (mandatory architecture pattern).** Every machine-readable artifact produced by broodforge (forge-manifest.json, spawn-manifest.json, phoenix-playbook.json) MUST have a corresponding self-contained HTML equivalent embedded in its package. The HTML file explains: what's inside the package, what each component does, key settings (cell_id, IPs, VMIDs, etc.), and what the operator must do. Implementation: `proxmox-bootstrap/html_package_manifest.py` provides `build_forge_manifest_html()`, `build_spawn_manifest_html()`, and `build_phoenix_manifest_html()`. Assemblers call these to produce `forge-manifest.html` and `spawn-manifest.html` embedded in each package. New manifest types must follow this pattern. |
| AD-052 | **EFF diceware passphrase as the default KeePass master password suggestion.** `keepassxc-cli generate` does not support word-based passphrases (CLI only supports character-class passwords). `lib/passphrase_eff.py` provides a stdlib-only EFF-derived diceware generator (~44 bits entropy at 4 words). `generate_master_password_suggestion()` defaults to `style="eff"`. The Capital.word.phrase.9 format remains available as `style="classic"`. |

| AD-053 | **Spawn completion reporting — /api/spawn-complete.** When phase-06-verify.sh on the broodling passes all health checks, it POSTs a JSON payload to `{hatchery_url}/api/spawn-complete` (the hatchery receiver endpoint). The payload includes the spawn-plan.json and hardware-profile.json. The hatchery calls `update_state_after_spawn()` to merge the broodling's allocated VMIDs, IPs, hostnames, and cluster role into bootstrap-state.json. The hatchery_url and optional receiver_token are embedded in spawn-manifest.json at package-generation time (derived from host_identity.fqdn and receiver port 9321). If the POST fails, the script logs a warning with manual fallback instructions. |
| AD-054 | **Migration commit convention.** Both `migrate-k3s-to-talos.py` and `migrate-k3s-to-ubuntu.py` call `_commit_migration_record()` after successfully writing bootstrap-state.json. Performs `git add <state_path> && git commit -m "migrate: {node} {from}→{to}"`. Non-fatal: git failure logs a warning and continues. Dry-run skips the commit. Operator is responsible for `git push` to Forgejo to trigger Assessment Engine reassessment. |

| AD-055 | **HTML is the sole output format for all generated documents.** ODS/ODT renderers (workbook.py, runbook.py, recovery_runbook.py, recovery_workbook.py, operational_report.py) are preserved in `doc-gen/renderers/deprecated/` for reference but are not called by `engine.py`. All new renderers must use `html_base.py` utilities and produce self-contained HTML. References to ODS/ODT as the workbook standard in the historical architecture reviews (`deprecated/ARCHITECTURE-REVIEW-v7.md` and earlier) describe an earlier design and are superseded by this decision. |

| AD-056 | **Spawn package self-assembly — no pre-generated artifacts required.** `assemble_spawn_package()` generates all phase scripts (spawn.sh, phase-*.sh) and IaC artifacts (opentofu tfvars, cloud-init snippets, ansible inventory) internally from the spawn-plan.json, matching the forge assembler pattern. An optional `artifacts_dir` override remains for operators who need to supply custom scripts. When `assemble-spawn-package.py` receives a bootstrap-state.json via `--state`, it calls `read_hatchery_state()` to derive a proper spawn-manifest with `hatchery_url` and `receiver_token`. WAN-mode spawn plans (disposition.network_mode=wan) automatically include the tailscale-join phase. This makes the operator two-step workflow: `spawn-planner.py --state ... → assemble-spawn-package.py --plan ... --state ...`. |

| AD-057 | **Pre-Install Forge Package and Image Builder — implemented (Phase 1.H, commit 072112e).** Today, `FORGING.md` requires "Proxmox VE installed on the target host" before forging begins (forge-manifest.json is generated on the operator's workstation, but the forge package itself is copied onto an *already-installed* host). Analysis of the `new/` proposed-revision corpus (Chapter 16 "Bootstrap and First-Node Architecture," Specification 70 "Bootstrap Forge Package and First-Node Deployment," Specification 148 "Canonical Bootstrap and First-Node Genesis Framework") names a real gap this surfaces: *"A BroodForge environment should be creatable without requiring an existing BroodForge deployment"* — and, more concretely, that bootstrap "Image Builder" tooling could "generate ISO images, USB installation media… derived from infrastructure knowledge." The proposed extension keeps broodforge's existing reference-stack-only philosophy (AD-040: target the validated reference stack, not universal platform support) but closes the remaining manual step: a workstation-side Image Builder that consumes `forge-manifest.json` and an unattended Proxmox VE installer answer file (Proxmox 8+ `answer.toml`) to produce a single bootable ISO/USB image bundling (a) the automated Proxmox VE installer, (b) the forge package, and (c) a first-boot systemd hook that runs `forge.sh` automatically once the freshly-installed host comes up — turning "bare metal → operational hatchery" into a boot-and-walk-away operation, with the same offline/air-gapped, hash-and-signature-verified artifact model already used for forge/spawn/phoenix packages (AD-042, AD-051). This is additive: the existing "operator already has Proxmox installed, run forge-planner.py" path remains the supported baseline; pre-install media generation is an optional alternative Step 0. **GUI addition (same session):** `proxmox-bootstrap/forge-image-builder.html` is a self-contained, offline-first operator wizard (no server required) that walks through all `generate-bootstrap-image.py` arguments with inline validation, live command preview, and a clipboard-copy output box. Follows the same dark-themed, stdlib-only, self-contained HTML pattern as FORGING.html and NODE-SPAWNING.html. A future server-invoke path (`/api/run-image-builder` endpoint in `broodforge_dashboard.py`) could stream builder output directly from the dashboard, but the clipboard-copy approach is the MVP and works entirely offline without any HTTP server. |
| AD-058 | **Second-factor authentication is the default for the KeePass unlock gate — not an opt-in.** `keepass_mfa.py` has supported TOTP (RFC 6238, authenticator-app-compatible) and YubiKey HMAC-SHA1 challenge-response since its introduction, but `KeePassInitConfig.mfa_method` and the `forge_keepass_init.py --mfa` flag both defaulted to `"none"`, and no guided-setup prompt surfaced the choice — in practice an operator had to know an undocumented CLI flag existed to enable it. Per direct operator instruction ("for high level functions of any kind, we should be requiring 2nd factor authentication as a default, not just a password"), the default is now `"totp"` (an authenticator app — no extra hardware to source); `"yubikey"` remains available for operators who prefer a hardware key; `"none"` remains selectable only as an explicit opt-out. **SMS-based and email-based OTP are not offered anywhere in `keepass_mfa.py` or `forge_keepass_init.py`, by deliberate design** — per the same instruction, both are weaker factors (SIM-swap and mailbox-compromise exposure) than an authenticator app or a hardware key, and broodforge will not add them as choices. This raises the baseline for the one gate that already protects every secret in the system (AD-042); it is additive (no new mechanism — `keepass_mfa.py` already existed and was tested) and reversible per-cell (`--mfa none` remains a supported, explicit choice). **Gap noted, not yet closed**: the choice is still CLI-flag-only — `guided_setup.py`/`forge_planner.py` do not yet surface an interactive MFA prompt alongside the other forge-time choices (KeePass master password style, network profile, etc.). Wiring MFA selection into the guided-setup flow (so the new default is *seen and confirmed* by the operator, not merely inherited silently) is recorded as a proposed follow-up — see Roadmap "Proposed Future Work." |
| AD-059 | **Recovery-Readiness Conformance Certificate (proposed scope — Phase 1.I, see Roadmap).** Reframes the `new/` corpus's ~13-document formal axiomatic-kernel/proof-system series (Root Manifest, System Graph, Reconciliation Engine, Deployment Certificate, hash-chained replay, idempotent-action invariants, trust boundaries, etc.) — not as "implement a parallel formal-verification subsystem" (rejected: heavier than broodforge's home-lab git+KeePass+restic trust model, AD-040's SHALL-NOT scope, and exactly the "implement the spec corpus verbatim" outcome the `new/` corpus deferral correctly avoided) but as naming two real, narrow concerns broodforge already addresses informally and could make verifiable: (1) **provable recovery readiness** — a reproducible demonstration that reconstruction would succeed, not just a declared score; (2) **observed-state ↔ intent-manifest conformance** — a defensible, evidenced answer to "does what's actually running match what was declared it should be?" Per direct operator decision, the resolution is to build **one** new generated artifact — `recovery-readiness-certificate.json` (+ HTML, AD-051 pattern) — as additive extensions to existing modules: `readiness.py` (the existing RRS/ACS/DCS/CRS/OSS scores — no new scoring system needed, the formal series names the same idea with different letters), `drift.py` (drift summary, optionally reclassified into structural/behavioral/performance/security buckets with a magnitude axis), `dependencies.py` (a SHA-256 graph hash over each dependency graph's canonical form), the snapshot/provenance store (a canonical-serialization + SHA-256 manifest hash recorded alongside each `history/` snapshot — tamper-evidence without changing the trust model), and Phase 12 drills (the latest `DrillRecord`). The certificate bundles all of these into one timestamped, signed-by-reference record: "as of this run, here is the evidence that this cell could recover, and here is what it was declared to be." Explicitly out of scope: Ed25519 root-of-trust chains, category-theoretic compositional proof objects, and formal certification "levels" with externally-audited conformance — none of that apparatus matches broodforge's actual threat model. See Roadmap Phase 1.I for the full scope, including the formal-concept → broodforge-mechanism translation table this decision is based on. |
| AD-060 | **Firm architectural constraint: no autonomous pathway may read and wield full root credentials against live hypervisors (proposed scope — Phase 1.J, see Roadmap).** Following the operator's request for a thorough evaluation of permanently storing each Proxmox host's root password in KeePass — which would give broodforge "a genuinely complete keystore of all node root passwords" and close the gap where a node that boots to Proxmox but fails to bring up its VM/k3s layer is currently a dead end requiring physical console access — the operator weighed the benefit against the risk and **explicitly ruled out any autonomous pathway that can read and wield full root credentials against live hypervisors.** The reasoning: today, even total compromise of the hatchery or KeePass yields at worst a narrow, time-boxed set of operational credentials for nodes mid-spawn (the temporary passphrase dies the instant Cloud-Init replaces it); a permanent "complete keystore of all node root passwords," reachable by an autonomous execution-broker pathway, converts that same compromise into root on *every hypervisor in the cell — the substrate everything else runs on* — turning any bug, misconfiguration, or compromise of *that one pathway* into an unbounded escalation. This is not a difference of degree from anything that exists in broodforge today; it is exactly the kind of unbounded autonomous action that AD-034/AD-040's "autonomous action is acceptable when bounded by safeguards and recoverability" standard (the F2 amendment, see `.ai/decisions.md` 2026-06-07) was never meant to license, because **root has no boundary by definition.** This stands as a firm SHALL-NOT, not a negotiable middle-ground position: no future development may build, or be interpreted as licensing, an autonomous code path that reads a hypervisor root credential from any store and wields it against a live hypervisor. **Two narrow, explicitly-named exceptions exist** — both already-established patterns, both bounded to a single node's *temporary*, soon-discarded credential, never the cell's permanent keystore: (1) **node spawning** — automatic interaction with a temporary root credential generated for the *new* node being provisioned (already implemented via Cloud-Init/AD-039: generated pre-install, used for SSH-based hardware discovery, discarded the instant Cloud-Init installs the KeePass-managed replacement); (2) **phoenix recovery packages** — by direct operator instruction, the same pattern extended to phoenix: a temporary root credential scoped to the phoenix setup session only, with a hard requirement — recorded in the generated phoenix runbook — that the operator rotates it once the recovery session completes (scoped as part of the Phase 9 phoenix-package design). Within this constraint, the accepted recovery design — **adopted as stated, all three parts implementation targets** — is: (a) constrained, forced-command recovery accounts (`ForceCommand`/`command=` in `authorized_keys`, a fixed read-only diagnostic menu, never a shell — the one piece of the recovery surface safe to query autonomously because its blast radius is bounded *by construction*); (b) full root retained only as human-unlock-gated break-glass behind the *existing* AD-042 gate (a documentation/policy annotation on the `pve0X-root-password` entries `secret-registry.yaml` already tracks — a storage change, not a privilege change, and no new autonomous pathway); (c) pre-generated spawn-media credentials, human-authorization-gated before the resulting node may join (extends the existing AD-043 passphrase pattern, gated the same way the existing autonomous-mode service-selection confirmation already is — AD-041). See Roadmap Phase 1.J for the full scoped implementation plan. |
| AD-063 | **Dynamic Analysis Self-Audit Integration (Phase 1.M, implemented 2026-06-09).** Extends Phase 1.L (AD-062) with a dynamic analysis tier implementing PAP-AUDIT §6 in full. **`DynamicHealthScore`** dataclass added to `continuous_assessment.py`: fields `hypothesis_failures`, `mutation_score_pct`, `bats_total/passed/failed`, `overall` (0–100; -1 = NOT_IMPLEMENTED), `assessed_at`, `error`, `not_implemented`. **`assess_dynamic_health()`** detects hypothesis tests via `@given` decorator scanning, runs mutmut results parser, and runs bats TAP output parser; returns `not_implemented=True` when no dynamic infrastructure is present (distinguishes "no infra yet" from "infra exists and something failed"). **Dashboard**: `_build_dynamic_health_subcard()` renders dynamic scores alongside static Code Health card; handles `not_implemented` state. **Remediation**: `_code_health_to_remediation_candidates()` extended for dynamic findings (hypothesis failures → HIGH, low mutation score → HIGH/MEDIUM, bats failures → HIGH). **Assessment → Queue wiring (R7-003)**: `run_continuous_assessment(repo_root, state, *, run_fn, now_fn)` is the first-class production caller — it calls `collect_health_remediation_candidates()`, converts each finding to a `RemediationProposal` (HIGH → ORANGE, MEDIUM → YELLOW), deduplicates by `{issue_id}:{action_type}` against active (non-terminal) queue entries (same key as `_dedup_proposals()` in remediation_planner.py), and submits new proposals via `add_proposal()`. CLI `__main__` block accepts `--manifest` / `--repo-root`. Shell wrapper: `proxmox-bootstrap/run-continuous-assessment.sh`. Systemd installer: `proxmox-bootstrap/setup-continuous-assessment-schedule.sh` (6-hour timer, same pattern as setup-operational-schedule.sh). **Contracts**: deal pre/postcondition contracts on `build_spawn_plan()`, `build_derived_vault_plan()`, `score_component()`. **beartype** wired in `conftest.py`. **pyproject.toml** dev deps added: hypothesis, mutmut, beartype, deal, schemathesis, atheris (Linux-only note); `[tool.mutmut]` config. **Test infrastructure**: hypothesis property tests in test_spawn_planner.py, test_vault_hierarchy.py, test_readiness.py; `tests/bash/forge_phase_test.bats` (exit-code tests with mocked commands); `tests/fuzz/fuzz_manifest.py` + `fuzz_spawn_planner.py` (atheris targets, no-op on non-Linux). **PAP-AUDIT §6 alignment**: all seven steps (beartype, deal, hypothesis, mutmut, bats, schemathesis config, atheris) implemented. 51 new tests (Phase 1.M) + 19 new tests (R7-003 wiring); full suite 4535 passed. |
| AD-062 | **Static Analysis Self-Audit Integration (Phase 1.L, proposed scope — see Roadmap).** Broodforge has systematic runtime assessment (readiness scoring, drift detection, Phase 26 remediation) but no equivalent assessment of the codebase itself. Phase 1.L adds a three-tier static analysis pipeline that feeds findings into the existing remediation system: **Tier 1** — `tools/run-static-audit.sh`, a standalone script that installs required tools (shellcheck via apt/brew/choco; ruff, bandit, vulture, detect-secrets via pip), runs them against all `.sh` files and generated script samples, produces a findings report at `.audit/static-audit-report.md` grouped by tool and mapped to reasoning patterns, and exits non-zero on any HIGH finding; **Tier 2** — pytest integration via `tests/static/test_shellcheck.py` (shellcheck on all `.sh` files + generated samples with minimal test manifests) and `pyproject.toml` default `--cov` options so coverage runs automatically; **Tier 3** — `assess_code_health()` in `continuous_assessment.py` (same pattern as `assess_readiness()`/`assess_drift()`) returning a `CodeHealthScore` dataclass with shellcheck finding count, bandit HIGH/MEDIUM counts, vulture dead-code percentage, coverage percentage, and an overall 0–100 score; a "Code Health" dashboard card in `broodforge_dashboard.py` alongside existing readiness/drift/dependency cards; HIGH findings from bandit/shellcheck surface as `RemediationCandidate` entries in the existing Phase 26 remediation pipeline, not a new system. **Out of scope**: cloud-based SAST, paid tools, SonarQube/Snyk/Veracode/GitHub Advanced Security, or any commercial license requirement. Baseline file `.secrets.baseline` (detect-secrets) is committed; generated reports (`.audit/*.json`, `.audit/*-report.md`) are gitignored. |
| AD-061 | **Granular Secret Access Silo Vault Hierarchy and User Provisioning (proposed scope — Phase 1.K, see Roadmap).** Following the operator's question about whether broodforge could support tiered, hierarchically-scoped secret access for *human* operators (a service operator who can manage their service but cannot reach the Proxmox root password, versus a "god-mode" sysadmin) — for which single-operator "god mode" is, and remains, the correct homelab default — this records the accepted design for the larger-org case the operator wants kept on the roadmap. **The constraint that shapes the design**: KeePass/KDBX databases are single-master-password, with no native per-user role layer inside one `.kdbx` file; building real per-user ACLs would require either an external identity-aware secrets broker (Vault-style — which contradicts broodforge's offline-first, stdlib-only, network-independent design constraints, `.ai/CURRENT_STATE.md` "Key Design Constraints," and AD-042's entire premise that the KeePass file can be embedded in offline packages with no server dependency) or **multiple derived vaults**, each scoped to a declared subset of secrets with its own independently-generated master password — "more vaults derived from the one vault," not "one vault with roles bolted on." The latter is the only approach that fits broodforge's existing architecture with no new dependency and no change to its trust-model foundations, and is the design adopted: a **`Role`/`Scope` registry** (a new authoritative YAML, following the existing 10-metadata-file pattern in `data-model/`) naming roles, hierarchical scopes expressed as glob patterns over `secret-registry.yaml`'s existing `owning_cell`/`required_by` vocabulary (`cell-1/*`, `cell-1/node-1/*`, `cell-1/node-1/vm-3/*`, or by `secret_type`/`required_for` facet), and which humans hold each role; and a **`derive-scoped-vault` generator** that reads the canonical KeePass DB plus the Role/Scope registry and produces a derivative `.kdbx` containing only in-scope entries, with its own freshly-generated passphrase (reusing `generate_master_password_suggestion()`/EFF generators, AD-043/AD-052) — the canonical "god mode" database remains exactly what it is today, broodforge's permanent default. **Two operator-directed expansions beyond the original sketch**: (1) **higher-tier vaults must include records of the access credentials for lower-tier scopes** — each derived vault's generated passphrase is itself written as an entry in the next tier up (ultimately the canonical god-mode vault), so a god-mode operator can always recover any scoped vault's passphrase from their own vault, generalizing the per-backup unique-secret rotation bookkeeping pattern already established in AD-044 ("a vault of vaults," not an isolated set of derivatives); (2) **a mechanism for creating users at the VM level and the Proxmox level**, with default account templates corresponding to the proposed scope divisions (e.g., service operator / node sysadmin / god mode), each provisioned at forge/spawn time with access to exactly its corresponding scoped vault and nothing beyond it. **Authorization model**: only holders of the canonical vault can mint scoped vaults or scope-tier user templates — true by construction ("you can only derive a scope you can already see the contents of"), matching who is already trusted to run `forge-planner.py`/`spawn-planner.py`. **Revocation = rotate + reissue**, documented up front as an honest non-guarantee — a derived vault cannot leak ciphertext it never received, which is arguably a *stronger* property than a layered ACL on a database the holder already possesses in full; this is a property of the offline-first model, not a flaw in this design specifically. Explicitly not proposed: real-time per-user audit logs (would require the broker/network dependency broodforge deliberately avoids, though "scoped vault X was used" correlation is possible for free since each derived vault is a distinguishable credential), or cryptographic enforcement of scope beyond "the derived vault simply does not contain out-of-scope ciphertext." See Roadmap Phase 1.K for the full scoped implementation plan. |

| AD-064 | **Kubernetes User Registry and Zero-Knowledge User Provisioning (Phase 1.U, implemented 2026-06-10).** Broodforge services run in Kubernetes, but user accounts were per-service — no central record of who should have access, making rebuild-time re-provisioning a manual effort. Phase 1.U adds a **user registry above the Kubernetes layer** (`config/user-registry.json`, schema in `proxmox-bootstrap/user_registry.py`) tracking all users with their per-service enrollment, disposition (active / archived / pending-deletion), and key-throw-away status. **Onboarding flow**: `forge-onboard-user.sh` generates a strong password + TOTP secret per service, stores both in master KeePass under `Broodforge/users/<user>/<service>/`, and produces an HTML onboarding package (`lib/forge-onboarding-pdf.py`) with embedded TOTP QR codes — HTML is the primary format (universally readable), PDF is optional via `--also-pdf`. **Granular service enrollment**: users default to all services or a sysadmin-chosen subset; `--add-service` enrolls an existing user in a new service and generates credentials for just that service. **Provisioning**: `forge-provision-users.sh` reads the registry and re-provisions all active users into k8s services at rebuild time, eliminating manual re-registration; uses a `provision` flow (auto-apply stored password) for normal users and a `reset` flow (temp password + notify) for users who threw away their key. **Zero-knowledge**: `forge-throw-away-key.sh` atomically deletes KeePass credentials and sets `key_thrown_away=true` in the registry — strictly ordered (KeePass deletion first, flag set only on success) so the registry accurately reflects whether admin-held credentials exist; after throw-away the admin can delete accounts but cannot impersonate users. **Offboarding**: `forge-offboard-user.sh` deletes service accounts, removes KeePass credentials, updates the registry, and sets disposition to archived (or removes the record entirely with `--remove-from-registry`). **Service adapter convention**: each service gets `_provision_<service>()` in `forge-provision-users.sh` and `_offboard_<service>()` in `forge-offboard-user.sh`; documented in `docs/USER-REGISTRY.md`. **Sidecar GUI surface**: user list, onboard, throw-away-key, provision, and offboard actions are all CLI-shelled operations designed for sidecar GUI integration. |

| AD-065 | **Authentik as k8s identity provider (Phase 2.A, implemented 2026-06-10).** Authentik chosen over Keycloak: lighter deployment (single Helm chart, no separate admin UI binary), Python-based (simpler to inspect and extend in the broodforge context), OIDC-first (SAML and LDAP as secondary protocols — matches broodforge's service surface), native k8s Helm deployment matching the Phase 2 deployment pattern. Keycloak is heavier (Java, separate KC admin CLI binary, more resource-intensive for a homelab reference stack). All Authentik admin credentials in master KeePass; service OIDC client secrets in forge-autonomous.kdbx child DB (AD-061 scope); OIDC client secrets subject to `forge-rotate-credential.sh` rotation ceremony. Local Authentik accounts work offline; cloud upstream providers (Google, GitHub) are optional and opportunistic. |
| AD-066 | **cert-manager for TLS certificate lifecycle (Phase 2.B, implemented 2026-06-10).** cert-manager chosen as the Kubernetes-native TLS automation layer. Integrates with ACME/Let's Encrypt DNS-01 already established in Phase 1.F.8d (Cloudflare and DuckDNS paths); ClusterIssuer CRDs make issuer selection declarative and auditable. The alternative — manual certificate rotation — was the baseline before Phase 2.B and was the primary source of the "operator must remember to rotate TLS certs" gap. cert-manager's Certificate CRD provides expiry observation without polling; cert-manager-state.json tracks expiry for dashboard alerting (CRITICAL ≤7d, WARNING ≤30d). No credentials in the k8s manifest — ACME account key is a k8s Secret reference. |
| AD-067 | **kube-prometheus-stack for cluster observability (Phase 2.C, implemented 2026-06-10).** kube-prometheus-stack (Prometheus + Grafana + Alertmanager as a unified Helm chart) chosen as the k8s observability standard. Rationale: the stack is the de-facto k8s monitoring default; Grafana's datasource/dashboard model integrates cleanly with Phase 2.D (Loki datasource), Phase 2.E (Longhorn StorageClass metrics), and the existing assessment engine. Alternative — Datadog/New Relic — requires cloud dependency (contradicts offline-first design). VictoriaMetrics is a valid alternative for long-term storage but adds operational complexity with no benefit at homelab scale. Grafana admin password sourced from forge-autonomous.kdbx via stdin exclusively — never env var, CLI arg, or values file. |
| AD-068 | **Loki + Promtail for log aggregation (Phase 2.D, implemented 2026-06-10).** Loki chosen over Elasticsearch/OpenSearch: lighter resource footprint (single-binary mode for homelab scale), Grafana-native (unified Grafana UI for metrics and logs without an additional data source server), no inverted index overhead (logs stored as compressed chunks, queried via LogQL). Promtail as the DaemonSet log shipper: native Loki protocol, CRI log format parsing (required for k3s/containerd), control-plane node toleration built in. Elasticsearch would require a dedicated JVM heap (≥4GB), separate Kibana, and additional operational knowledge — all excess for the broodforge reference stack target. Loki single-binary mode is appropriate for a single-cell deployment; operators can migrate to Loki distributed mode independently if log volume demands it. |
| AD-069 | **Longhorn for persistent storage (Phase 2.E, implemented 2026-06-10).** Longhorn chosen as the k3s default StorageClass for replicated block volumes. Rationale: Kubernetes-native (runs fully inside the cluster — no separate Ceph or NFS server to manage), default replica count 2 balances redundancy against capacity on homelab clusters (where nodes frequently share disks), built-in backup to S3/NFS targets integrates with Phase 1.O (CQB backup engine) at the block-volume layer, and Longhorn Manager exposes node disk management via its own CRD/API. Alternative — NFS — has no replication and requires an external NFS server. Ceph requires ≥3 dedicated storage nodes. Longhorn is the simplest path from "k3s cluster" to "replicated PVCs" with no external infrastructure. |
| AD-070 | **Flux CD GitOps wiring (Phase 2.G, implemented 2026-06-10).** Extends AD-023 (Flux CD as GitOps engine). Phase 2.G provides the broodforge management layer: GitSource and Kustomization registry in flux-state.json, manifest generation for source.toolkit.fluxcd.io/v1 GitRepository and kustomize.toolkit.fluxcd.io/v1 Kustomization CRDs, and the forge-init-flux.sh KeePass-gated bootstrap. SSH-key authentication only — no GITHUB_TOKEN or OAuth credential string in subprocess argv or environment (following the no-credentials-in-argv constraint established in Phase 2.A–2.F). Flux bootstrap delegates entirely to the `flux bootstrap git` CLI; no reimplementation of bootstrap logic in Python. |
| AD-071 | **Velero for workload backup (Phase 2.H, implemented 2026-06-10).** Velero chosen for Kubernetes workload backup (PVC snapshots + etcd state). Rationale: vendor-neutral (supports S3, Azure Blob, GCS, MinIO), provider credentials via `existingSecret` k8s reference (never inlined in Helm values — satisfying the no-credentials-in-values constraint), pod volume backup via restic (consistent with the restic-first backup philosophy of AD-044), and the restore path is tested and well-documented. Velero backup schedules are registered in velero-state.json and applied to the cluster as VolumeSnapshotLocation/Schedule CRs. Recent backup sync is capped at MAX_RECENT_BACKUPS=50 entries to prevent unbounded state growth. |
| AD-072 | **Linkerd for service mesh (Phase 2.I, implemented 2026-06-10).** Linkerd chosen over Istio for mTLS pod-to-pod encryption. Rationale: Linkerd is significantly lighter (no Envoy sidecar, pure-Go proxy), mTLS is enabled by default without per-service configuration, and the control plane installation is a single CLI pipeline (`linkerd install | kubectl apply -f -`). Istio requires a significantly larger control-plane footprint and per-service EnvoyFilter configuration that adds operational overhead disproportionate to the homelab reference stack target. Namespace enrollment uses `linkerd.io/inject=enabled` annotation plus a Server CR (policy.linkerd.io/v1beta3) for default-deny mTLS enforcement — the Server CR is the declarative expression of the mTLS policy and is the correct pattern for Linkerd v2.14+. Three `shell=True` subprocess calls in linkerd_manager.py for the piped install commands are a known pattern (see R8-001 in AUDIT-FINDINGS.md); command strings are hardcoded constants (not user-supplied), so injection risk is negligible; documented in AUDIT-FINDINGS.md R8-001. |
| AD-073 | **Kyverno policy enforcement (Phase 2.J, proposed).** Kyverno chosen as the Kubernetes-native policy engine over OPA/Gatekeeper. Rationale: Kyverno policies are Kubernetes resources (CRDs) rather than Rego — no separate language to learn, and policies apply the same GitOps/Flux reconciliation as any other k8s manifest. Policy scope: (1) image registry allowlist — only images from Forgejo and approved registries admitted; (2) resource limit enforcement — all Pods must declare CPU/memory limits (prevents unbounded resource consumption on the homelab cluster); (3) no-privileged-containers — reject Pods with `securityContext.privileged: true` outside the platform namespace. Policy CRDs stored in `k8s/policies/kyverno/`; managed by Flux. Admission webhook operates in `enforce` mode for all non-platform namespaces; platform namespace uses `audit` mode to avoid locking out cluster bootstrap. Kyverno reports surface in the Control Nexus dashboard (Phase 3.J) as policy violation counts per namespace. |
| AD-074 | **EventBus — internal event streaming platform (Phase 3.A, proposed).** NATS JetStream chosen as the event streaming backbone over Kafka and Redis Streams. Rationale: NATS is a single Go binary with no JVM/ZooKeeper dependency (critical for homelab resource constraints), JetStream provides durable, at-least-once delivery and consumer groups comparable to Kafka, and the NATS operator (nats.io/nats-operator) deploys cleanly into k3s via Helm. Kafka requires a separate ZooKeeper ensemble or KRaft cluster and minimum 3 brokers for durability — excessive for a single-cell homelab. Redis Streams lack schema enforcement and cross-service fan-out without additional tooling. EventBus topics follow the convention `bf.<domain>.<event_type>` (e.g., `bf.node.health_changed`, `bf.remediation.proposal_created`). All Phase 3 components publish and subscribe through the EventBus; no direct inter-service RPC calls. Schema registry: Avro schemas stored in `eventbus/schemas/`; producers validate before publish; consumers validate on receipt. |
| AD-075 | **Capability engine (Phase 3.B, proposed).** The capability engine is the authoritative registry of what broodforge knows how to do — a structured catalog of `Capability` records (name, preconditions, postconditions, implementation_ref, risk_level, rollback_ref) stored in `capability-engine/catalog.yaml`. It bridges the gap between "what the execution broker can run" and "what the remediation planner proposes" by providing a queryable surface: `capabilities.query(tags=["storage", "k3s"])` returns all capabilities matching those facets. The execution broker (Phase 3.C) resolves a `RemediationProposal.action_type` → `Capability` before executing; if no capability is found, the proposal is held for operator review rather than silently failing. Capability records are versioned alongside the codebase — changing a capability's preconditions changes the hash (covered by the codebase stamp, AD-083). |
| AD-076 | **Execution broker (Phase 3.C, proposed).** The execution broker is the sole authorised pathway for autonomous remediation actions. It receives approved `RemediationProposal` records from the Phase 26 remediation planner, resolves each to a `Capability` (Phase 3.B), checks all preconditions, executes the implementation, verifies postconditions, and publishes the result to the EventBus (Phase 3.A). **Operator gate**: any proposal with `risk_level >= HIGH` requires an explicit operator approval token before the broker will proceed — the broker does not self-approve high-risk actions. Dry-run mode (default for new capability registrations) executes the precondition checks only and reports what *would* happen. All broker actions are logged to the governance integrity chain (Phase 3.I) as `execution_event` records so the chain provides a tamper-evident audit trail of every autonomous action taken. |
| AD-077 | **Operational intelligence — time-series prediction and anomaly detection (Phases 3.D–3.E, proposed).** Prophet (Meta's time-series library) chosen over ARIMA and LSTM for resource forecasting. Rationale: Prophet is Python-native, requires no GPU, handles homelab-typical irregular sampling and missing data gracefully, and produces human-interpretable trend + seasonality decompositions alongside its forecast. ARIMA requires stationary series and manual parameter tuning. LSTM requires a GPU or extended CPU training time — incompatible with the homelab reference stack constraint. Anomaly detection uses Isolation Forest (scikit-learn) over DBSCAN: Isolation Forest is O(n log n), works on high-dimensional node telemetry without distance-metric tuning, and produces per-point anomaly scores that map cleanly to dashboard severity tiers. All predictions are published to the EventBus and surfaced in the Control Nexus dashboard (Phase 3.J) as projected resource exhaustion alerts with estimated time-to-threshold. |
| AD-078 | **Incidents and advisories subsystem (Phase 3.F, proposed).** `IncidentRecord` and `AdvisoryRecord` are first-class data structures in the broodforge data model (`data-model/incident.json`, `data-model/advisory.json`). An incident is an unplanned degradation or outage affecting a node, service, or cluster component; an advisory is a proactive notification (upcoming capacity threshold, pending certificate expiry, drift above baseline) that does not yet require action but warrants operator awareness. Both are published to the EventBus (`bf.incident.*`, `bf.advisory.*`) and rendered in the Control Nexus dashboard (Phase 3.J). Access-request submissions from the Portal (Phase 3.K) create an `IncidentRecord` of type `access_request` and are routed to the operator approval queue — this is the unifying abstraction that lets both operational incidents and user-initiated requests flow through the same triage surface. |
| AD-079 | **Secrets brokerage (Phases 3.G–3.H, proposed).** The secrets broker is the runtime interface between k8s workloads and the KeePass credential store. It replaces ad-hoc `keepass_gate.py` calls scattered across deployment scripts with a single, audited, rate-limited internal service. Architecture: a sidecar container (or init-container) per workload namespace requests credentials via a Unix socket using a short-lived workload identity token issued by Authentik (Phase 2.A); the broker verifies the token, looks up the credential in KeePass, returns it once over the socket, and never writes it to disk or env. The broker maintains a per-session credential cache invalidated on workload termination. All accesses logged to the governance integrity chain (Phase 3.I) as `credential_access_event` records. This closes the gap where the existing in-process KeePass gate cannot be audited across workload restarts without reading log files. |
| AD-080 | **Governance integrity chain (Phase 3.I, proposed).** An append-only, hash-linked checkpoint log providing tamper-evident audit of governance state changes across the federation. Each checkpoint record contains: `chain_hash = SHA-256(prev_chain_hash + state_merkle_root + timestamp + tz)`, `state_merkle_root` (SHA-256 over canonical JSON of all active policy, capability, and execution-broker configuration), `event_type` (governance_checkpoint | migration_approval | migration_event | execution_event | credential_access_event), and the event payload. **Migration approval proof**: before any governance schema migration (policy engine config, capability catalog, execution broker rules), a `migration_approval` record is sealed into the chain with `from_schema_hash`, `to_schema_hash`, `approved_by`, and `approval_chain_hash`. After migration, a `migration_event` record is appended with `adopted_schema_hash` and `approval_ref`. The audit tool compares these two hashes; a mismatch identifies the exact checkpoint at which an unapproved change occurred, giving a precise rollback target. Chain storage: `integrity/chain.jsonl` — one JSON record per line, never deleted, append-only enforced at the filesystem layer. `integrity/` lives at the repository root, peer to `proxmox-bootstrap/` (independent of bootstrap scope). |
| AD-081 | **Control Nexus — tiered operator dashboard (Phase 3.J, proposed).** The Control Nexus is the primary operator interface, structured in three tiers that match the broodforge architecture hierarchy: **Node tier** — per-node health (existing `broodforge_dashboard.py` surface extended with Phase 3 telemetry: EventBus consumer lag, execution broker queue depth, integrity chain tail hash); **Cluster tier** — cross-node aggregate view: readiness scores, drift summary, Kyverno policy violation counts, predicted resource exhaustion timeline, open incidents and advisories, remediation queue; **Federation tier** — stub in Phase 3.J, fully implemented in Phase 4: cross-cluster health roll-up, federation governance chain status. Control Nexus is implemented as an extension of the existing `broodforge_dashboard.py` Flask application, not a separate service — new tier tabs are rendered server-side, consistent with the existing HTML-first, stdlib-compatible pattern. |
| AD-082 | **Portal — user self-service hub (Phase 3.K, proposed).** The Portal is the end-user interface, distinct from the Control Nexus (operator-only). It provides: OIDC login via Authentik (Phase 2.A); service registry panel (services the authenticated user is enrolled in, with per-service status and direct links); account management (display name, SSH key, session management); access request flow (submits an `IncidentRecord` of type `access_request` to the operator queue via Phase 3.F). The Portal does not expose k8s, Proxmox, or any administrative API — all administrative capability remains in the Control Nexus. Implemented as `portal/` — a self-contained Flask (or static + OIDC-proxy) application, separate from the Control Nexus Flask app, with its own Authentik OIDC client. |
| AD-083 | **Codebase-hash versioning stamp (implemented 2026-06-13).** All broodforge documentation headers use a reproducible stamp format `YYYY-MM-DD_HH-MM-SS_<tz>_<shorthash>` in place of semantic version numbers (e.g., `v7.1`). The `<shorthash>` is the first 8 hex characters of a SHA-256 computed over all codebase files (Python, shell, YAML, TOML, tests) sorted by POSIX path, with documentation files excluded to avoid the self-referential hashing problem (a document cannot embed its own hash before it is written). The `<tz>` component (e.g., `UTC`, `MST`) is the timezone label of the timestamp, preventing ambiguity when stamps are generated in different timezone contexts. The canonical generator always uses UTC. Exclusion rules are codified in `proxmox-bootstrap/version-hash-schema.yaml` — the schema file is itself a `.yaml` and therefore IS included in the hash, so changing exclusion rules changes the stamp. Implementation: `proxmox-bootstrap/version_stamp.py`; schema is both human- and machine-readable (pyyaml or stdlib fallback parser). |
| AD-084 | **Portal federation/cluster context indicator (Phase 3.K, proposed).** Every Portal page displays a small, inconspicuous chip in the bottom-right corner showing the current federation name and cluster identity (e.g., `homelab-fed / hatchery`). Purpose: when a user has access to multiple broodforge environments, the chip provides unambiguous context about which system they are operating in, similar to a browser secure-site| AD-085 | **Cell codename convention — adjective-animal format.** Infrastructure cells may be identified by either a numeric index (`cell-1`, `cell-2`) or a human-readable codename in `adjective-animal` format (e.g., `flying-bat`, `crouching-tiger`, `silent-wolf`). Codenames are optional but strongly encouraged for any deployment with more than one cell: they are shorter, more memorable, and easier to distinguish at a glance than numeric IDs in logs, KeePass entry paths, backup manifests, and verbal communication. Codename rules: (1) exactly one adjective, one animal, joined by a single hyphen; (2) all lowercase, no spaces, no digits; (3) unique within a federation; (4) once assigned, the codename is permanent — renaming a cell requires a migration record in the governance integrity chain (AD-080). Generation: `proxmox-bootstrap/cell_codename.py` offers `suggest_codename(existing)` at forge time; operator may accept, regenerate, or supply their own. Codenames appear in `forge-manifest.json` as `cell_codename`, in KeePass entry alias paths, in backup manifest component prefixes, and in all generated HTML companions. Numeric `cell_id` remains the canonical machine key; `cell_codename` is a display alias stored in `bootstrap-state.json`. Word lists: `data-model/cell-codename-words.yaml`. |
| AD-086 | **Cryptographic Asset Management (CAM) — Secrets Broker and Artifact Broker abstractions (proposed).** Broodforge deployments involving LUKS-encrypted volumes, encrypted backup images, or other cryptographic material require a unified model for referencing secrets and binary artifacts without embedding raw values in packages or scripts. The CAM layer defines two broker abstractions: (1) **Secrets Broker** — resolves `secrets://` URIs to credential values at runtime, authority-agnostically. URI scheme: `secrets://<authority-class>/<asset-type>/<scope>/<label>` (e.g., `secrets://crypto/luks/node01/rootfs/passphrase`). The broker prompts the operator to unlock the configured authority (initially KeePass) and then fulfils all secret references for the session — matching the AD-042 KeePass unlock gate. Authority-pluggable: KeePass is default; any provider implementing the `SecretsAuthority` protocol can replace it without changing callers. (2) **Artifact Broker** — resolves `artifacts://` URI references to binary objects (LUKS headers, certificate PEM files, key backup archives). URI scheme: `artifacts://<authority-class>/<asset-type>/<scope>/<label>`. Initial authority stores LUKS headers as KeePassXC entry attachments (`AssetID` custom field = URI; binary attachment = raw bytes; `<label>-sha256` custom field = integrity hash). Phoenix package assembler replaces all raw secret values and artifact paths with URI references; Phoenix runner resolves URIs via the broker at restore time, never storing plaintext in the package. Forge-planner.py enumerates crypto assets and writes `crypto-assets.yaml` — the authoritative asset registry — with one entry per asset: `asset_id`, `asset_type`, `secret_ref`, `artifact_ref`, `validation`, `recovery_procedure`. Schema: `data-model/crypto-asset.yaml`. |
| AD-087 | **CAM — KeePassXC as initial authority and per-asset validation (proposed).** For each cryptographic asset, the operator creates a KeePass entry with: `Title` = human-readable label; `AssetID` (custom field) = full `secrets://` or `artifacts://` URI; `Password` = secret value; binary attachment = artifact bytes; `<label>-sha256` (custom field) = hex SHA-256 of attachment. The `crypto-assets.yaml` registry records the KeePass Group path (`keepass_group: Crypto/LUKS/node01`) so the broker navigates to the entry without scanning the full database. Validation: `cam_validate.py` runs three checks per asset — (1) *Presence*: URI resolves to a non-empty value; (2) *Integrity*: SHA-256 of fetched bytes matches stored hash; (3) *Recovery simulation* (opt-in, scheduled by Reconstruction Drill — Phase 12): asset is used in a dry-run of its recovery procedure against a non-production target. All results appended to the readiness certificate (AD-059). Gap closed: without CAM, there is no systematic check that LUKS headers and passphrases stored in KeePass at forge time remain valid and accessible at recovery time — a drift or accidental deletion would only surface mid-incident. CAM's validation makes this detectable in a scheduled drill. |
| AD-088 | **BFVault — browser-native encrypted secrets backup vault (proposed).** BFVault is a portable, zero-dependency backup artifact for secrets, credentials, and binary cryptographic assets (LUKS headers, KeePass `.kdbx` files, TLS certificates, SSH keys). It is the "break glass" backup that requires nothing beyond a modern browser to open. Design constraints: (1) **zero dependencies** — all cryptography uses the native Web Crypto API (AES-256-GCM, PBKDF2-SHA256 at 600,000 iterations; no WASM, no CDN); (2) **plaintext on unlock** — the outer artifact is strongly encrypted; once the passphrase is supplied, every asset and binary attachment is visible in the browser without any further tool; (3) **outer ZIP, inner JSON** — the exported `.zip` contains `meta.json` (plaintext KDF parameters: salt, IV, algorithm), `payload.enc` (AES-256-GCM ciphertext), and `bfvault.html` (self-contained browser viewer/editor that can re-export an updated vault); the inner payload is a single JSON document with all assets and base64-encoded binary attachments, avoiding a nested ZIP and the need for any ZIP library at read time; (4) **self-replicating exporter** — when exporting a new vault, `bfvault.html` serialises `document.documentElement.outerHTML` and includes itself in the output ZIP, so every exported vault is also an opener. **Asset types**: `credential`, `ssh-key`, `luks-header`, `certificate`, `totp`, `recovery-codes`, `keepass-database`, `note`, `generic-binary`. **KeePass integration**: the tool generates a standard KeePass XML export (importable via KeePassXC → Database → Import) with `AssetID` and `SecretsPath` custom fields set to the broodforge `secrets://` URI (AD-086), so importing the XML immediately wires up the secrets broker reference paths. **Relationship to walkthrough export**: the `@credential` field export in `md_to_html.py` (AD-036) uses the same cryptographic primitives and outer-ZIP structure, but its inner payload is a walkthrough-specific content ZIP rather than a BFVault JSON envelope; the two formats are parallel, not interchangeable. Schema: `data-model/bfvault-schema.yaml`. Tool: `docs/bfvault.html`. |
| AD-089 | **CAB — Cryptographic Asset Bundle, single-asset portable unit (proposed).** A CAB is the single-asset subset of BFVault: it packages one cryptographic asset for transfer, escrow, or sharing with a third party without exposing the full vault. Structure: same outer ZIP format as BFVault (`meta.json` + `payload.enc` + `cab-open.html`); inner payload contains only one asset's `manifest.json`, `fields.json`, `attachments/`, and `keepass-import.xml`. A CAB can be imported into a BFVault (the `bfvault.html` tool has an "Import CAB" function that decrypts the CAB and merges the asset into the current vault session). CABs are generated either from `bfvault.html` (export one asset as a CAB) or as standalone exports from walkthrough companions whose sole purpose is capturing a single credential set. The CAB format supersedes the standalone `decrypt.html` + `payload.enc` pattern used in the AD-036 walkthrough export — the walkthrough export will migrate to producing a CAB-shaped inner payload in a future iteration. Passphrase for a CAB may differ from the parent vault — this is intentional, as CABs are designed for selective disclosure. Schema shares `data-model/bfvault-schema.yaml` (the single-asset section). |
| AD-090 | **SecretsAuthority adapter interface — authority-agnostic secrets resolution (proposed).** The `SecretsAuthority` protocol is the single interface point that decouples the secrets broker (AD-086) from any specific vault implementation. An authority must implement: `resolve(uri: str) → str` (return secret value for a `secrets://` URI); `resolve_artifact(uri: str) → bytes` (return raw bytes for an `artifacts://` URI); `health_check() → bool` (confirm authority is reachable and unlocked). Current implementations: **KeePassXCAuthority** (AD-087, initial) — navigates KeePass group/entry by `keepass_group` + `AssetID` field; **BFVaultAuthority** (AD-088/089) — decrypts vault JSON and resolves from the in-memory asset map. Planned adapters: HashiCorpVaultAuthority (`secrets://hashicorp/...`), BitwardenAuthority, EnvAuthority (for CI/CD injection). Authority selection is configured in `cam-config.yaml` as a priority-ordered list; the broker tries each authority in order and returns the first successful resolution. This structure preserves all `secrets://` reference paths across migrations to new vault software — only the adapter changes, not the URI or any calling code. Schema: `data-model/secrets-authority-schema.yaml` (to be created). |
