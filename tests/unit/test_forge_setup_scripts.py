"""
test_forge_setup_scripts.py — Tests for Phase 1.F setup script generators:
  1.F.6   forge_keepass_init.py  — KeePass initialisation
  1.F.8a  setup_headscale.py     — Headscale auto-configuration
  1.F.8b  setup_dnsmasq.py       — dnsmasq config generator
  1.F.8c  setup_ddns.py          — DDNS updater configuration
  1.F.8d  setup_tls.py           — TLS certificate automation
"""



import forge_keepass_init as _kp
import setup_ddns as _ddns
import setup_dnsmasq as _dns
import setup_headscale as _hs
import setup_tls as _tls

# ===========================================================================
# 1.F.8b — setup_dnsmasq
# ===========================================================================

def _nt_lan():
    return {
        "profile": "lan",
        "management_cidr": "192.168.1.0/24",
        "gateway": "192.168.1.1",
    }

def _nt_wan():
    return {
        "profile": "wan",
        "management_cidr": "192.168.1.0/24",
        "gateway": "192.168.1.1",
        "wan_config": {
            "domain": "home.example.com",
            "dns_provider": "cloudflare",
            "headscale_url": "https://pve01.home.example.com:8080",
        },
    }

def _dns_registry():
    return [
        {"id": "hatchery", "name": "hatchery", "fqdn": "pve01.home.example.com",
         "ip": "192.168.1.10", "type": "proxmox-host"},
        {"id": "forgejo",  "name": "forgejo",  "fqdn": "forgejo.home.example.com",
         "ip": "192.168.1.11", "type": "vm"},
    ]


class TestSetupDnsmasq:
    def test_generate_returns_config(self):
        c = _dns.generate_dnsmasq_config(_nt_lan(), _dns_registry())
        assert isinstance(c, _dns.DnsmasqConfig)

    def test_hatchery_detect_from_proxmox_host_role(self):
        c = _dns.generate_dnsmasq_config(_nt_lan(), _dns_registry())
        assert c.hatchery_fqdn == "pve01.home.example.com"
        assert c.hatchery_lan_ip == "192.168.1.10"

    def test_address_entries_populated(self):
        c = _dns.generate_dnsmasq_config(_nt_lan(), _dns_registry())
        assert len(c.address_entries) == 2

    def test_lan_profile_in_config(self):
        c = _dns.generate_dnsmasq_config(_nt_lan(), _dns_registry())
        assert c.network_profile == "lan"

    def test_wan_profile_in_config(self):
        c = _dns.generate_dnsmasq_config(_nt_wan(), _dns_registry())
        assert c.network_profile == "wan"

    def test_wan_domain_extracted(self):
        c = _dns.generate_dnsmasq_config(_nt_wan(), _dns_registry())
        assert c.domain == "home.example.com"

    def test_render_produces_address_lines(self):
        c = _dns.generate_dnsmasq_config(_nt_lan(), _dns_registry())
        conf = _dns.render_dnsmasq_conf(c)
        assert "address=/pve01.home.example.com/192.168.1.10" in conf
        assert "address=/forgejo.home.example.com/192.168.1.11" in conf

    def test_render_has_upstream_servers(self):
        c = _dns.generate_dnsmasq_config(_nt_lan(), _dns_registry())
        conf = _dns.render_dnsmasq_conf(c)
        assert "server=8.8.8.8" in conf
        assert "server=1.1.1.1" in conf

    def test_render_wan_has_split_horizon_comment(self):
        c = _dns.generate_dnsmasq_config(_nt_wan(), _dns_registry())
        conf = _dns.render_dnsmasq_conf(c)
        assert "Split-horizon" in conf or "split-horizon" in conf.lower()

    def test_validate_valid_config(self):
        c = _dns.generate_dnsmasq_config(_nt_lan(), _dns_registry())
        errors = _dns.validate_dnsmasq_config(c)
        assert not errors

    def test_validate_empty_domain_error(self):
        c = _dns.DnsmasqConfig(domain="")
        errors = _dns.validate_dnsmasq_config(c)
        assert any(e.field == "domain" for e in errors)

    def test_validate_invalid_ip_error(self):
        c = _dns.DnsmasqConfig(domain="x.y", address_entries=[("a.b.c", "not-an-ip")])
        errors = _dns.validate_dnsmasq_config(c)
        assert errors

    def test_validate_duplicate_fqdn_error(self):
        c = _dns.DnsmasqConfig(
            domain="x.y",
            address_entries=[("a.b.c", "1.2.3.4"), ("a.b.c", "1.2.3.5")]
        )
        errors = _dns.validate_dnsmasq_config(c)
        assert any("Duplicate" in e.message for e in errors)

    def test_config_to_dict(self):
        c = _dns.generate_dnsmasq_config(_nt_lan(), _dns_registry())
        d = _dns.config_to_dict(c)
        assert d["address_count"] == 2
        assert d["network_profile"] == "lan"

    def test_no_registry_entries_no_address_lines(self):
        c = _dns.generate_dnsmasq_config(_nt_lan(), [])
        conf = _dns.render_dnsmasq_conf(c)
        assert "address=" not in conf


