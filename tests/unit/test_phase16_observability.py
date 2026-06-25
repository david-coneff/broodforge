"""
test_phase16_observability.py — Tests for Phase 16: Observability State.

Covers:
  16.1  data-model/observability-state-schema.json
  16.2  observability_collector.py — parsers, health computation
  16.3  readiness.py — _score_observability_completeness
"""

import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

import observability_collector as _obs

# ===========================================================================
# 16.1 — observability-state-schema.json
# ===========================================================================

class TestObservabilityStateSchema:
    def _schema(self):
        path = os.path.join(_ROOT, "data-model", "observability-state-schema.json")
        with open(path) as f:
            return json.load(f)

    def test_schema_loads(self):
        s = self._schema()
        assert s["title"] == "Observability State"

    def test_required_fields(self):
        s = self._schema()
        assert "cell_id" in s["required"]

    def test_prometheus_target_has_state(self):
        s = self._schema()
        target = s["definitions"]["prometheus_target"]["properties"]
        assert "state" in target

    def test_alert_rule_has_severity(self):
        s = self._schema()
        rule = s["definitions"]["alert_rule"]["properties"]
        assert "severity" in rule

    def test_valid_minimal(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")  # noqa: I001
        s = self._schema()
        jsonschema.validate({
            "schema_version": "1.0",
            "cell_id": "test-cell",
            "collected_at": "2026-06-01T12:00:00+00:00",
        }, s)


# ===========================================================================
# 16.2 — parsers
# ===========================================================================

_PROM_TARGETS_RESPONSE = {
    "status": "success",
    "data": {
        "activeTargets": [
            {
                "labels": {"job": "node-exporter", "instance": "192.168.1.10:9100"},
                "health": "up",
                "lastScrapeDuration": 0.012,
                "lastError": "",
            },
            {
                "labels": {"job": "k3s-metrics", "instance": "192.168.1.11:10250"},
                "health": "down",
                "lastScrapeDuration": 0,
                "lastError": "connection refused",
            },
        ]
    }
}

_PROM_RULES_RESPONSE = {
    "status": "success",
    "data": {
        "groups": [
            {
                "name": "broodforge-alerts",
                "rules": [
                    {
                        "type": "alerting",
                        "name": "NodeDiskFull",
                        "state": "firing",
                        "labels": {"severity": "critical"},
                        "query": "disk_used_pct > 90",
                    },
                    {
                        "type": "alerting",
                        "name": "NodeHighCPU",
                        "state": "inactive",
                        "labels": {"severity": "warning"},
                    },
                ]
            }
        ]
    }
}

_GRAFANA_DASHBOARDS_RESPONSE = [
    {"type": "dash-db", "title": "Node Overview", "uid": "abc123", "tags": ["infra"]},
    {"type": "dash-db", "title": "k3s Cluster",   "uid": "def456", "tags": ["k3s"]},
    {"type": "dash-folder", "title": "Infrastructure"},  # should be excluded
]


class TestParsePrometheusTargets:
    def test_returns_targets(self):
        targets = _obs._parse_prometheus_targets(_PROM_TARGETS_RESPONSE)
        assert len(targets) == 2

    def test_job_parsed(self):
        targets = _obs._parse_prometheus_targets(_PROM_TARGETS_RESPONSE)
        jobs = [t.job for t in targets]
        assert "node-exporter" in jobs

    def test_state_up(self):
        targets = _obs._parse_prometheus_targets(_PROM_TARGETS_RESPONSE)
        up = next(t for t in targets if t.job == "node-exporter")
        assert up.state == "up"

    def test_state_down(self):
        targets = _obs._parse_prometheus_targets(_PROM_TARGETS_RESPONSE)
        down = next(t for t in targets if t.job == "k3s-metrics")
        assert down.state == "down"

    def test_last_error_set(self):
        targets = _obs._parse_prometheus_targets(_PROM_TARGETS_RESPONSE)
        down = next(t for t in targets if t.job == "k3s-metrics")
        assert down.last_error == "connection refused"

    def test_scrape_duration_ms(self):
        targets = _obs._parse_prometheus_targets(_PROM_TARGETS_RESPONSE)
        up = next(t for t in targets if t.job == "node-exporter")
        assert up.last_scrape_duration_ms == 12.0


class TestParseAlertRules:
    def test_returns_rules(self):
        rules = _obs._parse_alert_rules(_PROM_RULES_RESPONSE)
        assert len(rules) == 2

    def test_firing_rule(self):
        rules = _obs._parse_alert_rules(_PROM_RULES_RESPONSE)
        firing = next(r for r in rules if r.name == "NodeDiskFull")
        assert firing.state == "firing"
        assert firing.severity == "critical"

    def test_inactive_rule(self):
        rules = _obs._parse_alert_rules(_PROM_RULES_RESPONSE)
        inactive = next(r for r in rules if r.name == "NodeHighCPU")
        assert inactive.state == "inactive"

    def test_group_name_set(self):
        rules = _obs._parse_alert_rules(_PROM_RULES_RESPONSE)
        assert rules[0].group == "broodforge-alerts"


class TestParseGrafanaDashboards:
    def test_returns_dashboards(self):
        dbs = _obs._parse_grafana_dashboards(_GRAFANA_DASHBOARDS_RESPONSE)
        assert len(dbs) == 2  # folder excluded

    def test_dashboard_title(self):
        dbs = _obs._parse_grafana_dashboards(_GRAFANA_DASHBOARDS_RESPONSE)
        titles = [d.title for d in dbs]
        assert "Node Overview" in titles

    def test_uid_set(self):
        dbs = _obs._parse_grafana_dashboards(_GRAFANA_DASHBOARDS_RESPONSE)
        d = next(d for d in dbs if d.title == "Node Overview")
        assert d.uid == "abc123"


# ===========================================================================
# ObservabilityDocument + health computation
# ===========================================================================

class TestComputeObservabilityHealth:
    def _doc(self, **kw):
        return _obs.ObservabilityDocument(
            cell_id="test-cell",
            collected_at="2026-06-01T12:00:00+00:00",
            **kw
        )

    def test_not_configured(self):
        doc = self._doc()
        health = _obs.compute_observability_health(doc)
        assert health["overall_status"] == "NOT_CONFIGURED"

    def test_healthy_all_up(self):
        doc = self._doc(
            prometheus_url="http://prom:9090",
            prometheus_reachable=True,
            grafana_reachable=True,
            targets=[
                _obs.PrometheusTarget(job="j", instance="i", state="up"),
            ],
        )
        health = _obs.compute_observability_health(doc)
        assert health["overall_status"] == "HEALTHY"
        assert health["targets_down"] == 0

    def test_degraded_target_down(self):
        doc = self._doc(
            prometheus_url="http://prom:9090",
            prometheus_reachable=True,
            grafana_reachable=True,
            targets=[
                _obs.PrometheusTarget(job="j", instance="i", state="down"),
            ],
        )
        health = _obs.compute_observability_health(doc)
        assert health["overall_status"] == "DEGRADED"
        assert health["targets_down"] == 1

    def test_critical_firing_alert(self):
        doc = self._doc(
            prometheus_url="http://prom:9090",
            prometheus_reachable=True,
            grafana_reachable=True,
            firing_alerts=[
                _obs.AlertRule(name="DiskFull", state="firing", severity="critical"),
            ],
        )
        health = _obs.compute_observability_health(doc)
        assert health["overall_status"] == "CRITICAL"
        assert health["firing_critical_alerts"] == 1

    def test_observability_to_dict(self):
        doc = self._doc()
        d = _obs.observability_to_dict(doc)
        assert d["schema_version"] == "1.0"
        assert "observability_health" in d


# ===========================================================================
# Injectable collector
# ===========================================================================

class TestCollectWithInjectedHttp:
    def test_collect_no_urls_no_data(self):
        doc = _obs.collect_observability_state("test-cell")
        assert doc.targets == []
        assert doc.prometheus_reachable is None

    def test_collect_with_prometheus_url(self):
        calls = []

        def mock_http_get(url):
            calls.append(url)
            if "targets" in url:
                return _PROM_TARGETS_RESPONSE
            if "rules" in url:
                return _PROM_RULES_RESPONSE
            return None

        def mock_reachable(url):
            return True

        doc = _obs.collect_observability_state(
            "test-cell",
            prometheus_url="http://prom:9090",
            http_get_fn=mock_http_get,
            reach_fn=mock_reachable,
        )
        assert doc.prometheus_reachable is True
        assert len(doc.targets) == 2
        assert len(doc.firing_alerts) == 1

    def test_collect_prometheus_unreachable(self):
        def mock_http_get(url):
            return None

        def mock_reachable(url):
            return False

        doc = _obs.collect_observability_state(
            "test-cell",
            prometheus_url="http://prom:9090",
            http_get_fn=mock_http_get,
            reach_fn=mock_reachable,
        )
        assert doc.prometheus_reachable is False
        assert doc.targets == []


# ===========================================================================
# 16.3 — readiness scoring
# ===========================================================================

from readiness import _score_observability_completeness


class TestScoreObservabilityCompleteness:
    def test_no_state_yellow(self):
        gaps = _score_observability_completeness({})
        assert gaps
        assert gaps[0].severity == "YELLOW"

    def test_not_configured_yellow(self):
        manifest = {
            "observability_state": {
                "observability_health": {"overall_status": "NOT_CONFIGURED"}
            }
        }
        gaps = _score_observability_completeness(manifest)
        assert any(g.gap_type == "OBSERVABILITY_NOT_CONFIGURED" for g in gaps)

    def test_healthy_no_gaps(self):
        manifest = {
            "observability_state": {
                "observability_health": {
                    "overall_status": "HEALTHY",
                    "prometheus_reachable": True,
                    "grafana_reachable": True,
                    "targets_down": 0,
                    "firing_critical_alerts": 0,
                    "issues": [],
                }
            }
        }
        gaps = _score_observability_completeness(manifest)
        assert not gaps

    def test_critical_alerts_orange(self):
        manifest = {
            "observability_state": {
                "observability_health": {
                    "overall_status": "CRITICAL",
                    "firing_critical_alerts": 2,
                    "issues": ["2 critical alerts firing"],
                }
            }
        }
        gaps = _score_observability_completeness(manifest)
        assert any(g.gap_type == "CRITICAL_ALERTS_FIRING" and g.severity == "ORANGE" for g in gaps)

    def test_degraded_yellow(self):
        manifest = {
            "observability_state": {
                "observability_health": {
                    "overall_status": "DEGRADED",
                    "targets_down": 1,
                    "firing_critical_alerts": 0,
                    "issues": ["1 target down"],
                }
            }
        }
        gaps = _score_observability_completeness(manifest)
        assert any(g.gap_type == "OBSERVABILITY_DEGRADED" and g.severity == "YELLOW" for g in gaps)
