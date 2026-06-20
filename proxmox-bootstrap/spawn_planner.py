#!/usr/bin/env python3
"""
spawn_planner.py — Spawn planner logic (Phase 12.E.3).

Separates the planning logic from interactive I/O so that the planner
can be tested without stdin/stdout and composed into different UIs.

Provides:
  ServiceCatalog       — wraps service-catalog.yaml; service lookup and filtering
  ServiceFitAssessor   — checks if services fit a HardwareProfile
  FitResult            — fit / marginal / no-fit with reason
  SpawnPlannerSession  — tracks planner state across the three steps
  build_spawn_plan()   — assembles spawn-plan.json from session state

Interactive CLI entry point: spawn-planner.py (separate script that calls this module).

Stdlib only (no pip, no yaml — uses simple YAML parser below).
"""

import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# deal contracts — graceful no-op when deal is not installed (dev dep only)
try:
    import deal as _deal
    _deal_pre  = _deal.pre
    _deal_post = _deal.post
except ImportError:  # pragma: no cover
    def _deal_pre(_c):   return lambda f: f  # type: ignore
    def _deal_post(_c):  return lambda f: f  # type: ignore


# ---------------------------------------------------------------------------
# Minimal YAML list-of-dicts parser (stdlib only — no PyYAML)
# Handles the service-catalog.yaml format only.
# ---------------------------------------------------------------------------

def _parse_service_catalog_yaml(text: str) -> list[dict]:
    """
    Parse a service-catalog.yaml-style YAML into a list of service dicts.
    Supports: top-level key "services:", list items starting with "  - name:",
    scalar and list values indented under each list item.
    """
    services = []
    current: Optional[dict] = None
    in_services = False
    list_field: Optional[str] = None      # field currently collecting list values

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        if not in_services:
            if line.strip() == "services:":
                in_services = True
            continue

        # Skip comments and blank lines
        if not line.strip() or line.strip().startswith("#"):
            continue

        # New service entry
        if re.match(r"^  - name:", line):
            if current is not None:
                services.append(current)
            current = {"name": line.split(":", 1)[1].strip()}
            list_field = None
            continue

        if current is None:
            continue

        # List item under a list field (e.g. "    - k3s-worker")
        m_list_item = re.match(r"^    - (.+)$", line)
        if m_list_item and list_field is not None:
            current[list_field].append(m_list_item.group(1).strip())
            continue

        # Key: scalar value (e.g. "    ram_gb: 4")
        m_kv = re.match(r"^    (\w+):\s*(.*)$", line)
        if m_kv:
            list_field = None
            key = m_kv.group(1)
            val = m_kv.group(2).strip()
            if val == "":
                # empty value — might be start of a list or null
                current[key] = []
                list_field = key
            elif val == "true":
                current[key] = True
            elif val == "false":
                current[key] = False
            elif re.match(r"^-?\d+$", val):
                current[key] = int(val)
            elif re.match(r"^-?\d+\.\d+$", val):
                current[key] = float(val)
            elif val.startswith("[") and val.endswith("]"):
                # Inline list: [a, b, c]
                inner = val[1:-1].strip()
                current[key] = [x.strip() for x in inner.split(",")] if inner else []
            else:
                current[key] = val
            continue

    if current is not None:
        services.append(current)

    return services


# ---------------------------------------------------------------------------
# ServiceCatalog
# ---------------------------------------------------------------------------

GROUPS = ("Infrastructure", "Platform", "Intelligence", "Monitoring", "Applications")

DEFAULT_CATALOG_PATH = Path(__file__).parent / "service-catalog.yaml"


