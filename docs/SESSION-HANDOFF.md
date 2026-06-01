# Session Handoff

Date: 2026-05-31 UTC (updated after Milestone 7.4 — Recovery Documentation Update Service Layer)
Status: Milestones 7.1–7.4, 6.B, Phase 8 complete. Ready to resume at Phase 9 — Phoenix Playbooks

---

## Project Identity

Project: **broodforge** — Self-Documenting, Self-Recovering Infrastructure Platform

| Term | Meaning |
|---|---|
| **Forging** | Initial deployment of the first node — bare hardware → hatchery |
| **Forge package** | Self-contained archive for forging the first hatchery |
| **Hatchery** | The operational first node (what forging produces) |
| **Hatchery process** | Phase A subsequent: produces spawn packages for broodlings |
| **Broodling** | A newly spawned node joining the hatchery |
| **Spawn package** | Self-contained archive for deploying a broodling (new identity) |
| **Stargate process** | Phase C/D: produces phoenix packages for failed nodes |
| **Phoenix package** | Self-contained archive for rebuilding a failed node (identity preserved) |

---

## Active Architecture: v7.1

Self-Documenting, Self-Assessing, Self-Recovering Infrastructure Platform
with Hatchery Process (broodling spawn) and Stargate Process (phoenix rebuild).
k3s + Flux CD + Proxmox + four intelligence layers.
Full review: docs/ARCHITECTURE-REVIEW-v7.md | Roadmap: ROADMAP.md (25-phase, 3 tracks)

---

## Completed This Project

### Phases 0–3 (proxmox-bootstrap + ansible)
See ROADMAP.md for full detail. All complete.

### Milestones 6.1–6.8, 7.1–7.3 (see CURRENT_STATE.md for full table)

All complete. Test count: **1228 total (1224 passed, 4 skipped)**

Test runner: `C:\Users\dave\AppData\Local\Programs\Python\Python311\python.exe -m pytest tests/unit/ -q`

---

## Completed: Milestone 7.3 — External Dependency State

### What was built

  data-model/external-dependency-state-schema.json
      Standalone schema for External Dependency State documents.
      Fields: schema_version, cell_id, declared_at, collection_errors, dependencies[].
      dependency entry: id, name, type (dns_provider/smtp_relay/cert_authority/ntp_server/
        container_registry/package_repo/vpn_gateway/object_storage/monitoring_sink/other),
        endpoint, description, required_by, status, last_checked_at, certificate{}, failover, notes.
      certificate sub-object: expires_at, issued_at, issuer, subject, sans, last_checked_at, auto_renew.

  data-model/bootstrap-state-schema.json
      Added optional `external_dependencies` array property (same definition inline).

  tests/fixtures/bootstrap/bootstrap-state.json
      Added 3 sample external dependencies:
        cloudflare-dns     (dns_provider,  with cert — expires 2027-03-15)
        smtp-relay-sendgrid (smtp_relay,    no cert — STARTTLS on port 587)
        letsencrypt-acme   (cert_authority, with cert — expires 2026-06-15)
      The letsencrypt cert is set to expire ~15 days out to exercise ORANGE scoring.

  doc-gen/external_dependencies.py
      ExternalDependencyRegistry — wraps external_dependencies list:
        available(), count(), all(), get(dep_id)
        with_certificates() — entries with certificate declared
        expiring_within_days(n, now) — certs expiring within n days; injects _days_remaining
        days_until_expiry(dep, now) — integer days until cert expires, or None
      build_external_dependency_registry(manifest) — factory from manifest dict
      Constants: CERT_EXPIRY_RED_DAYS=7, CERT_EXPIRY_ORANGE_DAYS=30, CERT_EXPIRY_YELLOW_DAYS=60

  doc-gen/readiness.py
      _score_external_dependency_state(manifest) — new function:
        Iterates over with_certificates() entries.
        days_remaining <= 7  → RED  (imminent — services will fail)
        days_remaining <= 30 → ORANGE (critical action required)
        days_remaining <= 60 → YELLOW (plan renewal)
        No certificate or no external_dependencies → no gap.
        component_id prefixed with "external:" e.g. "external:cloudflare-dns"
        gap_type = "CERT_EXPIRY"
      Wired into score_graph() alongside other registry gap checks.

  doc-gen/engine.py
      Both run_bootstrap() and run_recovery() now:
        Load external_dependencies from bootstrap_state and inject as
        manifest["external_dependencies"] before rendering.

  doc-gen/renderers/recovery_runbook.py
      Appendix G — External Dependencies added after Appendix F (Template Registry).
      For each dependency:
        h2 heading: "{name}  ({type})"
        Fields: ID, Endpoint, Status, Required by, Description, Failover, Notes
        TLS Certificate sub-section (h3) if cert declared:
          Expires at (with severity callout for ≤7d / ≤30d / ≤60d)
          Issuer, Subject, Auto-renew, Last checked, SANs
      Empty state message when no external_dependencies declared.

  tests/unit/test_external_dependencies.py
      71 tests (all pass):
        TestExternalDependencyRegistryBasic (8 tests)
        TestExternalDependencyRegistryCerts (9 tests)
        TestBuildExternalDependencyRegistry (4 tests)
        TestScoreExternalDependencyState (16 tests)
        TestRecoveryRunbookAppendixG (13 tests)
        TestExternalDependencyStateSchema (7 tests) — jsonschema installed
        TestBootstrapStateFixtureWithExternalDeps (8 tests)
        TestExternalDependencyConstants (5 tests)

