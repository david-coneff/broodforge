"""
test_phase23_federated_reconstruction.py — Phase 23: Federated Reconstruction Planning.

Covers:
  23.1  select_coordinator() — rank candidate coordinators
  23.2  build_phoenix_package_manifest()
  23.3  match_capabilities()
  23.4  build_federated_plan() — multi-phase reconstruction plan
  23.5  plan_trust_establishment()
  23.6  plan_workload_migration() — temporary migration plan
  23.7  FederatedReconstructionPlan properties (total_estimated_minutes)
"""



import federated_reconstruction as _fr
import federation_state as _fs

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _now():
    return "2026-06-01T12:00:00+00:00"


def _fed():
    fed = _fs.build_federation_state("fed-homelab", now_fn=_now)
    _fs.register_cell(fed, "pve01-cell", hostname="pve01",
                      capabilities=["k3s-server", "forgejo"], now_fn=_now)
    _fs.register_cell(fed, "pve02-cell", hostname="pve02",
                      capabilities=["k3s-worker", "pbs-datastore"], now_fn=_now)
    _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
    _fs.declare_recovery(fed, "pve01-cell", "pve02-cell",
                          backup_locations=[{"type": "restic", "path": "/backup/pve01"}],
                          now_fn=_now)
    return fed


class _FakeCapIndex:
    def __init__(self, data: dict):
        self._data = data
    def capabilities_of(self, cell_id: str) -> list[str]:
        return self._data.get(cell_id, [])
    def cells_with(self, cap_id: str) -> list[str]:
        return [c for c, caps in self._data.items() if cap_id in caps]


# ===========================================================================
# 23.1 — select_coordinator
# ===========================================================================

class TestSelectCoordinator:
    def test_returns_list(self):
        fed    = _fed()
        scores = _fr.select_coordinator("pve01-cell", fed)
        assert isinstance(scores, list)

    def test_excludes_subject_cell(self):
        fed    = _fed()
        scores = _fr.select_coordinator("pve01-cell", fed)
        ids    = [s.cell_id for s in scores]
        assert "pve01-cell" not in ids

    def test_pve02_is_candidate(self):
        fed    = _fed()
        scores = _fr.select_coordinator("pve01-cell", fed)
        ids    = [s.cell_id for s in scores]
        assert "pve02-cell" in ids

    def test_sorted_by_score_descending(self):
        fed    = _fed()
        scores = _fr.select_coordinator("pve01-cell", fed)
        if len(scores) >= 2:
            assert scores[0].score >= scores[1].score

    def test_recovery_rel_boosts_score(self):
        fed    = _fed()
        scores = _fr.select_coordinator("pve01-cell", fed)
        pve02  = next((s for s in scores if s.cell_id == "pve02-cell"), None)
        assert pve02 is not None
        assert pve02.score > 0

    def test_has_backups_when_declared(self):
        fed    = _fed()
        scores = _fr.select_coordinator("pve01-cell", fed)
        pve02  = next((s for s in scores if s.cell_id == "pve02-cell"), None)
        assert pve02 is not None
        assert pve02.has_backups is True

    def test_trust_valid_when_declared(self):
        fed    = _fed()
        scores = _fr.select_coordinator("pve01-cell", fed)
        pve02  = next((s for s in scores if s.cell_id == "pve02-cell"), None)
        assert pve02 is not None
        assert pve02.trust_valid is True

    def test_capability_overlap_boosts(self):
        fed    = _fed()
        cap_idx = _FakeCapIndex({
            "pve01-cell": ["k3s-server", "forgejo"],
            "pve02-cell": ["forgejo", "pbs-datastore"],  # overlap: forgejo
        })
        scores = _fr.select_coordinator("pve01-cell", fed, cap_idx)
        pve02  = next((s for s in scores if s.cell_id == "pve02-cell"), None)
        assert pve02 is not None
        # Score should include capability overlap bonus
        assert any("overlap" in r.lower() for r in pve02.reasons)


# ===========================================================================
# 23.2 — build_phoenix_package_manifest
# ===========================================================================

class TestPhoenixPackageManifest:
    def _build(self):
        fed     = _fed()
        rec_rel = fed.recovery_relationships[0]
        return _fr.build_phoenix_package_manifest(
            "pve01-cell", "pve02-cell", rec_rel, now_fn=_now,
        )

    def test_returns_manifest(self):
        m = self._build()
        assert isinstance(m, _fr.PhoenixPackageManifest)

    def test_subject_and_coordinator(self):
        m = self._build()
        assert m.subject_cell     == "pve01-cell"
        assert m.coordinator_cell == "pve02-cell"

    def test_package_id_set(self):
        m = self._build()
        assert m.package_id
        assert len(m.package_id) >= 8

    def test_contents_not_empty(self):
        m = self._build()
        assert len(m.contents) >= 4

    def test_includes_phoenix_playbook(self):
        m = self._build()
        types = {c["type"] for c in m.contents}
        assert "phoenix_playbook" in types

    def test_includes_trust_tokens(self):
        m = self._build()
        types = {c["type"] for c in m.contents}
        assert "trust_tokens" in types

    def test_backup_snapshots_included_when_locs(self):
        m = self._build()
        snap = next(c for c in m.contents if c["type"] == "backup_snapshots")
        assert snap["included"] is True


