#!/usr/bin/env python3
"""
platform_state_collector.py — Platform State Tier 2 collector (Phase 13.4).

Collects Proxmox platform software state from a host via SSH (or locally).
Produces a platform-state.json conforming to data-model/platform-state-schema.json.

Data collected:
  - Proxmox VE version, cluster name, quorum status
  - Kernel version (uname -r)
  - apt sources and pending updates
  - Key installed packages (proxmox-ve, k3s, headscale, etc.)
  - TLS certificates (Proxmox UI cert, broodforge certs)
  - systemd service status for key broodforge services
  - Config file fingerprints (SHA-256) for drift detection

Provides:
  PlatformStateDocument  — typed result
  collect_platform_state()   — main collection entry point
  compute_platform_health()  — aggregate health from document
  platform_state_to_dict()   — JSON-serialisable dict

Stdlib only.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from collector_utils import local_runner, RunnerFn  # noqa: F401


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PackageEntry:
    name:         str
    version:      Optional[str] = None
    architecture: Optional[str] = None
    source:       Optional[str] = None


@dataclass
class CertEntry:
    path:                str
    subject:             Optional[str]  = None
    issuer:              Optional[str]  = None
    sans:                list[str]      = field(default_factory=list)
    not_before:          Optional[str]  = None
    not_after:           Optional[str]  = None
    is_self_signed:      Optional[bool] = None
    fingerprint_sha256:  Optional[str]  = None
    auto_renew:          Optional[bool] = None
    renewal_tool:        Optional[str]  = None


@dataclass
class ServiceUnit:
    name:         str
    active:       Optional[bool] = None
    enabled:      Optional[bool] = None
    load_state:   Optional[str]  = None
    active_state: Optional[str]  = None
    sub_state:    Optional[str]  = None
    main_pid:     Optional[int]  = None


@dataclass
class PlatformStateDocument:
    cell_id:       str
    node_hostname: str
    collected_at:  str
    node_fqdn:     Optional[str]       = None
    proxmox_version: Optional[str]     = None
    proxmox_subscription: Optional[str] = None
    cluster_name:  Optional[str]       = None
    quorum_ok:     Optional[bool]      = None
    kernel_release: Optional[str]      = None
    kernel_machine: Optional[str]      = None
    pve_kernel:    Optional[bool]      = None
    packages:      list[PackageEntry]  = field(default_factory=list)
    certificates:  list[CertEntry]     = field(default_factory=list)
    services:      list[ServiceUnit]   = field(default_factory=list)
    config_fingerprints: dict[str, str] = field(default_factory=dict)
    apt_upgrades_available: Optional[int] = None
    apt_security_updates:   Optional[int] = None
    collection_errors: list[dict]      = field(default_factory=list)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_pve_version(output: str) -> Optional[str]:
    """Parse 'pveversion' or 'pveversion --verbose' output."""
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("pve-manager"):
            # e.g. "pve-manager/7.4-3/..."
            parts = line.split("/")
            if len(parts) >= 2:
                return parts[1]
        elif line.startswith("Proxmox"):
            return line
    return output.strip() or None


def _parse_dpkg_query(output: str) -> list[PackageEntry]:
    """Parse: dpkg-query -W -f='${Package}\t${Version}\t${Architecture}\n'"""
    packages = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            packages.append(PackageEntry(
                name=parts[0].strip(),
                version=parts[1].strip() if parts[1].strip() else None,
                architecture=parts[2].strip() if len(parts) > 2 else None,
            ))
    return packages


def _parse_systemctl_show(name: str, output: str) -> ServiceUnit:
    """Parse 'systemctl show {name}' output."""
    props: dict = {}
    for line in output.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            props[k] = v
    active = props.get("ActiveState") == "active"
    return ServiceUnit(
        name=name,
        active=active,
        enabled=props.get("UnitFileState") == "enabled",
        load_state=props.get("LoadState"),
        active_state=props.get("ActiveState"),
        sub_state=props.get("SubState"),
        main_pid=_int(props.get("MainPID")),
    )


def _parse_openssl_cert(path: str, output: str) -> CertEntry:
    """Parse 'openssl x509 -text -noout' output into a CertEntry."""
    cert = CertEntry(path=path)
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Subject:"):
            cert.subject = line.split(":", 1)[1].strip()
        elif line.startswith("Issuer:"):
            cert.issuer = line.split(":", 1)[1].strip()
        elif line.startswith("Not Before"):
            cert.not_before = line.split(":", 1)[1].strip()
        elif line.startswith("Not After"):
            cert.not_after = line.split(":", 1)[1].strip()
        elif "DNS:" in line:
            sans = re.findall(r"DNS:[^\s,]+", line)
            cert.sans = [s[4:] for s in sans]
    if cert.subject and cert.issuer:
        cert.is_self_signed = cert.subject == cert.issuer
    return cert


def _file_fingerprint(content: str) -> str:
    """SHA-256 hex digest of file content."""
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()


def _int(v: Any) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Platform health aggregation (Phase 13.7)
# ---------------------------------------------------------------------------

def compute_platform_health(doc: PlatformStateDocument) -> dict:
    """Derive platform_health dict from PlatformStateDocument."""
    from datetime import datetime, timezone

    # Certs expiring within 30 days
    now_ts = datetime.now(timezone.utc)
    expiring_soon = []
    for c in doc.certificates:
        if c.not_after:
            try:
                # Try parsing various date formats
                for fmt in ("%b %d %H:%M:%S %Y %Z", "%Y-%m-%dT%H:%M:%S%z"):
                    try:
                        exp = datetime.strptime(c.not_after, fmt)
                        if exp.tzinfo is None:
                            exp = exp.replace(tzinfo=timezone.utc)
                        days_left = (exp - now_ts).days
                        if days_left <= 30:
                            expiring_soon.append(c.path)
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

    # Failed services
    failed_services = [
        s.name for s in doc.services
        if s.active_state == "failed"
    ]

    # Overall status
    security_pending = (doc.apt_security_updates or 0) > 0
    if failed_services or (doc.apt_security_updates and doc.apt_security_updates > 5):
        overall = "DEGRADED"
    elif expiring_soon or security_pending:
        overall = "DEGRADED"
    else:
        overall = "HEALTHY"

    return {
        "overall_status":           overall,
        "security_updates_pending": security_pending,
        "certs_expiring_soon":      expiring_soon,
        "services_failed":          failed_services,
        "quorum_healthy":           doc.quorum_ok,
    }


# ---------------------------------------------------------------------------
# Key services and packages to check
# ---------------------------------------------------------------------------

_KEY_PACKAGES = [
    "proxmox-ve", "pve-manager", "pve-kernel-6.8",
    "k3s", "headscale", "dnsmasq", "certbot",
    "restic", "rclone", "keepassxc",
]

_KEY_SERVICES = [
    "pveproxy", "pvedaemon", "pvestatd",
    "dnsmasq", "headscale",
    "broodforge-ddns.timer", "broodforge-operational.timer",
]

_KEY_CERT_PATHS = [
    "/etc/pve/local/pve-ssl.pem",           # Proxmox UI cert
    "/etc/broodforge/ssl/fullchain.pem",    # Headscale / broodforge cert
]

_KEY_CONFIG_PATHS = [
    "/etc/network/interfaces",
    "/etc/pve/corosync.conf",
    "/etc/headscale/config.yaml",
    "/etc/dnsmasq.d/broodforge.conf",
]


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

def collect_platform_state(
    cell_id:   str,
    hostname:  str,
    fqdn:      Optional[str]    = None,
    runner_fn: Optional[RunnerFn] = None,
    now_fn:    Optional[Callable[[], str]] = None,
) -> PlatformStateDocument:
    """
    Collect platform state from the local host or via injectable runner.
    """
    runner = runner_fn or local_runner
    now    = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()

    doc = PlatformStateDocument(
        cell_id=cell_id,
        node_hostname=hostname,
        node_fqdn=fqdn,
        collected_at=now,
    )
    errors = []

    # Proxmox version
    try:
        out = runner("pveversion 2>/dev/null || pveversion --verbose 2>/dev/null || echo ''")
        doc.proxmox_version = _parse_pve_version(out)
    except Exception as e:
        errors.append({"component": "proxmox_version", "error": str(e)})

    # Kernel
    try:
        out = runner("uname -r").strip()
        doc.kernel_release = out or None
        doc.pve_kernel     = "pve" in (out or "").lower()
    except Exception as e:
        errors.append({"component": "kernel", "error": str(e)})

    # Key packages
    try:
        pkg_names = " ".join(_KEY_PACKAGES)
        out = runner(
            f"dpkg-query -W -f='${{Package}}\\t${{Version}}\\t${{Architecture}}\\n' "
            f"{pkg_names} 2>/dev/null || true"
        )
        doc.packages = _parse_dpkg_query(out)
    except Exception as e:
        errors.append({"component": "packages", "error": str(e)})

    # Key services
    for svc in _KEY_SERVICES:
        try:
            out = runner(f"systemctl show {svc} 2>/dev/null || true")
            if out.strip():
                doc.services.append(_parse_systemctl_show(svc, out))
        except Exception as e:
            errors.append({"component": f"service:{svc}", "error": str(e)})

    # Certificates
    for cert_path in _KEY_CERT_PATHS:
        try:
            out = runner(
                f"openssl x509 -text -noout -in {cert_path} 2>/dev/null || true"
            )
            if out.strip():
                cert = _parse_openssl_cert(cert_path, out)
                doc.certificates.append(cert)
        except Exception as e:
            errors.append({"component": f"cert:{cert_path}", "error": str(e)})

    # Config file fingerprints
    for cfg_path in _KEY_CONFIG_PATHS:
        try:
            content = runner(f"cat {cfg_path} 2>/dev/null || true")
            if content.strip():
                doc.config_fingerprints[cfg_path] = _file_fingerprint(content)
        except Exception as e:
            errors.append({"component": f"config:{cfg_path}", "error": str(e)})

    # apt updates
    try:
        out = runner(
            "apt-get -s upgrade 2>/dev/null | grep '^Inst' | wc -l || echo 0"
        )
        doc.apt_upgrades_available = _int(out.strip())
    except Exception:
        pass

    doc.collection_errors = errors
    return doc


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def platform_state_to_dict(doc: PlatformStateDocument) -> dict:
    """Convert PlatformStateDocument to a JSON-serialisable dict."""
    health = compute_platform_health(doc)
    return {
        "schema_version":  "1.0",
        "cell_id":         doc.cell_id,
        "node_hostname":   doc.node_hostname,
        "node_fqdn":       doc.node_fqdn,
        "collected_at":    doc.collected_at,
        "collection_errors": doc.collection_errors,
        "proxmox": {
            "version":         doc.proxmox_version,
            "subscription":    doc.proxmox_subscription,
            "cluster_name":    doc.cluster_name,
            "quorum_ok":       doc.quorum_ok,
        },
        "kernel": {
            "release":    doc.kernel_release,
            "pve_patched": doc.pve_kernel,
        },
        "apt": {
            "packages_upgraded_available": doc.apt_upgrades_available,
            "security_updates_available":  doc.apt_security_updates,
        },
        "installed_packages": [
            {"name": p.name, "version": p.version, "architecture": p.architecture}
            for p in doc.packages
        ],
        "certificates": [
            {
                "path":        c.path,
                "subject":     c.subject,
                "issuer":      c.issuer,
                "sans":        c.sans,
                "not_before":  c.not_before,
                "not_after":   c.not_after,
                "is_self_signed": c.is_self_signed,
            }
            for c in doc.certificates
        ],
        "systemd_services": [
            {
                "name":         s.name,
                "active":       s.active,
                "enabled":      s.enabled,
                "active_state": s.active_state,
                "sub_state":    s.sub_state,
            }
            for s in doc.services
        ],
        "config_fingerprints": dict(doc.config_fingerprints),
        "platform_health": health,
    }