---

## Completed: Milestone 7.2 — Service State Schema and Collection

  doc-gen/service_state_collector.py       collect_service_state(bootstrap_state, observed_vms)
  tests/fixtures/bootstrap/service-state.json  Updated fixture
  doc-gen/readiness.py                     _score_service_contract_completeness()
  doc-gen/engine.py                        _load_service_state() + injection in both paths
  proxmox-bootstrap/collect_tier2.py      collect_service_state() called after merge
  tests/unit/test_service_state_collector.py  49 tests

## Completed: Milestone 7.1 — Service Contract Implementation

  proxmox-bootstrap/service-contracts.yaml   Authoritative YAML for 4 known VMs
  doc-gen/service_contracts.py               ServiceContractRegistry + ServiceContractValidator
  doc-gen/dependencies.py                    Contract-driven edges (SERVICE, DEPENDS_ON)
  doc-gen/engine.py                          service_contracts injected in both paths
  proxmox-bootstrap/collect_tier2.py        check_service_contract_coverage()
  tests/unit/test_service_contracts.py       39 tests

## Completed: Milestone 6.8 — Bootstrap Documentation Update

  doc-gen/engine.py         run_bootstrap() loads dns_registry, base_images, templates
  doc-gen/renderers/workbook.py  Stage 03 VM IP from DNS registry; ISO path from template registry
  tests/unit/test_bootstrap_workbook.py  28 tests

---

## Architecture Decisions Added This Session

Three design decisions were recorded in ARCHITECTURE.md (AD-041, AD-042, AD-043)
and propagated to README.md (new sections) and ROADMAP.md (Phase 1.F + 12.E
sub-milestones). No code was written — these are design decisions only.

### AD-041 — Spawn package execution modes

**Execution mode is asked FIRST** — before any service selection — because the
answer determines whether service selection happens at all on the hatchery.

**Interactive:** Operator selects this → planner is done. No service selection on
the hatchery. Package includes all available service scripts. Service selection
happens entirely on the broodling at runtime, evaluated against actual hardware.

**Autonomous (default):** Operator selects this → planner continues to service
selection (full mirror / by group / individually). Selected services are locked
into the package. `spawn.sh` runs end-to-end on the broodling with no prompts
beyond the KeePass unlock gate.

`disposition.execution_mode: autonomous | interactive` recorded in spawn-plan.json.
`disposition.services` and `disposition.excluded` are populated for autonomous only.

### AD-048 — Split-horizon DNS and external DNS auto-update

The hatchery runs **dnsmasq** as a LAN DNS server, deployed in forge phase-03 before
any VMs exist. The operator provides their domain during phase-01 (plan); it is stored
in `bootstrap-state.json host_identity.domain` and `host_identity.fqdn`.

dnsmasq config generated from `dns-registry.yaml` by `generate-dnsmasq-config.py`:
- `address=/{fqdn}/{lan-ip}` for every entry in dns-registry.yaml
- Upstream forwarding to 8.8.8.8 / 1.1.1.1 for external names

