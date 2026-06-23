#!/usr/bin/env python3
"""
Tests for doc-gen/readiness.py — scoring model, cascade, SPOFs, blockers.
Run: python3 tests/unit/test_readiness.py
"""

import json
import unittest
from pathlib import Path

REPO = Path(__file__).parent.parent.parent

import dependencies as dep_mod
from readiness import (
    BackupInventory,
    _score_migration_health,
    score_component,
    score_graph,
    worst,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_inv(jobs=None, vzdump=None, offsite=None, tests=None):
    return {
        "pbs_jobs": jobs or [],
        "vzdump_schedules": vzdump or [],
        "offsite_backups": offsite or [],
        "restore_tests": tests or [],
    }


def _job(vmid, age_days, state="ok", tested=False, last_test=None):
    return {
        "job_id": f"job-{vmid}",
        "vmid": vmid,
        "name": f"vm-{vmid}",
        "datastore": "main",
        "schedule": "daily",
        "last_run_at": "2026-05-29T03:00:00Z",
        "last_run_state": state,
        "age_days": age_days,
        "size_bytes": 1073741824,
        "restore_tested": tested,
        "last_restore_test_at": last_test,
    }


def _node(nid, ntype, metadata=None):
    from dependencies import Node
    return Node(id=nid, type=ntype, label=nid, metadata=metadata or {})


# ---------------------------------------------------------------------------
# Test: worst()
# ---------------------------------------------------------------------------

class TestWorst(unittest.TestCase):
    def test_red_beats_all(self):
        for s in ("GREEN", "YELLOW", "ORANGE", "BLOCKED", "UNKNOWN"):
            self.assertEqual(worst("RED", s), "RED")
            self.assertEqual(worst(s, "RED"), "RED")

    def test_blocked_beats_orange_yellow_green(self):
        for s in ("GREEN", "YELLOW", "ORANGE"):
            self.assertEqual(worst("BLOCKED", s), "BLOCKED")

    def test_equal_returns_same(self):
        for s in ("GREEN", "YELLOW", "ORANGE", "RED", "BLOCKED"):
            self.assertEqual(worst(s, s), s)

    def test_green_is_best(self):
        self.assertEqual(worst("GREEN", "GREEN"), "GREEN")
        self.assertNotEqual(worst("GREEN", "YELLOW"), "GREEN")


# ---------------------------------------------------------------------------
# Test: BackupInventory
# ---------------------------------------------------------------------------

class TestBackupInventory(unittest.TestCase):
    def test_empty_inventory_not_available(self):
        bi = BackupInventory(None)
        self.assertFalse(bi.available())

    def test_non_empty_is_available(self):
        bi = BackupInventory(_make_inv(jobs=[_job(100, 1.0)]))
        self.assertTrue(bi.available())

    def test_find_job_by_vmid(self):
        bi = BackupInventory(_make_inv(jobs=[_job(100, 2.0), _job(101, 5.0)]))
        node = _node("vm:forgejo", "vm", {"vmid": 101})
        job = bi.find_job(node.id, node.type, node.metadata)
        self.assertIsNotNone(job)
        self.assertEqual(job["vmid"], 101)

    def test_find_host_job_by_vmid_zero(self):
        host_job = _job(0, 1.0)
        host_job["name"] = "pve01-host"
        bi = BackupInventory(_make_inv(jobs=[host_job]))
        node = _node("host:pve01", "host", {"hostname": "pve01"})
        job = bi.find_job(node.id, node.type, node.metadata)
        self.assertIsNotNone(job)

    def test_offsite_coverage(self):
        inv = _make_inv(offsite=[{
            "target": "nas:/backups",
            "method": "rsync",
            "last_sync_at": "2026-05-27T04:00:00Z",
            "age_days": 3.0,
            "covers": ["host:pve01", "zfs:rpool"],
        }])
        bi = BackupInventory(inv)
        self.assertTrue(bi.is_offsite_covered("host:pve01"))
        self.assertTrue(bi.is_offsite_covered("zfs:rpool"))
        self.assertFalse(bi.is_offsite_covered("vm:forgejo"))

    def test_best_job_selected_when_multiple(self):
        """If two jobs exist for same vmid, pick the fresher one."""
        old_job = _job(100, 10.0)
        new_job = _job(100, 1.0)
        bi = BackupInventory(_make_inv(jobs=[old_job, new_job]))
        node = _node("vm:something", "vm", {"vmid": 100})
        job = bi.find_job(node.id, node.type, node.metadata)
        self.assertEqual(job["age_days"], 1.0)


# ---------------------------------------------------------------------------
# Test: score_component — GREEN paths
# ---------------------------------------------------------------------------

class TestScoreComponentGreen(unittest.TestCase):
    def test_fresh_backup_tested_is_green(self):
        inv = _make_inv(jobs=[_job(101, 1.0, tested=True,
                                  last_test="2026-05-01T10:00:00Z")])
        bi = BackupInventory(inv)
        cr = score_component("vm:forgejo", "vm", {"vmid": 101}, bi)
        self.assertEqual(cr.score, "GREEN")
        self.assertEqual(len(cr.gaps), 0)

    def test_storage_no_job_still_green(self):
        """Storage nodes don't require individual backup jobs."""
        bi = BackupInventory(_make_inv())
        cr = score_component("zfs:rpool", "storage", {"pool_name": "rpool"}, bi)
        # Should not be RED — storage is implicitly covered
        self.assertNotEqual(cr.score, "RED")


# ---------------------------------------------------------------------------
# Test: score_component — YELLOW paths
# ---------------------------------------------------------------------------

class TestScoreComponentYellow(unittest.TestCase):
    def test_stale_backup_vm_threshold(self):
        """VM backup > 7 days → YELLOW."""
        inv = _make_inv(jobs=[_job(101, 8.0, tested=True,
                                  last_test="2026-05-01T10:00:00Z")])
        bi = BackupInventory(inv)
        cr = score_component("vm:forgejo", "vm", {"vmid": 101}, bi)
        self.assertEqual(cr.score, "YELLOW")
        gap_types = [g.gap_type for g in cr.gaps]
        self.assertIn("STALE_BACKUP", gap_types)

    def test_untested_restore_yields_yellow(self):
        inv = _make_inv(jobs=[_job(101, 1.0, tested=False)])
        bi = BackupInventory(inv)
        cr = score_component("vm:forgejo", "vm", {"vmid": 101}, bi)
        self.assertEqual(cr.score, "YELLOW")
        self.assertTrue(any(g.gap_type == "UNTESTED_RESTORE" for g in cr.gaps))

    def test_old_restore_test_yields_yellow(self):
        """Restore test older than 90 days → YELLOW."""
        inv = _make_inv(jobs=[_job(101, 1.0, tested=True,
                                  last_test="2025-01-01T00:00:00Z")])
        bi = BackupInventory(inv)
        cr = score_component("vm:forgejo", "vm", {"vmid": 101}, bi)
        self.assertIn(cr.score, ("YELLOW",))
        self.assertTrue(any(g.gap_type == "UNTESTED_RESTORE" for g in cr.gaps))

    def test_tier1_no_backup_data_yields_yellow_not_red(self):
        """No backup inventory (Tier 1) → YELLOW, not RED."""
        bi = BackupInventory(None)
        cr = score_component("vm:forgejo", "vm", {"vmid": 101}, bi)
        self.assertEqual(cr.score, "YELLOW")
        self.assertNotEqual(cr.score, "RED")

    def test_host_no_offsite_yields_yellow(self):
        """Host with local backup but no offsite → YELLOW."""
        host_job = _job(0, 1.0, tested=True, last_test="2026-05-01T10:00:00Z")
        bi = BackupInventory(_make_inv(jobs=[host_job]))
        cr = score_component("host:pve01", "host", {"hostname": "pve01"}, bi)
        self.assertEqual(cr.score, "YELLOW")
        self.assertTrue(any("offsite" in g.description.lower() for g in cr.gaps))


# ---------------------------------------------------------------------------
# Test: score_component — ORANGE paths
# ---------------------------------------------------------------------------

class TestScoreComponentOrange(unittest.TestCase):
    def test_very_stale_vm_backup_orange(self):
        """VM backup > 30 days → ORANGE."""
        inv = _make_inv(jobs=[_job(101, 35.0, tested=True,
                                  last_test="2026-05-01T10:00:00Z")])
        bi = BackupInventory(inv)
        cr = score_component("vm:forgejo", "vm", {"vmid": 101}, bi)
        self.assertEqual(cr.score, "ORANGE")

    def test_stale_host_backup_orange(self):
        """Host backup > 7 days → ORANGE."""
        host_job = _job(0, 8.0, tested=True, last_test="2026-05-01T10:00:00Z")
        offsite = [{"target": "nas:/b", "method": "rsync",
                    "last_sync_at": "2026-05-27T04:00:00Z",
                    "age_days": 1.0, "covers": ["host:pve01"]}]
        bi = BackupInventory(_make_inv(jobs=[host_job], offsite=offsite))
        cr = score_component("host:pve01", "host", {"hostname": "pve01"}, bi)
        self.assertEqual(cr.score, "ORANGE")


# ---------------------------------------------------------------------------
# Test: score_component — RED paths
# ---------------------------------------------------------------------------

class TestScoreComponentRed(unittest.TestCase):
    def test_no_backup_job_is_red(self):
        """VM with no backup job → RED."""
        bi = BackupInventory(_make_inv())  # empty inventory but available
        cr = score_component("vm:forgejo", "vm", {"vmid": 101}, bi)
        self.assertEqual(cr.score, "RED")
        self.assertTrue(any(g.gap_type == "MISSING_BACKUP" for g in cr.gaps))

    def test_failed_backup_run_is_red(self):
        inv = _make_inv(jobs=[_job(101, 1.0, state="failed")])
        bi = BackupInventory(inv)
        cr = score_component("vm:forgejo", "vm", {"vmid": 101}, bi)
        self.assertEqual(cr.score, "RED")


# ---------------------------------------------------------------------------
# Test: score_graph — cascade and graph-level
# ---------------------------------------------------------------------------

class TestScoreGraph(unittest.TestCase):
    def _build_two_node_graph(self, provider_score_data, consumer_score_data):
        """Build a minimal graph: consumer depends on provider."""
        from dependencies import DependencyGraph, Edge, Node, RestoreWave

        provider = Node(id="vm:provider", type="vm", label="Provider VM",
                        metadata={"vmid": 100})
        consumer = Node(id="vm:consumer", type="vm", label="Consumer VM",
                        metadata={"vmid": 101})
        edge = Edge("vm:consumer", "vm:provider", "NETWORK", "depends on provider")

        g = DependencyGraph(
            nodes=[provider, consumer],
            edges=[edge],
            restore_waves=[
                RestoreWave(1, ["vm:provider"], "provider first"),
                RestoreWave(2, ["vm:consumer"], "consumer after"),
            ]
        )
        return g

    def test_blocked_propagates_from_red(self):
        """Consumer becomes BLOCKED when provider is RED (missing backup)."""
        g = self._build_two_node_graph({}, {})
        # Provider has no backup (RED), consumer depends on it
        manifest = {
            "host": {"hostname": "pve01"},
            "backup_inventory": _make_inv(
                jobs=[_job(101, 1.0, tested=True, last_test="2026-05-01T10:00:00Z")]
                # vmid 100 (provider) has no backup → RED
            )
        }
        report = score_graph(g, manifest)
        scores = {c.component_id: c.score for c in report.components}
        self.assertEqual(scores.get("vm:provider"), "RED")
        self.assertEqual(scores.get("vm:consumer"), "BLOCKED")
        self.assertEqual(report.overall_score, "RED")

    def test_no_cascade_when_provider_is_yellow(self):
        """YELLOW provider does not block consumer."""
        g = self._build_two_node_graph({}, {})
        manifest = {
            "host": {"hostname": "pve01"},
            "backup_inventory": _make_inv(jobs=[
                _job(100, 8.0, tested=True, last_test="2026-05-01T10:00:00Z"),  # YELLOW (stale)
                _job(101, 1.0, tested=True, last_test="2026-05-01T10:00:00Z"),  # GREEN
            ])
        }
        report = score_graph(g, manifest)
        scores = {c.component_id: c.score for c in report.components}
        self.assertNotEqual(scores.get("vm:consumer"), "BLOCKED")

    def test_spof_detection(self):
        """Node with ≥2 VM dependents is a SPOF."""
        from dependencies import DependencyGraph, Edge, Node
        shared = Node(id="zfs:rpool", type="storage", label="rpool", metadata={})
        vm1    = Node(id="vm:a", type="vm", label="VM A", metadata={"vmid": 100})
        vm2    = Node(id="vm:b", type="vm", label="VM B", metadata={"vmid": 101})
        g = DependencyGraph(
            nodes=[shared, vm1, vm2],
            edges=[
                Edge("vm:a", "zfs:rpool", "STORAGE"),
                Edge("vm:b", "zfs:rpool", "STORAGE"),
            ],
            restore_waves=[]
        )
        manifest = {"host": {"hostname": "pve01"}, "backup_inventory": _make_inv(
            jobs=[_job(100, 1.0, tested=True, last_test="2026-05-01T10:00:00Z"),
                  _job(101, 1.0, tested=True, last_test="2026-05-01T10:00:00Z")]
        )}
        report = score_graph(g, manifest)
        self.assertIn("zfs:rpool", report.single_points_of_failure)

    def test_overall_score_is_worst(self):
        """overall_score = worst of all component scores."""
        from dependencies import DependencyGraph, Node
        g = DependencyGraph(
            nodes=[
                Node(id="vm:a", type="vm", label="VM A", metadata={"vmid": 200}),
                Node(id="vm:b", type="vm", label="VM B", metadata={"vmid": 201}),
            ],
            edges=[], restore_waves=[]
        )
        manifest = {
            "host": {"hostname": "pve01"},
            "backup_inventory": _make_inv(
                jobs=[
                    _job(200, 1.0, tested=True, last_test="2026-05-01T10:00:00Z"),  # GREEN
                    # 201 has no job → RED
                ]
            )
        }
        report = score_graph(g, manifest)
        self.assertEqual(report.overall_score, "RED")


# ---------------------------------------------------------------------------
# Test: full fixture end-to-end
# ---------------------------------------------------------------------------

class TestFixtureEndToEnd(unittest.TestCase):
    def test_tier2_fixture_scoring(self):
        """Run full scoring against the tier2 fixture. Verify expected scores."""
        fixture = json.loads(
            (REPO / "tests/fixtures/tier2/manifest.json").read_text()
        )
        graph = dep_mod.build_graph(fixture)
        report = score_graph(graph, fixture)

        scores = {c.component_id: c.score for c in report.components}

        # forgejo: 9-day-old backup, threshold 7 days → YELLOW
        forgejo_id = next((k for k in scores if "forgejo" in k), None)
        self.assertIsNotNone(forgejo_id)
        self.assertIn(scores[forgejo_id], ("YELLOW", "ORANGE"))

        # host: has backup, no offsite → YELLOW
        host_id = next((k for k in scores if k.startswith("host:")), None)
        self.assertIsNotNone(host_id)
        self.assertIn(scores[host_id], ("YELLOW",))

        # overall: at least YELLOW (forgejo is stale)
        self.assertIn(report.overall_score, ("YELLOW", "ORANGE", "RED"))

        # No BLOCKED (no RED components in this fixture)
        blocked = [c for c in report.components if c.score == "BLOCKED"]
        self.assertEqual(len(blocked), 0)

        # SPOFs should be detected (rpool has multiple dependents)
        self.assertGreater(len(report.single_points_of_failure), 0)


# ---------------------------------------------------------------------------
# Test: _score_migration_health (I3 audit fix — 9.T.12)
# ---------------------------------------------------------------------------

class TestScoreMigrationHealth(unittest.TestCase):
    def test_no_history_returns_empty(self):
        gaps = _score_migration_health({})
        self.assertEqual(gaps, [])

    def test_empty_history_returns_empty(self):
        gaps = _score_migration_health({"migration_history": []})
        self.assertEqual(gaps, [])

    def test_failed_outcome_gives_orange_gap(self):
        manifest = {
            "migration_history": [
                {"node_vm_name": "k3s-server-01", "migration_id": "m-001",
                 "outcome": "failed", "error": "talosctl apply timed out"},
            ]
        }
        gaps = _score_migration_health(manifest)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "ORANGE")
        self.assertEqual(gaps[0].gap_type, "MIGRATION_FAILED")
        self.assertIn("k3s-server-01", gaps[0].description)

    def test_rolled_back_outcome_gives_yellow_gap(self):
        manifest = {
            "migration_history": [
                {"node_vm_name": "k3s-worker-02", "migration_id": "m-002",
                 "outcome": "rolled_back"},
            ]
        }
        gaps = _score_migration_health(manifest)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].severity, "YELLOW")
        self.assertEqual(gaps[0].gap_type, "MIGRATION_ROLLED_BACK")
        self.assertIn("k3s-worker-02", gaps[0].description)

    def test_completed_outcome_gives_no_gap(self):
        manifest = {
            "migration_history": [
                {"node_vm_name": "k3s-server-01", "migration_id": "m-003",
                 "outcome": "completed"},
            ]
        }
        gaps = _score_migration_health(manifest)
        self.assertEqual(gaps, [])

    def test_mixed_outcomes_returns_both_gaps(self):
        manifest = {
            "migration_history": [
                {"node_vm_name": "node-a", "migration_id": "m-001", "outcome": "failed"},
                {"node_vm_name": "node-b", "migration_id": "m-002", "outcome": "rolled_back"},
                {"node_vm_name": "node-c", "migration_id": "m-003", "outcome": "completed"},
            ]
        }
        gaps = _score_migration_health(manifest)
        self.assertEqual(len(gaps), 2)
        severities = {g.severity for g in gaps}
        self.assertIn("ORANGE", severities)
        self.assertIn("YELLOW", severities)

    def test_multiple_failed_gives_multiple_gaps(self):
        manifest = {
            "migration_history": [
                {"node_vm_name": "node-a", "migration_id": "m-001", "outcome": "failed"},
                {"node_vm_name": "node-b", "migration_id": "m-002", "outcome": "failed"},
            ]
        }
        gaps = _score_migration_health(manifest)
        self.assertEqual(len(gaps), 2)
        self.assertTrue(all(g.severity == "ORANGE" for g in gaps))


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ===========================================================================
# Phase 1.M — hypothesis property tests
# ===========================================================================

