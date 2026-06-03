#!/usr/bin/env python3
"""
setup_tls.py — Let's Encrypt TLS certificate automation (Phase 1.F.8d).

Generates the setup commands and config for automated TLS cert issuance
and renewal. Path depends on which DDNS provider was selected in 1.F.8c:

  Cloudflare path:
    certbot + python3-certbot-dns-cloudflare (apt)
    Wildcard cert via DNS-01 challenge: *.{domain}
    certbot.timer handles auto-renewal
    k3s: ClusterIssuer with dns01.cloudflare solver

  DuckDNS path:
    acme.sh + dns_duckdns plugin
    Wildcard cert: *.{subdomain}.duckdns.org
    acme.sh cron handles auto-renewal
    k3s: sync-cert-to-k8s.sh copies cert into TLS secrets

  None / self-signed:
    No cert automation configured.
    Headscale operates with self-signed cert.

Provides:
  TlsConfig              — structured TLS configuration
  TlsProvider            — provider constants
  generate_tls_config()  — build from network_topology + host_identity
  render_tls_commands()  — ordered shell commands for cert issuance
  render_sync_cert_sh()  — k8s TLS secret sync script (DuckDNS path)
  config_to_dict()       — serialise for testing

Stdlib only.
"""

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Provider constants
# ---------------------------------------------------------------------------

class TlsProvider:
    CERTBOT   = "certbot"       # Cloudflare path
    ACME_SH   = "acme.sh"      # DuckDNS path
    SELF_SIGNED = "self-signed" # No automation
    NONE      = "none"          # Headscale: allow insecure / caller-managed

    @classmethod
    def for_ddns_provider(cls, ddns_provider: str) -> str:
        """Derive TLS provider from DDNS provider selection."""
        if ddns_provider == "cloudflare":
            return cls.CERTBOT
        if ddns_provider == "duckdns":
            return cls.ACME_SH
        return cls.SELF_SIGNED


# ---------------------------------------------------------------------------
# TlsConfig
# ---------------------------------------------------------------------------

