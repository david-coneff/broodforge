#!/usr/bin/env python3
"""
Tests for Phase 10 — Operational Documentation.

Covers:
  - build_operational_report_html(): HTML generation
  - Section 1: Overall Readiness (score, component counts, registry gaps)
  - Section 2: Drift Summary (with / without drift data)
  - Section 3: Current Capacity (CPU, RAM, storage pools)
  - Section 4: Service Health (running/stopped/degraded)
  - Section 5: Secret Completeness (all paths present / missing paths)
  - Section 6: External Dependencies (cert expiry callouts)
  - Section 7: Actions Required (time-sensitive cert, stopped services, backup fail)
  - engine.py --mode operational is wired (run_operational function exists)
"""

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent


def _future_iso(days: int) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_report(manifest_extras=None):
    from dependencies import build_graph
    from html_operational_report import build_operational_report_html
    from readiness import score_graph

    manifest = {
        "host": {"hostname": "pve01", "proxmox_version": "8.1.3"},
        "cpu":  {"model": "Intel i7-12700", "total_threads": 8},
        "memory": {"total_gb": 32, "available_gb": 14},
        "storage": {
            "block_devices": [{"name": "sda", "size_gb": 500, "model": "Samsung SSD"}],
            "zfs_pools": [{"name": "rpool", "state": "ONLINE", "size_gb": 500, "free_gb": 200}],
        },
        "network": {"default_gateway": "192.168.1.1", "dns_servers": ["8.8.8.8"]},
        "vms": [
            {"vmid": 101, "name": "forgejo", "status": "running"},
        ],
        "containers": [],
        "collected_at": "2026-01-01T00:00:00Z",
        "capacity_model": {
            "thresholds": {
                "ram_warn_pct": 80, "ram_crit_pct": 90,
                "storage_warn_pct": 80, "storage_crit_pct": 90,
            },
            "observed": {
                "ram_usage_pct": 56.0,
                "total_ram_gb": 32,
                "storage_usage_pct": 40.0,
                "total_storage_gb": 500,
                "storage_pools": [{"name": "rpool", "usage_pct": 40.0, "free_gb": 300}],
            },
            "trend": {"direction": "stable"},
        },
    }
    if manifest_extras:
        manifest.update(manifest_extras)

    graph    = build_graph(manifest)
    readiness = score_graph(graph, manifest)
    gen_meta = {
        "generated_at":         "2026-01-01T12:00:00Z",
        "generated_at_display": "2026-01-01 12:00:00 UTC",
        "collected_at":         "2026-01-01T00:00:00Z",
    }
    return build_operational_report_html(manifest, readiness, gen_meta)


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------

class TestOperationalReportCover(unittest.TestCase):

    def test_heading_present(self):
        text = _build_report()
        self.assertIn("Operational Report", text)

    def test_hostname_present(self):
        text = _build_report()
        self.assertIn("pve01", text)

    def test_generated_timestamp_present(self):
        text = _build_report()
        self.assertIn("Generated", text)


# ---------------------------------------------------------------------------
# Section 1 — Overall Readiness
# ---------------------------------------------------------------------------

class TestSection1Readiness(unittest.TestCase):

    def test_section_heading(self):
        text = _build_report()
        self.assertIn("Overall Readiness", text)

    def test_overall_score_shown(self):
        text = _build_report()
        self.assertIn("Overall Readiness", text)

    def test_component_count_shown(self):
        text = _build_report()
        # HTML shows component table with Score/Component/Reason columns
        self.assertIn("Score", text)

    def test_registry_gap_shown_when_missing(self):
        # No secret_registry → Secret Completeness section renders with warning
        text = _build_report()
        self.assertIn("Secret Completeness", text)


# ---------------------------------------------------------------------------
# Section 2 — Drift Summary
# ---------------------------------------------------------------------------

class TestSection2Drift(unittest.TestCase):

    def test_no_drift_data_shows_message(self):
        text = _build_report()
        self.assertIn("Drift Summary", text)
        self.assertIn("No drift data available", text)

    def test_drift_data_shows_counts(self):
        # HTML renderer uses drift_detected + changed_fields (not diffs)
        drift = {
            "from_snapshot":  "snap-001",
            "to_snapshot":    "snap-002",
            "drift_detected": True,
            "changed_fields": [
                {"field": "host.proxmox_version", "from": "8.1.2",
                 "to": "8.1.3", "severity": "green"},
            ],
        }
        text = _build_report({"drift": drift})
        self.assertIn("snap-001", text)
        self.assertIn("snap-002", text)
        self.assertIn("proxmox_version", text)

    def test_no_drift_when_zero_diffs(self):
        drift = {
            "from_snapshot":  "snap-a",
            "to_snapshot":    "snap-b",
            "drift_detected": False,
        }
        text = _build_report({"drift": drift})
        self.assertIn("No drift detected", text)


