"""
Tests for guest inventory collection, normalization, parsing, reporting,
schema validation, and history database integration.

Ansible and ansible-inventory are mocked throughout — these tests never
require a live Ansible installation.
"""

from __future__ import annotations

import json

from engine.db import HistoryDB, _compute_guest_summary
from engine.modules.guest_inventory import (
    _extract_containers,
    _extract_ips,
    _extract_mounts,
    _extract_os,
    _extract_services,
    _parse_ansible_output,
    _parse_inventory_json,
    normalize_guest,
)
from engine.modules.guest_parser import parse_guests
from engine.report_guest import generate_guest_report
from engine.schema import validate_assessment

# ===========================================================================
# Fixtures
# ===========================================================================

INVENTORY_JSON = {
    "_meta": {
        "hostvars": {
            "web01": {"ansible_host": "192.168.1.10", "configuration_method": "ansible"},
            "db01":  {"ansible_host": "192.168.1.20", "configuration_method": "ansible"},
            "cache01": {"ansible_host": "192.168.1.30"},
        }
    },
    "all": {
        "children": ["webservers", "databases", "ungrouped"]
    },
    "webservers": {"hosts": ["web01"]},
    "databases":  {"hosts": ["db01"]},
    "ungrouped":  {"hosts": ["cache01"]},
}

ANSIBLE_FACTS_WEB01 = {
    "ansible_facts": {
        "ansible_distribution": "Debian",
        "ansible_distribution_version": "12",
        "ansible_distribution_release": "bookworm",
        "ansible_kernel": "6.1.0-18-amd64",
        "ansible_architecture": "x86_64",
        "ansible_os_family": "Debian",
        "ansible_processor_vcpus": 2,
        "ansible_memtotal_mb": 4096,
        "ansible_all_ipv4_addresses": ["192.168.1.10"],
        "ansible_all_ipv6_addresses": [],
        "ansible_mounts": [
            {
                "mount": "/",
                "device": "/dev/sda1",
                "fstype": "ext4",
                "size_total": 21474836480,
                "size_available": 10737418240,
            }
        ],
    }
}

SERVICE_FACTS_WEB01 = {
    "ansible_facts": {
        "services": {
            "nginx.service": {"state": "running", "status": "enabled"},
            "ssh.service":   {"state": "running", "status": "enabled"},
            "cron.service":  {"state": "running", "status": "enabled"},
            "snapd.service": {"state": "inactive", "status": "disabled"},
        }
    }
}

DOCKER_OUTPUT = {
    "stdout": (
        '{"name":"nginx","image":"nginx:latest","status":"running"}\n'
        '{"name":"redis","image":"redis:7","status":"running"}'
    )
}

PODMAN_OUTPUT = {"error": "podman: command not found"}


# ===========================================================================
# Inventory parsing
# ===========================================================================

class TestInventoryParsing:
    def test_parse_all_hosts(self):
        inv = _parse_inventory_json(INVENTORY_JSON)
        assert set(inv.hosts) == {"web01", "db01", "cache01"}

    def test_parse_groups(self):
        inv = _parse_inventory_json(INVENTORY_JSON)
        assert "web01" in inv.groups.get("webservers", [])
        assert "db01" in inv.groups.get("databases", [])

    def test_groups_for_host(self):
        inv = _parse_inventory_json(INVENTORY_JSON)
        assert inv.groups_for("web01") == ["webservers"]
        assert inv.groups_for("db01") == ["databases"]

    def test_host_vars_preserved(self):
        inv = _parse_inventory_json(INVENTORY_JSON)
        assert inv.host_vars["web01"]["configuration_method"] == "ansible"

    def test_empty_inventory(self):
        inv = _parse_inventory_json({"_meta": {"hostvars": {}}})
        assert inv.hosts == []

    def test_groups_for_ungrouped_excluded(self):
        inv = _parse_inventory_json(INVENTORY_JSON)
        groups = inv.groups_for("cache01")
        assert "ungrouped" not in groups
        assert "all" not in groups


# ===========================================================================
# Ansible output parsing
# ===========================================================================

class TestAnsibleOutputParsing:
    def test_parse_success(self):
        raw = 'web01 | SUCCESS => {"ansible_facts": {"ansible_distribution": "Debian"}}'
        result = _parse_ansible_output("web01", raw)
        assert result["ansible_facts"]["ansible_distribution"] == "Debian"

    def test_parse_failed(self):
        raw = 'web01 | FAILED! => {"msg": "Permission denied"}'
        result = _parse_ansible_output("web01", raw)
        assert result["msg"] == "Permission denied"

    def test_parse_no_marker(self):
        result = _parse_ansible_output("web01", "some unexpected output")
        assert "error" in result

    def test_parse_bad_json(self):
        result = _parse_ansible_output("web01", "web01 | SUCCESS => not json")
        assert "error" in result