class ServiceCatalog:
    """Wraps service-catalog.yaml."""

    def __init__(self, services: list[dict]):
        self._services = {s["name"]: s for s in services}

    # ── Constructors ──────────────────────────────────────────────────────────

    @classmethod
    def from_file(cls, path=None) -> "ServiceCatalog":
        p = Path(path) if path else DEFAULT_CATALOG_PATH
        text = p.read_text(encoding="utf-8")
        return cls(_parse_service_catalog_yaml(text))

    @classmethod
    def from_list(cls, services: list[dict]) -> "ServiceCatalog":
        return cls(services)

    # ── Queries ───────────────────────────────────────────────────────────────

    def all(self) -> list[dict]:
        return list(self._services.values())

    def get(self, name: str) -> Optional[dict]:
        return self._services.get(name)

    def baseline(self) -> list[dict]:
        return [s for s in self.all() if s.get("baseline")]

    def by_group(self, group: str) -> list[dict]:
        return [s for s in self.all() if s.get("group") == group]

    def groups(self) -> list[str]:
        return [g for g in GROUPS if self.by_group(g)]

    def resolve_dependencies(self, names: list[str]) -> list[str]:
        """Return names + all transitive dependencies (no duplicates, order preserved)."""
        resolved: list[str] = []
        seen: set[str] = set()

        def _add(name: str):
            if name in seen:
                return
            seen.add(name)
            svc = self._services.get(name)
            if svc:
                for dep in (svc.get("dependencies") or []):
                    _add(dep)
                resolved.append(name)

        for n in names:
            _add(n)
        return resolved

    def total_ram_gb(self, names: list[str]) -> float:
        return sum(self._services[n].get("ram_gb", 0)
                   for n in names if n in self._services)

    def total_disk_gb(self, names: list[str]) -> float:
        return sum(self._services[n].get("disk_gb", 0)
                   for n in names if n in self._services)

    def total_vm_count(self, names: list[str]) -> int:
        return sum(self._services[n].get("vm_count", 1)
                   for n in names if n in self._services)

    def password_format(self, name: str) -> str:
        """Return 'alphanumeric' if this service declares password format restrictions; else 'default'."""
        svc = self._services.get(name, {})
        return svc.get("password_format", "default")

    def alphanumeric_services(self, names: list[str]) -> list[str]:
        """Return subset of names whose services require alphanumeric-only passwords."""
        return [n for n in names if self.password_format(n) == "alphanumeric"]


# ---------------------------------------------------------------------------
# Service fit assessment
# ---------------------------------------------------------------------------

FIT_OK       = "fit"
FIT_MARGINAL = "marginal"
FIT_NO_FIT   = "no-fit"


@dataclass
class FitResult:
    service_name: str
    status:       str       # FIT_OK | FIT_MARGINAL | FIT_NO_FIT
    reason:       str = ""


def assess_service_fit(
    service: dict,
    hardware: dict,
    available_ram_gb: float,
    available_disk_gb: float,
) -> FitResult:
    """
    Assess whether a service fits the available hardware resources.

    Args:
        service:           service dict from catalog
        hardware:          hardware-profile dict
        available_ram_gb:  RAM available for new VMs (host RAM minus already allocated)
        available_disk_gb: storage available for new VMs

    Returns:
        FitResult with status FIT_OK, FIT_MARGINAL, or FIT_NO_FIT
    """
    name      = service["name"]
    req_ram   = service.get("ram_gb", 0)
    req_disk  = service.get("disk_gb", 0)

    if req_ram > available_ram_gb:
        return FitResult(name, FIT_NO_FIT,
            f"requires {req_ram} GB RAM; only {available_ram_gb:.1f} GB available")

    # Marginal: fits but uses more than 75% of remaining RAM
    if req_ram > available_ram_gb * 0.75:
        return FitResult(name, FIT_MARGINAL,
            f"requires {req_ram} GB RAM; {available_ram_gb:.1f} GB available (marginal)")

    if req_disk > available_disk_gb:
        return FitResult(name, FIT_NO_FIT,
            f"requires {req_disk} GB disk; only {available_disk_gb:.1f} GB available")

    return FitResult(name, FIT_OK, f"RAM: {req_ram} GB / {available_ram_gb:.1f} GB available")


def assess_all_services(
    catalog: ServiceCatalog,
    hardware: dict,
    host_ram_gb: float,
) -> dict[str, FitResult]:
    """
    Return a FitResult for every service in the catalog.

    Assumes the host RAM is the available resource (caller adjusts for
    already-committed baseline RAM before calling for optional services).
    """
    baseline_ram = catalog.total_ram_gb([s["name"] for s in catalog.baseline()])
    # Rough estimate: 10% overhead for host processes
    available_ram  = host_ram_gb * 0.90 - baseline_ram

    # Disk: use total disk capacity from hardware profile as a rough proxy
    disks = hardware.get("disks") or []
    total_disk = sum(d.get("size_gb", 0) for d in disks if d.get("size_gb", 0) >= 10)
    available_disk = total_disk * 0.80  # 80% usable

    results = {}
    for svc in catalog.all():
        if svc.get("baseline"):
            # Baseline services are always deployed — skip fit check
            results[svc["name"]] = FitResult(svc["name"], FIT_OK, "baseline — always deployed")
        else:
            results[svc["name"]] = assess_service_fit(
                svc, hardware, available_ram, available_disk
            )
    return results