@dataclass
class TlsConfig:
    """Structured TLS certificate automation configuration."""

    provider:           str = TlsProvider.NONE

    # FQDN for the primary cert (e.g. hatchery.home.example.com)
    fqdn:               str = ""

    # Domain for wildcard cert (e.g. home.example.com → *.home.example.com)
    domain:             str = ""

    # Email for ACME registration (certbot requires this)
    acme_email:         Optional[str] = None

    # KeePass path for the Cloudflare API token
    cloudflare_token_keepass_path: Optional[str] = None

    # DuckDNS subdomain (for acme.sh path)
    duckdns_subdomain:  Optional[str] = None

    # Output cert paths (stable — reload hooks write here)
    cert_path:          str = "/etc/broodforge/ssl/fullchain.pem"
    key_path:           str = "/etc/broodforge/ssl/privkey.pem"

    # k3s namespace list for cert sync (DuckDNS path)
    k8s_namespaces:     list = None  # type: ignore

    def __post_init__(self):
        if self.k8s_namespaces is None:
            self.k8s_namespaces = ["default", "forgejo", "monitoring"]


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate_tls_config(
    network_topology: dict,
    host_identity:    dict,
) -> TlsConfig:
    """
    Build TlsConfig from network_topology and host_identity dicts.

    Uses:
      network_topology.ssl_provider      → provider (explicit override)
      network_topology.wan_config.tls_provider → derived if ssl_provider absent
      network_topology.wan_config.ddns_provider → fallback derivation
      network_topology.ssl_cert_path, ssl_key_path → existing cert paths
      host_identity.fqdn, .domain
    """
    nt      = network_topology
    wan     = nt.get("wan_config") or {}
    fqdn    = host_identity.get("fqdn")   or "hatchery.home.example.com"
    domain  = host_identity.get("domain") or "home.example.com"

    # Determine provider
    provider = (
        nt.get("ssl_provider")
        or wan.get("tls_provider")
        or TlsProvider.for_ddns_provider(wan.get("ddns_provider") or "none")
    )

    cert_path = nt.get("ssl_cert_path") or "/etc/broodforge/ssl/fullchain.pem"
    key_path  = nt.get("ssl_key_path")  or "/etc/broodforge/ssl/privkey.pem"

    duckdns_sub = None
    if provider == TlsProvider.ACME_SH:
        # Subdomain is the part before .duckdns.org
        # domain for DuckDNS looks like: myhatchery.duckdns.org
        parts = domain.split(".")
        if "duckdns" in parts:
            duckdns_sub = parts[0]
        else:
            # Derive from fqdn hostname
            duckdns_sub = host_identity.get("hostname") or "hatchery"

    return TlsConfig(
        provider=provider,
        fqdn=fqdn,
        domain=domain,
        acme_email=wan.get("acme_email"),
        cloudflare_token_keepass_path=wan.get("cloudflare_token_keepass_path"),
        duckdns_subdomain=duckdns_sub,
        cert_path=cert_path,
        key_path=key_path,
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_tls_commands(config: TlsConfig) -> list[str]:
    """
    Return ordered shell commands to issue the TLS certificate.

    These run in forge phase-03 after DDNS is configured and DNS has propagated.
    """
    if config.provider == TlsProvider.CERTBOT:
        return _certbot_commands(config)
    if config.provider == TlsProvider.ACME_SH:
        return _acme_sh_commands(config)
    if config.provider == TlsProvider.SELF_SIGNED:
        return _self_signed_commands(config)
    return ["echo '[tls] No TLS provider configured — skipping cert issuance.'"]


def _certbot_commands(config: TlsConfig) -> list[str]:
    """Certbot (Cloudflare DNS-01) commands."""
    creds_file = "/etc/broodforge/cloudflare.ini"
    email_flag = f"--email {config.acme_email}" if config.acme_email else "--register-unsafely-without-email"
    return [
        "apt-get install -y certbot python3-certbot-dns-cloudflare",
        f"install -d -m 700 /etc/broodforge",
        f"# Write Cloudflare credentials (token from KeePass at {config.cloudflare_token_keepass_path})",
        f"cat > {creds_file} << 'CREDS'",
        "dns_cloudflare_api_token = $CLOUDFLARE_API_TOKEN",
        "CREDS",
        f"chmod 600 {creds_file}",
        (
            f"certbot certonly --dns-cloudflare "
            f"--dns-cloudflare-credentials {creds_file} "
            f"--dns-cloudflare-propagation-seconds 30 "
            f"-d {config.fqdn} -d '*.{config.domain}' "
            f"{email_flag} --agree-tos --non-interactive"
        ),
        # Deploy to stable path
        f"install -d -m 750 /etc/broodforge/ssl",
        f"cp /etc/letsencrypt/live/{config.fqdn}/fullchain.pem {config.cert_path}",
        f"cp /etc/letsencrypt/live/{config.fqdn}/privkey.pem {config.key_path}",
        # Reload Headscale after cert placement
        "systemctl reload-or-restart headscale 2>/dev/null || true",
        "echo '[tls] Cloudflare certbot cert issued successfully.'",
    ]


def _acme_sh_commands(config: TlsConfig) -> list[str]:
    """acme.sh (DuckDNS DNS-01) commands."""
    subdomain = config.duckdns_subdomain or "hatchery"
    dom = f"{subdomain}.duckdns.org"
    return [
        "curl -fsSL https://get.acme.sh | sh -s email=${ACME_EMAIL:-admin@localhost}",
        "export DuckDNS_Token=$DUCKDNS_TOKEN",
        f"/root/.acme.sh/acme.sh --issue --dns dns_duckdns -d {dom} -d '*.{dom}' "
        f"--server letsencrypt --dnssleep 60",
        f"install -d -m 750 /etc/broodforge/ssl",
        f"/root/.acme.sh/acme.sh --install-cert -d {dom} "
        f"--cert-file {config.cert_path} --key-file {config.key_path} "
        f"--reloadcmd 'systemctl reload-or-restart headscale && /usr/local/bin/sync-cert-to-k8s.sh'",
        "echo '[tls] DuckDNS acme.sh cert issued successfully.'",
    ]


def _self_signed_commands(config: TlsConfig) -> list[str]:
    """Self-signed certificate generation (fallback)."""
    return [
        f"install -d -m 750 /etc/broodforge/ssl",
        (
            f"openssl req -x509 -newkey rsa:4096 -keyout {config.key_path} "
            f"-out {config.cert_path} -days 365 -nodes "
            f"-subj '/CN={config.fqdn}' "
            f"-addext 'subjectAltName=DNS:{config.fqdn},DNS:*.{config.domain}'"
        ),
        "echo '[tls] Self-signed certificate generated.'",
        "echo '[tls] WARNING: Clients will see certificate warnings. Replace with a real cert.'",
    ]


def render_sync_cert_sh(config: TlsConfig) -> str:
    """
    Render sync-cert-to-k8s.sh — copies the acme.sh wildcard cert into
    k8s TLS secrets in each configured namespace.

    Used on the DuckDNS path where cert-manager cannot do DNS-01 natively.
    """
    namespaces = config.k8s_namespaces or ["default"]
    ns_loop = " ".join(namespaces)
    return f"""\
#!/usr/bin/env bash
# sync-cert-to-k8s.sh — Sync TLS cert to k8s namespaces (Phase 1.F.8d, DuckDNS path)
# Called by acme.sh --reloadcmd and as a weekly k8s CronJob.
set -euo pipefail

CERT='{config.cert_path}'
KEY='{config.key_path}'
SECRET_NAME='broodforge-tls'
NAMESPACES='{ns_loop}'

for ns in $NAMESPACES; do
  kubectl create secret tls "$SECRET_NAME" \\
    --cert="$CERT" --key="$KEY" \\
    --namespace="$ns" --dry-run=client -o yaml | kubectl apply -f -
  echo "[tls] Synced $SECRET_NAME to namespace $ns"
done
echo "[tls] Certificate sync complete."
"""


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def config_to_dict(config: TlsConfig) -> dict:
    """Serialise TlsConfig to a plain dict."""
    return {
        "provider":                        config.provider,
        "fqdn":                            config.fqdn,
        "domain":                          config.domain,
        "acme_email":                      config.acme_email,
        "cloudflare_token_keepass_path":   config.cloudflare_token_keepass_path,
        "duckdns_subdomain":               config.duckdns_subdomain,
        "cert_path":                       config.cert_path,
        "key_path":                        config.key_path,
        "k8s_namespaces":                  list(config.k8s_namespaces or []),
    }
