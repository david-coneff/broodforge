#!/usr/bin/env python3
"""
proxmox-bootstrap/user_registry.py — Broodforge user registry (Phase 1.U).

Tracks all users who should have accounts on broodforge-managed Kubernetes services.
This registry lives above the Kubernetes layer so that:

  - On a full cluster rebuild/forge, all active users are automatically re-provisioned
    into each service (no manual re-registration required).
  - Each user is "dispositioned": active users are created by default on rebuild;
    archived users are preserved in the registry but skipped during provisioning.
  - Per-user, per-service credentials are held in the master KeePass DB under
    Broodforge/users/<username>/<service>/ until the key-throw-away operation
    is performed.
  - After key throw-away, the admin can still delete the account but cannot read
    or impersonate the user (zero-knowledge property).

Data flow:
  1. forge-onboard-user.sh   — creates UserRecord, generates credentials, stores in KeePass
  2. forge-provision-users.sh — reads registry, provisions accounts in k8s services
  3. forge-throw-away-key     — deletes KeePass entries, sets key_thrown_away=True
  4. Sidecar GUI              — reads/writes user-registry.json for operator view

Storage:
  config/user-registry.json  — committed; non-sensitive metadata only
  Master KeePass              — Broodforge/users/<user>/<service>/{password,totp-secret}

CLI:
  python3 user_registry.py --list
  python3 user_registry.py --add --username alice --email alice@example.com \\
      --services vaultwarden,headscale,gitea
  python3 user_registry.py --disposition alice archived
  python3 user_registry.py --throw-away-key alice vaultwarden
  python3 user_registry.py --users-for-rebuild
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

DISPOSITIONS = {"active", "archived", "pending-deletion"}


@dataclass
class ServiceEnrollment:
    """Per-service state for one user."""

    role: str = "user"
    key_thrown_away: bool = False
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ServiceEnrollment":
        return cls(
            role=d.get("role", "user"),
            key_thrown_away=bool(d.get("key_thrown_away", False)),
            notes=d.get("notes", ""),
        )

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "key_thrown_away": self.key_thrown_away,
            "notes": self.notes,
        }


@dataclass
class UserRecord:
    """One registered user."""

    id: str
    username: str
    display_name: str
    email: str
    disposition: str  # active | archived | pending-deletion
    services: dict  # service_name → ServiceEnrollment
    onboarding_acknowledged: bool = False
    registered_at: str = ""  # ISO-8601 UTC

    @classmethod
    def from_dict(cls, d: dict) -> "UserRecord":
        services = {
            svc: ServiceEnrollment.from_dict(enroll)
            for svc, enroll in d.get("services", {}).items()
        }
        return cls(
            id=d["id"],
            username=d["username"],
            display_name=d.get("display_name", d["username"]),
            email=d.get("email", ""),
            disposition=d.get("disposition", "active"),
            services=services,
            onboarding_acknowledged=bool(d.get("onboarding_acknowledged", False)),
            registered_at=d.get("registered_at", ""),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "disposition": self.disposition,
            "services": {
                svc: enroll.to_dict() for svc, enroll in self.services.items()
            },
            "onboarding_acknowledged": self.onboarding_acknowledged,
            "registered_at": self.registered_at,
        }


@dataclass
class UserRegistry:
    """Root registry object."""

    schema_version: str
    users: list = field(default_factory=list)  # list[UserRecord]

    @classmethod
    def from_dict(cls, d: dict) -> "UserRegistry":
        return cls(
            schema_version=str(d.get("schema_version", "1")),
            users=[UserRecord.from_dict(u) for u in d.get("users", [])],
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "users": [u.to_dict() for u in self.users],
        }


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class UserRegistryManager:
    """Load, modify, and save the user registry."""

    def __init__(self, registry_path: Path):
        self.registry_path = Path(registry_path)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> UserRegistry:
        """Load registry from JSON. Returns empty registry if file absent."""
        if not self.registry_path.exists():
            return UserRegistry(schema_version="1", users=[])
        with open(self.registry_path, encoding="utf-8") as fh:
            return UserRegistry.from_dict(json.load(fh))

    def save(self, registry: UserRegistry) -> None:
        """Atomically save registry to JSON."""
        tmp = self.registry_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(registry.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.registry_path)

    def init_skeleton(self) -> UserRegistry:
        """Create an empty registry file. Raises FileExistsError if already present."""
        if self.registry_path.exists():
            raise FileExistsError(
                f"Registry already exists: {self.registry_path}. "
                "Use --force to overwrite."
            )
        registry = UserRegistry(schema_version="1", users=[])
        self.save(registry)
        return registry

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------

    def get_user(self, username: str) -> Optional[UserRecord]:
        registry = self.load()
        for user in registry.users:
            if user.username == username:
                return user
        return None

    def add_user(
        self,
        username: str,
        display_name: str,
        email: str,
        services: list,  # list[str] — service names
        roles: Optional[dict] = None,  # service → role override
        now_fn=None,
    ) -> UserRecord:
        """Add a new user. Raises ValueError if username already exists."""
        registry = self.load()
        existing = next(
            (u for u in registry.users if u.username == username), None
        )
        if existing is not None:
            raise ValueError(f"User already registered: {username!r}")

        if roles is None:
            roles = {}

        if now_fn is None:
            now_fn = lambda: datetime.now(timezone.utc)

        record = UserRecord(
            id=str(uuid.uuid4()),
            username=username,
            display_name=display_name or username,
            email=email,
            disposition="active",
            services={
                svc: ServiceEnrollment(role=roles.get(svc, "user"))
                for svc in services
            },
            onboarding_acknowledged=False,
            registered_at=now_fn().isoformat(),
        )
        registry.users.append(record)
        self.save(registry)
        return record

    def update_user(self, record: UserRecord) -> None:
        """Persist changes to an existing UserRecord back to the registry."""
        registry = self.load()
        for i, u in enumerate(registry.users):
            if u.username == record.username:
                registry.users[i] = record
                self.save(registry)
                return
        raise ValueError(f"User not found: {record.username!r}")

    def set_disposition(self, username: str, disposition: str) -> UserRecord:
        """Set user disposition. Valid values: active, archived, pending-deletion."""
        if disposition not in DISPOSITIONS:
            raise ValueError(
                f"Invalid disposition {disposition!r}. "
                f"Valid: {sorted(DISPOSITIONS)}"
            )
        record = self.get_user(username)
        if record is None:
            raise ValueError(f"User not found: {username!r}")
        record.disposition = disposition
        self.update_user(record)
        return record

    def acknowledge_onboarding(self, username: str) -> UserRecord:
        """Mark user as having acknowledged their onboarding package."""
        record = self.get_user(username)
        if record is None:
            raise ValueError(f"User not found: {username!r}")
        record.onboarding_acknowledged = True
        self.update_user(record)
        return record

    # ------------------------------------------------------------------
    # Key throw-away
    # ------------------------------------------------------------------

    def add_service(
        self,
        username: str,
        service: str,
        role: str = "user",
        notes: str = "",
    ) -> UserRecord:
        """Enroll an existing user in an additional service.

        Raises ValueError if the user doesn't exist or is already enrolled.
        Credential generation (KeePass storage) is handled separately by
        forge-onboard-user.sh --add-service.
        """
        record = self.get_user(username)
        if record is None:
            raise ValueError(f"User not found: {username!r}")
        if service in record.services:
            raise ValueError(
                f"User {username!r} is already enrolled in {service!r}. "
                "Use --throw-away-key + re-onboard if you need to reset credentials."
            )
        record.services[service] = ServiceEnrollment(role=role, notes=notes)
        self.update_user(record)
        return record

    def throw_away_key(self, username: str, service: str) -> UserRecord:
        """Mark KeePass key as thrown away for user+service.

        This sets the flag only. The caller (forge-throw-away-key) is responsible
        for actually deleting the KeePass entry before calling this method,
        so there is no window where the flag is set but the key still exists.

        Raises ValueError if user or service not found, or key already thrown away.
        """
        record = self.get_user(username)
        if record is None:
            raise ValueError(f"User not found: {username!r}")
        if service not in record.services:
            raise ValueError(
                f"Service {service!r} not enrolled for user {username!r}. "
                f"Enrolled: {sorted(record.services)}"
            )
        enrollment = record.services[service]
        if enrollment.key_thrown_away:
            raise ValueError(
                f"Key already thrown away for {username!r}/{service!r}."
            )
        enrollment.key_thrown_away = True
        self.update_user(record)
        return record

    # ------------------------------------------------------------------
    # Rebuild queries
    # ------------------------------------------------------------------

    def users_for_rebuild(self) -> list:
        """Return all active users (disposition == active)."""
        registry = self.load()
        return [u for u in registry.users if u.disposition == "active"]

    def users_needing_provision(self, service: str) -> list:
        """Active users enrolled in service whose key is NOT thrown away."""
        return [
            u for u in self.users_for_rebuild()
            if service in u.services
            and not u.services[service].key_thrown_away
        ]

    def users_needing_reset(self, service: str) -> list:
        """Active users enrolled in service whose key IS thrown away (need reset link)."""
        return [
            u for u in self.users_for_rebuild()
            if service in u.services
            and u.services[service].key_thrown_away
        ]


# ---------------------------------------------------------------------------
# KeePass path convention
# ---------------------------------------------------------------------------

def keeass_entry_path(username: str, service: str, field: str = "password") -> str:
    """Return the master KeePass entry path for a user+service credential.

    Convention:  Broodforge/users/<username>/<service>/<field>
    field values: password | totp-secret | api-key | preshared-key
    """
    return f"Broodforge/users/{username}/{service}/{field}"


def keepass_totp_path(username: str, service: str) -> str:
    return keeass_entry_path(username, service, "totp-secret")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_list(manager: UserRegistryManager, args) -> int:
    registry = manager.load()
    if not registry.users:
        print("No users registered.")
        return 0
    for u in registry.users:
        services = ", ".join(
            f"{svc}{'(key-gone)' if e.key_thrown_away else ''}"
            for svc, e in u.services.items()
        )
        ack = "✓" if u.onboarding_acknowledged else "○"
        print(f"  {ack} {u.username:<20} [{u.disposition:<16}] {services}")
    return 0


def _cmd_add(manager: UserRegistryManager, args) -> int:
    services = [s.strip() for s in args.services.split(",") if s.strip()]
    try:
        record = manager.add_user(
            username=args.username,
            display_name=args.display_name or args.username,
            email=args.email or "",
            services=services,
        )
        print(f"Added user {record.username!r} (id={record.id})")
        print(f"  Services: {', '.join(record.services)}")
        print(
            f"\nNext: run forge-onboard-user.sh --user {record.username} to generate "
            "and store credentials in KeePass and produce an onboarding package."
        )
        return 0
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _cmd_disposition(manager: UserRegistryManager, args) -> int:
    try:
        record = manager.set_disposition(args.username, args.disposition)
        print(f"Set {record.username!r} disposition → {record.disposition}")
        return 0
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _cmd_add_service(manager: UserRegistryManager, args) -> int:
    username, service = args.add_service
    role = args.role or "user"
    try:
        record = manager.add_service(username, service, role=role)
        print(
            f"Enrolled {username!r} in {service!r} (role={role}).\n"
            f"\nNext: run forge-onboard-user.sh --add-service {username} {service}\n"
            f"to generate credentials and store them in KeePass."
        )
        return 0
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _cmd_throw_away_key(manager: UserRegistryManager, args) -> int:
    # This command does NOT delete the KeePass entry itself —
    # that must be done by the caller BEFORE running this command.
    print(
        f"WARNING: This marks the key as thrown away for {args.username!r}/{args.service!r}.\n"
        f"Ensure you have ALREADY deleted the KeePass entry at:\n"
        f"  {keeass_entry_path(args.username, args.service)}\n"
        f"before proceeding. Once marked, auto-provisioning will use a reset flow.\n"
    )
    if not args.yes:
        confirm = input("Type 'yes' to confirm: ").strip()
        if confirm != "yes":
            print("Aborted.")
            return 1
    try:
        manager.throw_away_key(args.username, args.service)
        print(
            f"Marked key_thrown_away=true for {args.username!r}/{args.service!r}.\n"
            f"On next rebuild, this user will receive a password-reset flow for "
            f"{args.service!r} instead of auto-provisioning."
        )
        return 0
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _cmd_users_for_rebuild(manager: UserRegistryManager, args) -> int:
    users = manager.users_for_rebuild()
    if not users:
        print("No active users.")
        return 0
    for u in users:
        for svc, enroll in u.services.items():
            flow = "reset" if enroll.key_thrown_away else "provision"
            print(f"{u.username}\t{svc}\t{flow}\t{u.email}")
    return 0


def _cmd_init(manager: UserRegistryManager, args) -> int:
    try:
        manager.init_skeleton()
        print(f"Created empty user registry: {manager.registry_path}")
        return 0
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Broodforge user registry — manage service users above the k8s layer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  --list                        List all registered users
  --add                         Add a new user (requires --username --services)
  --add-service <user> <svc>    Enroll existing user in an additional service
  --disposition <user> <value>  Set user disposition: active | archived | pending-deletion
  --throw-away-key <user> <svc> Mark key as discarded (admin loses credential access)
  --users-for-rebuild           Print TSV: username, service, flow (provision|reset)
  --init                        Create empty registry file

KeePass path convention:
  Broodforge/users/<username>/<service>/password
  Broodforge/users/<username>/<service>/totp-secret
""",
    )
    parser.add_argument(
        "--registry",
        default=str(
            Path(__file__).resolve().parents[1] / "config" / "user-registry.json"
        ),
        help="Path to user-registry.json (default: config/user-registry.json)",
    )

    # Sub-commands via flags (mirrors credential_hierarchy.py style)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--add", action="store_true")
    mode.add_argument("--disposition", nargs=2, metavar=("USERNAME", "DISPOSITION"))
    mode.add_argument("--add-service", nargs=2, metavar=("USERNAME", "SERVICE"),
                      dest="add_service",
                      help="Enroll existing user in an additional service")
    mode.add_argument("--throw-away-key", nargs=2, metavar=("USERNAME", "SERVICE"),
                      dest="throw_away_key")
    mode.add_argument("--users-for-rebuild", action="store_true")
    mode.add_argument("--init", action="store_true")

    # --add / --add-service options
    parser.add_argument("--username")
    parser.add_argument("--display-name", dest="display_name", default="")
    parser.add_argument("--email", default="")
    parser.add_argument(
        "--services",
        help="Comma-separated service names, e.g. vaultwarden,headscale,gitea",
    )
    parser.add_argument(
        "--role", default="user",
        help="Role for the enrolled service (default: user)",
    )
    parser.add_argument("--yes", action="store_true",
                        help="Skip confirmation prompt for destructive operations")

    args = parser.parse_args(argv)
    manager = UserRegistryManager(Path(args.registry))

    if args.list:
        return _cmd_list(manager, args)
    if args.add:
        if not args.username or not args.services:
            parser.error("--add requires --username and --services")
        return _cmd_add(manager, args)
    if args.add_service:
        return _cmd_add_service(manager, args)
    if args.disposition:
        args.username, args.disposition = args.disposition
        return _cmd_disposition(manager, args)
    if args.throw_away_key:
        args.username, args.service = args.throw_away_key
        return _cmd_throw_away_key(manager, args)
    if args.users_for_rebuild:
        return _cmd_users_for_rebuild(manager, args)
    if args.init:
        return _cmd_init(manager, args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
