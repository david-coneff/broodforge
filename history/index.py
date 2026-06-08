"""
Snapshot index builder.

Scans history/snapshots/ for manifest.json files and writes history/index.json.
Run: python3 history/index.py [--root <project-root>]
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).parent
_DOC_GEN_DIR = _HERE.parent / "doc-gen"
if str(_DOC_GEN_DIR) not in sys.path:
    sys.path.insert(0, str(_DOC_GEN_DIR))

try:
    from dependencies import build_graph as _build_graph
    _HAS_DEPENDENCIES = True
except ImportError:
    _build_graph = None  # type: ignore
    _HAS_DEPENDENCIES = False


def _canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _hash_dict(obj: dict) -> str:
    return hashlib.sha256(_canonical_json(obj).encode("utf-8")).hexdigest()


def build_index(root: Path) -> dict:
    """
    Build the snapshot index.

    Each entry additionally carries `manifest_hash` (SHA-256 over the
    snapshot's canonical-JSON manifest) and `graph_hash` (SHA-256 over the
    canonical form of the dependency graph `dependencies.build_graph` derives
    from it) — Phase 1.I / AD-059's "the graph that produced this readiness
    score is independently checkable after the fact" requirement.

    These hashes are recorded HERE, in the regenerated index, rather than
    written into each snapshot's `manifest.json` — the index is a derived
    registry this script already regenerates wholesale, while `manifest.json`
    files are raw historical captures that should not be mutated after the
    fact (mutating them would itself be a tamper-evidence problem, the exact
    thing these hashes exist to detect). `replay-snapshot.py` recomputes both
    hashes from the stored manifest and compares them against these recorded
    values to assert reproducibility.
    """
    snapshots_dir = root / "history" / "snapshots"
    snapshots = []
    cell_id = None

    for snapshot_dir in sorted(snapshots_dir.iterdir()):
        if not snapshot_dir.is_dir():
            continue
        manifest_path = snapshot_dir / "manifest.json"
        if not manifest_path.exists():
            continue

        with open(manifest_path) as f:
            manifest = json.load(f)

        if cell_id is None and manifest.get("cell_id"):
            cell_id = manifest["cell_id"]

        snap_id = snapshot_dir.name
        tier = manifest.get("assessment_tier", 1)
        collected_at = manifest.get("collected_at", "")

        # Derive template_version: tier 1 gets a version label, tier 2 none
        template_version = f"bootstrap-v1.0" if tier == 1 else None

        manifest_hash = _hash_dict(manifest)
        graph_hash = None
        if _HAS_DEPENDENCIES:
            try:
                graph_hash = _hash_dict(_build_graph(manifest).to_dict())
            except Exception:
                graph_hash = None

        snapshots.append({
            "id": snap_id,
            "tier": tier,
            "collected_at": collected_at,
            "archive_path": f"history/snapshots/{snap_id}.tar.gz",
            "manifest_path": f"history/snapshots/{snap_id}/manifest.json",
            "template_version": template_version,
            "doc_generation_ids": [],
            "notes": "",
            "manifest_hash": manifest_hash,
            "graph_hash": graph_hash,
        })

    tier1 = [s for s in snapshots if s["tier"] == 1]
    tier2 = [s for s in snapshots if s["tier"] == 2]

    latest_tier1 = max(tier1, key=lambda s: s["collected_at"])["id"] if tier1 else None
    latest_tier2 = max(tier2, key=lambda s: s["collected_at"])["id"] if tier2 else None

    index = {
        "snapshots": snapshots,
        "latest_tier1_id": latest_tier1,
        "latest_tier2_id": latest_tier2,
    }
    if cell_id:
        index["cell_id"] = cell_id
    return index


def main():
    # Allow --root override for testing
    if "--root" in sys.argv:
        idx = sys.argv.index("--root")
        root = Path(sys.argv[idx + 1]).resolve()
    else:
        root = Path(__file__).parent.parent

    index = build_index(root)
    out_path = root / "history" / "index.json"
    with open(out_path, "w") as f:
        json.dump(index, f, indent=2)
    print(f"Wrote {out_path} ({len(index['snapshots'])} snapshots)")


if __name__ == "__main__":
    main()
