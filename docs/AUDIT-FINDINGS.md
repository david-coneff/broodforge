# Broodforge Audit Findings — Documented Steps vs. Implementation

**Single, continuously-revised audit log.** Each analysis cycle appends a section
with a timestamp (`YYYY-MM-DD_HH_MM_SS` UTC). Findings are marked **[FIXED]**,
**[OUTSTANDING]**, or **[DOCUMENTED]** (a real gap that is now honestly described in
the operator docs rather than silently broken). Nothing is deleted — this is a
trailing history.

---

## Audit cycle — 2026-06-04_12_37_46 UTC

### Method

Cross-referenced **every documented user-guide step** against the implemented software:

1. **Script existence** — every `python3 …py` command in all docs resolves to a real file.
2. **CLI functionality** — every referenced CLI runs (`--help` probe).
3. **Flag-level (import-aware)** — every `--flag` used in a documented command is
   implemented in the target script *or a module it delegates to* (the hyphen-CLI →
   underscore-module wrapper pattern is followed).
4. **Subcommands** — `reconstruction-drill.py` (start/complete/last/report) and
   `remediation-cli.py` (list/approve/approve-all/reject/dry-run/history/status/
   enable-autonomous/disable-autonomous) match their docs.
5. **`bash *.sh` references** — all exist (forge.sh/spawn.sh/run-all.sh are generated
   at package-assembly time; schedule-reconstruction-drill.sh exists).

### Result of automated cross-reference

- Script existence: **0 missing.**
- Flag-level mismatches: **0.**
- Subcommand / bash-script references: **0 missing.**

The automated documented-command surface is **clean**. The remaining findings below
are *implementation* gaps where `forge.sh` invokes a tool that does not yet do its job
— surfaced by deep execution tracing, not by flag matching.

### Findings this cycle

| # | Area | Finding | Status |
|---|---|---|---|
| F1 | forge phase-03 | `setup_dnsmasq.py` was library-only (no CLI); phase-03 invoked it → **no-op** | **[FIXED]** — added `_cli_main` (`--manifest`/`--state` + `--dns-registry` + `--output`); writes the dnsmasq conf |
| F2 | forge phase-03 | `setup_headscale.py` was library-only (no CLI); phase-03 → **no-op** | **[FIXED]** — added CLI; writes `config.yaml` + systemd unit; `--run` prints init commands |
| F3 | forge phase-03 | `setup_tls.py` was library-only (no CLI); phase-03 → **no-op** | **[FIXED]** — added CLI; writes `sync-cert-to-k8s.sh`; prints/executes (`--run`) issuance commands |
| F6 | forge phase-03 | **Uncovered while verifying F1:** `generate_dnsmasq_config()` read `entry.get("fqdn")` but `dns-registry.yaml` uses `hostname` → the rendered config had **zero host mappings** | **[FIXED]** — now reads `hostname` (backward-compatible with `fqdn`) |
| F4 | forge phase-04 | No `opentofu/` modules exist; phase-04 self-skips VM provisioning | **[DOCUMENTED]** deploy-to-hardware milestone (FORGING status table) |
| F5 | forge phase-05 | `ansible/inventory/hosts.yaml` not generated end-to-end; phase-05 self-skips | **[DOCUMENTED]** deploy-to-hardware milestone (FORGING status table) |

### Fix attempt + re-audit result

**Attempt 1 — all targeted findings resolved on the first pass; no second round required.**

Re-audit verification (each confirmed against the *original* problem):
- **F1/F2/F3** — `--help` now prints usage for all three; each run exits 0 and **writes a
  real config file** with a synthetic manifest (dnsmasq `.conf`, headscale `config.yaml` +
  unit, TLS `sync-cert-to-k8s.sh`) — no longer no-ops.
- **F6** — `generate_dnsmasq_config()` with real `hostname`-keyed registry entries now
  produces 2/2 address mappings and detects the hatchery (was 0). 139 dnsmasq/headscale/
  tls/network tests pass; full suite **4000 passed, 1 skipped**.
- The import-aware flag cross-reference remains **0 mismatches**, and the Cycle-7
  empty-`--help` set (`setup_dnsmasq/headscale/tls`) now all report usage.

**F4/F5** remain genuine deploy-to-hardware implementation milestones (OpenTofu VM
modules + end-to-end Ansible inventory generation), honestly documented in
`proxmox-bootstrap/FORGING.md`'s phase-by-phase status table — a user following the docs
is told these are manual today, so they are not *hidden* broken steps.

---

## Audit cycle — 2026-06-04_13_01_48 UTC

### Method

Deep **content** verification of the config generators wired in the previous cycle
(F1–F3) — not just "does the CLI write a file", but "is the generated config correct".
This surfaced the same *field/value-mismatch* class as F6.

### Findings

