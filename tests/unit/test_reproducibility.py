"""
Reproducibility test: same manifest → byte-identical ODS and ODT outputs.

Validates the requirement that historical snapshots produce deterministic docs.
"""

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "doc-gen"))
sys.path.insert(0, str(ROOT / "doc-gen" / "renderers"))
sys.path.insert(0, str(ROOT / "data-model"))

TIER1_FIXTURE = ROOT / "tests" / "fixtures" / "tier1" / "manifest.json"


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class TestBootstrapReproducibility(unittest.TestCase):
    """Bootstrap doc-gen must be deterministic: same manifest → same bytes."""

    def _generate(self, manifest: dict) -> tuple[bytes, bytes]:
        """Run the bootstrap pipeline and return (ods_bytes, odt_bytes)."""
        # Import here so sys.path is already set
        import analyzers as az
        from workbook import build_bootstrap_workbook
        from runbook import build_bootstrap_runbook

        # Replicate _resolve_fields logic from engine.py inline to avoid
        # coupling to engine's argparse / file I/O
        resolved: dict = {}

        def _get(path, default=None):
            parts = path.split(".")
            obj = manifest
            for p in parts:
                if not isinstance(obj, dict):
                    return default
                obj = obj.get(p, default)
            return obj

        AUTO_FIELDS = {
            "host.hostname":         "host.hostname",
            "host.fqdn":             "host.fqdn",
            "host.proxmox_version":  "host.proxmox_version",
            "host.kernel_version":   "host.kernel_version",
            "host.timezone":         "host.timezone",
            "cpu.model":             "cpu.model",
            "cpu.total_threads":     "cpu.total_threads",
            "cpu.sockets":           "cpu.sockets",
            "cpu.cores_per_socket":  "cpu.cores_per_socket",
            "cpu.threads_per_core":  "cpu.threads_per_core",
            "cpu.architecture":      "cpu.architecture",
            "cpu.virtualization":    "cpu.virtualization",
            "memory.total_gb":       "memory.total_gb",
            "memory.available_gb":   "memory.available_gb",
            "memory.swap_total_gb":  "memory.swap_total_gb",
            "memory.numa_nodes":     "memory.numa_nodes",
            "network.default_gateway": "network.default_gateway",
            "network.dns_servers":   "network.dns_servers",
        }
        for field_id, path in AUTO_FIELDS.items():
            val = _get(path)
            if val is not None:
                resolved[field_id] = {
                    "value": str(val) if not isinstance(val, (list, dict)) else val,
                    "class": "AUTO", "note": f"From manifest: {path}",
                }
            else:
                resolved[field_id] = {
                    "value": "(not detected)", "class": "UNRESOLVED",
                    "note": f"Field '{path}' was not populated during assessment",
                }
        dns = _get("network.dns_servers") or []
        resolved["network.dns_servers"]["value"] = ", ".join(dns) if dns else "(none)"

        DERIVED_FIELDS = {
            "derived.zfs_topology":       "storage.zfs_topology",
            "derived.storage_pool_name":  "storage.pool_name",
            "derived.vm_id":              "vm_ids.next_available",
            "derived.vm_id_sequence":     "vm_ids.sequence_4",
            "derived.vm_ram":             "vm_sizing.infra_bootstrap_ram",
            "derived.vm_cores":           "vm_sizing.infra_bootstrap_cores",
            "derived.vm_disk":            "vm_sizing.infra_bootstrap_disk",
            "derived.vm_bridge":          "network.recommend_bridge",
            "derived.vm_ip_plan":         "network.recommend_ip_plan",
            "derived.vm_storage_pool":    "storage.pool_name",
            "derived.automation_summary": "software.automation_readiness",
        }
        for field_id, analyzer_id in DERIVED_FIELDS.items():
            result = az.run(analyzer_id, manifest)
            resolved[field_id] = {
                "value": result.value,
                "class": "DERIVED" if result.value != "UNRESOLVED" else "UNRESOLVED",
                "note":  result.rationale,
                "warnings": result.warnings,
                "confidence": result.confidence,
            }

        HUMAN_FIELDS = [
            ("human.root_password_location", "KeePass path for root password"),
            ("human.recovery_passphrase",     "KeePass path for disk encryption passphrase"),
            ("human.vm_ip_address",           "Static IP for infra-bootstrap VM"),
            ("human.vm_name",                 "VM name"),
            ("human.vm_username",             "OS username"),
            ("human.vm_password_location",    "KeePass path for VM password"),
            ("human.iso_location",            "ISO path in Proxmox"),
        ]
        for field_id, prompt in HUMAN_FIELDS:
            resolved[field_id] = {"value": None, "class": "HUMAN", "note": prompt}

        counts = {"AUTO": 0, "DERIVED": 0, "HUMAN": 0, "UNRESOLVED": 0}
        for entry in resolved.values():
            c = entry.get("class", "UNRESOLVED")
            counts[c] = counts.get(c, 0) + 1

        meta = {
            "generated_at":     "2026-01-01T00:00:00Z",  # fixed for reproducibility
            "collected_at":     manifest.get("collected_at", "unknown"),
            "tier":             manifest.get("assessment_tier", 1),
            "template_version": "bootstrap-v1.0",
            "field_counts":     counts,
            "unresolved_fields": [],
            "human_fields":     [],
            "drift":            None,
        }

        ods = build_bootstrap_workbook(manifest, resolved, meta)
        odt = build_bootstrap_runbook(manifest, resolved, meta)
        return ods, odt

    def test_ods_byte_identical(self):
        manifest = json.loads(TIER1_FIXTURE.read_text())
        ods1, _ = self._generate(manifest)
        ods2, _ = self._generate(manifest)
        self.assertEqual(
            _md5(ods1), _md5(ods2),
            "Bootstrap ODS output is not deterministic — same manifest produced different bytes"
        )

    def test_odt_byte_identical(self):
        manifest = json.loads(TIER1_FIXTURE.read_text())
        _, odt1 = self._generate(manifest)
        _, odt2 = self._generate(manifest)
        self.assertEqual(
            _md5(odt1), _md5(odt2),
            "Bootstrap ODT output is not deterministic — same manifest produced different bytes"
        )

    def test_different_manifests_differ(self):
        """Sanity check: different manifests produce different output."""
        m1 = json.loads(TIER1_FIXTURE.read_text())
        m2 = json.loads(TIER1_FIXTURE.read_text())
        m2.setdefault("host", {})["hostname"] = "different-host"
        ods1, _ = self._generate(m1)
        ods2, _ = self._generate(m2)
        self.assertNotEqual(
            _md5(ods1), _md5(ods2),
            "Different manifests should produce different ODS output"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
