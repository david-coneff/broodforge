# Broodforge — Roadmap

Version: 6.0
Last updated: 2026-05-31
Architecture: v7.0 (see ARCHITECTURE.md and docs/ARCHITECTURE-REVIEW-v7.md)

---

## Completed

- [x] Phase 1: Core assessment engine (Tier 2 foundation)
- [x] Phase 2: Assessment history store
- [x] Phase 3: Forgejo integration and repository export
- [x] Phase 4: Bootstrap assessment package (proxmox-audit-package-v1)
- [x] Milestone 5.1: Data Model Formalization (five schemas)
- [x] Milestone 5.2: Tier 1 Bootstrap Assessment Rebuild
- [x] Milestone 5.3: Bootstrap Documentation Generator
- [x] Milestone 5.4: Recovery Documentation Generator
- [x] Milestone 5.5: Recovery Readiness Scoring (with backup inventory)
- [x] Milestone 5.6: Historical State Integration (drift detection, snapshot index, reproducibility)
- [x] Milestones 6.0–6.8: Bootstrap State schema, Cloud-Init templates, Secret/DNS registries,
      provenance tracking, template registry, Tier 2 SSH state collector,
      Bootstrap Workbook registry wiring
- [x] Milestones 7.1–7.4: Service contract implementation, service state schema and collection,
      external dependency state (cert expiry + recovery Appendix G),
      recovery documentation service layer (contract block, health checks, restart commands,
      Appendix A edge legend)
- [x] Phase 6.B: Backup infrastructure — restic + rclone engine, BackupNaming, SpaceProbe,
      ResticRunner, RcloneRunner, BackupEngine, RestoreEngine, run-backup.py,
      restore-from-backup.py, setup-backup.py, backup readiness scoring, Appendix H

---

## Roadmap Overview

### Three Processes — Three Package Types

| Process | Package | Phases | What it does |
|---|---|---|---|
| **Forging** | Forge package | Phase 0–3 + Phase 1.F | Bare hardware → first operational hatchery |
| **Hatchery Process** | Spawn package | Phase 12.E | Hatchery → broodling joins without conflict |
| **Stargate Process** | Phoenix package | Phase 9 + Phase C/D | Failed node → identity resurrected |

### Three Tracks

**Forging Foundation (Phases 0–3, Phase 1.F)**
Establish the metadata model and all Phase A tooling. Culminates in the forge
package — a self-contained archive that takes bare hardware to an operational
broodforge hatchery via eight automated phases.

**Track 1 — Cell-Scoped Foundation (Phases 6–12.E)**
Complete the single-cell documentation, reconstruction, and spawn capability.
Includes:
- Phase 9 (Stargate Process) — phoenix playbooks that reconstitute a failed node's
  identity on new hardware
- Phase 12.E (Hatchery Process) — spawn package that a broodling runs after bare
  Proxmox install to join the hatchery without VMID, IP, or hostname conflicts
All schemas in this track carry `cell_id` (federation-readiness gate).

**Track 2 — Expanded State Model (Phases 13–18)**
Add the new state categories: Hardware, Platform, Cluster, Storage,
External Dependencies, Data Protection, Observability, Capability, Federation State.

**Track 3 — Digital Twin and Federation (Phases 19–25)**
Build the Digital Twin platform, federation architecture, federated reconstruction,
and continuous assessment capability.

Track 2 begins after Phase 12.E completes the single-cell + expansion foundation.
Track 3 begins after Phase 18 completes the expanded state model.

---

## Forging Foundation — Phase 0 through Phase 3

Phases 0–3 constitute the **forging process**: building the Phase A toolchain that
can take bare hardware to an operational broodforge hatchery. These phases are
complete. Phase 1.F (Forge Package Assembly) is the planned capstone.

### Phase 1.F — Forge Package Assembly *(Forging Process capstone)*

*Assembles all Phase A tooling into a single self-contained forge package — the
artifact an operator downloads and runs on bare Proxmox to forge the first hatchery.*

- [ ] 1.F.1: `forge-pack.sh` — assembles forge package from current repo state:
      discovery scripts, planners, generators, opentofu/, ansible/, forge.sh + phases,
      forge-workbook.ods template, lib/ (checkpoint, validation, failure-package)
- [ ] 1.F.2: `forge.sh` — orchestrated entry point with 8 phases:
      phase-00 (discover) → phase-01 (plan) → phase-02 (validate, RED blocks) →
      phase-03 (host config) → phase-04 (VMs) → phase-05 (k3s) →
      phase-06 (Flux GitOps) → phase-07 (intelligence layer) → phase-08 (verify + commit)
- [ ] 1.F.3: Forge workbook (ODS) — tracks forge execution with same checkpoint/status
      pattern as spawn and phoenix workbooks; committed to Forgejo on completion
- [ ] 1.F.4: `forge-manifest.json` — cell identity snapshot embedded in package:
      declares cell_id, naming convention, hardware requirements, storage config,
      secret registry paths, target VM set (minimum viable broodforge stack only)
- [ ] 1.F.5: Minimum viable forge validation — phase-02 checks that hardware meets
      minimum requirements for the broodforge stack (doc engine + assessment engine);
      user applications are not included in the forge package (added via GitOps after)
- [ ] 1.F.5a: **Proxmox subscription nag suppression** — `lib/pve-suppress-nag.sh`:
      Patches the Proxmox web UI JavaScript to remove the non-enterprise subscription
      popup. Applied during phase-03 (host config) as part of standard host hardening.

      Implementation: patches `/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js`
      to neutralise the `Ext.Msg.show` call that renders the subscription dialog.
      Idempotent — detects if already applied and exits cleanly.

      Persistence: installs a dpkg post-invoke hook at
      `/etc/apt/apt.conf.d/85pve-nag-suppress` that re-applies the patch whenever
      `proxmox-widget-toolkit` or `pve-manager` packages are updated, so the
      suppression survives Proxmox upgrades without operator intervention.

      Note: Proxmox Community Edition (VE without subscription) is fully functional
      and free to use. The subscription nag is a commercial reminder, not a licence
      restriction. This script removes the UI interruption for homelab operators who
      do not hold an enterprise subscription.

- [ ] 1.F.6: **KeePass initialisation at forge time** — phase-03 (host config) prompts
      the operator to set the KeePass master password before any secrets are generated:
      - Broodforge offers a generated readable passphrase as the default suggestion
        (format: `Capital.word.phrase.9` — 20-30 chars, leading capital, lowercase,
        period separators, trailing digit; see AD-043)
      - Operator may accept the suggestion, enter their own, or open the KeePass
        built-in generator for an alternative format
      - Password confirmed by re-entry; never stored by broodforge
      - KeePass database initialised and populated with generated service credential
        entries (paths only established here; values filled during service deployment)
      - Operator selects whether to embed the database in subsequent spawn/phoenix
        packages (embedded = convenient but requires master password at gate;
        path-based = database stays off the package entirely)
- [ ] 1.F.7: **Readable passphrase generator** (`lib/passphrase.py`) — stdlib only:
      Generates passwords in the `Capital.word.phrase.9` format from a curated word list.
      Used for master password suggestion, initial service credentials, and any
      operator-facing password output. Character set: A-Z (leading only), a-z, 0-9, `.`
- [ ] 1.F.8: **Service password compatibility detector** — if a service deployment phase
      fails with an authentication or credential-related error, the detector:
      - Matches the failure pattern against known incompatibility signatures
        (common patterns: service rejects `.` or `_` in passwords)
      - Offers to regenerate the affected credential as a plain alphanumeric password
        (letters + digits only, same length range — KeePass default format)
      - Retries the failed deployment phase with the new credential
      - Records the service name and character restriction in service-catalog metadata
        so the restriction is applied automatically in future deployments
      - The service-specific format override is stored in service-catalog.yaml as
        `password_format: alphanumeric` for any service known to require it
- [ ] 1.F.8a: **Headscale auto-configuration** — installed and configured during phase-03
      (host config) so the hatchery is the tailnet coordinator from the moment it is forged:

      **Installation:**
        Download headscale binary (or apt install headscale if available in repos)
        Generate headscale config: server_url, listen_addr, db_path, log_level
        server_url derived from the hatchery's discovered WAN/LAN address + port 8080
        TLS: configured with self-signed cert for initial operation; operator can
        supply a proper cert or configure ACME after forging
        systemd service created and enabled: `headscale serve`

      **Initial setup:**
        Create a broodforge user/namespace in Headscale:
          `headscale users create broodforge`
        Register the hatchery's own Tailscale client with its own Headscale:
          `tailscale up --login-server https://{hatchery-address}:8080`
          (the hatchery is the first node on its own tailnet)
        Record the Headscale server URL in bootstrap-state.json as
          `network_topology.headscale_url`
        Store the Headscale API key in KeePass:
          `headscale apikeys create` → stored at
          `Infrastructure/headscale/api-key`
        The hatchery's tailnet IP (100.64.0.1 or similar) is also recorded in
          bootstrap-state.json alongside its LAN IP

      **Auth key generation for spawn packages:**
        When spawn-planner.py runs in WAN mode, it calls:
          `headscale authkeys generate --expiration 1h --user broodforge`
        The resulting key (a short string, typeable or pasteable) is embedded in
        the spawn package. It is single-use and expires — not stored in KeePass.

      **LAN vs WAN detection:**
        spawn-planner.py tries a direct connection to the broodling's reported IP.
        If unreachable within 5 seconds, prompts the operator:
          "Broodling appears unreachable on LAN. Use WAN mode (Headscale)?"
        Operator can also set --wan or --lan explicitly.

- [ ] 1.F.8b: **Split-horizon DNS server (dnsmasq)** — deployed in phase-03 (host config),
      before any VMs exist, so DNS is available from the moment the hatchery can serve LAN:

      **Installation and configuration:**
        apt install dnsmasq
        Generate /etc/dnsmasq.conf from dns-registry.yaml:
          - One `address=/{fqdn}/{lan-ip}` line per dns-registry.yaml entry
          - `server=8.8.8.8` and `server=1.1.1.1` for upstream forwarding
          - `domain={operator-domain}` to make unqualified names resolvable
          - `listen-address={hatchery-lan-ip}` to bind to the LAN interface
        Generate via `proxmox-bootstrap/generate-dnsmasq-config.py`:
          reads dns-registry.yaml → writes /etc/dnsmasq.d/broodforge.conf
          Idempotent: re-run after any dns-registry.yaml update to reload config
        systemctl enable --now dnsmasq
        Update Proxmox host /etc/resolv.conf to point at itself (127.0.0.1)

      **The operator provides their domain during phase-01 (plan):**
        forge-planner.py asks:
          "Your domain name (e.g. home.example.com): _"
        Stored in bootstrap-state.json as `host_identity.domain`.
        All node hostnames in the deployment use this domain suffix:
          hatchery.home.example.com, forgejo.home.example.com, etc.
        FQDN stored as `host_identity.fqdn` — the canonical address for all
        inbound connections (Headscale, Forgejo, and any WAN-reachable service).

      **Split-horizon behaviour:**
        LAN clients with hatchery as DNS:   `hatchery.home.example.com` → LAN IP
        WAN clients using public DNS:        `hatchery.home.example.com` → WAN IP
        Same FQDN, same spawn package, same Headscale URL — works from everywhere.

      **Router/firewall requirements (operator-configured, not automated):**
        Port forwarding: 8080 (Headscale) → hatchery LAN IP
        External DNS A record: `hatchery.{domain}` → operator's WAN IP
        The forge wizard reminds the operator of these requirements but cannot
        configure the upstream router automatically (out of scope for forge).