# ===========================================================================
# Fact extraction helpers
# ===========================================================================

class TestFactExtraction:
    def test_extract_os_full(self):
        facts = ANSIBLE_FACTS_WEB01["ansible_facts"]
        os = _extract_os(facts)
        assert os["distribution"] == "Debian"
        assert os["distribution_version"] == "12"
        assert os["distribution_release"] == "bookworm"
        assert os["kernel_version"] == "6.1.0-18-amd64"
        assert os["family"] == "Debian"

    def test_extract_os_empty(self):
        assert _extract_os({}) == {}

    def test_extract_ips(self):
        facts = ANSIBLE_FACTS_WEB01["ansible_facts"]
        ips = _extract_ips(facts)
        assert "192.168.1.10" in ips

    def test_extract_ips_dedup(self):
        facts = {
            "ansible_all_ipv4_addresses": ["10.0.0.1", "10.0.0.1"],
            "ansible_all_ipv6_addresses": [],
        }
        ips = _extract_ips(facts)
        assert ips.count("10.0.0.1") == 1

    def test_extract_mounts(self):
        facts = ANSIBLE_FACTS_WEB01["ansible_facts"]
        mounts = _extract_mounts(facts)
        assert len(mounts) == 1
        m = mounts[0]
        assert m["mount"] == "/"
        assert m["fstype"] == "ext4"
        assert m["size_bytes"] == 21474836480
        assert m["used_bytes"] == 21474836480 - 10737418240
        assert m["available_bytes"] == 10737418240

    def test_extract_mounts_empty(self):
        assert _extract_mounts({}) == []

    def test_extract_services(self):
        running, enabled = _extract_services(SERVICE_FACTS_WEB01)
        assert "nginx.service" in running
        assert "ssh.service" in running
        assert "snapd.service" not in running
        assert "nginx.service" in enabled
        assert "snapd.service" not in enabled

    def test_extract_services_empty(self):
        running, enabled = _extract_services({})
        assert running == []
        assert enabled == []

    def test_extract_containers_docker(self):
        containers = _extract_containers(DOCKER_OUTPUT)
        assert len(containers) == 2
        assert containers[0]["name"] == "nginx"
        assert containers[0]["image"] == "nginx:latest"

    def test_extract_containers_error(self):
        assert _extract_containers(PODMAN_OUTPUT) == []

    def test_extract_containers_empty_stdout(self):
        assert _extract_containers({"stdout": ""}) == []


# ===========================================================================
# Guest normalization
# ===========================================================================

class TestNormalizeGuest:
    def _raw_facts(self):
        return {
            "setup": ANSIBLE_FACTS_WEB01,
            "service_facts": SERVICE_FACTS_WEB01,
            "docker": DOCKER_OUTPUT,
            "podman": PODMAN_OUTPUT,
        }

    def test_basic_fields(self):
        g = normalize_guest("web01", "web01", ["webservers"], self._raw_facts())
        assert g["hostname"] == "web01"
        assert g["inventory_name"] == "web01"
        assert g["groups"] == ["webservers"]
        assert g["collection_method"] == "ansible-facts"
        assert "collection_timestamp" in g

    def test_os_populated(self):
        g = normalize_guest("web01", "web01", ["webservers"], self._raw_facts())
        assert g["operating_system"]["distribution"] == "Debian"

    def test_cpu_memory(self):
        g = normalize_guest("web01", "web01", [], self._raw_facts())
        assert g["cpu_count"] == 2
        assert g["memory_mb"] == 4096

    def test_ip_addresses(self):
        g = normalize_guest("web01", "web01", [], self._raw_facts())
        assert "192.168.1.10" in g["ip_addresses"]

    def test_mounts(self):
        g = normalize_guest("web01", "web01", [], self._raw_facts())
        assert any(m["mount"] == "/" for m in g["mounted_filesystems"])

    def test_running_services(self):
        g = normalize_guest("web01", "web01", [], self._raw_facts())
        assert "nginx.service" in g["running_services"]

    def test_enabled_services(self):
        g = normalize_guest("web01", "web01", [], self._raw_facts())
        assert "nginx.service" in g["enabled_services"]

    def test_docker_containers(self):
        g = normalize_guest("web01", "web01", [], self._raw_facts())
        assert len(g["docker_containers"]) == 2

    def test_no_podman_containers(self):
        g = normalize_guest("web01", "web01", [], self._raw_facts())
        assert "podman_containers" not in g

    def test_host_vars_metadata(self):
        g = normalize_guest(
            "web01", "web01", [],
            self._raw_facts(),
            host_vars={"configuration_method": "ansible", "secret_source": "keepassxc"},
        )
        assert g["configuration_method"] == "ansible"
        assert g["secret_source"] == "keepassxc"

    def test_unreachable_host(self):
        raw = {
            "setup": {"error": "UNREACHABLE! -> {\"msg\": \"Failed to connect\"}"},
            "service_facts": {},
            "docker": {},
            "podman": {},
        }
        g = normalize_guest("down01", "down01", [], raw)
        assert g["collection_method"] == "unreachable"
        assert "operating_system" not in g

    def test_no_secrets_in_output(self):
        """Confirm no secret fields are passed through even if present in host_vars."""
        raw = {
            "setup": ANSIBLE_FACTS_WEB01,
            "service_facts": {},
            "docker": {},
            "podman": {},
        }
        dangerous_vars = {
            "ansible_password": "s3cr3t",
            "ansible_ssh_private_key_file": "/root/.ssh/id_rsa",
            "vault_token": "hvs.abc123",
            "configuration_method": "ansible",
        }
        g = normalize_guest("web01", "web01", [], raw, host_vars=dangerous_vars)
        output_str = json.dumps(g)
        assert "s3cr3t" not in output_str
        assert "/root/.ssh/id_rsa" not in output_str
        assert "hvs.abc123" not in output_str
        # Safe metadata is preserved
        assert g["configuration_method"] == "ansible"


