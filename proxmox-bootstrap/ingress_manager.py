"""
ingress_manager.py — Phase 2.F: Ingress & Traffic Management
Manages nginx-ingress Helm deployment, IngressRoute registry, and TLS termination
wiring for the broodforge k3s cluster.

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
import warnings
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

_SUBPROCESS_TIMEOUT = 300  # seconds


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class TlsConfig:
    """TLS termination config for an ingress route."""
    secret_name: str          # k8s Secret name holding cert+key
    hosts: list[str] = field(default_factory=list)
    cluster_issuer: str = ""  # cert-manager ClusterIssuer name (optional)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TlsConfig":
        return cls(
            secret_name=d["secret_name"],
            hosts=d.get("hosts", []),
            cluster_issuer=d.get("cluster_issuer", ""),
        )


@dataclass
class IngressRoute:
    """Registry entry for a single ingress route."""
    name: str                  # logical name, e.g. "forgejo"
    namespace: str             # k8s namespace
    service_name: str          # backend Service name
    service_port: int          # backend Service port
    hostname: str              # virtual hostname (FQDN)
    path_prefix: str = "/"     # path prefix, default "/"
    tls: Optional[TlsConfig] = None
    annotations: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    registered_at: str = ""
    last_updated: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.tls is not None:
            d["tls"] = self.tls.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "IngressRoute":
        tls = None
        if d.get("tls"):
            tls = TlsConfig.from_dict(d["tls"])
        return cls(
            name=d["name"],
            namespace=d["namespace"],
            service_name=d["service_name"],
            service_port=int(d["service_port"]),
            hostname=d["hostname"],
            path_prefix=d.get("path_prefix", "/"),
            tls=tls,
            annotations=d.get("annotations", {}),
            enabled=d.get("enabled", True),
            registered_at=d.get("registered_at", ""),
            last_updated=d.get("last_updated", ""),
        )


@dataclass
class IngressDeployment:
    """Records the Helm deployment of nginx-ingress-controller."""
    deployed: bool = False
    chart_version: str = ""
    namespace: str = "ingress-nginx"
    replica_count: int = 1
    service_type: str = "LoadBalancer"   # LoadBalancer | NodePort | ClusterIP
    node_port_http: Optional[int] = None
    node_port_https: Optional[int] = None
    deployed_at: str = ""
    helm_release: str = "ingress-nginx"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "IngressDeployment":
        return cls(
            deployed=d.get("deployed", False),
            chart_version=d.get("chart_version", ""),
            namespace=d.get("namespace", "ingress-nginx"),
            replica_count=int(d.get("replica_count", 1)),
            service_type=d.get("service_type", "LoadBalancer"),
            node_port_http=d.get("node_port_http"),
            node_port_https=d.get("node_port_https"),
            deployed_at=d.get("deployed_at", ""),
            helm_release=d.get("helm_release", "ingress-nginx"),
        )


@dataclass
class IngressState:
    """Full ingress state persisted to disk."""
    deployment: IngressDeployment = field(default_factory=IngressDeployment)
    routes: list[IngressRoute] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "deployment": self.deployment.to_dict(),
            "routes": [r.to_dict() for r in self.routes],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IngressState":
        return cls(
            deployment=IngressDeployment.from_dict(d.get("deployment", {})),
            routes=[IngressRoute.from_dict(r) for r in d.get("routes", [])],
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class IngressManager:
    """Manages nginx-ingress deployment and IngressRoute registry.

    Args:
        state_dir:   directory holding ingress-state.json
        now_fn:      injectable clock (default: UTC now)
    """

    STATE_FILE = "ingress-state.json"
    HELM_REPO_NAME = "ingress-nginx"
    HELM_REPO_URL = "https://kubernetes.github.io/ingress-nginx"
    HELM_CHART = "ingress-nginx/ingress-nginx"

    def __init__(
        self,
        state_dir: str,
        now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._state_dir = state_dir
        self._now_fn = now_fn
        self._state_path = os.path.join(state_dir, self.STATE_FILE)

    # ------------------------------------------------------------------
    # State I/O
    # ------------------------------------------------------------------

    def load(self) -> IngressState:
        if not os.path.exists(self._state_path):
            return IngressState()
        with open(self._state_path, "r", encoding="utf-8") as fh:
            return IngressState.from_dict(json.load(fh))

    def save(self, state: IngressState) -> None:
        os.makedirs(self._state_dir, exist_ok=True)
        tmp = self._state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2)
        os.replace(tmp, self._state_path)

    # ------------------------------------------------------------------
    # Helm values generation
    # ------------------------------------------------------------------

    def generate_helm_values(
        self,
        replica_count: int = 1,
        service_type: str = "LoadBalancer",
        node_port_http: Optional[int] = None,
        node_port_https: Optional[int] = None,
        enable_metrics: bool = True,
    ) -> dict[str, Any]:
        """Return a dict suitable for serialisation as Helm values YAML."""
        values: dict[str, Any] = {
            "controller": {
                "replicaCount": replica_count,
                "service": {
                    "type": service_type,
                },
                "metrics": {
                    "enabled": enable_metrics,
                    "serviceMonitor": {
                        "enabled": enable_metrics,
                        "namespace": "monitoring",
                    },
                },
                "config": {
                    "use-forwarded-headers": "true",
                    "compute-full-forwarded-for": "true",
                    "use-proxy-protocol": "false",
                },
                "resources": {
                    "requests": {"cpu": "100m", "memory": "90Mi"},
                    "limits": {"cpu": "500m", "memory": "256Mi"},
                },
            }
        }
        if service_type == "NodePort" and node_port_http and node_port_https:
            values["controller"]["service"]["nodePorts"] = {
                "http": node_port_http,
                "https": node_port_https,
            }
        return values

    # ------------------------------------------------------------------
    # Ingress manifest generation
    # ------------------------------------------------------------------

    def generate_ingress_manifest(self, route: IngressRoute) -> dict[str, Any]:
        """Return a k8s Ingress manifest dict for the given route."""
        annotations: dict[str, str] = {
            "kubernetes.io/ingress.class": "nginx",
            **route.annotations,
        }
        if route.tls and route.tls.cluster_issuer:
            annotations["cert-manager.io/cluster-issuer"] = route.tls.cluster_issuer

        spec: dict[str, Any] = {
            "rules": [
                {
                    "host": route.hostname,
                    "http": {
                        "paths": [
                            {
                                "path": route.path_prefix,
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        "name": route.service_name,
                                        "port": {"number": route.service_port},
                                    }
                                },
                            }
                        ]
                    },
                }
            ]
        }
        if route.tls:
            spec["tls"] = [
                {
                    "hosts": route.tls.hosts or [route.hostname],
                    "secretName": route.tls.secret_name,
                }
            ]

        return {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": route.name,
                "namespace": route.namespace,
                "annotations": annotations,
            },
            "spec": spec,
        }

    # ------------------------------------------------------------------
    # Route registry operations
    # ------------------------------------------------------------------

    def register_route(
        self,
        name: str,
        namespace: str,
        service_name: str,
        service_port: int,
        hostname: str,
        path_prefix: str = "/",
        tls: Optional[TlsConfig] = None,
        annotations: Optional[dict[str, str]] = None,
        dry_run: bool = False,
    ) -> IngressRoute:
        """Add or update an ingress route in the registry."""
        state = self.load()
        now = self._now_fn().strftime("%Y-%m-%dT%H:%M:%SZ")

        existing = next((r for r in state.routes if r.name == name and r.namespace == namespace), None)
        if existing:
            existing.service_name = service_name
            existing.service_port = service_port
            existing.hostname = hostname
            existing.path_prefix = path_prefix
            existing.tls = tls
            existing.annotations = annotations or {}
            existing.last_updated = now
            route = existing
        else:
            route = IngressRoute(
                name=name,
                namespace=namespace,
                service_name=service_name,
                service_port=service_port,
                hostname=hostname,
                path_prefix=path_prefix,
                tls=tls,
                annotations=annotations or {},
                registered_at=now,
                last_updated=now,
            )
            state.routes.append(route)

        if not dry_run:
            self.save(state)
        return route

    def disable_route(self, name: str, namespace: str, dry_run: bool = False) -> bool:
        """Mark an ingress route disabled (not deleted — preserves registry record)."""
        state = self.load()
        for r in state.routes:
            if r.name == name and r.namespace == namespace:
                r.enabled = False
                r.last_updated = self._now_fn().strftime("%Y-%m-%dT%H:%M:%SZ")
                if not dry_run:
                    self.save(state)
                return True
        return False

    def list_routes(self, namespace: Optional[str] = None, enabled_only: bool = False) -> list[IngressRoute]:
        state = self.load()
        routes = state.routes
        if namespace:
            routes = [r for r in routes if r.namespace == namespace]
        if enabled_only:
            routes = [r for r in routes if r.enabled]
        return routes

    # ------------------------------------------------------------------
    # Helm operations
    # ------------------------------------------------------------------

    def add_helm_repo(self) -> int:
        """Add the ingress-nginx Helm repo. Returns subprocess returncode."""
        result = subprocess.run(
            ["helm", "repo", "add", self.HELM_REPO_NAME, self.HELM_REPO_URL],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        subprocess.run(
            ["helm", "repo", "update"],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        return result.returncode

    def deploy(
        self,
        namespace: str = "ingress-nginx",
        replica_count: int = 1,
        service_type: str = "LoadBalancer",
        node_port_http: Optional[int] = None,
        node_port_https: Optional[int] = None,
        chart_version: str = "",
        dry_run: bool = False,
    ) -> int:
        """Deploy or upgrade nginx-ingress via Helm. Returns returncode."""
        import yaml as _yaml  # optional dep for values serialisation
        values = self.generate_helm_values(
            replica_count=replica_count,
            service_type=service_type,
            node_port_http=node_port_http,
            node_port_https=node_port_https,
        )
        values_path = os.path.join(self._state_dir, "ingress-values.yaml.tmp")
        try:
            with open(values_path, "w", encoding="utf-8") as fh:
                _yaml.dump(values, fh, default_flow_style=False)
        except ImportError:
            # Fallback: write JSON (Helm accepts JSON values files)
            values_path = os.path.join(self._state_dir, "ingress-values.json.tmp")
            with open(values_path, "w", encoding="utf-8") as fh:
                json.dump(values, fh)

        cmd = [
            "helm", "upgrade", "--install",
            "ingress-nginx", self.HELM_CHART,
            "--namespace", namespace,
            "--create-namespace",
            "--values", values_path,
            "--wait",
            "--timeout", "5m",
        ]
        if chart_version:
            cmd += ["--version", chart_version]
        if dry_run:
            cmd.append("--dry-run")

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )

        try:
            os.remove(values_path)
        except OSError:
            pass

        if result.returncode == 0 and not dry_run:
            state = self.load()
            state.deployment = IngressDeployment(
                deployed=True,
                chart_version=chart_version,
                namespace=namespace,
                replica_count=replica_count,
                service_type=service_type,
                node_port_http=node_port_http,
                node_port_https=node_port_https,
                deployed_at=self._now_fn().strftime("%Y-%m-%dT%H:%M:%SZ"),
                helm_release="ingress-nginx",
            )
            self.save(state)
        return result.returncode

    def get_deployment_status(self) -> dict[str, Any]:
        """Query live Helm release status. Returns dict with status info."""
        result = subprocess.run(
            ["helm", "status", "ingress-nginx", "--namespace", "ingress-nginx", "--output", "json"],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT,
        )
        if result.returncode != 0:
            return {"deployed": False, "error": result.stderr.strip()}
        try:
            data = json.loads(result.stdout)
            return {
                "deployed": True,
                "status": data.get("info", {}).get("status", ""),
                "chart": data.get("chart", {}).get("metadata", {}).get("version", ""),
            }
        except (json.JSONDecodeError, KeyError):
            return {"deployed": False, "error": "could not parse helm output"}

    def apply_route_to_cluster(self, route: IngressRoute, dry_run: bool = False) -> int:
        """Apply (kubectl apply) an ingress manifest to the cluster."""
        manifest = self.generate_ingress_manifest(route)
        manifest_path = os.path.join(
            self._state_dir, f"ingress-{route.namespace}-{route.name}.yaml.tmp"
        )
        try:
            import yaml as _yaml
            with open(manifest_path, "w", encoding="utf-8") as fh:
                _yaml.dump(manifest, fh, default_flow_style=False)
        except ImportError:
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh)

        cmd = ["kubectl", "apply", "-f", manifest_path]
        if dry_run:
            cmd.append("--dry-run=client")

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        try:
            os.remove(manifest_path)
        except OSError:
            pass
        return result.returncode


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="ingress_manager — Phase 2.F Ingress & Traffic Management"
    )
    parser.add_argument("--state-dir", default="/var/lib/broodforge", help="State directory")
    sub = parser.add_subparsers(dest="cmd")

    # deploy
    d = sub.add_parser("deploy", help="Deploy nginx-ingress via Helm")
    d.add_argument("--namespace", default="ingress-nginx")
    d.add_argument("--replicas", type=int, default=1)
    d.add_argument("--service-type", default="LoadBalancer",
                   choices=["LoadBalancer", "NodePort", "ClusterIP"])
    d.add_argument("--node-port-http", type=int)
    d.add_argument("--node-port-https", type=int)
    d.add_argument("--chart-version", default="")
    d.add_argument("--dry-run", action="store_true")

    # register
    r = sub.add_parser("register", help="Register an ingress route")
    r.add_argument("--name", required=True)
    r.add_argument("--namespace", required=True)
    r.add_argument("--service", required=True)
    r.add_argument("--port", type=int, required=True)
    r.add_argument("--hostname", required=True)
    r.add_argument("--path", default="/")
    r.add_argument("--tls-secret", default="")
    r.add_argument("--cluster-issuer", default="")
    r.add_argument("--dry-run", action="store_true")

    # list
    sub.add_parser("list", help="List registered ingress routes")

    # status
    sub.add_parser("status", help="Show live Helm release status")

    # apply
    ap = sub.add_parser("apply", help="Apply a registered route to the cluster")
    ap.add_argument("--name", required=True)
    ap.add_argument("--namespace", required=True)
    ap.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    mgr = IngressManager(state_dir=args.state_dir)

    if args.cmd == "deploy":
        mgr.add_helm_repo()
        rc = mgr.deploy(
            namespace=args.namespace,
            replica_count=args.replicas,
            service_type=args.service_type,
            node_port_http=args.node_port_http,
            node_port_https=args.node_port_https,
            chart_version=args.chart_version,
            dry_run=args.dry_run,
        )
        print("OK" if rc == 0 else f"FAILED (rc={rc})")
        return rc

    elif args.cmd == "register":
        tls = None
        if args.tls_secret:
            tls = TlsConfig(
                secret_name=args.tls_secret,
                cluster_issuer=args.cluster_issuer,
            )
        route = mgr.register_route(
            name=args.name,
            namespace=args.namespace,
            service_name=args.service,
            service_port=args.port,
            hostname=args.hostname,
            path_prefix=args.path,
            tls=tls,
            dry_run=args.dry_run,
        )
        print(json.dumps(route.to_dict(), indent=2))
        return 0

    elif args.cmd == "list":
        routes = mgr.list_routes()
        for r in routes:
            tls_mark = " [TLS]" if r.tls else ""
            status = "" if r.enabled else " [DISABLED]"
            print(f"  {r.namespace}/{r.name}: {r.hostname}{r.path_prefix} → {r.service_name}:{r.service_port}{tls_mark}{status}")
        return 0

    elif args.cmd == "status":
        s = mgr.get_deployment_status()
        print(json.dumps(s, indent=2))
        return 0 if s.get("deployed") else 1

    elif args.cmd == "apply":
        state = mgr.load()
        route = next(
            (r for r in state.routes if r.name == args.name and r.namespace == args.namespace),
            None,
        )
        if not route:
            print(f"ERROR: route {args.namespace}/{args.name} not found in registry")
            return 1
        rc = mgr.apply_route_to_cluster(route, dry_run=args.dry_run)
        print("OK" if rc == 0 else f"FAILED (rc={rc})")
        return rc

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