- [ ] 1.F.8c: **External DNS auto-update** — for operators with dynamic WAN IPs:

      **Tool selection:**
        Primary: **dns-lexicon** (pip install dns-lexicon) — 90+ providers, actively
          maintained, unified CLI/API. Providers: Cloudflare, GoDaddy, Namecheap,
          Route53, Porkbun, Gandi, OVH, DigitalOcean, Linode, Vultr, and 80+ more.
        Special case: **DuckDNS** — handled via a single HTTPS GET (no lexicon needed),
          suitable for operators who want a free subdomain rather than their own domain.
        DO NOT USE: inadyn — archived Oct 2025, no longer maintained.

      **Squarespace registrar note:**
        Squarespace exposes no DNS API. Operators with Squarespace-registered domains
        must delegate DNS management to Cloudflare (change nameservers in Squarespace
        dashboard → "Use Custom Nameservers" → enter Cloudflare NS records). After
        delegation, all DNS is managed via Cloudflare API — broodforge treats it as
        a standard Cloudflare provider. See docs/DNS-UPDATE-SETUP.md.

      **forge-planner.py asks:**
        "Is your WAN IP static or dynamic?"
        If dynamic: presents provider selection menu:
          1. Cloudflare (recommended — works for any registrar, including Squarespace)
          2. DuckDNS (free subdomain — no own domain needed)
          3. Other provider (Namecheap, GoDaddy, Route53, Porkbun, etc.) via dns-lexicon
          4. Skip — I will manage DNS records manually

      **Implementation:**
        `proxmox-bootstrap/setup-ddns.py` — interactive configuration wizard:
          Walks operator through provider selection, credential entry, and
          writes config to /etc/broodforge/ddns.conf.
          Credentials stored in KeePass; references stored in bootstrap-state.json.
          Tests the update before saving (makes a real DNS call to verify credentials).
        `proxmox-bootstrap/update-dns.py` — update script (called by systemd timer):
          Detects current WAN IP (curl ifconfig.me / ipinfo.io, with fallback)
          Compares to cached last-known IP (/var/lib/broodforge/last-wan-ip)
          If changed: calls dns-lexicon or DuckDNS GET to update A record
          Logs outcome to systemd journal
          On failure: logs and retries on next timer tick (does not crash)
        systemd timer: broodforge-ddns.timer — runs every 5 minutes
          OnBootSec=60 (initial delay to let network settle)
          OnUnitActiveSec=5min

      **Configuration stored in bootstrap-state.json:**
        `network_topology.ddns_provider` — "cloudflare" | "duckdns" | "lexicon:{name}" | null
        `network_topology.ddns_zone` — the DNS zone/domain being managed
        `network_topology.ddns_record` — the specific A record being updated (e.g. "hatchery")
        `network_topology.ddns_credential_reference` — KeePass path for API token/key

      **Documentation:** docs/DNS-UPDATE-SETUP.md — step-by-step guides for each
        provider including Squarespace → Cloudflare delegation walkthrough.