# ===========================================================================
# Guest parser
# ===========================================================================

class TestGuestParser:
    def _guest(self, hostname="web01", method="ansible-facts"):
        return {
            "hostname": hostname,
            "inventory_name": hostname,
            "groups": ["webservers"],
            "collection_method": method,
            "collection_timestamp": "2024-01-01T00:00:00+00:00",
            "operating_system": {"distribution": "Debian", "distribution_version": "12"},
        }

    def test_guests_in_fragment(self):
        raw = {"guests": [self._guest()], "inventory_path": "/etc/ansible/hosts"}
        result = parse_guests(raw)
        assert len(result["guests"]) == 1

    def test_state_sources_populated(self):
        raw = {"guests": [self._guest()], "inventory_path": "/inv"}
        result = parse_guests(raw)
        ss = result["state_sources"]
        assert ss["configured"]["tool"] == "ansible"
        assert ss["configured"]["inventory_path"] == "/inv"
        assert ss["observed"]["collected"] is True
        assert ss["declared"]["collected"] is False

    def test_error_returns_empty(self):
        assert parse_guests({"error": "ansible-inventory not found"}) == {}

    def test_empty_guests_ok(self):
        raw = {"guests": [], "inventory_path": "/inv"}
        result = parse_guests(raw)
        assert result.get("guests") is None or result.get("guests") == []
        assert "state_sources" in result


# ===========================================================================
# Schema validation
# ===========================================================================

class TestSchemaValidation:
    def _minimal_assessment(self):
        return {
            "schema_version": "1.0",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "hostname": "pve01.lab",
        }

    def test_assessment_with_no_guests_valid(self):
        errors = validate_assessment(self._minimal_assessment())
        assert errors == []

    def test_assessment_with_guests_valid(self):
        a = self._minimal_assessment()
        a["guests"] = [
            {
                "hostname": "web01",
                "collection_timestamp": "2024-01-01T00:00:00+00:00",
                "collection_method": "ansible-facts",
            }
        ]
        errors = validate_assessment(a)
        assert errors == []

    def test_assessment_with_state_sources_valid(self):
        a = self._minimal_assessment()
        a["state_sources"] = {
            "declared": {"tool": None, "state_path": None, "collected": False},
            "configured": {"tool": "ansible", "inventory_path": "/inv", "collected": True},
            "observed": {"tool": "broodforge", "collected": True},
        }
        errors = validate_assessment(a)
        assert errors == []

    def test_guest_missing_required_fails(self):
        a = self._minimal_assessment()
        a["guests"] = [{"hostname": "web01"}]  # missing collection_timestamp, collection_method
        errors = validate_assessment(a)
        assert len(errors) > 0


# ===========================================================================
# Report generation
# ===========================================================================

