#!/usr/bin/env python3
"""
setup_network.py — Network profile setup and migration (Phase 1.G / forge Phase 1.F).

Two profiles:
  lan — LAN-only: simple flat network, local DNS only, no Headscale, no external domain.
        Self-signed TLS optional. Spawn is LAN-only. No DDNS required.
  wan — WAN-capable: split-horizon DNS (dnsmasq), Headscale for cross-network spawn,
        DDNS for dynamic WAN IP, Let's Encrypt TLS via DNS-01.

Migration:
  lan → wan: add domain/DDNS, deploy Headscale, issue TLS certs, update dnsmasq.
  wan → lan: remove WAN-specific services, simplify dnsmasq.

Both initial setup and migration support two operation modes:
  guided    — step-by-step prompts with auto-suggestions at each step.
  autonomous — auto-suggestions accepted silently; no operator input.

Core classes are fully testable (io_fn injectable). Interactive prompts live in callers.

Stdlib only.
"""

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Profile constants
# ---------------------------------------------------------------------------

PROFILE_LAN = "lan"
PROFILE_WAN = "wan"
PROFILES    = (PROFILE_LAN, PROFILE_WAN)

SETUP_MODES = ("guided", "autonomous")

DNS_PROVIDERS     = ("cloudflare", "duckdns", "other", "none")
TLS_LAN_MODES     = ("self-signed", "none")
TLS_WAN_PROVIDERS = ("certbot-cloudflare", "acme.sh-duckdns", "self-signed", "none")


# ---------------------------------------------------------------------------
# Configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LanNetworkConfig:
    """Complete LAN-profile network configuration."""
    profile:        str = PROFILE_LAN

    # Core networking
    management_cidr: str = "192.168.1.0/24"
    gateway:         str = "192.168.1.1"
    nameservers:     list = field(default_factory=lambda: ["192.168.1.1", "8.8.8.8"])
    search_domain:   str = "internal"
    bridge_name:     str = "vmbr0"
    vlan_aware:      bool = True

    # LAN-specific
    tls_mode:        str = "self-signed"   # self-signed | none
    dnsmasq_enabled: bool = True


@dataclass
class WanNetworkConfig:
    """Complete WAN-profile network configuration."""
    profile:        str = PROFILE_WAN

    # Core networking (same fields as LAN)
    management_cidr: str = "192.168.1.0/24"
    gateway:         str = "192.168.1.1"
    nameservers:     list = field(default_factory=lambda: ["192.168.1.1", "8.8.8.8"])
    search_domain:   str = ""
    bridge_name:     str = "vmbr0"
    vlan_aware:      bool = True

    # WAN-specific: identity
    domain:          str = ""              # e.g. home.example.com
    fqdn:            str = ""             # e.g. hatchery.home.example.com

    # WAN-specific: DNS/DDNS
    dns_provider:    str = "cloudflare"    # cloudflare | duckdns | other | none
    dns_provider_credential_reference: Optional[str] = None
    ddns_enabled:    bool = True
    ddns_update_interval_min: int = 5

    # WAN-specific: Headscale
    headscale_enabled: bool = True
    headscale_url:     str = ""            # auto-built from fqdn

    # WAN-specific: TLS
    tls_provider:    str = "certbot-cloudflare"   # certbot-cloudflare | acme.sh-duckdns | self-signed | none

    # dnsmasq
    dnsmasq_enabled: bool = True           # always True for WAN (split-horizon)


# ---------------------------------------------------------------------------
# Auto-suggestion engine
# ---------------------------------------------------------------------------

def _get(obj: Any, *keys, default=None) -> Any:
    for k in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(k, default)
    return obj


