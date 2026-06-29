# Broodforge

**Self-Documenting, Self-Assessing, Self-Recovering Infrastructure Platform**

Broodforge is a framework for operating a Proxmox-based homelab that continuously
understands its own state, evaluates its own health, can reconstruct itself from
complete failure, and can spawn additional nodes — entirely from repository state.

Three packages, three processes:

| Process | Package | What it does |
|---|---|---|
| **Forging** | **Forge package** | Bare hardware → first operational hatchery |
| **Hatchery process** | **Spawn package** | Hatchery → new broodling joins without conflict |
| **Stargate process** | **Phoenix package** | Failed node → identity resurrected on new hardware |

**Forging** is how the first node is built — raw hardware shaped into a
self-describing, self-managing hatchery. The **hatchery** is what it becomes:
the source from which **broodlings** are spawned. The **stargate process** is
how any node — hatchery or broodling — rises from catastrophic failure with its
identity intact.

---

## Configuration Modes — Automation vs. Manual Control

Every deployment package (forge, spawn, phoenix) supports four configuration modes.
The mode can be selected at package-creation time on the hatchery, or at execution
time on the target node.

```
How should this package be configured?

  1. Autonomous (default) — broodforge calculates all settings from discovery data
  2. IP-Selective         — autonomous except you choose IP addressing
  3. Group-Manual         — pick which setting groups to configure manually
  4. Full Manual          — walk through all settings with auto-suggestions

> _
```

**Autonomous** (default) is the fastest path — broodforge picks everything from
hardware discovery and declared metadata. Use this for standard deployments where
you trust the automatic choices.

**IP-Selective** is for operators who have a specific IP plan (a fixed CIDR range,
reserved addresses, a naming convention for machine IPs). Everything else —
ZFS topology, VM sizing, k3s config — is automatic. Only network addressing
requires input.

**Group-Manual** offers a group selector. You choose which settings *categories*
to configure manually; the rest are automatic. Groups: Network, Storage, VM Sizing,
Identity, Security, k3s, Backup.

```
Which setting groups do you want to configure manually?
(press SPACE to toggle, ENTER to confirm)

  [ ] Network    CIDR: 192.168.1.0/24 suggested  gateway: 192.168.1.1
  [✓] Storage    ZFS mirror (2 disks detected)    pool: rpool suggested
  [ ] VM Sizing  3 VMs × 4GB RAM (28GB available)
  [ ] Identity   hostname: pve01  domain: home.example.com
  [ ] Security   KeePass at /opt/broodforge/cluster.kdbx
  [ ] k3s        pod_cidr: 10.42.0.0/16  single-node initially
  [ ] Backup     Cloudflare + local /mnt/backup

> _
```

**Full Manual** walks through every setting. At each step the auto-suggestion is
shown prominently. You may accept it (press Enter) or enter your own value.

**Suggestion revision:** when you override a setting, all downstream suggestions
are revised to remain logically consistent. Choose `192.168.50.0/24` as your CIDR
and all subsequent VM IP suggestions come from that range. Choose a custom hostname
and the FQDN suggestion updates to match.

**Conflict detection:** if your choice conflicts with a prior selection (duplicate
VMID, overlapping subnet, RAM exceeding host capacity), a warning is shown with
the specific conflict. You may still proceed — broodforge will not block you.

---

## The Problem

Running a homelab with real services (Git, photos, documents, monitoring) creates
a quiet fragility: the more the environment matures, the harder it becomes to
recreate from scratch. Configuration drift accumulates. Manual steps are forgotten.
Recovery runbooks go stale. After a catastrophic failure, "just rebuild it" becomes
a multi-day archaeology project.

Broodforge answers five questions that homelab operators typically cannot:

1. **How do I get from bare hardware to a fully self-managing cluster?** (Forging)
2. **What is this system, exactly — and is it what was intended?** (Documentation + Assessment)
3. **Could I fully reconstruct this from scratch today?** (Recovery Readiness)
4. **If I spawn a broodling into this datacenter, what does it need to look like?** (Node Spawning)
5. **When something goes wrong, what failed and why?** (Failure Analysis)

---

## Core Philosophy

**The platform's primary product is not virtual machines.**

Broodforge exists to produce:

- **Reproducibility** — any component can be rebuilt from repository state alone
- **Recoverability** — any failure mode has a documented, tested, executable recovery path
- **Observability** — the platform continuously knows its own state against its own intent
- **Forgeability** — forging the first node produces a forge package the operator
  runs on bare hardware to stand up a complete self-managing hatchery from scratch
- **Spawnability** — spawning a broodling produces a hardware-aware spawn package
  the broodling runs after bare Proxmox install, not a checklist of manual steps

Applications (Nextcloud, Immich, monitoring) run on the platform and benefit from
its capabilities. They are not the reason the platform exists.

This distinction has concrete architectural consequences: the documentation engine
and assessment engine deploy before any user workload. A workload that cannot be
documented or assessed is not fit for deployment on this platform.

---

## Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Hypervisor | Proxmox VE | VM hosting, storage, networking, snapshots |
| IaC | OpenTofu | Proxmox infrastructure declaration |
| Configuration | Ansible | VM and service configuration |
| Provisioning | Cloud-Init | VM first-boot identity and networking |
| Git hosting | Forgejo (VM, pre-k3s) | All repositories — primary source of truth |
| GitOps | Flux CD | Continuous reconciliation: Git → k3s |
| Orchestration | k3s | All application workloads |
| Secrets | KeePassXC-compatible | Secret references only (paths, never values) |
| Workbooks | HTML (machine-generated) | Execution and audit records — browser-viewable, print-friendly |

---

## Four Intelligence Layers

### Phase A — Bootstrap Intelligence *(pre-k3s, stdlib Python)*
#### · **Forging Process** (first node) · **Hatchery Process** (broodling spawn)

Runs on the operator's machine or Proxmox host shell before any cluster exists.
No cluster, no dependencies, no network access required.

**Discovery** interrogates the physical host to produce structured profiles:
- CPU topology (model, cores, threads, socket count, architecture)
- RAM inventory (total, ECC status, DIMM population)
- Storage discovery (drives: model, serial, capacity, type, interface, SMART health)
- Network hardware (NIC models, ports, speed, MAC addresses, bonding capability)
- Proxmox state (existing VMs, backups, cluster membership, storage pools)

**Planning** produces a validated deployment plan from discovered hardware +
declared metadata:
- Cluster topology (single-node vs HA based on physical host count)
- Storage pool topology (mirror/raidz1/raidz2/raidz3 from disk count and mix)
- VM sizing (VMID allocation, RAM/CPU per role, IP assignment)
- Naming plan (all hostnames, DNS entries, KeePass paths — convention-validated)

**Generation** produces deployment-ready artifacts from the plan:
- OpenTofu variable files (`.auto.tfvars`) for each VM role
- Cloud-Init snippets (user-data, network-config, vendor-data per VM)
- Ansible inventory and k3s configuration files
- Flux CD bootstrap configuration pointing at Forgejo

**Validation** gates deployment on capacity, naming, and readiness checks.
Any RED finding blocks deployment until resolved.

**Node Spawning** — when a new physical host (a **broodling**) is being added to
the same Proxmox datacenter, the **hatchery process** reads current cluster state
and produces a **spawn package**: a self-contained archive of scripts and a
reserved-resource data dump copied to the broodling after its bare Proxmox
bootstrap. The spawn package knows everything the hatchery has reserved — VMIDs,
IPs, hostnames, cluster topology, placement policy — and configures the broodling
around those constraints so it joins cleanly without conflict.
See [Node Spawning](#node-spawning) below.

---

### Phase B — Documentation Engine *(k3s workload, continuous)*

Continuously collects state from Proxmox API, Kubernetes API, Flux CD, OpenTofu
remote state, Forgejo, and metadata YAML files. Generates living documentation
committed back to Forgejo:

- **Intent-aware architecture docs** — not just *what*, but *why* and *which policy*
  drove the decision. Example: "3 control-plane nodes [policy: k3s-cluster#ha-control-plane,
  reason: etcd quorum requires 3 servers at ≥ 3 physical hosts, current: 3 hosts]"
