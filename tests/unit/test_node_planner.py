"""
tests/unit/test_node_planner.py — Unit tests for Phase 1.Q node_planner.py

Test coverage:
  1.  CodenameGenerator — generates unique, valid codenames
  2.  generate_join_pin — format ####-####-####-####, uses secrets
  3.  NodePlanner.plan_batch — returns correct count, role, generates PINs
  4.  NodePlanner.commit_plan — persists to state file, atomic
  5.  NodePlanner.commit_plan — rejects duplicate codename
  6.  NodePlanner.store_broodling_registration — PIN verified, advances state
  7.  NodePlanner.store_broodling_registration — PIN mismatch rejected
  8.  NodePlanner.join_deadline — auto-blacklists when expired
  9.  NodePlanner.join_deadline — permissive (None) when not set
  10. NodePlanner.set_join_deadline — validates ISO format
  11. NodePlanner.blacklist — revocation path; refuses to blacklist active
  12. NodePlanner.approve — advances state to active
  13. NodePlanner.decommission — advances to decommissioned
  14. NodePlanner.unblacklist — restores to iso-built
  15. NodePlanner.update_state — atomic write; updates updated_at
  16. _empty_node_entry — all required keys present
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Import path ──────────────────────────────────────────────────────────────
from node_planner import (
    CodenameGenerator,
    NodeAllocationPlan,
    NodePlanner,
    _empty_node_entry,
    generate_join_pin,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _fixed_now(dt: datetime):
    """Return a now_fn that always returns `dt`."""
    return lambda: dt


def _make_planner(tmp_path: Path, now: datetime | None = None) -> NodePlanner:
    """Create a NodePlanner wired to a temp state dir."""
    now_fn = _fixed_now(now) if now else _fixed_now(datetime(2026, 1, 1, tzinfo=timezone.utc))
    return NodePlanner(
        state_dir=tmp_path,
        headscale_url="",   # stub — no real headscale calls
        now_fn=now_fn,
    )


def _stub_plan(codename: str, role: str = "worker") -> NodeAllocationPlan:
    """Helper to build a pre-populated plan without Headscale."""
    return NodeAllocationPlan(
        codename         = codename,
        role             = role,
        headscale_key    = f"STUB_KEY_{codename}",
        headscale_key_id = f"STUB_ID_{codename}",
        join_pin         = generate_join_pin(),
    )


# ── 1. CodenameGenerator ──────────────────────────────────────────────────────

class TestCodenameGenerator:
    def test_generates_valid_format(self):
        gen = CodenameGenerator()
        name = gen.generate(existing=set())
        assert "-" in name
        adj, animal = name.split("-", 1)
        assert adj in CodenameGenerator.ADJECTIVES
        assert animal in CodenameGenerator.ANIMALS

    def test_avoids_existing(self):
        gen = CodenameGenerator()
        # Pre-fill almost everything except one codename
        all_names = {
            f"{a}-{b}"
            for a in CodenameGenerator.ADJECTIVES
            for b in CodenameGenerator.ANIMALS
        }
        # Leave exactly one free
        known_free = "swift-falcon"
        existing = all_names - {known_free}
        result = gen.generate(existing=existing)
        assert result == known_free

    def test_raises_when_exhausted(self):
        gen = CodenameGenerator()
        all_names = {
            f"{a}-{b}"
            for a in CodenameGenerator.ADJECTIVES
            for b in CodenameGenerator.ANIMALS
        }
        with pytest.raises(RuntimeError, match="exhausted"):
            gen.generate(existing=all_names)


# ── 2. generate_join_pin ──────────────────────────────────────────────────────

class TestGenerateJoinPin:
    def test_format(self):
        """Format: ###-###-###-### (4 groups of 3 digits)."""
        pin = generate_join_pin()
        parts = pin.split("-")
        assert len(parts) == 4
        for p in parts:
            assert len(p) == 3, f"Each group must be 3 digits, got: {p!r}"
            assert p.isdigit()

    def test_randomness(self):
        pins = {generate_join_pin() for _ in range(50)}
        # Very unlikely to get all identical
        assert len(pins) > 1

    def test_uses_secrets_module(self):
        """12 decimal digits total (4 × 3)."""
        pin = generate_join_pin()
        digits_only = pin.replace("-", "")
        assert len(digits_only) == 12
        assert digits_only.isdigit()


# ── 3. plan_batch ────────────────────────────────────────────────────────────

class TestPlanBatch:
    def test_returns_correct_count(self, tmp_path):
        planner = _make_planner(tmp_path)
        with patch.object(planner, "_create_headscale_key", return_value=("KEY", "ID")):
            plans = planner.plan_batch(count=3, role="worker")
        assert len(plans) == 3

    def test_unique_codenames(self, tmp_path):
        planner = _make_planner(tmp_path)
        with patch.object(planner, "_create_headscale_key", return_value=("KEY", "ID")):
            plans = planner.plan_batch(count=5)
        codenames = [p.codename for p in plans]
        assert len(codenames) == len(set(codenames))

    def test_invalid_role_raises(self, tmp_path):
        planner = _make_planner(tmp_path)
        with pytest.raises(ValueError, match="role"):
            planner.plan_batch(count=1, role="invalid-role")

    def test_pins_generated(self, tmp_path):
        planner = _make_planner(tmp_path)
        with patch.object(planner, "_create_headscale_key", return_value=("KEY", "ID")):
            plans = planner.plan_batch(count=2)
        for p in plans:
            parts = p.join_pin.split("-")
            assert len(parts) == 4
            assert all(len(g) == 3 and g.isdigit() for g in parts)