# ===========================================================================
# 1.F.8a — setup_headscale
# ===========================================================================

def _hi():
    return {
        "hostname": "pve01",
        "domain": "home.example.com",
        "fqdn": "pve01.home.example.com",
        "cell_id": "pve01-cell",
    }


class TestSetupHeadscale:
    def test_generate_returns_config(self):
        c = _hs.generate_headscale_config(_nt_lan(), _hi())
        assert isinstance(c, _hs.HeadscaleConfig)

    def test_server_url_from_fqdn(self):
        c = _hs.generate_headscale_config(_nt_lan(), _hi())
        assert "pve01.home.example.com" in c.server_url

    def test_server_url_from_wan_config(self):
        nt = _nt_wan()
        c = _hs.generate_headscale_config(nt, _hi())
        assert c.server_url == "https://pve01.home.example.com:8080"

    def test_listen_addr_default(self):
        c = _hs.generate_headscale_config(_nt_lan(), _hi())
        assert c.listen_addr == "0.0.0.0:8080"

    def test_broodforge_user(self):
        c = _hs.generate_headscale_config(_nt_lan(), _hi())
        assert c.broodforge_user == "broodforge"

    def test_render_yaml_contains_server_url(self):
        c = _hs.generate_headscale_config(_nt_wan(), _hi())
        yaml = _hs.render_headscale_yaml(c)
        assert "server_url:" in yaml
        assert "pve01.home.example.com" in yaml

    def test_render_yaml_contains_db_path(self):
        c = _hs.generate_headscale_config(_nt_lan(), _hi())
        yaml = _hs.render_headscale_yaml(c)
        assert "db_path:" in yaml
        assert "/var/lib/headscale" in yaml

    def test_render_yaml_with_tls(self):
        c = _hs.generate_headscale_config(_nt_lan(), _hi())
        c.tls_cert_path = "/etc/broodforge/ssl/fullchain.pem"
        c.tls_key_path  = "/etc/broodforge/ssl/privkey.pem"
        yaml = _hs.render_headscale_yaml(c)
        assert "tls_cert_path:" in yaml
        assert "tls_key_path:" in yaml

    def test_render_unit_has_service_section(self):
        unit = _hs.render_headscale_unit()
        assert "[Service]" in unit
        assert "headscale serve" in unit

    def test_init_commands_returns_list(self):
        c = _hs.generate_headscale_config(_nt_lan(), _hi())
        cmds = _hs.headscale_init_commands(c)
        assert isinstance(cmds, list)
        assert len(cmds) > 3

    def test_init_commands_create_user(self):
        c = _hs.generate_headscale_config(_nt_lan(), _hi())
        cmds = _hs.headscale_init_commands(c)
        user_cmd = next((cmd for cmd in cmds if "users create" in cmd), None)
        assert user_cmd is not None
        assert "broodforge" in user_cmd

    def test_config_to_dict(self):
        c = _hs.generate_headscale_config(_nt_lan(), _hi())
        d = _hs.config_to_dict(c)
        assert "server_url" in d
        assert "broodforge_user" in d


