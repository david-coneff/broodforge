#!/usr/bin/env python3
"""
observability_collector.py — Observability State collector (Phase 16.2).

Collects monitoring stack health: Prometheus target status, firing alerts,
Grafana dashboard presence, and log collection configuration.

Produces observability-state.json conforming to
data-model/observability-state-schema.json.

Uses HTTP queries against the Prometheus API and Grafana API (no auth required
for basic status endpoints in homelab configurations).

Provides:
  PrometheusTarget, AlertRule, DashboardEntry  — typed entries
  ObservabilityDocument                         — typed result
  collect_observability_state()                 — main entry point
  compute_observability_health()               — aggregate health
  observability_to_dict()                      — JSON-serialisable dict

Stdlib only.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PrometheusTarget:
    job:           str
    instance:      str
    state:         Optional[str]   = None   # up, down, unknown
    labels:        dict            = field(default_factory=dict)
    last_scrape_duration_ms: Optional[float] = None
    last_error:    Optional[str]   = None


@dataclass
class AlertRule:
    name:     str
    group:    Optional[str] = None
    state:    Optional[str] = None   # firing, pending, inactive
    severity: Optional[str] = None
    expr:     Optional[str] = None
    for_duration: Optional[str] = None


@dataclass
class DashboardEntry:
    title:  str
    uid:    Optional[str] = None
    url:    Optional[str] = None
    tags:   list[str] = field(default_factory=list)


@dataclass
class ObservabilityDocument:
    cell_id:           str
    collected_at:      str
    prometheus_url:    Optional[str]         = None
    prometheus_version: Optional[str]        = None
    prometheus_reachable: Optional[bool]     = None
    targets:           list[PrometheusTarget] = field(default_factory=list)
    alert_rules:       list[AlertRule]        = field(default_factory=list)
    firing_alerts:     list[AlertRule]        = field(default_factory=list)
    grafana_url:       Optional[str]         = None
    grafana_reachable: Optional[bool]        = None
    grafana_version:   Optional[str]         = None
    dashboards:        list[DashboardEntry]  = field(default_factory=list)
    alertmanager_url:  Optional[str]         = None
    alertmanager_reachable: Optional[bool]   = None
    active_alerts:     Optional[int]         = None
    log_tool:          Optional[str]         = None
    log_reachable:     Optional[bool]        = None
    log_sources:       list[str]             = field(default_factory=list)
    collection_errors: list[dict]            = field(default_factory=list)


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _http_get_json(url: str, timeout: int = 5) -> Optional[dict]:
    """Fetch JSON from a URL. Returns None on any error."""
    try:
        if urlparse(url).scheme not in ("http", "https"):
            return None
        req = Request(url, headers={"Accept": "application/json"})  # noqa: S310  # nosec B310
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310  # nosec B310
            return json.loads(resp.read().decode())
    except (URLError, json.JSONDecodeError, Exception):
        return None


def _is_reachable(url: str, timeout: int = 5) -> bool:
    try:
        if urlparse(url).scheme not in ("http", "https"):
            return False
        req = Request(url, headers={"Accept": "application/json"})  # noqa: S310  # nosec B310
        with urlopen(req, timeout=timeout):  # noqa: S310  # nosec B310
            return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_prometheus_targets(data: dict) -> list[PrometheusTarget]:
    """Parse Prometheus /api/v1/targets response."""
    targets = []
    active = (data.get("data") or {}).get("activeTargets") or []
    for t in active:
        labels = t.get("labels") or {}
        last_dur = t.get("lastScrapeDuration")
        targets.append(PrometheusTarget(
            job=labels.get("job", "unknown"),
            instance=labels.get("instance", "unknown"),
            state=t.get("health"),  # up/down/unknown
            labels=labels,
            last_scrape_duration_ms=round(float(last_dur) * 1000, 2) if last_dur else None,
            last_error=t.get("lastError") or None,
        ))
    return targets


def _parse_alert_rules(data: dict) -> list[AlertRule]:
    """Parse Prometheus /api/v1/rules response."""
    rules = []
    for group in ((data.get("data") or {}).get("groups") or []):
        group_name = group.get("name")
        for rule in (group.get("rules") or []):
            if rule.get("type") != "alerting":
                continue
            labels = rule.get("labels") or {}
            rules.append(AlertRule(
                name=rule.get("name") or "unknown",
                group=group_name,
                state=rule.get("state"),
                severity=labels.get("severity"),
                expr=rule.get("query") or rule.get("expr"),
                for_duration=rule.get("duration"),
            ))
    return rules


def _parse_grafana_dashboards(data: dict) -> list[DashboardEntry]:
    """Parse Grafana /api/search response."""
    dashboards = []
    items = data if isinstance(data, list) else (data.get("data") or [])
    for item in items:
        if isinstance(item, dict) and item.get("type") == "dash-db":
            dashboards.append(DashboardEntry(
                title=item.get("title") or "unknown",
                uid=item.get("uid"),
                url=item.get("url"),
                tags=item.get("tags") or [],
            ))
    return dashboards


# ---------------------------------------------------------------------------
# Observability health aggregation (Phase 16.3)
# ---------------------------------------------------------------------------

def compute_observability_health(doc: ObservabilityDocument) -> dict:
    """Derive observability_health dict from ObservabilityDocument."""
    issues = []

    # Prometheus reachability
    prom_ok = doc.prometheus_reachable
    if prom_ok is False:
        issues.append("Prometheus is not reachable")

    # Targets down
    targets_down = sum(1 for t in doc.targets if t.state in ("down", "unknown"))
    if targets_down > 0:
        issues.append(f"{targets_down} Prometheus target(s) down")

    # Firing critical alerts
    firing_crit = sum(
        1 for a in doc.firing_alerts
        if a.severity in ("critical", "page")
    )
    if firing_crit > 0:
        issues.append(f"{firing_crit} critical alert(s) firing")

    # Grafana reachability
    grafana_ok = doc.grafana_reachable
    if grafana_ok is False:
        issues.append("Grafana is not reachable")

    # No Prometheus configured at all
    if doc.prometheus_url is None and not doc.targets:
        return {
            "overall_status":          "NOT_CONFIGURED",
            "prometheus_reachable":    None,
            "grafana_reachable":       None,
            "targets_down":            0,
            "firing_critical_alerts":  0,
            "issues":                  ["Observability stack not configured"],
        }

    # Overall
    if firing_crit > 0 or (prom_ok is False and doc.targets):
        overall = "CRITICAL"
    elif targets_down > 0 or grafana_ok is False or issues:
        overall = "DEGRADED"
    else:
        overall = "HEALTHY"

    return {
        "overall_status":          overall,
        "prometheus_reachable":    prom_ok,
        "grafana_reachable":       grafana_ok,
        "targets_down":            targets_down,
        "firing_critical_alerts":  firing_crit,
        "issues":                  issues,
    }


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

def collect_observability_state(
    cell_id:          str,
    prometheus_url:   Optional[str] = None,
    grafana_url:      Optional[str] = None,
    alertmanager_url: Optional[str] = None,
    http_get_fn:      Optional[Callable[[str], Optional[dict]]] = None,
    reach_fn:         Optional[Callable[[str], bool]] = None,
    now_fn:           Optional[Callable[[], str]] = None,
) -> ObservabilityDocument:
    """
    Collect observability state by querying the Prometheus/Grafana APIs.

    prometheus_url: e.g. "http://prometheus.home.example.com:9090"
    grafana_url:    e.g. "http://grafana.home.example.com:3000"
    http_get_fn:    injectable for testing (replaces _http_get_json)
    reach_fn:       injectable for testing (replaces _is_reachable)
    """
    now       = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    http_get  = http_get_fn or _http_get_json
    reachable = reach_fn or _is_reachable

    doc = ObservabilityDocument(
        cell_id=cell_id,
        collected_at=now,
        prometheus_url=prometheus_url,
        grafana_url=grafana_url,
        alertmanager_url=alertmanager_url,
    )
    errors = []

    # Prometheus
    if prometheus_url:
        try:
            doc.prometheus_reachable = reachable(f"{prometheus_url}/-/healthy")
            if doc.prometheus_reachable:
                # Targets
                tdata = http_get(f"{prometheus_url}/api/v1/targets")
                if tdata:
                    doc.targets = _parse_prometheus_targets(tdata)
                # Alert rules
                rdata = http_get(f"{prometheus_url}/api/v1/rules")
                if rdata:
                    all_rules = _parse_alert_rules(rdata)
                    doc.alert_rules = all_rules
                    doc.firing_alerts = [r for r in all_rules if r.state == "firing"]
        except Exception as e:
            errors.append({"component": "prometheus", "error": str(e)})

    # Grafana
    if grafana_url:
        try:
            doc.grafana_reachable = reachable(f"{grafana_url}/api/health")
            if doc.grafana_reachable:
                # Health info
                hdata = http_get(f"{grafana_url}/api/health")
                if hdata:
                    doc.grafana_version = hdata.get("version")
                # Dashboards
                ddata = http_get(f"{grafana_url}/api/search?type=dash-db&limit=100")
                if ddata:
                    doc.dashboards = _parse_grafana_dashboards(ddata)
        except Exception as e:
            errors.append({"component": "grafana", "error": str(e)})

    doc.collection_errors = errors
    return doc


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def observability_to_dict(doc: ObservabilityDocument) -> dict:
    """Convert ObservabilityDocument to a JSON-serialisable dict."""
    health = compute_observability_health(doc)
    targets_up   = sum(1 for t in doc.targets if t.state == "up")
    targets_down = sum(1 for t in doc.targets if t.state in ("down", "unknown"))
    return {
        "schema_version": "1.0",
        "cell_id":        doc.cell_id,
        "collected_at":   doc.collected_at,
        "collection_errors": doc.collection_errors,
        "prometheus": {
            "url":           doc.prometheus_url,
            "version":       doc.prometheus_version,
            "reachable":     doc.prometheus_reachable,
            "targets_up":    targets_up,
            "targets_down":  targets_down,
            "targets_total": len(doc.targets),
            "targets": [
                {
                    "job":      t.job,
                    "instance": t.instance,
                    "state":    t.state,
                    "last_error": t.last_error,
                }
                for t in doc.targets
            ],
        },
        "alertmanager": {
            "url":           doc.alertmanager_url,
            "reachable":     doc.alertmanager_reachable,
            "active_alerts": doc.active_alerts,
        },
        "alert_rules": [
            {"name": r.name, "group": r.group, "state": r.state, "severity": r.severity}
            for r in doc.alert_rules
        ],
        "firing_alerts": [
            {"name": r.name, "state": r.state, "severity": r.severity}
            for r in doc.firing_alerts
        ],
        "grafana": {
            "url":       doc.grafana_url,
            "reachable": doc.grafana_reachable,
            "version":   doc.grafana_version,
            "dashboards": [
                {"title": d.title, "uid": d.uid}
                for d in doc.dashboards
            ],
        },
        "log_collection": {
            "tool":      doc.log_tool,
            "reachable": doc.log_reachable,
            "sources":   doc.log_sources,
        },
        "observability_health": health,
    }