def full_mirror_services(
    catalog: ServiceCatalog,
    fit_results: dict[str, FitResult],
) -> tuple[list[str], list[dict]]:
    """
    Return (selected, excluded) for full-mirror mode:
    all services that fit (including baseline), excluding those that don't.
    """
    selected = []
    excluded = []
    for svc in catalog.all():
        name = svc["name"]
        fit  = fit_results.get(name)
        if fit is None or fit.status == FIT_NO_FIT:
            excluded.append({"service": name, "reason": (fit.reason if fit else "not assessed")})
        else:
            selected.append(name)
    # Resolve dependencies
    selected = catalog.resolve_dependencies(selected)
    return selected, excluded


# ---------------------------------------------------------------------------
# Planner session
# ---------------------------------------------------------------------------

# Network modes
NET_LAN     = "lan"
NET_WAN     = "wan"
NET_SPECIFY = "specify"

# Execution modes
EXEC_AUTONOMOUS  = "autonomous"
EXEC_INTERACTIVE = "interactive"

# Service selection modes
SEL_FULL_MIRROR = "full-mirror"
SEL_GROUP       = "group"
SEL_INDIVIDUAL  = "individual"


@dataclass
class SpawnPlannerSession:
    """
    Stateful session for the spawn planner.

    Populated in order: network_mode → guided_setup (optional) →
      execution_mode → service selection.
    After all steps, build_spawn_plan() produces the spawn-plan.json dict.
    """
    # Step 0 — Network
    network_mode:         str = NET_LAN
    broodling_ip:         Optional[str] = None
    wan_auth_key:         Optional[str] = None
    headscale_url:        Optional[str] = None

    # Step 0.5 — Guided setup (optional, non-autonomous modes)
    guided_session:       Optional[Any] = None   # GuidedSetupSession
    setup_overrides:      dict = field(default_factory=dict)  # from session_to_overrides

    # Step 1 — Execution
    execution_mode:       str = EXEC_AUTONOMOUS
    temp_root_password:   Optional[str] = None  # generated at autonomous selection

    # Step 2 — Service selection (autonomous only)
    selection_mode:       str = SEL_FULL_MIRROR
    selected_services:    list = field(default_factory=list)
    excluded_services:    list = field(default_factory=list)  # [{service, reason}]
    fit_results:          dict = field(default_factory=dict)  # name → FitResult

    # Allocated resources (set by build_spawn_plan)
    allocated_vmids:      list = field(default_factory=list)
    allocated_ips:        list = field(default_factory=list)
    suggested_hostname:   Optional[str] = None


# ---------------------------------------------------------------------------
# Temporary password generation (AD-043)
# ---------------------------------------------------------------------------

_WORDS = [
    "ready", "spawn", "hatch", "forge", "brood", "fleet", "node", "cluster",
    "infra", "build", "launch", "setup", "start", "begin", "prime", "fresh",
]


@_deal_post(lambda result: isinstance(result, str) and len(result) >= 8)
def generate_temp_password(seed: Optional[int] = None) -> str:
    """Generate a readable temporary root password (Capital.word.word.N format)."""
    if seed is not None:
        import random  # noqa: S311
        rng = random.Random(seed)  # noqa: S311
        w1 = _WORDS[rng.randint(0, len(_WORDS) - 1)]  # noqa: S311
        w2 = _WORDS[rng.randint(0, len(_WORDS) - 1)]  # noqa: S311
        n  = rng.randint(1, 9)  # noqa: S311
    else:
        w1 = secrets.choice(_WORDS)
        w2 = secrets.choice(_WORDS)
        n  = secrets.randbelow(9) + 1
    return f"{w1.capitalize()}.to.{w2}.{n}"


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------

@_deal_pre(lambda session, manifest, bootstrap_state, catalog, hardware=None, now_fn=None:
           isinstance(bootstrap_state, dict))
