#!/usr/bin/env python3
"""
provenance.py — Deployment provenance registry for doc-gen.

Provides ProvenanceRegistry: a wrapper around provenance_records from
bootstrap-state.json that enables per-VM lookup of deployment history
(OpenTofu workspace, Ansible commit, Cloud-Init hashes, template used).
"""

from typing import Optional


class ProvenanceRegistry:
    """
    Wrapper around provenance_records for fast per-VM lookups.

    Records are keyed by vmid (int) and by name (str). Either lookup
    may be used; vmid is preferred when available since names can be
    renamed without changing the record.
    """

    def __init__(self, records: list):
        self._records = list(records or [])
        self._by_vmid: dict[int, dict] = {}
        self._by_name: dict[str, dict] = {}

        for r in self._records:
            vmid = r.get("vmid")
            if vmid is not None:
                try:
                    self._by_vmid[int(vmid)] = r
                except (TypeError, ValueError):
                    pass
            name = r.get("name")
            if name:
                self._by_name[name] = r

    def available(self) -> bool:
        return bool(self._records)

    def count(self) -> int:
        return len(self._records)

    def for_vmid(self, vmid) -> Optional[dict]:
        """Return the provenance record for a given vmid, or None."""
        try:
            return self._by_vmid.get(int(vmid))
        except (TypeError, ValueError):
            return None

    def for_name(self, name: str) -> Optional[dict]:
        """Return the provenance record for a given VM name, or None."""
        return self._by_name.get(name)

    def all(self) -> list:
        return list(self._records)

    def coverage(self, vmids: list) -> dict:
        """
        Return {vmid: record_or_None} for every vmid in the supplied list.
        Useful for identifying which VMs are missing provenance records.
        """
        result = {}
        for vmid in vmids:
            try:
                result[int(vmid)] = self._by_vmid.get(int(vmid))
            except (TypeError, ValueError):
                result[vmid] = None
        return result


def build_provenance_registry(manifest: dict) -> ProvenanceRegistry:
    """
    Build a ProvenanceRegistry from manifest["provenance_registry"].

    engine.py injects this key from bootstrap-state.json provenance_records.
    Returns an empty registry (available() == False) if the key is absent.
    """
    records = manifest.get("provenance_registry") or []
    return ProvenanceRegistry(records)