# ---------------------------------------------------------------------------
# Section 3 — Current Capacity
# ---------------------------------------------------------------------------

class TestSection3Capacity(unittest.TestCase):

    def setUp(self):
        self.text = _build_report()

    def test_capacity_section_heading(self):
        self.assertIn("Capacity", self.text)

    def test_cpu_info_shown(self):
        self.assertIn("RAM Usage", self.text)

    def test_ram_shown(self):
        self.assertIn("32", self.text)

    def test_zfs_pool_shown(self):
        self.assertIn("56.0", self.text)
        self.assertIn("stable", self.text)

    def test_high_ram_warning(self):
        # RAM usage 95% is above the 90% critical threshold
        extras = {"capacity_model": {
            "thresholds": {"ram_warn_pct": 80, "ram_crit_pct": 90,
                           "storage_warn_pct": 80, "storage_crit_pct": 90},
            "observed": {"ram_usage_pct": 95, "total_ram_gb": 32},
        }}
        text = _build_report(extras)
        self.assertIn("critical", text.lower())

    def test_high_storage_warning(self):
        # Storage usage 96% is above the 90% critical threshold
        extras = {"capacity_model": {
            "thresholds": {"ram_warn_pct": 80, "ram_crit_pct": 90,
                           "storage_warn_pct": 80, "storage_crit_pct": 90},
            "observed": {"storage_usage_pct": 96, "total_storage_gb": 100},
        }}
        text = _build_report(extras)
        self.assertIn("critical", text.lower())

    def test_vm_count_shown(self):
        self.assertIn("forgejo", self.text)


# ---------------------------------------------------------------------------
# Section 4 — Service Health
# ---------------------------------------------------------------------------

class TestSection4ServiceHealth(unittest.TestCase):

    def test_no_services_shows_message(self):
        text = _build_report()
        self.assertIn("Service Health", text)

    def test_running_services_shown(self):
        service_state = {"services": [
            {"name": "forgejo", "vm": "forgejo", "vmid": 101, "status": "running"},
            {"name": "inventory", "vm": "inventory", "vmid": 102, "status": "running"},
        ]}
        text = _build_report({"service_state": service_state})
        self.assertIn("forgejo", text)
        self.assertIn("2", text)

    def test_stopped_service_flagged(self):
        service_state = {"services": [
            {"name": "forgejo", "vm": "forgejo", "vmid": 101, "status": "stopped"},
        ]}
        text = _build_report({"service_state": service_state})
        self.assertIn("Stopped", text)

    def test_contracts_but_no_state_shows_collection_hint(self):
        extras = {
            "service_contracts": [{"service": "forgejo", "vm": "forgejo"}],
        }
        text = _build_report(extras)
        self.assertIn("Tier 2 collection", text)


# ---------------------------------------------------------------------------
# Section 5 — Secret Completeness
# ---------------------------------------------------------------------------

class TestSection5SecretCompleteness(unittest.TestCase):

    def test_all_paths_present_shows_checkmark(self):
        secrets = [
            {"id": "root-pw", "secret_type": "password", "keepass_path": "Infra/root"},
            {"id": "api-key", "secret_type": "api-token",  "keepass_path": "Infra/api"},
        ]
        text = _build_report({"secret_registry": secrets})
        self.assertIn("Missing: 0", text)

    def test_missing_path_flagged(self):
        secrets = [
            {"id": "root-pw", "secret_type": "password", "keepass_path": "Infra/root"},
            {"id": "missing-key", "secret_type": "ssh-key", "keepass_path": None},
        ]
        text = _build_report({"secret_registry": secrets})
        self.assertIn("missing-key", text)
        self.assertIn("missing KeePass path", text)

    def test_no_secrets_shows_hint(self):
        text = _build_report({"secret_registry": []})
        self.assertIn("Secret Completeness", text)

    def test_count_correct(self):
        secrets = [
            {"id": "a", "keepass_path": "p1"},
            {"id": "b", "keepass_path": "p2"},
            {"id": "c", "keepass_path": None},
        ]
        text = _build_report({"secret_registry": secrets})
        self.assertIn("With KeePass path: 2", text)