@_deal_post(lambda result: isinstance(result, dict) and "generated_at" in result)
def build_spawn_plan(
    session:          SpawnPlannerSession,
    manifest:         Any,       # SpawnManifest or dict with reservation data
    bootstrap_state:  dict,
    catalog:          ServiceCatalog,
    hardware:         Optional[dict] = None,
    now_fn:           Optional[Callable[[], str]] = None,
) -> dict:
    """
    Assemble the spawn-plan.json dict from a completed planner session.

    Args:
        session:         completed SpawnPlannerSession
        manifest:        SpawnManifest or raw manifest dict from read_hatchery_state
        bootstrap_state: hatchery's bootstrap-state.json
        catalog:         ServiceCatalog (for VM count and resource allocation)
        hardware:        optional hardware-profile dict
        now_fn:          injectable timestamp generator (default: UTC now)

    Returns:
        spawn-plan dict ready for JSON serialization.
    """
    # Support both SpawnManifest wrapper and raw dict
    if hasattr(manifest, "raw"):
        m = manifest.raw
    elif isinstance(manifest, dict):
        m = manifest
    else:
        m = {}

    # For allocation helpers that need the SpawnManifest object
    from hatchery_state import SpawnManifest as _SM, read_hatchery_state as _rhs
    _manifest_obj = manifest if isinstance(manifest, _SM) else _rhs(bootstrap_state, {})

    now  = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    cell = bootstrap_state.get("cell_id", "")
    hi   = bootstrap_state.get("host_identity") or {}
    domain = hi.get("domain", "")
    hostname = session.suggested_hostname or "broodling"
    fqdn     = f"{hostname}.{domain}" if domain else hostname

    # Execution mode and services
    exec_mode = session.execution_mode
    if exec_mode == EXEC_AUTONOMOUS:
        services  = session.selected_services
        excluded  = session.excluded_services
        sel_mode  = session.selection_mode
    else:
        services  = []
        excluded  = []
        sel_mode  = None

    # VMIDs — use allocated_vmids from session; fall back to manifest allocation
    vmids = list(session.allocated_vmids)

    # IPs — use allocated_ips from session
    ips = list(session.allocated_ips)

    # Number of VMs = total vm_count of selected services (min 1 for baseline)
    vm_count = catalog.total_vm_count(services) if services else 1
    if not vmids:
        from hatchery_state import next_vmid_block
        vmids = next_vmid_block(_manifest_obj, vm_count)
    if not ips:
        cidr = (bootstrap_state.get("network_topology") or {}).get("management_cidr", "192.168.1.0/24")
        from hatchery_state import next_ip_block
        ips = next_ip_block(_manifest_obj, cidr, vm_count)

    # Build VMs list
    hw_ram = (hardware or {}).get("ram_gb") or (bootstrap_state.get("capacity_model") or {}).get("host_ram_gb") or 32
    vms = _build_vms(services, vmids, ips, hw_ram, catalog, hostname)

    # Storage from hardware profile
    hw_disks  = (hardware or {}).get("disks") or []
    hw_derived = (hardware or {}).get("derived") or {}
    disk_ids  = [d.get("name", "") for d in hw_disks if d.get("size_gb", 0) >= 10]
    topology  = hw_derived.get("zfs_topology") or _guess_topology(len(disk_ids))

    # Network
    nt  = bootstrap_state.get("network_topology") or {}
    wan = nt.get("wan_config") or {}
    gw  = nt.get("gateway", "")
    ns  = [gw] if gw else []

    # k3s
    k3s_role = "worker"
    if "k3s-server" in services:
        k3s_role = "server"
    k3s_cluster = bootstrap_state.get("k3s_cluster") or {}
    server_url  = k3s_cluster.get("server_url", "")
    # k3s join tokens are the one secret the spawn package carries (README: included in
    # the spawn package, valid only for the spawn window, rotated after the broodling
    # joins). Carry them so generate_ansible_k3s_vars() emits a usable token instead of
    # the unresolved "{{ vault_k3s_worker_token }}" placeholder, which nothing fills.
    # Tokens are written to bootstrap-state.json["k3s"] by forge phase-05 after Ansible
    # k3s bootstrap succeeds (F-011 fix in forge_scripts.py generate_phase_05_sh).
    _k3s_secrets = bootstrap_state.get("k3s") or {}

    plan: dict = {
        "cell_id":       cell,
        "hostname":      hostname,
        "domain":        domain,
        "fqdn":          fqdn,
        "lan_ip":        ips[0] if ips else "",
        "package_id":    f"spawn-{cell}-{hostname}-{now[:10].replace('-', '')}",
        "generated_at":  now,
        "disposition": {
            "execution_mode": exec_mode,
            "network_mode":   session.network_mode,
            "services":       services,
            "excluded":       excluded,
        },
        "storage": {
            "pool_name":      "rpool",
            "topology":       topology,
            "disk_ids":       disk_ids,
            "datastore_name": "local-rpool",
        },
        "network": {
            "bridge":      "vmbr0",
            "gateway":     gw,
            "nameservers": ns,
        },
        "hatchery": {
            "proxmox_cluster_address": hi.get("lan_ip", ""),
            "headscale_url":           wan.get("headscale_url") or nt.get("headscale_url") or session.headscale_url or "",
            "cell_id":                 cell,
        },
        "vms": vms,
        "k3s": {
            "role":               k3s_role,
            "server_url":         server_url,
            "node_labels":        [f"{k3s_role}=true"],
            "worker_join_token":  _k3s_secrets.get("worker_join_token"),
            "server_join_token":  _k3s_secrets.get("server_join_token"),
            "worker_token_path":  f"Infrastructure/k3s/worker-join-token",
            "server_token_path":  f"Infrastructure/k3s/server-join-token",
        },
        "k3s_role": k3s_role,
    }

    # Fail fast if k3s join tokens are absent — a spawn plan with None tokens will
    # produce an ansible vars file with null k3s_token, causing every broodling
    # k3s join to fail (F-011/F-020). Tokens are written to bootstrap-state.json
    # by forge phase-05 after Ansible k3s bootstrap succeeds.
    _worker_token = _k3s_secrets.get("worker_join_token")
    _server_token = _k3s_secrets.get("server_join_token")
    if not _worker_token or not _server_token:
        raise ValueError(
            "k3s join tokens are missing from bootstrap-state.json[\"k3s\"]. "
            "Run forge first and ensure phase-05 (k3s cluster init) completed "
            "successfully. Tokens are written to bootstrap-state.json after "
            "Ansible k3s bootstrap runs. "
            "KeePass paths: Infrastructure/k3s/worker-join-token and "
            "Infrastructure/k3s/server-join-token."
        )

    # WAN-specific fields
    if session.network_mode == NET_WAN:
        # Fail fast if WAN mode spawn is missing a Headscale pre-auth key (F-021).
        # The key must be generated on the hatchery before running spawn-planner:
        #   headscale preauthkeys create --expiration 1h
        # Store it in KeePass at Infrastructure/headscale/api-key, then pass it
        # via --wan-auth-key or set it in the session before calling build_spawn_plan.
        if not session.wan_auth_key:
            raise ValueError(
                "WAN mode spawn requires a Headscale pre-auth key (wan_auth_key). "
                "Generate one on the hatchery: headscale preauthkeys create --expiration 1h "
                "Store it in KeePass at Infrastructure/headscale/api-key and pass it via "
                "--wan-auth-key to spawn-planner.py. "
                "See NODE-SPAWNING.md 'WAN mode prerequisites' for the full workflow."
            )
        plan["disposition"]["wan_auth_key"] = session.wan_auth_key or ""
        plan["hatchery"]["headscale_url"]   = session.headscale_url or ""

    # Guided setup overrides — embedded so downstream tools know which fields
    # were intentionally set by the operator vs. auto-calculated.
    if session.setup_overrides:
        plan["setup_overrides"] = session.setup_overrides

    # Credential format overrides — services that require alphanumeric-only passwords.
    # Populated from service-catalog.yaml password_format fields.
    # Used by generated phase scripts to issue credentials in the correct format
    # and to drive automatic retry logic (1.F.8) if a deployment fails due to
    # password character restrictions.
    alphanumeric_svcs = catalog.alphanumeric_services(services) if services else []
    if alphanumeric_svcs:
        plan["credential_format_overrides"] = {
            svc: "alphanumeric" for svc in alphanumeric_svcs
        }

    return plan


