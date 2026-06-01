"""
test_phase19_federation.py — Phase 19: Federation State and Trust Model.

Covers:
  19.1  data-model/federation-state-schema.json
  19.2  CellRegistryEntry, register_cell(), federation registry
  19.3  TrustRelationship, declare_trust(), all trust types
  19.4  verify_trust() — expiry, reverification age, revocation
  19.5  RecoveryRelationship, declare_recovery()
  19.6  verify_recovery() — structural + probe-fn verification
  19.7  Tier3AssessmentEngine, score_federation_readiness()
        FederationReadinessReport, CellFederationScore
  19.8  federation_state_to_dict() + JSON round-trip
"""

import json
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "proxmox-bootstrap"))

import federation_state as _fs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _now():
    return "2026-06-01T12:00:00+00:00"


def _fed():
    """Build a two-cell federation for testing."""
    fed = _fs.build_federation_state("fed-homelab", federation_name="Home Lab Federation", now_fn=_now)
    _fs.register_cell(fed, "pve01-cell", hostname="pve01", domain="home.example.com",
                      fqdn="pve01.home.example.com", capabilities=["k3s-server", "forgejo"],
                      now_fn=_now)
    _fs.register_cell(fed, "pve02-cell", hostname="pve02", domain="home.example.com",
                      fqdn="pve02.home.example.com", capabilities=["k3s-worker", "pbs-datastore"],
                      now_fn=_now)
    return fed


# ===========================================================================
# 19.1 — schema
# ===========================================================================

class TestFederationStateSchema:
    def _schema(self):
        path = os.path.join(_ROOT, "data-model", "federation-state-schema.json")
        with open(path) as f:
            return json.load(f)

    def test_schema_loads(self):
        s = self._schema()
        assert s["title"] == "Federation State"

    def test_required_fields(self):
        s = self._schema()
        assert "federation_id" in s["required"]
        assert "declared_at" in s["required"]

    def test_trust_type_enum(self):
        s = self._schema()
        trust_defn = s["definitions"]["trust_relationship"]
        trust_enum = trust_defn["properties"]["relationship_type"]["enum"]
        assert "peer" in trust_enum
        assert "recovery" in trust_enum
        assert "backup-provider" in trust_enum
        assert "read-only" in trust_enum

    def test_validates_serialised_state(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")
        schema = self._schema()
        fed = _fed()
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        doc = _fs.federation_state_to_dict(fed)
        jsonschema.validate(doc, schema)


# ===========================================================================
# 19.2 — Cell registry
# ===========================================================================

class TestCellRegistry:
    def test_register_cell_adds_entry(self):
        fed = _fs.build_federation_state("f1", now_fn=_now)
        _fs.register_cell(fed, "cell-a", now_fn=_now)
        assert len(fed.cells) == 1

    def test_register_cell_idempotent(self):
        fed = _fs.build_federation_state("f1", now_fn=_now)
        _fs.register_cell(fed, "cell-a", hostname="pve01", now_fn=_now)
        _fs.register_cell(fed, "cell-a", hostname="pve01-updated", now_fn=_now)
        assert len(fed.cells) == 1
        assert fed.get_cell("cell-a").hostname == "pve01-updated"

    def test_register_two_cells(self):
        fed = _fed()
        assert len(fed.cells) == 2

    def test_get_cell(self):
        fed = _fed()
        cell = fed.get_cell("pve01-cell")
        assert cell is not None
        assert cell.hostname == "pve01"

    def test_get_cell_missing(self):
        fed = _fed()
        assert fed.get_cell("nonexistent") is None

    def test_cell_is_active(self):
        fed = _fed()
        assert fed.get_cell("pve01-cell").is_active

    def test_cell_capabilities(self):
        fed = _fed()
        caps = fed.get_cell("pve01-cell").capabilities
        assert "k3s-server" in caps

    def test_peers_of(self):
        fed = _fed()
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        peers = fed.peers_of("pve01-cell")
        assert "pve02-cell" in peers


# ===========================================================================
# 19.3 — Trust relationships
# ===========================================================================

class TestTrustRelationships:
    def test_declare_trust_adds_entry(self):
        fed = _fed()
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        assert len(fed.trust_relationships) == 1

    def test_declare_trust_idempotent(self):
        fed = _fed()
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        assert len(fed.trust_relationships) == 1

    def test_declare_trust_different_types(self):
        fed = _fed()
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_RECOVERY, now_fn=_now)
        assert len(fed.trust_relationships) == 2

    def test_all_trust_types(self):
        for t_type in _fs.ALL_TRUST_TYPES:
            fed = _fs.build_federation_state("f", now_fn=_now)
            _fs.register_cell(fed, "a", now_fn=_now)
            _fs.register_cell(fed, "b", now_fn=_now)
            t = _fs.declare_trust(fed, "a", "b", t_type, now_fn=_now)
            assert t.relationship_type == t_type

    def test_get_trust(self):
        fed = _fed()
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        trusts = fed.get_trust("pve01-cell", "pve02-cell")
        assert len(trusts) == 1

    def test_trust_relationship_id_deterministic(self):
        fed1 = _fed()
        fed2 = _fed()
        t1 = _fs.declare_trust(fed1, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        t2 = _fs.declare_trust(fed2, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        assert t1.relationship_id == t2.relationship_id

    def test_trust_expiry_date_set(self):
        fed = _fed()
        t = _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER,
                               expires_at="2027-06-01T00:00:00+00:00", now_fn=_now)
        assert t.expires_at == "2027-06-01T00:00:00+00:00"
        assert t.days_until_expiry > 0

    def test_trust_reverify_days(self):
        fed = _fed()
        t = _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER,
                               reverify_days=30, now_fn=_now)
        assert t.reverify_days == 30


