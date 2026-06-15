#!/usr/bin/env python3
"""
openbao_manager.py — Phase 3.L: OpenBao Secrets Broker
=======================================================
Python API client for OpenBao (open-source HashiCorp Vault fork).
Replaces keepassxc-cli as the machine-facing secrets broker in broodforge.

Topology
--------
OpenBao runs as a systemd service on the governance VM, not exposed outside
the Headscale overlay network.  All secrets that broodforge previously read
directly from KeePass child DBs are now served via OpenBao; KeePass remains
as the human-facing encrypted credential store (and optionally the audit
record after bootstrap — see UNSEAL_STRATEGY / KEEPASS_MODE below).

Operator decisions (set via environment or openbao-config.json)
---------------------------------------------------------------
OPENBAO_UNSEAL_STRATEGY:
  "transit"   — Auto-unseal via a second OpenBao Transit instance (HA-friendly,
                requires a second OpenBao process; adds infrastructure but zero
                operator involvement on restart).
  "shamir"    — Manual Shamir 3-of-5 unseal.  Keys split across: KeePass
                master DB (2 shards), two offline USB keys (2 shards), and the
                governance VM's TPM-sealed key file (1 shard).
                Requires operator action after every reboot.

OPENBAO_KEEPASS_MODE:
  "writable"  — KeePass child DBs remain writable.  `forge-sync-credentials.sh`
                writes new secrets to both OpenBao and KeePass so KeePass
                remains a human-readable audit copy.
  "readonly"  — After bootstrap, KeePass child DBs become read-only (no direct
                machine writes).  OpenBao is the single authoritative source.
                Reduces attack surface but removes the human-readable fallback.

Path schema
-----------
  child://forge-autonomous/group/entry  →  forge/autonomous/<group>/<entry>
  child://forge-spawn/group/entry       →  forge/spawn/<group>/<entry>
  child://forge-migrate/group/entry     →  forge/migrate/<group>/<entry>
  TOTP accounts                         →  forge/totp/code/<account>

Usage (from forge-lib.sh wrapper)
----------------------------------
  python3 openbao_manager.py read  forge/autonomous/proxmox/api_token
  python3 openbao_manager.py write forge/spawn/ssh/key_passphrase  --value '...'
  python3 openbao_manager.py totp  forge/totp/code/proxmox_admin
  python3 openbao_manager.py status
  python3 openbao_manager.py unseal  --keys-file /tmp/unseal_shards.json
  python3 openbao_manager.py audit   --limit 50
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = Path("/etc/broodforge/openbao-config.json")
FALLBACK_CONFIG: dict[str, Any] = {
    "addr":             "http://127.0.0.1:8200",
    "namespace":        "",
    "token_env":        "OPENBAO_TOKEN",
    "token_file":       "/run/broodforge/openbao-token",
    "unseal_strategy":  "shamir",       # "transit" | "shamir"
    "keepass_mode":     "writable",     # "writable" | "readonly"
    "mount_kv":         "forge",
    "mount_totp":       "forge/totp",
    "transit_addr":     "",             # only for unseal_strategy=transit
    "transit_key":      "broodforge-unseal",
    "audit_path":       "file/",
    "request_timeout":  10,
    "retry_attempts":   3,
    "retry_delay":      1.0,
}

# Policy HCL templates — written to config/openbao-policies/ during init
POLICY_TEMPLATES: dict[str, str] = {
    "forge-autonomous": """\
# forge-autonomous: secrets accessible without human TTY (scheduled forge jobs)
path "forge/autonomous/*" {
  capabilities = ["read", "list"]
}
path "forge/totp/code/*" {
  capabilities = ["read"]
}
""",
    "forge-spawn": """\
# forge-spawn: secrets scoped to spawn-phase operations
path "forge/spawn/*" {
  capabilities = ["read", "list"]
}
""",
    "forge-migrate": """\
