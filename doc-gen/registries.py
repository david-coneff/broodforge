#!/usr/bin/env python3
"""
registries.py — Registry loaders for doc-gen.

Provides SecretRegistry and DnsRegistry wrappers for fast lookups.
Data is sourced from manifest keys injected by engine.py (from bootstrap-state.json),
with fallback to standalone YAML files in proxmox-bootstrap/.
"""

from pathlib import Path
from typing import Optional

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ---------------------------------------------------------------------------
# SecretRegistry
# ---------------------------------------------------------------------------

class SecretRegistry:
    """Wrapper around the secret registry entries for fast lookups."""

    def __init__(self, secrets: list):
        self._secrets = list(secrets or [])
        self._by_id: dict[str, dict] = {}
        self._by_component: dict[str, list] = {}

        for s in self._secrets:
            sid = s.get("id")
            if sid:
                self._by_id[sid] = s
            for comp in s.get("required_by", []):
                self._by_component.setdefault(comp, []).append(s)

    def available(self) -> bool:
        return bool(self._secrets)

    def count(self) -> int:
        return len(self._secrets)

    def get(self, secret_id: str) -> Optional[dict]:
        return self._by_id.get(secret_id)

    def for_component(self, component_ref: str) -> list:
        return list(self._by_component.get(component_ref, []))

    def all(self) -> list:
        return list(self._secrets)

    def has_unresolved(self) -> bool:
        """True if any secret has a missing or placeholder KeePass path."""
        return any(
            not s.get("keepass_path") or "[HUMAN" in str(s.get("keepass_path") or "")
            for s in self._secrets
        )


# ---------------------------------------------------------------------------
# DnsRegistry
# ---------------------------------------------------------------------------

class DnsRegistry:
    """Wrapper around the DNS registry entries for fast lookups."""

    def __init__(self, entries: list):
        self._entries = list(entries or [])
        self._by_vmid: dict[int, dict] = {}
        self._by_hostname: dict[str, dict] = {}
        self._by_role: dict[str, list] = {}

        for e in self._entries:
            vmid = e.get("vmid")
            if vmid is not None:
                try:
                    self._by_vmid[int(vmid)] = e
                except (TypeError, ValueError):
                    pass

            fqdn = e.get("hostname", "")
            if fqdn:
                self._by_hostname[fqdn] = e
                # Also index by short name (strip domain suffix)
                short = fqdn.split(".")[0]
                if short and short not in self._by_hostname:
                    self._by_hostname[short] = e

            role = e.get("role")
            if role:
                self._by_role.setdefault(role, []).append(e)

    def available(self) -> bool:
        return bool(self._entries)

    def count(self) -> int:
        return len(self._entries)

    def ip_for_vmid(self, vmid) -> Optional[str]:
        try:
            entry = self._by_vmid.get(int(vmid))
        except (TypeError, ValueError):
            return None
        return entry.get("ip") if entry else None

    def ip_for_hostname(self, hostname: str) -> Optional[str]:
        entry = self._by_hostname.get(hostname)
        return entry.get("ip") if entry else None

    def entry_for_vmid(self, vmid) -> Optional[dict]:
        try:
            return self._by_vmid.get(int(vmid))
        except (TypeError, ValueError):
            return None

    def entries_for_role(self, role: str) -> list:
        return list(self._by_role.get(role, []))

    def all(self) -> list:
        return list(self._entries)

    def vm_ip_map(self) -> dict:
        """Return {vmid: ip} for all entries that have a vmid."""
        return {vmid: e["ip"] for vmid, e in self._by_vmid.items()}


# ---------------------------------------------------------------------------
# YAML loaders
# ---------------------------------------------------------------------------

def _parse_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if _HAS_YAML:
        return _yaml.safe_load(text) or {}
    raise ImportError(
        "PyYAML is required to load standalone YAML registry files. "
        "Install it (pip install pyyaml) or load registries from bootstrap-state.json instead."
    )


def load_secret_registry_from_yaml(path: Path) -> "SecretRegistry":
    """Load SecretRegistry from a standalone secret-registry.yaml file."""
    data = _parse_yaml(path)
    return SecretRegistry(data.get("secrets", []))


def load_dns_registry_from_yaml(path: Path) -> "DnsRegistry":
    """Load DnsRegistry from a standalone dns-registry.yaml file."""
    data = _parse_yaml(path)
    return DnsRegistry(data.get("dns_registry", []))


# ---------------------------------------------------------------------------
# Composite builder
# ---------------------------------------------------------------------------

def build_registries(manifest: dict, repo_root: Optional[Path] = None) -> tuple:
    """
    Build (SecretRegistry, DnsRegistry) from manifest keys or YAML fallback.

    Priority:
      1. manifest["secret_registry"] / manifest["dns_registry"] (injected from bootstrap-state.json)
      2. proxmox-bootstrap/secret-registry.yaml and dns-registry.yaml (if repo_root given)

    Either registry may be empty (.available() == False) if data is unavailable.
    """
    secrets_data = list(manifest.get("secret_registry") or [])
    dns_data = list(manifest.get("dns_registry") or [])

    if not secrets_data and repo_root is not None:
        yaml_path = repo_root / "proxmox-bootstrap" / "secret-registry.yaml"
        if yaml_path.exists():
            try:
                sr = load_secret_registry_from_yaml(yaml_path)
                secrets_data = sr.all()
            except Exception:
                pass

    if not dns_data and repo_root is not None:
        yaml_path = repo_root / "proxmox-bootstrap" / "dns-registry.yaml"
        if yaml_path.exists():
            try:
                dr = load_dns_registry_from_yaml(yaml_path)
                dns_data = dr.all()
            except Exception:
                pass

    return SecretRegistry(secrets_data), DnsRegistry(dns_data)
