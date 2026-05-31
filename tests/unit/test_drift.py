"""Tests for doc-gen/drift.py — field-level manifest diff and drift detection."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "doc-gen"))

from drift import compute_drift, doc_field_drift


def _drift(from_m, to_m):
    return compute_drift(from_m, to_m, "snap_a", "snap_b")


class TestIdenticalManifests(unittest.TestCase):
    def test_no_diffs(self):
        m = {"host": {"hostname": "pve1", "memory": {"total_gb": 64}}}
        result = _drift(m, m)
        self.assertEqual(result["diffs"], [])
        self.assertEqual(result["drift_severity"], "LOW")

    def test_metadata_excluded(self):
        m1 = {"schema_version": "1.0", "collected_at": "2026-01-01T00:00:00Z",
               "assessment_tier": 1, "host": {"hostname": "pve1"}}
        m2 = {"schema_version": "2.0", "collected_at": "2026-06-01T00:00:00Z",
               "assessment_tier": 2, "host": {"hostname": "pve1"}}
        result = _drift(m1, m2)
        self.assertEqual(result["diffs"], [])


class TestSeverity(unittest.TestCase):
    def test_ip_change_high(self):
        m1 = {"network": {"management_ip": "10.0.0.1"}}
        m2 = {"network": {"management_ip": "10.0.0.2"}}
        result = _drift(m1, m2)
        self.assertEqual(len(result["diffs"]), 1)
        self.assertEqual(result["diffs"][0]["severity"], "HIGH")
        self.assertEqual(result["drift_severity"], "HIGH")

    def test_hostname_change_high(self):
        m1 = {"host": {"hostname": "pve1"}}
        m2 = {"host": {"hostname": "pve2"}}
        result = _drift(m1, m2)
        self.assertEqual(result["diffs"][0]["severity"], "HIGH")

    def test_version_change_medium(self):
        m1 = {"host": {"pve_version": "8.1.0"}}
        m2 = {"host": {"pve_version": "8.2.0"}}
        result = _drift(m1, m2)
        self.assertEqual(result["diffs"][0]["severity"], "MEDIUM")
        self.assertEqual(result["drift_severity"], "MEDIUM")

    def test_count_change_low(self):
        m1 = {"vms": {"count": 3}}
        m2 = {"vms": {"count": 5}}
        result = _drift(m1, m2)
        self.assertEqual(result["diffs"][0]["severity"], "LOW")
        self.assertEqual(result["drift_severity"], "LOW")


class TestAdditionsRemovals(unittest.TestCase):
    def test_vm_added(self):
        m1 = {"vms": {"list": []}}
        m2 = {"vms": {"list": [{"vmid": 100, "name": "web01"}]}}
        result = _drift(m1, m2)
        # new paths appear as additions
        additions = [d for d in result["diffs"] if d["from_value"] is None]
        self.assertGreater(len(additions), 0)

    def test_vm_removed(self):
        m1 = {"vms": {"list": [{"vmid": 100, "name": "web01"}]}}
        m2 = {"vms": {"list": []}}
        result = _drift(m1, m2)
        removals = [d for d in result["diffs"] if d["to_value"] is None]
        self.assertGreater(len(removals), 0)

    def test_field_added(self):
        m1 = {"host": {"hostname": "pve1"}}
        m2 = {"host": {"hostname": "pve1", "cpu_model": "EPYC"}}
        result = _drift(m1, m2)
        additions = [d for d in result["diffs"] if d["from_value"] is None]
        self.assertEqual(len(additions), 1)
        self.assertEqual(additions[0]["path"], "host.cpu_model")

    def test_field_removed(self):
        m1 = {"host": {"hostname": "pve1", "cpu_model": "EPYC"}}
        m2 = {"host": {"hostname": "pve1"}}
        result = _drift(m1, m2)
        removals = [d for d in result["diffs"] if d["to_value"] is None]
        self.assertEqual(len(removals), 1)
        self.assertEqual(removals[0]["path"], "host.cpu_model")


class TestNestedPaths(unittest.TestCase):
    def test_nested_storage_change(self):
        m1 = {"storage": {"zfs_pools": [{"name": "rpool", "free_gb": 500}]}}
        m2 = {"storage": {"zfs_pools": [{"name": "rpool", "free_gb": 320}]}}
        result = _drift(m1, m2)
        changed = [d for d in result["diffs"] if "free_gb" in d["path"]]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["from_value"], 500)
        self.assertEqual(changed[0]["to_value"], 320)


class TestSeverityEscalation(unittest.TestCase):
    def test_escalates_to_high(self):
        m1 = {"host": {"pve_version": "8.1", "management_ip": "10.0.0.1"}}
        m2 = {"host": {"pve_version": "8.2", "management_ip": "10.0.0.5"}}
        result = _drift(m1, m2)
        self.assertEqual(result["drift_severity"], "HIGH")

    def test_escalates_to_medium(self):
        m1 = {"host": {"pve_version": "8.1", "count": 3}}
        m2 = {"host": {"pve_version": "8.2", "count": 5}}
        result = _drift(m1, m2)
        self.assertEqual(result["drift_severity"], "MEDIUM")


class TestDocFieldDrift(unittest.TestCase):
    def setUp(self):
        self.field_map = {
            "host.hostname": "Host Name",
            "network.management_ip": "Management IP",
            "host.pve_version": "PVE Version",
            "storage.total_gb": "Total Storage (GB)",
        }

    def test_stale_fields_identified(self):
        m1 = {"host": {"hostname": "pve1"}, "network": {"management_ip": "10.0.0.1"}}
        m2 = {"host": {"hostname": "pve2"}, "network": {"management_ip": "10.0.0.1"}}
        drift = _drift(m1, m2)
        stale = doc_field_drift(drift, self.field_map)
        self.assertIn("Host Name", stale)
        self.assertNotIn("Management IP", stale)

    def test_no_stale_when_no_drift(self):
        m = {"host": {"hostname": "pve1"}, "network": {"management_ip": "10.0.0.1"}}
        drift = _drift(m, m)
        stale = doc_field_drift(drift, self.field_map)
        self.assertEqual(stale, [])

    def test_prefix_match_for_nested(self):
        m1 = {"storage": {"total_gb": 1000}}
        m2 = {"storage": {"total_gb": 800}}
        drift = _drift(m1, m2)
        stale = doc_field_drift(drift, self.field_map)
        self.assertIn("Total Storage (GB)", stale)

    def test_record_header_fields(self):
        m1 = {"host": {"hostname": "pve1"}}
        m2 = {"host": {"hostname": "pve2"}}
        drift = _drift(m1, m2)
        self.assertEqual(drift["from_snapshot"], "snap_a")
        self.assertEqual(drift["to_snapshot"], "snap_b")
        self.assertIn("generated_at", drift)
        self.assertIn("doc_fields_stale", drift)


if __name__ == "__main__":
    import unittest
    unittest.main(verbosity=2)