def suggest_lan(field: str, manifest: dict, partial: LanNetworkConfig) -> Any:
    """Return an auto-suggestion for a LAN-profile field."""

    if field == "management_cidr":
        c = _get(manifest, "network_topology", "management_cidr")
        if c: return c
        gw = _get(manifest, "network", "default_gateway")
        if gw:
            try:
                return str(ipaddress.ip_interface(f"{gw}/24").network)
            except ValueError:
                pass
        return "192.168.1.0/24"

    if field == "gateway":
        c = _get(manifest, "network_topology", "gateway") \
            or _get(manifest, "network", "default_gateway")
        if c: return c
        try:
            net = ipaddress.ip_network(partial.management_cidr, strict=False)
            return str(next(net.hosts()))
        except (ValueError, StopIteration):
            return "192.168.1.1"

    if field == "nameservers":
        discovered = _get(manifest, "network", "dns_servers") or []
        if discovered: return discovered
        return [partial.gateway, "8.8.8.8"]

    if field == "search_domain":
        return _get(manifest, "network_topology", "search_domain") or "internal"

    if field == "bridge_name":
        return "vmbr0"

    if field == "vlan_aware":
        return True

    if field == "tls_mode":
        return "self-signed"

    if field == "dnsmasq_enabled":
        return True

    return None


def suggest_wan(field: str, manifest: dict, partial: WanNetworkConfig) -> Any:
    """Return an auto-suggestion for a WAN-profile field."""

    # Re-use LAN suggestions for shared fields
    if field in ("management_cidr", "gateway", "nameservers", "bridge_name", "vlan_aware"):
        lan_partial = LanNetworkConfig(management_cidr=partial.management_cidr,
                                       gateway=partial.gateway)
        return suggest_lan(field, manifest, lan_partial)

    if field == "search_domain":
        # WAN: search domain derives from the external domain
        if partial.domain:
            return partial.domain
        return _get(manifest, "network_topology", "search_domain") or ""

    if field == "domain":
        existing = _get(manifest, "host_identity", "domain")
        return existing or "home.example.com"

    if field == "fqdn":
        hostname = _get(manifest, "host_identity", "hostname") \
                   or _get(manifest, "host", "hostname") or "hatchery"
        domain = partial.domain or "home.example.com"
        return f"{hostname}.{domain}"

    if field == "dns_provider":
        return "cloudflare"

    if field == "ddns_enabled":
        return True

    if field == "ddns_update_interval_min":
        return 5

    if field == "headscale_enabled":
        return True

    if field == "headscale_url":
        fqdn = partial.fqdn or suggest_wan("fqdn", manifest, partial)
        return f"https://{fqdn}:8080"

    if field == "tls_provider":
        provider = partial.dns_provider
        if provider == "cloudflare":
            return "certbot-cloudflare"
        if provider == "duckdns":
            return "acme.sh-duckdns"
        return "self-signed"

    if field == "dnsmasq_enabled":
        return True   # always required for split-horizon

    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    valid:    bool
    warnings: list = field(default_factory=list)   # non-fatal — operator may proceed
    errors:   list = field(default_factory=list)   # fatal — cannot proceed


def validate_lan_config(config: LanNetworkConfig) -> ValidationResult:
    warnings, errors = [], []

    try:
        ipaddress.ip_network(config.management_cidr, strict=False)
    except ValueError:
        errors.append(f"management_cidr '{config.management_cidr}' is not valid CIDR notation")

    try:
        gw = ipaddress.ip_address(config.gateway)
        net = ipaddress.ip_network(config.management_cidr, strict=False)
        if gw not in net:
            warnings.append(f"Gateway {config.gateway} is not within CIDR {config.management_cidr}")
    except ValueError:
        errors.append(f"gateway '{config.gateway}' is not a valid IP address")

    if config.tls_mode not in TLS_LAN_MODES:
        errors.append(f"tls_mode must be one of {TLS_LAN_MODES}")

    return ValidationResult(valid=not errors, warnings=warnings, errors=errors)


