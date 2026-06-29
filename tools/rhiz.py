#!/usr/bin/env python3
"""rhiz — run rhizome's pinned tooling against THIS repository.

The executable tooling (rhiz-lint, rhiz-search, doc-graph) lives in the rhizome
repository and ONLY there. This thin bootstrap resolves a rhizome checkout at the
shared **`tools-stable`** channel and forwards a subcommand to the matching tool
with this repo as its target — so every repo runs the ONE canonical version of
the tools, never a copy that can drift apart. The channel moves only when rhizome
blesses a tool revision (a single fast-forward), so the whole ecosystem advances
together. See `rhiz-child-repo-convention.md` §1.1.

This file is itself a stable bootstrap (like `gradlew`/`mvnw`): copy it into a
child repo's `tools/`. It rarely changes; the tools it dispatches to are never
copied. Keep it current with `rhiz self-update` (pulls the canonical bootstrap
from the channel).

Forge-agnostic. Nothing here hardcodes a host beyond a *default* URL:
  $RHIZ_TOOLS_URL  — where rhizome lives (default: the GitHub origin). Point it at
                     a Forgejo/Gitea/self-hosted instance to switch forges; git,
                     the channel branch, and the tools are otherwise identical.
  $RHIZ_TOOLS_REF  — channel/ref to track (default: tools-stable). A SHA here is
                     the escape-hatch for temporarily pinning during a risky bump.
  $RHIZ_TOOLS_PATH — an existing local rhizome checkout (e.g. a sibling clone);
                     used as-is for dev speed. CI's source of truth is the channel.

Resolution order for the rhizome checkout:
  1. $RHIZ_TOOLS_PATH if it points at a real checkout;
  2. a cached clone at <repo>/.rhiz-tools/rhizome, fetched to the channel from
     $RHIZ_TOOLS_URL.

Subcommands (extra args are forwarded to the underlying tool):
  lint [..]        rhiz-lint.py    --root <repo> [..]
  search [..]      rhiz-search.py  --root-repo <repo> [..]   (e.g. `search query "x"`)
  docs             doc-graph.py render-all --root <repo>
  verify <index>   doc-graph.py verify <index>
  maintain         lint + search index + docs   (the mechanical loop, no LLM)
  report           rhiz-maintain.py --report — classify findings auto vs judgment
  update           refresh the cached rhizome checkout only
  self-update      overwrite this bootstrap with the channel's canonical copy
  channel          print the channel/ref this repo tracks (drift-guard reads this)
  where            print the resolved rhizome checkout path + forge URL
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

CHANNEL_DEFAULT = "tools-stable"
RHIZOME_URL_DEFAULT = "https://github.com/david-coneff/rhizome.git"


def repo_root() -> Path:
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(top)
    except Exception:
        return Path.cwd()


def channel() -> str:
    return os.environ.get("RHIZ_TOOLS_REF", CHANNEL_DEFAULT)


def tools_url() -> str:
    return os.environ.get("RHIZ_TOOLS_URL", RHIZOME_URL_DEFAULT)


def resolve_rhizome(root: Path) -> Path:
    local = os.environ.get("RHIZ_TOOLS_PATH")
    if local and (Path(local) / "tools" / "rhiz-lint.py").exists():
        return Path(local).resolve()
    cache = root / ".rhiz-tools" / "rhizome"
    ref = channel()
    if not (cache / ".git").exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, tools_url(), str(cache)],
            check=True,
        )
    else:
        subprocess.run(["git", "-C", str(cache), "fetch", "--depth", "1", "origin", ref], check=True)
        subprocess.run(["git", "-C", str(cache), "checkout", "-q", "FETCH_HEAD"], check=True)
    return cache


def _run(args) -> int:
    print("+ " + " ".join(str(a) for a in args), file=sys.stderr)
    return subprocess.run(args).returncode


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    sub, rest = sys.argv[1], sys.argv[2:]
    root = repo_root()

    if sub == "channel":
        print(channel())
        return 0

    R = resolve_rhizome(root)
    py = sys.executable or "python3"
    lint = str(R / "tools" / "rhiz-lint.py")
    search = str(R / "tools" / "rhiz-search.py")
    dg = str(R / "protocol" / "modules" / "rhiz-merkle" / "tools" / "doc-graph.py")

    if sub == "where":
        print(f"rhizome: {R}\nforge:   {tools_url()}\nchannel: {channel()}")
        return 0
    if sub == "update":
        return 0  # resolve_rhizome already refreshed the cache
    if sub == "self-update":
        src, dst = R / "tools" / "rhiz.py", root / "tools" / "rhiz.py"
        if src.resolve() == dst.resolve():
            print("self-update skipped: this IS the canonical bootstrap")
            return 0
        shutil.copyfile(src, dst)
        print(f"updated {dst} from {R} @ {channel()}")
        return 0
    if sub == "lint":
        return _run([py, lint, "--root", str(root), *rest])
    if sub == "search":
        return _run([py, search, "--root-repo", str(root), *rest])
    if sub == "docs":
        return _run([py, dg, "render-all", "--root", str(root), *rest])
    if sub == "verify":
        return _run([py, dg, "verify", *rest])
    if sub == "maintain":
        rc = _run([py, lint, "--root", str(root)])
        rc |= _run([py, search, "--root-repo", str(root), "index"])
        rc |= _run([py, dg, "render-all", "--root", str(root)])
        return rc
    if sub == "report":
        return _run([py, str(R / "tools" / "rhiz-maintain.py"), "--report", "--root", str(root), *rest])

    print(f"unknown subcommand: {sub}\n{__doc__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