Split-horizon behaviour:
- LAN clients (using hatchery as DNS): `hatchery.home.example.com` → LAN IP
- WAN clients (using public DNS):       `hatchery.home.example.com` → WAN IP
  (operator must create external A record or configure DDNS)

**Key consequence:** every spawn package uses a single Headscale URL (`https://hatchery.{domain}:8080`) that resolves correctly from both LAN and WAN. Same package, no modification.

External DNS auto-update (forge phase-03, optional) for dynamic WAN IPs:
- Tool: **dns-lexicon** (pip install dns-lexicon) — 90+ providers, Python, actively maintained
- Supported: Cloudflare, GoDaddy, Namecheap, Route53, Porkbun, Gandi, OVH, DigitalOcean, and 80+ more
- DuckDNS: simple HTTPS GET (no lexicon needed) — free subdomain option
- **Squarespace: NO DNS API exists** — operators must delegate DNS to Cloudflare (change nameservers in Squarespace dashboard); full walkthrough in docs/DNS-UPDATE-SETUP.md
- **inadyn: DO NOT USE** — archived October 2025
- systemd timer: broodforge-ddns.timer (every 5 min, OnBootSec=60)
- update-dns.py: fetches WAN IP (ifconfig.me, ipinfo.io fallback), compares to cache, calls lexicon or DuckDNS GET on change
- Config stored in `network_topology.ddns_provider/zone/record/credential_reference`

TLS certificate automation (1.F.8d):
- Cloudflare path: certbot + python3-certbot-dns-cloudflare → wildcard cert `*.{domain}`
  → certbot.timer auto-renewal → cert-manager ClusterIssuer with Cloudflare DNS-01 for k3s
- DuckDNS path: acme.sh with dns_duckdns → wildcard cert `*.{subdomain}.duckdns.org`
  → acme.sh cron auto-renewal → sync-cert-to-k8s.sh syncs cert into k8s TLS secrets per namespace
- Both: Headscale configured with TLS cert paths; stored in network_topology.ssl_*
- docs/CLOUDFLARE-SETUP.md: full guide (DNS delegation from Squarespace, API token, certbot, ClusterIssuer)
- docs/DUCKDNS-SETUP.md: full guide (DDNS client, acme.sh, k8s cert sync)
- docs/DNS-UPDATE-SETUP.md: gateway index + comparison table

Router requirements (operator-configured, forge cannot automate):
- Port forward: 8080 (Headscale) → hatchery LAN IP
- External DNS A record: `hatchery.{domain}` → WAN IP (or DDNS handles this)

### AD-047 — Headscale WAN connectivity

Headscale (self-hosted Tailscale coordination server) is auto-configured in forge
phase-03. The hatchery becomes its own tailnet coordinator:
- apt/binary install of headscale; systemd service; broodforge user/namespace created
- Hatchery registers with its own Headscale (`tailscale up --login-server https://hatchery:8080`)
- Headscale URL → `bootstrap-state.json network_topology.headscale_url`
- Headscale API key → KeePass `Infrastructure/headscale/api-key`

Spawn packages in WAN mode embed a one-time Headscale auth key (`headscale authkeys
generate --expiration 1h`; not stored in KeePass). The broodling's `phase-00a`
(first thing spawn.sh does) installs Tailscale and registers with the hatchery's
Headscale. After that, all SSH and cluster communication uses the WireGuard tunnel
transparently. Broodlings remain permanent tailnet members; tailnet IP recorded in
bootstrap-state.json alongside LAN IP.

Spawn planner now asks: **network mode first** (LAN / WAN / specify), then execution
mode (autonomous / interactive), then service selection (if autonomous).
LAN mode: direct SSH with temporary root password — Tailscale not used.
WAN mode: phase-00a runs Tailscale join, then temporary root password SSH proceeds
over the WireGuard tunnel exactly as in LAN mode.

**Hardware discovery — password-based SSH from hatchery (LAN or WAN via tailnet):**
The hatchery is a trusted node. Password-based SSH from hatchery to fresh broodling
is acceptable — no pre-exchanged keys needed. The spawn planner generates a suggested
temporary root password (readable passphrase format, e.g. `Ready.to.spawn.7`) at
autonomous-mode selection time. Operator uses this password during Proxmox installation.
Hatchery holds the password in session memory and SSHes to broodling automatically
once the operator signals installation is complete. If operator used a different password,
they enter it when prompted. Temporary password is valid from install completion until
Cloud-Init sets the real KeePass-managed credential during spawn execution. Not stored
in KeePass; not persisted after the spawn session. For interactive mode: no hatchery-side
discovery needed — spawn.sh discovers hardware on the broodling at runtime.

