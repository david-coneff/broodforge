# 🔥 Broodforge Setup Guide

Gather this information and make these decisions before starting each process.
Fields in the Pre-flight sections are shared with the corresponding detail
sections — fill them in once, use them everywhere.

> **⚙ Follow-up items (not yet in md_to_html.py):** The original hand-authored
> SETUP-GUIDE.html included three per-package progress bars (Forge/Spawn/Phoenix
> PHS), localStorage-backed field persistence across page reloads, and a
> manifest import/export panel that pre-fills fields from `forge-manifest.json`.
> These features are logged as Phase 3.Q items for md_to_html.py extension.

---

## 📋 Pre-flight checklist — Forge

Have this ready before running `forge.sh`. Fill in the fields below — they are
referenced throughout the Forge setup sections.

### Host & network

@field[Proxmox host IP|e.g. 192.168.1.10]
@field[Planned hostname|e.g. pve01]
@field[Network profile (lan or wan)|lan  or  wan]
@field[Domain name (WAN only)|e.g. home.example.com]

### Storage & configuration

@field[Config mode|autonomous / ip-selective / group-manual / full-manual]
@field[ZFS pool name|e.g. rpool  (default)]

### Security decisions

@field[KeePass MFA method|none / totp / yubikey]
@field[Cloud backup provider|e.g. Backblaze B2, Cloudflare R2, local /mnt/backup]

> KeePass master password is never stored here. Decide how you'll generate it
> (broodforge suggestion, KeePass generator, or your own) before running
> phase-03.

### Hardware minimums to verify

@check[Hardware checklist|Proxmox VE installed from official ISO (not upgraded from Debian)|SSH access as `root` from your workstation|RAM ≥ 32 GB (16 GB absolute minimum for forge-only stack)|VT-x / AMD-V enabled in BIOS|≥ 2 disks available for ZFS mirror (or 1 disk accepted for single/stripe)|Cloud backup API key obtained (if using remote backup)]

---

## 📋 Pre-flight checklist — Spawn

Have this ready before running `spawn.sh`. Fill in the fields below — they are
referenced throughout the Spawn setup sections.

### Broodling identity

@field[Broodling hostname|e.g. pve02  [auto from hatchery]]
@field[Broodling LAN IP|e.g. 192.168.1.15  [auto-allocated]]
@field[Pre-flight scan result|PASS / FAIL — note any mismatches]

### Hatchery & broodling state

@check[Pre-spawn checklist|Hatchery PHS ≥ 80, all VMs running, Forgejo accessible|`bootstrap-state.json` is current (run Tier 2 assessment if in doubt)|Spawn package generated on hatchery|Proxmox VE installed on broodling (fresh install)|Broodling can reach hatchery (LAN ping or Headscale connectivity)]

> KeePass master password will be prompted once at the beginning of `spawn.sh`.
> Have it available.

---

## 📋 Pre-flight checklist — Phoenix

Have this ready before running `phoenix.sh`. Fill in the fields below — they
are referenced throughout the Phoenix setup sections.

### Target node & hardware

@field[Failed node hostname|e.g. pve01  [from phoenix package]]
@field[Replacement hardware notes|e.g. same model / 4 disks instead of 2]

### Recovery resources — confirm before starting

@check[Pre-phoenix checklist|**Failed node is fully powered off** — confirm before starting|PBS backup storage is accessible|KeePass database retrieved from backup|KeePass master password available|Phoenix package generated on a surviving node]

> Retrieve `bootstrap-state.json` from backup or Forgejo before generating
> the phoenix package. See the Backup Locations section for credential details.

---

## 🔨 Forge — bare hardware → first operational hatchery

The forge process turns a freshly installed Proxmox host into a fully
self-managing hatchery — the source from which broodlings are spawned and
through which the cluster is managed. Run once per cell.

### Before you begin

#### You will need

@check[Pre-forge checklist|Physical host with Proxmox VE installed from ISO|SSH access as `root` from your workstation|Forge package copied to the host (e.g. via `scp`)|Domain name ready (if using external DNS / WAN profile)|Cloud backup provider API key obtained (optional but recommended)]

@field[Proxmox host IP|e.g. 192.168.1.10]
@field[Domain name|e.g. home.example.com]
@field[Backup provider and endpoint|e.g. Backblaze B2 bucket URL]

#### Hardware minimums for the broodforge stack

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM | 16 GB | 32 GB |
| Storage | 1 disk (stripe, no redundancy) | 2+ disks (ZFS mirror) |
| CPU | 4 cores, VT-x / AMD-V enabled | 8+ cores |

> Run `./forge.sh phase-00` (discovery only) before the full forge to verify
> hardware is detected correctly and review the hardware profile before
> committing any changes.

### Configuration mode

`phase-01` (plan) asks which mode to use. All modes produce the same result —
a validated `forge-plan.json` — but differ in how much the operator controls.