# ===========================================================================
# 19.4 — verify_trust
# ===========================================================================

class TestVerifyTrust:
    def _make_trust(self, **kwargs) -> _fs.TrustRelationship:
        return _fs.TrustRelationship(
            relationship_id="test-rel",
            from_cell="a", to_cell="b",
            relationship_type=_fs.TRUST_PEER,
            declared_at=_now(),
            **kwargs,
        )

    def test_active_valid_trust(self):
        t   = self._make_trust()
        res = _fs.verify_trust(t, now_fn=_now)
        assert res.valid is True

    def test_revoked_trust_invalid(self):
        t   = self._make_trust(status="revoked")
        res = _fs.verify_trust(t, now_fn=_now)
        assert res.valid is False
        assert "revoked" in res.reason.lower()

    def test_expired_trust_invalid(self):
        t   = self._make_trust(expires_at="2020-01-01T00:00:00+00:00")
        res = _fs.verify_trust(t, now_fn=_now)
        assert res.valid is False
        assert "expired" in res.reason.lower()

    def test_future_expiry_valid(self):
        t   = self._make_trust(expires_at="2030-01-01T00:00:00+00:00")
        res = _fs.verify_trust(t, now_fn=_now)
        assert res.valid is True

    def test_overdue_reverification_invalid(self):
        # verified_at 200 days ago, reverify_days=90
        old = "2025-11-13T00:00:00+00:00"  # ~200 days before 2026-06-01
        t   = self._make_trust(reverify_days=90, verified_at=old)
        res = _fs.verify_trust(t, now_fn=_now)
        assert res.valid is False
        assert "re-verified" in res.reason.lower() or "verified" in res.reason.lower()

    def test_recent_verification_valid(self):
        recent = "2026-05-01T00:00:00+00:00"  # 31 days before _now
        t   = self._make_trust(reverify_days=90, verified_at=recent)
        res = _fs.verify_trust(t, now_fn=_now)
        assert res.valid is True

    def test_expiring_soon_still_valid(self):
        soon = "2026-06-08T00:00:00+00:00"  # 7 days from _now
        t   = self._make_trust(expires_at=soon)
        res = _fs.verify_trust(t, now_fn=_now)
        assert res.valid is True
        assert "soon" in res.reason.lower() or str(7) in res.reason


# ===========================================================================
# 19.5 — RecoveryRelationship
# ===========================================================================

