#!/usr/bin/env python3
"""
network_topology_collector.py — Network topology collection library (Phase 8).

Provides:
  parse_interfaces_file(text)     — parse /etc/network/interfaces into bridge list
  collect_observed_bridges(...)   — SSH to host, read interfaces, return bridges
  compare_topology(declared, observed) — diff declared vs observed bridges
  merge_observed_topology(state, observed) — update bootstrap-state.json in-place

Stdlib only (no pip). SSH via subprocess + system ssh binary.
"""

import re
import subprocess
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# /etc/network/interfaces parser
# ---------------------------------------------------------------------------

def parse_interfaces_file(text: str) -> list[dict]:
    """
    Parse the content of /etc/network/interfaces and return a list of
    bridge interface dicts.

    Only bridges are returned (interfaces with `bridge-ports` stanzas
    or iface type that is a bridge). Loopback and plain NICs are excluded.

    Each dict:
      name        str
      ports       list[str]     (bridge-ports values, split on whitespace)
      vlan_aware  bool
      ip          str | None    (CIDR notation from 'address' line)
      gateway     str | None
      mtu         int | None
      state       "UNKNOWN"     (will be updated by live probe if available)
    """
    bridges = []
    current: Optional[dict] = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        # New stanza: "iface <name> inet <method>"
        m = re.match(r"^iface\s+(\S+)\s+inet\s+(\S+)", line)
        if m:
            if current and current.get("_is_bridge"):
                bridges.append(_finalise_bridge(current))
            current = {
                "_name":       m.group(1),
                "_method":     m.group(2),
                "_is_bridge":  False,
                "_ports":      [],
                "_vlan_aware": False,
                "_ip":         None,
                "_gateway":    None,
                "_mtu":        None,
            }
            continue

        if current is None:
            continue

        # Bridge-specific options
        if re.match(r"^bridge-ports\s+", line):
            ports_str = line.split(None, 1)[1]
            ports = [p for p in ports_str.split() if p != "none"]
            current["_ports"]     = ports
            current["_is_bridge"] = True

        elif re.match(r"^bridge-vlan-aware\s+", line):
            val = line.split(None, 1)[1].strip().lower()
            current["_vlan_aware"] = val == "yes"

        elif re.match(r"^address\s+", line):
            current["_ip"] = line.split(None, 1)[1].strip()

        elif re.match(r"^gateway\s+", line):
            current["_gateway"] = line.split(None, 1)[1].strip()

        elif re.match(r"^mtu\s+", line):
            try:
                current["_mtu"] = int(line.split(None, 1)[1].strip())
            except ValueError:
                pass

    # Flush last stanza
    if current and current.get("_is_bridge"):
        bridges.append(_finalise_bridge(current))

    return bridges


def _finalise_bridge(raw: dict) -> dict:
    return {
        "name":       raw["_name"],
        "ports":      raw["_ports"],
        "vlan_aware": raw["_vlan_aware"],
        "ip":         raw["_ip"],
        "gateway":    raw["_gateway"],
        "mtu":        raw["_mtu"],
        "state":      "UNKNOWN",
    }


# ---------------------------------------------------------------------------
# SSH-based collector
# ---------------------------------------------------------------------------

def collect_observed_bridges(
    host: str,
    user: str = "root",
    port: int = 22,
    key: Optional[str] = None,
    password: Optional[str] = None,
    runner_fn=None,
) -> tuple[list[dict], list[str]]:
    """
    SSH to host and read /etc/network/interfaces.

    Returns (bridges_list, errors_list).

    runner_fn: injectable for tests — fn(cmd, env) -> (returncode, stdout, stderr)
    If not provided, uses subprocess.run with the system ssh binary.
    """
    ssh_cmd = ["ssh",
               "-o", "StrictHostKeyChecking=no",
               "-o", "BatchMode=yes",
               "-p", str(port)]
    if key:
        ssh_cmd += ["-i", key]
    ssh_cmd += [f"{user}@{host}", "cat /etc/network/interfaces"]

    if runner_fn:
        rc, stdout, stderr = runner_fn(ssh_cmd, None)
    else:
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True, text=True, timeout=30,
            )
            rc, stdout, stderr = result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return [], [f"SSH to {host} timed out after 30s"]
        except Exception as exc:
            return [], [f"SSH to {host} failed: {exc}"]

    if rc != 0:
        return [], [f"SSH to {host} returned exit {rc}: {stderr.strip()}"]

    try:
        bridges = parse_interfaces_file(stdout)
    except Exception as exc:
        return [], [f"Failed to parse /etc/network/interfaces: {exc}"]

    return bridges, []


# ---------------------------------------------------------------------------
# Comparison: declared vs observed
# ---------------------------------------------------------------------------

def compare_topology(
    declared_bridges: list[dict],
    observed_bridges: list[dict],
) -> tuple[bool, str]:
    """
    Compare declared vs. observed bridge configuration.

    Returns (drift_detected: bool, drift_details: str).
    drift_details is empty string when no drift.
    """
    declared_by_name = {b["name"]: b for b in (declared_bridges or [])}
    observed_by_name = {b["name"]: b for b in (observed_bridges or [])}

    issues = []

    # Declared bridges that are not observed
    for name, decl in declared_by_name.items():
        if name not in observed_by_name:
            issues.append(f"Bridge '{name}' declared but NOT found on host")
            continue
        obs = observed_by_name[name]
        # Compare key fields
        if decl.get("ip") and obs.get("ip") and decl["ip"] != obs["ip"]:
            issues.append(
                f"Bridge '{name}' IP mismatch: "
                f"declared={decl['ip']} observed={obs['ip']}"
            )
        decl_vlan = bool(decl.get("vlan_aware"))
        obs_vlan  = bool(obs.get("vlan_aware"))
        if decl_vlan != obs_vlan:
            issues.append(
                f"Bridge '{name}' vlan_aware mismatch: "
                f"declared={decl_vlan} observed={obs_vlan}"
            )
        decl_ports = set(decl.get("ports") or [])
        obs_ports  = set(obs.get("ports") or [])
        if decl_ports and obs_ports and decl_ports != obs_ports:
            issues.append(
                f"Bridge '{name}' ports mismatch: "
                f"declared={sorted(decl_ports)} observed={sorted(obs_ports)}"
            )

    # Observed bridges not in declaration (informational, not drift)
    for name in observed_by_name:
        if name not in declared_by_name:
            issues.append(f"Bridge '{name}' found on host but NOT declared (undeclared bridge)")

    drift_detected = bool(issues)
    drift_details  = "; ".join(issues) if issues else ""
    return drift_detected, drift_details


# ---------------------------------------------------------------------------
# Merge observed topology into bootstrap-state.json
# ---------------------------------------------------------------------------

def merge_observed_topology(state: dict, observed_bridges: list[dict], errors: list[str]) -> dict:
    """
    Update the network_topology_declared section of bootstrap-state with
    observed bridge data and drift results. Returns the modified state dict.
    """
    ntd = state.setdefault("network_topology_declared", {})
    declared_bridges = ntd.get("bridges") or []

    drift_detected, drift_details = compare_topology(declared_bridges, observed_bridges)

    ntd["observed_bridges"] = observed_bridges
    ntd["drift_detected"]   = drift_detected
    ntd["drift_details"]    = drift_details if drift_details else None
    ntd["observed_at"]      = datetime.now(timezone.utc).isoformat()

    if errors:
        state.setdefault("collection_errors", []).extend(errors)

    return state