# forge-migrate: secrets scoped to migration operations
path "forge/migrate/*" {
  capabilities = ["read", "list"]
}
""",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s [openbao] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger("openbao_manager")


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_config(config_path: Path | None = None) -> dict[str, Any]:
    cfg = dict(FALLBACK_CONFIG)
    path = config_path or DEFAULT_CONFIG_PATH
    if path.exists():
        try:
            with path.open() as f:
                overrides = json.load(f)
            cfg.update(overrides)
            log.debug("Loaded config from %s", path)
        except Exception as exc:
            log.warning("Could not read %s: %s — using defaults", path, exc)
    # Environment overrides
    for env_key, cfg_key in [
        ("OPENBAO_ADDR",            "addr"),
        ("OPENBAO_NAMESPACE",       "namespace"),
        ("OPENBAO_UNSEAL_STRATEGY", "unseal_strategy"),
        ("OPENBAO_KEEPASS_MODE",    "keepass_mode"),
    ]:
        val = os.environ.get(env_key)
        if val:
            cfg[cfg_key] = val
    return cfg


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

class OpenBaoHTTPError(Exception):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


def _http(
    method: str,
    url: str,
    token: str | None,
    payload: dict | None = None,
    timeout: int = 10,
    namespace: str = "",
) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["X-Vault-Token"] = token
    if namespace:
        headers["X-Vault-Namespace"] = namespace
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise OpenBaoHTTPError(exc.code, body) from exc
    except urllib.error.URLError as exc:
        raise ConnectionError(f"Cannot reach OpenBao at {url}: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# OpenBaoManager
# ---------------------------------------------------------------------------

class OpenBaoManager:
    """Thin Python wrapper around the OpenBao (Vault-compatible) HTTP API."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.addr: str = cfg["addr"].rstrip("/")
        self.namespace: str = cfg.get("namespace", "")
        self.timeout: int = int(cfg.get("request_timeout", 10))
        self._token: str | None = None

    # ---- token resolution --------------------------------------------------

    @property
    def token(self) -> str:
        if self._token:
            return self._token
        # 1. OPENBAO_TOKEN / configured env var
        env_var = self.cfg.get("token_env", "OPENBAO_TOKEN")
        tok = os.environ.get(env_var) or os.environ.get("VAULT_TOKEN")
        if tok:
            self._token = tok
            return tok
        # 2. Token file (written by broodforge bootstrap)
        tok_file = Path(self.cfg.get("token_file", "/run/broodforge/openbao-token"))
        if tok_file.exists():
            self._token = tok_file.read_text().strip()
            return self._token
        raise RuntimeError(
            "No OpenBao token found.  Set OPENBAO_TOKEN or ensure "
            f"{self.cfg.get('token_file')} exists."
        )

    # ---- internal HTTP helper ----------------------------------------------

    def _api(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        unauthenticated: bool = False,
    ) -> dict:
        url = f"{self.addr}/v1/{path.lstrip('/')}"
        tok = None if unauthenticated else self.token
        attempts = int(self.cfg.get("retry_attempts", 3))
        delay = float(self.cfg.get("retry_delay", 1.0))
        for i in range(attempts):
            try:
                return _http(method, url, tok, payload, self.timeout, self.namespace)
            except ConnectionError:
                if i < attempts - 1:
                    log.warning("Connection failed (attempt %d/%d), retrying…", i + 1, attempts)
                    time.sleep(delay)
                    continue
                raise

    # ---- health / status ---------------------------------------------------

    def health(self) -> dict:
        """Return OpenBao health status (no auth required)."""
        return self._api("GET", "sys/health", unauthenticated=True)

    def is_sealed(self) -> bool:
        try:
            h = self.health()
            return bool(h.get("sealed", True))
        except Exception:
            return True

    def seal_status(self) -> dict:
        return self._api("GET", "sys/seal-status", unauthenticated=True)

    # ---- unseal ------------------------------------------------------------

    def unseal_shamir(self, key_shards: list[str]) -> dict:
        """Submit Shamir unseal key shards one by one until unsealed."""
        result: dict = {}
        for shard in key_shards:
            result = self._api("POST", "sys/unseal", {"key": shard}, unauthenticated=True)
            log.info(
                "Unseal shard submitted — sealed=%s threshold=%s/%s",
                result.get("sealed"),
                result.get("progress"),
                result.get("t"),
            )
            if not result.get("sealed"):
                log.info("OpenBao is now unsealed.")
                break
        return result

    def unseal_transit(self) -> dict:
        """
        Auto-unseal via Transit engine on a second OpenBao instance.
        This is handled automatically by OpenBao's seal configuration;
        this method just verifies the result.
        Strategy: unseal_strategy=transit in config triggers the correct
        seal stanza in /etc/openbao/config.hcl — see forge-init-openbao.sh.
        """
        status = self.seal_status()
        if status.get("sealed"):
            raise RuntimeError(
                "Transit auto-unseal failed — check the transit OpenBao instance "
                f"at {self.cfg.get('transit_addr', '(not configured)')}"
            )
        return status

    def unseal(self, keys_file: Path | None = None) -> dict:
        """
        Unseal OpenBao using the configured strategy.
        For 'shamir': reads shards from keys_file (JSON list of strings).
        For 'transit': verifies auto-unseal completed.
        """
        strategy = self.cfg.get("unseal_strategy", "shamir")
        if strategy == "transit":
            return self.unseal_transit()
        # shamir
        if keys_file is None:
            raise ValueError("keys_file required for shamir unseal strategy")
        shards: list[str] = json.loads(keys_file.read_text())
        return self.unseal_shamir(shards)

    # ---- KV secrets engine -------------------------------------------------

    def _kv_path(self, child_path: str) -> str:
        """
        Map child:// or bare path to the OpenBao KV mount path.
        child://forge-autonomous/proxmox/api_token
          → forge/autonomous/proxmox/api_token (KV v2 data path)
        """
        if child_path.startswith("child://"):
            rest = child_path[len("child://"):]
            mount = self.cfg.get("mount_kv", "forge")
            return f"{mount}/{rest}"
        return child_path

    def read_secret(self, path: str) -> str | None:
        """
        Read a secret from the KV v2 store.
        Returns the 'value' field (the canonical single-field convention used
        by broodforge), or None if not found.
        """
        kv_path = self._kv_path(path)
        mount, *rest = kv_path.split("/", 1)
        data_path = f"{mount}/data/{rest[0]}" if rest else kv_path
        try:
            resp = self._api("GET", data_path)
            return resp.get("data", {}).get("data", {}).get("value")
        except OpenBaoHTTPError as exc:
            if exc.status == 404:
                return None
            raise

    def write_secret(self, path: str, value: str, metadata: dict | None = None) -> dict:
        """
        Write a secret to the KV v2 store.
        Respects OPENBAO_KEEPASS_MODE: in 'readonly' mode, direct machine writes
        are still allowed (OpenBao is the source of truth); KeePass is not updated.
        In 'writable' mode, forge-sync-credentials.sh handles the KeePass mirror.
        """
        kv_path = self._kv_path(path)
        mount, *rest = kv_path.split("/", 1)
        data_path = f"{mount}/data/{rest[0]}" if rest else kv_path
        payload: dict[str, Any] = {"data": {"value": value}}
        if metadata:
            payload["data"].update(metadata)
        return self._api("POST", data_path, payload)

    def list_secrets(self, path: str) -> list[str]:
        """List keys at a KV path."""
        kv_path = self._kv_path(path)
        mount, *rest = kv_path.split("/", 1)
        meta_path = f"{mount}/metadata/{rest[0]}" if rest else kv_path
        try:
            resp = self._api("LIST", meta_path)
            return resp.get("data", {}).get("keys", [])
        except OpenBaoHTTPError as exc:
            if exc.status == 404:
                return []
            raise

    def delete_secret(self, path: str) -> None:
        """Soft-delete (latest version) a KV v2 secret."""
        kv_path = self._kv_path(path)
        mount, *rest = kv_path.split("/", 1)
        data_path = f"{mount}/data/{rest[0]}" if rest else kv_path
        self._api("DELETE", data_path)

    # ---- TOTP engine -------------------------------------------------------

    def totp_code(self, account: str) -> str:
        """
        Generate a TOTP code for a named account.
        Replaces kdbx_totp() in forge-lib.sh.
        """
        path = f"{self.cfg.get('mount_totp', 'forge/totp')}/code/{account}"
        resp = self._api("GET", path)
        code = resp.get("data", {}).get("code")
        if not code:
            raise RuntimeError(f"TOTP engine returned no code for account '{account}'")
        return code

    def totp_create(
        self,
        account: str,
        issuer: str,
        secret_b32: str,
        digits: int = 6,
        period: int = 30,
        algorithm: str = "SHA1",
    ) -> dict:
        """
        Register a TOTP account in the OpenBao TOTP engine.
        Used during forge-init-openbao.sh to migrate from KeePass.
        """
        path = f"{self.cfg.get('mount_totp', 'forge/totp')}/keys/{account}"
        return self._api("POST", path, {
            "generate":     False,
            "exported":     False,
            "key":          secret_b32,
            "issuer":       issuer,
            "account_name": account,
            "digits":       digits,
            "period":       period,
            "algorithm":    algorithm,
        })

    def totp_list(self) -> list[str]:
        path = f"{self.cfg.get('mount_totp', 'forge/totp')}/keys"
        try:
            resp = self._api("LIST", path)
            return resp.get("data", {}).get("keys", [])
        except OpenBaoHTTPError as exc:
            if exc.status == 404:
                return []
            raise

    # ---- policy management -------------------------------------------------

    def policy_apply(self, name: str, hcl: str) -> dict:
        """Write an HCL policy."""
        return self._api("POST", f"sys/policies/acl/{name}", {"policy": hcl})

    def policy_read(self, name: str) -> str | None:
        try:
            resp = self._api("GET", f"sys/policies/acl/{name}")
            return resp.get("policy")
        except OpenBaoHTTPError as exc:
            if exc.status == 404:
                return None
            raise

    def policy_list(self) -> list[str]:
        resp = self._api("LIST", "sys/policies/acl")
        return resp.get("data", {}).get("keys", [])

    def apply_forge_policies(self) -> None:
        """Write all broodforge role policies to OpenBao."""
        for name, hcl in POLICY_TEMPLATES.items():
            self.policy_apply(name, hcl)
            log.info("Policy applied: %s", name)

    # ---- token management --------------------------------------------------

    def token_create(
        self,
        policies: list[str],
        ttl: str = "1h",
        display_name: str = "",
        no_parent: bool = False,
        num_uses: int = 0,
    ) -> dict:
        payload: dict[str, Any] = {
            "policies":  policies,
            "ttl":       ttl,
            "renewable": True,
            "no_parent": no_parent,
        }
        if display_name:
            payload["display_name"] = display_name
        if num_uses:
            payload["num_uses"] = num_uses
        return self._api("POST", "auth/token/create", payload)

    def token_renew(self, token: str | None = None, increment: str = "1h") -> dict:
        payload: dict[str, Any] = {"increment": increment}
        if token:
            payload["token"] = token
        return self._api("POST", "auth/token/renew-self", payload)

    def token_lookup(self) -> dict:
        return self._api("GET", "auth/token/lookup-self")

    def token_revoke(self, token: str) -> None:
        self._api("POST", "auth/token/revoke", {"token": token})

    # ---- audit log ---------------------------------------------------------

    def audit_enable(
        self, path: str = "file/", log_path: str = "/var/log/openbao/audit.log"
    ) -> dict:
        return self._api("POST", f"sys/audit/{path.rstrip('/')}", {
            "type":    "file",
            "options": {"file_path": log_path},
        })

    def audit_list(self) -> dict:
        return self._api("GET", "sys/audit")

    def query_audit(
        self, limit: int = 100, log_path: str = "/var/log/openbao/audit.log"
    ) -> list[dict]:
        """
        Read the last `limit` audit log entries from the local JSON audit log.
        OpenBao's audit log is one JSON object per line.
        """
        p = Path(log_path)
        if not p.exists():
            log.warning("Audit log not found at %s", log_path)
            return []
        lines: list[dict] = []
        with p.open() as f:
            for raw in f:
                raw = raw.strip()
                if raw:
                    try:
                        lines.append(json.loads(raw))
                    except json.JSONDecodeError:
                        pass
        return lines[-limit:]

    # ---- mount management --------------------------------------------------

    def mount_kv(self, path: str = "forge", version: int = 2) -> dict:
        """Enable a KV v2 secrets engine at `path`."""
        return self._api("POST", f"sys/mounts/{path}", {
            "type":    "kv",
            "options": {"version": str(version)},
        })

    def mount_totp(self, path: str = "forge/totp") -> dict:
        """Enable the TOTP secrets engine."""
        return self._api("POST", f"sys/mounts/{path}", {"type": "totp"})

    def mount_list(self) -> dict:
        return self._api("GET", "sys/mounts")

    # ---- init / bootstrap helpers -----------------------------------------

    def init(self, secret_shares: int = 5, secret_threshold: int = 3) -> dict:
        """
        Initialize a new OpenBao instance.
        Returns unseal keys and root token — write to secure offline storage
        immediately.  Revoke root token after bootstrap.

        Shamir shard distribution:
          - 2 shards → KeePass master DB (forge-master/openbao entry)
          - 2 shards → offline USB keys
          - 1 shard  → governance VM TPM-sealed key file

        Transit: set secret_shares=1, secret_threshold=1 and configure
        seal{} stanza in /etc/openbao/config.hcl before calling init.
        """
        strategy = self.cfg.get("unseal_strategy", "shamir")
        if strategy == "transit":
            secret_shares = 1
            secret_threshold = 1
            log.info("Transit auto-unseal: initializing with 1-of-1 recovery key")
        else:
            log.info(
                "Shamir unseal: initializing with %d-of-%d threshold",
                secret_threshold, secret_shares,
            )
        result = self._api("POST", "sys/init", {
            "secret_shares":    secret_shares,
            "secret_threshold": secret_threshold,
        }, unauthenticated=True)
        log.warning(
            "BOOTSTRAP: Write unseal keys and root token to secure storage NOW. "
            "Root token: %s",
            result.get("root_token", "(not returned)"),
        )
        return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="OpenBao Secrets Broker — broodforge Phase 3.L",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--config", type=Path, default=None, help="Path to openbao-config.json")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show seal status and health")

    r = sub.add_parser("read", help="Read a secret by path")
    r.add_argument("path", help="Secret path (child:// or bare KV path)")

    w = sub.add_parser("write", help="Write a secret")
    w.add_argument("path", help="Secret path")
    w.add_argument("--value", required=True, help="Secret value")

    ls = sub.add_parser("list", help="List secrets at a path")
    ls.add_argument("path", help="KV path prefix")

    t = sub.add_parser("totp", help="Generate TOTP code for an account")
    t.add_argument("account", help="Account name (or forge/totp/code/<account>)")

    u = sub.add_parser("unseal", help="Unseal OpenBao")
    u.add_argument(
        "--keys-file", type=Path, default=None,
        help="JSON file containing Shamir key shards (list of strings)",
    )

    pol = sub.add_parser("policy", help="Policy management")
    pol.add_argument("action", choices=["apply-all", "list", "show"])
    pol.add_argument("--name", help="Policy name (for show)")

    tok = sub.add_parser("token", help="Token operations")
    tok.add_argument("action", choices=["lookup", "renew", "revoke"])
    tok.add_argument("--token", help="Token string (for revoke)")
    tok.add_argument("--ttl", default="1h")

    aud = sub.add_parser("audit", help="Query audit log")
    aud.add_argument("--limit", type=int, default=50)
    aud.add_argument("--log-path", default="/var/log/openbao/audit.log")

    ini = sub.add_parser("init", help="Initialize a fresh OpenBao instance")
    ini.add_argument("--shares", type=int, default=5)
    ini.add_argument("--threshold", type=int, default=3)

    sub.add_parser("mount-setup", help="Enable forge KV and TOTP mounts")

    return p


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    cfg = load_config(args.config)
    mgr = OpenBaoManager(cfg)

    try:
        if args.command == "status":
            status = mgr.seal_status()
            health = {}
            try:
                health = mgr.health()
            except Exception:
                pass
            print(json.dumps({"seal_status": status, "health": health}, indent=2))

        elif args.command == "read":
            val = mgr.read_secret(args.path)
            if val is None:
                log.error("Secret not found: %s", args.path)
                return 1
            print(val)

        elif args.command == "write":
            result = mgr.write_secret(args.path, args.value)
            print(json.dumps(result, indent=2))

        elif args.command == "list":
            for k in mgr.list_secrets(args.path):
                print(k)

        elif args.command == "totp":
            account = args.account
            if account.startswith("forge/totp/code/"):
                account = account[len("forge/totp/code/"):]
            print(mgr.totp_code(account))

        elif args.command == "unseal":
            print(json.dumps(mgr.unseal(keys_file=args.keys_file), indent=2))

        elif args.command == "policy":
            if args.action == "apply-all":
                mgr.apply_forge_policies()
                log.info("All forge policies applied.")
            elif args.action == "list":
                for name in mgr.policy_list():
                    print(name)
            elif args.action == "show":
                if not args.name:
                    log.error("--name required for policy show")
                    return 1
                print(mgr.policy_read(args.name) or "(policy not found)")

        elif args.command == "token":
            if args.action == "lookup":
                print(json.dumps(mgr.token_lookup(), indent=2))
            elif args.action == "renew":
                print(json.dumps(mgr.token_renew(increment=args.ttl), indent=2))
            elif args.action == "revoke":
                if not args.token:
                    log.error("--token required for revoke")
                    return 1
                mgr.token_revoke(args.token)
                log.info("Token revoked.")

        elif args.command == "audit":
            for entry in mgr.query_audit(args.limit, args.log_path):
                print(json.dumps(entry))

        elif args.command == "init":
            print(json.dumps(mgr.init(args.shares, args.threshold), indent=2))

        elif args.command == "mount-setup":
            for fn, label in [(mgr.mount_kv, "KV engine at forge/"), (mgr.mount_totp, "TOTP engine at forge/totp/")]:
                try:
                    fn()
                    log.info("%s mounted", label)
                except OpenBaoHTTPError as exc:
                    if exc.status == 400 and "existing mount" in exc.body:
                        log.info("%s already mounted", label)
                    else:
                        raise

    except (ConnectionError, OpenBaoHTTPError, RuntimeError) as exc:
        log.error("%s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