def validate_wan_config(config: WanNetworkConfig) -> ValidationResult:
    warnings, errors = [], []

    # Validate shared fields via LAN helper
    lan = LanNetworkConfig(management_cidr=config.management_cidr,
                            gateway=config.gateway,
                            tls_mode="none")
    lan_result = validate_lan_config(lan)
    warnings.extend(lan_result.warnings)
    errors.extend(lan_result.errors)

    if not config.domain:
        errors.append("domain is required for WAN profile")
    elif not re.match(r"^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}$", config.domain):
        warnings.append(f"domain '{config.domain}' does not look like a valid domain name")

    if config.dns_provider not in DNS_PROVIDERS:
        errors.append(f"dns_provider must be one of {DNS_PROVIDERS}")

    if config.tls_provider not in TLS_WAN_PROVIDERS:
        errors.append(f"tls_provider must be one of {TLS_WAN_PROVIDERS}")

    if config.dns_provider == "cloudflare" and not config.dns_provider_credential_reference:
        warnings.append(
            "dns_provider_credential_reference not set — "
            "Cloudflare API token KeePass path must be configured before DDNS/TLS work"
        )

    if config.headscale_enabled and not config.headscale_url:
        warnings.append("headscale_url is empty — will be auto-built from FQDN during forge")

    return ValidationResult(valid=not errors, warnings=warnings, errors=errors)


# ---------------------------------------------------------------------------
# Migration plan generation
# ---------------------------------------------------------------------------

@dataclass
class MigrationPlan:
    """Describes what will change when migrating between network profiles."""
    from_profile: str
    to_profile:   str
    steps:        list   # list of {id, description, action, autonomous_possible, notes}
    warnings:     list = field(default_factory=list)


def plan_migration_to_wan(
    current: LanNetworkConfig,
    target: WanNetworkConfig,
) -> MigrationPlan:
    """Generate a step list for migrating from LAN to WAN profile."""
    steps = [
        {
            "id":   "1-domain",
            "description": f"Configure external domain: {target.domain or '(not set)'}",
            "action": "Set domain and DNS provider in bootstrap-state.json network_topology",
            "autonomous_possible": True,
            "notes": (
                "Cloudflare: change your domain's nameservers to Cloudflare, create API token. "
                "DuckDNS: sign up at duckdns.org, copy your token. "
                "See docs/DNS-UPDATE-SETUP.md."
            ),
        },
        {
            "id":   "2-ddns",
            "description": "Install and configure DDNS agent (broodforge-ddns.timer)",
            "action": "pip install dns-lexicon + write /etc/broodforge/ddns.conf + enable timer",
            "autonomous_possible": True,
            "notes": "Requires API credentials for chosen DNS provider.",
        },
        {
            "id":   "3-dnsmasq",
            "description": "Update dnsmasq for split-horizon DNS",
            "action": "Re-run generate-dnsmasq-config.py with WAN profile settings",
            "autonomous_possible": True,
            "notes": (
                "LAN clients will resolve domain names to LAN IPs via dnsmasq. "
                "External clients resolve via your registrar/DDNS to WAN IP."
            ),
        },
        {
            "id":   "4-headscale",
            "description": "Deploy Headscale coordination server",
            "action": "apt install headscale + configure + register hatchery with its own Headscale",
            "autonomous_possible": True,
            "notes": (
                "Headscale serves as the WireGuard coordination server for cross-network spawn. "
                "The hatchery becomes the first node on its own tailnet."
            ),
        },
        {
            "id":   "5-tls",
            "description": f"Issue Let's Encrypt TLS certificate via {target.tls_provider}",
            "action": (
                "certbot certonly --dns-cloudflare ..." if target.tls_provider == "certbot-cloudflare"
                else "acme.sh --issue --dns dns_duckdns ..."
            ),
            "autonomous_possible": True,
            "notes": "Wildcard certificate covers all subdomains. Headscale reconfigured with cert paths.",
        },
        {
            "id":   "6-router",
            "description": "Router port forwarding (manual — cannot be automated)",
            "action": "Forward port 8080 (Headscale) from WAN to hatchery LAN IP",
            "autonomous_possible": False,
            "notes": (
                "This step requires access to your router/firewall admin panel. "
                "Broodforge cannot configure your router automatically."
            ),
        },
        {
            "id":   "7-commit",
            "description": "Update bootstrap-state.json and commit to Forgejo",
            "action": "Write WAN profile settings, regenerate documentation, commit",
            "autonomous_possible": True,
            "notes": "Assessment Engine regenerates all documentation after the commit.",
        },
    ]

    warnings = []
    if not target.domain:
        warnings.append("No domain configured — steps 1–5 cannot be completed without a domain name")
    if not target.dns_provider_credential_reference:
        warnings.append("DNS provider credential KeePass path not set — DDNS and TLS steps will need manual credential entry")

    return MigrationPlan(
        from_profile=PROFILE_LAN,
        to_profile=PROFILE_WAN,
        steps=steps,
        warnings=warnings,
    )


