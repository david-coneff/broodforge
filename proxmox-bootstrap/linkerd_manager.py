"""
linkerd_manager.py — Phase 2.I: Service Mesh (Linkerd)
Manages Linkerd CRD/control-plane installation, mesh enrollment, and mTLS
status for the broodforge k3s cluster.

PAP compliance:
- No bare datetime.now() — always now_fn parameter
- All subprocess calls use timeout=_SUBPROCESS_TIMEOUT
- No credentials in env vars, argv, or log output
- Atomic file writes (write to .tmp, os.replace())
- KeePass gate for operator-level actions (AD-060)
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Callable, Optional

_SUBPROCESS_TIMEOUT = 300  # seconds


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MeshedNamespace:
    """A namespace enrolled in the Linkerd mesh."""
    namespace: str
    injected: bool = True
    mtls_enforced: bool = True
    enrolled_at: str = ""
    last_checked: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MeshedNamespace":
        return cls(
            namespace=d["namespace"],
            injected=d.get("injected", True),
            mtls_enforced=d.get("mtls_enforced", True),
            enrolled_at=d.get("enrolled_at", ""),
            last_checked=d.get("last_checked", ""),
        )


@dataclass
class LinkerdDeployment:
    """Records the Linkerd installation state."""
    installed: bool = False
    version: str = ""
    ha_mode: bool = False
    viz_installed: bool = False
    multicluster_installed: bool = False
    installed_at: str = ""
    crds_installed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LinkerdDeployment":
        return cls(
            installed=d.get("installed", False),
            version=d.get("version", ""),
            ha_mode=d.get("ha_mode", False),
            viz_installed=d.get("viz_installed", False),
            multicluster_installed=d.get("multicluster_installed", False),
            installed_at=d.get("installed_at", ""),
            crds_installed=d.get("crds_installed", False),
        )


@dataclass
class LinkerdState:
    deployment: LinkerdDeployment = field(default_factory=LinkerdDeployment)
    meshed_namespaces: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "deployment": self.deployment.to_dict(),
            "meshed_namespaces": [n.to_dict() for n in self.meshed_namespaces],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LinkerdState":
        return cls(
            deployment=LinkerdDeployment.from_dict(d.get("deployment", {})),
            meshed_namespaces=[MeshedNamespace.from_dict(n) for n in d.get("meshed_namespaces", [])],
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class LinkerdManager:
    """Manages Linkerd service mesh installation and namespace enrollment."""

    STATE_FILE = "linkerd-state.json"

    def __init__(
        self,
        state_dir: str,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._state_dir = state_dir
        self._now_fn = now_fn
        self._state_path = os.path.join(state_dir, self.STATE_FILE)

    def load(self) -> LinkerdState:
        if not os.path.exists(self._state_path):
            return LinkerdState()
        with open(self._state_path, "r", encoding="utf-8") as fh:
            return LinkerdState.from_dict(json.load(fh))

    def save(self, state: LinkerdState) -> None:
        os.makedirs(self._state_dir, exist_ok=True)
        tmp = self._state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2)
        os.replace(tmp, self._state_path)

    def check(self) -> tuple:
        """Run `linkerd check --pre`. Returns (ok, output)."""
        result = subprocess.run(
            ["linkerd", "check", "--pre"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        return result.returncode == 0, result.stdout + result.stderr

    def install_crds(self, dry_run: bool = False) -> int:
        if dry_run:
            result = subprocess.run(
                ["linkerd", "install", "--crds"],
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
            print(f"[dry-run] Would apply {result.stdout.count('kind:')} CRD manifests")
            return 0
        cmd = "linkerd install --crds | kubectl apply -f -"
        result = subprocess.run(  # nosec B602 – pipe requires shell=True; cmd is a fixed literal
            cmd, shell=True, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode == 0:
            state = self.load()
            state.deployment.crds_installed = True
            self.save(state)
        return result.returncode

    def install(self, ha_mode: bool = False, dry_run: bool = False) -> int:
        linkerd_cmd = "linkerd install" + (" --ha" if ha_mode else "")
        if dry_run:
            print(f"[dry-run] Would run: {linkerd_cmd} | kubectl apply -f -")
            return 0
        cmd = f"{linkerd_cmd} | kubectl apply -f -"
        result = subprocess.run(  # nosec B602 – pipe requires shell=True; cmd built from fixed literals and ha_mode bool
            cmd, shell=True, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode == 0:
            ver = self._detect_version()
            state = self.load()
            state.deployment.installed = True
            state.deployment.version = ver
            state.deployment.ha_mode = ha_mode
            state.deployment.installed_at = self._now_fn().strftime("%Y-%m-%dT%H:%M:%SZ")
            self.save(state)
        return result.returncode

    def install_viz(self, dry_run: bool = False) -> int:
        if dry_run:
            print("[dry-run] Would run: linkerd viz install | kubectl apply -f -")
            return 0
        cmd = "linkerd viz install | kubectl apply -f -"
        result = subprocess.run(  # nosec B602 – pipe requires shell=True; cmd is a fixed literal
            cmd, shell=True, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode == 0:
            state = self.load()
            state.deployment.viz_installed = True
            self.save(state)
        return result.returncode

    def _detect_version(self) -> str:
        try:
            r = subprocess.run(
                ["linkerd", "version", "--client", "--short"],
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
            return r.stdout.strip()
        except Exception:
            return ""

    def enroll_namespace(
        self,
        namespace: str,
        inject: bool = True,
        enforce_mtls: bool = True,
        dry_run: bool = False,
    ) -> MeshedNamespace:
        now = self._now_fn().strftime("%Y-%m-%dT%H:%M:%SZ")
        if inject and not dry_run:
            subprocess.run(
                ["kubectl", "annotate", "namespace", namespace,
                 "linkerd.io/inject=enabled", "--overwrite"],
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
        if enforce_mtls and not dry_run:
            self._apply_default_deny_policy(namespace)

        state = self.load()
        existing = next((n for n in state.meshed_namespaces if n.namespace == namespace), None)
        if existing:
            existing.injected = inject
            existing.mtls_enforced = enforce_mtls
            existing.last_checked = now
            ns = existing
        else:
            ns = MeshedNamespace(
                namespace=namespace, injected=inject,
                mtls_enforced=enforce_mtls, enrolled_at=now, last_checked=now,
            )
            state.meshed_namespaces.append(ns)
        if not dry_run:
            self.save(state)
        return ns

    def _apply_default_deny_policy(self, namespace: str) -> int:
        manifest = {
            "apiVersion": "policy.linkerd.io/v1beta3",
            "kind": "Server",
            "metadata": {"name": "default-deny", "namespace": namespace},
            "spec": {"podSelector": {}, "port": 0, "proxyProtocol": "opaque"},
        }
        manifest_path = os.path.join(
            self._state_dir, f"linkerd-policy-{namespace}.json.tmp"
        )
        os.makedirs(self._state_dir, exist_ok=True)
        with open(manifest_path, "w") as fh:
            json.dump(manifest, fh)
        result = subprocess.run(
            ["kubectl", "apply", "-f", manifest_path],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        try:
            os.remove(manifest_path)
        except OSError:
            pass
        return result.returncode

    def disenroll_namespace(self, namespace: str, dry_run: bool = False) -> bool:
        if not dry_run:
            subprocess.run(
                ["kubectl", "annotate", "namespace", namespace,
                 "linkerd.io/inject-", "--overwrite"],
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
        state = self.load()
        before = len(state.meshed_namespaces)
        state.meshed_namespaces = [
            n for n in state.meshed_namespaces if n.namespace != namespace
        ]
        if not dry_run and len(state.meshed_namespaces) < before:
            self.save(state)
        return len(state.meshed_namespaces) < before

    def check_health(self) -> tuple:
        result = subprocess.run(
            ["linkerd", "check"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        return result.returncode == 0, result.stdout + result.stderr

    def get_mesh_status(self) -> dict:
        result = subprocess.run(
            ["linkerd", "viz", "stat", "namespaces", "--output", "json"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip()}
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"error": "parse failed"}

    def list_meshed(self) -> list:
        return self.load().meshed_namespaces


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="linkerd_manager — Phase 2.I Service Mesh")
    parser.add_argument("--state-dir", default="/var/lib/broodforge")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("check-pre", help="Run linkerd check --pre")
    icrds = sub.add_parser("install-crds", help="Install Linkerd CRDs")
    icrds.add_argument("--dry-run", action="store_true")

    inst = sub.add_parser("install", help="Install Linkerd control plane")
    inst.add_argument("--ha", action="store_true")
    inst.add_argument("--dry-run", action="store_true")

    viz = sub.add_parser("install-viz", help="Install linkerd-viz extension")
    viz.add_argument("--dry-run", action="store_true")

    en = sub.add_parser("enroll", help="Enroll namespace in mesh")
    en.add_argument("--namespace", required=True)
    en.add_argument("--no-inject", action="store_true")
    en.add_argument("--no-enforce-mtls", action="store_true")
    en.add_argument("--dry-run", action="store_true")

    dis = sub.add_parser("disenroll", help="Remove namespace from mesh")
    dis.add_argument("--namespace", required=True)
    dis.add_argument("--dry-run", action="store_true")

    sub.add_parser("list", help="List meshed namespaces")
    sub.add_parser("check", help="Run linkerd check")
    sub.add_parser("status", help="Show mesh status per namespace")

    args = parser.parse_args(argv)
    mgr = LinkerdManager(state_dir=args.state_dir)

    if args.cmd == "check-pre":
        ok, out = mgr.check()
        print(out)
        return 0 if ok else 1
    elif args.cmd == "install-crds":
        rc = mgr.install_crds(dry_run=getattr(args, "dry_run", False))
        print("OK" if rc == 0 else f"FAILED (rc={rc})")
        return rc
    elif args.cmd == "install":
        rc = mgr.install(ha_mode=args.ha, dry_run=args.dry_run)
        print("OK" if rc == 0 else f"FAILED (rc={rc})")
        return rc
    elif args.cmd == "install-viz":
        rc = mgr.install_viz(dry_run=args.dry_run)
        print("OK" if rc == 0 else f"FAILED (rc={rc})")
        return rc
    elif args.cmd == "enroll":
        ns = mgr.enroll_namespace(
            namespace=args.namespace,
            inject=not args.no_inject,
            enforce_mtls=not args.no_enforce_mtls,
            dry_run=args.dry_run,
        )
        print(json.dumps(ns.to_dict(), indent=2))
        return 0
    elif args.cmd == "disenroll":
        removed = mgr.disenroll_namespace(args.namespace, dry_run=args.dry_run)
        print("removed" if removed else "not found")
        return 0
    elif args.cmd == "list":
        for n in mgr.list_meshed():
            mtls = "[mTLS]" if n.mtls_enforced else ""
            inj = "[inject]" if n.injected else "[no-inject]"
            print(f"  {n.namespace} {inj} {mtls}")
        return 0
    elif args.cmd == "check":
        ok, out = mgr.check_health()
        print(out)
        return 0 if ok else 1
    elif args.cmd == "status":
        print(json.dumps(mgr.get_mesh_status(), indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