- [ ] 1.F.8d: **Let's Encrypt TLS certificate automation** — runs after DNS is configured
      (1.F.8b + 1.F.8c); tool and method depend on which DNS provider was selected:

      **Cloudflare path:**
        Install certbot + python3-certbot-dns-cloudflare (apt)
        Write /etc/broodforge/cloudflare.ini using API token from KeePass
          (chmod 600 — certbot refuses to read world-readable credentials files)
        Issue wildcard cert:
          certbot certonly --dns-cloudflare
            --dns-cloudflare-credentials /etc/broodforge/cloudflare.ini
            --dns-cloudflare-propagation-seconds 30
            -d {fqdn} -d "*.{domain}"
            --email {operator-email} --agree-tos --non-interactive
        Certs land at /etc/letsencrypt/live/{fqdn}/fullchain.pem + privkey.pem
        certbot.timer (installed by certbot) handles auto-renewal
        Deploy hook written to /etc/letsencrypt/renewal-hooks/deploy/:
          Reloads headscale and nginx after each successful renewal

      **DuckDNS path:**
        Install acme.sh (curl https://get.acme.sh | sh)
        Issue wildcard cert:
          DuckDNS_Token={token from KeePass}
          acme.sh --issue --dns dns_duckdns
            -d {subdomain}.duckdns.org -d "*.{subdomain}.duckdns.org"
            --server letsencrypt --dnssleep 60
        Install cert to stable path /etc/broodforge/ssl/ with --install-cert
        acme.sh cron entry handles auto-renewal (added during install)
        Reload command: systemctl reload headscale + sync-cert-to-k8s.sh

      **Both paths — Headscale TLS config:**
        forge.sh writes the cert paths into /etc/headscale/config.yaml after
        cert issuance; Headscale is (re)started with TLS enabled

      **k3s ClusterIssuer (deployed in phase-06 Flux bootstrap):**
        Cloudflare: ClusterIssuer with dns01.cloudflare solver + k8s secret from
          Cloudflare API token (written from KeePass during phase-06)
        DuckDNS: No native cert-manager DNS-01 support; forge generates
          sync-cert-to-k8s.sh which copies the acme.sh wildcard cert into k8s TLS
          secrets in each namespace; script is wired into acme.sh --reloadcmd and
          also runs as a weekly k8s CronJob to catch any drift

      **SSL config stored in bootstrap-state.json:**
        network_topology.ssl_provider: "certbot" | "acme.sh"
        network_topology.ssl_method:   "dns-01-cloudflare" | "dns-01-duckdns"
        network_topology.ssl_cert_path: path to fullchain.pem
        network_topology.ssl_key_path:  path to privkey.pem

      **Documentation:** docs/CLOUDFLARE-SETUP.md Part 3 and docs/DUCKDNS-SETUP.md Part 2

- [ ] 1.F.9: **Timezone preference at forge time** — phase-01 (plan) prompts the
      operator to confirm or set their local timezone:
      - Auto-detected from the host OS if available
      - Stored in `bootstrap-state.json` as `vm_defaults.timezone`
      - Used by all documentation engine output (all timestamps show both UTC and local)
      - Updatable after forging via `engine.py --set-timezone` without requiring a rebuild
- [ ] 1.F.10: **Backup destination setup at forge time** — phase-01 (plan) walks the
      operator through configuring restic + rclone backup destinations:
      - At least one destination required before forge proceeds (secrets must be backed up)
      - Local destinations (filesystem path, USB mount point) need no credentials
      - Cloud destinations require an API key, Application Key, or OAuth token — not
        username/password; operator directed to docs/CLOUD-STORAGE-SETUP.md for setup
      - Destinations defined as an **ordered chain** per layer; no limit on chain depth
      - Each destination attempted in sequence; each upload independently verified
      - If a destination fails, the next in the chain is attempted automatically;
        the failure is reported to the operator but does not halt the process
      - If every destination in the chain fails for a layer: RED alarm surfaced
        to operator via log, workbook, and next assessment run — never silent
      - All backups encrypted by default with restic (encryption is mandatory, not optional);
        encryption password per restic repo stored in KeePass and retrieved by secrets
        broker at backup time — operator never manually handles backup decryption keys
      - Separate choices for: (a) secrets / KeePass DB, (b) configuration state,
        (c) application data volumes (opt-in; not configured by default)
      - Retention policy: number of versions to keep (default: 5); permanent checkpoint option
      - All backup config stored in bootstrap-state.json as first-class readiness metadata
- [ ] 1.F.11: Documentation: `FORGING.md` — operator runbook covering prerequisites,
      running forge-pack.sh on the repo, copying forge package to target host,
      executing forge.sh, verifying hatchery is operational

### Phase 1.G — Guided Setup Framework *(cross-cutting: forge, spawn, phoenix)*

*A shared configuration guidance engine used by all three deployment packages.
At every manual prompt the auto-suggestion is displayed and revised as the operator
makes choices. Conflicts are detected and surfaced before commitment.*

**Four configuration modes:**

| Mode | Operator interaction | When to use |
|---|---|---|
| **Autonomous** (default) | None — all settings calculated automatically | Standard deployment |
| **IP-Selective** | Choose IP addressing only; everything else is automatic | Operator has a specific IP plan |
| **Group-Manual** | Group selector → configure chosen groups manually, rest is automatic | Operator wants control over specific areas |
| **Full Manual** | Walk through all settings with auto-suggestions | Complete control |

**Setting groups (available in Group-Manual and Full Manual modes):**

| Group | Settings covered |
|---|---|
| Network | Management CIDR, gateway, bridge names, VLAN IDs, DNS, Headscale URL |
| Storage | ZFS pool topology, pool name, datastore names, disk assignment |
| VM Sizing | VMID block, per-VM RAM/CPU/disk, placement constraints |
| Identity | Hostname, domain, FQDN, cell_id, naming convention |
| Security | KeePass location, password format, SSH key references |
| k3s | Pod/service CIDR, CNI plugin, initial role (server/worker) |
| Backup | Restic destinations, retention policy, DDNS provider |

**Suggestion revision:** when the operator overrides a setting, all downstream
auto-suggestions are revised to remain logically consistent. Example: choosing
`192.168.50.0/24` as the management CIDR causes all subsequent VM IP suggestions
to come from that range; choosing a custom pool name causes all datastore references
to use that name.

**Conflict detection:** before accepting each override, the engine checks:
- VMID collisions with existing or other declared VMs
- IP address collisions with DNS registry or other declared VMs
- Subnet overlaps with k3s pod/service CIDR or other networks
- RAM allocation exceeding host total RAM
- ZFS pool or bridge names that already exist on the host
Warnings are shown with specific conflict details. The operator may still proceed.

- [x] 1.G.1: `proxmox-bootstrap/guided_setup.py` — core engine:
      `SETTING_GROUPS` — dict defining the seven groups and their constituent field paths
      `GuidedSetupSession` — session class that tracks:
        mode (autonomous|ip-selective|group-manual|full-manual)
        selected_groups (set of group names for group-manual mode)
        choices (field_path → {value, source: 'auto'|'manual'})
        warnings (accumulated conflict messages)
      `suggest(field_path, session)` — returns auto-suggestion revised from current choices;
        subnet changes cascade to IP suggestions; hostname changes cascade to FQDN; etc.
      `set_value(field_path, value, session)` → list[str] conflict warnings;
        records choice; triggers suggestion revision for dependent fields
      `check_conflicts(field_path, value, session)` → list[str] warning messages

- [x] 1.G.2: Group selector interface:
      `select_groups(session)` — displays group table with current auto-suggestions for
        a representative field in each group; operator toggles groups on/off;
        returns the set of groups to configure manually
      `prompt_field(field_path, label, session, choices=None)` → value;
        shows auto-suggestion, optional discrete choices, accepts free-text or selection;
        calls set_value() and surfaces any conflicts before returning

- [x] 1.G.3: IP-Selective mode specialization:
      Runs autonomously except for the Network group;
      `run_ip_selective(session)` — prompts only for CIDR, gateway, and VM IP assignments;
        all other settings auto-calculated; subsequent IP suggestions revised from choices

- [x] 1.G.3b: Network profiles (setup_network.py):
      LanNetworkConfig / WanNetworkConfig dataclasses; suggest_lan/wan() with field
      revision (cidr→gateway, domain→fqdn, dns_provider→tls_provider);
      validate_lan/wan_config() with errors/warnings; plan_migration_to_wan()
      (7-step plan, router step non-autonomous); plan_migration_to_lan() with
      preserve_headscale option; lan/wan_config_to_state() serialization;
      apply_network_config_to_state(); generate_dnsmasq_config() for both profiles.
      Schema: network_topology.profile + wan_config + lan_config + ssl_provider enum updated.
- [ ] 1.G.4: Wire into forge (Phase 1.F):
      forge-planner.py phase-01 (plan) asks which configuration mode to use;
      autonomous: existing behaviour; ip-selective / group-manual / full-manual:
        launches guided_setup session before proceeding with automated planning

- [ ] 1.G.5: Wire into spawn (Phase 12.E):
      spawn-planner.py Step 0 (network mode) extended to include guided setup mode;
      pre-populates spawn-plan.json with operator choices; marks fields as 'manual'
      so the assessment engine knows they were intentional

- [ ] 1.G.6: Wire into phoenix (Phase 9):
      phoenix package generation offers guided setup for restoration scope and
      any identity fields the operator wants to override;
      particularly useful for partial restoration scope selection

---

## Track 1 — Cell-Scoped Foundation

### Phase 6 — Bootstrap State

**6.0 — External Backup Setup and Recovery Runbook Integration**
- [x] `external_backup` section in bootstrap-state-schema.json
- [x] `backup.py` — archive naming, GPG encryption, transfer, listing, pruning
- [x] `setup-external-backup.py` — GitHub or encrypted-archive interactive wizard
- [x] `init-bootstrap-state.py` — prompts for external backup as part of init flow
- [x] Recovery runbook Step 0 — pre-populated bootstrap state retrieval commands
      derived from declared external_backup provider (git clone / rclone + gpg / UNRESOLVED)

**6.1 — Bootstrap State Schema and Repository Structure**
- [x] `data-model/bootstrap-state-schema.json` (Cloud-Init, image registry, templates,
      provenance, secret registry, DNS registry, service contracts, hardware requirements)
- [x] `data-model/service-state-schema.json`
- [x] `cell_id` field in both schemas
- [x] `proxmox-bootstrap/` repository structure
- [x] Schema validation tests (90 tests in test_bootstrap_service_schemas.py)

**6.2 — Cloud-Init Template Library**
- [x] Cloud-Init user-data per VM role
- [x] Cloud-Init network-config per VM
- [x] Proxmox vendor-data snippet
- [x] Snippet upload procedure documentation (SNIPPET-UPLOAD.md)

**6.3 — Secret Registry**
- [x] `secret-registry.yaml` schema with `owning_cell` field (federation-readiness)
- [x] Initial registry entries for all known secrets
- [x] Secret registry reader in doc-gen (`doc-gen/registries.py` — `SecretRegistry`)
- [x] Wire into recovery documentation (pre-populated "Secrets Required for Recovery" section + Appendix D)
- [x] Secret registry completeness in readiness scorer (ORANGE if missing)

**6.4 — DNS Registry**
- [x] `dns-registry.yaml` schema
- [x] Initial registry entries for all VMs
- [x] DNS registry reader in doc-gen (`doc-gen/registries.py` — `DnsRegistry`)
- [x] Wire into recovery runbook (replace `[VM_IP]` placeholders with actual IPs + Appendix C)
- [x] DNS registry completeness in readiness scorer (YELLOW if missing)

**6.5 — Deployment Provenance**
- [x] Provenance record schema (provenance_records in bootstrap-state-schema.json)
- [x] Provenance recorder (bootstrap-state.json provenance_records array)
- [ ] Provenance collector in Tier 2 assessment
- [x] Provenance completeness in readiness scorer (YELLOW if missing, per VM)
- [x] Wire into recovery documentation (per-VM block + Appendix E)

**6.6 — Template Registry and Base Image Tracking**
- [x] Template registry schema (base_images + templates arrays in bootstrap-state-schema.json)
- [x] Initial registry entries (ubuntu-2204-base ISO + template in bootstrap-state.json)
- [x] Template registry reader in doc-gen (doc-gen/template_registry.py — TemplateRegistry)
- [x] Template registry completeness in readiness scorer (ORANGE if missing)
- [x] Appendix F — Template Registry in recovery runbook
- [ ] Template rebuild playbook format (Phase 9)

**6.7 — Tier 2 Bootstrap State Collector**
- [x] `proxmox-bootstrap/collect_tier2.py` — SSH collector library (parse_qm_list,
      parse_qm_config, collect_templates, collect_provenance_records, merge_into_state)
- [x] `proxmox-bootstrap/collect-tier2.py` — CLI entry point (--host, --user, --port,
      --key, --state, --dry-run, --verbose)
- [x] `proxmox-bootstrap/TIER2-COLLECTION.md` — runbook: prerequisites, usage, merge
      behaviour, ISO name inference, post-collection steps, troubleshooting
- [x] `--dry-run` flag; merge-only logic (never overwrites existing manual entries)
- [x] Tests — 54 tests in test_tier2_collector.py
- [ ] Cloud-Init snippet comparison (deployed vs. repository) — deferred to 6.8
- [ ] Integration into Tier 2 manifest — deferred to 6.8

**6.8 — Bootstrap Documentation Update**
- [x] Bootstrap Workbook Stage 03: VM IP from DNS registry; ISO path from template registry
- [x] Stage 03 validation checkpoint and qm create note pre-populated from registries
- [x] End-to-end test (28 tests)

**6.B — Backup Infrastructure** *(restic + rclone; KeePass, config state, app data)*

- [ ] 6.B.1: `proxmox-bootstrap/setup-backup.py` — interactive backup configuration wizard:
      - Installs restic and rclone on the host if not present
      - Configures one or more backup layers:
          (a) Secrets / KeePass DB — always enabled when any destination configured
          (b) Configuration state — enabled by default
          (c) Application data volumes — opt-in per volume at service setup
      - For each layer, builds an **ordered destination chain** (no limit on length):
          → Enter destinations one at a time; add as many as desired
          → Each destination attempted in sequence when the previous one fails
          → All attempted; failures reported but chain continues; all-fail = RED
      - Local destinations: filesystem path or USB mount point (no credentials)
      - Cloud destinations: provider selection → API credential entry → rclone config
          written to `~/.config/rclone/rclone.conf`; restic repo initialised at destination
          Cloud destinations require API key / OAuth / Application Key — not user+password
          (see `docs/CLOUD-STORAGE-SETUP.md`)
      - **Per-backup unique secrets (non-KeePass layers)**:
          Each individual backup run generates a new unique restic repo password via
          `restic key add` + `restic key remove` (rewraps the master key; no data
          re-encryption). Stored in KeePass at a timestamped path per component:
            `Backup/{layer}/{component}/{YYYY-MM-DD_HH_MM_SS}/repo-password`
          A `current` alias key is also maintained:
            `Backup/{layer}/{component}/current` → latest timestamp subdirectory
          Secrets broker uses the snapshot timestamp to look up the exact key for
          any given snapshot at restore time. After `restic forget` prunes a snapshot,
          the corresponding KeePass entry is removed automatically.
          KeePass DB backup is exempt — its auth method (master password or configured
          token/key file) is never subject to per-backup rotation.
      - **KeePass DB backup — no restic layer**: the `.kdbx` file is already AES-256
          encrypted by KeePass; backed up as a plain rclone file copy to each configured
          destination; adding restic encryption would create a circular dependency (need
          the repo password from KeePass to decrypt backup of KeePass — irrecoverable)
      - **KeePass backup transport credentials** stored in `forge-manifest.json`, NOT in
          KeePass — the one exception to the "packages carry only KeePass references" rule;
          these credentials are embedded in forge/spawn/phoenix packages so a bare machine
          can retrieve the KeePass DB before KeePass is available
      - **Secrets broker configuration**: wizard records which KeePass path templates map
          to which components/layers so that automated backup and restore require no manual
          secret entry beyond the initial master password gate
      - **Space-aware component routing**: wizard records the target snapshot retention
          count and estimated component sizes; at runtime the backup engine probes
          available space before each run and routes individual components to destinations
          with sufficient room (see 6.B.3 for execution detail)
      - Retention policy per layer: number of snapshots to keep (default 5);
          permanent checkpoint: any snapshot can be tagged `checkpoint` and is
          excluded from rotation regardless of retention count
      - **Naming convention enforced by wizard**: all repo paths, KeePass key paths,
          snapshot tags, and KeePass DB filenames are constructed programmatically
          from cell_id, component metadata, and UTC timestamps — operators do not
          name backup artifacts; see 6.B.2 naming convention for the full scheme
      - All configuration serialised into `bootstrap-state.json` backup_config section

- [ ] 6.B.2: `backup_config` section in `bootstrap-state-schema.json` — schema for:

      **Naming convention** (enforced programmatically; operators do not name artifacts manually):
        Component prefixes: `kdbx` | `cell-config` | `node-{hostname}` | `vm-{name}-{vmid}`
          | `ct-{name}-{ctid}` | `vol-{vm_name}-{vol_name}` | `svc-{service_name}`
        Timestamp format: `YYYY-MM-DD_HH_MM_SS` (UTC; underscores; matches project convention)
        Hash: 8 hex chars — SHA-256 of file content (KeePass files) or first 8 of UUID/snapshot ID
        Restic repo paths: `{destination_root}/{cell_id}/{layer}/{component_prefix}/`
        KeePass DB files: `kdbx_{cell_id}_{timestamp}_{hash8}.kdbx`
        Snapshot set IDs: `{cell_id}_{timestamp}_{run_hash8}` (UUID first 8 chars)
        Restic snapshot tags: `cell:{cell_id}`, `set:{snapshot_set_id}`,
          `component:{prefix}`, `layer:{layer}`, `run:{timestamp}`
        KeePass key paths: `Backup/{layer}/{component_prefix}/{timestamp}/repo-password`
          and `Backup/{layer}/{component_prefix}/current` (alias to latest)

      - Per-layer destination chain (ordered array; unlimited length):
          For config/appdata layers — each entry:
            `{type, rclone_remote, restic_repo_root, restic_repo_password_keepass_prefix,
              retention_count}`
            Restic repo path assembled as: `{restic_repo_root}/{cell_id}/{layer}/{component}/`
          For secrets/KeePass layer — each entry:
            `{type, rclone_remote, kdbx_destination_root}`
            Destination file named: `kdbx_{cell_id}_{timestamp}_{hash8}.kdbx`
            (no restic layer; transport credentials stored in forge-manifest.json)
      - Permanent checkpoint tag name (default: `checkpoint`)
      - Layer-level `all_failed_policy`: `alert` | `block_assessment` (default: both)
      - Per-layer backup history (appended on each run; trimmed to last 100 entries):
          `{run_at, snapshot_set_id, destinations_attempted, destinations_succeeded,
            consecutive_all_fail_count, components: [{component_id, component_prefix,
            destination, restic_snapshot_id, keepass_key_path, size_bytes, verified,
            routed_reason}]}`
          `snapshot_set_id`: `{cell_id}_{timestamp}_{run_hash8}` — human-readable;
          links all component snapshots belonging to the same logical backup point
      - Space routing metadata per component per run (embedded in components[]):
          `routed_reason`: `primary` | `space_fallback` | `chunked_split`

- [ ] 6.B.3: `proxmox-bootstrap/run-backup.py` — backup execution engine:

      **Naming — all names constructed programmatically, never entered manually:**
      - Restic repo path: `{restic_repo_root}/{cell_id}/{layer}/{component_prefix}/`
          e.g. `b2:cell-backup/proxmox-cell-a/config/vm-forgejo-101/`
      - KeePass DB copy: `kdbx_{cell_id}_{timestamp}_{sha256_of_file[:8]}.kdbx`
          e.g. `kdbx_proxmox-cell-a_2026-06-01_03_00_00_a3f2b891.kdbx`
      - Snapshot set ID: `{cell_id}_{timestamp}_{snapshot_set_uuid[:8]}`
          e.g. `proxmox-cell-a_2026-06-01_03_00_00_f7c1d3a2`
      - Restic snapshot tags applied at creation: `cell:{cell_id}`, `set:{snapshot_set_id}`,
          `component:{component_prefix}`, `layer:{layer}`, `run:{timestamp}`
      - KeePass key path: `Backup/{layer}/{component_prefix}/{timestamp}/repo-password`

      **Per-backup secret rotation:**
      - For each component being backed up, generates a new unique passphrase
      - Adds it to the restic repo: `restic key add` (new key now unlocks the repo)
      - Stores it in KeePass at the timestamped path:
          `Backup/{layer}/{component_prefix}/{YYYY-MM-DD_HH_MM_SS}/repo-password`
      - Updates the `current` alias in KeePass to point to the new timestamp path
      - Removes the previous key from the repo: `restic key remove` (old password
          no longer works; only the newly generated key is valid going forward)
      - On pruning (after `restic forget`): removes the corresponding KeePass entry
          for each pruned snapshot's timestamp path; `current` always points to latest
      - KeePass master password gate fires once per session; all subsequent secret
          lookups and key rotations are automatic
      - **KeePass database backup**: triggered whenever configuration state backup runs;
          executed as a plain rclone copy of the `.kdbx` file — no restic layer, no key
          rotation; transport credentials read from `forge-manifest.json` (not KeePass);
          KeePass is already AES-256 encrypted and requires no additional encryption layer

      **Space-aware component routing:**
      - Before backing up each component, probes available space at each destination
          in the chain using rclone's `about` command (or filesystem `statvfs` for local)
      - Estimates required space: last snapshot size × 1.1 (10% growth headroom)
      - Routing logic per component:
          1. Primary destination has space → back up there (routed_reason: `primary`)
          2. Primary is full or insufficient → try next destination in chain
             (routed_reason: `space_fallback`)
          3. No single destination has sufficient space, but multiple have partial space:
             → Split by sub-components (e.g., each volume backed up independently to
                whichever destination has room for that volume)
             → Each sub-component gets its own restic repo, its own key rotation, its
                own KeePass path, and its own backup_history entry
             → The parent `snapshot_set_id` links all sub-component snapshots so restore
                knows they belong to the same logical backup point
             (routed_reason: `chunked_split`)
          4. Even sub-component splitting cannot fit within available space across all
             destinations → surfaces as a human-required decision; backup run records
             a BLOCKED status for the affected component; other components continue
      - All routing decisions (destination chosen, available space at run time,
          routed_reason) recorded in the component entry in `backup_history`
      - Restore reads routing from `backup_history` → secrets broker retrieves the
          correct key per component+destination+timestamp → restores each piece
          from its actual destination → assembles the full snapshot set automatically

      **Ordered destination chain execution:**
      - After space-aware routing determines where each component goes, backs up each
          component to its assigned destination
      - On completion runs `restic stats` to verify upload integrity (snapshot count
          and size must be consistent with expectations)
      - If verification fails or destination errors: logs with full error detail,
          marks destination as failed in this run, moves to next destination in chain
      - If all destinations fail for a layer:
          → Writes RED entry to backup_history
          → Increments `consecutive_all_fail_count`
          → Emits a structured failure record visible in the next assessment run
          → Never fails silently; surfaced in workbook, readiness report, and alerts

      **Retention and checkpoints:**
      - Applies `restic forget --prune --keep-last N` per destination after each
          successful backup (only on destinations that succeeded this run)
      - After pruning: removes corresponding per-snapshot KeePass entries; updates
          `current` alias to remain valid
      - Snapshots tagged `checkpoint` are excluded from forget regardless of N
      - Prompts operator to create a checkpoint if none exists after > 7 days

      **Run trigger:**
      - Triggered by assessment engine on completion of a full cluster assessment
      - Can also be run manually: `python3 proxmox-bootstrap/run-backup.py [--layer secrets|config|appdata]`
      - Dry-run mode: `--dry-run` shows what would be backed up, to which destinations,
          with current space probe results and routing decisions (no writes made)

- [ ] 6.B.4: **Simple mode** — one wizard, uniform policy across layers:
      - Operator defines a single ordered destination chain that applies to all layers
      - Per-layer overrides available but not required
      - Recommended starting point; detailed mode layers on top as needed

- [ ] 6.B.5: **Detailed mode** — per-node, per-VM, per-container, per-volume heterogeneous policy:
      - Each component defines its own ordered destination chain, retention count,
          and restic repo password (or inherits from parent explicitly)
      - Inheritance chain: cell → node → VM → container → volume; each level can
          override any field while inheriting the rest from the parent
      - Children create a sub-directory prefix at the inherited destination so backup
          data is co-located but separately addressable (`/cell/node/vm/volume/`)
      - Siblings' destination chains auto-suggested as defaults when configuring a new
          sibling (enter once, reuse across all sibling components)
      - Policy inheritance and credential reuse minimise repeated configuration entry
          while maintaining independent restic repos per component (dedup is per-repo)

- [ ] 6.B.6: Backup readiness scoring in `readiness.py`:
      - RED: no destination configured for secrets or configuration state layers
      - RED: `consecutive_all_fail_count` ≥ 2 (two consecutive complete-chain failures)
      - RED: last successful backup older than 3× schedule interval
      - ORANGE: last successful backup older than 2× schedule interval
      - ORANGE: any destination in chain has failed in last 3 runs (partial coverage)
      - YELLOW: all destinations healthy but last backup older than 1× schedule interval
      - YELLOW: no permanent checkpoint exists
      - GREEN: all destinations reachable, last backup within schedule, checkpoint exists

- [ ] 6.B.7: Backup status in recovery runbook — Appendix H:
      - Per-layer: destination chain with last-run status per destination (✓ / ✗ / skipped),
          last successful backup timestamp, snapshot count, most recent permanent checkpoint
      - All-fail history: if consecutive_all_fail_count > 0, shown prominently
      - Restic repo password KeePass paths listed (for manual recovery reference)

- [ ] 6.B.8: `proxmox-bootstrap/restore-from-backup.py` — automated restore engine:

      **Design principle:** maximise automation via secrets broker; operator enters
      master password once at the gate; everything else is automatic.

      **Snapshot discovery and selection:**
      - Probes each configured destination (in chain order) for available restic snapshots
      - Presents snapshot list: timestamp, tag, component, size
      - Defaults to "latest" unless operator specifies a date or checkpoint tag
      - `--latest`, `--checkpoint` (most recent tagged snapshot), `--date YYYY-MM-DD`,
          `--tag NAME` selection flags

      **Automated secret retrieval for per-backup keys:**
      - For each component being restored, reads its `backup_history` entry to find:
          `{destination, restic_snapshot_id, keepass_key_path, routed_reason}`
      - Resolves `keepass_key_path` (the timestamped per-backup path) via secrets broker
          — automatically retrieves the unique key that was current for that specific backup
      - For chunked-split restores: reads all sub-component entries sharing the same
          `snapshot_set_id`; resolves each sub-component's key independently; restores
          each piece from its actual destination; assembles full snapshot set
      - For service-level restores (post-restic): retrieves service credentials from
          KeePass and re-injects into service config — no per-service password re-entry

      **Restore execution:**
      - Restores to target path; verifies file integrity post-restore via `restic check`
      - For chunked-split snapshot sets: restores sub-components in dependency order
          (volumes before containers, containers before VMs), assembles into target path
      - Generates structured restore report: component, destination, snapshot ID,
          timestamp, `routed_reason`, integrity verification result, KeePass path used
      - If a destination is unreachable at restore time, tries other destinations that
          hold the same component (if any — depends on whether backup ran to multiple)
      - Supports `--dry-run` (lists what would be restored, from where, which keys used)
      - Supports `--component` flag: restore a single VM, container, or volume
      - Supports `--snapshot-set` flag: restore all components of a specific backup point
          (identified by `snapshot_set_id` from `backup_history`)

- [ ] 6.B.9: Documentation: `docs/CLOUD-STORAGE-SETUP.md` — step-by-step provider guides:
      - Google Drive (OAuth2 / Service Account — most complex; full walkthrough) ✓ written
      - Backblaze B2 (Application Key — simplest cloud option) ✓ written
      - AWS S3 (IAM user, access key/secret) ✓ written
      - Cloudflare R2 (S3-compatible, no egress fees) ✓ written
      - Self-hosted MinIO (S3-compatible, full privacy) ✓ written
      - Each guide dated; review reminder in document header

### Phase 7 — Service State

**7.1 — Service Contract Implementation**
- [ ] Service Contract YAML spec format
- [ ] Initial contracts for all known VMs
- [ ] Service contract reader in Tier 2 collector
- [ ] Service contract validator (observed vs. declared)
- [ ] Dependency graph builder updated to use contracts as primary source

**7.2 — Service State Schema and Collection**
- [ ] Finalise `service-state-schema.json` with `cell_id`
- [ ] Service state collector
- [ ] Service state in Tier 2 manifest
- [ ] Service contract completeness in readiness scorer

**7.3 — External Dependency State (Phase 7 addition from v5.0)**
- [x] `data-model/external-dependency-state-schema.json`
- [x] External dependency declaration format (DNS provider, SMTP, cert authority) — `external_dependencies` in bootstrap-state.json; `doc-gen/external_dependencies.py` ExternalDependencyRegistry
- [x] Certificate expiry monitoring (RED ≤ 7d, ORANGE ≤ 30d, YELLOW ≤ 60d) — `_score_external_dependency_state()` in readiness.py
- [x] External dependency section in Recovery Runbook — Appendix G (endpoint, type, required_by, cert expiry with severity callouts)

**7.4 — Recovery Documentation Update (Service Layer)**
- [x] Service contract block per VM in restore sequence: provided interfaces,
      required interfaces, startup_after note, restart commands, secret references,
      per-interface health check checkboxes
- [x] Health check commands derived from contract: curl for HTTP/HTTPS (uses
      url_pattern when available, falls back to vm_ip:port), pg_isready for postgresql,
      nc for smtp, empty for ssh (already in standard block)
- [x] Service restart commands: ssh ubuntu@{ip} 'sudo systemctl restart {svc}'
- [x] Appendix A: edge type legend (SERVICE★/DEPENDS_ON/STORAGE/NETWORK/BACKUP)
      + ★ marker on SERVICE edges to distinguish contract-driven from heuristic

### Phase 8 — Network Topology as Code

- [x] 8.1: Network topology declaration format — `data-model/network-topology-schema.json`
      (bridges, VLANs, firewall policy) + `network_topology_declared` section in
      bootstrap-state-schema.json + canonical fixture in bootstrap-state.json
- [x] 8.2: Network topology collector — `proxmox-bootstrap/network_topology_collector.py`:
      parse_interfaces_file() parses /etc/network/interfaces format;
      collect_observed_bridges() SSHes to host (injectable runner for tests);
      compare_topology() diffs declared vs observed; merge_observed_topology()
      writes drift results back into bootstrap-state.json
- [x] 8.3: Network topology drift detection — compare_topology() returns
      (drift_detected: bool, drift_details: str); merge_observed_topology()
      persists both fields; readiness scorer surfaces as ORANGE/RED
- [x] 8.4: Recovery documentation Wave 0 — build_recovery_runbook() now emits
      a full "Wave 0 — Network Reconstruction" section before the restore sequence:
      per-bridge IP, ports, vlan_aware; verify commands (ip link, ip addr);
      reconstruct commands (ifreload -a from /etc/network/interfaces);
      drift warning if drift_detected; "NOT DECLARED" UNRESOLVED field if absent
- [x] 8.5: Network topology completeness in readiness scorer —
      _score_network_topology_completeness(): YELLOW if not declared; ORANGE if
      drift detected; RED if all declared bridges are missing in observed state

### Phase 9 — Phoenix Playbooks *(Stargate Process — reconstruction scripts)*

These are the playbooks that form the execution layer of the stargate process —
per-wave, per-VM scripts that reconstitute a failed node's identity on new hardware.
See Phase 12.E for the hatchery process playbooks (broodling spawn scripts).

- [x] 9.1: Phoenix playbook format and schema — `data-model/phoenix-playbook-schema.json`:
      schema_version, cell_id, target_node (hostname, role, k3s_role), identity
      (lan_ip, tailnet_ip, vmids, bridge_names, zfs_pool_name), hardware_profile,
      restoration_scope (full|partial|deferred), deferred_services, waves (playbook_wave
      → playbook_step with id, action, commands, validation, method, on_failure, secret_refs),
      estimated_total_minutes, validation_checklist
- [x] 9.2: Playbook generator — `proxmox-bootstrap/phoenix_playbook.py`:
      PhoenixPlaybookGenerator class + build_phoenix_playbook() factory;
      reads manifest (host_identity, vms, dns_registry, network_topology_declared,
      storage_config, provenance_registry); now_fn injectable for tests;
      _zfs_topology_from_disk_count() adapts topology to replacement hardware
- [x] 9.3: Wave 0 (network reconstruction) + Wave 1 (ZFS pool) + Wave 2 (host config) +
      Wave 3 (VM PBS restore, identity-preserving — same VMIDs, IPs, provenance info) +
      Wave 4 (k3s membership + Flux reconciliation) generated with pre-populated commands
- [x] 9.4: Wave 0.5 (template rebuild) playbook — _wave_05_template_rebuild() in
      PhoenixPlaybookGenerator; inserted at wave=2.5 between host config and VM restore;
      _os_variant_for_vm() reads k3s-cluster.yaml server_nodes[].os_variant;
      Ubuntu path: download ISO + qm create + qm template; Talos path scaffolded
- [x] 9.5: Per-VM RECREATE vs RESTORE decision — _vm_is_stateless() checks
      service_contract.backup_job==null AND provenance_registry.tofu_workspace present;
      stateless VMs: RECREATE (tofu apply + Ansible playbook); stateful VMs: RESTORE (qmrestore)
- [x] 9.6: Shell script generator — proxmox-bootstrap/phoenix_scripts.py:
      generate_wave_script(wave) → bash script with checkpoint tracking per step;
      generate_run_all_sh(playbook) → orchestrating entry point that calls each wave script
      in wave-number order with failure detection
- [x] 9.7: Playbook validator — proxmox-bootstrap/phoenix_validator.py:
      validate_playbook() → list of {severity, field, message} findings;
      ERROR: missing required fields, empty waves, duplicate wave/step IDs, invalid enum values,
      empty step commands; WARNING: missing vmids/bridges/pool in identity, non-ascending waves;
      is_valid() and summarise_findings() helper functions
- [x] 9.8: Playbook existence in readiness scorer — _score_phoenix_playbook_existence():
      YELLOW if neither phoenix_playbook nor phoenix_playbook_generated_at is present
      in the manifest; wired into score_graph() alongside other registry gap scorers

**9.T — Talos Alternative Support** *(optional; activate by setting os_variant: talos)*

*Foundation — build and config tooling:*
- [ ] 9.T.1: `docs/TALOS-ALTERNATIVE.md` — prerequisites, build procedure for talos-1x-base
        template, talosctl installation, machine config generation, migration checklist
- [ ] 9.T.2: `proxmox-bootstrap/build-talos-template.sh` — downloads Talos ISO,
        creates Proxmox VM, converts to template (talos-1x-base, VMID 9001)
- [ ] 9.T.3: `proxmox-bootstrap/generate-talos-config.py` — generates talos machine
        configs from k3s-cluster.yaml (control plane + worker patches); stdlib only
- [ ] 9.T.4: Talos template entry in bootstrap-state.json template registry
        (talos-1x-base alongside ubuntu-2204-base; separate base_image entry)
- [ ] 9.T.5: bootstrap-state-schema.json — add `os_variant` enum (ubuntu | talos)
        to template registry entries and provenance_records
- [ ] 9.T.6: doc-gen readiness scorer — YELLOW if os_variant=talos but no Talos
        machine config found in repo (talos-configs/ directory absent)
- [ ] 9.T.7: Recovery runbook — emit Talos-specific reconstruction steps
        (talosctl apply-config instead of Ansible) when os_variant=talos
- [ ] 9.T.8: Tests for Talos config generator and runbook rendering

*OS transition automation — Ubuntu → Talos:*
- [ ] 9.T.9: `proxmox-bootstrap/migrate-k3s-to-talos.py` — automated migration script
        Steps: drain k3s node → snapshot VM → destroy Ubuntu VM → provision Talos VM
        from talos-1x-base template → apply machine config → verify cluster health →
        update bootstrap-state.json os_variant + provenance_records → commit to repo
        Flag: `--dry-run` prints plan without making changes
        Flag: `--skip-snapshot` for test environments where snapshot overhead is unwanted
        Guard: refuses to run if cluster health check fails pre-drain (RED readiness)
- [ ] 9.T.10: Pre-migration checklist validator — confirms all prerequisites before
        migration begins: talos-1x-base template exists, machine config generated,
        Velero PVC backup current (ORANGE if any check fails; migration blocked until GREEN)
- [ ] 9.T.11: Post-migration verifier — confirms k3s node rejoined cluster, all
        namespaces healthy, Flux reconciliation complete, PVCs reattached;
        writes migration completion record to bootstrap-state.json provenance_records
- [ ] 9.T.12: Recovery runbook — "OS Variant Migration" appendix documents the
        Ubuntu→Talos path with pre/post-migration steps and rollback procedure

*OS transition automation — Talos → Ubuntu:*
- [ ] 9.T.13: `proxmox-bootstrap/migrate-k3s-to-ubuntu.py` — automated reverse migration
        Steps: drain k3s node → snapshot VM → destroy Talos VM → provision Ubuntu VM
        from ubuntu-2204-base template → apply Cloud-Init + Ansible k3s-server role →
        verify cluster health → update bootstrap-state.json → commit to repo
        Same flags as 9.T.9 (--dry-run, --skip-snapshot)
        Guard: refuses to run if cluster health check fails pre-drain
- [ ] 9.T.14: Shared migration library `proxmox-bootstrap/migrate_k3s_lib.py`
        Extract common steps from 9.T.9 and 9.T.13: drain, snapshot, VM destroy,
        health check, provenance record update. Both migration scripts import this.
- [ ] 9.T.15: Migration state file `bootstrap-state.json migration_history` array
        Each completed migration appended: from_variant, to_variant, migrated_at,
        migrated_by, snapshot_vmid (for rollback), pre_migration_k3s_version
- [ ] 9.T.16: Rollback procedure — if post-migration verifier fails, restore VM from
        pre-migration snapshot, update os_variant back, re-run health check;
        rollback outcome appended to migration_history
- [ ] 9.T.17: Tests for both migration scripts (mock Proxmox API + mock talosctl/ansible)

### Phase 10 — Operational Documentation

- [x] 10.1: Operational documentation class design — `doc-gen/renderers/operational_report.py`;
      seven sections: overall readiness, drift summary, capacity, service health,
      secret completeness, external dependencies, time-sensitive actions
- [x] 10.2: Drift summary renderer — Section 2 reads manifest["drift"] (from compute_drift());
      shows from/to snapshot, severity, changed fields (capped at 30)
- [x] 10.3: Capacity trend renderer — Section 3 reads cpu/memory/storage from manifest;
      ORANGE/RED warnings on RAM ≥90% or storage ≥90% utilization
- [x] 10.4: Service health summary renderer — Section 4 reads manifest["service_state"];
      shows running/stopped/degraded counts and per-service status line
- [x] 10.5: Secret registry completeness renderer — Section 5 reads manifest["secret_registry"];
      shows total/with-path counts; lists secrets missing keepass_path
- [x] 10.6: Wire into engine.py — run_operational() function + `--mode operational` choice;
      loads all registries, computes drift + readiness, renders Operational-Report.odt
- [x] 10.7: Scheduled refresh — `proxmox-bootstrap/setup-operational-schedule.sh` installs
      broodforge-operational.service + broodforge-operational.timer (every hour)

### Phase 11 — Capacity Model

- [x] 11.1: Capacity model schema — `capacity_model` section added to bootstrap-state-schema.json:
      thresholds (cpu/ram/storage warn/crit pcts + restoration_headroom_pct),
      observed (snapshot: ram/storage usage pcts + totals), trend (direction + days_to_full)
- [x] 11.2: Capacity tracking — `proxmox-bootstrap/capacity_collector.py`:
      collect_capacity_snapshot() reads cpu/memory/storage from manifest;
      merge_capacity_model() updates bootstrap-state.json with observed + trend
- [x] 11.3: Capacity validation in readiness scorer — _score_capacity_model():
      YELLOW: no capacity_model; YELLOW/ORANGE: RAM/storage above warn/crit threshold
- [x] 11.4: Trend analysis — compute_trend() derives direction (increasing/stable/decreasing)
      and days_to_full projection from ordered historical snapshots; uses linear rate
- [x] 11.5: ORANGE if target host cannot accommodate restored workload —
      check_restoration_headroom() compares sum(VM RAM) vs host RAM × (1 - headroom_pct)

### Phase 12 — Full Single-Cell Reconstruction Test

- [x] 12.1: End-to-end drill framework — `proxmox-bootstrap/reconstruction_drill.py`:
      DrillRecord (per-wave timing, gap tracking), start_drill() factory from phoenix playbook,
      save_drill_record() / get_last_drill() for bootstrap-state persistence,
      `reconstruction_drills[]` schema in bootstrap-state-schema.json;
      `docs/RECONSTRUCTION-DRILL.md` operator guide (live + tabletop modes)
- [x] 12.2: Reconstruction time measurement — DrillRecord.record_wave() tracks
      estimated vs actual minutes per wave; generate_drill_report() produces Markdown
      table with timing comparison and accuracy %; DrillRecord.accuracy_pct property
- [x] 12.3: Gap identification — DrillRecord.gaps_found/gaps_remediated; readiness scorer
      _score_reconstruction_drill(): YELLOW if no drill, YELLOW if > 90 days stale,
      ORANGE if last drill was failed/aborted; wired into score_graph()
- [x] 12.4: Scheduled drill activity — `proxmox-bootstrap/schedule-reconstruction-drill.sh`
      installs broodforge-drill-reminder.timer (fires every 90 days, logs journal reminder)

**Gate:** Phase 12 completion validates the single-cell foundation.
Track 2 begins after Phase 12.

### Phase 12.E — Node Spawn Bootstrap *(Hatchery Process)*

*The existing cluster is the hatchery. Additional nodes — broodlings — are spawned
from it via the **hatchery process**. Phase 12.E adds the ability to run the
hatchery process: the assessment engine produces a **spawn package** — a
self-contained archive of scripts and a reserved-resource data dump — that is
copied to a broodling after bare Proxmox installation and executed there. The
broodling joins the existing Proxmox cluster and k3s cluster without VMID, IP,
or hostname conflicts.*

**Hatchery process vs stargate process:**
The hatchery process (this phase) assigns *new* identity — VMIDs, IPs, hostnames
that don't conflict with anything already in the hatchery.
The stargate process (Phase 9) preserves *existing* identity — the exact VMIDs,
IPs, hostnames, and certs of a node that failed, reconstituted on new hardware.

**Context:** Phase 12 answers "can I rebuild this?" Phase 12.E answers "can I
spawn a broodling into this datacenter?" The assessment engine knows everything
the hatchery has reserved — IPs, VMIDs, hostnames, k3s join tokens, cluster
topology — and encodes that knowledge into the spawn package so the broodling
never needs to ask the operator what is already taken.

- [x] 12.E.1: **Hatchery state reader** — reads `bootstrap-state.json` and queries
      the live Assessment Engine API to extract a point-in-time reservation snapshot:
      all allocated VMIDs, all assigned IPs (from DNS registry + provenance records),
      all hostnames, Proxmox cluster join address, k3s server/worker counts,
      k3s join tokens (worker and server). Produces `spawn-manifest.json`.
      This is the authoritative "what the hatchery has reserved" data dump embedded
      in every spawn package.

- [x] 12.E.2: **Conflict validator** (`proxmox-bootstrap/validate-spawn.py`) —
      run before the spawn package is generated and again on the broodling before
      any deployment action:
      - No VMID collisions (proposed new VMIDs vs all VMIDs in spawn-manifest.json)
      - No IP collisions (proposed new IPs vs all IPs in spawn-manifest.json)
      - No hostname collisions (proposed hostnames vs all hostnames in spawn-manifest.json)
      - Placement policy satisfied (proposed roles are declared for this host type)
      - Capacity check: broodling RAM sufficient for its assigned VM roles
      RED finding on any collision blocks spawn package generation until resolved.
      The validator is designed to be re-run on the broodling from the spawn package
      itself, using only the embedded manifest (no live API access required).

- [ ] 12.E.3: **Spawn planner with execution mode gate and service selection**
      (`proxmox-bootstrap/spawn-planner.py`) —

      The planner runs on the hatchery. **Execution mode is the first question**,
      because the answer determines whether service selection happens at all.

      **Step 0 — Network mode (asked before anything else):**

      Because the hatchery runs split-horizon DNS, the Headscale server URL in every
      spawn package is always the hatchery's FQDN (`host_identity.fqdn`):
        `https://hatchery.home.example.com:8080`
      LAN broodlings resolve this to the LAN IP via the hatchery's dnsmasq.
      WAN broodlings resolve this to the WAN IP via public DNS.
      The same spawn package works from both locations without modification.

      The planner still asks which network mode the broodling is on, because
      the SSH discovery path differs (direct IP vs tailnet IP):

      ```
      Is the broodling on the same LAN as the hatchery?
      [auto-detecting — trying {broodling-ip} directly... timeout 5s]

        1. Same LAN  — direct SSH using temporary root password
        2. WAN       — Headscale tailnet (generates auth key; Headscale URL is
                       hatchery.{domain} — already correct for both LAN and WAN)
        3. Specify   — enter broodling IP / hostname manually

      > _
      ```

      **LAN mode:** proceeds with the existing temporary root password flow.
        Broodling is configured to use hatchery as its DNS server (via DHCP or
        static config in spawn package), so `hatchery.{domain}` resolves to LAN IP.

      **WAN mode:** the planner calls:
        `headscale authkeys generate --expiration 1h --user broodforge`
        The auth key and `https://hatchery.{domain}:8080` are embedded in the
        spawn package. phase-00a on the broodling:
          Installs Tailscale: `curl -fsSL https://tailscale.com/install.sh | sh`
          Registers: `tailscale up --authkey {key}
                                   --login-server https://hatchery.{domain}:8080`
          (The FQDN resolves to WAN IP via public DNS, which routes to Headscale
          via the operator's router port forwarding.)
          Broodling appears on tailnet → hatchery SSHes to its tailnet IP for discovery.
        After spawn completes, Tailscale remains installed — the broodling is a
        permanent tailnet member. Its tailnet IP is recorded in bootstrap-state.json
        alongside its LAN IP (if any).

      **Step 1 — Execution mode (asked after network mode):**

      ```
      How should the spawn package run on the broodling?

        1. Autonomous (default)  — finalise service selection now; spawn.sh runs
                                   without prompting after the KeePass unlock gate
        2. Interactive            — no selection needed now; spawn.sh evaluates the
                                   broodling's hardware at runtime and presents the
                                   service menu there

      > _
      ```

      **If Interactive:** the planner records `execution_mode: interactive` and
      proceeds directly to package assembly. No service selection on the hatchery.
      The package includes all available service scripts. Service selection happens
      entirely on the broodling at execution time against actual hardware.

      **If Autonomous:** the planner continues to Step 2.

      For autonomous mode, the planner also generates a **suggested temporary root
      password** (readable passphrase format) at this point and displays it to the
      operator with the instruction to use it when setting the Proxmox root password
      during installation. The hatchery stores this password in memory for the
      duration of the spawn-planning session so it can use it for password-based SSH
      discovery without the operator re-entering it. The password is NOT stored in
      KeePass — it is temporary, replaced by a proper KeePass-managed credential
      during the spawn process.

      **Step 2 — Service selection (autonomous only):**

      The planner reads the service catalog (`metadata/service-catalog.yaml`) to
      know what the hatchery runs and the broodling's hardware profile to know what fits.

      **Mode 1 — Full mirror:**
      Selects all services that fit the broodling's hardware.
      Services that don't fit are listed with a reason (RAM, disk, dependency) and
      excluded. The operator reviews the exclusion list and confirms or switches mode.

      **Mode 2 — Select by group:**
      Services grouped by category (Infrastructure, Platform, Intelligence,
      Monitoring, Applications). Operator includes/excludes whole groups, then
      fine-tunes individual services within groups.

      **Mode 3 — Select individually:**
      Every service listed with hardware fit status, resource requirements, and
      dependencies. The planner enforces dependencies: selecting nextcloud
      automatically selects longhorn if not already selected.

      **Hardware fit display for each service:**
        [✓] fits — RAM available vs required shown; disk requirements shown
        [!] marginal — fits with reduced VM sizing; operator warned explicitly
        [✗] does not fit — specific shortfall shown (RAM delta, missing disk, etc.)
      Services marked [✗] are excluded regardless of selection.

      **The intelligence baseline is always included and cannot be deselected:**
      Proxmox cluster membership, k3s worker, assessment/doc engine visibility,
      `bootstrap-state.json` contribution. This is the minimum viable participation.

      **Produces `spawn-plan-{hostname}.json` containing:**
      - `disposition.execution_mode` — `autonomous` | `interactive`
      - `disposition.services` — selected service names (autonomous only; empty for interactive)
      - `disposition.mode` — `full-mirror` | `group` | `individual` (autonomous only)
      - `disposition.excluded` — services excluded with reason (autonomous only)
      - Non-conflicting VMID block, IPs, hostnames
      - ZFS pool topology from disk configuration
      - For autonomous: only VM roles, Cloud-Init snippets, Ansible roles for selected services
      - For interactive: full service catalog scripts included; selection deferred to broodling
      - k3s node labels and taints (autonomous: derived from selection; interactive: set at runtime)
      - Proxmox cluster join address (from manifest)
      - k3s join token type: worker always; server only if k3s-server selected (or selectable)
      - If 3rd server node possible: etcd migration plan included in interactive; locked in autonomous

- [x] 12.E.4: **Spawn hardware discovery (autonomous mode only)** — produces
      `hardware-profile-{hostname}.json` before the spawn package is generated.
      This is the input to the spawn planner for hardware-specific adaptation:
      disk topology → ZFS pool type, NIC inventory → bridge definitions, RAM → VM sizing.

      Two discovery paths depending on network mode selected in Step 0 of 12.E.3:

      **LAN mode — password-based SSH (same-network broodling):**
        The spawn planner generates a suggested temporary root password (readable
        passphrase format, e.g. `Ready.to.spawn.7`) at Step 0 selection time.
        The operator uses this password during Proxmox installation.
        The hatchery holds the password in session memory and SSHes directly:
          `python3 discover-hardware.py --host {broodling-lan-ip} --password-prompt`
          (password retrieved from session, not re-entered by the operator)
          → `hardware-profile-{hostname}.json`
        If the operator used a different password, they enter it when prompted.
        Password transmitted over the trusted LAN only.
        Valid from: Proxmox installation complete.
        Valid until: Cloud-Init sets the real KeePass-managed credential.
        Not stored in KeePass; not persisted after the spawn session.

      **WAN mode — Headscale tailnet (cross-network broodling):**
        The spawn package contains the Headscale auth key and server URL.
        The broodling's `phase-00a` (runs before hardware pre-flight) installs
        Tailscale and registers with the hatchery's Headscale:
          `curl -fsSL https://tailscale.com/install.sh | sh`
          `tailscale up --authkey {key} --login-server {headscale_url}`
        Broodling appears on the tailnet → hatchery SSHes to its tailnet IP exactly
        as in LAN mode (temporary root password, same mechanism):
          `python3 discover-hardware.py --host {tailnet-ip} --password-prompt`
        No port forwarding required. The WireGuard tunnel is the transport;
        the temporary root password is still the authentication.
        After spawn completes, Tailscale remains — the broodling is a permanent
        tailnet member. Its tailnet IP is recorded in bootstrap-state.json.

      **Interactive mode:** no hardware discovery on the hatchery is needed.
        spawn.sh discovers hardware locally on the broodling at runtime.
        In WAN mode, phase-00a (Tailscale join) still runs first so the hatchery
        can reach the broodling for any follow-up coordination.

      Discovery output is embedded in autonomous spawn packages so phase-00 can
      reference disk IDs and NIC layout without re-running discovery on the broodling.

- [x] 12.E.5: **Spawn IaC and config generator** — from `spawn-plan-{hostname}.json`:
      - OpenTofu `.auto.tfvars` for this host's VM set
      - Cloud-Init snippets with this host's allocated IPs (from spawn plan, not hatchery IPs)
      - Ansible inventory additions (this host appended to existing groups)
      - k3s join token embedded in Ansible role vars (from spawn manifest)

- [x] 12.E.6: **Spawn scripts** — generated shell scripts using the same
      checkpoint/failure-package/ODS-update library as recovery scripts.
      All scripts read from spawn-plan.json; bridge names, pool names, and IPs
      are consistent across phases because phase-00 creates what later phases reference.

      - `spawn.sh` — orchestrated entry point; runs all phases in order

      *Host-level phases (Proxmox host must be configured before VMs can exist):*

      - `phase-00-host-bootstrap.sh` — two sub-stages, always in order:

        **Sub-stage A: Hardware pre-flight (read-only, no changes made)**
        Re-scans the broodling's actual hardware and compares against the embedded
        `hardware-profile.json` and `spawn-plan.json`. This catches any divergence
        between what was discovered on the hatchery and what is actually present now.
        Checks (all must pass before sub-stage B runs):
          - Disk IDs in spawn plan exist on this host and have the expected capacity
          - NIC names/MACs match the embedded hardware profile
            (Proxmox can renumber NICs after kernel updates or hardware changes)
          - Available RAM ≥ sum of VM RAM in spawn plan + 10% host overhead
          - No existing ZFS pool with a name that conflicts with the planned pool
          - No existing network bridge with a name that conflicts with the plan
          - Conflict re-validation: re-runs validate-spawn.py against spawn-manifest.json
            (catches any hatchery reservations made between package generation and now)
        On any mismatch: generates a failure package with a clear "hardware mismatch"
        or "stale manifest" diagnosis, prints the diff, and exits without making
        any changes to the broodling. The operator re-runs discovery on the hatchery
        and regenerates the spawn package.
        On pass: proceeds to sub-stage B.

        **Sub-stage B: Host configuration (writes config, creates pool, activates network)**
        Must run before any VM creation because VMs reference bridges and datastores
        that only exist after this stage:
          set hostname + fix /etc/hosts (pvecm add fails if hostname → 127.0.0.1)
          write bridge definitions to /etc/network/interfaces (per NIC layout in plan)
          ifreload -a to activate bridges without full reboot
          zpool create per plan topology (disk IDs confirmed by pre-flight)
          pvesm add zfspool to register pool as Proxmox datastore
          configure apt repos (no-subscription or enterprise)
        Output: Proxmox host ready to accept VM provisioning and cluster join.

      - `phase-01-join-proxmox.sh` — `pvecm add <hatchery-address>` using Proxmox cluster
        join address and fingerprint from spawn manifest; idempotent (detects if
        already a member). New host now visible in Proxmox datacenter.

      *VM provisioning phases (depend on phase-00 bridge/datastore names existing):*

      - `phase-02-vms.sh` — `tofu apply` using tfvars from spawn plan; bridge
        names and datastore names in tfvars match what phase-00 created exactly.

      - `phase-03-cloudinit.sh` — install generated Cloud-Init snippets (user-data,
        network-config, vendor-data) into Proxmox snippet store on this host;
        start VMs; poll SSH readiness for each VM before proceeding.

      *Cluster join phases (depend on VMs running):*

      - `phase-04-join-k3s.sh` — run Ansible k3s-server or k3s-worker role against
        the new VMs using join token from spawn manifest; selects correct token type
        (worker or server) based on spawn plan role.

      - `phase-05-promote-ha.sh` (conditional) — SQLite → embedded etcd migration;
        only generated when this broodling creates the 3rd k3s server node. Existing
        hatchery cluster is quiesced, etcd promoted, control plane distributed. If this phase
        is not needed, it is omitted from the package entirely.

      - `phase-06-verify.sh` — cluster health check (all nodes Ready, all VMs
        running), re-runs conflict validator against live Proxmox and k3s state
        as final confirmation. Failure here generates a failure package.

      *[Automatic after phase-06 — no further operator action:]*
      *Flux CD detects new k3s nodes, schedules workloads per anti-affinity rules.*
      *Assessment Engine detects broodling in Proxmox API, updates scores.*
      *Documentation Engine regenerates topology with broodling included.*

- [ ] 12.E.7: **Spawn package assembler** (`proxmox-bootstrap/assemble-spawn-package.py`) —
      bundles spawn-manifest.json, spawn-plan-{hostname}.json, generated scripts,
      OpenTofu tfvars, Cloud-Init snippets, Ansible additions, spawn workbook ODS,
      and the shared script library into:
      `spawn-package-{cell_id}-{hostname}-{YYYY-MM-DD_HH_MM_SS}.tar.gz`
      The package is self-contained and offline-capable: the broodling does not need
      to reach the hatchery's API during execution.
      **The package never contains the KeePass database or any secret values.**
      It contains only KeePass secret paths (references). See AD-042.

- [ ] 12.E.7a: **KeePass unlock gate in spawn.sh** — before any phase accesses secrets,
      `spawn.sh` prompts the operator to enter the KeePass master password and verifies
      it unlocks the operator's KeePass database (copied separately to the broodling or
      accessed via a known path). Scripts retrieve individual secrets programmatically
      from the unlocked database; no secret value is written to the broodling's disk in
      plain text. The gate runs regardless of execution mode (autonomous or interactive).
      In autonomous mode, this is the only prompt before fully automated execution.
      In interactive mode, this gate is followed by the service selection prompt.

- [ ] 12.E.8: **Spawn workbook** (ODS) — embedded in the spawn package; tracks
      each phase with the same checkpoint/status/timestamp/validation pattern as
      the recovery workbook:
      - Sheets: Overview, Discovery, Storage, Network, Proxmox-Join, VMs, k3s-Join, Validation
      - Machine-updated by each spawn script phase
      - Spawn failure package generated automatically if any phase fails

- [x] 12.E.9: **Bootstrap-state.json updater** — runs on the hatchery after the
      broodling reports successful spawn (phase-08-verify.sh exits 0); merges the broodling's
      hardware profile, allocated VMIDs, IPs, hostnames, and cluster role into
      `bootstrap-state.json`; adds provenance records for new VMs; commits to Forgejo.
      Assessment Engine reassessment triggered automatically by Forgejo webhook.

- [x] 12.E.10: **Disposition-aware assessment scoring** — the Assessment Engine
      reads `disposition.services` from each host's entry in `bootstrap-state.json`
      and adjusts placement compliance evaluation to match declared intent:
      - Placement compliance is checked per service, per host: is this service
        running on the hosts that declared it in their disposition?
      - A node without `prometheus` in its service list is not penalized for
        missing a Prometheus replica
      - A node without `k3s-server` is not scored against HA control-plane
        distribution requirements
      - A node without `pbs-datastore` is not flagged for missing backup targets
      - The assessment report shows each host's `disposition.services` list
        alongside its scores — visible confirmation of what each node is expected
        to contribute and whether it is delivering
      - `disposition.excluded` (services that didn't fit at spawn time) is also
        shown, so the operator knows what was intentionally left out vs. what
        drifted away after deployment
      - A mismatch between `disposition.services` and observed reality remains a
        RED finding — disposition does not excuse services that were selected but
        are not running

- [ ] 12.E.11: **Spawn scenarios tested:**
      - Baseline only (small machine): joins cluster, visible to assessment, no workloads
      - Compute disposition: k3s workers added, Flux schedules workloads
      - Storage disposition: PBS datastore added, Longhorn replicas
      - Control-plane disposition: HA promotion if 3rd server node
      - Mixed disposition (compute + storage): combined deployment
      - Hardware insufficient for selected flag: flag dropped with warning, rest proceeds
      - Full peer disposition: matches hatchery capabilities
      All scenarios use fixture hardware profiles. Conflict detection validated with
      deliberate VMID/IP/hostname collision fixtures.

- [ ] 12.E.12: **Documentation:** `proxmox-bootstrap/NODE-SPAWNING.md` — operator
       runbook covering: prerequisites (bare Proxmox installed, SSH access),
       running hardware discovery on the broodling, selecting disposition interactively
       on the hatchery, reviewing the spawn plan's hardware fit assessment and warnings,
       copying and executing the spawn package on the broodling, verifying cluster
       health, and confirming `bootstrap-state.json` is updated with the broodling's
       disposition and state.

**Note on hardware heterogeneity:** The spawn planner explicitly does NOT require
identical hardware. A second host with 6 HDDs gets raidz1; the first host with
2 SSDs has a mirror. Both run the same VM roles and software stack. Only the
hardware adaptation layer (ZFS topology, NIC bridge config, VM sizing within
available RAM) differs between them.

**Note on Talos variant:** If `os_variant: talos` is declared for k3s-server nodes
(see Milestone 9.T), the spawn planner emits Talos machine configs instead of
Cloud-Init for server VMs on the broodling. The spawn plan records `os_variant`
per VM, matching the existing cluster's declared variant.

---

## Track 2 — Expanded State Model

### Phase 13 — Hardware and Platform State

- [ ] 13.1: `data-model/hardware-state-schema.json` (BIOS, firmware, disks, NICs, UPS)
- [ ] 13.2: Hardware State Tier 1 collector (extend bootstrap assessment)
- [ ] 13.3: `data-model/platform-state-schema.json` (Proxmox config, certs, packages)
- [ ] 13.4: Platform State Tier 2 collector
- [ ] 13.5: Hardware requirements declaration in Bootstrap State
- [ ] 13.6: Pre-reconstruction hardware verification playbook
- [ ] 13.7: Hardware and Platform readiness scoring

### Phase 14 — Cluster and Storage State

- [ ] 14.1: `data-model/cluster-state-schema.json` (identity, topology, membership, history)
- [ ] 14.2: Cluster State collector (Proxmox cluster API, Corosync, HA manager)
- [ ] 14.3: `data-model/storage-state-schema.json` (ZFS, Ceph, CephFS, RBD, datastores)
- [ ] 14.4: Storage State collector (ZFS CLI, Ceph status API)
- [ ] 14.5: Ceph FSID in readiness scorer (RED if missing)
- [ ] 14.6: Cluster and Storage waves in Reconstruction Playbook generator

### Phase 15 — Data Protection State

- [ ] 15.1: `data-model/data-protection-state-schema.json` (PBS, jobs, retention, RTO/RPO)
- [ ] 15.2: Data Protection collector (PBS API, backup job inventory, verification status)
- [ ] 15.3: RTO/RPO declaration format and compliance scoring
- [ ] 15.4: Backup encryption key recoverability check (RED if not recoverable)
- [ ] 15.5: PBS self-recovery plan check (ORANGE if absent)
- [ ] 15.6: Data Protection readiness scoring additions

### Phase 16 — Observability State

- [ ] 16.1: `data-model/observability-state-schema.json` (monitoring stack, alerts, dashboards)
- [ ] 16.2: Observability State collector
- [ ] 16.3: Observability reconstruction in playbook generator
- [ ] 16.4: Alert rule restoration in Recovery Runbook

### Phase 17 — Digital Twin Foundation

- [ ] 17.1: Cell Identity schema and registry (`twin/federation/cells/`)
- [ ] 17.2: Twin storage layout (full `twin/` directory structure)
- [ ] 17.3: Twin state writer (all collectors write to twin, not only history/)
- [ ] 17.4: Staleness manifest (per-field confidence and last-updated tracking)
- [ ] 17.5: Twin consistency checker (stale, missing, conflicting state detection)
- [ ] **17.6: `cell_id` migration — all existing schemas updated (federation gate)**

### Phase 18 — Capability and Secret Reference State

- [ ] 18.1: `data-model/capability-state-schema.json` (all capability categories)
- [ ] 18.2: Capability declaration format and initial declaration
- [ ] 18.3: Capability verification in Tier 2 assessment
- [ ] 18.4: Capability index builder (aggregation across all cells)
- [ ] 18.5: `data-model/secret-reference-state-schema.json` (standalone, with `owning_cell`)
- [ ] 18.6: Secret Reference State migration (extract from Bootstrap State)
- [ ] 18.7: Capability-based readiness scoring additions

**Gate:** Phase 18 completion validates the expanded state model.
Track 3 begins after Phase 18.

---

## Track 3 — Digital Twin and Federation

### Phase 19 — Federation State and Trust Model

- [ ] 19.1: `data-model/federation-state-schema.json` (cell registry, relationships, trust)
- [ ] 19.2: Cell identity and federation registry
- [ ] 19.3: Trust relationship schema and declaration format (all relationship types)
- [ ] 19.4: Trust relationship verification procedure (CLI + automated check)
- [ ] 19.5: Recovery relationship schema and declaration format
- [ ] 19.6: Recovery relationship verification (backup reachable, history readable)
- [ ] 19.7: Tier 3 assessment engine (cross-cell, federation-scope)
- [ ] 19.8: Federation State tests

### Phase 20 — Federation Documentation Generation

- [ ] 20.1: Federation Workbook renderer (all cells, all relationships, federation readiness)
- [ ] 20.2: Federation Runbook renderer (coordination procedures)
- [ ] 20.3: Cell Workbook (full 17-state view per cell)
- [ ] 20.4: Cell Runbook (full cell reconstruction)
- [ ] 20.5: Cluster Workbook and Runbook
- [ ] 20.6: Node Workbook and Runbook
- [ ] 20.7: Dependency Workbook (all five graph types, multi-cell scope)
- [ ] 20.8: Command Reference Sheets (pre-populated for all known values)
- [ ] 20.9: Validation Sheets (post-recovery checklists)

### Phase 21 — Failure Domain Modeling

- [ ] 21.1: Failure domain taxonomy schema
- [ ] 21.2: Failure propagation rules engine (storage → VMs → services propagation)
- [ ] 21.3: Blast radius calculator (given failure at level X, enumerate affected)
- [ ] 21.4: SPOF detection (components with no recovery alternative)
- [ ] 21.5: Circular recovery dependency detection
- [ ] 21.6: Failure domain analysis in readiness reports

### Phase 22 — Multi-Level Readiness Assessment

- [ ] 22.1: Hardware-level readiness scoring (new inputs from Phase 13)
- [ ] 22.2: Cluster-level readiness scoring (new inputs from Phase 14)
- [ ] 22.3: Cell-level readiness (aggregation across all 17 state categories)
- [ ] 22.4: Federation-level readiness (aggregation across all cells)
- [ ] 22.5: Federation Readiness Report
- [ ] 22.6: Tier 3 assessment integration with multi-level readiness

### Phase 23 — Federated Reconstruction Planning

- [ ] 23.1: Recovery coordinator model (coordinator selection from capability index)
- [ ] 23.2: Phoenix package assembly (history, docs, repos, secrets, backup locations)
- [ ] 23.3: Capability matching (find available cells for each recovery need)
- [ ] 23.4: Multi-phase reconstruction playbook generator (all 7 phases)
- [ ] 23.5: Cross-cell trust establishment automation
- [ ] 23.6: Temporary workload migration planning
- [ ] 23.7: Federated reconstruction tests

### Phase 24 — Continuous Assessment and Twin Maintenance

- [ ] 24.1: Scheduled assessment framework (cron-driven, cell-scoped)
- [ ] 24.2: Repository ingestion hooks (git webhook → twin update on push)
- [ ] 24.3: Deployment event hooks (tofu apply / ansible run → twin update)
- [ ] 24.4: Staleness alerting (notify when state categories exceed threshold)
- [ ] 24.5: Twin diff reporting (what changed in the twin since last report)
- [ ] 24.6: PBS API integration for continuous Data Protection State updates
- [ ] 24.7: Certificate expiry monitoring (continuous External Dependency State)

### Phase 25 — Reconstruction Validation

- [ ] 25.1: Reconstruction drill framework (scheduled full-destroy + reconstruct)
- [ ] 25.2: Reconstruction time measurement and RTO validation
- [ ] 25.3: Automated post-reconstruction assessment and comparison
- [ ] 25.4: Gap identification and remediation tracking
- [ ] 25.5: Federation reconstruction drill (multi-cell coordinated scenario)

---

## Design Principles

1. **Reconstruction is the objective.** Every state category, metadata field, and
   documentation artifact is evaluated against: "Does this enable reconstruction
   from repository state after complete infrastructure loss?"

2. **Documentation is generated, not authored.** Technical infrastructure information
   is collected automatically. Operators provide only what cannot be discovered.

3. **Cell scope is universal.** `cell_id` is mandatory on every state document.
   No single-environment assumptions anywhere in the data model.

4. **The Digital Twin is the source of truth.** All outputs derive from the twin.

5. **Recovery relationships are explicit.** Which cell holds what for whom is
   declared and verified, not assumed.

6. **Missing information is surfaced, never silently omitted.** UNRESOLVED and
   STALE fields are always visible with reason, impact, and remediation guidance.

7. **Trust is declared and verified.** Inter-cell trust has expiry, is verified at
   Tier 3 assessment, and expired trust degrades federation readiness scores.

8. **Historical snapshots are reproducible.** Same twin state always produces same outputs.

9. **Readiness scoring is honest.** RED means recovery will likely fail.

10. **Single-cell work must be federation-ready from the start.** `cell_id` in all
    schemas. Recovery playbooks organized by cell. Documentation scoped by cell.
    The federation layer is added above, not retrofitted below.