| # | Area | Finding | Status |
|---|---|---|---|
| G1 | forge phase-03 TLS | `generate_tls_config()` stores `ssl_provider` verbatim, but `setup_network.py` writes it as **`certbot-cloudflare`** / **`acme.sh-duckdns`** while `TlsProvider` constants are `certbot` / `acme.sh`. So `render_tls_commands()` never matches → falls through to a **no-op (no certificate issued)** for every real provider value. Only the bare `certbot` worked. | **[FIXED]** — normalize the provider to the `TlsProvider` constants before matching |
| G2 | forge phase-03 TLS | `acme_email` is read from `wan_config.acme_email` but is **written nowhere** in the codebase → certbot always uses `--register-unsafely-without-email`. Functional (cert still issues) but suboptimal. | **[FIXED]** — also read top-level `acme_email`; behavior still valid when absent |
| G3 | forge phase-03 Headscale | `dns_base_domain = brood.{tld}` → **`brood.com`** for `home.example.com` — a registrable domain the operator does **not** own, used as the MagicDNS base. | **[FIXED]** — derive from the operator's own domain (`brood.{domain}`) |

### Fix attempt + re-audit result

**Attempt 1 — all three resolved; no second round required.** Re-audited each against
the original problem:
- **G1** — `certbot-cloudflare`→`certbot` (13 cmds), `acme.sh-duckdns`→`acme.sh` (6 cmds),
  `cloudflare`/`duckdns` likewise, `self-signed` (4 cmds); `none` correctly stays a 1-line
  no-op. Previously every real value produced the 1-line no-op.
- **G2** — top-level `acme_email` now flows into the cert config.
- **G3** — `dns_base_domain` = `brood.home.example.com` (operator-owned subdomain).

290 tls/headscale/network tests pass; full suite **4000 passed, 1 skipped**.

---

## Audit cycle — 2026-06-04_13_07_34 UTC

### Method

Systematic **field-location** cross-reference: which `network_topology` keys
`setup_network.py` *writes* vs. which keys each `generate_*_config()` *reads*. (The
F6/G1/G3 bugs were all writer-puts-here / reader-looks-there mismatches.)

### Findings

| # | Area | Finding | Status |
|---|---|---|---|
| G4 | DDNS | `setup_network.wan_config_to_state()` writes `ddns_provider`/`ddns_zone`/`ddns_record`/`ddns_credential_reference` at the **top level** of `network_topology`, but `generate_ddns_config()` read only `wan_config.ddns_*` → produced **`provider: none`** (DDNS silently not configured) even when the operator selected Cloudflare/DuckDNS. | **[FIXED]** — read ddns_* from `wan_config` *or* top level |
| G5 | Headscale | `generate_headscale_config()` read `wan_config.headscale_url`, but `setup_network` writes `headscale_url` at the top level → fell back to the FQDN-derived URL (same value here, but ignored the stored one). | **[FIXED]** — read `headscale_url` from `wan_config` *or* top level |

### Fix attempt + re-audit result

**Attempt 1 — both resolved; no second round.** Fed `setup_network.wan_config_to_state()`
output (cloudflare WAN) straight into the generators:
- **G4** — `generate_ddns_config` now returns `provider: cloudflare` (was `none`).
- **G5** — `generate_headscale_config` now uses the stored `headscale_url`.

122 ddns/headscale/network tests pass; full suite **4000 passed, 1 skipped**.

> Lower-impact, left as-is (graceful fallback, not broken): `setup_tls` reads
> `wan_config.cloudflare_token_keepass_path` while `setup_network` stores the credential
> as `dns_provider_credential_reference` — the rendered certbot command takes the token
> from `$CLOUDFLARE_API_TOKEN` (env) regardless, so cert issuance is unaffected.

---

## Audit cycle — 2026-06-04_13_16_16 UTC

### Method

Extended the field-location audit to the **documentation readers** of `network_topology`
(doc-gen renderers), not just the config generators.

### Findings

| # | Area | Finding | Status |
|---|---|---|---|
| G6 | bootstrap docs | `doc-gen/renderers/html_bootstrap.py` read `wan_config.headscale_url`, but `setup_network` writes `headscale_url` at the **top level** → the generated bootstrap **workbook** showed a blank Headscale URL and the bootstrap **runbook** skipped its "Headscale running" checklist item, even on a WAN cell. | **[FIXED]** — read `headscale_url` (and `ddns_provider`/`ssl_provider`) from `wan_config` *or* top level, in both the workbook overview and the runbook host-config section |

### Fix attempt + re-audit result

**Attempt 1 — resolved.** Note: there are **two** active builders — `build_bootstrap_workbook_html`
(overview table) and `build_bootstrap_runbook_html` (Stage-03 host-config checklist) — both
called by `engine.py`. Verified each separately with a `setup_network`-style state (top-level
`headscale_url`):
- **Workbook** overview now shows the Headscale URL (was blank).
- **Runbook** host-config now includes the "Headscale running" checklist item (was skipped).