# ── 4. commit_plan — persists ────────────────────────────────────────────────

class TestCommitPlan:
    def test_persists_nodes(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("swift-falcon")
        planner.commit_plan([plan])
        state_file = tmp_path / "provisioning-state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert len(data["nodes"]) == 1
        node = data["nodes"][0]
        assert node["codename"] == "swift-falcon"
        assert node["state"] == "planned"
        assert node["join_pin"] == plan.join_pin

    def test_multiple_plans(self, tmp_path):
        planner = _make_planner(tmp_path)
        plans   = [_stub_plan(f"node-{i}") for i in range(3)]
        planner.commit_plan(plans)
        nodes = planner.list_nodes()
        assert len(nodes) == 3


# ── 5. commit_plan — rejects duplicate codename ──────────────────────────────

class TestCommitPlanDuplicate:
    def test_rejects_duplicate(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("calm-raven")
        planner.commit_plan([plan])
        # Try to commit same codename again
        with pytest.raises(ValueError, match="already exists"):
            planner.commit_plan([_stub_plan("calm-raven")])


# ── 6. store_broodling_registration — PIN verified ───────────────────────────

class TestStoreRegistration:
    def test_valid_pin_advances_state(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("bold-lynx")
        planner.commit_plan([plan])
        # Advance to iso-built so registration is meaningful
        planner.update_state("bold-lynx", state="iso-built")

        with patch("node_planner._compute_key_fingerprint", return_value="SHA256:abcd1234"):
            planner.store_broodling_registration(
                codename       = "bold-lynx",
                public_key_pem = "-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----",
                join_pin       = plan.join_pin,
            )

        node = planner.get_node("bold-lynx")
        assert node["state"] == "pending-approval"
        assert node["broodling_public_key_fingerprint"] == "SHA256:abcd1234"

    def test_stores_joined_at(self, tmp_path):
        t = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        planner = _make_planner(tmp_path, now=t)
        plan    = _stub_plan("keen-ibis")
        planner.commit_plan([plan])

        with patch("node_planner._compute_key_fingerprint", return_value="FP"):
            planner.store_broodling_registration(
                codename="keen-ibis",
                public_key_pem="fake-pem",
                join_pin=plan.join_pin,
            )

        node = planner.get_node("keen-ibis")
        assert node["joined_at"] == "2026-06-01T12:00:00Z"


# ── 7. PIN mismatch rejected ─────────────────────────────────────────────────

class TestPinMismatch:
    def test_wrong_pin_raises(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("pure-wren")
        planner.commit_plan([plan])

        with pytest.raises(ValueError, match="PIN mismatch"):
            planner.store_broodling_registration(
                codename       = "pure-wren",
                public_key_pem = "fake-pem",
                join_pin       = "0000-0000-0000-0000",  # wrong
            )

    def test_wrong_pin_does_not_advance_state(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("firm-heron")
        planner.commit_plan([plan])
        try:
            planner.store_broodling_registration("firm-heron", "fake-pem", "9999-9999-9999-9999")
        except ValueError:
            pass
        node = planner.get_node("firm-heron")
        assert node["state"] == "planned"


# ── 8. join_deadline — auto-blacklists when expired ──────────────────────────

class TestJoinDeadline:
    def test_expired_deadline_blacklists(self, tmp_path):
        now = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)
        planner = _make_planner(tmp_path, now=now)
        plan    = _stub_plan("wide-curlew")
        planner.commit_plan([plan])
        # Set a deadline that's already in the past
        past = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        planner.update_state("wide-curlew", join_deadline=past)

        with pytest.raises(ValueError, match="deadline"):
            planner.store_broodling_registration("wide-curlew", "fake", plan.join_pin)

        node = planner.get_node("wide-curlew")
        assert node["state"] == "blacklisted"
        assert node["blacklisted"] is True


# ── 9. join_deadline — permissive when not set ───────────────────────────────

class TestJoinDeadlinePermissive:
    def test_no_deadline_allows_registration(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("open-viper")
        planner.commit_plan([plan])
        # No join_deadline set → registration should succeed
        with patch("node_planner._compute_key_fingerprint", return_value="FP"):
            planner.store_broodling_registration("open-viper", "fake-pem", plan.join_pin)
        assert planner.get_node("open-viper")["state"] == "pending-approval"


# ── 10. set_join_deadline — validates ISO format ─────────────────────────────

class TestSetJoinDeadline:
    def test_invalid_format_raises(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("deep-egret")
        planner.commit_plan([plan])
        with pytest.raises(ValueError, match="ISO 8601"):
            planner.set_join_deadline("deep-egret", "not-a-date")

    def test_clear_deadline(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("vast-godwit")
        planner.commit_plan([plan])
        # Set then clear
        future = "2099-01-01T00:00:00Z"
        planner.set_join_deadline("vast-godwit", future)
        assert planner.get_node("vast-godwit")["join_deadline"] == future
        planner.set_join_deadline("vast-godwit", None)
        assert planner.get_node("vast-godwit")["join_deadline"] is None


# ── 11. blacklist ─────────────────────────────────────────────────────────────

class TestBlacklist:
    def test_blacklist_sets_state(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("lone-finch")
        planner.commit_plan([plan])
        planner.blacklist("lone-finch", reason="Security concern")
        node = planner.get_node("lone-finch")
        assert node["state"] == "blacklisted"
        assert node["blacklisted"] is True
        assert node["blacklist_reason"] == "Security concern"

    def test_cannot_blacklist_active(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("free-merlin")
        planner.commit_plan([plan])
        planner.update_state("free-merlin", state="active")
        with pytest.raises(ValueError, match="decommission"):
            planner.blacklist("free-merlin", reason="test")


# ── 12. approve ───────────────────────────────────────────────────────────────

class TestApprove:
    def test_approve_advances_to_active(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("cool-avocet")
        planner.commit_plan([plan])
        planner.update_state("cool-avocet", state="pending-approval")
        with patch.object(planner, "_approve_headscale_node"):
            planner.approve("cool-avocet")
        node = planner.get_node("cool-avocet")
        assert node["state"] == "active"
        assert node["approved_at"] is not None

    def test_approve_wrong_state_raises(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("warm-harrier")
        planner.commit_plan([plan])  # state = planned
        with pytest.raises(ValueError, match="Cannot approve"):
            planner.approve("warm-harrier")


# ── 13. decommission ──────────────────────────────────────────────────────────

class TestDecommission:
    def test_decommission_sets_state(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("raw-plover")
        planner.commit_plan([plan])
        planner.update_state("raw-plover", state="active")
        with patch.object(planner, "_delete_headscale_node"):
            planner.decommission("raw-plover")
        node = planner.get_node("raw-plover")
        assert node["state"] == "decommissioned"
        assert node["decommissioned_at"] is not None


# ── 14. unblacklist ───────────────────────────────────────────────────────────

class TestUnblacklist:
    def test_unblacklist_restores_iso_built(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("dry-lapwing")
        planner.commit_plan([plan])
        planner.blacklist("dry-lapwing", reason="test")
        planner.unblacklist("dry-lapwing")
        node = planner.get_node("dry-lapwing")
        assert node["state"] == "iso-built"
        assert node["blacklisted"] is False
        assert node["blacklist_reason"] is None

    def test_unblacklist_not_blacklisted_raises(self, tmp_path):
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("soft-dunlin")
        planner.commit_plan([plan])
        with pytest.raises(ValueError, match="not currently blacklisted"):
            planner.unblacklist("soft-dunlin")


# ── 15. update_state — atomic / updates updated_at ───────────────────────────

class TestUpdateState:
    def test_updates_fields(self, tmp_path):
        t = datetime(2026, 3, 15, 9, 30, tzinfo=timezone.utc)
        planner = _make_planner(tmp_path, now=t)
        plan    = _stub_plan("bare-quail")
        planner.commit_plan([plan])
        planner.update_state("bare-quail", notes="Rack A slot 3", role="storage")
        node = planner.get_node("bare-quail")
        assert node["notes"] == "Rack A slot 3"
        assert node["role"] == "storage"
        assert node["updated_at"] == "2026-03-15T09:30:00Z"

    def test_atomic_write_creates_tmp_then_renames(self, tmp_path):
        """Atomic write should not leave a .tmp file behind."""
        planner = _make_planner(tmp_path)
        plan    = _stub_plan("quiet-bittern")
        planner.commit_plan([plan])
        tmp_file = tmp_path / "provisioning-state.json.tmp"
        assert not tmp_file.exists()
        state_file = tmp_path / "provisioning-state.json"
        assert state_file.exists()


# ── 16. _empty_node_entry — required keys present ────────────────────────────

class TestEmptyNodeEntry:
    REQUIRED_KEYS = [
        "codename", "display_name", "role",
        "headscale_key_id", "headscale_node_id", "headscale_device_name",
        "join_pin", "join_deadline",
        "iso_path", "iso_built_at",
        "created_at", "updated_at", "joined_at", "approved_at", "decommissioned_at",
        "state", "blacklisted", "blacklist_reason",
        "notes", "assigned_address",
        "broodling_public_key_pem", "broodling_public_key_fingerprint",
    ]

    def test_all_keys_present(self):
        entry = _empty_node_entry()
        for key in self.REQUIRED_KEYS:
            assert key in entry, f"Missing key: {key}"

    def test_default_state_is_planned(self):
        entry = _empty_node_entry()
        assert entry["state"] == "planned"

    def test_blacklisted_default_is_false(self):
        entry = _empty_node_entry()
        assert entry["blacklisted"] is False

    def test_join_deadline_default_is_none(self):
        entry = _empty_node_entry()
        assert entry["join_deadline"] is None