### AD-042 — KeePass security model

- No package (forge, spawn, phoenix) ever contains the KeePass database or any secret value
- Packages contain only KeePass paths (references)
- A KeePass unlock gate runs before the first secret is accessed in any package
- The operator enters the master password at this gate; scripts retrieve secrets programmatically
- In autonomous spawn mode, this is the only human prompt before fully automated execution
- k3s join tokens are included in spawn manifests but are rotated after the broodling joins

### AD-042 (corrected) — KeePass security model

The earlier version of AD-042 stated packages "never contain the KeePass database."
This was incorrect. The correct model:

- The KeePass database is **optionally** embedded in forge/spawn/phoenix packages
- The operator chooses at package-generation time: embed / path / prompt
- Embedded or not, the database **cannot auto-unlock** — master password required at the gate
- After the master password is entered once, the in-process secrets broker handles all
  lookups for the session without further operator input
- If not embedded, the installer prompts for a filesystem path (USB, local disk,
  or pre-agreed path) at run time
- No secret value is written to the node's filesystem in plain text

### AD-043 — Password generation policy

**Default format (user-facing):** Readable passphrase — `Capital.word.phrase.9`
  - Leading capital, lowercase words, period separators, trailing digit, 20-30 chars
  - Human-memorable, terminal-safe (no quoting needed), broadly compatible

**Fallback format:** Alphanumeric only (letters + digits, same length)
  - Used when a service rejects the default format (periods or other characters)
  - Triggered automatically: if a deployment phase fails with a credential-related error,
    broodforge detects the pattern, offers to regenerate alphanumeric, retries the phase
  - Service restriction recorded in service-catalog.yaml as `password_format: alphanumeric`
    for automatic application in future deployments

**Master password (forging):** Operator chooses from three options — accept a generated
passphrase, enter their own, or invoke KeePass's built-in generator

### AD-046 — Proxmox nag suppression

`lib/pve-suppress-nag.sh` patches Proxmox web UI JS to remove the non-enterprise
subscription popup. Applied in phase-03 (host config). A dpkg post-invoke hook at
`/etc/apt/apt.conf.d/85pve-nag-suppress` re-applies the patch on package upgrades.
Idempotent; no-op if already applied. Proxmox CE is fully functional without subscription.

### AD-044 — Backup infrastructure (corrected and expanded)

**Engine:** restic (encryption mandatory, dedup, versioned snapshots, retention, checkpoint tagging)
**Transport:** rclone as restic backend for providers restic doesn't natively support

**Three backup layers:**
1. **Secrets / KeePass DB** — always enabled once any destination configured; non-optional
2. **Configuration state** — cell-scoped (full cluster state, not per-node); post-assessment trigger
3. **Application data volumes** — opt-in per volume; not default

**Destination model — ordered chain of unlimited depth:**
- Each destination attempted in sequence; failures logged and exposed, never swallowed
- Each upload verified (restic integrity check) before marking success
- If all destinations fail for a layer: RED finding surfaced in assessment, never silent
- No limit on chain length; add as many destinations as needed for redundancy

**Per-backup unique secrets:**
- Each backup run generates a NEW restic repo password via `restic key add` + `key remove`
  (rewraps master key; no data re-encryption; fast)
- Stored in KeePass at: `Backup/{layer}/{component}/{YYYY-MM-DD_HH_MM_SS}/repo-password`
- `current` alias maintained at: `Backup/{layer}/{component}/current`
- Secrets broker looks up the exact timestamped key for each snapshot at restore time
- After `restic forget`: corresponding KeePass entries cleaned up automatically
- KeePass DB backup exempt — its auth method (master password / token / key file) is never rotated

**Encryption:**
- Mandatory for config-state and appdata layers (restic, per-backup unique password)
- KeePass DB layer: NO restic encryption — plain rclone copy of already-AES-256-encrypted `.kdbx`
- KeePass backup transport credentials stored in `forge-manifest.json` (not in KeePass)
- Operators never manually handle restic repo passwords — before or after initial setup

