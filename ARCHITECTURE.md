# Broodforge Architecture — Forging, Hatchery, Stargate

Version: 7.1
Date: 2026-06-08 UTC (AD-059, AD-060, AD-061 added — operator decisions promoted the three Roadmap draft sketches to scoped phases: Recovery-Readiness Conformance Certificate (Phase 1.I), firm constraint against autonomous full-root hypervisor pathways with constrained-account/break-glass/pre-generated-media middle path (Phase 1.J), and Granular Secret Access Silo Vault Hierarchy and User Provisioning (Phase 1.K). Earlier same-week: AD-057, AD-058 added — Pre-Install Forge Package and Image Builder now fully implemented including cross-platform GUI wizard; Second-factor authentication is the default for the KeePass unlock gate)
Design history & rationale: docs/DESIGN-HISTORY.md
Full historical reviews (v4–v7): deprecated/

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
| Workbooks | HTML (machine-generated) | Execution records and recovery workbooks — self-contained, print-friendly |

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

```
HATCHERY PROCESS — PRE-PACKAGE (on the hatchery)
──────────────────────────────
1. Hardware discovery (autonomous mode only):
   The hatchery is a trusted node on a secured LAN. Password-based SSH from
   the hatchery to a fresh broodling is acceptable — no pre-exchanged key required.
   The spawn planner generates a suggested temporary root password (readable passphrase
   format) before the operator installs Proxmox. The operator uses that password during
   installation; the hatchery connects automatically with it after install completes.
   Discovery runs from the hatchery using that temporary password:
     python3 spawn_hardware_discovery.py --host {broodling-ip} --user root --password-prompt (password-based via sshpass)
     → hardware-profile-{hostname}.json
   Temporary password is valid only until the spawn package's Cloud-Init phase
   replaces it with a KeePass-managed credential.
   For interactive mode: no hardware profile needed on the hatchery; spawn.sh
   discovers hardware on the broodling at runtime.

2. Assessment Engine reads current cluster state
   → spawn-manifest.json: all reserved VMIDs, IPs, hostnames,
     Proxmox cluster join address + fingerprint, k3s join tokens

3. spawn-planner.py — execution mode gate, then conditional service selection
   Execution mode is asked FIRST:
     Autonomous (default): triggers service selection on the hatchery; selection
       locked into package; spawn.sh runs unattended after KeePass gate.
     Interactive: no selection on hatchery; package includes all service scripts;
       spawn.sh presents service menu on the broodling against actual hardware.

   Service selection (autonomous only) — three modes:
     Mode 1 — Full mirror: select all services that fit this hardware
       Exclusions shown with reason; operator confirms or switches mode
     Mode 2 — Select by group: Infrastructure / Platform / Intelligence /
               Monitoring / Applications — toggle whole groups, then fine-tune
     Mode 3 — Select individually: every service listed with fit status:
       [✓] k3s-server        4 GB RAM req  /  14 GB avail
       [✓] prometheus        2 GB RAM req  /  fits
       [✗] loki              4 GB RAM req  /  insufficient
       Dependencies enforced (selecting nextcloud auto-selects longhorn if needed)

   Intelligence baseline always included, cannot be deselected:
   Proxmox cluster membership, k3s worker, assessment/doc engine visibility,
   bootstrap-state.json contribution.

   Disposition stored as `disposition.execution_mode`, `disposition.services` (selected,
   autonomous only), `disposition.excluded` (didn't fit + reason, autonomous only)
   in spawn-plan.json.

4. validate-spawn.py → conflict check on all proposed allocations
   RED on any VMID / IP / hostname collision — blocks package generation

5. spawn-plan.json assembled
   Non-conflicting VMID block, IPs, hostnames, ZFS topology, bridge definitions,
   only VM roles / Cloud-Init / Ansible roles for selected services,
   k3s labels + taints derived from service list (Flux schedules accordingly)

6. assemble-spawn-package.py
   spawn-package-{cell}-{hostname}-{ts}.tar.gz
     ├── spawn-manifest.json   (reservation snapshot — used offline)
     ├── spawn-plan.json       (disposition + conflict-validated allocations)
     ├── hardware-profile.json (disk IDs, NIC layout for host config)
     ├── scripts/spawn.sh + phase-00 through phase-06
     ├── opentofu/             (only disposition-declared VM roles)
     ├── cloud-init/           (snippets for disposition VMs only)
     ├── ansible/              (inventory additions + disposition-scoped role vars)
     └── spawn-workbook.html   (auditable execution record)

[operator copies package to broodling — only manual step after install]

SPAWN EXECUTION (on the broodling)
────────────────────────────────────
HOST-LEVEL PHASES — must complete before any VM can be created:

  phase-00-host-bootstrap.sh

    [A] Hardware pre-flight — read-only, no changes made
        Re-scans actual hardware, diffs against embedded hardware-profile.json:
        ├── Disk IDs in plan present + capacity matches
        ├── NIC names/MACs match profile (renumbering happens after kernel updates)
        ├── Available RAM ≥ plan VM total + 10% host overhead
        ├── No existing ZFS pool name conflicts with planned pool
        ├── No existing bridge name conflicts with planned bridges
        └── Conflict re-validation vs spawn-manifest.json
            (catches any new hatchery reservations since package was built)
        On mismatch → failure package with diff, exit without touching anything
        On pass    → proceed to [B]

    [B] Host configuration — writes files, creates pool, activates network
        ├── Set hostname + fix /etc/hosts   (pvecm add fails if host → 127.0.0.1)
        ├── Write bridge definitions        (/etc/network/interfaces from NIC layout)
        ├── ifreload -a                     (activate bridges without reboot)
        ├── zpool create                    (disk IDs confirmed by pre-flight)
        ├── pvesm add zfspool               (register pool as Proxmox datastore)
        └── Configure apt repos
    → Broodling ready: bridges exist, storage registered, hostname correct

  phase-01-join-proxmox.sh
    pvecm add <hatchery-address> --fingerprint <from manifest>
    → Broodling visible in Proxmox datacenter

VM PROVISIONING PHASES — bridge + datastore names from phase-00 must exist:

  phase-02-vms.sh
    tofu apply   (disposition-scoped tfvars; bridge/datastore names from phase-00)
    → Disposition-declared VMs created on broodling

  phase-03-cloudinit.sh
    Install Cloud-Init snippets into Proxmox snippet store
    Start VMs → Cloud-Init runs: hostname, IP, SSH keys, packages
    Poll SSH readiness before proceeding

CLUSTER JOIN PHASES — depend on VMs running:

  phase-04-join-k3s.sh
    Ansible: k3s-server or k3s-worker role, join token from manifest
    → Broodling's k3s nodes join the hatchery cluster

  phase-05-promote-ha.sh   [conditional — only if broodling is the 3rd server node]
    SQLite → embedded etcd migration; control plane distributed across hosts

  phase-06-verify.sh
    Cluster health check, all disposition VMs running, conflict re-validation vs live state

AUTOMATIC (no operator action after phase-06):
  Flux CD     → schedules disposition-appropriate workloads on broodling
  Assessment  → detects broodling in Proxmox API, scores against its disposition
  Doc Engine  → regenerates topology with broodling included

bootstrap-state.json updated on hatchery → committed to Forgejo
```