# ===========================================================================
# 23.3 — match_capabilities
# ===========================================================================

class TestMatchCapabilities:
    def _cap_idx(self):
        return _FakeCapIndex({
            "pve01-cell": ["k3s-server", "forgejo"],
            "pve02-cell": ["k3s-worker", "pbs-datastore", "forgejo"],
        })

    def test_match_available_cap(self):
        results = _fr.match_capabilities("pve01-cell", ["forgejo"], self._cap_idx())
        assert results[0].matched is True
        assert "pve02-cell" in results[0].available_cells

    def test_no_match_for_missing_cap(self):
        results = _fr.match_capabilities("pve01-cell", ["nonexistent-cap"], self._cap_idx())
        assert results[0].matched is False
        assert results[0].gap_reason is not None

    def test_excludes_subject_cell(self):
        results = _fr.match_capabilities("pve01-cell", ["forgejo"], self._cap_idx())
        assert "pve01-cell" not in results[0].available_cells

    def test_one_result_per_capability(self):
        caps    = ["forgejo", "pbs-datastore", "nonexistent"]
        results = _fr.match_capabilities("pve01-cell", caps, self._cap_idx())
        assert len(results) == 3

    def test_capability_id_preserved(self):
        results = _fr.match_capabilities("pve01-cell", ["k3s-worker"], self._cap_idx())
        assert results[0].capability_id == "k3s-worker"


# ===========================================================================
# 23.4 — build_federated_plan
# ===========================================================================

class TestBuildFederatedPlan:
    def _build(self):
        fed   = _fed()
        scores = _fr.select_coordinator("pve01-cell", fed)
        coord  = scores[0]
        return _fr.build_federated_plan("pve01-cell", coord, fed, now_fn=_now)

    def test_returns_plan(self):
        p = self._build()
        assert isinstance(p, _fr.FederatedReconstructionPlan)

    def test_phases_present(self):
        p = self._build()
        assert len(p.phases) >= 5

    def test_phase_numbers_sequential(self):
        p = self._build()
        nums = [ph.phase_number for ph in p.phases]
        assert nums == sorted(nums)

    def test_trust_phase_first(self):
        p = self._build()
        assert p.phases[0].phase_number == 0
        assert "Trust" in p.phases[0].name

    def test_federation_phase_last(self):
        p  = self._build()
        last = p.phases[-1]
        assert "Federation" in last.name or "Re-registration" in last.name

    def test_total_estimated_minutes_positive(self):
        p = self._build()
        assert p.total_estimated_minutes > 0

    def test_subject_and_coordinator_set(self):
        p = self._build()
        assert p.subject_cell     == "pve01-cell"
        assert p.coordinator_cell == "pve02-cell"

    def test_each_phase_has_steps(self):
        p = self._build()
        for ph in p.phases:
            assert len(ph.steps) > 0, f"Phase {ph.name} has no steps"


# ===========================================================================
# 23.5 — plan_trust_establishment
# ===========================================================================

class TestPlanTrustEstablishment:
    def test_returns_steps(self):
        fed   = _fed()
        steps = _fr.plan_trust_establishment("pve01-cell", "pve02-cell", fed)
        assert isinstance(steps, list)
        assert len(steps) >= 5

    def test_includes_headscale(self):
        fed   = _fed()
        steps = _fr.plan_trust_establishment("pve01-cell", "pve02-cell", fed)
        combined = " ".join(steps)
        assert "headscale" in combined.lower()

    def test_mentions_both_cells(self):
        fed   = _fed()
        steps = _fr.plan_trust_establishment("pve01-cell", "pve02-cell", fed)
        combined = " ".join(steps)
        assert "pve01-cell" in combined
        assert "pve02-cell" in combined


# ===========================================================================
# 23.6 — plan_workload_migration
# ===========================================================================

class TestPlanWorkloadMigration:
    def _build(self):
        return _fr.plan_workload_migration(
            "pve01-cell", "pve02-cell",
            ["forgejo", "assessment-engine"],
            now_fn=_now,
        )

    def test_returns_plan(self):
        p = self._build()
        assert isinstance(p, _fr.WorkloadMigrationPlan)

    def test_source_and_destination(self):
        p = self._build()
        assert p.source_cell      == "pve01-cell"
        assert p.destination_cell == "pve02-cell"

    def test_workloads_set(self):
        p = self._build()
        assert "forgejo" in p.workloads

    def test_has_steps(self):
        p = self._build()
        assert len(p.steps) >= 4

    def test_includes_drain_step(self):
        p = self._build()
        combined = " ".join(s.action for s in p.steps)
        assert "drain" in combined.lower()

    def test_includes_verify_step(self):
        p = self._build()
        combined = " ".join(s.action for s in p.steps)
        assert "verify" in combined.lower() or "health" in combined.lower()

    def test_estimated_minutes_set(self):
        p = self._build()
        assert p.estimated_minutes and p.estimated_minutes > 0

    def test_steps_sequential(self):
        p = self._build()
        nums = [s.step_number for s in p.steps]
        assert nums == sorted(nums)