def plan_migration_to_lan(
    current: WanNetworkConfig,
    preserve_headscale: bool = False,
) -> MigrationPlan:
    """Generate a step list for migrating from WAN to LAN profile."""
    steps = [
        {
            "id":   "1-ddns",
            "description": "Disable DDNS agent",
            "action": "systemctl disable --now broodforge-ddns.timer",
            "autonomous_possible": True,
            "notes": "External DNS record will no longer auto-update. The record can be left as-is or deleted manually.",
        },
    ]

    if preserve_headscale:
        steps.append({
            "id":   "2-headscale",
            "description": "Keep Headscale running (retained for optional WAN access)",
            "action": "No change to Headscale",
            "autonomous_possible": True,
            "notes": "Headscale remains available but new spawn packages will use LAN-only mode by default.",
        })
    else:
        steps.append({
            "id":   "2-headscale",
            "description": "Stop and disable Headscale",
            "action": "systemctl disable --now headscale",
            "autonomous_possible": True,
            "notes": "Tailscale clients on broodlings will lose tailnet connectivity. Ensure LAN access before disabling.",
        })

    steps += [
        {
            "id":   "3-dnsmasq",
            "description": "Simplify dnsmasq to LAN-only mode",
            "action": "Re-run generate-dnsmasq-config.py with LAN profile settings",
            "autonomous_possible": True,
            "notes": "Removes split-horizon complexity. dnsmasq still serves LAN name resolution.",
        },
        {
            "id":   "4-commit",
            "description": "Update bootstrap-state.json and commit to Forgejo",
            "action": "Write LAN profile settings, regenerate documentation, commit",
            "autonomous_possible": True,
            "notes": "Spawn packages generated after this point will be LAN-only.",
        },
    ]

    return MigrationPlan(
        from_profile=PROFILE_WAN,
        to_profile=PROFILE_LAN,
        steps=steps,
    )


# ---------------------------------------------------------------------------
# State serialization
# ---------------------------------------------------------------------------

def lan_config_to_state(config: LanNetworkConfig) -> dict:
    """Return the network_topology dict to write into bootstrap-state.json."""
    return {
        "profile":        config.profile,
        "management_cidr": config.management_cidr,
        "gateway":        config.gateway,
        "nameservers":    config.nameservers,
        "search_domain":  config.search_domain,
        "interface_name": "ens18",     # VM NIC — unchanged by profile
        "headscale_url":  None,
        "ddns_provider":  None,
        "ddns_zone":      None,
        "ddns_record":    None,
        "ddns_credential_reference": None,
        "ssl_provider":   "self-signed" if config.tls_mode == "self-signed" else None,
        "ssl_method":     None,
        "ssl_cert_path":  None,
        "ssl_key_path":   None,
        "lan_config": {
            "tls_mode":        config.tls_mode,
            "dnsmasq_enabled": config.dnsmasq_enabled,
        },
        "wan_config": None,
    }