256 bootstrap tests pass; full suite **4000 passed, 1 skipped**.

---

## Audit cycle — 2026-06-04_13_20_46 UTC

### Method

**Comprehensive sweep** for the whole bug class (rather than one-at-a-time): grepped every
reader of a `setup_network`-top-level key (`headscale_url`, `ddns_*`, `ssl_*`) that reads it
from `wan_config`, across all of `proxmox-bootstrap/` and `doc-gen/`.

### Findings (one cluster, G7)

| Reader | Impact | Status |
|---|---|---|
| `spawn_planner.py` (spawn-manifest `hatchery.headscale_url`) | **HIGH** — a WAN **spawn package** would embed an empty Headscale URL, so the broodling could not join the tailnet | **[FIXED]** |
| `spawn-planner.py` (network-mode prompt default) | MED | **[FIXED]** |
| `twin_state_writer.py` (`headscale_url` in twin state) | MED — propagates the blank into derived state | **[FIXED]** |
| `setup_tls.py` (ddns-provider fallback for TLS derivation) | LOW (ssl_provider read first) | **[FIXED]** |
| `html_forge_workbook.py` (Headscale URL / providers + checklist) | LOW–MED (forge workbook display) | **[FIXED]** |

All now read the key from `wan_config` **or** the top level (matching G4/G5/G6).

Left as-is (correct): `forge_planner.py` reads `headscale_url` from the `wan_config` it
*itself* builds during forge planning — internally consistent, not a cross-writer mismatch.

### Fix attempt + re-audit result

**Attempt 1 — resolved.** Re-grep confirms all five sites now use the read-both pattern; the
sweep returns no remaining `wan_config`-only reads of top-level keys. Full suite **4000
passed, 1 skipped**. (Same fix shape as G4/G5/G6, which were verified functionally.)

> This closes the recurring **field-location** class (F6 dnsmasq, G1 TLS provider value,
> G3 Headscale base, G4 DDNS, G5/G6/G7 headscale_url): writers split fields between
> top-level `network_topology` and nested `wan_config`; readers now accept either.

---

## Audit cycle — 2026-06-04_13_25_31 UTC

### Method

Different class: **secret/value flow** through the spawn pipeline (not network fields).
Traced the k3s join token from the hatchery state → spawn package → generated Ansible vars.

### Findings

| # | Area | Finding | Status |
|---|---|---|---|
| G8 | spawn k3s join | `build_spawn_plan()` put only the k3s **token KeePass paths** (`worker_token_path`) in `plan["k3s"]`, but `generate_ansible_k3s_vars()` reads token **values** (`worker_join_token`). With no value present it emitted `k3s_token: '{{ vault_k3s_worker_token }}'` — an unresolved Ansible-vault placeholder that **nothing fills** (no broker/runtime substitution exists). The broodling's k3s join would use that literal string and **fail**. | **[FIXED]** |

### Fix + re-audit result

The README documents k3s join tokens as the **one secret the spawn package carries**
(embedded in the spawn manifest, valid only during the spawn window, rotated after the
broodling joins). So the documented-model fix is to carry the real token: `build_spawn_plan`
now copies `worker_join_token`/`server_join_token` from the hatchery's `bootstrap_state["k3s"]`
into `plan["k3s"]` (keeping the `*_token_path` references too). Verified: `generate_ansible_k3s_vars`
now emits the real token for both worker and server roles, with no `{{ vault_… }}` placeholder.
Full suite **4000 passed, 1 skipped**.

> **Security note for the operator (design decision):** this fix follows the *documented*
> model (token in the package, short-lived, rotated post-join). The alternative — resolve the
> token from KeePass at runtime via the secrets broker (the `*_token_path` references hint at
> this) — would keep the token out of `spawn-plan.json` entirely. That is a more secure design
> but requires a runtime resolver that does not exist yet. **Flagged for your call**; the
> current fix makes the documented flow actually work. (Related: cycle-1 A1 redacts these same
> tokens from the unauthenticated dashboard endpoint.)

---

## Audit cycle — 2026-06-04_13_29_26 UTC

### Method

Traced the **spawn-completion** contract: phase-06 POSTs `{spawn_plan, hardware_profile}`
→ `build_spawn_result(spawn_plan)` → `update_state_after_spawn`. Cross-referenced every
field `build_spawn_result` reads against what `build_spawn_plan` actually writes.

### Findings

| # | Area | Finding | Status |
|---|---|---|---|
| G9 | spawn-complete DNS | `update_state_after_spawn` documents "adds hostname→IP entries for broodling + its VMs" and iterates `result.dns_entries`, but `build_spawn_result` set `dns_entries = spawn_plan.get("dns_entries")` — a key the planner **never writes** → always `[]`, so **no DNS entries were registered after a spawn** (broodling + VMs unresolvable by name). | **[FIXED]** — derive `dns_entries` from the broodling host + its VMs when absent |