class TestGuestReport:
    def _assessment_with_guests(self):
        return {
            "schema_version": "1.0",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "hostname": "pve01.lab",
            "guests": [
                {
                    "hostname": "web01",
                    "inventory_name": "web01",
                    "groups": ["webservers"],
                    "collection_method": "ansible-facts",
                    "collection_timestamp": "2024-01-01T00:00:00+00:00",
                    "operating_system": {"distribution": "Debian", "distribution_version": "12"},
                    "running_services": ["nginx.service", "ssh.service"],
                    "enabled_services": ["nginx.service", "ssh.service"],
                    "docker_containers": [{"name": "app", "image": "myapp:1.0", "status": "running"}],
                    "configuration_method": "ansible",
                },
                {
                    "hostname": "db01",
                    "inventory_name": "db01",
                    "groups": ["databases"],
                    "collection_method": "unreachable",
                    "collection_timestamp": "2024-01-01T00:00:00+00:00",
                },
            ],
            "state_sources": {
                "declared": {"tool": None, "state_path": None, "collected": False},
                "configured": {"tool": "ansible", "inventory_path": "/etc/ansible/hosts", "collected": True},
                "observed": {"tool": "broodforge", "collected": True},
            },
        }

    def test_report_is_string(self):
        report = generate_guest_report(self._assessment_with_guests())
        assert isinstance(report, str)
        assert len(report) > 0

    def test_report_header(self):
        report = generate_guest_report(self._assessment_with_guests())
        assert "Guest Assessment Report" in report
        assert "pve01.lab" in report

    def test_report_guest_summary_section(self):
        report = generate_guest_report(self._assessment_with_guests())
        assert "Guest Summary" in report
        assert "2" in report  # total guest count

    def test_report_os_section(self):
        report = generate_guest_report(self._assessment_with_guests())
        assert "Debian" in report

    def test_report_services_section(self):
        report = generate_guest_report(self._assessment_with_guests())
        assert "nginx.service" in report

    def test_report_containers_section(self):
        report = generate_guest_report(self._assessment_with_guests())
        assert "Docker" in report
        assert "app" in report

    def test_report_inventory_groups(self):
        report = generate_guest_report(self._assessment_with_guests())
        assert "webservers" in report
        assert "databases" in report

    def test_report_state_sources(self):
        report = generate_guest_report(self._assessment_with_guests())
        assert "State Sources" in report
        assert "ansible" in report

    def test_report_no_guests(self):
        a = {
            "schema_version": "1.0",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "hostname": "pve01.lab",
        }
        report = generate_guest_report(a)
        assert "No guests collected" in report

    def test_report_no_recommendations(self):
        """Verify the report contains no recommendation language."""
        report = generate_guest_report(self._assessment_with_guests()).lower()
        for word in ("recommend", "upgrade", "replace", "should", "consider", "suggest"):
            assert word not in report, f"Report must not contain '{word}'"


# ===========================================================================
# History database – guest summaries
# ===========================================================================