- **Full resource inventory** (VMs, pods, services, PVCs, storage pools)
- **Service dependency graph** (Mermaid source → rendered SVG)
- **Drift report** (declared vs observed divergence — what exists that shouldn't, and vice versa)
- **Changelog** (changes since previous generation)

Documentation regenerates within 15 minutes of any metadata commit or infrastructure change.

---

### Phase B.5 — Assessment Engine *(k3s workload, scored)*

Evaluates five categories and produces five scored dimensions (0–100 each):

| Score | Category | What It Measures |
|---|---|---|
| **ACS** | Architecture Compliance | Drift, naming violations, placement policy, unmanaged resources |
| **RRS** | Recovery Readiness | Backup age vs RPO, phoenix package validity, secret coverage |
| **DCS** | Documentation Coverage | Resources documented, mandatory fields complete, intent fields populated |
| **CRS** | Capacity Risk | CPU/RAM/storage utilization vs declared thresholds |
| **OSS** | Operational Stability | Pod restart rates, Flux reconciliation lag, k8s error event rate |

These aggregate into a **Platform Health Score (PHS)**. Thresholds: GREEN ≥ 80,
YELLOW 60–79, ORANGE 40–59, RED < 40.

All findings produce human-reviewable recommendations with severity, component,
description, and suggested remediation. The Assessment Engine never takes autonomous
action on infrastructure. Autonomous remediation is explicitly deferred to a
post-Phase 12 governance review with defined safeguards.

---

### Phase C/D — Recovery and Execution Intelligence *(k3s + standalone scripts)* · **Stargate Process**

Generates and executes recovery knowledge in the form of **phoenix packages** —
self-contained archives that rebuild a failed node back to as close to its original
state as possible, even if the underlying hardware has changed.

**Recovery wave ordering** — the sequence the phoenix playbook reconstructs in
(generated by `phoenix_playbook.py`; one `phase-{N}-{name}.sh` script per wave):

```
Wave 0    Network reconstruction   (bridges from declared network topology)
Wave 1    ZFS pool restore/create  (topology adapted to the replacement disks)
Wave 2    Proxmox host config      (hostname, /etc/hosts, datastore registration)
Wave 2.5  Template rebuild         (conditional — only if a base template is missing)
Wave 3    VM restore from PBS      (identity-preserving: same VMIDs/IPs; RECREATE where flagged)
Wave 4    k3s cluster membership   (certs + node name preserved — rejoins, not re-bootstraps)
Wave 5    Post-restore validation  (cluster health, all in-scope VMs running)
```

Application and platform workloads are not separate waves: once the node rejoins
in Wave 4, Flux CD reconciles its disposition-appropriate workloads automatically.

**RESTORE vs RECREATE** decisions are made per component (data restore from PBS
vs full recreation via IaC + Ansible).

**Executable phoenix scripts** are checkpoint-based, resumable, and offline-capable.
Phases 1–3 (through k3s) require only the phoenix package, the operator's machine,
and PBS backup access — no internet, no Forgejo required.

**HTML recovery workbook** — machine-generated execution audit trail (every step
status, timestamp, operator notes, validation results). Opens in any browser;
checkboxes save state in localStorage; print-friendly.

**Failure packages** — structured, LLM-optimized analysis artifacts generated
automatically on any script step failure. Contains: what was attempted, the error,
system state at failure, all logs, and a pre-composed LLM prompt for root cause
analysis.

---

## Forging — Building the First Node

**Forging** is the process of turning bare hardware into a self-managing hatchery
from scratch. It is what every broodforge deployment begins with — before there is
a hatchery, before there are broodlings, before there is a stargate to rise through.

### The Forge Package

The **forge package** is a self-contained archive that the operator downloads and
runs on a freshly installed Proxmox host. It contains everything needed to go from
"bare Proxmox" to a fully operational broodforge hatchery — no prior cluster, no
prior state, no internet required after the package is copied to the host.

```
forge-package-{cell_id}-{ts}.tar.gz
  ├── forge-manifest.json     Declared intent: cell identity, naming convention,
  │                            hardware requirements, secret registry paths
  ├── discovery/              Hardware, network, storage discovery scripts
  ├── planners/               Cluster, storage, network, naming planners
  ├── generators/             OpenTofu vars, Cloud-Init snippets, Ansible inventory
  ├── [opentofu/]             IaC for Proxmox VMs (Forgejo, operations VM) — in progress (see FORGING.md)
  ├── ansible/                Roles + playbooks: common, forgejo, operations-vm, k3s-server
  ├── scripts/
  │   ├── forge.sh            Orchestrated entry point — runs all phases
  │   ├── phase-00-discover.sh   Hardware/network/storage discovery
  │   ├── phase-01-plan.sh       Cluster/storage/network/naming planning
  │   ├── phase-02-validate.sh   Capacity, naming, readiness validation (RED blocks)
  │   ├── phase-03-host.sh       Proxmox host configuration (hostname, ZFS, bridges)
  │   ├── phase-04-vms.sh        Forgejo + operations VM provisioning (tofu apply)
  │   ├── phase-05-k3s.sh        k3s single-node cluster deployment
  │   ├── phase-06-gitops.sh     Flux CD bootstrap → GitOps operational
  │   ├── phase-07-intelligence.sh  Doc engine + assessment engine deployed
  │   └── phase-08-verify.sh    Full health check; bootstrap-state.json committed
  ├── workbook/
  │   └── forge-workbook.html  Auditable execution record (same checkpoint pattern)
  └── lib/                    checkpoint.sh, validation.sh, failure-package.sh
```

### The hatchery's domain name

During phase-01 (plan), the operator provides their domain:

```
Your domain name (e.g. home.example.com): _
```

This becomes the root for all node names in the cluster: `hatchery.home.example.com`,
`forgejo.home.example.com`, `pbs.home.example.com`, and so on.
The hatchery's FQDN is the single stable address used everywhere — Headscale server
URL, Forgejo remote, backup destinations, and spawn packages.

Phase-03 (host config) deploys **dnsmasq** on the Proxmox host and configures it
for split-horizon DNS: LAN clients that use the hatchery as their nameserver resolve
`hatchery.home.example.com` to the LAN IP; WAN clients resolve the same name to
the WAN IP via the operator's external DNS registrar. The dnsmasq config is generated
directly from `dns-registry.yaml`, so every registered hostname is automatically served.

For operators with dynamic WAN IPs, forge optionally configures a DDNS agent
(Cloudflare, Duck DNS, No-IP) that keeps the external A record current.

### What Forging Produces

After `forge.sh` completes, the hatchery is operational:

```
Proxmox host configured
  └── Forgejo VM                Git hosting — all repositories; source of truth
  └── Operations VM             Phase A toolchain + emergency access
  └── k3s cluster (single node)
        └── flux-system         GitOps engine — reconciles from Forgejo
        └── cert-manager        TLS management
        └── ingress-nginx       HTTP routing
        └── doc-engine          Documentation Engine — GATE 1
        └── assessment-engine   Assessment Engine — GATE 2
```

The hatchery can now:
- Document and assess its own state continuously
- Produce spawn packages for broodlings (hatchery process)
- Produce phoenix packages for self-recovery (stargate process)
- Host user applications (after intelligence layer gates pass)

### Minimum Viable Forge

The forge package deploys the broodforge stack only — no user applications, no
monitoring stack, no additional services. This is intentional: the hatchery must
understand and assess itself before hosting anything else. The gates in the
deployment order enforce this:

```
forge.sh phase-00  Discover hardware → validated hardware profile
forge.sh phase-01  Plan deployment → cluster/storage/network/naming plan
forge.sh phase-02  Validate plan → RED finding blocks forge until resolved
forge.sh phase-03  Configure host → ZFS, bridges, hostname, apt repos
forge.sh phase-04  Provision VMs → Forgejo + operations VM online
forge.sh phase-05  Deploy k3s → single-node cluster operational
forge.sh phase-06  Bootstrap Flux → GitOps reconciling from Forgejo
forge.sh phase-07  Deploy intelligence → doc engine + assessment engine
forge.sh phase-08  Verify + commit → bootstrap-state.json in Forgejo

[Hatchery is now forged — user applications can be added via GitOps]
```

Any phase failure generates a failure package with full logs and a pre-composed
LLM analysis prompt. The forge is resumable from the last successful checkpoint.

---

## Node Spawning — The Hatchery Process

Once forged, the hatchery can spawn additional nodes. The **hatchery process**
runs on the hatchery to produce a **spawn package** — the artifact a broodling
uses to join without conflicting with anything already reserved.

### The Spawn Package

The hatchery process reads the hatchery's current cluster state and produces a
**spawn package**: a self-contained archive copied to a broodling after bare
Proxmox installation and executed there. It does not require the operator to know
what is already allocated or to manually coordinate with the hatchery.

```
spawn-package-{cell_id}-{new-hostname}-{ts}.tar.gz
  ├── spawn-manifest.json        Reserved-resource snapshot from assessment engine:
  │                               all existing VMIDs, IPs, hostnames, cluster state,
  │                               k3s join tokens, Proxmox cluster join address
  ├── spawn-plan.json            Conflict-validated allocations for this node:
  │                               new VMID block, new IPs, new hostnames, ZFS topology,
  │                               k3s role, VM roles per placement policy
  ├── spawn.sh                   Orchestrated entry point — runs all phases
  ├── [tailscale-join.sh]        WAN mode only: Headscale/Tailscale join (phase-00a)
  ├── phase-00-preflight.sh      Hardware pre-flight (read-only; conflict re-validation)
  ├── phase-00-host.sh           Hostname, bridges, ZFS pool, datastore registration
  ├── phase-01-proxmox.sh        pvecm add + cluster membership verification
  ├── phase-02-vms.sh            OpenTofu apply for this host's VM set
  ├── phase-03-cloudinit.sh      Install Cloud-Init snippets into Proxmox snippet store; start VMs
  ├── phase-04-k3s.sh            k3s join (worker or server role)
  ├── [phase-05-ha.sh]           Conditional — etcd HA promotion (3rd server node only)
  ├── phase-06-verify.sh         Post-spawn validation; POST /api/spawn-complete to hatchery
  ├── validate-spawn.py          Conflict re-validator run by phase-00-preflight (+ import closure)
  ├── opentofu/                  Hardware-adapted tfvars for this host's VMs
  ├── cloud-init/                Adapted snippets (IPs from spawn-plan, not hatchery)
  ├── ansible/                   Inventory additions for this host
  ├── spawn-manifest.html        Human-readable package manifest (AD-051)
  ├── spawn-workbook.html        Auditable execution record (same pattern as recovery workbook)
  └── lib/                       checkpoint.sh, keepass-gate.sh
```

The spawn manifest is a point-in-time snapshot of everything the hatchery has
reserved. The spawn plan is the conflict-validated answer to: given those
reservations and the broodling's declared disposition, what does this specific
broodling get?

### Disposition — What the New Node Is Meant to Do

Every broodling has a **disposition** chosen at package generation time on the
hatchery. The disposition is a list of specific services to deploy on the broodling,
selected interactively from what the hatchery actually runs. A broodling with less
RAM, fewer disks, or slower CPUs can join the cluster and contribute meaningfully
without being expected to run services it can't support.

**Minimum viable participation (always included, cannot be deselected):**
- Joins the Proxmox cluster
- Runs at least one k3s worker node
- Is visible to the assessment and documentation engines (appears in inventory,
  contributes hardware/state data to `bootstrap-state.json`)
- Runs the intelligence collectors so the hatchery knows its state

**Because the hatchery runs split-horizon DNS, every spawn package uses the same
Headscale URL regardless of the broodling's location:**

```
Headscale server: https://hatchery.home.example.com:8080
```

- LAN broodlings resolve `hatchery.home.example.com` to the LAN IP via the
  hatchery's dnsmasq — the connection stays on the local network
- WAN broodlings resolve the same name to the WAN IP via public DNS, routing
  through the operator's port forwarding to reach Headscale

One spawn package, one URL, works from anywhere.

**The spawn planner asks network mode first to determine the SSH discovery path:**

```
Is the broodling on the same LAN as the hatchery?
[auto-detecting... timeout 5s]

  1. Same LAN  — direct SSH using temporary root password
  2. WAN       — Headscale tailnet (phase-00a joins tailnet before discovery;
                 Headscale URL is hatchery.{domain} — correct for both LAN and WAN)
  3. Specify   — enter broodling IP / hostname manually

> _
```

**LAN mode:** hatchery SSHes directly to the broodling using the temporary root
password generated by the planner. No Tailscale involved.

**WAN mode:** the planner generates a one-time Headscale auth key and embeds it in
the spawn package. On the broodling, `phase-00a` installs Tailscale and registers:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up --authkey tskey-auth-k1234XXXX \
             --login-server https://hatchery.home.example.com:8080
```

The broodling appears on the hatchery's tailnet. All subsequent communication uses
the WireGuard tunnel — no port forwarding beyond the Headscale port, no static WAN
IP on the broodling side. After spawn, Tailscale remains installed and the broodling
is a permanent tailnet member.

**Headscale** auto-configures during hatchery forging. No Tailscale Inc. account needed.

**The spawn planner asks execution mode second:**

```
How should the spawn package run on the broodling?

  1. Autonomous (default)  — finalise service selection now; spawn.sh runs without
                             prompting after the KeePass unlock gate
  2. Interactive            — no service selection needed now; spawn.sh evaluates
                             the broodling's hardware at runtime and presents the
                             service menu there

> _
```

**If Interactive:** the planner is done. The package is assembled with all available
service scripts included. Service selection happens entirely on the broodling at
execution time — there are no further choices to make on the hatchery.

**If Autonomous:** the planner continues with service selection:

```
How should this node be configured?

  1. Full mirror  — deploy all services the hatchery runs that fit this broodling's hardware
  2. Select by group  — pick infrastructure / platform / application groups
  3. Select individually  — choose specific services one by one

> _
```

Autonomous mode is the default for speedy, hands-off deployment. The service
list is finalised on the hatchery and the package runs end-to-end without further
operator decisions. The only prompt on the broodling is the KeePass master password
entry (see [KeePass Security](#keepass-and-secret-security)).

Interactive mode is for cases where the operator wants to make final decisions
on-site, or where the broodling's hardware may differ from what was profiled on
the hatchery. The package carries all service scripts; `spawn.sh` re-evaluates
actual hardware at runtime and presents the selection menu there.

For options 2 and 3, the planner shows each service with its hardware fit status
derived from `metadata/service-catalog.yaml` and the new host's hardware profile:

```
INFRASTRUCTURE SERVICES
  [✓] k3s-server        4 GB RAM req  /  14 GB avail  — adds HA control plane
  [✓] k3s-worker        2 GB RAM req  /  14 GB avail  — adds compute capacity (selected by default)
  [✓] pbs-datastore     requires dedicated disk  /  4 disks detected (raidz1)

PLATFORM SERVICES
  [✓] cert-manager      256 MB RAM req  /  fits
  [✓] ingress-nginx     512 MB RAM req  /  fits
  [✓] flux-system       512 MB RAM req  /  fits (replica of existing GitOps source)

INTELLIGENCE LAYER
  [✓] doc-engine        1 GB RAM req  /  fits  — HA replica of documentation engine
  [✓] assessment-engine 1 GB RAM req  /  fits  — HA replica of assessment engine

MONITORING
  [✓] prometheus        2 GB RAM req  /  fits
  [✓] grafana           512 MB RAM req  /  fits
  [✗] loki              4 GB RAM req  /  insufficient (2 GB would remain after other services)

APPLICATIONS
  [✓] nextcloud         2 GB RAM req  /  fits  — requires storage disposition
  [✓] immich            3 GB RAM req  /  fits  — requires storage disposition
  [✗] gitea             RAM fits  /  no dedicated disk detected for data volume

Total selected: 11.2 GB RAM / 14 GB available  (1 service excluded due to RAM, 1 due to storage)
Proceed with this selection? [Y/n/edit]
```

Services that don't fit are shown with a specific reason (RAM, disk, dependency)
and excluded from the plan — they do not cause the spawn to fail. The operator
can adjust the selection before the package is built.

**The disposition is recorded in `spawn-plan.json` and `bootstrap-state.json`
as a service list, not abstract flags.** The assessment engine reads it and only
scores the broodling against services it was deployed to provide. A broodling
without `prometheus` in its disposition is not penalized for a missing Prometheus replica.
A mismatch between declared disposition and observed reality remains a RED finding —
disposition does not excuse missing what was explicitly selected.

### What the Assessment Engine Accounts For at Package Generation

The assessment engine reads current cluster state before generating any spawn
package. It accounts for:

- **Reserved VMIDs** — all VMIDs in use across all existing hosts; allocates a
  non-overlapping block for the new host
- **Reserved IPs** — all addresses in the DNS registry and provenance records;
  new IPs allocated from the declared subnet without collisions
- **Reserved hostnames** — all hostnames in the naming plan; new names are
  convention-compliant and globally unique
- **Cluster join credentials** — k3s join tokens and Proxmox cluster address embedded
  in the spawn manifest; new host joins without operator intervention
- **Disposition vs. hardware** — each selected capability flag is validated against
  the hardware profile; flags that don't fit are dropped from the plan with a clear
  warning before the package is built, not as a failure after deployment

### What Adapts to the New Host's Hardware

| Hardware difference | How the spawn package adapts |
|---|---|
| Different disk count / mix | ZFS pool topology recalculated (mirror / raidz1 / raidz2) |
| Different NIC count or speed | Bridge/bond configuration from that host's NIC inventory |
| Different RAM | Services that don't fit are excluded from selection with a reason |
| Lesser overall capability | Operator selects a reduced service list; baseline always included |

**What does not change:** Naming convention, KeePass path structure, Proxmox cluster
membership, the intelligence collection baseline, secret references.

### Spawn Workflow

The operator's interaction is: install Proxmox → copy spawn package → run
`spawn.sh`. Everything else is automated.

#### On the Hatchery — before touching the broodling

**Step 1 — Execution mode** (asked first):

- **Interactive:** skip to package assembly — no hardware profile needed. Service selection happens on the broodling at runtime.
- **Autonomous:** continue to Step 2.

**Step 2 — Hardware discovery** (autonomous only):

The hatchery is a trusted node on the homelab LAN. Password-based SSH from the hatchery to a fresh broodling is acceptable — no pre-exchanged keys required.

The spawn planner generates a suggested temporary root password before the operator touches the broodling:

```
Suggested temporary root password for Proxmox installation:
  Ready.to.spawn.7
Use this when setting the root password during Proxmox install.
Press Enter here when the installation is complete and the node is reachable.
```

The hatchery already knows the password it suggested, so discovery proceeds automatically once the operator signals that Proxmox is installed:

```
Connecting to 192.168.1.100 as root... ✓
Running discover-hardware.py... ✓
Running discover-network.py...  ✓
Running discover-storage.py...  ✓
hardware-profile-pve-node-02.json saved.
```

If the operator used a different password during installation, the planner prompts for it instead. The password is transmitted over the local trusted network and replaced by properly generated KeePass-managed credentials during spawn. It is valid only from Proxmox installation until `phase-03-cloudinit.sh` runs and sets the real password.

**Step 3 — Spawn planning** (autonomous only):

```bash
spawn-planner.py --hostname pve-node-02 --profile hardware-profile-pve-node-02.json
```

The planner presents a hardware fit assessment and service selection:

```
[✓] compute       — 12 GB RAM available, 6 GB required — fits
[✓] storage       — 4 dedicated disks detected — fits (raidz1)
[✗] control-plane — requires 4 GB RAM; only 2 GB available after other roles
[✗] monitoring    — requires 2 GB RAM; insufficient after compute allocation
```

The operator confirms or adjusts, locking the disposition into `spawn-plan.json`. The Assessment Engine then reads hatchery cluster state into `spawn-manifest.json` — all reserved VMIDs, IPs, hostnames, Proxmox cluster address, and k3s tokens. The conflict validator blocks package generation on any collision.

The spawn package is then assembled and ready to copy to the broodling. In autonomous mode it is offline-capable — the broodling never queries the hatchery API. In interactive mode all service scripts are included and selection happens at runtime.

#### On the Broodling — bare Proxmox just installed

**phase-00a** [WAN mode only] Tailscale join — runs before anything else. Installs Tailscale and registers with the hatchery's Headscale using the embedded auth key. The broodling appears on the tailnet so the hatchery can SSH in for coordination. Skipped entirely in LAN mode where direct SSH is already available.

**phase-00** Host bootstrap — two sub-stages:

- **[A] Hardware pre-flight** (read-only, no changes made): Re-scans actual hardware and diffs against the embedded `hardware-profile.json` — disk IDs, NIC names/MACs, RAM vs disposition minimums, no conflicting pool or bridge names, conflict re-check vs manifest. A mismatch generates a failure package with a diff and exits; nothing is written to the host. On pass, proceeds to [B].

- **[B] Host configuration:** Sets hostname and `/etc/hosts`, writes bridge definitions, runs `ifreload -a`, creates the ZFS pool (topology from plan, disk IDs confirmed by pre-flight), registers the Proxmox datastore with `pvesm add`, and configures apt repos. After this phase: bridges exist, storage is registered, hostname is correct.

**phase-01** `pvecm add` → joins Proxmox cluster.

**VM Provisioning** (only VMs declared by disposition):

- **phase-02** `tofu apply` — only disposition-selected VM roles provisioned
- **phase-03** Cloud-Init snippets installed → VMs started → first-boot runs

**Cluster join:**

- **phase-04** k3s join — worker role always; server role only if disposition includes control-plane and hardware pre-flight confirmed it fits
- **phase-05** [conditional] etcd HA promotion if this is the 3rd server node
- **phase-06** Verify: cluster health, all disposition VMs running, no IP conflicts

After phase-06, everything is automatic: Flux CD schedules only workloads matching this node's disposition labels and taints; the Assessment Engine scores the broodling only against its declared disposition; the Doc Engine regenerates the topology showing the broodling's role in the cluster.

Any phase failure generates a failure package automatically.

### Example Broodling Dispositions

| Broodling type | Selection | Use case |
|---|---|---|
| Full mirror | All services that fit | Matches hatchery capabilities; Flux schedules freely |
| Lightweight companion | k3s-worker + cert-manager + ingress | Small machine adds compute; no storage or HA |
| Storage node | k3s-worker + pbs-datastore + longhorn | NAS-class machine; adds backup target and PVC replicas |
| HA enabler | k3s-server (only) | Upgrades cluster to 3-server etcd quorum; minimal footprint |
| App replica node | k3s-worker + nextcloud + immich | Adds capacity for specific applications that support replicas |
| Observer only | *(baseline only)* | Joins cluster, visible to assessment, runs no workloads |

---

## KeePass and Secret Security

All forge, spawn, and phoenix packages carry KeePass **paths** — references that
locate secrets within the operator's database. The package scripts never store or
emit secret values in plain text. Beyond paths, the KeePass database itself is
**optionally** included in a package for convenience, but the security model ensures
that inclusion alone is harmless without the master password.

### The database inclusion choice

At package-generation time the operator chooses one of three options for the
KeePass database:

```
Where should the KeePass database come from during deployment?

  1. Include in this package  — database file is embedded in the archive
                                (convenient; safe because it cannot auto-unlock)
  2. Path on the target host  — database lives on a USB drive, a local disk,
                                or a pre-agreed filesystem path on the new node
                                (not embedded; operator specifies path at run time)
  3. Prompt at run time       — spawn.sh asks the operator for the path when it runs

> _
```

Options 2 and 3 are for environments where the operator prefers to keep the
database entirely separate from the deployment archive.

### The KeePass unlock gate

Regardless of how the database is sourced, **it cannot be auto-unlocked**. Before
any secret is accessed, the installer pauses and prompts:

```
KeePass database located at: /media/usb0/cluster.kdbx
Enter master password: _
```

The master password is entered once at the start of the bootstrap process. After
that, the **secrets broker** handles all subsequent secret lookups automatically
for the duration of that session — no further operator input is needed per-secret.
The unlocked state lives only in process memory; nothing is written to disk.

In **autonomous spawn mode**, this gate and the hardware pre-flight confirmation
are the only human interactions before fully automated execution.

In **interactive spawn mode**, the master password gate is followed immediately by
the service selection prompt.

### What packages contain vs. what they don't

| Always in package | Optional | Never included |
|---|---|---|
| KeePass secret paths (references) | KeePass database file | Any secret value |
| Service configuration skeletons | | Unlocked credential material |
| VM configuration parameters | | |
| Cluster join addresses and fingerprints | | |
| k3s join tokens* | | |

*k3s join tokens are included in the spawn manifest but are valid only during the
spawn window and are rotated after the broodling joins successfully.

**Security property:** A package without the database is useless without both the
database file and the master password. A package with the database embedded is useless
without the master password. Either way, interception of the package alone yields
no usable credentials — only the paths at which they are stored.

---

## Password Generation

Broodforge uses a two-tier password generation approach. The goal is passwords that
are both human-usable and machine-safe — without forcing operators to copy random
strings from screens, and without failing on services that reject common special characters.

### Tier 1 — Readable passphrases (default for all user-facing passwords)

Whenever a password will be seen or entered by a human — KeePass master password
suggestion, service admin credentials, initial VM passwords — broodforge generates
a readable passphrase:

```
Format:  Capital.word.phrase.9
         └── Leading capital letter
             └── Remaining letters lowercase
                 └── Words separated by periods
                     └── Trailing single digit
                         └── Total length: 20–30 characters
```

Examples:
```
Correct.horse.battery.3
Network.surge.proxy.7
Stable.margin.deploy.2
```

These passphrases are human-memorable, typeable in a terminal without quoting or
escaping, and satisfy most service password requirements (letters, digits, and periods
are universally accepted in typical applications).

### Tier 2 — Alphanumeric fallback (for services that reject special characters)

Some services reject passwords containing periods, underscores, or any non-alphanumeric
character. If broodforge detects a deployment failure with a pattern matching a
credential rejection (authentication failure, invalid password format, bad character),
it:

1. Identifies the affected service and the likely character restriction
2. Offers to regenerate the credential as a plain alphanumeric password (letters +
   digits only, same length range — the KeePass default format)
3. Retries the failed deployment phase with the new credential
4. Records the service name and character restriction in `service-catalog.yaml` as
   `password_format: alphanumeric`, so the restriction is applied automatically in
   every future deployment — no manual detection needed after the first encounter

### Master password — forging

During forging, the operator sets the KeePass master password for the first time.
Broodforge presents two options:

```
Choose your KeePass master password:

  1. Generate  — produce a readable passphrase (e.g. Correct.horse.battery.3)
  2. KeePass   — use KeePass's built-in password generator (stronger options available)
  3. Enter     — type your own

Password is confirmed by re-entry. It is never stored by broodforge.
```

The generated passphrase option produces a password that the operator can write down
legibly and recover from cold storage if needed — an important property for the
database that protects everything else in the cluster.

---

## Backup Architecture

Broodforge uses **[restic](https://restic.net/)** as its backup engine and
**[rclone](https://rclone.org/)** as its cloud storage transport layer. Restic
provides encryption at rest, deduplication, versioned snapshots, retention policies,
and permanent checkpoint tagging. Rclone provides a unified interface to dozens of
cloud storage providers so broodforge does not need a separate integration per vendor.

Together, restic + rclone cover: local disk, USB drives, Backblaze B2, AWS S3,
Cloudflare R2, Google Drive, Dropbox, SFTP targets, self-hosted MinIO, and more —
using the same backup commands regardless of where the data lands.

### What gets backed up

Three independent backup layers, each with its own schedule and destination policy:

| Layer | What is included | Default | Trigger |
|---|---|---|---|
| **Secrets** | KeePass database | Always | Any cluster state backup; also on any new secret added |
| **Configuration state** | `bootstrap-state.json`, assessment history, generated docs, all node states | Always | Assessment engine run completes |
| **Application data** | VM data volumes (Nextcloud files, Immich photos, database dumps) | Opt-in per volume | Schedule declared per volume in service-catalog |

**Every node's configuration is visible to every other node.** The assessment engine
on each node holds the full cluster state — any node can construct a phoenix package
for any other. Configuration backup is therefore cell-scoped, not node-scoped.

The KeePass database backup is non-optional once a backup destination is configured.
A database that goes stale after new services are deployed without being backed up
makes recovery impossible; this is treated as a critical readiness gap.

### Backup destinations — ordered chain model

Destinations are configured as an **ordered chain** of unlimited depth. When a
backup runs, each destination in the chain is attempted. Failures are logged and
exposed — never swallowed. If a destination fails, the next one in the chain is
tried automatically. If every destination fails for a layer, this is surfaced as a
RED finding in the assessment report and the next scheduled run will retry.

The chain can be as long as needed. Two destinations cover the common case (e.g., local
disk + cloud). More destinations provide deeper redundancy without any limit.

| Destination type | Examples | Authentication |
|---|---|---|
| Local filesystem | `/backup`, `/mnt/spare-drive` | None (path) |
| Removable media | `/media/usb-backup` | None (path; mount must exist) |
| Backblaze B2 | `b2:bucket-name/path` | Application Key (ID + secret) |
| AWS S3 / Cloudflare R2 | `s3:bucket/path` | Access Key + Secret Key |
| Google Drive | `rclone:gdrive:/backups/cell` | OAuth2 / Service Account |
| SFTP | `sftp:host:/backup/path` | SSH key |
| Self-hosted (MinIO) | `s3:minio-endpoint/bucket` | Access Key + Secret Key |

Cloud destinations require a long-lived API secret or OAuth token — username and
password alone are not accepted. See [`docs/CLOUD-STORAGE-SETUP.md`](docs/CLOUD-STORAGE-SETUP.md)
for step-by-step provider setup guides.

**Each upload is verified** — after writing to a destination, broodforge runs a
restic integrity check (snapshot count and size probe) to confirm the data actually
landed. A destination that accepts data but fails verification is treated the same
as one that rejected the write.

### Encryption

**All backups except the KeePass database** are encrypted by restic before leaving
the source machine. Encryption is mandatory for these layers and cannot be disabled.

**Every individual backup gets its own unique secret.** A component does not carry
the same restic password across all backups for all time. For each backup run,
broodforge generates a new passphrase, adds it to the restic repository
(`restic key add`), and removes the previous one (`restic key remove`). This
rewraps the repository's internal master key without re-encrypting stored data —
it is fast and does not break existing snapshots.

The new password is stored in KeePass at a timestamped path:
```
Backup/{layer}/{component}/2026-06-01_03_00_00/repo-password
Backup/{layer}/{component}/current              → points to latest timestamp
```

At restore time, the secrets broker reads the snapshot's timestamp from
`backup_history`, constructs the correct KeePass path, and retrieves the exact
key that was valid for that snapshot. After `restic forget` prunes a snapshot, the
corresponding KeePass entry is cleaned up automatically.

**Operators never manually handle restic repo passwords — before or after initial setup.**

The encryption chain for a non-KeePass backed-up file:
```
File on disk
  → restic encrypts with run-specific repo password (new per backup, from KeePass)
  → Encrypted chunk written to destination
  → Destination may add its own at-rest encryption (e.g., B2 SSE, S3 SSE)
```

**KeePass database backup — no restic layer:**

The KeePass database is already AES-256 encrypted by KeePass itself. Adding a
restic encryption layer on top would create an irrecoverable circular dependency:
to decrypt the backup you need the repo password; the repo password is stored in
KeePass; but you are trying to restore KeePass. There is no way out of that loop.

The KeePass database is therefore backed up as a plain file copy — the `.kdbx`
file transported as-is to each configured destination via rclone. No restic layer.
The file is already encrypted; anyone who obtains the backup still needs the
KeePass master password (or other configured authentication method) to open it.

**KeePass backup destination credentials** cannot be stored in KeePass for the same
reason. They are stored in `forge-manifest.json` (embedded in the forge, spawn, and
phoenix packages) so they are accessible on a bare machine before KeePass is
available. This is the one exception to the rule that packages carry only KeePass
references — the KeePass backup transport credentials must exist outside KeePass.

Recovery flow for a lost KeePass database:
```
1. Obtain forge/spawn/phoenix package  (contains backup destination credentials)
2. Use embedded rclone config to access the KeePass backup destination
3. Download latest .kdbx backup (or a pinned checkpoint version)
4. Open with master password / KeePass authentication method
5. All restic repo passwords and service credentials now available via secrets broker
```

KeePass supports multiple authentication methods (master password, key file,
hardware token). Broodforge stores the auth method metadata in `bootstrap-state.json`
but the actual credential is the operator's sole responsibility — it is never
stored anywhere in the system.

### Backup modes

**Simple mode** — one ordered destination chain, uniform across all layers:

```
Configure backup destination chain (add as many as you like):

  Destination 1: local path /mnt/backup-drive   [verified OK]
  Destination 2: Backblaze B2 b2:cell-backup     [verified OK]
  Add another destination?  [Y/n]

What to back up:
  [x] Secrets (KeePass database)   — always enabled once a destination is configured
  [x] Configuration state          — backed up after every assessment run
  [ ] Application data volumes     — opt-in per service

Retention per layer:
  Snapshots to keep:          [5]
  Permanent checkpoints:      [Y] — operator can tag any snapshot to survive rotation
```

**Detailed mode** — per-node, per-VM, per-container, per-volume heterogeneous policy.
Each component defines its own ordered destination chain and retention count, or
inherits from its parent. Children create sub-directories at inherited destinations.
Sibling settings are auto-suggested to avoid re-entering credentials for related components.

```
Backup policy for: nextcloud (Nextcloud application, VM 102)
  Inherit parent chain (vm:102 → local + B2)?  [Y/n]
  Add volume-level policy for /opt/nextcloud/data (47 GB)?
    Chain: [inherit] / [new destination]  >
    Schedule:    daily at 03:00  >
    Retention:   7 daily, 4 weekly, 3 monthly  >
    Checkpoint?  [Y/n]
```

**Space-aware component routing and chunked splitting:**

Before each backup run, broodforge probes available space at every destination in
the chain. Each component is routed to whichever destination has room:

```
[BACKUP RUN SPACE PROBE]
  destination 1 (/mnt/backup-drive):  12 GB available  (need 8 GB for forgejo) ✓
  destination 2 (b2:cell-backup):      2 GB available  (need 8 GB for forgejo) ✗ full
  destination 3 (rclone:gdrive):      40 GB available  ✓

  Component routing:
    forgejo          (8 GB)  → destination 1  [primary — space OK]
    inventory        (3 GB)  → destination 1  [primary — space OK]
    assessment-vm    (6 GB)  → destination 2  [space_fallback — dest 1 now tight]
    nextcloud-data  (18 GB)  → chunked_split:
                                 /var/www        (9 GB)  → destination 1
                                 /var/db         (9 GB)  → destination 3
                              [no single dest has 18 GB; split at sub-component level]
```

All routing decisions are recorded in `backup_history` alongside the
`snapshot_set_id` that links sub-component pieces belonging to the same logical
backup point. Restore reads this metadata and automatically assembles chunked
backups from their respective destinations without operator involvement.

If a component cannot be split further (e.g., a single large VM disk image) and
no destination has enough space, that specific component surfaces as a
human-required decision. All other components in the run continue.

**Failure exposure — never silent:**

```
[BACKUP RUN 2026-06-01_03-00_00_UTC]
  layer: config-state
    destination 1 (/mnt/backup-drive):  ✓ 847 MB  verified
    destination 2 (b2:cell-backup):     ✗ FAILED — connection timeout after 30s
    destination 3 (rclone:gdrive):      ✓ 847 MB  verified
  result: PARTIAL — 2/3 destinations succeeded
  WARNING: destination 2 has failed 3 consecutive runs — investigate B2 connectivity

[BACKUP RUN 2026-06-02_03-00_00_UTC]
  layer: config-state
    ALL 3 DESTINATIONS FAILED — RED GAP LOGGED
    Assessment engine will surface this at next run
```

### Backup naming convention

Every backup file, restic repo path, KeePass key entry, and snapshot set identifier
follows a consistent naming convention so the purpose of any backup artifact is
immediately readable from its name alone — no metadata lookup required.

**Component type prefixes:**

| Prefix | What it backs up |
|---|---|
| `kdbx` | KeePass database |
| `cell-config` | Cell-wide configuration state (bootstrap-state.json, assessment history) |
| `node-{hostname}` | Proxmox host (e.g., `node-pve01`) |
| `vm-{name}-{vmid}` | Virtual machine (e.g., `vm-forgejo-101`) |
| `ct-{name}-{ctid}` | LXC container (e.g., `ct-postgresql-200`) |
| `vol-{vm_name}-{vol_name}` | Data volume within a VM (e.g., `vol-nextcloud-data`) |
| `svc-{service_name}` | Application service (e.g., `svc-immich`) |

**KeePass database file copies** (rclone, no restic layer):
```
kdbx_{cell_id}_{YYYY-MM-DD_HH-MM_SS_TZ}_{hash8}.kdbx

Examples:
  kdbx_proxmox-cell-a_2026-06-01_03-00_00_UTC_a3f2b891.kdbx
```
`{hash8}` = first 8 hex characters of the SHA-256 of the `.kdbx` file at backup time.
Changes whenever the database changes; confirms which version of the DB was captured.

**Restic repository paths** (directory at each destination):
```
{destination_root}/{cell_id}/{layer}/{component}/

Examples:
  /mnt/backup/proxmox-cell-a/config/vm-forgejo-101/
  b2:cell-backup/proxmox-cell-a/appdata/vol-nextcloud-data/
  rclone:gdrive:broodforge/proxmox-cell-a/config/cell-config/
```
The repo directory is the stable, human-readable identifier. The restic snapshot
IDs inside it are the 40-character hex IDs restic assigns internally.

**Snapshot set identifiers** (links all component snapshots from one backup run):
```
{cell_id}_{YYYY-MM-DD_HH-MM_SS_TZ}_{run_hash8}

Examples:
  proxmox-cell-a_2026-06-01_03-00_00_UTC_f7c1d3a2
```
`{run_hash8}` = first 8 characters of the snapshot_set UUID. Used as the
`snapshot_set_id` in `backup_history` and as a restic snapshot tag.

**Restic snapshot tags** (attached to every restic snapshot at creation):
```
cell:{cell_id}
set:{snapshot_set_id}
component:{component_prefix}
layer:{config|appdata}
run:{YYYY-MM-DD_HH-MM_SS_TZ}
```
Tags make every snapshot queryable by `restic snapshots --tag component:vm-forgejo-101`
without needing to open the backup_history JSON.

**KeePass key paths** (per-backup restic repo passwords):
```
Backup/{layer}/{component}/{YYYY-MM-DD_HH-MM_SS_TZ}/repo-password
Backup/{layer}/{component}/current

Examples:
  Backup/config/vm-forgejo-101/2026-06-01_03-00_00_UTC/repo-password
  Backup/config/vm-forgejo-101/current
  Backup/appdata/vol-nextcloud-data/2026-06-01_03-00_00_UTC/repo-password
```

**Naming is enforced, not suggested.** `setup-backup.py`, `run-backup.py`, and
`restore-from-backup.py` construct all paths and names programmatically from
`cell_id`, component metadata, and UTC timestamps. Operators do not name backup
artifacts manually.

### Backup settings as readiness metadata

Backup configuration is stored in `bootstrap-state.json` as a first-class readiness
input. The assessment engine scores:
- **RED** — no destination configured for secrets or configuration state
- **RED** — all destinations failed on two or more consecutive runs (chain is broken)
- **RED** — last successful backup older than 3× the declared schedule interval
- **ORANGE** — any destination in the chain has failed on the last 3 runs (partial coverage)
- **ORANGE** — last successful backup older than 2× schedule interval
- **YELLOW** — all destinations healthy but last backup older than 1× schedule interval
- **YELLOW** — no permanent checkpoint exists
- **GREEN** — all destinations reachable, last backup within schedule, checkpoint exists

A cluster with a stale or fully-failed secrets backup is unrecoverable after a
failure. This is surfaced prominently in every readiness report.

### Automated recovery via secrets broker

The restore process is designed to minimise operator interaction:

1. Operator enters KeePass master password once at the unlock gate
2. Secrets broker retrieves all restic repo passwords from KeePass automatically
3. `restore-from-backup.py` probes each destination for available snapshots
4. Operator selects snapshot (or accepts "latest" / most recent checkpoint)
5. Restore executes — integrity verified post-restore
6. Service credentials re-injected from KeePass automatically (no per-service password re-entry)
7. Restore report generated (what, from where, when, integrity result)

Steps 2, 5, and 6 require no operator input. The only manual decisions are the
master password (step 1) and snapshot selection (step 4).

---

## Documentation Timestamps and Timezone

During forging, the operator sets their preferred timezone for documentation
timestamps. This preference is stored in `bootstrap-state.json` as
`vm_defaults.timezone` and used by the documentation engine when generating
all workbooks, runbooks, and readiness reports.

The display format is: `YYYY-MM-DD HH:MM:SS UTC (HH:MM:SS {TZ})` — both UTC
and local time are always shown, so documents are unambiguous regardless of
reader timezone.

To update the timezone preference after forging:

```bash
python3 doc-gen/engine.py --set-timezone "Australia/Melbourne"
# or edit vm_defaults.timezone in bootstrap-state.json directly
```

---

## Phoenix Package — The Stargate Process

The **stargate process** is what produces a phoenix package when a node has failed.
Where the hatchery process creates something new that must not conflict with what
exists, the stargate process recreates something that *already existed* — sending
its identity through the gate and reconstituting it on new hardware.

A **phoenix package** preserves the failed node's identity exactly, even if the
physical hardware underneath has changed.

> **Operator runbook:** [`docs/PHOENIX.md`](docs/PHOENIX.md) walks the full stargate
> workflow end-to-end — generate the playbook from `bootstrap-state.json`
> (`phoenix-planner.py --state … --output phoenix-playbook.json`), assemble the
> package, copy + verify, and run the recovery waves.

### Hatchery Process vs Stargate Process — the core distinction

| | Hatchery process → Spawn package | Stargate process → Phoenix package |
|---|---|---|
| **Purpose** | New broodling joining the hatchery | Failed node rising from its ashes |
| **Identity** | New — VMIDs, IPs, hostnames allocated without conflict | Preserved — same VMIDs, IPs, hostnames, certs as original |
| **Hardware** | Adapts to new hardware; allocations computed fresh | Adapts to new hardware; identity is fixed, hardware fits around it |
| **k8s node names** | New names per naming convention | Exact original names — cluster membership is restored, not rebuilt |
| **Services** | Chosen by operator at spawn time (disposition) | Full or partial restoration scope chosen at recovery time |
| **Hardcoded reservations** | Avoided — new node gets non-conflicting allocations | Preserved — anything hardcoded in the original config comes back as-is |

### What the Phoenix Package Preserves

When a node is lost to catastrophic hardware failure and replaced with different
physical hardware, the phoenix package ensures that everything at the logical layer
comes back identically:

- **VM names and VMIDs** — Proxmox inventory identity; other nodes reference these
- **VM IP addresses** — DNS registry entries, service URLs, any config that
  hardcodes an IP stays valid
- **Hostnames** — k8s node names are derived from hostnames; changing them
  breaks cluster membership and certificate validity
- **k8s cluster certificates** — tied to the node's hostname and IP; preserved
  so the node rejoins its existing cluster rather than creating a new one
- **Cluster role** — if the original was a k3s server node, the phoenix is too;
  etcd membership is restored, not re-bootstrapped
- **Service-level hardcoded values** — Forgejo's external URL, any service whose
  config bakes in a specific IP or hostname

### What the Phoenix Package Adapts

The new physical hardware may differ from what failed. The phoenix package scans
the new hardware before applying anything and recalculates only the physical layer:

- **ZFS pool topology** — different disk count → different raidz level; same pool
  *name* is preserved so Proxmox datastores and VM disk paths remain valid
- **Network bridge configuration** — different NIC layout → different bridge
  definitions; same bridge *names* are preserved so VM network assignments remain valid
- **Physical disk assignments** — new disk IDs from the replacement hardware

The hardware scan happens as the first phase of the phoenix package on the new
machine, before any identity is applied. If the new hardware cannot meet the
original node's minimum requirements (insufficient RAM for its VM set, insufficient
disks for the original ZFS topology), the phoenix package reports a specific
shortfall and offers a reduced restoration scope rather than failing silently.

### Restoration Scope — Full or Partial

The phoenix package offers a restoration scope selection at recovery time, analogous
to the spawn package's disposition selection:

```
What should be restored on this node?

  1. Full restoration  — restore all services that were running (default)
  2. Select by group  — restore infrastructure first; defer applications
  3. Select individually — choose which services to bring back now vs. later

> _
```

The primary difference from spawn disposition is the default: full restoration
is the expected case for a phoenix. Partial restoration is available for situations
where the replacement hardware is temporarily smaller, or where restoring certain
services should wait until the node is verified stable.

Services deferred at phoenix time are recorded in `bootstrap-state.json` with
`restoration_status: deferred` so the assessment engine knows they are expected
but not yet running, and does not generate spurious RED findings during the
recovery window.

### Phoenix Package Contents

```
phoenix-package-{cell_id}-{hostname}-{ts}.tar.gz
  ├── phoenix-playbook.json      Machine-readable reconstruction plan:
  │                               node identity snapshot (VMIDs, IPs, hostnames,
  │                               cluster role, PBS backup locations), hardware-adapted
  │                               rebuild plan, restoration scope, RESTORE vs RECREATE
  ├── run-all.sh                 Orchestrated entry point — runs each wave in order
  ├── phase-0-network-reconstruction.sh   Wave 0
  ├── phase-1-*.sh               Wave 1 — ZFS pool restore/create
  ├── phase-2-*.sh               Wave 2 — Proxmox host configuration
  ├── [phase-2-5-*.sh]           Wave 2.5 — template rebuild (conditional)
  ├── phase-3-*.sh               Wave 3 — VM restore from PBS (+ per-VM RECREATE)
  ├── phase-4-*.sh               Wave 4 — k3s cluster membership restore
  ├── phase-5-*.sh               Wave 5 — post-restore validation
  │                               (one phase-{N}-{wave-name}.sh per wave, generated
  │                                dynamically from the playbook)
  ├── phoenix-manifest.html      Human-readable package manifest (AD-051)
  ├── [phoenix-workbook.html]    Auditable execution record (optional)
  ├── [kdbx/{cell_id}.kdbx]      Optional embedded KeePass database
  └── lib/                       checkpoint.sh, phoenix-keepass-gate.sh
```

---

## Source of Truth Hierarchy

```
TIER 1 — AUTHORITATIVE INTENT
  metadata/*.yaml  (operators only; changes trigger full regeneration cascade)

TIER 2 — AUTHORITATIVE DECLARED STATE
  OpenTofu state + Kubernetes manifests (in Forgejo)

TIER 3 — AUTHORITATIVE OBSERVED STATE
  Proxmox API + Kubernetes API (reality — cannot be edited, only observed)

TIER 4 — DERIVED ARTIFACTS
  Generated docs, forge packages, spawn packages, phoenix packages, assessment reports

TIER 5 — DISPOSABLE
  Rendered diagrams, cached API responses, intermediate artifacts
```

Conflicts between tiers surface as Assessment Engine findings. Tier 1 (intent)
always wins. Tier 3 (observed reality) never overrides declared intent — it
creates a drift finding instead.

---

## Deployment Gating

Intelligence-layer workloads deploy before any user application. Flux CD
dependency declarations enforce this ordering.

```
Phase A   Bootstrap Intelligence (pre-k3s, operator machine)
          ↓
Phase 2   Proxmox host + Forgejo VM operational
          ↓
Phase 3   k3s cluster operational (single-node initially)
          ↓
Phase 4   Documentation Engine ─────── GATE 1: platform is documented
          ↓
Phase 5   Assessment Engine ────────── GATE 2: platform is scored (PHS computed)
          ↓
Phase 6   Flux CD GitOps ─────────────GATE 3: platform is GitOps-managed
          ↓
Phase 7   Monitoring ────────────────  GATE 4: platform is observable
          ↓
          User Applications ──────────[PHS ≥ 80 required]
```

---

## Development Status

Broodforge is under active development. See [ROADMAP.md](ROADMAP.md) for full
milestone detail and [rhiz-memory/state/SESSION_HANDOFF.md](rhiz-memory/state/SESSION_HANDOFF.md)
for the latest session context. Broodforge follows the
[Rhizome](https://github.com/david-coneff/rhizome) methodology as a child
instance; its memory layer — session handoff, decisions, and audit records —
lives under [`rhiz-memory/`](rhiz-memory/_instance.md). (The session pointer was
previously `docs/SESSION-HANDOFF.md`, retired when broodforge adopted
methodology-governed session continuity; the original is preserved at
[docs/deprecated/SESSION-HANDOFF.md](docs/deprecated/SESSION-HANDOFF.md).)

### Completed

| Milestone | Description |
|---|---|
| Legacy `pae` CLI | Assessment engine, SQLite history, OpenTofu ingestion, report generation |
| Architecture Reviews v4–v7 | Progressive architecture formalization (v7: Assessment Engine as first-class subsystem, 5 scores, 12-phase roadmap) |
| Phase 0 | Metadata model — 10 authoritative YAML schemas + validator |
| Phase 1 | Bootstrap Intelligence — hardware/network/storage discovery + 4 planners + 2 validators |
| Milestones 5.1–5.6 | Data model formalization, bootstrap/recovery doc generators, readiness scoring, drift detection |
| Milestones 6.0–6.8 | Bootstrap State schema, Cloud-Init templates, Secret/DNS registries, provenance tracking, template registry, Tier 2 SSH state collector, Bootstrap Workbook registry wiring |
| Milestones 7.1–7.3 | Service contract implementation, service state schema and collection, external dependency state (cert expiry monitoring, recovery runbook Appendix G) |

**Test suite: 4000 passing, 1 skipped (Windows-only).**
All roadmap milestones complete through Phase 26 (Autonomous Remediation) + 9.T
(Talos alternative), including node spawn automation (Phase 12.E) and the phoenix
recovery/stargate process. The planning, assessment, spawn, phoenix, recovery, and
remediation tiers are implemented and tested.

**One known gap:** the **forge** VM-provisioning IaC — the OpenTofu modules for the
initial Forgejo + operations VMs, and the generated Ansible inventory — is the
active deploy-to-hardware work. `forge.sh` runs end-to-end but phases 04–05 self-skip
with a clear message until that layer lands (see `proxmox-bootstrap/FORGING.md`
→ "Forge provisioning status"). The spawn flow generates its IaC fully and does not
share this gap.

### Active

**Deploy to hardware** — All implementation milestones complete. Next step: run
`python3 proxmox-bootstrap/forge-planner.py` on your workstation to plan the first
cell, then `assemble-forge-package.py` and `bash forge.sh` on a real Proxmox host.
See `proxmox-bootstrap/FORGING.md` for the full operator runbook.

### Upcoming

- **Real-hardware forge validation** — exercise the full forge → spawn → phoenix
  lifecycle on physical Proxmox nodes and fold any failure packages back into fixes.
- **Autonomous remediation governance review** — the post-Phase-12 safeguard review
  before enabling autonomous infrastructure action by default (see Phase 26 / AD on
  remediation policy in [ROADMAP.md](ROADMAP.md)).

---

## Project Structure

```
broodforge/
├── .ai/                       Project context, current state, decisions
├── config/
│   └── user-registry.json     User registry — who has accounts in k8s services
├── data-model/                JSON schemas + stdlib validator
├── doc-gen/                   Documentation generation engine (stdlib only)
│   ├── engine.py              CLI: --mode bootstrap | recovery
│   ├── registries.py          SecretRegistry + DnsRegistry
│   ├── template_registry.py   TemplateRegistry
│   ├── provenance.py          ProvenanceRegistry
│   ├── readiness.py           GREEN/YELLOW/ORANGE/RED scorer
│   └── renderers/             HTML document generators (deprecated/ holds old ODS/ODT)
├── engine/                    Legacy pae CLI (Phases 1–6 assessment history)
├── collector/                 Legacy collector framework
├── lib/
│   ├── forge-lib.sh           Core shell library (KeePass gate, helpers)
│   ├── forge-sync-lib.py      KeePass master→child DB sync (pykeepass)
│   ├── forge-onboarding-pdf.py  HTML onboarding package generator (TOTP QR codes)
│   └── forge-render-docs.sh   Architecture/doc → HTML renderer
├── proxmox-bootstrap/         Bootstrap Intelligence toolchain
│   ├── metadata/              AUTHORITATIVE infrastructure intent YAML
│   ├── snippets/              Cloud-Init user-data, network-config, vendor-data
│   ├── user_registry.py       User registry CLI + data model
│   ├── collect_tier2.py       Tier 2 SSH state collector library
│   ├── collect-tier2.py       CLI entry point for Tier 2 collection
│   └── TIER2-COLLECTION.md    Operator runbook for Tier 2 collection
├── scripts/
│   ├── forge-onboard-user.sh       Onboard user → credentials + HTML package
│   ├── forge-provision-users.sh    Re-provision all users into k8s services
│   ├── forge-throw-away-key.sh     Delete admin copy of credentials (zero-knowledge)
│   ├── forge-offboard-user.sh      Remove user from services + registry
│   └── forge-sync-credentials.sh  Sync credentials master→child KeePass DBs
├── tests/                     4000+ tests (unit + fixtures)
├── docs/
│   ├── USER-REGISTRY.md       User lifecycle, service adapter convention
│   ├── ARCHITECTURE.html      Rendered architecture (auto-generated from ARCHITECTURE.md)
│   └── ...                    Architecture reviews, session handoffs
├── reports/                   Generated documentation output
├── ARCHITECTURE.md            Current architecture summary (v7.2)
└── ROADMAP.md                 Full development roadmap (25 phases)
```

---

## Design Constraints

- **stdlib only** in all planners, generators, and validators — no pip dependencies
- **`cell_id` mandatory** on all schema documents (federation-readiness gate)
- **Metadata YAML files are never generated** — they are the authoritative source
- **Generated artifacts are never the source of truth** — always regenerate from metadata
- **`POPULATE:` markers** signal documentation gaps — never silently omit missing data
- **Filenames:** `YYYY-MM-DD_HH-MM_SS_TZ` (e.g. `2026-06-01_03-00_00_UTC`)
- **Document timestamps:** `YYYY-MM-DD HH:MM:SS UTC (HH:MM:SS TZ)`

---

## Design Principles

1. **Reconstruction is the objective.** Every state category, metadata field, and
   documentation artifact must answer: "Does this enable reconstruction from
   repository state after complete infrastructure loss?"

2. **Documentation captures intent, not just state.** Not "3 control-plane nodes"
   but "3 control-plane nodes because HA policy requires etcd quorum at ≥ 3 hosts."

3. **Missing information is surfaced, never silently omitted.** UNRESOLVED and STALE
   fields always appear with reason, impact, and remediation guidance.

4. **The Assessment Engine recommends; humans act.** No autonomous infrastructure
   action. Findings produce human-reviewable recommendations with severity and suggested
   remediation. Automation requires explicit governance review.

5. **Cell scope is universal.** `cell_id` in all schemas. Recovery playbooks organized
   by cell. The federation layer is added above, not retrofitted below.

6. **Failure drives improvement.** Every recovery script failure generates a structured
   failure package. Every failure package should produce a bootstrap repository commit
   that prevents that failure mode from recurring.

7. **Forging, spawning, and resurrection are all first-class operations.** Each
   produces a self-contained, auditable, checkpoint-resumable package. Forging
   builds the first hatchery from scratch. Spawning extends it with broodlings.
   Resurrection reconstitutes any node through the stargate. The result
   is the same class of auditable, checkpoint-based deployment artifact as the
   initial bootstrap.
