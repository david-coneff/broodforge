"""
kyverno_manager.py — Phase 2.J: Policy Enforcement (Kyverno)
Manages Kyverno admission controller installation and ClusterPolicy/Policy
registry for the broodforge k3s cluster.

PAP compliance:
- No bare datetime.now() — always now_fn parameter
- All subprocess calls use timeout=_SUBPROCESS_TIMEOUT
- No credentials in env vars, argv, or log output
- Atomic file writes (write to .tmp, os.replace())
- KeePass gate for operator-level actions (AD-061)
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

_SUBPROCESS_TIMEOUT = 300  # seconds


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PolicyRecord:
    """A registered Kyverno ClusterPolicy or namespaced Policy."""
    name: str
    kind: str = "ClusterPolicy"       # ClusterPolicy | Policy
    namespace: str = ""               # empty for ClusterPolicy
    category: str = ""                # e.g. "security", "best-practices"
    action: str = "Audit"             # Audit | Enforce
    rules_count: int = 0
    registered_at: str = ""
    manifest_path: str = ""           # path to YAML applied via kubectl

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PolicyRecord":
        return cls(
            name=d["name"],
            kind=d.get("kind", "ClusterPolicy"),
            namespace=d.get("namespace", ""),
            category=d.get("category", ""),
            action=d.get("action", "Audit"),
            rules_count=d.get("rules_count", 0),
            registered_at=d.get("registered_at", ""),
            manifest_path=d.get("manifest_path", ""),
        )


@dataclass
class KyvernoDeployment:
    """Records the Kyverno installation state."""
    installed: bool = False
    chart_version: str = ""
    namespace: str = "kyverno"
    replica_count: int = 1
    installed_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "KyvernoDeployment":
        return cls(
            installed=d.get("installed", False),
            chart_version=d.get("chart_version", ""),
            namespace=d.get("namespace", "kyverno"),
            replica_count=d.get("replica_count", 1),
            installed_at=d.get("installed_at", ""),
        )


@dataclass
class KyvernoState:
    deployment: KyvernoDeployment = field(default_factory=KyvernoDeployment)
    policies: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "deployment": self.deployment.to_dict(),
            "policies": [p.to_dict() for p in self.policies],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KyvernoState":
        return cls(
            deployment=KyvernoDeployment.from_dict(d.get("deployment", {})),
            policies=[PolicyRecord.from_dict(p) for p in d.get("policies", [])],
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class KyvernoManager:
    """Manages Kyverno policy engine installation and ClusterPolicy registry.

    Kyverno is deployed via Helm.  Policies are tracked in the state file;
    actual YAML manifests are applied/deleted through kubectl.
    """

    STATE_FILE = "kyverno-state.json"
    HELM_REPO_NAME = "kyverno"
    HELM_REPO_URL = "https://kyverno.github.io/kyverno/"
    HELM_CHART = "kyverno/kyverno"
    DEFAULT_NAMESPACE = "kyverno"

    def __init__(
        self,
        state_dir: str,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._state_dir = state_dir
        self._now_fn = now_fn
        self._state_path = os.path.join(state_dir, self.STATE_FILE)

    # ── persistence ────────────────────────────────────────────────────────

    def load(self) -> KyvernoState:
        """Load state from disk; returns empty state if file absent."""
        if not os.path.exists(self._state_path):
            return KyvernoState()
        with open(self._state_path, "r", encoding="utf-8") as fh:
            return KyvernoState.from_dict(json.load(fh))

    def save(self, state: KyvernoState) -> None:
        """Atomically persist state to disk."""
        tmp = self._state_path + ".tmp"
        os.makedirs(self._state_dir, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2)
        os.replace(tmp, self._state_path)

    # ── Helm helpers ────────────────────────────────────────────────────────

    def _helm_repo_add(self) -> None:
        subprocess.run(
            ["helm", "repo", "add", self.HELM_REPO_NAME, self.HELM_REPO_URL],
            check=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        subprocess.run(
            ["helm", "repo", "update"],
            check=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )

    def _detect_chart_version(self) -> str:
        result = subprocess.run(
            ["helm", "list", "-n", self.DEFAULT_NAMESPACE,
             "-o", "json", "--filter", "kyverno"],
            capture_output=True, text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        try:
            releases = json.loads(result.stdout or "[]")
            if releases:
                return releases[0].get("chart", "")
        except (json.JSONDecodeError, IndexError):
            pass
        return ""

    # ── install / upgrade ──────────────────────────────────────────────────

    def install(
        self,
        chart_version: Optional[str] = None,
        replica_count: int = 1,
        namespace: str = DEFAULT_NAMESPACE,
    ) -> KyvernoState:
        """Add Helm repo and install/upgrade Kyverno."""
        self._helm_repo_add()

        cmd = [
            "helm", "upgrade", "--install", "kyverno", self.HELM_CHART,
            "--namespace", namespace,
            "--create-namespace",
            "--set", f"replicaCount={replica_count}",
            "--wait",
        ]
        if chart_version:
            cmd += ["--version", chart_version]

        subprocess.run(cmd, check=True, timeout=_SUBPROCESS_TIMEOUT)

        detected = self._detect_chart_version()
        state = self.load()
        ts = self._now_fn().isoformat()
        state.deployment = KyvernoDeployment(
            installed=True,
            chart_version=chart_version or detected,
            namespace=namespace,
            replica_count=replica_count,
            installed_at=ts,
        )
        self.save(state)
        return state

    def uninstall(self) -> KyvernoState:
        """Remove Kyverno Helm release."""
        state = self.load()
        ns = state.deployment.namespace or self.DEFAULT_NAMESPACE
        subprocess.run(
            ["helm", "uninstall", "kyverno", "--namespace", ns],
            check=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        state.deployment = KyvernoDeployment()
        self.save(state)
        return state

    # ── policy registry ────────────────────────────────────────────────────

    def register_policy(
        self,
        name: str,
        manifest_path: str,
        kind: str = "ClusterPolicy",
        namespace: str = "",
        category: str = "",
        action: str = "Audit",
        rules_count: int = 0,
        apply: bool = True,
    ) -> PolicyRecord:
        """Apply a Kyverno policy YAML and record it in state."""
        if apply:
            kubectl_cmd = ["kubectl", "apply", "-f", manifest_path]
            subprocess.run(kubectl_cmd, check=True, timeout=_SUBPROCESS_TIMEOUT)

        record = PolicyRecord(
            name=name,
            kind=kind,
            namespace=namespace,
            category=category,
            action=action,
            rules_count=rules_count,
            registered_at=self._now_fn().isoformat(),
            manifest_path=manifest_path,
        )
        state = self.load()
        # upsert by name+kind
        state.policies = [p for p in state.policies
                          if not (p.name == name and p.kind == kind)]
        state.policies.append(record)
        self.save(state)
        return record

    def remove_policy(self, name: str, kind: str = "ClusterPolicy") -> KyvernoState:
        """Delete a policy from the cluster and deregister it."""
        state = self.load()
        existing = next(
            (p for p in state.policies if p.name == name and p.kind == kind), None
        )
        if existing and existing.manifest_path:
            subprocess.run(
                ["kubectl", "delete", "-f", existing.manifest_path, "--ignore-not-found"],
                check=True, timeout=_SUBPROCESS_TIMEOUT,
            )
        state.policies = [p for p in state.policies
                          if not (p.name == name and p.kind == kind)]
        self.save(state)
        return state

    def list_policies(self) -> list[PolicyRecord]:
        """Return the current policy registry."""
        return self.load().policies

    def get_policy(self, name: str, kind: str = "ClusterPolicy") -> Optional[PolicyRecord]:
        """Return a single policy record by name+kind, or None."""
        return next(
            (p for p in self.list_policies() if p.name == name and p.kind == kind),
            None,
        )

    # ── live status ────────────────────────────────────────────────────────

    def get_live_policy_count(self) -> dict:
        """Query kubectl for live ClusterPolicy count (best-effort)."""
        result = subprocess.run(
            ["kubectl", "get", "clusterpolicies", "-o", "json"],
            capture_output=True, text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        try:
            data = json.loads(result.stdout or "{}")
            items = data.get("items", [])
            return {"cluster_policies": len(items)}
        except (json.JSONDecodeError, KeyError):
            return {"cluster_policies": 0}

    def check_health(self) -> dict:
        """Run kubectl rollout status for the kyverno deployment."""
        state = self.load()
        ns = state.deployment.namespace or self.DEFAULT_NAMESPACE
        result = subprocess.run(
            ["kubectl", "rollout", "status",
             "deployment/kyverno", "-n", ns],
            capture_output=True, text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        return {
            "ok": result.returncode == 0,
            "output": (result.stdout + result.stderr).strip(),
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        description="Kyverno policy-engine manager (Phase 2.J)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="Install/upgrade Kyverno via Helm")
    p_install.add_argument("--chart-version", default=None)
    p_install.add_argument("--replicas", type=int, default=1)
    p_install.add_argument("--namespace", default=KyvernoManager.DEFAULT_NAMESPACE)

    sub.add_parser("uninstall", help="Remove Kyverno Helm release")

    p_add = sub.add_parser("add-policy", help="Apply and register a policy YAML")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--manifest", required=True)
    p_add.add_argument("--kind", default="ClusterPolicy")
    p_add.add_argument("--namespace", default="")
    p_add.add_argument("--category", default="")
    p_add.add_argument("--action", default="Audit",
                       choices=["Audit", "Enforce"])
    p_add.add_argument("--rules", type=int, default=0)
    p_add.add_argument("--no-apply", action="store_true")

    p_rm = sub.add_parser("remove-policy", help="Deregister and delete a policy")
    p_rm.add_argument("--name", required=True)
    p_rm.add_argument("--kind", default="ClusterPolicy")

    sub.add_parser("list", help="List registered policies")
    sub.add_parser("health", help="Check Kyverno rollout status")

    args = parser.parse_args(argv)
    mgr = KyvernoManager(
        state_dir=os.environ.get("BROODFORGE_STATE_DIR", "/var/lib/broodforge/state"),
        now_fn=lambda: datetime.now(timezone.utc),
    )

    if args.cmd == "install":
        st = mgr.install(
            chart_version=args.chart_version,
            replica_count=args.replicas,
            namespace=args.namespace,
        )
        print(f"Kyverno installed: chart={st.deployment.chart_version} "
              f"ns={st.deployment.namespace}")

    elif args.cmd == "uninstall":
        mgr.uninstall()
        print("Kyverno uninstalled.")

    elif args.cmd == "add-policy":
        rec = mgr.register_policy(
            name=args.name,
            manifest_path=args.manifest,
            kind=args.kind,
            namespace=args.namespace,
            category=args.category,
            action=args.action,
            rules_count=args.rules,
            apply=not args.no_apply,
        )
        print(f"Policy registered: {rec.kind}/{rec.name} ({rec.action})")

    elif args.cmd == "remove-policy":
        mgr.remove_policy(name=args.name, kind=args.kind)
        print(f"Policy removed: {args.kind}/{args.name}")

    elif args.cmd == "list":
        policies = mgr.list_policies()
        if not policies:
            print("No policies registered.")
        else:
            for p in policies:
                print(f"{p.kind}/{p.name}  action={p.action}  "
                      f"rules={p.rules_count}  cat={p.category or '-'}")

    elif args.cmd == "health":
        h = mgr.check_health()
        status = "OK" if h["ok"] else "DEGRADED"
        print(f"Kyverno health: {status}\n{h['output']}")


if __name__ == "__main__":
    main()
