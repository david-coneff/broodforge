# metadata/ — Authoritative Infrastructure Intent

This directory is **Tier 1 of the source of truth hierarchy**.

## What these files are

These YAML files declare the *intent* of the infrastructure — what should exist,
why it should exist, and under which policies it was created. They are the input
that drives every generator, planner, and documentation artifact in the platform.

## What these files are NOT

- They are not generated artifacts. Never run a script that overwrites these files.
- They are not the observed state. Observed state comes from Proxmox and Kubernetes APIs.
- They are not documentation. Documentation is generated FROM these files.

## Governance rules

1. **Only human operators may commit to this directory.** No automated process
   writes to metadata/ except under explicit operator review.

2. **Changes trigger full regeneration.** A commit here triggers:
   - Documentation Engine regeneration
   - Assessment Engine reassessment
   - Recovery package regeneration
   This is by design — metadata is the source, everything else is derived.

3. **POPULATE: markers indicate required operator input.** Any field containing
   `POPULATE:` must be filled in before the platform is considered operational.
   The Assessment Engine flags POPULATE fields as documentation coverage gaps.

4. **All fields include a `reason:` or `policy:` annotation where non-obvious.**
   The v7.0 architecture requires intent-aware documentation. These annotations
   are the input to the intent layer.

## Files

| File | Purpose |
|---|---|
| `cell-identity.yaml` | Who this cell is — ID, federation, criticality, operator |
| `hardware-profile.yaml` | What hardware this cell requires and declares |
| `network-topology.yaml` | Management network, VLANs, bridges, DNS |
| `vm-roles.yaml` | Which VMs exist, their purpose, resource sizing |
| `k3s-cluster.yaml` | k3s topology, HA policy, node roles, storage class |
| `service-catalog.yaml` | Services running on the platform and their dependencies |
| `backup-policy.yaml` | RPO/RTO declarations per component |
| `recovery-priority.yaml` | Recovery wave ordering and HA requirements |
| `placement-policy.yaml` | VM placement and distribution policies |
| `naming-convention.yaml` | Naming rules for all platform resources |

## Validation

Validate all metadata files:
```bash
python3 proxmox-bootstrap/validate-metadata.py
```

Requires: PyYAML (`pip install pyyaml`)