**Autonomous (DEFAULT)** — Broodforge calculates every setting from hardware
discovery. No questions asked beyond the KeePass master password. Use this for
standard deployments.

**IP-Selective** — Fully autonomous except you choose IP addressing: management
CIDR, gateway, and per-VM IP assignments. Everything else (ZFS topology, VM
sizing, k3s config) is calculated automatically.

> All VM IPs are auto-assigned from your chosen CIDR unless you also override
> them individually.

**Group-Manual** — A group selector lets you toggle which setting categories to
configure manually. Unselected groups are auto-configured. Selected groups show
suggestions at each prompt.

```
[ ] Network    CIDR: 192.168.1.0/24  gateway: 192.168.1.1
[✓] Storage    ZFS mirror (2 disks)  pool: rpool
[ ] VM Sizing  3 VMs × 4 GB RAM (28 GB available)
[ ] Identity   hostname: pve01  domain: home.example.com
[ ] Security   KeePass at /opt/broodforge/cluster.kdbx
[ ] k3s        pod_cidr: 10.42.0.0/16
[ ] Backup     Cloudflare + local /mnt/backup
```

**Full Manual** — Walk through every setting. At each prompt the auto-suggestion
is shown; press Enter to accept or type a new value. If your choice conflicts
with a prior setting, broodforge warns you and offers a revised suggestion.

> Suggestions update as you make choices: changing the subnet revises all IP
> suggestions; changing the hostname revises the FQDN and Headscale URL.

@field[Config mode chosen|autonomous / ip-selective / group-manual / full-manual]

### Network topology

Discovered from the Proxmox host's existing network configuration. Changes here
affect Cloud-Init snippets for all VMs — regenerate after any change.

#### Network profile — choose first (required)

The network profile determines which services are deployed and which spawn modes
are available. Choose once; migration between profiles is supported later.

**LAN-only (Profile A)** — Simple flat network. Local DNS only (dnsmasq,
`.internal` suffix). No Headscale, no DDNS, no Let's Encrypt. Spawn packages
work only from the same LAN.

**WAN-capable (Profile B)** — Full stack: split-horizon DNS, Headscale VPN,
DDNS agent, and Let's Encrypt wildcard cert. Enables WAN spawn (broodlings on
remote networks).

> You can start with LAN-only and migrate to WAN-capable later using
> `setup-network.py --migrate-to wan`. Migration is autonomous or guided.

#### Profile A — LAN-only, what gets deployed

- dnsmasq for local name resolution (`pve01.internal`, `forgejo.internal`, etc.)
- Self-signed TLS certificate for Proxmox UI (optional)
- No Headscale, no DDNS agent, no Let's Encrypt
- Spawn packages work only from the same LAN

#### Profile B — WAN-capable, what gets deployed (in addition to A)

- Your domain (e.g. `home.example.com`) or DuckDNS subdomain
- dnsmasq in split-horizon mode — LAN clients resolve to LAN IPs, WAN clients
  to WAN IP via registrar
- Headscale on port 8080 — WAN broodlings join the hatchery's tailnet using a
  one-time auth key
- DDNS agent (`broodforge-ddns.timer`) — keeps your A record current if WAN IP
  is dynamic
- Let's Encrypt wildcard cert (`*.home.example.com`) via DNS-01 — Headscale +
  services use it
- **Router port forwarding required: 8080 (Headscale).** Your router, cannot be
  automated.

#### Migrating between profiles later

```bash
# Guided migration (step-by-step with explanations):
python3 proxmox-bootstrap/setup-network.py \
  --state proxmox-bootstrap/bootstrap-state.json \
  --migrate-to wan \
  --mode guided

# Autonomous migration (auto-suggestions, minimal prompts):
python3 proxmox-bootstrap/setup-network.py \
  --migrate-to wan \
  --mode autonomous
```

LAN → WAN migration steps (all autonomous except the router step):

1. Configure domain + DNS provider credentials in KeePass
2. Install and configure DDNS agent
3. Update dnsmasq for split-horizon DNS
4. Deploy Headscale
5. Issue Let's Encrypt certificate
6. **Manual:** forward port 8080 on your router to the hatchery's LAN IP
7. Update `bootstrap-state.json` + commit to Forgejo

> The router port forwarding step (6) cannot be automated — broodforge cannot
> configure your router. All other steps are autonomous.

WAN → LAN migration is also supported: DDNS disabled, Headscale optionally
stopped (or retained), dnsmasq simplified, state updated.

#### Management CIDR (auto)

The subnet all infrastructure VMs attach to. Auto-detected from the host's
management interface.

- **Auto-suggestion:** inferred from the host's `vmbr0` address (e.g. `192.168.1.0/24`)
- **Override when:** you have a specific subnet plan or the auto-detected value is wrong

> Changing this after VMs are deployed requires updating all Cloud-Init
> network-config snippets and re-running `generate-network-configs.py`.

#### Gateway (auto)

