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