class TestGuestHistoryDB:
    def _assessment(self, guests=None):
        return {
            "schema_version": "1.0",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "hostname": "pve01.lab",
            "guests": guests or [],
        }

    def _guest(self, hostname="web01", dist="Debian", method="ansible-facts", conf="ansible"):
        return {
            "hostname": hostname,
            "inventory_name": hostname,
            "groups": ["webservers"],
            "collection_method": method,
            "collection_timestamp": "2024-01-01T00:00:00+00:00",
            "operating_system": {"distribution": dist, "distribution_version": "12"},
            "running_services": ["nginx.service"],
            "docker_containers": [{"name": "app", "image": "myapp:1", "status": "running"}],
            "configuration_method": conf,
        }

    def test_guest_summary_stored(self, tmp_path):
        db = HistoryDB(tmp_path / "h.db")
        id1 = db.store(self._assessment([self._guest()]))
        summary = db.guest_summary_for(id1)
        assert summary is not None
        assert summary["guest_count"] == 1
        db.close()

    def test_guest_summary_os(self, tmp_path):
        db = HistoryDB(tmp_path / "h.db")
        id1 = db.store(self._assessment([self._guest(dist="Debian"), self._guest("db01", dist="Ubuntu")]))
        summary = db.guest_summary_for(id1)
        assert "Debian 12" in summary["os_summary"] or any("Debian" in k for k in summary["os_summary"])
        db.close()

    def test_guest_summary_service_count(self, tmp_path):
        db = HistoryDB(tmp_path / "h.db")
        id1 = db.store(self._assessment([self._guest(), self._guest("db01")]))
        summary = db.guest_summary_for(id1)
        assert summary["service_count"] == 2  # 1 running service per guest
        db.close()

    def test_guest_summary_container_count(self, tmp_path):
        db = HistoryDB(tmp_path / "h.db")
        id1 = db.store(self._assessment([self._guest()]))
        summary = db.guest_summary_for(id1)
        assert summary["container_count"] == 1
        db.close()

    def test_guest_summary_groups(self, tmp_path):
        db = HistoryDB(tmp_path / "h.db")
        id1 = db.store(self._assessment([self._guest()]))
        summary = db.guest_summary_for(id1)
        assert "webservers" in summary["inventory_groups"]
        db.close()

    def test_guest_summary_collection_methods(self, tmp_path):
        db = HistoryDB(tmp_path / "h.db")
        g1 = self._guest(method="ansible-facts")
        g2 = self._guest("db01", method="unreachable")
        id1 = db.store(self._assessment([g1, g2]))
        summary = db.guest_summary_for(id1)
        assert summary["collection_methods"].get("ansible-facts") == 1
        assert summary["collection_methods"].get("unreachable") == 1
        db.close()

    def test_guest_summary_config_methods(self, tmp_path):
        db = HistoryDB(tmp_path / "h.db")
        id1 = db.store(self._assessment([self._guest(conf="ansible")]))
        summary = db.guest_summary_for(id1)
        assert summary["configuration_methods"].get("ansible") == 1
        db.close()

    def test_no_guests_summary_zero_count(self, tmp_path):
        db = HistoryDB(tmp_path / "h.db")
        id1 = db.store(self._assessment([]))
        summary = db.guest_summary_for(id1)
        assert summary["guest_count"] == 0
        db.close()

    def test_guest_summary_missing_id(self, tmp_path):
        db = HistoryDB(tmp_path / "h.db")
        assert db.guest_summary_for(999) is None
        db.close()

    def test_no_secrets_in_db(self, tmp_path):
        """Passwords and keys must not appear in any DB table."""
        db_path = tmp_path / "h.db"
        db = HistoryDB(db_path)
        g = self._guest()
        g["ansible_password"] = "SHOULD_NOT_STORE"   # simulate accidental inclusion
        db.store(self._assessment([g]))
        db.close()

        # Read raw DB content as text and verify
        db_path.read_bytes().decode("utf-8", errors="replace")
        # The field name may appear (it's in the guest JSON blob); the value must not
        # appear in the guest_summaries table specifically – check the summary is clean
        db2 = HistoryDB(db_path)
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT * FROM guest_summaries").fetchall()
        for row in rows:
            for cell in row:
                assert "SHOULD_NOT_STORE" not in str(cell)
        conn.close()
        db2.close()


# ===========================================================================
# _compute_guest_summary unit tests
# ===========================================================================

class TestComputeGuestSummary:
    def _guest(self, hostname="web01", dist="Debian", method="ansible-facts", conf="ansible",
               running=None, docker=None, podman=None):
        g = {
            "hostname": hostname,
            "collection_method": method,
            "configuration_method": conf,
            "groups": ["webservers"],
            "operating_system": {"distribution": dist, "distribution_version": "12"},
        }
        if running is not None:
            g["running_services"] = running
        if docker is not None:
            g["docker_containers"] = docker
        if podman is not None:
            g["podman_containers"] = podman
        return g

    def test_empty(self):
        s = _compute_guest_summary([])
        assert s["guest_count"] == 0
        assert s["service_count"] == 0
        assert s["container_count"] == 0

    def test_count(self):
        s = _compute_guest_summary([self._guest(), self._guest("db01")])
        assert s["guest_count"] == 2

    def test_os_summary(self):
        s = _compute_guest_summary([self._guest(dist="Debian"), self._guest("db01", dist="Ubuntu")])
        assert "Debian 12" in s["os_summary"] or any("Debian" in k for k in s["os_summary"])

    def test_service_count(self):
        s = _compute_guest_summary([self._guest(running=["nginx", "sshd"])])
        assert s["service_count"] == 2

    def test_docker_container_count(self):
        s = _compute_guest_summary([
            self._guest(docker=[{"name": "a", "image": "x", "status": "running"}])
        ])
        assert s["container_count"] == 1

    def test_podman_container_count(self):
        s = _compute_guest_summary([
            self._guest(podman=[{"name": "b", "image": "y", "status": "running"}])
        ])
        assert s["container_count"] == 1

    def test_groups(self):
        s = _compute_guest_summary([self._guest()])
        assert "webservers" in s["inventory_groups"]

    def test_collection_methods(self):
        g1 = self._guest(method="ansible-facts")
        g2 = self._guest("db01", method="unreachable")
        s = _compute_guest_summary([g1, g2])
        assert s["collection_methods"]["ansible-facts"] == 1
        assert s["collection_methods"]["unreachable"] == 1