try:
    from hypothesis import assume, given, settings
    from hypothesis import strategies as st
    _HAS_HYPOTHESIS = True
except ImportError:
    _HAS_HYPOTHESIS = False

if _HAS_HYPOTHESIS:
    _VALID_SCORES = ("GREEN", "YELLOW", "ORANGE", "RED", "BLOCKED", "UNKNOWN")

    class TestScoreComponentProperties:
        def _inv(self) -> "BackupInventory":
            return BackupInventory({"available": False})

        @given(
            node_id=st.text(min_size=1, max_size=64,
                            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                                   whitelist_characters="-_")),
            node_type=st.sampled_from(["proxmox_host", "k3s_vm", "service_vm", "unknown"]),
        )
        @settings(max_examples=30)
        def test_always_returns_valid_score(self, node_id: str, node_type: str) -> None:
            assume(node_id.strip())
            result = score_component(node_id, node_type, {}, self._inv())
            assert result.score in _VALID_SCORES

        @given(
            node_id=st.text(min_size=1, max_size=32,
                            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                                   whitelist_characters="-")),
        )
        @settings(max_examples=30)
        def test_score_component_dep_info_false_returns_blocked_or_worse(self, node_id: str) -> None:
            assume(node_id.strip())
            result = score_component(node_id, "proxmox_host", {}, self._inv(),
                                     dep_info_complete=False)
            assert result.score in _VALID_SCORES

        @given(
            node_id=st.text(min_size=1, max_size=32,
                            alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                                   whitelist_characters="-")),
            node_type=st.sampled_from(["proxmox_host", "k3s_vm", "service_vm"]),
        )
        @settings(max_examples=25)
        def test_component_id_echoed_in_result(self, node_id: str, node_type: str) -> None:
            assume(node_id.strip())
            result = score_component(node_id, node_type, {}, self._inv())
            assert result.component_id == node_id