def _build_vms(
    services: list[str],
    vmids:    list[int],
    ips:      list[str],
    host_ram_gb: float,
    catalog:  ServiceCatalog,
    hostname: str,
) -> list[dict]:
    """Build VMs list from selected services."""
    vms     = []
    vm_idx  = 0
    used_names: set[str] = set()

    for name in services:
        svc = catalog.get(name)
        if svc is None:
            continue
        vm_count = svc.get("vm_count", 1)
        for _ in range(vm_count):
            if vm_idx >= len(vmids) or vm_idx >= len(ips):
                break
            vm_name = _vm_name_for_service(name, vm_idx, used_names)
            used_names.add(vm_name)
            mem_mb  = int(svc.get("ram_gb", 2) * 1024)
            vms.append({
                "vmid":         vmids[vm_idx],
                "name":         vm_name,
                "ip":           ips[vm_idx],
                "memory_mb":    mem_mb,
                "initial_user": "ubuntu",
                "service":      name,
            })
            vm_idx += 1

    if not vms and vmids and ips:
        # Baseline: one minimal VM
        vms.append({
            "vmid":         vmids[0],
            "name":         f"{hostname}-vm-00",
            "ip":           ips[0],
            "memory_mb":    2048,
            "initial_user": "ubuntu",
            "service":      "baseline",
        })

    return vms