**Standard backup naming convention (enforced programmatically):**
- Component prefixes: `kdbx` | `cell-config` | `node-{hostname}` | `vm-{name}-{vmid}`
  | `ct-{name}-{ctid}` | `vol-{vm_name}-{vol_name}` | `svc-{service_name}`
- Timestamp: `YYYY-MM-DD_HH_MM_SS` (UTC, underscores — matches existing project convention)
- Hash: 8 hex chars — SHA-256 of file content (KeePass files) or first 8 of snapshot UUID
- Restic repo paths: `{root}/{cell_id}/{layer}/{component_prefix}/`
- KeePass DB files: `kdbx_{cell_id}_{timestamp}_{hash8}.kdbx`
- Snapshot set IDs: `{cell_id}_{timestamp}_{run_hash8}` — human-readable, links all pieces of a run
- Restic snapshot tags: `cell:{cell_id}`, `set:{snapshot_set_id}`, `component:{prefix}`,
  `layer:{layer}`, `run:{timestamp}` — queryable with `restic snapshots --tag component:vm-forgejo-101`
- KeePass key paths: `Backup/{layer}/{component_prefix}/{timestamp}/repo-password`
  + `Backup/{layer}/{component_prefix}/current` alias

**Space-aware component routing and chunked splitting:**
- Before each run: probe available space per destination via rclone `about` / `statvfs`
- Route each component to a destination with sufficient room (`primary`)
- If primary full: try next destination in chain (`space_fallback`)
- If no single destination fits a component: split at sub-component level across multiple
  destinations (`chunked_split`); each piece gets its own restic repo, own key, own KeePass path
- All pieces linked by `snapshot_set_id` UUID in `backup_history`
- Restore: secrets broker reads `backup_history` → resolves per-snapshot key → assembles automatically
- Truly unsplittable + no space: surfaces as human decision; other components continue

**Restore automation:**
- Master password entered once at KeePass gate
- Secrets broker resolves all restic repo passwords and service credentials automatically
- Only operator decisions: master password + snapshot selection
- All other restore steps (decrypt, verify integrity, re-inject service credentials) are automated

**Readiness scoring:** RED on no-destination, consecutive all-fail, or >3× schedule overdue;
ORANGE on partial failure or >2× overdue; YELLOW on >1× overdue or no checkpoint; GREEN = all healthy

**Ref:** ROADMAP.md Phase 6.B; docs/CLOUD-STORAGE-SETUP.md (provider setup guides, written)

### AD-045 — Timezone preference

Set once at forge time; stored in `bootstrap-state.json` as `vm_defaults.timezone`.
All documentation timestamps display `YYYY-MM-DD HH:MM:SS UTC (HH:MM:SS {TZ})`.
Updateable after forging via `engine.py --set-timezone "Continent/City"` without rebuild.

---

## Key new files added this session

  docs/CLOUD-STORAGE-SETUP.md   Step-by-step cloud provider API setup guides
                                 (Google Drive OAuth2 + Service Account, Backblaze B2,
                                 AWS S3, Cloudflare R2, self-hosted MinIO)
                                 Dated 2026-05-31; review by 2027-05-31

---

## Completed: Milestone 7.4 — Recovery Documentation Update (Service Layer)

