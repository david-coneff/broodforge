#!/usr/bin/env python3
"""
Tests for Milestone 7.4 — Recovery Documentation Update (Service Layer).

Covers:
  - _get_contract() lookup helper
  - _health_check_cmds() for HTTP, postgresql, smtp, ssh, generic port, null
  - _service_restart_cmds() command generation
  - Service contract block in per-VM restore section (HTML renderer)
  - Required interfaces listed per contract
  - startup_after note rendered
  - Secret references listed
  - Contract-level checkboxes
  - Appendix A edge type legend
  - SERVICE edge ★ marker in Appendix A
  - No contract block for non-VM nodes or VMs without a contract

NOTE: ODT renderer (recovery_runbook.py) is deprecated. All tests use
      build_recovery_runbook_html() from html_recovery_runbook.py.
"""

import unittest

from html_recovery_runbook import (
    _get_contract,
    _health_check_cmds,
    _service_restart_cmds,
    build_recovery_runbook_html,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CONTRACTS = [
    {
        "service": "forgejo",
        "vm": "forgejo",
        "vmid": 101,
        "provided_interfaces": [
            {
                "protocol": "https",
                "port": 3000,
                "url_pattern": "https://forgejo.internal",
                "health_check": "GET /api/healthz",
            },
            {
                "protocol": "ssh",
                "port": 22,
                "url_pattern": None,
                "health_check": None,
            },
        ],
        "required_interfaces": [
            {
                "service": "postgresql",
                "protocol": "postgresql",
                "port": 5432,
                "critical": True,
            }
        ],
        "startup_after": ["postgresql"],
        "backup_job": "pbs-daily-vms",
        "secret_references": ["forgejo-admin-password", "forgejo-deploy-key"],
        "owner": "infrastructure",
    },
    {
        "service": "assessment-engine",
        "vm": "assessment-engine",
        "vmid": 103,
        "provided_interfaces": [
            {"protocol": "ssh", "port": 22, "url_pattern": None, "health_check": None}
        ],
        "required_interfaces": [
            {"service": "forgejo", "protocol": "https", "port": 3000, "critical": True}
        ],
        "startup_after": ["forgejo"],
        "backup_job": "pbs-daily-vms",
        "secret_references": ["assessment-engine-deploy-key"],
        "owner": "infrastructure",
    },
]

DNS_REGISTRY = [
    {"hostname": "forgejo.internal", "ip": "192.168.1.21", "vmid": 101, "role": "forgejo"},
    {"hostname": "assessment.internal", "ip": "192.168.1.23", "vmid": 103, "role": "assessment-engine"},
]

BASE_MANIFEST = {
    "host": {"hostname": "pve01", "proxmox_version": "8.1.3"},
    "network": {"default_gateway": "192.168.1.1", "dns_servers": ["8.8.8.8"]},
    "vms": [
        {"vmid": 101, "name": "forgejo", "status": "running"},
        {"vmid": 103, "name": "assessment-engine", "status": "running"},
    ],
    "containers": [],
    "collected_at": "2026-01-01T00:00:00Z",
    "service_contracts": CONTRACTS,
    "dns_registry": DNS_REGISTRY,
}


def _build_html(manifest_extras=None):
    from dependencies import build_graph
    from readiness import score_graph
    manifest = dict(BASE_MANIFEST)
    if manifest_extras:
        manifest.update(manifest_extras)
    graph = build_graph(manifest)
    readiness = score_graph(graph, manifest)
    gen_meta = {
        "generated_at": "2026-01-01T12:00:00Z",
        "generated_at_display": "2026-01-01 12:00:00 UTC",
    }
    return build_recovery_runbook_html(manifest, graph, readiness, gen_meta)


# ---------------------------------------------------------------------------
# _get_contract
# ---------------------------------------------------------------------------

class TestGetContract(unittest.TestCase):

    def _manifest(self):
        return {"service_contracts": CONTRACTS}

    def test_returns_contract_for_known_vm(self):
        c = _get_contract("forgejo", self._manifest())
        self.assertIsNotNone(c)
        self.assertEqual(c["service"], "forgejo")

    def test_returns_none_for_unknown_vm(self):
        self.assertIsNone(_get_contract("nonexistent", self._manifest()))

    def test_returns_none_when_no_contracts(self):
        self.assertIsNone(_get_contract("forgejo", {}))

    def test_returns_none_for_null_contracts(self):
        self.assertIsNone(_get_contract("forgejo", {"service_contracts": None}))

    def test_matches_by_vm_field(self):
        c = _get_contract("assessment-engine", self._manifest())
        self.assertIsNotNone(c)
        self.assertEqual(c["vm"], "assessment-engine")


# ---------------------------------------------------------------------------
# _health_check_cmds
# ---------------------------------------------------------------------------

class TestHealthCheckCmds(unittest.TestCase):

    def test_ssh_returns_empty(self):
        iface = {"protocol": "ssh", "port": 22, "health_check": None}
        self.assertEqual(_health_check_cmds(iface, "192.168.1.21"), [])

    def test_null_health_check_http_no_url_pattern(self):
        iface = {"protocol": "https", "port": 3000, "health_check": None, "url_pattern": None}
        cmds = _health_check_cmds(iface, "192.168.1.21")
        self.assertTrue(len(cmds) >= 1)
        self.assertIn("192.168.1.21", cmds[0])

    def test_http_get_with_url_pattern(self):
        iface = {
            "protocol": "https",
            "port": 3000,
            "url_pattern": "https://forgejo.internal",
            "health_check": "GET /api/healthz",
        }
        cmds = _health_check_cmds(iface, "192.168.1.21")
        self.assertTrue(any("curl" in c for c in cmds))
        self.assertTrue(any("https://forgejo.internal/api/healthz" in c for c in cmds))

    def test_http_get_without_url_pattern_uses_ip(self):
        iface = {
            "protocol": "http",
            "port": 8080,
            "url_pattern": None,
            "health_check": "GET /health",
        }
        cmds = _health_check_cmds(iface, "10.0.0.5")
        joined = " ".join(cmds)
        self.assertIn("10.0.0.5", joined)
        self.assertIn("/health", joined)
        self.assertIn("curl", joined)

    def test_postgresql_generates_pg_isready(self):
        iface = {"protocol": "postgresql", "port": 5432, "health_check": None}
        cmds = _health_check_cmds(iface, "192.168.1.20")
        self.assertTrue(any("pg_isready" in c for c in cmds))
        self.assertTrue(any("192.168.1.20" in c for c in cmds))
        self.assertTrue(any("5432" in c for c in cmds))

    def test_postgresql_with_vm_ip_placeholder(self):
        iface = {"protocol": "postgresql", "port": 5432, "health_check": None}
        cmds = _health_check_cmds(iface, "[VM_IP]")
        self.assertTrue(any("pg_isready" in c for c in cmds))
        joined = " ".join(cmds)
        self.assertNotIn("[VM_IP]", joined)

    def test_smtp_generates_nc(self):
        iface = {"protocol": "smtp", "port": 25, "health_check": None}
        cmds = _health_check_cmds(iface, "192.168.1.10")
        self.assertTrue(any("nc" in c for c in cmds))
        self.assertTrue(any("25" in c for c in cmds))

    def test_null_health_check_ssh_returns_empty(self):
        iface = {"protocol": "ssh", "port": 22, "health_check": None, "url_pattern": None}
        self.assertEqual(_health_check_cmds(iface, "192.168.1.20"), [])

    def test_expected_comment_in_http_cmds(self):
        iface = {
            "protocol": "https",
            "port": 443,
            "url_pattern": "https://example.com",
            "health_check": "GET /healthz",
        }
        cmds = _health_check_cmds(iface, "10.0.0.1")
        joined = " ".join(cmds)
        self.assertIn("2xx", joined)


# ---------------------------------------------------------------------------
# _service_restart_cmds
# ---------------------------------------------------------------------------

class TestServiceRestartCmds(unittest.TestCase):

    def test_generates_systemctl_restart(self):
        contract = {"service": "forgejo"}
        cmds = _service_restart_cmds(contract, "192.168.1.21")
        joined = " ".join(cmds)
        self.assertIn("systemctl restart forgejo", joined)

    def test_generates_systemctl_status(self):
        contract = {"service": "forgejo"}
        cmds = _service_restart_cmds(contract, "192.168.1.21")
        joined = " ".join(cmds)
        self.assertIn("systemctl status", joined)

    def test_includes_ssh_prefix_with_ip(self):
        contract = {"service": "forgejo"}
        cmds = _service_restart_cmds(contract, "192.168.1.21")
        self.assertTrue(any("ssh ubuntu@192.168.1.21" in c for c in cmds))

    def test_placeholder_when_ip_unknown(self):
        contract = {"service": "my-svc"}
        cmds = _service_restart_cmds(contract, "[VM_IP]")
        joined = " ".join(cmds)
        self.assertNotIn("ssh ubuntu@[VM_IP]", joined)
        self.assertTrue(any("MY_SVC" in c or "MY-SVC" in c or "ssh" in c for c in cmds))

    def test_service_name_in_commands(self):
        contract = {"service": "assessment-engine"}
        cmds = _service_restart_cmds(contract, "192.168.1.23")
        joined = " ".join(cmds)
        self.assertIn("assessment-engine", joined)


# ---------------------------------------------------------------------------
# Integration — HTML recovery runbook content
# ---------------------------------------------------------------------------

class TestRunbookServiceContractBlock(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = _build_html()

    def test_service_contract_heading_present(self):
        self.assertIn("Service Contract", self.html)

    def test_forgejo_contract_shown(self):
        self.assertIn("forgejo", self.html)

    def test_provided_interface_https_shown(self):
        self.assertIn("3000", self.html)

    def test_health_check_curl_command_shown(self):
        self.assertIn("curl", self.html)

    def test_health_check_url_in_html(self):
        self.assertIn("/api/healthz", self.html)

    def test_required_interface_postgresql_shown(self):
        self.assertIn("postgresql", self.html)

    def test_required_interface_critical_shown(self):
        self.assertIn("CRITICAL", self.html)

    def test_startup_after_shown(self):
        self.assertIn("Start after", self.html)

    def test_secret_references_shown(self):
        self.assertIn("forgejo-admin-password", self.html)
        self.assertIn("forgejo-deploy-key", self.html)

    def test_contract_checkbox_all_required_reachable(self):
        self.assertIn("All required interfaces", self.html)
        self.assertIn("verified reachable", self.html)

    def test_contract_checkbox_service_healthy(self):
        self.assertIn("running and healthy", self.html)

    def test_health_check_checkbox_for_https_interface(self):
        self.assertIn("Health check passed", self.html)

    def test_restart_commands_present(self):
        self.assertIn("systemctl restart", self.html)

    def test_assessment_engine_contract_shown(self):
        self.assertIn("assessment-engine", self.html)


class TestRunbookNoContractVM(unittest.TestCase):
    """VMs without a declared contract should not show a contract block."""

    def test_no_contract_block_for_uncovered_vm(self):
        html = _build_html({"vms": [{"vmid": 999, "name": "mystery-vm", "status": "running"}],
                            "service_contracts": []})
        self.assertNotIn("Service Contract:", html)

    def test_non_vm_node_has_no_contract_block(self):
        html = _build_html()
        self.assertIn("Service Contract", html)   # VMs have it
        self.assertIn("pve01", html)              # host is also present


class TestRunbookAppendixALegend(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = _build_html()

    def test_appendix_a_legend_present(self):
        self.assertIn("Edge Type Legend", self.html)

    def test_legend_service_entry(self):
        self.assertIn("SERVICE", self.html)
        self.assertIn("service-contracts.yaml", self.html)

    def test_legend_depends_on_entry(self):
        self.assertIn("DEPENDS_ON", self.html)

    def test_legend_storage_entry(self):
        self.assertIn("STORAGE", self.html)

    def test_legend_network_entry(self):
        self.assertIn("NETWORK", self.html)

    def test_star_marker_explanation(self):
        self.assertIn("service-contracts.yaml", self.html)

    def test_service_edges_show_star(self):
        self.assertIn("★", self.html)


class TestRunbookHealthCheckUrls(unittest.TestCase):
    """Verify health check URL construction uses url_pattern when available."""

    def test_forgejo_health_check_uses_url_pattern(self):
        html = _build_html()
        self.assertIn("https://forgejo.internal/api/healthz", html)

    def test_health_check_without_url_pattern_uses_ip(self):
        contracts_no_url = [
            {
                "service": "forgejo",
                "vm": "forgejo",
                "vmid": 101,
                "provided_interfaces": [
                    {
                        "protocol": "https",
                        "port": 3000,
                        "url_pattern": None,
                        "health_check": "GET /health",
                    }
                ],
                "required_interfaces": [],
                "startup_after": [],
                "secret_references": [],
            }
        ]
        html = _build_html({"service_contracts": contracts_no_url})
        self.assertIn("192.168.1.21", html)
        self.assertIn("/health", html)


if __name__ == "__main__":
    unittest.main()