_SVC_SHORT: dict[str, str] = {
    "k3s-worker":       "k3s-worker",
    "k3s-server":       "k3s-server",
    "pbs-datastore":    "pbs",
    "longhorn":         "longhorn",
    "forgejo":          "forgejo",
    "monitoring":       "monitoring",
    "prometheus-agent": "prom-agent",
    "assessment-engine": "assessment",
    "cert-manager":     "cert-mgr",
    "nextcloud":        "nextcloud",
    "immich":           "immich",
}


def _vm_name_for_service(service: str, idx: int, used: set[str]) -> str:
    base = _SVC_SHORT.get(service, service[:12])
    n    = 1
    name = f"{base}-{n:02d}"
    while name in used:
        n   += 1
        name = f"{base}-{n:02d}"
    return name


def _guess_topology(n: int) -> str:
    if n <= 1:  return "stripe"
    if n == 2:  return "mirror"
    if n == 3:  return "raidz1"
    if n <= 6:  return "raidz2"
    return "raidz3"


# ---------------------------------------------------------------------------
# Planner step helpers (used by the interactive CLI and by tests)
# ---------------------------------------------------------------------------

def step0_set_network_mode(
    session:    SpawnPlannerSession,
    mode:       str,
    broodling_ip: Optional[str] = None,
    wan_auth_key: Optional[str] = None,
    headscale_url: Optional[str] = None,
) -> SpawnPlannerSession:
    """Configure network mode in session. Returns updated session."""
    session.network_mode  = mode
    session.broodling_ip  = broodling_ip
    session.wan_auth_key  = wan_auth_key
    session.headscale_url = headscale_url
    return session


def step1_set_execution_mode(
    session:          SpawnPlannerSession,
    mode:             str,
    temp_password_seed: Optional[int] = None,
) -> SpawnPlannerSession:
    """Configure execution mode. For autonomous, generates temp root password."""
    session.execution_mode = mode
    if mode == EXEC_AUTONOMOUS:
        session.temp_root_password = generate_temp_password(temp_password_seed)
    return session


def step2_select_services(
    session:    SpawnPlannerSession,
    catalog:    ServiceCatalog,
    hardware:   dict,
    host_ram_gb: float,
    mode:       str = SEL_FULL_MIRROR,
    manual_selection: Optional[list[str]] = None,
    manual_excluded:  Optional[list[str]] = None,
) -> SpawnPlannerSession:
    """
    Perform service selection for autonomous mode.

    For SEL_FULL_MIRROR: selects all fitting services.
    For SEL_GROUP or SEL_INDIVIDUAL: uses manual_selection (caller already
    handled the interactive group/individual choosing).

    Updates session.selected_services, session.excluded_services,
    session.fit_results, session.selection_mode.
    """
    session.selection_mode = mode
    fit_results = assess_all_services(catalog, hardware, host_ram_gb)
    session.fit_results = fit_results

    if mode == SEL_FULL_MIRROR:
        selected, excluded = full_mirror_services(catalog, fit_results)
        session.selected_services = selected
        session.excluded_services = excluded
    else:
        # Caller provides explicit selection; resolve dependencies
        base = [s["name"] for s in catalog.baseline()]
        combined = base + (manual_selection or [])
        combined = catalog.resolve_dependencies(combined)
        # Exclude anything that doesn't fit
        selected = []
        excluded = list({"service": s, "reason": "manually excluded"}
                        for s in (manual_excluded or []))
        for name in combined:
            fr = fit_results.get(name)
            if fr and fr.status == FIT_NO_FIT:
                excluded.append({"service": name, "reason": fr.reason})
            else:
                selected.append(name)
        session.selected_services = selected
        session.excluded_services = excluded

    return session