### What was built

  doc-gen/renderers/recovery_runbook.py   Three new helper functions + two rendering additions:

  _get_contract(vm_name, manifest)
      Looks up a service contract from manifest["service_contracts"] by VM name.

  _health_check_cmds(iface, vm_ip)
      Generates executable health-check commands from a provided_interface entry.
      SSH → empty (already in standard validation). postgresql → pg_isready.
      smtp → nc port check. http/https with "GET /path" → curl -sf --max-time 10.
      Uses url_pattern if available; falls back to vm_ip + port. Generic port check
      if no health_check string but port is known.

  _service_restart_cmds(contract, vm_ip)
      Generates ssh ubuntu@{ip} 'sudo systemctl restart {svc}' + status command.
      Uses a descriptive placeholder when IP is unknown.

  Per-VM service contract block (inserted after provenance, before Restore notes):
      h3 "Service Contract: {service_name}"
      Provided interfaces with health check commands per interface
      Required interfaces (critical/optional) with "verify before starting" note
      startup_after note
      Service restart commands (systemctl via SSH)
      Secret references required by this service
      Checkboxes: required interfaces reachable, health check passed per interface,
                  service running and healthy

  Appendix A — edge type legend added before edge list:
      [SERVICE★]   — from declared required_interface in service-contracts.yaml
      [DEPENDS_ON] — startup ordering or structural dependency
      [STORAGE]    — storage pool dependency
      [NETWORK]    — network infrastructure dependency
      [BACKUP]     — backup relationship
      ★ = sourced from declared service contract
      SERVICE edges rendered as →[SERVICE★]→ to distinguish from heuristic edges.

  tests/unit/test_recovery_runbook_service.py — 44 tests (all passing):
      TestGetContract (5 tests)
      TestHealthCheckCmds (9 tests)
      TestServiceRestartCmds (5 tests)
      TestRunbookServiceContractBlock (13 tests)
      TestRunbookNoContractVM (2 tests)
      TestRunbookAppendixALegend (7 tests)
      TestRunbookHealthCheckUrls (2 tests) — url_pattern vs IP fallback

**Tests: 1272 total (1268 passed, 4 skipped)**

---

## Completed: Phase 6.B — Backup Infrastructure

### What was built

  data-model/bootstrap-state-schema.json
      Added: backup_config property + 8 new definitions:
      backup_config, backup_layer_secrets, backup_layer_restic,
      backup_destination_secrets, backup_destination_restic,
      backup_run_record, backup_component_record (+ external_dependency already existed)

  proxmox-bootstrap/backup_engine.py  — main library:
      BackupNaming       pure naming helpers (no I/O): repo paths, kdbx filenames,
                         snapshot_set_id, KeePass key paths, snapshot tags
      SpaceProbe         rclone about JSON parsing + os.statvfs for local paths
      ResticRunner       thin subprocess wrapper (injectable runner_fn for tests):
                         init, exists, backup, key_add/remove/list, stats, forget,
                         restore, check; password via env var only (not in args)
      RcloneRunner       thin subprocess wrapper: copyto, lsf
      generate_backup_passphrase()  Capital.word.word.N format, 20-30 chars
      BackupEngine       orchestrates per-layer runs:
                         run_secrets_backup() — rclone copy, no restic layer
                         run_restic_backup()  — per-backup key rotation (key_add +
                           key_remove), backup, stats verification, forget/prune,
                           KeePass key path storage via optional secrets_provider
      RestoreEngine      reads backup_history, resolves per-snapshot KeePass keys,
                         restores from recorded destination; dry-run support;
                         list_snapshot_sets(), find_record_for_set(),
                         restore_snapshot_set()

  proxmox-bootstrap/run-backup.py         CLI: --state, --layer, --kdbx, --source,
                                           --component, --dry-run, --verbose
                                           Updates backup_history in bootstrap-state.json
  proxmox-bootstrap/restore-from-backup.py  CLI: --state, --layer, --snapshot-set,
                                           --latest, --component, --target, --list, --dry-run
  proxmox-bootstrap/setup-backup.py      Interactive wizard (simple mode):
                                           destinations for secrets/config/appdata layers,
                                           retention policy, all_failed_policy

  doc-gen/readiness.py   _score_backup_config_completeness(manifest) — new scorer:
                          RED: no backup_config, no destinations, consec_fail>=2, >3× stale
                          ORANGE: consec_fail==1, >2× stale, never backed up
                          YELLOW: >1× stale, no permanent checkpoint
                          Wired into score_graph() alongside existing scorers
                          Tests that assert "no gaps" updated to include backup_config

  doc-gen/engine.py       Both run_bootstrap() and run_recovery() inject backup_config
                           from bootstrap-state into manifest

  doc-gen/renderers/recovery_runbook.py   Appendix H — Backup Configuration:
                           Per-layer status (destinations, last backup, all-fail warning),
                           recent history table, restore commands, KeePass backup note.
                           Empty state: prominent warning with setup command.

  tests/unit/test_backup_infrastructure.py   82 tests:
      TestBackupNaming (14), TestGenerateBackupPassphrase (6), TestSpaceProbe (4),
      TestResticRunner (11), TestRcloneRunner (5), TestBackupEngineSecrets (5),
      TestBackupEngineRestic (6), TestRestoreEngine (8),
      TestScoreBackupConfigCompleteness (10), TestRunbookAppendixH (8),
      TestBootstrapStateSchemaWithBackupConfig (2)

