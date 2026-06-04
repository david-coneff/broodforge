# Broodforge Architecture — Forging, Hatchery, Stargate

Version: 7.1
Date: 2026-05-31 UTC
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

Full architectural rationale: docs/DESIGN-HISTORY.md (design evolution) +
the AD table above (current decisions). Historical review text: deprecated/.
