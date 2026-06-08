"""
Field-level manifest diff and documentation drift detector.

Usage:
    from doc_gen.drift import compute_drift, doc_field_drift
"""

from datetime import datetime, timezone
from typing import Any, Callable, Optional


# Paths matching these patterns get elevated severity
_HIGH_PATTERNS = ("ip", "hostname", "address", "gateway", "nameserver")
_MEDIUM_PATTERNS = ("version", "release", "kernel", "pve_version")


def _flatten(obj: Any, prefix: str = "") -> dict:
    """Recursively flatten a nested dict/list into dot-notation paths."""
    items = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            items.update(_flatten(v, path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            path = f"{prefix}[{i}]"
            items.update(_flatten(v, path))
    else:
        items[prefix] = obj
    return items


def _severity(path: str, from_val: Any, to_val: Any) -> str:
    low_path = path.lower()
    if any(p in low_path for p in _HIGH_PATTERNS):
        return "HIGH"
    if any(p in low_path for p in _MEDIUM_PATTERNS):
        return "MEDIUM"
    return "LOW"


def _impact(path: str, severity: str) -> str:
    if severity == "HIGH":
        return f"{path} changed — network/identity fields in generated docs are stale"
    if severity == "MEDIUM":
        return f"{path} changed — version fields in generated docs may be stale"
    return f"{path} changed — review generated docs for accuracy"


def compute_drift(
    from_manifest: dict,
    to_manifest: dict,
    from_snapshot_id: str,
    to_snapshot_id: str,
    now_fn: Optional[Callable[[], str]] = None,
) -> dict:
    """
    Compare two manifests and return a drift record.

    Parameters
    ----------
    from_manifest, to_manifest : dict
        Raw manifest dicts.
    from_snapshot_id, to_snapshot_id : str
        Snapshot IDs for the drift record header.
    now_fn : Optional[Callable[[], str]]
        Injectable clock returning an ISO-8601 timestamp string, for
        deterministic tests (datetime sweep convention — see ARCHITECTURE.md).

    Returns
    -------
    dict matching historical-state-schema drift record format.
    """
    from_flat = _flatten(from_manifest)
    to_flat = _flatten(to_manifest)

    all_paths = set(from_flat) | set(to_flat)
    # Exclude schema metadata paths from drift — they always differ
    skip = {"schema_version", "collected_at", "assessment_tier"}
    all_paths = {p for p in all_paths if p.split(".")[0] not in skip}

    diffs = []
    for path in sorted(all_paths):
        in_from = path in from_flat
        in_to = path in to_flat
        if in_from and in_to:
            fv, tv = from_flat[path], to_flat[path]
            if fv != tv:
                sev = _severity(path, fv, tv)
                diffs.append({
                    "path": path,
                    "from_value": fv,
                    "to_value": tv,
                    "severity": sev,
                    "documentation_impact": _impact(path, sev),
                })
        elif in_from and not in_to:
            diffs.append({
                "path": path,
                "from_value": from_flat[path],
                "to_value": None,
                "severity": "LOW",
                "documentation_impact": f"{path} removed — field may be missing from generated docs",
            })
        else:
            diffs.append({
                "path": path,
                "from_value": None,
                "to_value": to_flat[path],
                "severity": "LOW",
                "documentation_impact": f"{path} added — new field not in prior docs",
            })

    severity_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    overall = "LOW"
    for d in diffs:
        if severity_rank[d["severity"]] > severity_rank[overall]:
            overall = d["severity"]

    return {
        "from_snapshot": from_snapshot_id,
        "to_snapshot": to_snapshot_id,
        "generated_at": (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))(),
        "diffs": diffs,
        "drift_severity": overall,
        "doc_fields_stale": [],
    }


def doc_field_drift(drift_record: dict, field_map: dict) -> list[str]:
    """
    Given a drift record and a field map (path -> doc field name),
    return a list of document field names that are now stale.

    Parameters
    ----------
    drift_record : dict
        Output of compute_drift().
    field_map : dict
        Mapping of manifest dot-paths to doc field names,
        e.g. {"host.hostname": "Host Name", "network.management_ip": "Management IP"}.

    Returns
    -------
    list of stale doc field names.
    """
    changed_paths = {d["path"] for d in drift_record["diffs"]}
    stale = []
    for manifest_path, doc_field in field_map.items():
        # Match exact path or prefix (covers list items under a parent path)
        if any(cp == manifest_path or cp.startswith(manifest_path + ".") or
               cp.startswith(manifest_path + "[") for cp in changed_paths):
            stale.append(doc_field)
    return stale