Default gateway for all VMs. Revised automatically when you change the
management CIDR (set to the first host in the new subnet).

#### Bridge name (auto)

The Proxmox bridge all VMs attach to. Defaults to `vmbr0`. Change only if you
use a non-standard bridge name.

#### Domain & DNS (manual)

Your domain name (e.g. `home.example.com`) — entered once during phase-01
(plan). All node FQDNs use this suffix. The hatchery's dnsmasq serves local
resolution; your registrar's DNS serves external resolution (WAN profile only).

> If you don't have a domain, choose the DuckDNS option in the Backup & DNS
> section and get a free `*.duckdns.org` subdomain.

#### Headscale URL (auto)

Auto-built from your FQDN: `https://hatchery.{domain}:8080`. Headscale is
deployed in phase-03 and this URL is embedded in all subsequent spawn packages.

@field[Network profile chosen|lan / wan]
@field[Management CIDR|e.g. 192.168.1.0/24  [auto-detected]]
@field[Headscale URL|e.g. https://hatchery.home.example.com:8080  [auto-built]]

### Storage

#### ZFS pool topology (auto)

Determined from disk count discovered in phase-00:

| Disk count | Topology |
|------------|----------|
| 1 disk | stripe (no redundancy — not recommended for production) |
| 2 disks | mirror (recommended for homelab) |
| 3 disks | raidz1 (1-disk redundancy) |
| 4–6 disks | raidz2 (2-disk redundancy) |
| 7+ disks | raidz3 |

> If you have SSDs and HDDs mixed, broodforge will suggest topology based on
> total count. Override in group-manual or full-manual mode if you want to use
> only the SSDs for the pool.

#### Pool name (auto)

Defaults to `rpool`. Override if your convention differs. The pool name is
embedded in all VM disk paths — changing it after deployment requires migrating
all VM disk references.

#### Datastore name (auto)

Defaults to `local-{pool_name}` (e.g. `local-rpool`). This is the Proxmox
datastore registered for VM disks.

@field[ZFS pool name|e.g. rpool  [default]]
@field[ZFS pool topology detected|e.g. mirror (2 disks)]

### VM sizing

The forge package deploys only the minimum viable broodforge stack: Forgejo
(Git hosting), an operations VM (Phase A toolchain), and the k3s server. User
applications are deployed via GitOps after the forge completes.

#### VMID block start (auto)

Defaults to 100 (or above any existing VMIDs). All forge VMs are allocated
consecutively from this start. Override if you have a VMID reservation scheme.

> VMIDs 0–99 are reserved by Proxmox. VMIDs 9000+ are reserved for templates.
> Stay in the 100–8999 range.

#### RAM per VM (auto)

Auto-calculated at ~25% of host RAM per VM, floor at 2 GB. Override per-VM in
group-manual or full-manual mode.

#### vCPUs per VM (auto)

Auto-calculated as `max(host_threads ÷ 4, 1)`. Override if you want more or
fewer cores per VM.

@field[VMID block start|e.g. 100  [default]]
@field[RAM per VM|e.g. 8 GB  [auto-calculated]]

### Identity & naming

#### Hostname (auto)

Detected from the Proxmox host. Changing it here updates the host's
`/etc/hostname` and `/etc/hosts` during phase-03. Must be lowercase
alphanumeric and hyphens only.

#### Domain (manual)

Your domain suffix (e.g. `home.example.com`). Entered once during phase-01.
All node FQDNs derive from this: `hatchery.home.example.com`,
`pve01.home.example.com`, etc.

#### cell_id (auto)

Stable unique identifier for this infrastructure cell. Defaults to
`{hostname}-cell`. Used in backup paths, spawn package names, phoenix package
names, and bootstrap-state.json.

#### Naming convention (auto)

VM naming follows `{role}-{index:02d}` (e.g. `k3s-server-01`). Stored in
`metadata/naming-convention.yaml`. Change only if your organisation has a
different convention — inconsistency after deployment requires rename operations.

@field[Hostname|e.g. pve01  [auto-detected]]
@field[Domain suffix|e.g. home.example.com  [manual]]
@field[cell_id|e.g. pve01-cell  [auto from hostname]]

### Security & secrets

#### KeePass master password (required)

Set once during phase-03 (host config). Options at the prompt:

1. **Generate** — broodforge suggests a readable passphrase
   (`Capital.word.phrase.9` format, 20–30 chars)
2. **KeePass generator** — use KeePass's own generator
3. **Enter** — type your own

> **DANGER:** Write the master password down and store it somewhere physically
> secure. It is never stored by broodforge. Losing it means losing access to
> all cluster secrets and all backup encryption keys. There is no recovery path.

The passphrase format (`Capital.word.phrase.9`) is human-memorable,
terminal-safe (no shell escaping), and satisfies most requirements.

#### KeePass database location (optional)

Defaults to `/opt/broodforge/cluster.kdbx`. Override if you have a preferred
path. The database is backed up separately to all configured backup destinations.

#### KeePass MFA method (optional)

If you added an extra factor to the KeePass database (TOTP or YubiKey
challenge-response), record the method and recovery info below so you can
regain access if the factor device is lost.

@radio[KeePass MFA method|None|TOTP (authenticator app)|YubiKey]
@field[TOTP seed (base32) — if TOTP method chosen|e.g. JBSWY3DPEHPK3PXP… (base32 secret from QR setup)]
@field[TOTP issuer / label|e.g. Broodforge KeePass]
@field[YubiKey serial — if YubiKey method chosen|e.g. 12345678]
@field[YubiKey slot used|e.g. Slot 2 (HMAC-SHA1 challenge-response)]
@field[YubiKey configuration notes|e.g. Programmed via YubiKey Manager, challenge-response mode]

> The TOTP seed is the one thing broodforge cannot recover for you. Without it,
> a lost phone means permanent loss of KeePass access. Print it or store it
> alongside your master password.

#### Service password format (auto)

All generated service passwords use the readable passphrase format by default.
If a service rejects periods or special characters, broodforge detects the
deployment failure and offers an alternative format for that specific service.

#### SSH keys (auto)

A deploy key pair is generated for each VM during phase-04 (VMs) and stored in
KeePass. You do not need to provide pre-existing SSH keys unless you have
specific requirements.

@field[KeePass database path|e.g. /opt/broodforge/cluster.kdbx  [default]]

### k3s configuration

#### Pod CIDR (auto)

Default: `10.42.0.0/16` (k3s default). If your management subnet overlaps
`10.42.x.x`, broodforge automatically shifts the pod CIDR to avoid conflict.

#### Service CIDR (auto)

Default: `10.43.0.0/16`. Revised to avoid overlap with pod CIDR and management
CIDR automatically.

#### CNI plugin (auto)

Defaults to `flannel` (k3s built-in). For advanced networking (Cilium, Calico),
override in full-manual mode — but this requires additional configuration beyond
what broodforge currently automates.

#### Initial cluster role (auto)

The forge always creates a single-node cluster (one server node). HA promotion
(3-server etcd quorum) happens automatically when the 3rd broodling with a
`k3s-server` disposition joins and all three servers are healthy.

### Backup & DNS

#### DNS provider & DDNS (required for WAN spawn)

Choose how external DNS is managed for your domain:

- **Cloudflare (recommended)** — change your domain's nameservers to Cloudflare;
  broodforge uses the Cloudflare API for DDNS and Let's Encrypt DNS-01 challenges.
  See `CLOUDFLARE-SETUP.md`.
- **DuckDNS** — free `*.duckdns.org` subdomain; no own domain required. See
  `DUCKDNS-SETUP.md`.
- **Static WAN IP** — skip DDNS; create the A record at your registrar manually.

> Squarespace domains have no DNS API — delegate nameservers to Cloudflare
> first, then use the Cloudflare option.

#### TLS certificates (Let's Encrypt) — auto

Issued during phase-03 using DNS-01 challenges (no port 80 required):

- **Cloudflare path:** `certbot` + `python3-certbot-dns-cloudflare` → wildcard
  cert `*.{domain}`
- **DuckDNS path:** `acme.sh` with built-in `dns_duckdns` → wildcard cert
  `*.{subdomain}.duckdns.org`

Headscale is automatically configured to use the issued cert. k3s services use
cert-manager (Cloudflare path) or cert sync (DuckDNS path).

#### Backup destinations (optional)

Configure backup destinations to protect your secrets and state. Backup is
optional — the forge completes without it — but strongly recommended before
production use.

- **Local path** — `/mnt/backup-drive` (no credentials)
- **USB drive** — `/media/usb` (must be mounted at runtime)
- **Backblaze B2** — Application Key (see `CLOUD-STORAGE-SETUP.md`)
- **AWS S3 / Cloudflare R2** — Access Key + Secret
- **Google Drive** — OAuth2 via rclone (most complex setup)

Backup layers: **Secrets** (KeePass — rclone copy), **Config state** (restic,
encrypted), **App data** (opt-in, restic). Each backup run generates a new
unique restic repo password stored in KeePass. You never manually handle backup
encryption keys after initial setup.

@field[DNS provider|Cloudflare / DuckDNS / Static WAN IP]
@field[Backup destination(s)|e.g. Backblaze B2 + local /mnt/backup]

### Execution phases

Run `bash forge.sh`. The forge is resumable — if a phase fails, fix the issue
and re-run; completed phases are skipped via checkpoint files.

@check[Forge execution phases|**phase-00 discover** — Hardware, disk, NIC, CPU/RAM inventory; generates hardware profile|**phase-01 plan** — Generate `forge-plan.json` (interactive based on config mode)|**phase-02 validate** — RED findings must be resolved before proceeding; YELLOW are advisory|**phase-03 host** — Hostname, ZFS pool, KeePass database, Headscale, TLS certs, dnsmasq|**phase-04 vms** — Forgejo + operations VM created; Ansible provisioned; SSH keys generated|**phase-05 k3s** — k3s single-node cluster initialised; kubeconfig written to `/root/.kube/config`|**phase-06 gitops** — Flux CD bootstrapped; Forgejo seeded with broodforge manifests|**phase-07 intelligence** — Documentation engine + Assessment Engine initialised; initial PHS computed|**phase-08 verify** — Full health check; generates post-forge snapshot in `bootstrap-state.json`]

@field[phase-00 — Notes / deviations|e.g. disk count, NIC names detected]
@field[phase-01 — Config mode chosen|autonomous / ip-selective / group-manual / full-manual]
@field[phase-01 — Network profile|lan / wan]
@field[phase-02 — Issues found / fixed|e.g. expected 2 disks, found 1 — accepted stripe]
@field[phase-03 — Hostname set|e.g. pve01]
@field[phase-03 — ZFS pool name|e.g. rpool]
@field[phase-03 — KeePass path|e.g. /opt/broodforge/cluster.kdbx]
@field[phase-03 — Root password (record in KeePass, not here)|Record in KeePass]
@field[phase-04 — Forgejo VMID / IP|e.g. 101 / 192.168.1.11]
@field[phase-05 — k3s server VM IP|e.g. 192.168.1.12]
@field[phase-07 — Initial PHS|e.g. 82 (GREEN)]
@field[phase-08 — Final PHS|e.g. 88 (GREEN)]

> After phase-08 the hatchery is operational. Add user applications via GitOps.
> Spawn broodlings when you're ready to expand.

---

## 🥚 Spawn — hatchery process → broodling joins the cluster

The spawn package is created on the hatchery and run on a fresh broodling after
bare Proxmox installation. The broodling joins without VMID, IP, or hostname
conflicts — all identity is allocated from the hatchery's DNS registry before
the package is generated.

### Before you begin

#### On the hatchery (before touching the broodling)

- Hatchery is healthy: PHS ≥ 80, all VMs running, Forgejo accessible
- `bootstrap-state.json` is current (run a Tier 2 assessment if in doubt)
- You know whether the broodling is on the same LAN or on a remote network

#### On the broodling (before running the spawn package)

- Proxmox VE installed from ISO (fresh install, nothing else configured)
- Root password set during install — you will use this for SSH during hardware
  discovery
- Network cable connected (LAN) or internet accessible (WAN/Headscale mode)

> **DANGER:** Do not join the broodling to any existing Proxmox cluster before
> running the spawn package. The spawn package does the cluster join in the
> correct order with the correct identity.

### Step 0 — Network mode (LAN or WAN)

Asked first — determines how the hatchery reaches the broodling for hardware
discovery.

**Same LAN (auto-detected)** — The hatchery attempts a direct connection to the
broodling's IP. If reachable within 5 seconds, LAN mode is selected
automatically. Hardware discovery SSHes directly using the temporary root
password.

> The spawn planner generates a suggested temporary root password (e.g.
> `Ready.spawn.here.7`) at this step — use it during Proxmox install.

**WAN / different network** — The spawn planner calls
`headscale authkeys generate --expiration 1h` and embeds the key + hatchery
Headscale URL into the package. `phase-00a` on the broodling installs Tailscale
and registers using this key before hardware discovery begins.

| Setting | Value |
|---------|-------|
| Headscale URL | Auto-populated from `network_topology.headscale_url` in `bootstrap-state.json` |

> The auth key is single-use and expires in 1 hour. If the broodling doesn't
> run `phase-00a` in time, regenerate the package.

@radio[Network mode|LAN (same subnet)|WAN (Headscale / different network)]

### Step 1 — Execution mode

**Autonomous (DEFAULT)** — Service selection is locked into the package at
generation time. `spawn.sh` runs without prompting after the KeePass unlock
gate. The only human interaction is entering the KeePass master password.

**Interactive** — No service selection at package-generation time. The package
carries scripts for all disposition-approved services. `spawn.sh` evaluates the
broodling's actual hardware and presents a service selector at runtime.

@radio[Execution mode|Autonomous (default)|Interactive]

### Configuration mode

Same four modes as forge (autonomous, IP-selective, group-manual, full-manual).
In autonomous mode, all settings are derived from the hardware profile and the
hatchery's existing allocation records.

> For most broodling additions, autonomous mode is correct. Use IP-selective if
> you've reserved specific IPs for this node in your DHCP/DNS setup.

### Step 2 — Disposition & service selection (autonomous only)

Which services should this broodling run? The planner reads the service catalog
and the broodling's hardware profile to show what fits.

**Full mirror** — Deploy all services the hatchery currently runs that fit the
broodling's hardware. Services that don't fit (insufficient RAM, no suitable
disk) are listed with their constraint.

**Select by group** — Toggle entire service groups (Infrastructure, Platform,
Intelligence, Monitoring, Applications) on/off, then fine-tune individual
services within groups.

**Select individually** — Every service is listed with its hardware fit status.
Broodforge enforces dependencies: selecting Nextcloud automatically selects
Longhorn if not already selected.

```
[✓] k3s-server        4 GB RAM req  /  14 GB avail — adds HA control plane
[✓] pbs-datastore     4 disks req  /  4 detected — raidz1
[!] prometheus        2 GB RAM req  /  marginal (fits with reduced sizing)
[✗] loki              4 GB RAM req  /  insufficient (2 GB would remain)
```

The intelligence baseline is always included and cannot be deselected: Proxmox
cluster membership, k3s worker, assessment/doc engine visibility,
`bootstrap-state.json` sync.

@radio[Disposition / service selection|Full mirror|Select by group|Select individually]

### Network topology (broodling-specific)

Each broodling gets its own non-conflicting IP allocation from the hatchery's
DNS registry. The spawn manifest contains all reserved IPs so no collision can
occur even in parallel spawns.

**Impact of hatchery network profile on spawn:**

| Hatchery profile | Spawn modes available |
|------------------|-----------------------|
| LAN-only (A) | LAN spawn only. No Headscale. Broodling must be on same subnet. |
| WAN-capable (B) | Both LAN and WAN spawn. WAN broodlings join via Headscale one-time auth key. |

> To enable WAN spawn on a hatchery running LAN profile: run
> `setup-network.py --migrate-to wan` on the hatchery first, then regenerate
> the spawn package.

#### IP assignment (auto)

IPs are allocated from the management CIDR, skipping all addresses already in
the DNS registry and provenance records. Override in IP-selective mode.

#### Bridge topology (auto)

Bridge names must match what the hatchery expects. The spawn package adapts
*which NICs* are enslaved to each bridge based on the broodling's hardware
discovery output.

### Storage (broodling-specific)

#### ZFS pool topology (auto)

Recalculated from the broodling's actual disk count. A node with 2 SSDs gets a
mirror; a node with 4 HDDs gets raidz1. The pool *name* is the same as the
hatchery's pool name (default: `rpool`) — consistency is required for shared
PBS backup paths.

> Hardware heterogeneity is intentional and expected. The spawn package adapts
> the storage layer to what's actually there.

### VM sizing (disposition-scoped)

Only VMs for the selected disposition are provisioned. VMID block is allocated
from the hatchery's assessment engine — no conflicts with existing VMIDs.

#### VMID block (auto)

The assessment engine reads all existing VMIDs from the hatchery's Proxmox API
and DNS registry, then allocates the next available consecutive block for this
broodling. Override in group-manual or full-manual mode if you have a
reservation scheme.

### Identity

#### Hostname (auto)

Generated from the naming convention in `metadata/naming-convention.yaml`. For
example, the second Proxmox node might be `pve02`. Override in group-manual or
full-manual mode.

#### FQDN (auto)

Built from hostname + hatchery domain: `pve02.home.example.com`. Added to
hatchery's dnsmasq and DNS registry after spawn completes.

### Execution phases (on the broodling)

Copy the spawn package to the broodling, then run `bash spawn.sh`. The spawn
is resumable via checkpoint files.

@field[Broodling hostname|e.g. pve02  [auto-allocated]]
@field[Broodling LAN IP|e.g. 192.168.1.15  [auto-allocated]]

@check[Spawn execution phases|**phase-00a [WAN only]** — Install Tailscale, join Headscale using embedded auth key|**phase-00 [A] pre-flight** — Remote hardware discovery from hatchery; profile comparison; PASS/FAIL report|**phase-00 [B] host config** — Hostname set, bridges configured, ZFS pool created|**phase-01** — Joins Proxmox cluster; identity confirmed by hatchery|**phase-02** — OpenTofu apply for disposition-selected VMs|**phase-03** — Cloud-Init snippets generated and uploaded|**phase-04** — k3s join (worker or server, based on disposition)|**phase-05 [conditional]** — SQLite sync for HA etcd promotion (if this is the 3rd server node)|**phase-06 verify** — Cluster health check; broodling scored by Assessment Engine|**Backup reachability** — Verify all backup destinations accessible from broodling]

@field[phase-00 — Pre-flight result|PASS / FAIL — note any mismatches]
@field[phase-06 — Final verification|e.g. 2/2 nodes Ready, Flux reconciling]

> After phase-06: Flux schedules workloads; Assessment Engine detects and scores
> the broodling against its declared disposition.

---

## 🦅 Phoenix — stargate process → failed node resurrected

The phoenix package preserves a failed node's identity exactly — same VMIDs,
IPs, hostnames, k3s node name, certificates — and reconstitutes it on new or
repaired hardware. Run once per node recovery event.

### Before you begin

#### Obtain the phoenix package

- Retrieve `bootstrap-state.json` from external backup (see recovery runbook
  Step 0)
- Run `python3 proxmox-bootstrap/phoenix_playbook.py --state bootstrap-state.json`
  on the hatchery (or another surviving node) to generate the phoenix package
- Copy the package to the replacement hardware

#### Confirm before starting

- PBS backup storage is accessible — you will need it for VM restoration in
  Wave 3
- Replacement hardware meets or exceeds the original node's minimum requirements
- KeePass database is available (from external backup or another node)
- You have the KeePass master password
- All backup destinations listed in the Backup Locations section are reachable

> **DANGER:** The phoenix package restores the original node's VMIDs and IPs.
> If the failed node is still partially running, shut it down completely before
> proceeding. Running two nodes with the same identity will corrupt cluster state.

### Hardware assessment (phase-00 pre-flight)

The first thing `phoenix.sh` does is scan the replacement hardware and compare
it against the embedded hardware profile. This is read-only — nothing is changed
until the operator confirms the pre-flight report.

#### What is checked

- Disk IDs in the plan are present and have the expected capacity
- NIC names/MACs match the embedded profile (NICs can renumber after kernel
  updates)
- Available RAM ≥ sum of all VM RAM in the plan + 10% host overhead
- No existing ZFS pool with a conflicting name
- No existing bridge with a conflicting name

#### When the pre-flight fails

A failure package is generated describing the mismatch. The host is left
unchanged. Common causes:

- **Wrong disk IDs** — replacement hardware has different disk layout. Update
  the hardware profile and regenerate the phoenix package.
- **NIC renumbering** — run `ip link` to see current NIC names and compare to
  the profile.
- **Insufficient RAM** — consider partial restoration scope (restore baseline
  first, add remaining VMs after upgrade).

#### Hardware adaptation (what adjusts automatically)

- **ZFS topology** — different disk count on replacement hardware → topology
  recalculated (e.g. 3 disks → raidz1 instead of original mirror)
- **Bridge configuration** — different NIC layout → bridge definitions adapt to
  actual NICs
- **Physical disk IDs** — new hardware, new disk serial numbers in the
  `zpool create` command

What does *not* adapt: pool name, bridge names, VMIDs, IPs, hostnames, k3s
node name — these are the preserved identity.

### Identity preservation

The phoenix package carries the node's complete logical identity. These values
are fixed — they cannot be overridden without breaking cluster membership.

| Preserved element | Why it must not change |
|-------------------|----------------------|
| Hostname | Changing it breaks k3s node membership (node certificates are tied to hostname) |
| IP addresses | All VM IPs and host management IP restored exactly. DNS entries already exist. |
| VMIDs | Other nodes' Proxmox configs reference VMIDs. Changing breaks live-migration, HA. |
| k3s node name | Same as hostname. Cluster certificates are tied to this name. |
| ZFS pool name | VM disk paths reference this name — changing requires migrating all disk references. |
| Bridge names | VM network assignments reference bridge names. Changing breaks network connectivity. |

### Restoration scope

**Full restoration (DEFAULT)** — Restore all services that were running. This
is the expected case for a phoenix — you want the node back exactly as it was.

**Partial restoration** — Choose which services to restore now and defer others.
Useful when the replacement hardware is temporarily smaller than the original,
or when you want to verify baseline functionality before restoring higher-RAM
services. Deferred services are recorded as `restoration_status: deferred` in
`bootstrap-state.json` so the Assessment Engine does not generate false RED
findings.

@radio[Restoration scope|Full restoration (default)|Partial restoration]

### Wave 0 — Network reconstruction

Bridges must exist before VMs can be created. Wave 0 verifies and, if
necessary, reconstructs the bridge configuration from
`network_topology_declared` in the phoenix package.

**If bridges are present and correct** — Wave 0 verifies with
`ip link show {bridge_name}` and `ip addr show {bridge_name}`. Checks: bridge
UP, correct IP assigned, gateway reachable. If all pass, Wave 0 succeeds in
under 10 seconds.

**If bridges are missing** — The recovery runbook provides the `ifreload -a`
command and references the declared network topology. Ensure
`/etc/network/interfaces` matches the template in the phoenix package before
retrying.

### Wave 1 — Storage reconstruction

**Import existing pool (preferred)** — If the original disks survived (e.g.
hardware failure was a controller or CPU, not disks), attempt pool import:
`zpool import {pool_name}`. If successful, all VM disk images are intact and
Wave 3 skips PBS restore for those VMs.

**Recreate pool on replacement disks** — If disks are lost, recreate with the
adapted topology. The pool name is preserved; disk IDs come from the hardware
pre-flight scan.

```bash
# Example: 3-disk raidz1 on replacement hardware
zpool create rpool raidz1 /dev/sda /dev/sdb /dev/sdc
```

> **DANGER:** This destroys any data on the listed disks. Confirm disk IDs
> match the target disks before running.

### Wave 3 — VM restoration

Each VM is either RESTORED from PBS backup or RECREATED from IaC, depending on
whether it is stateless.

**RESTORE — from PBS backup (stateful VMs)** — VMs with persistent data
(Forgejo, databases, application VMs) are restored via `qmrestore`. The
recovery runbook pre-populates the PBS backup path and VMID.

```bash
qmrestore /path/to/backup/{vmid}-latest.vma.zst {vmid} --storage local-rpool
qm start {vmid}
```

**RECREATE — from IaC + Ansible (stateless VMs)** — VMs with no persistent
data (infra-bootstrap, assessment-engine) are recreated by running OpenTofu +
Ansible. The playbook includes the exact OpenTofu workspace and Ansible
inventory used at original deployment.

```bash
tofu -chdir=opentofu/ apply -target=proxmox_vm_qemu.{vm_name} -auto-approve
ansible-playbook -i inventory/ site.yml --limit {vm_name}
```

**KeePass & secrets during restore** — Enter the KeePass master password once
at the beginning of `phoenix.sh`. The secrets broker retrieves all restic
backup repo passwords, service credentials, and SSH keys from KeePass
automatically — no manual credential entry after unlock.

### Wave 4 — k3s cluster membership

The node's k3s certificates are tied to its hostname and IP — both preserved.
The node should rejoin the cluster automatically when the k3s service starts on
the restored k3s server VM.

**If the node rejoins automatically** — Verify with `kubectl get nodes`. The
restored node should appear as Ready within ~30 seconds of the k3s server VM
starting.

**If the node does not appear** — Check the k3s server log on the restored VM:

```bash
ssh ubuntu@{vm_ip} 'sudo journalctl -u k3s -n 50'
```

Common causes: certificate mismatch (hostname changed), IP conflict (another
device took the IP), k3s token mismatch.

### Execution phases

Run `bash phoenix.sh`. Resumable via checkpoint files.

@field[Failed node hostname|e.g. pve01  [from phoenix package]]
@field[Replacement hardware notes|e.g. same model / 4 disks instead of 2]

@check[Phoenix execution phases|**Wave 0 — Network**: Verify bridges; reconstruct `/etc/network/interfaces` if missing|**Wave 0.5 — Templates**: Rebuild VM templates from stored base images|**Wave 1 — Storage**: Import or recreate ZFS pool|**Wave 2 — Host config**: Set hostname, packages, and Proxmox system config|**Wave 3 — VMs**: RESTORE (qmrestore from PBS) or RECREATE (OpenTofu + Ansible) each VM|**Wave 4 — k3s**: Verify k3s node rejoins cluster and reaches Ready state]

@field[Wave 0 — Bridge status|e.g. vmbr0 UP, vmbr1 UP — or rebuilt from template]
@field[Wave 1 — Pool status|e.g. imported existing / recreated raidz1 on 3 disks]
@field[Wave 3 — VMs restored|e.g. forgejo 101 ✓, ops-vm 102 ✓, k3s-server 103 ✓]
@field[Wave 4 — k3s status|e.g. 2/2 nodes Ready, Flux reconciling]

### Post-recovery validation

After all waves complete:

- `zpool status` — all pools ONLINE, no errors
- `ip link show type bridge` — all bridges UP
- `qm list` — all VMs running (status running)
- `kubectl get nodes` — all nodes Ready
- `flux get kustomizations` — all Applied=True, Ready=True
- Proxmox web UI accessible at `https://{hostname}:8006`
- SSH to each restored VM: login succeeds

#### After validation

- Run a Tier 2 assessment to generate a fresh post-recovery snapshot
- Update `bootstrap-state.json` with the phoenix completion record
- Commit the updated `bootstrap-state.json` to Forgejo
- Run a reconstruction drill entry:
  `python3 proxmox-bootstrap/reconstruction-drill.py --record-manual --outcome success`
- Verify all backup destinations are reachable and run a post-recovery test
  backup to confirm integrity
- The Assessment Engine detects the Forgejo commit and regenerates documentation
  automatically

> Review the provenance records for all restored VMs — compare the deployed
> commit hashes to the current Forgejo repository state to confirm recovery
> fidelity before closing the incident.

---

## 🗄 Backup locations & credentials (optional)

> **Skipping backup configuration is allowed but discouraged.** Operating
> without backups puts your data at risk — a disk failure or failed phoenix
> recovery without accessible backups can mean permanent data loss. Minimum
> viable backup: the KeePass `.kdbx` file and at least one offsite copy of
> `bootstrap-state.json`. Phoenix recovery without these two items may be
> impossible.

Record every backup target — what it covers, where it lands, and what
credentials are needed. This is your quick-reference during Phoenix recovery.

@table[Backup destinations|What it backs up|Location / path / URL|Credential / auth method|Notes]

> The backup table above is a reference record — it is not automatically synced
> with your configured backup destinations. Update it when you add, change, or
> remove a backup destination.