# ===========================================================================
# 1.F.8c — setup_ddns
# ===========================================================================

def _nt_wan_cloudflare():
    return {
        "profile": "wan",
        "management_cidr": "192.168.1.0/24",
        "gateway": "192.168.1.1",
        "wan_config": {
            "domain": "home.example.com",
            "ddns_provider": "cloudflare",
            "ddns_zone": "home.example.com",
            "ddns_record": "pve01",
            "ddns_credential_reference": "External/cloudflare/api-token",
        },
    }

def _nt_wan_duckdns():
    return {
        "profile": "wan",
        "management_cidr": "192.168.1.0/24",
        "gateway": "192.168.1.1",
        "wan_config": {
            "domain": "myhatchery.duckdns.org",
            "ddns_provider": "duckdns",
            "ddns_record": "myhatchery",
            "ddns_credential_reference": "External/duckdns/token",
        },
    }


class TestSetupDdns:
    def test_generate_cloudflare_config(self):
        c = _ddns.generate_ddns_config(_nt_wan_cloudflare(), _hi())
        assert c.provider == "cloudflare"
        assert c.zone == "home.example.com"
        assert c.record == "pve01"

    def test_generate_duckdns_config(self):
        c = _ddns.generate_ddns_config(_nt_wan_duckdns(), _hi())
        assert c.provider == "duckdns"
        assert c.duckdns_subdomain == "myhatchery"

    def test_none_provider_default(self):
        c = _ddns.generate_ddns_config(_nt_lan(), _hi())
        assert c.provider == _ddns.DdnsProvider.NONE

    def test_render_none_provider(self):
        c = _ddns.generate_ddns_config(_nt_lan(), _hi())
        script = _ddns.render_update_script(c)
        assert "disabled" in script or "none" in script.lower()

    def test_render_cloudflare_script(self):
        c = _ddns.generate_ddns_config(_nt_wan_cloudflare(), _hi())
        script = _ddns.render_update_script(c)
        assert "lexicon" in script
        assert "cloudflare" in script

    def test_render_duckdns_script(self):
        c = _ddns.generate_ddns_config(_nt_wan_duckdns(), _hi())
        script = _ddns.render_update_script(c)
        assert "duckdns.org" in script
        assert "myhatchery" in script

    def test_render_timer_unit(self):
        c = _ddns.generate_ddns_config(_nt_wan_cloudflare(), _hi())
        timer = _ddns.render_systemd_timer(c)
        assert "[Timer]" in timer
        assert "OnBootSec" in timer

    def test_render_service_unit(self):
        c = _ddns.generate_ddns_config(_nt_wan_cloudflare(), _hi())
        svc = _ddns.render_systemd_service(c)
        assert "[Service]" in svc

    def test_update_interval_in_timer(self):
        c = _ddns.generate_ddns_config(_nt_wan_cloudflare(), _hi())
        assert c.update_interval_minutes == 5
        timer = _ddns.render_systemd_timer(c)
        assert "5min" in timer

    def test_wan_ip_services_in_script(self):
        c = _ddns.generate_ddns_config(_nt_wan_cloudflare(), _hi())
        script = _ddns.render_update_script(c)
        assert "ifconfig.me" in script or "ipinfo.io" in script

    def test_config_to_dict(self):
        c = _ddns.generate_ddns_config(_nt_wan_cloudflare(), _hi())
        d = _ddns.config_to_dict(c)
        assert d["provider"] == "cloudflare"
        assert "zone" in d

    def test_is_lexicon_provider_cloudflare(self):
        assert _ddns.DdnsProvider.is_lexicon_provider("cloudflare")

    def test_is_lexicon_provider_duckdns(self):
        assert not _ddns.DdnsProvider.is_lexicon_provider("duckdns")

    def test_is_lexicon_provider_lexicon_prefix(self):
        assert _ddns.DdnsProvider.is_lexicon_provider("lexicon:namecheap")