Checked and **OK** (no fix needed): `vmid_block`/`ip_block` already fall back to deriving
from `vms[]`; `tailnet_ip` absent is correct (assigned only after the broodling joins the
tailnet); `domain`/`package_id` are written by the planner.

### Fix + re-audit result

`build_spawn_result` now derives `dns_entries` from `spawn_plan["lan_ip"]` (the broodling
host) and each `vms[].ip` (with fqdn from the VM name + domain), matching the existing
vmid/ip derivation. Verified end-to-end: a plan with 2 VMs yields 3 dns entries
(broodling + 2 VMs) and `update_state_after_spawn` registers all three IPs into
`dns_registry`. 451 spawn/update/receiver tests pass; full suite **4000 passed, 1 skipped**.

---

## Audit cycle — 2026-06-04_13_31_51 UTC — FIRST CLEAN PASS

### Method (deep + even-deeper)

Symptom-based content scans of the pipelines not yet content-checked, plus one more
contract trace:

1. **Phoenix wave content** — built a playbook from the fixture state; scanned all 64
   step commands across 6 waves for placeholders / empties (`{{…}}`, `[VM_IP]`, `None`,
   `POPULATE`).
2. **Spawn IaC content** — generated tfvars, both cloud-init snippets, the Ansible
   inventory, and the k3s group_vars; scanned for unresolved placeholders and missing
   critical values (VM IP, VMID, k3s token).
3. **Backup contract** — cross-referenced the `backup_config` keys `setup-backup.py`
   writes vs. those `run-backup.py` / `restore-from-backup.py` read.

### Result

- **Phoenix waves: clean** — real VMIDs (100/101/102/103/9000) in `qm` commands, no
  placeholders.
- **Spawn IaC: clean** — tfvars carries `vmid=241`, `ip=192.168.1.41/24`; the k3s
  group_vars now carries the real join token (G8 fix); inventory + cloud-init populated.
- **Backup contract: coherent** — readers read only keys the writer produces; no
  field-name/location mismatch.

**No new findings.** This is the first cycle where both a deepthink pass and an
even-deeper pass surface zero issues — the stopping condition.

### Caveat

The structured audits (documented commands, CLI flags, network-field locations, secret
flow, spawn/phoenix/backup content) are now clean. This does **not** prove the absence of
deeper logic bugs or anything that only appears on real Proxmox hardware — those remain
`user-tested`-pending (see `FEATURE-HISTORY.md`). Full suite throughout: **4000 passed,
1 skipped**.

---

## Trailing history of fixes (cycles 1–7, this session)

All verified by re-audit and the pytest suite (4000 passed, 1 skipped) at the time.

| Finding | Resolution | Status |
|---|---|---|
| Forge package shipped without its library code (`--repo` optional, docs omit it) → phase-00 fails | Assembler infers repo root by default; verified bundles 95 tools + 26 schemas + 78 doc-gen | **[FIXED]** |
| Dashboard `/api/state` (unauth) leaked k3s join tokens from bootstrap-state.json | `_redact_secrets()` on all unauth GET endpoints | **[FIXED]** |
| Spawn pre-flight `validate-spawn.py` referenced but never bundled (silent skip) | New `validate-spawn.py` CLI + closure bundled | **[FIXED]** |
| Forge IaC: `ansible/` + `generators/` not bundled; phase-05 referenced wrong filenames | Bundle both; fix phase-05 paths; honest status note | **[FIXED]** |
| Stargate workflow had no playbook-generation entry point | `phoenix-planner.py --state` now generates; new `docs/PHOENIX.md` | **[FIXED]** |
| `engine.py` invoked with unsupported `--state`/`--output` (forge phase-07) | Switched to `--manifest` | **[FIXED]** |
| `engine.py --set-timezone` documented (AD-045) but unimplemented | Implemented `--set-timezone TZ` | **[FIXED]** |
| `spawn_hardware_discovery.py` (NODE-SPAWNING step 1) had no CLI; password auth dead | Added CLI + `sshpass` password auth (no argv leak) | **[FIXED]** |
| `setup_ddns.py` library invoked as CLI by forge + docs; `setup-ddns.py` filename wrong | Real CLI (both forms); fixed all references | **[FIXED]** |
| `init-bootstrap-state.py` (forge phase-07) ignored `--manifest`, would hang interactively | `--manifest` seeds state non-interactively; phase-07 passes `--non-interactive` | **[FIXED]** |
| Stale spawn/phoenix phase names, test counts, broken doc links, "Forgability" spelling | Corrected across README/ROADMAP/FORGING/ARCHITECTURE | **[FIXED]** |