**What adapts to each broodling's hardware:** ZFS pool topology (disk count/mix),
NIC bridge/bond layout, VM RAM sizing within available capacity,
IP/VMID/hostname allocations, services trimmed to what hardware can support.

**What stays identical across all nodes:** Naming convention, KeePass path structure,
Proxmox cluster membership, the intelligence collection baseline (assessment + doc
engine visibility), secret references.

**Disposition determines what is deployed, not just hardware:**
A broodling's disposition is chosen at spawn time and recorded in `bootstrap-state.json`.
The assessment engine reads it — a broodling without `k3s-server` is not scored
against HA control-plane requirements. Disposition declares intent; the assessment
engine scores reality against that declared intent, not against the hatchery's full configuration.

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
| AD-061 | **Granular Secret Access Silo Vault Hierarchy and User Provisioning (proposed scope — Phase 1.K, see Roadmap).** Following the operator's question about whether broodforge could support tiered, hierarchically-scoped secret access for *human* operators (a service operator who can manage their service but cannot reach the Proxmox root password, versus a "god-mode" sysadmin) — for which single-operator "god mode" is, and remains, the correct homelab default — this records the accepted design for the larger-org case the operator wants kept on the roadmap. **The constraint that shapes the design**: KeePass/KDBX databases are single-master-password, with no native per-user role layer inside one `.kdbx` file; building real per-user ACLs would require either an external identity-aware secrets broker (Vault-style — which contradicts broodforge's offline-first, stdlib-only, network-independent design constraints, `.ai/CURRENT_STATE.md` "Key Design Constraints," and AD-042's entire premise that the KeePass file can be embedded in offline packages with no server dependency) or **multiple derived vaults**, each scoped to a declared subset of secrets with its own independently-generated master password — "more vaults derived from the one vault," not "one vault with roles bolted on." The latter is the only approach that fits broodforge's existing architecture with no new dependency and no change to its trust-model foundations, and is the design adopted: a **`Role`/`Scope` registry** (a new authoritative YAML, following the existing 10-metadata-file pattern in `data-model/`) naming roles, hierarchical scopes expressed as glob patterns over `secret-registry.yaml`'s existing `owning_cell`/`required_by` vocabulary (`cell-1/*`, `cell-1/node-1/*`, `cell-1/node-1/vm-3/*`, or by `secret_type`/`required_for` facet), and which humans hold each role; and a **`derive-scoped-vault` generator** that reads the canonical KeePass DB plus the Role/Scope registry and produces a derivative `.kdbx` containing only in-scope entries, with its own freshly-generated passphrase (reusing `generate_master_password_suggestion()`/EFF generators, AD-043/AD-052) — the canonical "god mode" database remains exactly what it is today, broodforge's permanent default. **Two operator-directed expansions beyond the original sketch**: (1) **higher-tier vaults must include records of the access credentials for lower-tier scopes** — each derived vault's generated passphrase is itself written as an entry in the next tier up (ultimately the canonical god-mode vault), so a god-mode operator can always recover any scoped vault's passphrase from their own vault, generalizing the per-backup unique-secret rotation bookkeeping pattern already established in AD-044 ("a vault of vaults," not an isolated set of derivatives); (2) **a mechanism for creating users at the VM level and the Proxmox level**, with default account templates corresponding to the proposed scope divisions (e.g., service operator / node sysadmin / god mode), each provisioned at forge/spawn time with access to exactly its corresponding scoped vault and nothing beyond it. **Authorization model**: only holders of the canonical vault can mint scoped vaults or scope-tier user templates — true by construction ("you can only derive a scope you can already see the contents of"), matching who is already trusted to run `forge-planner.py`/`spawn-planner.py`. **Revocation = rotate + reissue**, documented up front as an honest non-guarantee — a derived vault cannot leak ciphertext it never received, which is arguably a *stronger* property than a layered ACL on a database the holder already possesses in full; this is a property of the offline-first model, not a flaw in this design specifically. Explicitly not proposed: real-time per-user audit logs (would require the broker/network dependency broodforge deliberately avoids, though "scoped vault X was used" correlation is possible for free since each derived vault is a distinguishable credential), or cryptographic enforcement of scope beyond "the derived vault simply does not contain out-of-scope ciphertext." See Roadmap Phase 1.K for the full scoped implementation plan. |

Full architectural rationale: docs/DESIGN-HISTORY.md (design evolution) +
the AD table above (current decisions). Historical review text: deprecated/.