# ===========================================================================
# 1.F.8d — setup_tls
# ===========================================================================

def _nt_wan_certbot():
    return {
        "profile": "wan",
        "management_cidr": "192.168.1.0/24",
        "gateway": "192.168.1.1",
        "wan_config": {
            "domain": "home.example.com",
            "ddns_provider": "cloudflare",
            "tls_provider": "certbot",
            "acme_email": "admin@example.com",
        },
    }

def _nt_wan_acmesh():
    return {
        "profile": "wan",
        "management_cidr": "192.168.1.0/24",
        "gateway": "192.168.1.1",
        "wan_config": {
            "domain": "myhatchery.duckdns.org",
            "ddns_provider": "duckdns",
            "tls_provider": "acme.sh",
        },
    }


class TestSetupTls:
    def test_generate_certbot_config(self):
        c = _tls.generate_tls_config(_nt_wan_certbot(), _hi())
        assert c.provider == _tls.TlsProvider.CERTBOT

    def test_generate_acmesh_config(self):
        hi = dict(_hi())
        hi["fqdn"] = "myhatchery.duckdns.org"
        hi["domain"] = "myhatchery.duckdns.org"
        c = _tls.generate_tls_config(_nt_wan_acmesh(), hi)
        assert c.provider == _tls.TlsProvider.ACME_SH

    def test_generate_self_signed_for_none(self):
        c = _tls.generate_tls_config(_nt_lan(), _hi())
        assert c.provider in (_tls.TlsProvider.SELF_SIGNED, _tls.TlsProvider.NONE)

    def test_for_ddns_provider_cloudflare(self):
        assert _tls.TlsProvider.for_ddns_provider("cloudflare") == _tls.TlsProvider.CERTBOT

    def test_for_ddns_provider_duckdns(self):
        assert _tls.TlsProvider.for_ddns_provider("duckdns") == _tls.TlsProvider.ACME_SH

    def test_for_ddns_provider_none(self):
        assert _tls.TlsProvider.for_ddns_provider("none") == _tls.TlsProvider.SELF_SIGNED

    def test_render_certbot_commands_list(self):
        c = _tls.generate_tls_config(_nt_wan_certbot(), _hi())
        cmds = _tls.render_tls_commands(c)
        assert any("certbot" in cmd for cmd in cmds)
        assert any("certonly" in cmd for cmd in cmds)

    def test_render_acmesh_commands_list(self):
        c = _tls.generate_tls_config(_nt_wan_acmesh(), _hi())
        cmds = _tls.render_tls_commands(c)
        assert any("acme.sh" in cmd for cmd in cmds)

    def test_render_self_signed_commands(self):
        c = _tls.TlsConfig(
            provider=_tls.TlsProvider.SELF_SIGNED,
            fqdn="pve01.home.example.com",
            domain="home.example.com",
        )
        cmds = _tls.render_tls_commands(c)
        assert any("openssl" in cmd for cmd in cmds)
        assert any("self-signed" in cmd.lower() for cmd in cmds)

    def test_render_none_provider(self):
        c = _tls.TlsConfig(provider=_tls.TlsProvider.NONE)
        cmds = _tls.render_tls_commands(c)
        assert cmds  # Not empty

    def test_render_sync_cert_sh(self):
        c = _tls.TlsConfig(
            provider=_tls.TlsProvider.ACME_SH,
            fqdn="myhatchery.duckdns.org",
            domain="myhatchery.duckdns.org",
        )
        script = _tls.render_sync_cert_sh(c)
        assert "kubectl create secret tls" in script
        assert "broodforge-tls" in script

    def test_sync_cert_sh_includes_namespaces(self):
        c = _tls.TlsConfig(k8s_namespaces=["default", "monitoring"])
        script = _tls.render_sync_cert_sh(c)
        assert "default" in script
        assert "monitoring" in script

    def test_config_to_dict(self):
        c = _tls.generate_tls_config(_nt_wan_certbot(), _hi())
        d = _tls.config_to_dict(c)
        assert "provider" in d
        assert "fqdn" in d

    def test_certbot_email_in_command(self):
        c = _tls.generate_tls_config(_nt_wan_certbot(), _hi())
        cmds = _tls.render_tls_commands(c)
        email_cmd = " ".join(cmds)
        assert "admin@example.com" in email_cmd

    def test_certbot_wildcard_domain(self):
        c = _tls.generate_tls_config(_nt_wan_certbot(), _hi())
        cmds = _tls.render_tls_commands(c)
        joined = " ".join(cmds)
        assert "*.home.example.com" in joined or "*.{config.domain}" in joined or "home.example.com" in joined


