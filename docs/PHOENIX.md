# PHOENIX — Stargate Process Operator Runbook

**The stargate process** rebuilds a failed node back to its original identity on new
hardware. This runbook generates and executes a **phoenix package** end-to-end.
It is the recovery counterpart to `FORGING.md` (first node) and `NODE-SPAWNING.md`
(additional nodes).

Fill in the **Parameters** panel — every command on this page updates live, and each
**Copy** button copies the resolved command including your actual paths and values.

---

## Before you begin — collect identity information

Start here. These values are used throughout the runbook and auto-populate file names
and commands below. The node identity being restored must be known before generating
the phoenix package.

@field[Cell identifier or codename (e.g. cell-1 or flying-bat)]
@field[Node codename being restored (e.g. stargate-01)]
@credential[Node master password / KeePass database passphrase]

> **Codename convention:** Cells may use numeric IDs (`cell-1`) or
> adjective-animal codenames (`flying-bat`, `crouching-tiger`). Either form
> is valid — use whatever matches your `bootstrap-state.json`.

> **KeePass note:** The credential field above is stored in your browser session
> only — it is erased when you close this tab and is never included in the exported
> package. Use it as a scratch reference while you work, then ensure it is
> saved in your KeePass database.

---

## Working directory

All commands assume you are in the broodforge repo root. Set this once:

@dir[Broodforge repo root path]

```bash
cd {{broodforge-repo-root-path}}
```

---

## Step 1 — Generate the phoenix playbook from cell state

The playbook is the machine-readable reconstruction plan. Generate the base playbook
directly from `bootstrap-state.json`:

```bash
cd {{broodforge-repo-root-path}}
python3 proxmox-bootstrap/phoenix-planner.py \
  --state {{STATE=proxmox-bootstrap/bootstrap-state.json}} \
  --hardware {{HARDWARE=hardware-profile-replacement.json}} \
  --output {{PLAYBOOK=phoenix-playbook.json}}
```

Omit `--hardware` if you do not yet have a replacement hardware profile — the planner
will plan against the original topology and adapt at run time.

The planner prints the restoration scope and wave count. Record them:

@radio[Restoration scope|Full — all waves executed|Partial — specific waves only|Dry-run — plan only, no changes]
@field[Number of waves in the playbook]

---

## Step 2 — Assemble the phoenix package

To embed the KeePass database in the package for offline recovery, record the path here first:

@filename[KeePass database path (optional — leave blank to skip embedding)]

```bash
cd {{broodforge-repo-root-path}}
python3 proxmox-bootstrap/assemble-phoenix-package.py \
  --playbook {{PLAYBOOK=phoenix-playbook.json}} \
  --state {{STATE=proxmox-bootstrap/bootstrap-state.json}} \
  --kdbx {{KDBX=}} \
  --output-dir .
```

Omit `--kdbx {{KDBX=}}` if you left the KeePass path blank above.

The assembler prints the package path and its SHA-256. **Paste the full assembler
output into the field below** — the filename and hash will be extracted automatically.

@parse[Paste assembler output here — extracts package filename|Package written:\s*(\S+\.tar\.gz)|phoenix-package-filename]
@parse[Paste assembler output here — extracts SHA-256|SHA-256:\s*([0-9a-f]{64})|package-sha-256]

Then record (or override) the extracted values:

@filename[Phoenix package filename|PHOENIX_Cell-{{note:cell-identifier-or-codename}}_Node-{{note:node-codename-being-restored}}_{{STAMP}}]
@field[Package SHA-256]

---

## Step 3 — Copy to the replacement hardware and verify

@field[Replacement host hostname or label (for your records)]

```bash
cd {{broodforge-repo-root-path}}
scp {{note:phoenix-package-filename}} root@{{HATCHERY_IP=192.168.1.20}}:/root/
```

On the replacement host, verify integrity before extracting:

```bash
sha256sum /root/{{note:phoenix-package-filename}}
```

Compare the output against the SHA-256 recorded in Step 2.

@radio[Integrity check result|✓ Hashes match — proceed|✗ Hashes differ — do not proceed, re-copy package]

---

## Step 4 — Execute the waves

On the **replacement host**:

```bash
cd /root
tar xzf {{note:phoenix-package-filename}}
bash run-all.sh
```

`run-all.sh` sources the KeePass gate (one master-password prompt), then runs each
wave in order, checkpointing as it goes. If a wave fails, fix the cause and re-run
`bash run-all.sh` — completed waves are skipped automatically.

### Per-wave timing and observations

Record actual completion time and any deviations for each wave:

@table[Per-wave actual times and notes|Wave|Actual completion time|Deviations / observations](Wave 0 — Network reconstruction,Wave 1 — ZFS pool restore/create,Wave 2 — Proxmox host configuration,Wave 2.5 — Template rebuild (conditional),Wave 3 — VM restore from PBS,Wave 4 — k3s cluster membership,Wave 5 — Post-restore validation)

@radio[Overall wave execution result|✓ All waves completed on first run|↺ Some waves required retry — see table|✗ Execution halted — unresolved failure]
@field[Total execution time (wall clock)]

---

## Step 5 — Verify identity restored

```bash
qm list                          # original VMIDs present and running
kubectl get nodes                # restored node Ready under its ORIGINAL name
flux get kustomizations          # workloads reconciling
```

@radio[Restored node shows Ready under original hostname|✓ Yes — identity preserved|✗ No — identity mismatch, check k3s certs and /etc/hosts]
@field[Verified node name in kubectl output]

---

## If a wave fails

Every wave step failure writes a **failure package** (structured logs + a pre-composed
LLM analysis prompt). Attach it when asking for help, or feed it to an LLM to diagnose.
Fix the root cause, then resume with `bash run-all.sh`.

@check[Post-failure actions taken|Reviewed failure package logs|Identified root cause|Applied fix|Re-ran run-all.sh|Verified wave completed on retry]

---

## General notes

@area[Anything that did not fit the steps above — unexpected prompts, hardware quirks, manual interventions]

---

*Broodforge PHOENIX — Stargate Process | Use the ⬇ Export button to save this runbook record.*