**Tests: 1354 total (1350 passed, 4 skipped)**

---

## Next Action: Phase 8 — Network Topology as Code

### What It Is

Milestone 7.4 extends the recovery runbook with service-layer awareness:
service contract validation steps, health check commands (from the `health_check`
field in provided_interfaces), service restart/verification commands, and a
distinct visual rendering of Service Contract dependency edges in the runbook.

### Specific Deliverables

**In `doc-gen/renderers/recovery_runbook.py`:**

1. **Per-VM section: Service Contract validation block** — for each VM node that
   has a declared service contract, add a "Service Contract" section within that
   VM's restore sequence entry:
   - List provided interfaces with their health_check commands
   - List required_interfaces dependencies (which services this VM needs)
   - startup_after ordering note

2. **Health check commands** — if a provided_interface has a health_check field
   (e.g. "GET /api/healthz"), emit a validation command:
   - HTTP health checks → `curl -f <health_check_url>`
   - SSH → `ssh ubuntu@<vm_ip>` (already covered)
   - postgresql → `pg_isready -h <vm_ip> -p 5432`

3. **Service restart commands** — for each service, emit restart guidance:
   - Systemd service (inferred from service name): `systemctl restart <service>`
   - Container: `docker restart <name>` or `podman restart <name>`
   - Fallback: `# restart command not determinable — check service-contracts.yaml`

4. **Service Contract dependency graph rendering** — in Appendix A (Dependency Graph),
   label edges with their edge type (SERVICE vs DEPENDS_ON vs STORAGE etc.) so the
   operator can see which edges came from declared contracts vs. heuristics.

### Files to Read Before Writing Code

  doc-gen/renderers/recovery_runbook.py  — full file (especially the per-VM restore section ~line 350–470)
  doc-gen/service_contracts.py           — ServiceContractRegistry methods
  proxmox-bootstrap/service-contracts.yaml — real contract data for reference
  tests/fixtures/bootstrap/bootstrap-state.json — service_contracts field structure
  doc-gen/dependencies.py               — edge types (SERVICE, DEPENDS_ON, etc.)

### Deliverables

  doc-gen/renderers/recovery_runbook.py  Modified with service layer steps
  tests/unit/test_recovery_runbook_service.py  New test file — contract validation steps,
                                                health check commands, dependency labels

### End-to-End Test

  python3 doc-gen/engine.py --mode recovery --manifest tests/fixtures/bootstrap/bootstrap-state.json
  → Recovery-Runbook.odt opens; forgejo section shows health check command
  → assessment-engine section shows startup_after: forgejo dependency note

---

## Key Files

  doc-gen/registries.py             SecretRegistry + DnsRegistry
  doc-gen/provenance.py             ProvenanceRegistry
  doc-gen/template_registry.py      TemplateRegistry
  doc-gen/external_dependencies.py  ExternalDependencyRegistry (new, Milestone 7.3)
  doc-gen/service_contracts.py      ServiceContractRegistry + Validator
  doc-gen/service_state_collector.py  collect_service_state()
  doc-gen/readiness.py              GREEN/YELLOW/ORANGE/RED/BLOCKED scorer
  doc-gen/engine.py                 run_bootstrap() + run_recovery()
  doc-gen/renderers/workbook.py     build_bootstrap_workbook()
  doc-gen/renderers/runbook.py      build_bootstrap_runbook()
  doc-gen/renderers/recovery_runbook.py  build_recovery_runbook() (Appendices A–G)
  proxmox-bootstrap/collect_tier2.py   Tier 2 SSH collector library
  tests/fixtures/bootstrap/bootstrap-state.json   canonical fixture

## Design Constraints

  - stdlib only in planners/generators/validators (no pip)
  - cell_id mandatory on all schema documents
  - Metadata files are never generated
  - Generated artifacts are never the source of truth
  - POPULATE: markers = documentation coverage gaps
  - Filenames: YYYY-MM-DD_HH_MM_SS (UTC, underscores)
  - Documents: YYYY-MM-DD HH:MM:SS UTC (HH:MM:SS MDT)
