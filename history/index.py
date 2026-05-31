"""
Snapshot index builder.

Scans history/snapshots/ for manifest.json files and writes history/index.json.
Run: python3 history/index.py [--root <project-root>]
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def build_index(root: Path) -> dict:
    snapshots_dir = root / "history" / "snapshots"
    snapshots = []

    for snapshot_dir in sorted(snapshots_dir.iterdir()):
        if not snapshot_dir.is_dir():
            continue
        manifest_path = snapshot_dir / "manifest.json"
        if not manifest_path.exists():
            continue

        with open(manifest_path) as f:
            manifest = json.load(f)

        snap_id = snapshot_dir.name
        tier = manifest.get("assessment_tier", 1)
        collected_at = manifest.get("collected_at", "")

        # Derive template_version: tier 1 gets a version label, tier 2 none
        template_version = f"bootstrap-v1.0" if tier == 1 else None

        snapshots.append({
            "id": snap_id,
            "tier": tier,
            "collected_at": collected_at,
            "archive_path": f"history/snapshots/{snap_id}.tar.gz",
            "manifest_path": f"history/snapshots/{snap_id}/manifest.json",
            "template_version": template_version,
            "doc_generation_ids": [],
            "notes": "",
        })

    tier1 = [s for s in snapshots if s["tier"] == 1]
    tier2 = [s for s in snapshots if s["tier"] == 2]

    latest_tier1 = max(tier1, key=lambda s: s["collected_at"])["id"] if tier1 else None
    latest_tier2 = max(tier2, key=lambda s: s["collected_at"])["id"] if tier2 else None

    return {
        "snapshots": snapshots,
        "latest_tier1_id": latest_tier1,
        "latest_tier2_id": latest_tier2,
    }


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
