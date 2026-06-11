#!/usr/bin/env python3
"""
node_planner.py — Phase 1.Q Zero-Touch Node Provisioning planner.

Manages the lifecycle of bare-metal Proxmox nodes (broodlings) joining the
cluster via Headscale. Generates codenames, creates Headscale pre-auth keys,
persists provisioning state, and handles operator-gated approval/blacklisting.

Node lifecycle:
  planned → iso-built → joining → pending-approval → active
                                                    ↘ blacklisted (any state except active)
  active → decommissioned

State file: $BROODFORGE_STATE_DIR/provisioning-state.json
            (default: /var/lib/broodforge/provisioning-state.json)

Design notes:
  - Pre-auth keys are single-use, valid until used or blacklisted (no time limit).
  - join_deadline: optional operator-set deadline. If set and the node has not
    reached pending-approval by that time when a registration arrives, the node
    is auto-blacklisted. Default is null (permissive — no deadline). Sysadmin
    can whitelist (un-blacklist) at any time by resetting blacklisted=False and
    state back to iso-built.
  - join_pin: ###-###-###-### PIN generated at plan time, embedded in the
    ISO. The broodling sends this PIN with its registration request, so the
    operator sees both the human-readable codename AND a 12-digit numeric secret
    that ties the join request to the specific ISO without exposing the node's
    private key. If the PIN does not match, the registration is rejected.

Exit codes:
  0 — success
  1 — fatal error
  2 — NOT_IMPLEMENTED (stub)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import secrets
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False  # Windows CI; lock is a no-op

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_STATE_DIR = "/var/lib/broodforge"
STATE_FILENAME    = "provisioning-state.json"

VALID_STATES = frozenset({
    "planned", "iso-built", "joining", "pending-approval",
    "active", "blacklisted", "decommissioned",
})

VALID_ROLES = frozenset({"worker", "control-plane", "storage", "general"})

_SUBPROCESS_TIMEOUT = 60  # seconds for all subprocess calls

# ---------------------------------------------------------------------------
# Codename vocabulary
# ---------------------------------------------------------------------------

_ADJECTIVES: list[str] = [
    "swift", "calm", "bright", "bold", "keen", "sharp", "pure", "clear",
    "firm", "fair", "still", "deep", "wide", "true", "vast", "lone",
    "free", "open", "raw", "cool", "warm", "dry", "soft", "bare",
    "quiet", "brisk", "stark", "lean", "prime", "safe",
]

_ANIMALS: list[str] = [
    "falcon", "wolf", "crane", "lynx", "raven", "osprey", "ibis", "kestrel",
    "finch", "heron", "marten", "stoat", "viper", "gecko", "wren", "quail",
    "egret", "lapwing", "curlew", "dunlin", "godwit", "bittern", "merlin",
    "hobby", "garnet", "harrier", "avocet", "plover", "dotterel", "redshank",
]


# ---------------------------------------------------------------------------
# CodenameGenerator
# ---------------------------------------------------------------------------

class CodenameGenerator:
    """Generates unique adjective-animal codenames."""

    ADJECTIVES = _ADJECTIVES
    ANIMALS    = _ANIMALS

    def generate(self, existing: set[str]) -> str:
        """Return a new codename not in `existing`.

        Raises RuntimeError if the full vocabulary is exhausted.
        """
        candidates = [
            f"{adj}-{animal}"
            for adj    in self.ADJECTIVES
            for animal in self.ANIMALS
        ]
        random.shuffle(candidates)
        for name in candidates:
            if name not in existing:
                return name
        raise RuntimeError(
            "Codename vocabulary exhausted — all adjective-animal combinations are in use."
        )


# ---------------------------------------------------------------------------
# PIN generator
# ---------------------------------------------------------------------------

def generate_join_pin() -> str:
    """
    Generate a ###-###-###-### machine-readable join PIN (12 digits, 4 groups of 3).

    The PIN is generated at plan time, embedded in the ISO, and sent by the
    broodling with its registration request. The operator sees it alongside the
    codename to verify the specific machine requesting to join, without exposing
    the node's private key.

    Format: ###-###-###-### (e.g. 042-817-394-651)
    Provides 10^12 ≈ 1 trillion combinations — far more unique than needed.
    Easier to read and verify than 4-digit groups.
    """
    groups = [f"{secrets.randbelow(1000):03d}" for _ in range(4)]
    return "-".join(groups)


# ---------------------------------------------------------------------------
# NodeAllocationPlan
# ---------------------------------------------------------------------------

@dataclass
class NodeAllocationPlan:
    """Result of planning a single new node."""

    codename:          str
    role:              str
    headscale_key:     str   # pre-auth key string (embedded in ISO)
    headscale_key_id:  str   # key ID (for revocation)
    join_pin:          str   # ####-####-####-#### PIN (embedded in ISO)
    notes:             str = ""


# ---------------------------------------------------------------------------
# NodePlanner
# ---------------------------------------------------------------------------

class NodePlanner:
    """
    Lifecycle manager for broodling provisioning state.

    All writes are atomic (write tmp → rename) and protected by a
    per-process file lock so concurrent dashboard/CLI invocations don't
    corrupt the state file.
    """

    def __init__(
        self,
        state_dir:     str | Path                        = DEFAULT_STATE_DIR,
        headscale_url: Optional[str]                     = None,
        now_fn:        Optional[Callable[[], datetime]]  = None,
    ) -> None:
        self.state_dir     = Path(state_dir)
        self.state_path    = self.state_dir / STATE_FILENAME
        self.headscale_url = headscale_url or os.environ.get("BROODFORGE_HEADSCALE_URL", "")
        self._now: Callable[[], datetime] = now_fn or (
            lambda: datetime.now(timezone.utc)
        )
        self._codegen = CodenameGenerator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan_batch(
        self,
        count: int,
        role:  str = "worker",
    ) -> list[NodeAllocationPlan]:
        """
        Allocate codenames, generate Headscale pre-auth keys, and generate
        join PINs for N new nodes.

        Checks existing Proxmox nodes (warns if pvesh unavailable) and
        provisioning-state.json to avoid collisions. Does NOT write to
        the state file — call commit_plan() to persist.
        """
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'. Valid: {sorted(VALID_ROLES)}")

        existing = self._all_known_codenames()
        plans: list[NodeAllocationPlan] = []

        for _ in range(count):
            codename = self._codegen.generate(existing)
            existing.add(codename)
            key_str, key_id = self._create_headscale_key(codename)
            pin = generate_join_pin()
            plans.append(NodeAllocationPlan(
                codename         = codename,
                role             = role,
                headscale_key    = key_str,
                headscale_key_id = key_id,
                join_pin         = pin,
            ))

        return plans

    def commit_plan(self, plans: list[NodeAllocationPlan]) -> None:
        """Write planned nodes to provisioning-state.json as state='planned'."""
        now_iso = self._now().strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._locked_state() as ctx:
            state = ctx.state
            for plan in plans:
                if any(n["codename"] == plan.codename for n in state["nodes"]):
                    raise ValueError(
                        f"Codename '{plan.codename}' already exists in provisioning state."
                    )
                entry = _empty_node_entry()
                entry.update({
                    "codename":          plan.codename,
                    "role":              plan.role,
                    "headscale_key_id":  plan.headscale_key_id,
                    "join_pin":          plan.join_pin,
                    "state":             "planned",
                    "created_at":        now_iso,
                    "updated_at":        now_iso,
                    "notes":             plan.notes,
                })
                state["nodes"].append(entry)
            self._write_state(state)

    def update_state(self, codename: str, **kwargs) -> None:
        """Update fields on a node entry. Thread-safe via file lock."""
        with self._locked_state() as ctx:
            node = _find_node(ctx.state, codename)
            if node is None:
                raise KeyError(f"Codename '{codename}' not found in provisioning state.")
            node.update(kwargs)
            node["updated_at"] = self._now().strftime("%Y-%m-%dT%H:%M:%SZ")
            self._write_state(ctx.state)

    def set_join_deadline(self, codename: str, deadline_iso: Optional[str]) -> None:
        """
        Set or clear a join deadline for a node.

        deadline_iso: ISO 8601 string (e.g. "2026-07-01T00:00:00Z") or None
                      to clear (revert to permissive / no deadline).

        If the deadline has already passed when set, a warning is printed but
        the deadline is still recorded. Auto-blacklist happens at registration
        time (in store_broodling_registration), not proactively.

        The sysadmin can always clear the blacklist by calling:
          planner.update_state(codename, blacklisted=False, blacklist_reason=None,
                               state="iso-built")
        """
        node = self.get_node(codename)
        if node is None:
            raise KeyError(f"Codename '{codename}' not found.")

        if deadline_iso is not None:
            # Validate format
            try:
                dt = datetime.fromisoformat(deadline_iso.replace("Z", "+00:00"))
                if dt <= self._now():
                    print(
                        f"[node_planner] WARNING: join_deadline for '{codename}' "
                        f"is in the past ({deadline_iso}). The node will be "
                        f"auto-blacklisted on its next registration attempt.",
                        file=sys.stderr,
                    )
            except ValueError as exc:
                raise ValueError(
                    f"Invalid deadline format '{deadline_iso}'. Use ISO 8601, e.g. "
                    "'2026-07-01T00:00:00Z'."
                ) from exc

        self.update_state(codename, join_deadline=deadline_iso)
        action = f"set to {deadline_iso}" if deadline_iso else "cleared (permissive)"
        print(f"[node_planner] Join deadline for '{codename}' {action}.")

    def get_node(self, codename: str) -> Optional[dict]:
        """Return a copy of the node entry, or None if not found."""
        state = self._load_state()
        node = _find_node(state, codename)
        return dict(node) if node is not None else None

    def list_nodes(self, state_filter: Optional[str] = None) -> list[dict]:
        """Return all nodes, optionally filtered by state."""
        nodes = self._load_state().get("nodes", [])
        if state_filter:
            nodes = [n for n in nodes if n.get("state") == state_filter]
        return list(nodes)

    def blacklist(self, codename: str, reason: str) -> None:
        """
        Mark node as blacklisted. Revokes the Headscale pre-auth key if still active.
        Valid from any state except 'active'.
        """
        with self._locked_state() as ctx:
            node = _find_node(ctx.state, codename)
            if node is None:
                raise KeyError(f"Codename '{codename}' not found.")
            if node.get("state") == "active":
                raise ValueError(
                    f"Cannot blacklist active node '{codename}'. "
                    "Use decommission instead."
                )
            key_id = node.get("headscale_key_id")
            if key_id and not node.get("blacklisted"):
                try:
                    self._revoke_headscale_key(key_id)
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[node_planner] WARNING: could not revoke Headscale key "
                        f"{key_id}: {exc}",
                        file=sys.stderr,
                    )
            now_iso = self._now().strftime("%Y-%m-%dT%H:%M:%SZ")
            node["blacklisted"]      = True
            node["blacklist_reason"] = reason
            node["state"]            = "blacklisted"
            node["updated_at"]       = now_iso
            self._write_state(ctx.state)

    def unblacklist(self, codename: str) -> None:
        """
        Clear blacklist on a node and return it to iso-built state so it may
        attempt to join again. A new pre-auth key will be needed for another
        ISO build if the old key was revoked.
        """
        with self._locked_state() as ctx:
            node = _find_node(ctx.state, codename)
            if node is None:
                raise KeyError(f"Codename '{codename}' not found.")
            if not node.get("blacklisted"):
                raise ValueError(f"'{codename}' is not currently blacklisted.")
            now_iso = self._now().strftime("%Y-%m-%dT%H:%M:%SZ")
            node["blacklisted"]      = False
            node["blacklist_reason"] = None
            node["state"]            = "iso-built"
            node["updated_at"]       = now_iso
            self._write_state(ctx.state)
        print(
            f"[node_planner] '{codename}' un-blacklisted → state iso-built. "
            "If the Headscale key was revoked, a new ISO build is required.",
        )

    def approve(self, codename: str) -> None:
        """
        Set node state to active. Also triggers Headscale node approval
        if a headscale_node_id is known.
        """
        with self._locked_state() as ctx:
            node = _find_node(ctx.state, codename)
            if node is None:
                raise KeyError(f"Codename '{codename}' not found.")
            if node.get("state") not in ("pending-approval", "joining"):
                raise ValueError(
                    f"Cannot approve '{codename}' in state '{node.get('state')}'. "
                    "Expected 'pending-approval' or 'joining'."
                )
            headscale_node_id = node.get("headscale_node_id")
            if headscale_node_id:
                try:
                    self._approve_headscale_node(str(headscale_node_id))
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[node_planner] WARNING: Headscale node approval failed: {exc}",
                        file=sys.stderr,
                    )
            now_iso = self._now().strftime("%Y-%m-%dT%H:%M:%SZ")
            node["state"]       = "active"
            node["approved_at"] = now_iso
            node["updated_at"]  = now_iso
            self._write_state(ctx.state)

    def decommission(self, codename: str) -> None:
        """
        Mark node as decommissioned. Deletes the Headscale node entry.
        The state file retains the record for audit history.
        """
        with self._locked_state() as ctx:
            node = _find_node(ctx.state, codename)
            if node is None:
                raise KeyError(f"Codename '{codename}' not found.")
            headscale_node_id = node.get("headscale_node_id")
            if headscale_node_id:
                try:
                    self._delete_headscale_node(str(headscale_node_id))
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[node_planner] WARNING: Headscale node delete failed: {exc}",
                        file=sys.stderr,
                    )
            now_iso = self._now().strftime("%Y-%m-%dT%H:%M:%SZ")
            node["state"]             = "decommissioned"
            node["decommissioned_at"] = now_iso
            node["updated_at"]        = now_iso
            self._write_state(ctx.state)

    def rename_headscale(self, codename: str, new_name: str) -> None:
        """
        Rename a Headscale device. Requires an active headscale_node_id.
        Updates headscale_device_name in state.
        """
        node = self.get_node(codename)
        if node is None:
            raise KeyError(f"Codename '{codename}' not found.")
        headscale_node_id = node.get("headscale_node_id")
        if not headscale_node_id:
            raise ValueError(f"'{codename}' has no Headscale node ID recorded yet.")
        result = subprocess.run(
            ["headscale", "nodes", "rename",
             "--identifier", str(headscale_node_id),
             "--new-name", new_name],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"headscale nodes rename failed: {result.stderr.strip()}"
            )
        self.update_state(codename, headscale_device_name=new_name)

    def update_node_fields(
        self,
        codename:         str,
        display_name:     Optional[str] = None,
        notes:            Optional[str] = None,
        role:             Optional[str] = None,
        assigned_address: Optional[str] = None,
    ) -> None:
        """Update editable operator-visible fields."""
        kwargs: dict = {}
        if display_name is not None:
            kwargs["display_name"] = display_name
        if notes is not None:
            kwargs["notes"] = notes
        if role is not None:
            if role not in VALID_ROLES:
                raise ValueError(f"Invalid role '{role}'.")
            kwargs["role"] = role
        if assigned_address is not None:
            kwargs["assigned_address"] = assigned_address
        if not kwargs:
            raise ValueError("No fields to update.")
        self.update_state(codename, **kwargs)

    def store_broodling_registration(
        self,
        codename:       str,
        public_key_pem: str,
        join_pin:       str,
    ) -> None:
        """
        Called when a broodling posts its registration request.

        Validates the join_pin (rejects if wrong — indicates wrong ISO or spoofed
        request). Checks join_deadline and auto-blacklists if expired.
        Stores the broodling's public key, computes its fingerprint,
        and advances state to pending-approval.

        Raises ValueError with a clear message on validation failures.
        """
        node = self.get_node(codename)
        if node is None:
            raise KeyError(f"Unknown codename '{codename}'.")

        # Verify join PIN
        expected_pin = node.get("join_pin", "")
        if not secrets.compare_digest(
            (join_pin or "").strip(),
            (expected_pin or "").strip(),
        ):
            raise ValueError(
                f"Join PIN mismatch for '{codename}'. "
                "Registration rejected. Check that the correct ISO was used."
            )

        # Check join deadline (auto-blacklist if expired)
        deadline_str = node.get("join_deadline")
        if deadline_str:
            try:
                deadline_dt = datetime.fromisoformat(deadline_str.replace("Z", "+00:00"))
                if self._now().astimezone(timezone.utc) > deadline_dt.astimezone(timezone.utc):
                    reason = (
                        f"Auto-blacklisted: join_deadline {deadline_str} expired "
                        f"before registration arrived."
                    )
                    self.blacklist(codename, reason=reason)
                    raise ValueError(
                        f"'{codename}' join deadline has expired. Node has been "
                        "auto-blacklisted. The sysadmin can un-blacklist it via "
                        "the Nodes panel or node_planner.py --unblacklist."
                    )
            except (ValueError, TypeError) as exc:
                if "auto-blacklisted" in str(exc).lower() or "expired" in str(exc).lower():
                    raise
                # Bad deadline format — log and proceed permissively
                print(
                    f"[node_planner] WARNING: could not parse join_deadline "
                    f"'{deadline_str}' for '{codename}': {exc}",
                    file=sys.stderr,
                )

        # All checks passed — store registration
        fingerprint = _compute_key_fingerprint(public_key_pem)
        now_iso = self._now().strftime("%Y-%m-%dT%H:%M:%SZ")
        self.update_state(
            codename,
            broodling_public_key_pem         = public_key_pem,
            broodling_public_key_fingerprint = fingerprint,
            state                            = "pending-approval",
            joined_at                        = now_iso,
        )

    # ------------------------------------------------------------------
    # Private: Headscale integration
    # ------------------------------------------------------------------

    def _create_headscale_key(self, codename: str) -> tuple[str, str]:
        """
        Generate a single-use Headscale pre-auth key.
        Returns (key_string, key_id).
        Falls back to stub values if headscale CLI is unavailable.
        """
        if not self.headscale_url:
            print(
                f"[node_planner] WARNING: BROODFORGE_HEADSCALE_URL not set. "
                f"Using stub key for '{codename}'. Set the URL before ISO build.",
                file=sys.stderr,
            )
            return (f"STUB_KEY_{codename}", f"STUB_ID_{codename}")

        cmd = [
            "headscale", "preauthkeys", "create",
            "--one-time",
            "--expiration", "0",
            "--tags", "tag:broodling",
            "--output", "json",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except FileNotFoundError:
            print(
                "[node_planner] WARNING: 'headscale' CLI not found. Using stub key.",
                file=sys.stderr,
            )
            return (f"STUB_KEY_{codename}", f"STUB_ID_{codename}")

        if result.returncode != 0:
            raise RuntimeError(
                f"headscale preauthkeys create failed: {result.stderr.strip()}"
            )

        try:
            data = json.loads(result.stdout)
            if isinstance(data, dict):
                key_str = data.get("key") or data.get("authKey") or ""
                key_id  = str(data.get("id") or data.get("ID") or "")
            else:
                key_str = str(data)
                key_id  = ""
        except (json.JSONDecodeError, AttributeError):
            key_str = result.stdout.strip()
            key_id  = ""

        if not key_str:
            raise RuntimeError("headscale returned an empty pre-auth key.")

        return (key_str, key_id)

    def _revoke_headscale_key(self, key_id: str) -> None:
        """headscale preauthkeys expire --id <key_id>"""
        if not key_id or key_id.startswith("STUB_"):
            return
        result = subprocess.run(
            ["headscale", "preauthkeys", "expire", "--id", key_id],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"headscale preauthkeys expire failed: {result.stderr.strip()}"
            )

    def _approve_headscale_node(self, headscale_node_id: str) -> None:
        """headscale nodes approve --identifier <id>"""
        if not headscale_node_id or headscale_node_id.startswith("STUB_"):
            return
        result = subprocess.run(
            ["headscale", "nodes", "approve", "--identifier", headscale_node_id],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"headscale nodes approve failed: {result.stderr.strip()}"
            )

    def _delete_headscale_node(self, headscale_node_id: str) -> None:
        """headscale nodes delete --identifier <id> --force"""
        if not headscale_node_id or headscale_node_id.startswith("STUB_"):
            return
        result = subprocess.run(
            ["headscale", "nodes", "delete",
             "--identifier", headscale_node_id,
             "--force"],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"headscale nodes delete failed: {result.stderr.strip()}"
            )

    # ------------------------------------------------------------------
    # Private: state file I/O
    # ------------------------------------------------------------------

    def _load_state(self) -> dict:
        """Load provisioning-state.json. Returns empty state structure if absent."""
        if not self.state_path.exists():
            return {"nodes": []}
        with open(self.state_path) as fh:
            try:
                return json.load(fh)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"provisioning-state.json is corrupt: {exc}"
                ) from exc

    def _write_state(self, state: dict) -> None:
        """Atomically write state to disk (tmp file then rename)."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(".json.tmp")
        with open(tmp_path, "w") as fh:
            json.dump(state, fh, indent=2, default=str)
            fh.write("\n")
        tmp_path.rename(self.state_path)

    def _locked_state(self) -> "_StateLock":
        """Context manager that holds an exclusive file lock."""
        return _StateLock(self)

    def _all_known_codenames(self) -> set[str]:
        """Collect all codenames that must not be reused."""
        existing: set[str] = set()

        # From provisioning state
        state = self._load_state()
        for node in state.get("nodes", []):
            cn = node.get("codename")
            if cn:
                existing.add(cn)

        # From Proxmox API (best-effort)
        try:
            result = subprocess.run(
                ["pvesh", "get", "/nodes", "--output-format", "json"],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode == 0:
                pve_nodes = json.loads(result.stdout)
                for n in pve_nodes:
                    name = n.get("node") or n.get("name")
                    if name:
                        existing.add(name)
        except Exception:  # noqa: BLE001
            print(
                "[node_planner] WARNING: Could not query Proxmox API (pvesh). "
                "Checking provisioning state only.",
                file=sys.stderr,
            )

        return existing


# ---------------------------------------------------------------------------
# _StateLock — context manager for locked reads+writes
# ---------------------------------------------------------------------------

class _StateLock:
    """
    Context manager: acquires an exclusive file lock, loads state, yields
    a context object. The caller must call _write_state() before exiting
    to persist any changes.
    """

    def __init__(self, planner: "NodePlanner") -> None:
        self._planner   = planner
        self._lock_path = planner.state_path.with_suffix(".json.lock")
        self._lock_fh   = None
        self.state: dict = {}

    def __enter__(self) -> "_StateLock":
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_fh = open(self._lock_path, "w")
        if _HAS_FCNTL:
            try:
                fcntl.flock(self._lock_fh, fcntl.LOCK_EX)
            except OSError:
                pass
        self.state = self._planner._load_state()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._lock_fh:
            if _HAS_FCNTL:
                try:
                    fcntl.flock(self._lock_fh, fcntl.LOCK_UN)
                except OSError:
                    pass
            self._lock_fh.close()
            self._lock_fh = None
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_node_entry() -> dict:
    """Return a fully-populated node dict with all fields at zero values."""
    return {
        "codename":                       "",
        "display_name":                   "",
        "role":                           "worker",
        "headscale_key_id":               None,
        "headscale_node_id":              None,
        "headscale_device_name":          None,
        "join_pin":                       None,
        "join_deadline":                  None,   # null = permissive (no deadline)
        "iso_path":                       None,
        "iso_built_at":                   None,
        "created_at":                     None,
        "updated_at":                     None,
        "joined_at":                      None,
        "approved_at":                    None,
        "decommissioned_at":              None,
        "state":                          "planned",
        "blacklisted":                    False,
        "blacklist_reason":               None,
        "notes":                          "",
        "assigned_address":               None,
        "broodling_public_key_pem":       None,
        "broodling_public_key_fingerprint": None,
    }


def _find_node(state: dict, codename: str) -> Optional[dict]:
    """Return the mutable node dict from state, or None."""
    for node in state.get("nodes", []):
        if node.get("codename") == codename:
            return node
    return None


def _compute_key_fingerprint(public_key_pem: str) -> str:
    """
    Compute a fingerprint of a PEM public key via openssl.
    Falls back to a truncated SHA-256 hex if openssl is unavailable.
    """
    import hashlib
    try:
        result = subprocess.run(
            ["openssl", "pkey", "-pubin", "-noout", "-fingerprint", "-sha256"],
            input=public_key_pem.encode(),
            capture_output=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode == 0:
            return result.stdout.decode().strip()
    except Exception:  # noqa: BLE001
        pass
    digest = hashlib.sha256(public_key_pem.encode()).hexdigest()
    return f"SHA256:{digest[:32]}..."


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_plan(args: argparse.Namespace, planner: NodePlanner) -> int:
    plans = planner.plan_batch(count=args.count, role=args.role)
    output = [
        {
            "codename":         p.codename,
            "role":             p.role,
            "headscale_key":    p.headscale_key,
            "headscale_key_id": p.headscale_key_id,
            "join_pin":         p.join_pin,
            "notes":            p.notes,
        }
        for p in plans
    ]
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print("\nProposed batch:")
        for i, p in enumerate(plans, 1):
            key_preview = (
                p.headscale_key[:12] + "..."
                if len(p.headscale_key) > 12
                else p.headscale_key
            )
            print(
                f"  {i:2d}. {p.codename:<22s} {p.role:<15s} "
                f"PIN: {p.join_pin}  [Headscale key: {key_preview}]"
            )
        print()
    return 0


def _cli_commit(args: argparse.Namespace, planner: NodePlanner) -> int:
    with open(args.plan_file) as fh:
        raw = json.load(fh)
    plans = [
        NodeAllocationPlan(
            codename         = entry["codename"],
            role             = entry["role"],
            headscale_key    = entry.get("headscale_key", ""),
            headscale_key_id = entry.get("headscale_key_id", ""),
            join_pin         = entry.get("join_pin", generate_join_pin()),
            notes            = entry.get("notes", ""),
        )
        for entry in raw
    ]
    planner.commit_plan(plans)
    print(f"[node_planner] Committed {len(plans)} node(s) to provisioning state.")
    return 0


def _cli_list(args: argparse.Namespace, planner: NodePlanner) -> int:
    state_filter = getattr(args, "state_filter", None)
    nodes = planner.list_nodes(state_filter=state_filter)
    if getattr(args, "json", False):
        print(json.dumps(nodes, indent=2, default=str))
    else:
        if not nodes:
            print("No nodes found.")
            return 0
        print(f"{'Codename':<22} {'Role':<14} {'State':<20} {'PIN':<16} {'Created':<22}")
        print("-" * 96)
        for n in nodes:
            created = (n.get("created_at") or "")[:16]
            pin     = n.get("join_pin") or "—"
            print(
                f"{n.get('codename',''):<22} "
                f"{n.get('role',''):<14} "
                f"{n.get('state',''):<20} "
                f"{pin:<16} "
                f"{created:<22}"
            )
    return 0


def _cli_approve(args: argparse.Namespace, planner: NodePlanner) -> int:
    planner.approve(args.codename)
    print(f"[node_planner] '{args.codename}' approved — state set to active.")
    return 0


def _cli_blacklist(args: argparse.Namespace, planner: NodePlanner) -> int:
    planner.blacklist(args.codename, args.reason)
    print(f"[node_planner] '{args.codename}' blacklisted.")
    return 0


def _cli_unblacklist(args: argparse.Namespace, planner: NodePlanner) -> int:
    planner.unblacklist(args.codename)
    return 0


def _cli_set_deadline(args: argparse.Namespace, planner: NodePlanner) -> int:
    deadline = args.deadline if args.deadline != "none" else None
    planner.set_join_deadline(args.codename, deadline)
    return 0


def _cli_update(args: argparse.Namespace, planner: NodePlanner) -> int:
    updates: dict = {}
    for pair in args.set:
        if "=" not in pair:
            print(
                f"[node_planner] ERROR: --set value must be key=value, got: {pair!r}",
                file=sys.stderr,
            )
            return 1
        k, v = pair.split("=", 1)
        updates[k] = v
    planner.update_state(args.codename, **updates)
    print(f"[node_planner] Updated '{args.codename}': {list(updates.keys())}")
    return 0


def main(argv: list[str] | None = None) -> int:  # noqa: C901
    ap = argparse.ArgumentParser(
        description="broodforge node provisioning planner (Phase 1.Q)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 node_planner.py --plan --count 3 --role worker --json\n"
            "  python3 node_planner.py --commit --plan-file plan.json\n"
            "  python3 node_planner.py --list [--state pending-approval] [--json]\n"
            "  python3 node_planner.py --approve swift-falcon\n"
            "  python3 node_planner.py --blacklist calm-raven --reason 'Wrong hardware'\n"
            "  python3 node_planner.py --unblacklist calm-raven\n"
            "  python3 node_planner.py --set-deadline bold-lynx --deadline 2026-08-01T00:00:00Z\n"
            "  python3 node_planner.py --set-deadline bold-lynx --deadline none  # clear deadline\n"
            "  python3 node_planner.py --update bold-lynx --set state=joining headscale_node_id=42\n"
        ),
    )

    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan",         action="store_true", help="Plan a batch of new nodes")
    mode.add_argument("--commit",       action="store_true", help="Commit a plan file to state")
    mode.add_argument("--list",         action="store_true", help="List nodes")
    mode.add_argument("--approve",      metavar="CODENAME",  help="Approve a node join")
    mode.add_argument("--blacklist",    metavar="CODENAME",  help="Blacklist a node")
    mode.add_argument("--unblacklist",  metavar="CODENAME",  help="Un-blacklist a node (restore to iso-built)")
    mode.add_argument("--set-deadline", metavar="CODENAME",  help="Set or clear a join deadline")
    mode.add_argument("--update",       metavar="CODENAME",  help="Update state fields")

    # --plan
    ap.add_argument("--count",  type=int, default=1, metavar="N",
                    help="Number of nodes to plan (default: 1)")
    ap.add_argument("--role",   default="worker", choices=sorted(VALID_ROLES),
                    help="Node role (default: worker)")
    ap.add_argument("--json",   action="store_true", help="Output JSON")

    # --commit
    ap.add_argument("--plan-file", metavar="PATH", help="JSON plan file to commit")

    # --list
    ap.add_argument("--state",  dest="state_filter", metavar="STATE",
                    help="Filter by lifecycle state")

    # --blacklist
    ap.add_argument("--reason", default="", help="Reason for blacklisting")

    # --set-deadline
    ap.add_argument("--deadline", metavar="ISO8601_OR_NONE",
                    help="Deadline timestamp (ISO 8601) or 'none' to clear")

    # --update
    ap.add_argument("--set", nargs="+", metavar="KEY=VALUE",
                    help="Fields to update (e.g. state=joining headscale_node_id=42)")

    # global
    ap.add_argument("--state-dir", metavar="DIR",
                    help="Override BROODFORGE_STATE_DIR")

    parsed = ap.parse_args(argv)

    planner = NodePlanner(
        state_dir     = parsed.state_dir or os.environ.get(
            "BROODFORGE_STATE_DIR", DEFAULT_STATE_DIR
        ),
        headscale_url = os.environ.get("BROODFORGE_HEADSCALE_URL", ""),
    )

    try:
        if parsed.plan:
            return _cli_plan(parsed, planner)
        if parsed.commit:
            if not parsed.plan_file:
                print("[node_planner] ERROR: --commit requires --plan-file", file=sys.stderr)
                return 1
            return _cli_commit(parsed, planner)
        if parsed.list:
            return _cli_list(parsed, planner)
        if parsed.approve:
            parsed.codename = parsed.approve
            return _cli_approve(parsed, planner)
        if parsed.blacklist:
            parsed.codename = parsed.blacklist
            if not parsed.reason:
                print("[node_planner] ERROR: --blacklist requires --reason", file=sys.stderr)
                return 1
            return _cli_blacklist(parsed, planner)
        if parsed.unblacklist:
            parsed.codename = parsed.unblacklist
            return _cli_unblacklist(parsed, planner)
        if parsed.set_deadline:
            parsed.codename = parsed.set_deadline
            if not parsed.deadline:
                print(
                    "[node_planner] ERROR: --set-deadline requires --deadline "
                    "(ISO 8601 or 'none' to clear)",
                    file=sys.stderr,
                )
                return 1
            return _cli_set_deadline(parsed, planner)
        if parsed.update:
            parsed.codename = parsed.update
            if not parsed.set:
                print("[node_planner] ERROR: --update requires --set", file=sys.stderr)
                return 1
            return _cli_update(parsed, planner)
    except (KeyError, ValueError) as exc:
        print(f"[node_planner] ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[node_planner] FATAL: {exc}", file=sys.stderr)
        return 1

    return 2  # NOT_IMPLEMENTED


if __name__ == "__main__":
    sys.exit(main())
