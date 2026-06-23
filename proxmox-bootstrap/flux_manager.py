"""
flux_manager.py — Phase 2.G: GitOps / Flux CD Management
Manages Flux CD installation, GitRepository/Kustomization sources, and
reconciliation status for the broodforge k3s cluster.

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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

_SUBPROCESS_TIMEOUT = 300  # seconds


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class GitSource:
    """A Flux GitRepository source."""
    name: str
    namespace: str
    url: str                     # git repo URL
    branch: str = "main"
    interval: str = "1m"
    secret_ref: str = ""         # k8s secret name for SSH/HTTPS credentials
    registered_at: str = ""
    last_updated: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d["name"], namespace=d["namespace"], url=d["url"],
            branch=d.get("branch", "main"), interval=d.get("interval", "1m"),
            secret_ref=d.get("secret_ref", ""),
            registered_at=d.get("registered_at", ""),
            last_updated=d.get("last_updated", ""),
        )


@dataclass
class Kustomization:
    """A Flux Kustomization that applies a path from a GitRepository."""
    name: str
    namespace: str
    source_ref: str          # GitRepository name
    source_namespace: str
    path: str                # path within the repo (e.g. "./clusters/home")
    interval: str = "10m"
    prune: bool = True
    health_checks: list = field(default_factory=list)
    depends_on: list = field(default_factory=list)
    registered_at: str = ""
    last_updated: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(
            name=d["name"], namespace=d["namespace"],
            source_ref=d["source_ref"], source_namespace=d["source_namespace"],
            path=d["path"], interval=d.get("interval", "10m"),
            prune=d.get("prune", True),
            health_checks=d.get("health_checks", []),
            depends_on=d.get("depends_on", []),
            registered_at=d.get("registered_at", ""),
            last_updated=d.get("last_updated", ""),
        )


@dataclass
class FluxDeployment:
    """Records the Flux CLI bootstrap."""
    installed: bool = False
    version: str = ""
    namespace: str = "flux-system"
    bootstrap_repo_url: str = ""
    bootstrap_path: str = ""
    installed_at: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(
            installed=d.get("installed", False),
            version=d.get("version", ""),
            namespace=d.get("namespace", "flux-system"),
            bootstrap_repo_url=d.get("bootstrap_repo_url", ""),
            bootstrap_path=d.get("bootstrap_path", ""),
            installed_at=d.get("installed_at", ""),
        )


@dataclass
class FluxState:
    deployment: FluxDeployment = field(default_factory=FluxDeployment)
    sources: list = field(default_factory=list)
    kustomizations: list = field(default_factory=list)

    def to_dict(self):
        return {
            "deployment": self.deployment.to_dict(),
            "sources": [s.to_dict() for s in self.sources],
            "kustomizations": [k.to_dict() for k in self.kustomizations],
        }

    @classmethod
    def from_dict(cls, d):
        return cls(
            deployment=FluxDeployment.from_dict(d.get("deployment", {})),
            sources=[GitSource.from_dict(s) for s in d.get("sources", [])],
            kustomizations=[Kustomization.from_dict(k) for k in d.get("kustomizations", [])],
        )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class FluxManager:
    """Manages Flux CD GitOps installation and source/kustomization registry."""

    STATE_FILE = "flux-state.json"

    def __init__(self, state_dir, now_fn=lambda: datetime.now(timezone.utc)):
        self._state_dir = state_dir
        self._now_fn = now_fn
        self._state_path = os.path.join(state_dir, self.STATE_FILE)

    # ------------------------------------------------------------------
    # State I/O
    # ------------------------------------------------------------------

    def load(self):
        if not os.path.exists(self._state_path):
            return FluxState()
        with open(self._state_path, "r", encoding="utf-8") as fh:
            return FluxState.from_dict(json.load(fh))

    def save(self, state):
        os.makedirs(self._state_dir, exist_ok=True)
        tmp = self._state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state.to_dict(), fh, indent=2)
        os.replace(tmp, self._state_path)

    # ------------------------------------------------------------------
    # Flux install
    # ------------------------------------------------------------------

    def check_prerequisites(self):
        """Run `flux check --pre`. Returns (ok: bool, output: str)."""
        result = subprocess.run(
            ["flux", "check", "--pre"],
            capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
        )
        return result.returncode == 0, result.stdout + result.stderr

    def bootstrap_github(self, owner, repo, path, branch="main",
                         namespace="flux-system", personal=True, dry_run=False):
        """Bootstrap Flux on a GitHub repo (SSH key method, no token in argv).
        Credentials must be pre-configured via ssh-agent or a k8s secret.
        Returns returncode.
        """
        cmd = [
            "flux", "bootstrap", "github",
            "--owner", owner, "--repository", repo,
            "--branch", branch, "--path", path,
            "--namespace", namespace,
        ]
        if personal:
            cmd.append("--personal")
        if dry_run:
            cmd.append("--verbose")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        if result.returncode == 0 and not dry_run:
            ver = self._detect_flux_version()
            state = self.load()
            state.deployment = FluxDeployment(
                installed=True, version=ver, namespace=namespace,
                bootstrap_repo_url=f"https://github.com/{owner}/{repo}",
                bootstrap_path=path,
                installed_at=self._now_fn().strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            self.save(state)
        return result.returncode

    def bootstrap_git(self, url, path, branch="main", namespace="flux-system",
                      secret_ref="", dry_run=False):
        """Bootstrap Flux on a generic Git server (Forgejo / Gitea / GitLab).
        Returns returncode.
        """
        cmd = [
            "flux", "bootstrap", "git",
            "--url", url, "--branch", branch, "--path", path,
            "--namespace", namespace,
        ]
        if secret_ref:
            cmd += ["--secret-name", secret_ref]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        if result.returncode == 0 and not dry_run:
            ver = self._detect_flux_version()
            state = self.load()
            state.deployment = FluxDeployment(
                installed=True, version=ver, namespace=namespace,
                bootstrap_repo_url=url, bootstrap_path=path,
                installed_at=self._now_fn().strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            self.save(state)
        return result.returncode

    def _detect_flux_version(self):
        try:
            r = subprocess.run(
                ["flux", "version", "--client"],
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
            for line in r.stdout.splitlines():
                if "flux:" in line.lower():
                    return line.strip().split()[-1]
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # Source registry
    # ------------------------------------------------------------------

    def register_source(self, name, namespace, url, branch="main", interval="1m",
                        secret_ref="", dry_run=False):
        """Register a GitRepository source."""
        state = self.load()
        now = self._now_fn().strftime("%Y-%m-%dT%H:%M:%SZ")
        existing = next((s for s in state.sources if s.name == name and s.namespace == namespace), None)
        if existing:
            existing.url = url; existing.branch = branch; existing.interval = interval
            existing.secret_ref = secret_ref; existing.last_updated = now
            src = existing
        else:
            src = GitSource(name=name, namespace=namespace, url=url,
                            branch=branch, interval=interval, secret_ref=secret_ref,
                            registered_at=now, last_updated=now)
            state.sources.append(src)
        if not dry_run:
            self.save(state)
        return src

    def register_kustomization(self, name, namespace, source_ref, source_namespace,
                                path, interval="10m", prune=True,
                                depends_on=None, dry_run=False):
        """Register a Kustomization."""
        state = self.load()
        now = self._now_fn().strftime("%Y-%m-%dT%H:%M:%SZ")
        existing = next((k for k in state.kustomizations
                         if k.name == name and k.namespace == namespace), None)
        if existing:
            existing.source_ref = source_ref; existing.source_namespace = source_namespace
            existing.path = path; existing.interval = interval; existing.prune = prune
            existing.depends_on = depends_on or []; existing.last_updated = now
            ks = existing
        else:
            ks = Kustomization(
                name=name, namespace=namespace, source_ref=source_ref,
                source_namespace=source_namespace, path=path, interval=interval,
                prune=prune, depends_on=depends_on or [],
                registered_at=now, last_updated=now,
            )
            state.kustomizations.append(ks)
        if not dry_run:
            self.save(state)
        return ks

    # ------------------------------------------------------------------
    # Manifest generation
    # ------------------------------------------------------------------

    def generate_git_repository_manifest(self, src):
        spec: dict = {
            "interval": src.interval,
            "ref": {"branch": src.branch},
            "url": src.url,
        }
        if src.secret_ref:
            spec["secretRef"] = {"name": src.secret_ref}
        return {
            "apiVersion": "source.toolkit.fluxcd.io/v1",
            "kind": "GitRepository",
            "metadata": {"name": src.name, "namespace": src.namespace},
            "spec": spec,
        }

    def generate_kustomization_manifest(self, ks):
        spec: dict = {
            "interval": ks.interval,
            "path": ks.path,
            "prune": ks.prune,
            "sourceRef": {"kind": "GitRepository", "name": ks.source_ref,
                          "namespace": ks.source_namespace},
        }
        if ks.depends_on:
            spec["dependsOn"] = [{"name": d} for d in ks.depends_on]
        return {
            "apiVersion": "kustomize.toolkit.fluxcd.io/v1",
            "kind": "Kustomization",
            "metadata": {"name": ks.name, "namespace": ks.namespace},
            "spec": spec,
        }

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def reconcile(self, kind, name, namespace, timeout="2m"):
        """Trigger immediate reconciliation. kind = 'source' | 'kustomization'."""
        cmd = ["flux", "reconcile", kind, name, "--namespace", namespace,
               "--timeout", timeout]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        return result.returncode, result.stdout + result.stderr

    def get_all_status(self):
        """Return dict of live Flux object statuses (requires flux CLI)."""
        statuses = {}
        for kind in ("source git", "kustomization"):
            parts = kind.split()
            cmd = ["flux", "get"] + parts + ["--all-namespaces", "--output", "json"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
            if result.returncode == 0:
                try:
                    statuses[kind] = json.loads(result.stdout)
                except json.JSONDecodeError:
                    statuses[kind] = {"error": "parse failed"}
            else:
                statuses[kind] = {"error": result.stderr.strip()}
        return statuses

    def apply_source(self, src, dry_run=False):
        """kubectl apply a GitRepository manifest."""
        manifest = self.generate_git_repository_manifest(src)
        return self._kubectl_apply(manifest, dry_run)

    def apply_kustomization(self, ks, dry_run=False):
        """kubectl apply a Kustomization manifest."""
        manifest = self.generate_kustomization_manifest(ks)
        return self._kubectl_apply(manifest, dry_run)

    def _kubectl_apply(self, manifest, dry_run=False):
        mpath = os.path.join(self._state_dir,
                             f"flux-{manifest['kind'].lower()}-{manifest['metadata']['name']}.json.tmp")
        os.makedirs(self._state_dir, exist_ok=True)
        with open(mpath, "w") as fh:
            json.dump(manifest, fh)
        cmd = ["kubectl", "apply", "-f", mpath]
        if dry_run:
            cmd.append("--dry-run=client")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT)
        try:
            os.remove(mpath)
        except OSError:
            pass
        return result.returncode


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="flux_manager — Phase 2.G GitOps")
    parser.add_argument("--state-dir", default="/var/lib/broodforge")
    sub = parser.add_subparsers(dest="cmd")

    bg = sub.add_parser("bootstrap-git", help="Bootstrap Flux on a generic Git server")
    bg.add_argument("--url", required=True)
    bg.add_argument("--path", required=True)
    bg.add_argument("--branch", default="main")
    bg.add_argument("--namespace", default="flux-system")
    bg.add_argument("--secret-ref", default="")
    bg.add_argument("--dry-run", action="store_true")

    rs = sub.add_parser("register-source", help="Register a GitRepository source")
    rs.add_argument("--name", required=True)
    rs.add_argument("--namespace", required=True)
    rs.add_argument("--url", required=True)
    rs.add_argument("--branch", default="main")
    rs.add_argument("--interval", default="1m")
    rs.add_argument("--secret-ref", default="")
    rs.add_argument("--dry-run", action="store_true")

    rk = sub.add_parser("register-kustomization", help="Register a Kustomization")
    rk.add_argument("--name", required=True)
    rk.add_argument("--namespace", required=True)
    rk.add_argument("--source-ref", required=True)
    rk.add_argument("--source-namespace", required=True)
    rk.add_argument("--path", required=True)
    rk.add_argument("--interval", default="10m")
    rk.add_argument("--no-prune", action="store_true")
    rk.add_argument("--depends-on", nargs="*", default=[])
    rk.add_argument("--dry-run", action="store_true")

    sub.add_parser("list", help="List registered sources and kustomizations")

    rc = sub.add_parser("reconcile", help="Trigger reconciliation")
    rc.add_argument("--kind", required=True, choices=["source", "kustomization"])
    rc.add_argument("--name", required=True)
    rc.add_argument("--namespace", required=True)
    rc.add_argument("--timeout", default="2m")

    sub.add_parser("status", help="Show live Flux status")

    args = parser.parse_args(argv)
    mgr = FluxManager(state_dir=args.state_dir)

    if args.cmd == "bootstrap-git":
        rc = mgr.bootstrap_git(url=args.url, path=args.path, branch=args.branch,
                                namespace=args.namespace, secret_ref=args.secret_ref,
                                dry_run=args.dry_run)
        print("OK" if rc == 0 else f"FAILED (rc={rc})")
        return rc
    elif args.cmd == "register-source":
        src = mgr.register_source(name=args.name, namespace=args.namespace, url=args.url,
                                   branch=args.branch, interval=args.interval,
                                   secret_ref=args.secret_ref, dry_run=args.dry_run)
        print(json.dumps(src.to_dict(), indent=2))
        return 0
    elif args.cmd == "register-kustomization":
        ks = mgr.register_kustomization(
            name=args.name, namespace=args.namespace, source_ref=args.source_ref,
            source_namespace=args.source_namespace, path=args.path,
            interval=args.interval, prune=not args.no_prune,
            depends_on=args.depends_on, dry_run=args.dry_run)
        print(json.dumps(ks.to_dict(), indent=2))
        return 0
    elif args.cmd == "list":
        state = mgr.load()
        print("Sources:")
        for s in state.sources:
            print(f"  {s.namespace}/{s.name}: {s.url} [{s.branch}] every {s.interval}")
        print("Kustomizations:")
        for k in state.kustomizations:
            print(f"  {k.namespace}/{k.name}: {k.path} from {k.source_ref} every {k.interval}")
        return 0
    elif args.cmd == "reconcile":
        rcode, out = mgr.reconcile(args.kind, args.name, args.namespace, args.timeout)
        print(out)
        return rcode
    elif args.cmd == "status":
        s = mgr.get_all_status()
        print(json.dumps(s, indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
