#!/usr/bin/env python3
"""
cert_manager.py — Certificate Lifecycle Management (Phase 2.B).

Manages TLS certificate lifecycle for broodforge's Kubernetes cluster:
  - cert-manager Helm values.yaml generation
  - Certificate record registry (domain → issuer → expiry)
  - Expiry alerting thresholds (WARNING ≤30d, CRITICAL ≤7d)
  - ClusterIssuer spec generation (ACME / Let's Encrypt + self-signed)
  - Certificate renewal status tracking
  - Integration with forge-rotate-credential.sh via _rotate_tls_cert()

PAP constraints:
  - No bare datetime.now() — now_fn injected throughout
  - All subprocess calls: timeout=_SUBPROCESS_TIMEOUT
  - No credentials in env, argv, or logs
  - KeePass gate in the shell layer; this module never opens a kdbx

State file: {STATE_DIR}/cert-manager-state.json
Values file: generated to {STATE_DIR}/cert-manager-values.yaml (operator-managed, not in VCS)

CLI:
  python3 cert_manager.py --generate-values --output <file>
  python3 cert_manager.py --register-cert --domain <domain> --issuer <name>
      --secret-name <k8s-secret> [--namespace <ns>] [--san <domain,...>]
  python3 cert_manager.py --record-renewal --domain <domain> --expires <ISO-date>
  python3 cert_manager.py --list [--json] [--critical] [--warning]
  python3 cert_manager.py --status [--json]
  python3 cert_manager.py --generate-issuer --issuer <name> --type <acme|selfsigned>
      [--email <email>] [--server <url>] [--output <file>]

Exit codes:
  0 — success
  1 — error
  2 — NOT_IMPLEMENTED (cert-manager not deployed)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SUBPROCESS_TIMEOUT = 300  # seconds

STATE_FILENAME = "cert-manager-state.json"
VALUES_FILENAME = "cert-manager-values.yaml"
DEFAULT_STATE_DIR = os.environ.get("BROODFORGE_STATE_DIR", "/var/lib/broodforge")
DEFAULT_NAMESPACE = "cert-manager"
DEFAULT_HELM_RELEASE = "cert-manager"
DEFAULT_CHART = "jetstack/cert-manager"
DEFAULT_CHART_VERSION = "v1.14.4"
DEFAULT_ACME_SERVER = "https://acme-v02.api.letsencrypt.org/directory"
DEFAULT_ACME_STAGING_SERVER = "https://acme-staging-v02.api.letsencrypt.org/directory"

# Expiry thresholds (days)
EXPIRY_CRITICAL_DAYS = 7
EXPIRY_WARNING_DAYS = 30


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CertRecord:
    """A tracked TLS certificate."""
    domain: str                   # Primary domain (CN)
    issuer_name: str              # Name of the ClusterIssuer
    issuer_type: str              # acme | selfsigned | ca
    secret_name: str              # Kubernetes secret holding the cert
    namespace: str                # Kubernetes namespace
    san_domains: List[str]        # Subject Alternative Names (excluding primary)
    registered_at: str            # ISO-8601 UTC
    expires_at: Optional[str]     # ISO-8601 UTC, None = not yet known
    last_renewed_at: Optional[str]  # ISO-8601 UTC
    renewal_count: int
    status: str                   # active | expired | revoked | pending

    @classmethod
    def new(
        cls,
        domain: str,
        issuer_name: str,
        issuer_type: str,
        secret_name: str,
        namespace: str = "default",
        san_domains: Optional[List[str]] = None,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> "CertRecord":
        ts = now_fn().isoformat()
        return cls(
            domain=domain,
            issuer_name=issuer_name,
            issuer_type=issuer_type,
            secret_name=secret_name,
            namespace=namespace,
            san_domains=san_domains or [],
            registered_at=ts,
            expires_at=None,
            last_renewed_at=None,
            renewal_count=0,
            status="pending",
        )


@dataclass
class CertManagerState:
    """Persisted cert-manager state."""
    schema_version: str = "1.0"
    helm_release: str = DEFAULT_HELM_RELEASE
    helm_namespace: str = DEFAULT_NAMESPACE
    chart_version: str = DEFAULT_CHART_VERSION
    deployed_at: Optional[str] = None
    certificates: List[CertRecord] = field(default_factory=list)
    issuers: List[dict] = field(default_factory=list)   # raw issuer metadata

    def find_cert(self, domain: str) -> Optional[CertRecord]:
        for c in self.certificates:
            if c.domain == domain:
                return c
        return None


# ---------------------------------------------------------------------------
# Expiry helpers
# ---------------------------------------------------------------------------

def _days_until_expiry(
    cert: CertRecord,
    now_fn: Callable[[], datetime],
) -> Optional[int]:
    """Return days until expiry, or None if expires_at not set."""
    if not cert.expires_at:
        return None
    expires = datetime.fromisoformat(cert.expires_at)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    delta = expires - now_fn()
    return int(delta.total_seconds() / 86400)


def cert_expiry_status(
    cert: CertRecord,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> str:
    """Return 'critical', 'warning', 'ok', or 'unknown'."""
    days = _days_until_expiry(cert, now_fn)
    if days is None:
        return "unknown"
    if days <= EXPIRY_CRITICAL_DAYS:
        return "critical"
    if days <= EXPIRY_WARNING_DAYS:
        return "warning"
    return "ok"


# ---------------------------------------------------------------------------
# State I/O (atomic write)
# ---------------------------------------------------------------------------

def _state_path(state_dir: str) -> Path:
    return Path(state_dir) / STATE_FILENAME


def load_state(state_dir: str) -> CertManagerState:
    p = _state_path(state_dir)
    if not p.exists():
        return CertManagerState()
    with open(p) as fh:
        raw = json.load(fh)
    certs = [CertRecord(**c) for c in raw.get("certificates", [])]
    return CertManagerState(
        schema_version=raw.get("schema_version", "1.0"),
        helm_release=raw.get("helm_release", DEFAULT_HELM_RELEASE),
        helm_namespace=raw.get("helm_namespace", DEFAULT_NAMESPACE),
        chart_version=raw.get("chart_version", DEFAULT_CHART_VERSION),
        deployed_at=raw.get("deployed_at"),
        certificates=certs,
        issuers=raw.get("issuers", []),
    )


def save_state(state: CertManagerState, state_dir: str) -> None:
    p = _state_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    payload = {
        "schema_version": state.schema_version,
        "helm_release": state.helm_release,
        "helm_namespace": state.helm_namespace,
        "chart_version": state.chart_version,
        "deployed_at": state.deployed_at,
        "certificates": [asdict(c) for c in state.certificates],
        "issuers": state.issuers,
    }
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=2)
    tmp.replace(p)


# ---------------------------------------------------------------------------
# Helm values generation
# ---------------------------------------------------------------------------

def generate_values_yaml(
    namespace: str = DEFAULT_NAMESPACE,
    install_crds: bool = True,
    replicas: int = 1,
    prometheus_enabled: bool = True,
) -> str:
    """Generate a cert-manager Helm values.yaml."""
    lines = [
        "# cert-manager Helm values — generated by broodforge cert_manager.py",
        "# Do not edit manually; regenerate with forge-init-cert-manager.sh",
        "",
        f"installCRDs: {'true' if install_crds else 'false'}",
        "",
        "replicaCount: {}".format(replicas),
        "",
        "prometheus:",
        "  enabled: {}".format("true" if prometheus_enabled else "false"),
        "  servicemonitor:",
        "    enabled: {}".format("true" if prometheus_enabled else "false"),
        "",
        "# Webhook and cainjector replicas follow controller",
        "webhook:",
        "  replicaCount: {}".format(replicas),
        "",
        "cainjector:",
        "  replicaCount: {}".format(replicas),
        "",
        "# Resource limits (conservative — broodforge reference stack)",
        "resources:",
        "  requests:",
        "    cpu: 10m",
        "    memory: 32Mi",
        "  limits:",
        "    cpu: 100m",
        "    memory: 128Mi",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# ClusterIssuer spec generation
# ---------------------------------------------------------------------------

def generate_cluster_issuer_yaml(
    name: str,
    issuer_type: str,          # acme | selfsigned | ca
    email: str = "",
    acme_server: str = DEFAULT_ACME_SERVER,
    staging: bool = False,
    secret_name: str = "",
) -> str:
    """Generate a ClusterIssuer manifest YAML string."""
    if issuer_type == "selfsigned":
        return "\n".join([
            "apiVersion: cert-manager.io/v1",
            "kind: ClusterIssuer",
            "metadata:",
            f"  name: {name}",
            "spec:",
            "  selfSigned: {}",
            "",
        ])
    if issuer_type == "ca":
        sn = secret_name or f"{name}-ca-key-pair"
        return "\n".join([
            "apiVersion: cert-manager.io/v1",
            "kind: ClusterIssuer",
            "metadata:",
            f"  name: {name}",
            "spec:",
            "  ca:",
            f"    secretName: {sn}",
            "",
        ])
    if issuer_type == "acme":
        server = DEFAULT_ACME_STAGING_SERVER if staging else acme_server
        sn = secret_name or f"{name}-acme-account-key"
        return "\n".join([
            "apiVersion: cert-manager.io/v1",
            "kind: ClusterIssuer",
            "metadata:",
            f"  name: {name}",
            "spec:",
            "  acme:",
            f"    server: {server}",
            f"    email: {email}",
            "    privateKeySecretRef:",
            f"      name: {sn}",
            "    solvers:",
            "    - http01:",
            "        ingress:",
            "          class: nginx",
            "",
        ])
    raise ValueError(f"Unknown issuer type: {issuer_type!r}. Use acme|selfsigned|ca")


# ---------------------------------------------------------------------------
# CertManager operations
# ---------------------------------------------------------------------------

class CertManagerError(Exception):
    pass


class CertManager:
    """Certificate lifecycle manager."""

    def __init__(
        self,
        state_dir: str = DEFAULT_STATE_DIR,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.state_dir = state_dir
        self.now_fn = now_fn
        self._state: Optional[CertManagerState] = None

    # -- state access --------------------------------------------------------

    @property
    def state(self) -> CertManagerState:
        if self._state is None:
            self._state = load_state(self.state_dir)
        return self._state

    def _save(self) -> None:
        save_state(self.state, self.state_dir)

    # -- certificate operations ----------------------------------------------

    def register_cert(
        self,
        domain: str,
        issuer_name: str,
        issuer_type: str = "acme",
        secret_name: str = "",
        namespace: str = "default",
        san_domains: Optional[List[str]] = None,
    ) -> CertRecord:
        """Register a new certificate for tracking."""
        if self.state.find_cert(domain):
            raise CertManagerError(f"Certificate for domain {domain!r} already registered")
        sn = secret_name or domain.replace(".", "-") + "-tls"
        cert = CertRecord.new(
            domain=domain,
            issuer_name=issuer_name,
            issuer_type=issuer_type,
            secret_name=sn,
            namespace=namespace,
            san_domains=san_domains or [],
            now_fn=self.now_fn,
        )
        self.state.certificates.append(cert)
        self._save()
        return cert

    def record_renewal(self, domain: str, expires_at: str) -> CertRecord:
        """Update expiry after a successful renewal."""
        cert = self.state.find_cert(domain)
        if cert is None:
            raise CertManagerError(f"No certificate registered for {domain!r}")
        cert.expires_at = expires_at
        cert.last_renewed_at = self.now_fn().isoformat()
        cert.renewal_count += 1
        cert.status = "active"
        self._save()
        return cert

    def mark_deployed(self, chart_version: str = DEFAULT_CHART_VERSION) -> None:
        """Record that cert-manager Helm chart was deployed."""
        self.state.deployed_at = self.now_fn().isoformat()
        self.state.chart_version = chart_version
        self._save()

    def register_issuer(self, name: str, issuer_type: str) -> None:
        """Record a ClusterIssuer in state."""
        for existing in self.state.issuers:
            if existing.get("name") == name:
                existing["issuer_type"] = issuer_type
                existing["updated_at"] = self.now_fn().isoformat()
                self._save()
                return
        self.state.issuers.append({
            "name": name,
            "issuer_type": issuer_type,
            "created_at": self.now_fn().isoformat(),
        })
        self._save()

    # -- queries -------------------------------------------------------------

    def list_certs(
        self,
        critical_only: bool = False,
        warning_or_worse: bool = False,
    ) -> List[CertRecord]:
        certs = list(self.state.certificates)
        if critical_only:
            certs = [c for c in certs if cert_expiry_status(c, self.now_fn) == "critical"]
        elif warning_or_worse:
            certs = [
                c for c in certs
                if cert_expiry_status(c, self.now_fn) in ("critical", "warning")
            ]
        return certs

    def summary(self) -> dict:
        """Return a dashboard-friendly status dict."""
        certs = self.state.certificates
        by_status: dict = {"critical": 0, "warning": 0, "ok": 0, "unknown": 0}
        for c in certs:
            s = cert_expiry_status(c, self.now_fn)
            by_status[s] = by_status.get(s, 0) + 1
        return {
            "deployed": self.state.deployed_at is not None,
            "chart_version": self.state.chart_version,
            "cert_count": len(certs),
            "issuer_count": len(self.state.issuers),
            "expiry_summary": by_status,
        }

    # -- kubectl query (live status) ----------------------------------------

    def query_live_cert(self, domain: str) -> Optional[dict]:
        """
        Query cert-manager for the live status of a certificate via kubectl.
        Returns a dict with 'ready', 'not_after', 'reason' or None on failure.
        Requires kubectl in PATH and a working kubeconfig.
        """
        cert = self.state.find_cert(domain)
        if cert is None:
            return None
        try:
            result = subprocess.run(
                [
                    "kubectl", "get", "certificate",
                    "-n", cert.namespace,
                    cert.domain.replace(".", "-") + "-tls",
                    "-o", "json",
                ],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout)
            conditions = data.get("status", {}).get("conditions", [])
            ready = any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in conditions
            )
            not_after = data.get("status", {}).get("notAfter")
            return {"ready": ready, "not_after": not_after, "reason": None}
        except Exception as exc:
            logger.debug("kubectl query failed for %s: %s", domain, exc)
            return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_generate_values(args: argparse.Namespace) -> int:
    yaml_content = generate_values_yaml(
        namespace=DEFAULT_NAMESPACE,
        install_crds=True,
        replicas=1,
        prometheus_enabled=True,
    )
    out = args.output if hasattr(args, "output") and args.output else "-"
    if out == "-":
        print(yaml_content, end="")
    else:
        p = Path(out)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(yaml_content)
        tmp.replace(p)
        print(f"Written to {p}", file=sys.stderr)
    return 0


def _cmd_register_cert(args: argparse.Namespace) -> int:
    mgr = CertManager(state_dir=args.state)
    san = [s.strip() for s in args.san.split(",")] if getattr(args, "san", None) else []
    try:
        cert = mgr.register_cert(
            domain=args.domain,
            issuer_name=args.issuer,
            secret_name=getattr(args, "secret_name", "") or "",
            namespace=getattr(args, "namespace", "default") or "default",
            san_domains=san,
        )
        print(f"Registered certificate for {cert.domain} (secret={cert.secret_name})")
        return 0
    except CertManagerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_record_renewal(args: argparse.Namespace) -> int:
    mgr = CertManager(state_dir=args.state)
    try:
        cert = mgr.record_renewal(domain=args.domain, expires_at=args.expires)
        print(f"Recorded renewal for {cert.domain}; expires {cert.expires_at}")
        return 0
    except CertManagerError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_list(args: argparse.Namespace) -> int:
    mgr = CertManager(state_dir=args.state)
    certs = mgr.list_certs(
        critical_only=getattr(args, "critical", False),
        warning_or_worse=getattr(args, "warning", False),
    )
    if getattr(args, "json", False):
        print(json.dumps([asdict(c) for c in certs], indent=2))
        return 0
    if not certs:
        print("No certificates registered.")
        return 0
    print(f"{'DOMAIN':<35} {'ISSUER':<20} {'EXPIRES':<25} {'STATUS'}")
    for c in certs:
        days = _days_until_expiry(c, lambda: datetime.now(timezone.utc))
        days_str = f"{days}d" if days is not None else "unknown"
        status = cert_expiry_status(c, lambda: datetime.now(timezone.utc))
        print(f"{c.domain:<35} {c.issuer_name:<20} {c.expires_at or 'not set':<25} {status} ({days_str})")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    mgr = CertManager(state_dir=args.state)
    summary = mgr.summary()
    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2))
        return 0
    print(f"cert-manager deployed: {summary['deployed']}")
    print(f"Chart version:         {summary['chart_version']}")
    print(f"Certificates tracked:  {summary['cert_count']}")
    print(f"Issuers registered:    {summary['issuer_count']}")
    es = summary["expiry_summary"]
    print(f"Expiry summary:        critical={es['critical']} warning={es['warning']} ok={es['ok']} unknown={es['unknown']}")
    return 0


def _cmd_generate_issuer(args: argparse.Namespace) -> int:
    try:
        yaml_content = generate_cluster_issuer_yaml(
            name=args.issuer,
            issuer_type=args.type,
            email=getattr(args, "email", "") or "",
            staging=getattr(args, "staging", False),
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    out = getattr(args, "output", None) or "-"
    if out == "-":
        print(yaml_content, end="")
    else:
        p = Path(out)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(yaml_content)
        tmp.replace(p)
        print(f"Written to {p}", file=sys.stderr)

    mgr = CertManager(state_dir=args.state)
    mgr.register_issuer(name=args.issuer, issuer_type=args.type)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="cert_manager.py — Certificate Lifecycle Management (Phase 2.B)"
    )
    parser.add_argument("--state", default=DEFAULT_STATE_DIR,
                        help="Broodforge state directory")

    sub = parser.add_subparsers(dest="cmd")

    p_gv = sub.add_parser("generate-values", help="Generate cert-manager Helm values.yaml")
    p_gv.add_argument("--output", default="-", help="Output file (default: stdout)")

    p_rc = sub.add_parser("register-cert", help="Register a certificate for tracking")
    p_rc.add_argument("--domain", required=True)
    p_rc.add_argument("--issuer", required=True)
    p_rc.add_argument("--secret-name", default="")
    p_rc.add_argument("--namespace", default="default")
    p_rc.add_argument("--san", default="", help="Comma-separated SANs")

    p_rr = sub.add_parser("record-renewal", help="Record a renewal and new expiry date")
    p_rr.add_argument("--domain", required=True)
    p_rr.add_argument("--expires", required=True, help="ISO-8601 expiry date")

    p_ls = sub.add_parser("list", help="List tracked certificates")
    p_ls.add_argument("--json", action="store_true")
    p_ls.add_argument("--critical", action="store_true", help="Show only critical certs")
    p_ls.add_argument("--warning", action="store_true", help="Show warning-or-worse certs")

    p_st = sub.add_parser("status", help="Show cert-manager deployment status")
    p_st.add_argument("--json", action="store_true")

    p_gi = sub.add_parser("generate-issuer", help="Generate ClusterIssuer manifest")
    p_gi.add_argument("--issuer", required=True)
    p_gi.add_argument("--type", required=True, choices=["acme", "selfsigned", "ca"])
    p_gi.add_argument("--email", default="")
    p_gi.add_argument("--staging", action="store_true")
    p_gi.add_argument("--output", default="-")

    # Legacy flat-flag interface (backwards compat)
    parser.add_argument("--generate-values", action="store_true")
    parser.add_argument("--output", default="-")
    parser.add_argument("--register-cert", action="store_true")
    parser.add_argument("--domain", default="")
    parser.add_argument("--issuer", default="")
    parser.add_argument("--secret-name", default="")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--san", default="")
    parser.add_argument("--record-renewal", action="store_true")
    parser.add_argument("--expires", default="")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--critical", action="store_true")
    parser.add_argument("--warning", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--generate-issuer", action="store_true")
    parser.add_argument("--type", default="acme")
    parser.add_argument("--email", default="")
    parser.add_argument("--staging", action="store_true")

    args = parser.parse_args(argv)

    # subcommand dispatch
    if args.cmd == "generate-values":
        return _cmd_generate_values(args)
    if args.cmd == "register-cert":
        return _cmd_register_cert(args)
    if args.cmd == "record-renewal":
        return _cmd_record_renewal(args)
    if args.cmd == "list":
        return _cmd_list(args)
    if args.cmd == "status":
        return _cmd_status(args)
    if args.cmd == "generate-issuer":
        return _cmd_generate_issuer(args)

    # flat-flag legacy dispatch
    if args.generate_values:
        return _cmd_generate_values(args)
    if args.register_cert:
        return _cmd_register_cert(args)
    if args.record_renewal:
        return _cmd_record_renewal(args)
    if args.list:
        return _cmd_list(args)
    if args.status:
        return _cmd_status(args)
    if args.generate_issuer:
        return _cmd_generate_issuer(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