# ===========================================================================
# 1.F.6 — forge_keepass_init
# ===========================================================================

class TestForgeKeepassInit:
    def _manifest(self):
        return {
            "schema_version": "1.0",
            "cell_id": "pve01-cell",
            "generated_at": "2026-06-01T12:00:00+00:00",
            "setup_mode": "autonomous",
            "host_identity": {
                "hostname": "pve01",
                "domain": "home.example.com",
                "fqdn": "pve01.home.example.com",
                "cell_id": "pve01-cell",
            },
            "network_topology": {
                "profile": "lan",
                "management_cidr": "192.168.1.0/24",
                "gateway": "192.168.1.1",
            },
        }

    def test_generate_returns_config(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        assert isinstance(c, _kp.KeePassInitConfig)

    def test_entries_populated(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        assert len(c.entries) > 0

    def test_db_path_set(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        assert c.db_path.endswith(".kdbx")

    def test_entry_paths_returns_list(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        paths = _kp.keepass_entry_paths(c)
        assert isinstance(paths, list)
        assert len(paths) > 0

    def test_required_only_filter(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        all_paths = _kp.keepass_entry_paths(c, required_only=False)
        req_paths = _kp.keepass_entry_paths(c, required_only=True)
        assert len(req_paths) <= len(all_paths)

    def test_required_paths_include_headscale(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        req = _kp.keepass_entry_paths(c, required_only=True)
        assert any("headscale" in p for p in req)

    def test_required_paths_include_forgejo(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        req = _kp.keepass_entry_paths(c, required_only=True)
        assert any("forgejo" in p for p in req)

    def test_describe_plan_contains_db_path(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        plan = _kp.describe_init_plan(c)
        assert c.db_path in plan

    def test_describe_plan_contains_required_entries(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        plan = _kp.describe_init_plan(c)
        assert "Required entries" in plan

    def test_render_init_commands_returns_list(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        cmds = _kp.render_init_commands(c)
        assert isinstance(cmds, list)
        assert len(cmds) > 5

    def test_render_init_commands_creates_db(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        cmds = _kp.render_init_commands(c)
        assert any("db-create" in cmd for cmd in cmds)

    def test_embed_in_packages_false_default(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        assert c.embed_in_packages is False

    def test_embed_in_packages_flag(self):
        c = _kp.generate_keepass_init_config(self._manifest(), embed_in_packages=True)
        assert c.embed_in_packages is True

    def test_config_to_dict(self):
        c = _kp.generate_keepass_init_config(self._manifest())
        d = _kp.config_to_dict(c)
        assert "entry_count" in d
        assert "db_path" in d
        assert d["entry_count"] > 0

    def test_initial_entries_constant_has_k3s_tokens(self):
        paths = [e.path for e in _kp.KEEPASS_INITIAL_ENTRIES]
        assert any("join-token" in p for p in paths)

    def test_suggested_passphrase_optional(self):
        c = _kp.generate_keepass_init_config(self._manifest(), suggested_passphrase="Test.phrase.1")
        assert c.suggested_passphrase == "Test.phrase.1"