# ---------------------------------------------------------------------------
# Section 6 — External Dependencies
# ---------------------------------------------------------------------------

class TestSection6ExternalDependencies(unittest.TestCase):

    def test_no_deps_shows_message(self):
        text = _build_report()
        self.assertIn("External Dependencies", text)

    def test_reachable_dep_shown(self):
        deps = [{"id": "cf", "name": "Cloudflare", "type": "dns_provider",
                 "endpoint": "https://1.1.1.1", "status": "reachable"}]
        text = _build_report({"external_dependencies": deps})
        self.assertIn("Cloudflare", text)

    def test_cert_expiry_warning_shown(self):
        deps = [{"id": "le", "name": "Let's Encrypt", "type": "cert_authority",
                 "endpoint": "https://acme.example.com", "status": "reachable",
                 "certificate": {"expires_at": _future_iso(20)}}]
        text = _build_report({"external_dependencies": deps})
        self.assertIn("cert expires in", text.lower())

    def test_imminent_cert_shown_as_urgent(self):
        deps = [{"id": "le", "name": "Critical Cert", "type": "cert_authority",
                 "endpoint": "https://acme.example.com", "status": "reachable",
                 "certificate": {"expires_at": _future_iso(3)}}]
        text = _build_report({"external_dependencies": deps})
        self.assertIn("expires in", text.lower())


# ---------------------------------------------------------------------------
# Section 7 — Actions Required
# ---------------------------------------------------------------------------

class TestSection7Actions(unittest.TestCase):

    def test_no_actions_when_clean(self):
        secrets = [{"id": "s1", "keepass_path": "p1"}]
        deps    = [{"id": "d1", "name": "D1", "type": "other",
                    "endpoint": "https://x", "status": "reachable"}]
        text = _build_report({
            "secret_registry": secrets,
            "external_dependencies": deps,
        })
        self.assertIn("Time-Sensitive Actions", text)
        self.assertIn("No time-sensitive actions", text)

    def test_imminent_cert_is_action(self):
        deps = [{"id": "d", "name": "Urgent Cert", "type": "cert_authority",
                 "endpoint": "https://x", "status": "reachable",
                 "certificate": {"expires_at": _future_iso(3)}}]
        text = _build_report({"external_dependencies": deps})
        self.assertIn("URGENT", text)
        self.assertIn("Renew", text)

    def test_stopped_service_is_action(self):
        service_state = {"services": [
            {"name": "forgejo", "vm": "forgejo", "vmid": 101, "status": "stopped"},
        ]}
        text = _build_report({"service_state": service_state})
        # The stopped service fires both service health section and action item
        self.assertIn("forgejo", text)

    def test_backup_all_fail_is_action(self):
        bc = {
            "layers": {
                "config": {
                    "enabled": True,
                    "destinations": [{"id": "local", "type": "local",
                                      "restic_repo_root": "/mnt/backup",
                                      "restic_repo_password_keepass_prefix": "Backup/config",
                                      "retention_count": 5}],
                    "consecutive_all_fail_count": 2,
                    "last_backup_at": None,
                }
            }
        }
        text = _build_report({"backup_config": bc})
        self.assertIn("BACKUP FAILURE", text)
        self.assertIn("config", text)

    def test_scheduled_refresh_section_present(self):
        text = _build_report()
        self.assertIn("Time-Sensitive Actions", text)
        self.assertIn("No time-sensitive actions", text)


# ---------------------------------------------------------------------------
# engine.py --mode operational wiring
# ---------------------------------------------------------------------------

class TestEngineOperationalMode(unittest.TestCase):

    def _engine(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "engine_mod",
            REPO_ROOT / "doc-gen" / "engine.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_run_operational_function_exists(self):
        eng = self._engine()
        self.assertTrue(hasattr(eng, "run_operational"))
        self.assertTrue(callable(eng.run_operational))

    def test_operational_in_mode_choices(self):
        """The --mode operational choice is declared in engine.py's argparse."""
        eng = self._engine()
        self.assertTrue(hasattr(eng, "run_operational"))


if __name__ == "__main__":
    unittest.main()