def wan_config_to_state(config: WanNetworkConfig) -> dict:
    """Return the network_topology dict to write into bootstrap-state.json."""
    tls_cert = tls_key = None
    if config.tls_provider in ("certbot-cloudflare",):
        tls_cert = f"/etc/letsencrypt/live/{config.fqdn}/fullchain.pem"
        tls_key  = f"/etc/letsencrypt/live/{config.fqdn}/privkey.pem"
    elif config.tls_provider == "acme.sh-duckdns":
        tls_cert = "/etc/broodforge/ssl/fullchain.pem"
        tls_key  = "/etc/broodforge/ssl/key.pem"

    return {
        "profile":         config.profile,
        "management_cidr": config.management_cidr,
        "gateway":         config.gateway,
        "nameservers":     config.nameservers,
        "search_domain":   config.search_domain or config.domain,
        "interface_name":  "ens18",
        "headscale_url":   config.headscale_url,
        "ddns_provider":   config.dns_provider if config.dns_provider != "none" else None,
        "ddns_zone":       config.domain,
        "ddns_record":     config.fqdn.split(".")[0] if config.fqdn else None,
        "ddns_credential_reference": config.dns_provider_credential_reference,
        "ssl_provider":    config.tls_provider,
        "ssl_method":      f"dns-01-{config.dns_provider}" if config.dns_provider != "none" else None,
        "ssl_cert_path":   tls_cert,
        "ssl_key_path":    tls_key,
        "lan_config": None,
        "wan_config": {
            "domain":            config.domain,
            "dns_provider":      config.dns_provider,
            "dns_provider_credential_reference": config.dns_provider_credential_reference,
            "ddns_enabled":      config.ddns_enabled,
            "ddns_update_interval_min": config.ddns_update_interval_min,
            "headscale_enabled": config.headscale_enabled,
            "tls_provider":      config.tls_provider,
            "router_port_forward_note":
                "Forward port 8080 (Headscale) and 443 (HTTPS) from WAN to this host's LAN IP",
        },
    }


def apply_network_config_to_state(state: dict, network_topology: dict) -> dict:
    """Merge network topology into bootstrap-state.json dict in-place."""
    state["network_topology"] = {
        **(state.get("network_topology") or {}),
        **network_topology,
    }
    return state


# ---------------------------------------------------------------------------
# dnsmasq config generation
# ---------------------------------------------------------------------------

def generate_dnsmasq_config(
    network_topology: dict,
    dns_registry: list,
    hostname: str = "pve01",
) -> str:
    """
    Generate /etc/dnsmasq.d/broodforge.conf content from network_topology and dns_registry.

    For LAN profile: local name resolution only.
    For WAN profile: LAN clients get LAN IPs (split-horizon); external via registrar.
    """
    profile = network_topology.get("profile", PROFILE_LAN)
    network_topology.get("management_cidr", "192.168.1.0/24")
    network_topology.get("gateway", "192.168.1.1")
    domain  = network_topology.get("search_domain") or \
              (network_topology.get("wan_config") or {}).get("domain", "internal")
    listen  = None
    for entry in (dns_registry or []):
        if entry.get("role") == "proxmox-host":
            listen = entry.get("ip")
            break

    lines = [
        "# /etc/dnsmasq.d/broodforge.conf",
        f"# Generated by setup_network.py  profile={profile}",
        "#",
        "# Edit proxmox-bootstrap/metadata/network-topology.yaml and re-run",
        "# generate-dnsmasq-config.py to update.",
        "",
    ]

    if listen:
        lines.append(f"listen-address={listen},127.0.0.1")
    lines.append(f"domain={domain}")
    lines.append(f"local=/{domain}/")
    lines.append("")

    lines.append("# Local hostname resolution from dns_registry:")
    for entry in (dns_registry or []):
        hn  = entry.get("hostname") or entry.get("fqdn", "")
        ip  = entry.get("ip", "")
        if hn and ip:
            lines.append(f"address=/{hn}/{ip}")

    lines += [
        "",
        "# Upstream resolvers (for external names):",
        "server=8.8.8.8",
        "server=1.1.1.1",
        "",
        "# Performance:",
        "cache-size=500",
        "no-negcache",
    ]

    if profile == PROFILE_WAN:
        wan = network_topology.get("wan_config") or {}
        wan_domain = wan.get("domain", "")
        if wan_domain:
            lines += [
                "",
                f"# Split-horizon: {wan_domain} resolves to LAN IPs for local clients.",
                "# External clients resolve via your DNS registrar/DDNS → WAN IP.",
                "# No extra config needed here — the address= lines above handle LAN resolution.",
            ]

    return "\n".join(lines) + "\n"
