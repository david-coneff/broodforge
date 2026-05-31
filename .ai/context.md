# Project AI Context

## What this project is

A Proxmox infrastructure assessment engine that generates bootstrap, operational, and
recovery documentation from observed infrastructure state. Documentation is a generated
artifact. Recovery procedures are derived from structured state.

Primary objective: complete destroy-and-recreate reconstruction from repository state.

## Architecture version

v4.0 — see ARCHITECTURE.md and docs/ARCHITECTURE-REVIEW-v4.md.

Seven-state model: Declared, Bootstrap, Configured, Service, Observed, Historical, Recovery.
Six-layer lifecycle: Definition → Provisioning → Configuration → Service → Assessment → Documentation.

Cloud-Init is a first-class Bootstrap State asset, not an afterthought.

## Current milestone

**Milestone 5.6 — Historical State Integration** (next to implement)

See docs/SESSION-HANDOFF.md for exact starting point and step-by-step plan.

## What is complete (90 tests passing)

- Five JSON schemas with stdlib-only validator
- Tier 1 bootstrap assessment (bootstrap.sh + modular collectors + analyze.py)
- Bootstrap documentation generator → ODS workbook + ODT runbook
- Recovery documentation generator → ODS workbook + ODT runbook + Readiness-Report.md
- Dependency graph builder with topological sort (Kahn's algorithm)
- Recovery readiness scorer (GREEN/YELLOW/ORANGE/RED/BLOCKED with cascade propagation)
- Standalone readiness report (Readiness-Report.json + .md)

## Key design decisions

- manifest.json is the contract between assessment layer and doc-gen layer
- doc-gen never reads raw collector files directly
- Field classification: AUTO / DERIVED / HUMAN / UNRESOLVED
- UNRESOLVED fields are never silently omitted (reason + guidance + impact always present)
- All ODS/ODT generation uses zipfile + XML (stdlib only, no odfpy)
- Tier 1 assessment uses Python 3 stdlib only (no pip installs)
- Historical snapshots must be reproducible (same manifest → same docs)
- Service Contracts replace heuristics as primary dependency source (Phase 7)
- Secret Registry tracks KeePass path references, never secret values (Phase 6)
- DNS Registry eliminates [VM_IP] placeholders in recovery docs (Phase 6)

## Observe → Decide → Act → Record → Validate

All generated documentation follows this methodology.
