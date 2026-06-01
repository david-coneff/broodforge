# FORGING.md — Operator Runbook

**Phase 1.F** | Last updated: 2026-06-01

Forging is the process of taking bare Proxmox hardware to a fully operational
broodforge hatchery using the forge package. This runbook covers the complete
forge workflow end-to-end.

---

## Prerequisites

### Hardware requirements

| Component | Minimum | Recommended |
|---|---|---|
| RAM | 16 GiB | 32 GiB |
| Disks (ZFS) | 2 × ≥32 GiB | 2-4 × ≥200 GiB SSD |
| NICs | 1 | 2 (management + VM traffic) |
| CPU cores | 2 | 4+ |

### Software requirements

- Proxmox VE installed on the target host (bare metal or nested virtualisation)
- Proxmox CE (community edition, no subscription) is fully supported
- Network access from your workstation to the target host (SSH on port 22)
- Python 3.11+ on your workstation (for generating the forge package)

### Network requirements

- Static IP assigned to the hatchery host (or DHCP reservation)
- Default gateway configured
- Internet access from the hatchery host (for apt, Let's Encrypt, Flux CD)

---

## Step 1 — Generate the forge manifest

On your **workstation**, generate the forge manifest using the interactive planner:

```bash
python3 proxmox-bootstrap/forge-planner.py
```

The planner will ask you to:
1. Choose a setup mode (autonomous recommended for first forge)
2. Set the hatchery hostname and domain
3. Choose a network profile (LAN only or WAN-capable with Headscale)
4. Confirm your timezone
5. Configure at least one backup destination

The planner writes `forge-manifest.json` in the current directory.

**Review the manifest:**
```bash
cat forge-manifest.json
```

---

## Step 2 — Assemble the forge package

On your **workstation**, generate the self-contained forge package:

```bash
bash forge-pack.sh --manifest forge-manifest.json
```

This produces:
```
dist/forge-package-{cell_id}-{timestamp}.tar.gz
```

To embed the KeePass database in the package (convenient for offline use):
```bash
bash forge-pack.sh --manifest forge-manifest.json --embed-kdbx /path/to/keepass.kdbx
```

**Security note:** The forge package never contains secret values — only KeePass paths
(references). If you embed the KeePass database, it requires the master password to
unlock. Without the database, the KeePass gate will prompt for the path at runtime.

---

## Step 3 — Copy the forge package to the target host

```bash
scp dist/forge-package-*.tar.gz root@<hatchery-ip>:/root/
```

---

## Step 4 — Execute the forge package

On the **target host** (SSH in or use the Proxmox console):

```bash
cd /root
tar xzf forge-package-*.tar.gz
bash forge.sh
```

### What forge.sh does

The forge orchestrator runs 9 phases in order. Completed phases are checkpointed —
if forge.sh fails or is interrupted, re-run it to resume from where it left off:

| Phase | Script | Action |
|---|---|---|
| 00 | `phase-00-discover.sh` | Hardware discovery (disks, NICs, RAM, CPU) |
| 01 | `phase-01-plan.sh` | Identity planning (hostname, domain, cell_id) |
| 02 | `phase-02-validate.sh` | Hardware validation — RED findings block forge |
| 03 | `phase-03-host.sh` | Host config: hostname, ZFS pool, dnsmasq, KeePass init |
| 04 | `phase-04-vms.sh` | VM provisioning (OpenTofu — minimum viable stack) |
| 05 | `phase-05-k3s.sh` | k3s cluster init (Ansible k3s-server role) |
| 06 | `phase-06-gitops.sh` | Flux CD bootstrap → Forgejo |
| 07 | `phase-07-intelligence.sh` | Assessment + documentation engine init |
| 08 | `phase-08-verify.sh` | Cluster health check + state commit |

### Resuming after failure

```bash
# Resume from a specific phase (e.g. phase 3 if phase-03 failed)
bash forge.sh --from 3

# Start completely fresh
bash forge.sh --reset
```

---

## Step 5 — Forge phase details

### Phase 00 — Discover

Scans the hardware using `lsblk`, `ip link`, and `/proc/meminfo`. Writes
`hardware-profile.json`. No changes are made to the system.

### Phase 01 — Plan

Re-reads `forge-manifest.json`. If the manifest was generated on a different machine,
this step adapts the plan to the actual discovered hardware.

### Phase 02 — Validate

Runs `forge_validator.py` against `hardware-profile.json`. RED findings block the
forge. Review the output and resolve issues before re-running.

Common RED findings:
- **RAM too low**: add RAM or use a machine with ≥16 GiB
- **Insufficient disks**: add a second disk for ZFS mirror
- **No NICs**: check that the NIC is detected by the kernel

### Phase 03 — Host configuration

This is the longest phase. It:
1. Sets the hostname and /etc/hosts
2. Suppresses the Proxmox CE subscription nag
3. Creates the ZFS pool (topology derived from disk count)
4. Installs and configures dnsmasq (split-horizon DNS)
5. Initialises the KeePass database (master password prompt)
6. If WAN profile: installs Headscale, issues TLS cert, configures DDNS

**KeePass gate:** Phase 03 prompts for the KeePass master password once.
All subsequent secret lookups during forging use this unlocked session —
you will not be prompted again.

**Master password selection:**
- forge.sh suggests a readable passphrase (e.g. `Forest.amber.glide.8`)
- Accept the suggestion, enter your own, or use KeePass's built-in generator
- This is the single most important secret — choose carefully and record it safely

### Phase 03 — WAN profile only

If you selected the WAN network profile:

- **Headscale** is installed and configured as the hatchery's own tailnet coordinator
- **TLS certificate** is issued via Let's Encrypt (Cloudflare or DuckDNS path)
- **DDNS** timer is configured to update the external A record every 5 minutes

**Before running phase 03 in WAN mode:**
1. Ensure your domain's A record or DDNS is set up (see `docs/DNS-UPDATE-SETUP.md`)
2. If using Cloudflare: have your API token ready (will be stored in KeePass)
3. If using DuckDNS: have your token ready
4. Configure port forwarding: 8080 → hatchery LAN IP (for Headscale)

### Phase 04 — VMs

Provisions the minimum viable stack VMs using OpenTofu. The VM IDs, IPs, and roles
are derived from `forge-manifest.json`. VM definitions are in `opentofu/`.

### Phase 05 — k3s

Runs the Ansible `k3s-server` role against the provisioned VMs. The k3s join token
is retrieved from KeePass automatically.

### Phase 06 — Flux CD bootstrap

Bootstraps Flux CD against the Forgejo git server. Flux will continuously reconcile
the GitOps repository to deploy application workloads.

**After forging:** push your application manifests to the Forgejo repository. Flux CD
will deploy them automatically without further manual intervention.

### Phase 07 — Intelligence layer

Initialises `bootstrap-state.json` from the forge manifest and generates the first
set of broodforge documentation (Bootstrap Workbook, Recovery Runbook, Readiness Report).

### Phase 08 — Verify and commit

- Verifies all k3s nodes are Ready
- Checks Flux CD reconciliation status
- Commits `bootstrap-state.json` and `forge-manifest.json` to the Forgejo repository

---

## Step 6 — Verify the hatchery is operational

After forge.sh completes:

```bash
# Check k3s cluster health
kubectl get nodes
kubectl get pods -A

# Check Flux CD
flux get kustomizations

# Check assessment engine
python3 doc-gen/engine.py --mode bootstrap --state proxmox-bootstrap/bootstrap-state.json

# Access Forgejo web UI
open https://forgejo.{your-domain}
```

Expected output from `kubectl get nodes`:
```
NAME         STATUS   ROLES                  AGE   VERSION
pve01-k3s    Ready    control-plane,master   5m    v1.28.x
```

---

## Troubleshooting

### Phase 02 fails with "hardware mismatch"

The hardware does not meet minimum requirements. Review `hardware-profile.json`
and the validator output. Common causes:
- Not enough disks: `lsblk` shows only 1 disk ≥32 GiB
- Too little RAM: `/proc/meminfo MemTotal` shows < 16 GiB
- No physical NICs: `ip link` shows only loopback and virtual interfaces

### Phase 03 fails with "ZFS pool create failed"

Common causes:
- Disk already has a ZFS pool from a previous attempt: `zpool import -a` then `zpool destroy rpool`
- Disk is in use by the OS (boot disk): ensure the ZFS member disks are not the Proxmox boot disk

### Phase 05 fails with "Ansible unreachable"

The k3s VMs are not yet accessible via SSH. Wait for Cloud-Init to complete (usually 1-3 minutes).
Check VM status in the Proxmox web UI. Re-run `bash forge.sh --from 5`.

### Phase 06 fails with "Flux bootstrap failed"

Common causes:
- Forgejo is not yet running: check VM health in phase 04
- Git repository not pre-created: forge.sh will attempt to create it automatically,
  but if Forgejo credentials aren't in KeePass yet, it may fail

### Headscale not accessible from WAN

1. Verify port forwarding: router → 8080 → hatchery LAN IP
2. Verify external DNS A record: `dig hatchery.{domain} @8.8.8.8`
3. Check Headscale service: `systemctl status headscale`
4. Check TLS cert: `openssl s_client -connect hatchery.{domain}:8080`

---

## Key files after forge

| File | Location | Purpose |
|---|---|---|
| `forge-manifest.json` | `/root/` | Cell identity snapshot |
| `hardware-profile.json` | `/root/` | Discovered hardware |
| `bootstrap-state.json` | `proxmox-bootstrap/` | Authoritative cell state |
| `dns-registry.yaml` | `proxmox-bootstrap/` | DNS records for all nodes |
| KeePass database | `/etc/broodforge/keepass.kdbx` | All service credentials |
| dnsmasq config | `/etc/dnsmasq.d/broodforge.conf` | Split-horizon DNS |
| Headscale config | `/etc/headscale/config.yaml` | Tailnet coordinator |
| TLS cert (WAN) | `/etc/broodforge/ssl/` | Let's Encrypt wildcard cert |

---

## Next steps after forging

1. **Push GitOps repository** to Forgejo — Flux CD will deploy application workloads
2. **Spawn broodlings** — run `python3 proxmox-bootstrap/spawn-planner.py` on the hatchery
   to generate spawn packages for additional nodes
3. **Run reconstruction drill** — validate the hatchery can be reconstructed from state
   (`docs/RECONSTRUCTION-DRILL.md`)
4. **Review the Bootstrap Workbook** — generated in `reports/` by the intelligence layer
5. **Set up monitoring** — deploy Prometheus agent via Flux GitOps

---

*Broodforge FORGING.md | Phase 1.F | Architecture v7.1*