# ---------------------------------------------------------------------------
# Step 0.5 — Guided setup wiring (optional, inserted between Step 0 and Step 1)
# ---------------------------------------------------------------------------

def step_guided_setup(
    session:         SpawnPlannerSession,
    mode:            str,
    manifest_dict:   dict,
    selected_groups: Optional[list[str]] = None,
    ip_values:       Optional[dict] = None,
    field_values:    Optional[dict] = None,
) -> SpawnPlannerSession:
    """
    Wire a GuidedSetupSession into the spawn planner session.

    This is an optional step between Step 0 (network mode) and Step 1
    (execution mode). It allows the operator to override auto-calculated
    spawn settings using the guided setup framework.

    mode:            autonomous | ip-selective | group-manual | full-manual
    manifest_dict:   hatchery's bootstrap-state dict (provides suggestions)
    selected_groups: groups to configure manually (group-manual mode)
    ip_values:       dict of field_path → value for IP field overrides
    field_values:    dict of field_path → value for any manual field overrides

    On completion, session.setup_overrides contains all manual choices
    as {field_path: {value, source}} for embedding in spawn-plan.json.
    """
    from guided_setup import (
        GuidedSetupSession,
        set_value as gs_set_value,
        run_ip_selective_suggestions,
        session_to_overrides,
    )

    if mode == "autonomous":
        # Autonomous: no guided session needed
        return session

    gs = GuidedSetupSession(
        mode=mode,
        manifest=manifest_dict,
        selected_groups=set(selected_groups or []),
    )
    session.guided_session = gs

    if mode == "ip-selective":
        run_ip_selective_suggestions(gs)
        if ip_values:
            for fp, val in ip_values.items():
                gs_set_value(fp, val, gs, source="manual")

    elif mode == "group-manual":
        if selected_groups:
            gs.selected_groups = set(selected_groups)
        if field_values:
            for fp, val in field_values.items():
                gs_set_value(fp, val, gs, source="manual")

    elif mode == "full-manual":
        if field_values:
            for fp, val in field_values.items():
                gs_set_value(fp, val, gs, source="manual")

    session.setup_overrides = session_to_overrides(gs)
    return session


def step3_allocate_resources(
    session:         SpawnPlannerSession,
    manifest,        # SpawnManifest object or raw dict
    bootstrap_state: dict,
    catalog:         ServiceCatalog,
    hardware:        Optional[dict] = None,
) -> SpawnPlannerSession:
    """
    Allocate VMIDs, IPs, and hostname from the manifest.
    Populates session.allocated_vmids, allocated_ips, suggested_hostname.

    Args:
        manifest: SpawnManifest object (from read_hatchery_state) or raw dict.
                  SpawnManifest is preferred; raw dict support is for convenience.
    """
    from hatchery_state import next_vmid_block, next_ip_block, suggest_hostname, SpawnManifest

    # Accept either SpawnManifest or raw dict
    if isinstance(manifest, SpawnManifest):
        m = manifest
    else:
        # Wrap raw dict in a SpawnManifest
        from hatchery_state import read_hatchery_state
        m = read_hatchery_state(bootstrap_state, {})

    hi         = bootstrap_state.get("host_identity") or {}
    domain     = hi.get("domain", "")
    nt         = bootstrap_state.get("network_topology") or {}
    cidr       = nt.get("management_cidr", "192.168.1.0/24")

    services   = session.selected_services if session.execution_mode == EXEC_AUTONOMOUS else []
    vm_count   = max(1, catalog.total_vm_count(services) if services else 1)

    session.allocated_vmids    = next_vmid_block(m, vm_count)
    session.allocated_ips      = next_ip_block(m, cidr, vm_count)
    session.suggested_hostname = suggest_hostname(m, "pve", domain)
    return session