class TestRecoveryRelationship:
    def test_declare_recovery_adds_entry(self):
        fed = _fed()
        _fs.declare_recovery(fed, "pve01-cell", "pve02-cell", now_fn=_now)
        assert len(fed.recovery_relationships) == 1

    def test_declare_recovery_idempotent(self):
        fed = _fed()
        _fs.declare_recovery(fed, "pve01-cell", "pve02-cell", now_fn=_now)
        _fs.declare_recovery(fed, "pve01-cell", "pve02-cell", now_fn=_now)
        assert len(fed.recovery_relationships) == 1

    def test_declare_recovery_with_backup_locations(self):
        fed = _fed()
        locs = [{"type": "restic", "remote": "b2:cell-backup", "path": "/pve01-cell/config/"}]
        r = _fs.declare_recovery(fed, "pve01-cell", "pve02-cell",
                                  backup_locations=locs, now_fn=_now)
        assert len(r.backup_locations) == 1
        assert r.backup_locations[0]["remote"] == "b2:cell-backup"

    def test_coordinators_for(self):
        fed = _fed()
        _fs.declare_recovery(fed, "pve01-cell", "pve02-cell", now_fn=_now)
        coords = fed.coordinators_for("pve01-cell")
        assert "pve02-cell" in coords

    def test_rto_rpo(self):
        fed = _fed()
        r = _fs.declare_recovery(fed, "pve01-cell", "pve02-cell",
                                   rto_minutes=60, rpo_hours=4, now_fn=_now)
        assert r.rto_minutes == 60
        assert r.rpo_hours == 4


# ===========================================================================
# 19.6 — verify_recovery
# ===========================================================================

class TestVerifyRecovery:
    def _make_recovery(self, **kwargs) -> _fs.RecoveryRelationship:
        return _fs.RecoveryRelationship(
            relationship_id="rec-01",
            subject_cell="pve01-cell",
            coordinator_cell="pve02-cell",
            declared_at=_now(),
            **kwargs,
        )

    def test_no_locations_not_reachable(self):
        r   = self._make_recovery(backup_locations=[])
        res = _fs.verify_recovery(r, now_fn=_now)
        assert res.reachable is False
        assert "no backup" in res.reason.lower()

    def test_unavailable_status(self):
        r   = self._make_recovery(status="unavailable", backup_locations=[{"type": "restic"}])
        res = _fs.verify_recovery(r, now_fn=_now)
        assert res.reachable is False

    def test_structural_check_passes_with_locations(self):
        locs = [{"type": "restic", "remote": "b2:backup", "path": "/cell/"}]
        r   = self._make_recovery(backup_locations=locs)
        res = _fs.verify_recovery(r, now_fn=_now)
        assert res.reachable is True
        assert "structural" in res.reason.lower()

    def test_probe_fn_all_reachable(self):
        locs = [{"type": "restic", "path": "/backup/cell-a"}]
        r   = self._make_recovery(backup_locations=locs)
        res = _fs.verify_recovery(r, probe_fn=lambda p: True, now_fn=_now)
        assert res.reachable is True

    def test_probe_fn_unreachable(self):
        locs = [{"type": "restic", "path": "/backup/cell-a"}]
        r   = self._make_recovery(backup_locations=locs)
        res = _fs.verify_recovery(r, probe_fn=lambda p: False, now_fn=_now)
        assert res.reachable is False
        assert "unreachable" in res.reason.lower()


# ===========================================================================
# 19.7 — score_federation_readiness + Tier3AssessmentEngine
# ===========================================================================

class TestScoreFederationReadiness:
    def test_empty_federation_red(self):
        fed = _fs.build_federation_state("f", now_fn=_now)
        report = _fs.score_federation_readiness(fed, now_fn=_now)
        assert report.overall_score == "RED"

    def test_no_coordinator_yellow(self):
        fed = _fed()
        report = _fs.score_federation_readiness(fed, now_fn=_now)
        # No coordinator declared → YELLOW
        assert report.overall_score in ("YELLOW", "ORANGE", "RED")

    def test_with_coordinator_green(self):
        fed = _fed()
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        _fs.declare_recovery(fed, "pve01-cell", "pve02-cell", now_fn=_now)
        _fs.declare_recovery(fed, "pve02-cell", "pve01-cell", now_fn=_now)
        report = _fs.score_federation_readiness(fed, now_fn=_now)
        assert report.overall_score == "GREEN"

    def test_per_cell_scores_present(self):
        fed = _fed()
        _fs.declare_recovery(fed, "pve01-cell", "pve02-cell", now_fn=_now)
        _fs.declare_recovery(fed, "pve02-cell", "pve01-cell", now_fn=_now)
        report = _fs.score_federation_readiness(fed, now_fn=_now)
        ids = {s.cell_id for s in report.cell_scores}
        assert "pve01-cell" in ids
        assert "pve02-cell" in ids

    def test_total_and_active_cells(self):
        fed = _fed()
        report = _fs.score_federation_readiness(fed, now_fn=_now)
        assert report.total_cells == 2
        assert report.active_cells == 2


