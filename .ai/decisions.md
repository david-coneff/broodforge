# Architecture Decisions

## AD-001: Two-tier assessment model
**Date:** 2026-05-30
**Decision:** Split assessment into Tier 1 (bootstrap, minimal deps) and Tier 2 (full engine).
**Rationale:** Tier 1 must run on unknown hardware with no tooling installed.
Conflating the two creates unnecessary complexity and dependency risk for the bootstrap case.

## AD-002: manifest.json as doc-gen contract
**Date:** 2026-05-30
**Decision:** The doc-gen layer reads only manifest.json, never raw collector files.
**Rationale:** Decouples collection format from documentation format.
Collector output format can change without breaking doc-gen.

## AD-003: UNRESOLVED is a first-class field state
**Date:** 2026-05-30
**Decision:** Missing data is always surfaced as UNRESOLVED with reason, collection guidance,
and readiness impact. Never silently omit.
**Rationale:** Silent gaps are worse than visible gaps. An operator who sees a blank field
may assume it doesn't matter. An UNRESOLVED field with impact rating forces a decision.

## AD-004: Workbook/runbook examples are style templates only
**Date:** 2026-05-30
**Decision:** The Stage 01-12 ODS/ODT files demonstrate structure and methodology but are
not final implementations. Generated documents will follow their structure but populate
fields from assessment data.
**Rationale:** The examples were manually authored. Treating them as authoritative would
perpetuate manual documentation maintenance.

## AD-005: Historical snapshot reproducibility is a hard requirement
**Date:** 2026-05-30
**Decision:** Any historical snapshot must regenerate the documentation current at that time.
**Rationale:** Recovery documentation must be trustworthy. If we cannot reproduce what we
said the infrastructure looked like at a given point, we cannot trust the documentation.

## AD-006: Cloud-Init elevated to first-class Bootstrap State
**Date:** 2026-05-30
**Decision:** Cloud-Init user-data, network-config, and snippets are tracked in a
dedicated Bootstrap State repository as versioned, hash-verified managed assets.
**Rationale:** Without Cloud-Init metadata in repository state, first-boot provisioning
cannot be replayed during reconstruction. The provisioning gap is the primary obstacle
to automated disaster recovery.

## AD-007: Service Contracts replace heuristics as primary dependency source
**Date:** 2026-05-30
**Decision:** Declared Service Contracts (YAML files per service) are the primary source
of dependency graph edges. Name-pattern heuristics are retained as a fallback only.
**Rationale:** Heuristics based on VM name patterns are unreliable for novel service
names and produce incorrect restore sequences. Declared contracts are authoritative.

## AD-008: Secret Registry tracks references, never values
**Date:** 2026-05-30
**Decision:** The Secret Registry is a YAML file in the Bootstrap State repository that
maps secret identifiers to KeePass paths. It never contains secret values.
**Rationale:** Enables automated gap detection and pre-populated recovery steps
(operator knows exactly which KeePass entry to open) without creating a secret-in-repo
security risk.

## AD-009: DNS Registry eliminates [VM_IP] placeholders
**Date:** 2026-05-30
**Decision:** A DNS Registry maps hostnames to IPs for all VMs. Doc-gen reads the
registry and pre-populates commands with actual IP addresses.
**Rationale:** `[VM_IP]` placeholders require operator lookup during recovery, which
adds time and creates opportunities for error. Known values should always be pre-filled.

## AD-010: Three documentation classes (bootstrap, operational, recovery)
**Date:** 2026-05-30
**Decision:** Documentation is produced in three independent classes from the same
metadata model: Bootstrap (construction), Operational (administration), Recovery
(reconstruction). Previously only Bootstrap and Recovery existed.
**Rationale:** Operational documentation is a distinct use case (running environment
administration) that cannot be served by either bootstrap or recovery documentation.
Drift summaries and capacity trends have no place in a recovery runbook.

## AD-011: Deployment Provenance Records enable reproducible reconstruction
**Date:** 2026-05-30
**Decision:** Each VM deployment creates a Provenance Record capturing: tofu workspace
commit, cloud-init snippet hashes, ansible playbook commit, ansible inventory commit,
base template checksum, deployment timestamp and operator.
**Rationale:** Without a build receipt, reconstruction cannot be validated as equivalent
to the original deployment. Provenance records are the "replay tape" for automation.

## AD-012: Reconstruction Playbooks are generated artifacts
**Date:** 2026-05-30
**Decision:** Reconstruction Playbooks (executable shell scripts for full-destroy
reconstruction) are generated from the state model, not manually authored.
**Rationale:** Manually authored reconstruction scripts diverge from actual state.
Generated scripts are always consistent with the current state model.