class TestTier3AssessmentEngine:
    def _engine(self):
        fed = _fed()
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        _fs.declare_recovery(fed, "pve01-cell", "pve02-cell", now_fn=_now)
        _fs.declare_recovery(fed, "pve02-cell", "pve01-cell", now_fn=_now)
        return _fs.Tier3AssessmentEngine(fed, now_fn=_now)

    def test_returns_result(self):
        result = self._engine().assess()
        assert isinstance(result, _fs.Tier3AssessmentResult)

    def test_assessed_at_set(self):
        result = self._engine().assess()
        assert result.assessed_at == _now()

    def test_federation_score(self):
        result = self._engine().assess()
        assert result.federation_score in ("GREEN", "YELLOW", "ORANGE", "RED")

    def test_trust_expiry_warning(self):
        fed = _fed()
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER,
                          expires_at="2026-06-08T00:00:00+00:00",  # 7 days from _now
                          now_fn=_now)
        _fs.declare_recovery(fed, "pve01-cell", "pve02-cell", now_fn=_now)
        _fs.declare_recovery(fed, "pve02-cell", "pve01-cell", now_fn=_now)
        engine = _fs.Tier3AssessmentEngine(fed, now_fn=_now)
        result = engine.assess()
        categories = {f["category"] for f in result.findings}
        assert "trust_expiry" in categories

    def test_expired_trust_red_finding(self):
        fed = _fed()
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER,
                          expires_at="2020-01-01T00:00:00+00:00",  # past
                          now_fn=_now)
        engine = _fs.Tier3AssessmentEngine(fed, now_fn=_now)
        result = engine.assess()
        red_findings = [f for f in result.findings if f["severity"] == "RED"]
        assert len(red_findings) >= 1

    def test_capability_spof_warning(self):
        fed = _fed()
        _fs.declare_recovery(fed, "pve01-cell", "pve02-cell", now_fn=_now)
        _fs.declare_recovery(fed, "pve02-cell", "pve01-cell", now_fn=_now)
        cap_states = {
            "pve01-cell": {"capabilities": [{"id": "forgejo", "status": "active"}]},
            "pve02-cell": {"capabilities": [{"id": "k3s-worker", "status": "active"}]},
        }
        engine = _fs.Tier3AssessmentEngine(fed, cell_cap_states=cap_states, now_fn=_now)
        result = engine.assess()
        spof = [f for f in result.findings if f["category"] == "capability_spof"]
        assert len(spof) >= 1


# ===========================================================================
# 19.8 — federation_state_to_dict + JSON round-trip
# ===========================================================================

class TestFederationStateSerialization:
    def test_to_dict_structure(self):
        fed = _fed()
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        _fs.declare_recovery(fed, "pve01-cell", "pve02-cell", now_fn=_now)
        d = _fs.federation_state_to_dict(fed)
        assert d["schema_version"] == "1.0"
        assert d["federation_id"] == "fed-homelab"
        assert isinstance(d["cells"], list)
        assert isinstance(d["trust_relationships"], list)
        assert isinstance(d["recovery_relationships"], list)

    def test_cells_in_dict(self):
        fed = _fed()
        d = _fs.federation_state_to_dict(fed)
        cell_ids = {c["cell_id"] for c in d["cells"]}
        assert "pve01-cell" in cell_ids
        assert "pve02-cell" in cell_ids

    def test_json_roundtrip(self):
        fed = _fed()
        _fs.declare_trust(fed, "pve01-cell", "pve02-cell", _fs.TRUST_PEER, now_fn=_now)
        _fs.declare_recovery(fed, "pve01-cell", "pve02-cell", now_fn=_now)
        d = _fs.federation_state_to_dict(fed)
        loaded = json.loads(json.dumps(d))
        assert loaded["federation_id"] == "fed-homelab"
        assert len(loaded["trust_relationships"]) == 1
        assert len(loaded["recovery_relationships"]) == 1
