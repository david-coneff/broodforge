"""
test_vault_hierarchy.py — Tests for Phase 1.K (AD-061):
  _vault_hierarchy.py          — derived-vault plan / user-provisioning builder
  html_package_manifest.py     — build_scoped_vault_plan_html (AD-051 twin)
  role-scope-registry.yaml     — registry loading from the real template file
"""

import json
import os
from pathlib import Path

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

import _vault_hierarchy as _vh
import html_package_manifest as _hpm

_PB_DIR = Path(_ROOT) / "proxmox-bootstrap"


# ---------------------------------------------------------------------------
# Fixtures — synthetic secret-registry-shaped entries
# ---------------------------------------------------------------------------

def _secret_entries():
    return [
        {
            "id": "pve01-root-password",
            "description": "Proxmox host root password",
            "keepass_path": "Infrastructure/proxmox/pve01-root",
            "owning_cell": "proxmox-cell-a",
            "secret_type": "password",
            "required_by": ["host:pve01"],
            "required_for": ["ssh-access", "pve-api-auth"],
            "rotation_schedule": "annually",
        },
        {
            "id": "pve01-api-token",
            "description": "Proxmox API token for OpenTofu provider",
            "keepass_path": "Infrastructure/proxmox/pve01-tofu-token",
            "owning_cell": "proxmox-cell-a",
            "secret_type": "api-token",
            "required_by": ["host:pve01"],
            "required_for": ["opentofu-execution"],
            "rotation_schedule": "annually",
        },
        {
            "id": "infra-bootstrap-deploy-key",
            "description": "SSH deploy key for infra-bootstrap VM",
            "keepass_path": "Infrastructure/ssh/deploy-keys/infra-bootstrap",
            "owning_cell": "proxmox-cell-a",
            "secret_type": "ssh-private-key",
            "required_by": ["vm:infra-bootstrap"],
            "required_for": ["ansible-execution"],
            "rotation_schedule": None,
        },
        {
            "id": "vm-100-password",
            "description": "Initial OS user password for infra-bootstrap VM",
            "keepass_path": "Infrastructure/vms/vm-100-ubuntu-password",
            "owning_cell": "proxmox-cell-a",
            "secret_type": "password",
            "required_by": ["vm:infra-bootstrap"],
            "required_for": ["first-boot-access"],
            "rotation_schedule": None,
        },
        {
            "id": "external-cloudflare-token",
            "description": "Cloudflare API token",
            "keepass_path": "External/cloudflare/api-token",
            "owning_cell": "other-cell",
            "secret_type": "api-token",
            "required_by": ["service:cloudflare-ddns"],
            "required_for": ["dns-01"],
            "rotation_schedule": "annually",
        },
    ]


def _service_operator_role():
    return {
        "role": "service-operator",
        "description": "Operates a single VM/service.",
        "tier": "service-operator",
        "scope": {
            "required_by": ["vm:infra-bootstrap"],
            "secret_type": ["ssh-private-key", "password"],
        },
        "excludes": ["pve01-*"],
        "holders": ["alice"],
    }


def _node_sysadmin_role():
    return {
        "role": "node-sysadmin",
        "description": "Administers Proxmox hosts and their VMs.",
        "tier": "node-sysadmin",
        "scope": {
            "required_by": ["host:*", "vm:*"],
            "owning_cell": ["proxmox-cell-a"],
        },
        "excludes": [],
        "holders": ["bob"],
    }


def _god_mode_role():
    return {
        "role": "god-mode",
        "description": "Full undivided access.",
        "tier": "god-mode",
        "scope": {},
        "excludes": [],
        "holders": ["operator"],
    }


def _fixed_now_fn():
    return "2026-06-08T12:00:00+00:00"


# ===========================================================================
# Registry loading
# ===========================================================================

class TestRegistryLoading:
    def test_loads_real_role_scope_registry(self):
        path = _PB_DIR / "role-scope-registry.yaml"
        assert path.exists()
        roles = _vh.load_role_scope_registry(str(path))
        assert len(roles) == 3
        names = {r.get("role") for r in roles}
        assert names == {"service-operator", "node-sysadmin", "god-mode"}

    def test_loads_real_secret_registry(self):
        path = _PB_DIR / "secret-registry.yaml"
        assert path.exists()
        entries = _vh.load_secret_registry(str(path))
        assert len(entries) >= 8
        assert all("id" in e and "keepass_path" in e for e in entries)

    def test_role_scope_from_dict(self):
        scope = _vh.role_scope_from_dict(_service_operator_role())
        assert scope.role == "service-operator"
        assert scope.tier == "service-operator"
        assert scope.required_by == ["vm:infra-bootstrap"]
        assert scope.secret_type == ["ssh-private-key", "password"]
        assert scope.excludes == ["pve01-*"]
        assert scope.holders == ["alice"]

    def test_role_scope_from_dict_defaults(self):
        scope = _vh.role_scope_from_dict({"role": "bare"})
        assert scope.role == "bare"
        assert scope.required_by == []
        assert scope.holders == []
        assert scope.tier == "service-operator"


# ===========================================================================
# Glob-scope matching
# ===========================================================================

class TestScopeMatching:
    def test_required_by_glob_matches(self):
        scope = _vh.role_scope_from_dict(_service_operator_role())
        entries = _secret_entries()
        matched = _vh.select_scoped_entries(scope, entries)
        ids = {e["id"] for e in matched}
        assert "infra-bootstrap-deploy-key" in ids
        assert "vm-100-password" in ids
        assert "pve01-root-password" not in ids
        assert "external-cloudflare-token" not in ids

    def test_excludes_drops_matching_id(self):
        scope = _vh.RoleScope(
            role="broad", required_by=["*"], excludes=["pve01-*"],
        )
        entries = _secret_entries()
        matched = _vh.select_scoped_entries(scope, entries)
        ids = {e["id"] for e in matched}
        assert "pve01-root-password" not in ids
        assert "pve01-api-token" not in ids
        assert "infra-bootstrap-deploy-key" in ids

    def test_owning_cell_glob(self):
        scope = _vh.RoleScope(role="cell-scoped", owning_cell=["proxmox-cell-a"])
        matched = _vh.select_scoped_entries(scope, _secret_entries())
        ids = {e["id"] for e in matched}
        assert "external-cloudflare-token" not in ids
        assert "pve01-root-password" in ids

    def test_secret_type_glob(self):
        scope = _vh.RoleScope(role="ssh-only", secret_type=["ssh-private-key"])
        matched = _vh.select_scoped_entries(scope, _secret_entries())
        ids = {e["id"] for e in matched}
        assert ids == {"infra-bootstrap-deploy-key"}

    def test_required_for_glob(self):
        scope = _vh.RoleScope(role="dns-ops", required_for=["dns-*"])
        matched = _vh.select_scoped_entries(scope, _secret_entries())
        ids = {e["id"] for e in matched}
        assert ids == {"external-cloudflare-token"}

    def test_union_not_intersection(self):
        scope = _vh.RoleScope(
            role="union-test",
            required_by=["service:*"],
            secret_type=["password"],
        )
        matched = _vh.select_scoped_entries(scope, _secret_entries())
        ids = {e["id"] for e in matched}
        # service:* matches the cloudflare entry; secret_type=password matches
        # the two password entries — union of both facets, not intersection.
        assert "external-cloudflare-token" in ids
        assert "pve01-root-password" in ids
        assert "vm-100-password" in ids

    def test_empty_scope_matches_nothing(self):
        scope = _vh.role_scope_from_dict(_god_mode_role())
        matched = _vh.select_scoped_entries(scope, _secret_entries())
        assert matched == []

    def test_glob_wildcards(self):
        scope = _vh.RoleScope(role="hosts", required_by=["host:*"])
        matched = _vh.select_scoped_entries(scope, _secret_entries())
        ids = {e["id"] for e in matched}
        assert ids == {"pve01-root-password", "pve01-api-token"}


# ===========================================================================
# Vault-of-vaults recordkeeping path
# ===========================================================================

class TestVaultRecordPath:
    def test_path_shape(self):
        path = _vh.vault_record_path("service-operator", "2026-06-08_12_00_00")
        assert path == "Vaults/service-operator/2026-06-08_12_00_00/passphrase"

    def test_path_uses_role_and_timestamp(self):
        path = _vh.vault_record_path("node-sysadmin", "TS")
        assert path.startswith("Vaults/node-sysadmin/TS/")
        assert path.endswith("/passphrase")


# ===========================================================================
# Plan composition
# ===========================================================================

class TestBuildDerivedVaultPlan:
    def test_basic_plan_shape(self):
        plan = _vh.build_derived_vault_plan(
            _service_operator_role(), _secret_entries(),
            now_fn=_fixed_now_fn,
            passphrase="Test.fixed.phrase.1", passphrase_source="test-fixed",
        )
        assert plan.role == "service-operator"
        assert plan.tier == "service-operator"
        assert plan.passphrase == "Test.fixed.phrase.1"
        assert plan.passphrase_source == "test-fixed"
        assert plan.generated_at == "2026-06-08T12:00:00+00:00"
        assert plan.holders == ["alice"]

    def test_in_scope_filtering_correctness(self):
        plan = _vh.build_derived_vault_plan(
            _service_operator_role(), _secret_entries(),
            now_fn=_fixed_now_fn, passphrase="x", passphrase_source="t",
        )
        ids = {e["id"] for e in plan.entries}
        assert ids == {"infra-bootstrap-deploy-key", "vm-100-password"}
        assert plan.total_registry_count == 5
        assert plan.excluded_count == 5 - len(plan.entries)

    def test_record_path_uses_timestamp_from_generated_at(self):
        plan = _vh.build_derived_vault_plan(
            _service_operator_role(), _secret_entries(),
            now_fn=_fixed_now_fn, passphrase="x", passphrase_source="t",
        )
        assert plan.parent_record_path == "Vaults/service-operator/2026-06-08_12_00_00/passphrase"

    def test_passphrase_generated_when_not_supplied(self):
        plan = _vh.build_derived_vault_plan(
            _service_operator_role(), _secret_entries(), now_fn=_fixed_now_fn,
        )
        assert isinstance(plan.passphrase, str) and len(plan.passphrase) > 0
        assert plan.passphrase_source in ("keepassxc-cli", "eff", "secrets", "unavailable")

    def test_god_mode_tier_refused(self):
        with pytest.raises(ValueError, match="god-mode"):
            _vh.build_derived_vault_plan(_god_mode_role(), _secret_entries())

    def test_db_paths(self):
        plan = _vh.build_derived_vault_plan(
            _node_sysadmin_role(), _secret_entries(),
            parent_db_path="/etc/broodforge/keepass.kdbx",
            derived_db_dir="/etc/broodforge/vaults",
            now_fn=_fixed_now_fn, passphrase="x", passphrase_source="t",
        )
        assert plan.db_path == "/etc/broodforge/vaults/node-sysadmin.kdbx"
        assert plan.parent_db_path == "/etc/broodforge/keepass.kdbx"

    def test_supplied_passphrase_marks_operator_supplied_source(self):
        plan = _vh.build_derived_vault_plan(
            _service_operator_role(), _secret_entries(),
            now_fn=_fixed_now_fn, passphrase="Custom.pass.1",
        )
        assert plan.passphrase == "Custom.pass.1"
        assert plan.passphrase_source == "operator-supplied"


# ===========================================================================
# Command-string generation
# ===========================================================================

class TestRenderDeriveVaultCommands:
    def _plan(self):
        return _vh.build_derived_vault_plan(
            _service_operator_role(), _secret_entries(),
            now_fn=_fixed_now_fn, passphrase="Test.pass.1", passphrase_source="t",
        )

    def test_commands_are_strings(self):
        cmds = _vh.render_derive_vault_commands(self._plan())
        assert all(isinstance(c, str) for c in cmds)
        assert len(cmds) > 5

    def test_commands_create_db_and_entries(self):
        cmds = "\n".join(_vh.render_derive_vault_commands(self._plan()))
        assert "keepassxc-cli db-create" in cmds
        assert "DERIVED_VAULT_PASSWORD" in cmds
        assert "/etc/broodforge/vaults/service-operator.kdbx" in cmds
        assert "Infrastructure/ssh/deploy-keys/infra-bootstrap" in cmds
        assert "Infrastructure/vms/vm-100-ubuntu-password" in cmds

    def test_commands_record_passphrase_in_parent(self):
        cmds = "\n".join(_vh.render_derive_vault_commands(self._plan()))
        assert "KEEPASS_MASTER_PASSWORD" in cmds
        assert "/etc/broodforge/keepass.kdbx" in cmds
        assert "Vaults/service-operator/2026-06-08_12_00_00/passphrase" in cmds

    def test_no_plaintext_passphrase_in_commands(self):
        cmds = "\n".join(_vh.render_derive_vault_commands(self._plan()))
        assert "Test.pass.1" not in cmds

    def test_describe_vault_plan_includes_design_statements(self):
        text = _vh.describe_vault_plan(self._plan())
        assert "Authorization model" in text
        assert "Revocation = rotate" in text
        assert "Test.pass.1" in text  # shown-once summary DOES include it
        assert "SHOWN ONCE" in text


# ===========================================================================
# User-provisioning templates
# ===========================================================================

class TestVmAccountTemplate:
    def test_generates_account_block(self):
        plan = _vh.build_derived_vault_plan(
            _service_operator_role(), _secret_entries(),
            now_fn=_fixed_now_fn, passphrase="x", passphrase_source="t",
        )
        acct = _vh.generate_vm_account_template(_service_operator_role(), plan)
        assert acct["name"] == "service-operator"
        assert acct["tier"] == "service-operator"
        assert "docker" in acct["groups"]
        assert acct["sudo"] is None
        assert "service-operator.kdbx" in acct["ssh_key_reference"]
        assert "name: 'service-operator'" in acct["yaml_block"]
        assert "groups: [docker]" in acct["yaml_block"]
        assert "sudo: false" in acct["yaml_block"]

    def test_node_sysadmin_gets_sudo(self):
        acct = _vh.generate_vm_account_template(_node_sysadmin_role())
        assert "sudo" in acct["groups"]
        assert acct["sudo"] == "ALL=(ALL) NOPASSWD:ALL"
        assert "sudo: ALL=(ALL) NOPASSWD:ALL" in acct["yaml_block"]

    def test_works_without_plan(self):
        acct = _vh.generate_vm_account_template(_service_operator_role())
        assert acct["scoped_vault_path"].endswith("service-operator.kdbx")


class TestProxmoxAccountCommands:
    def test_generates_pveum_sequence(self):
        cmds = _vh.generate_proxmox_account_commands(_node_sysadmin_role())
        joined = "\n".join(cmds)
        assert "pveum user add node-sysadmin@pve" in joined
        assert "pveum aclmod" in joined
        assert "PVEAdmin" in joined
        assert "pveum user token add" in joined

    def test_service_operator_gets_narrower_role(self):
        cmds = "\n".join(_vh.generate_proxmox_account_commands(_service_operator_role()))
        assert "PVEVMUser" in cmds

    def test_no_live_api_calls(self):
        """These are command strings for an operator to run — never executed."""
        cmds = _vh.generate_proxmox_account_commands(_node_sysadmin_role())
        assert all(isinstance(c, str) for c in cmds)
        assert any("does not call the Proxmox API directly" in c for c in cmds)


# ===========================================================================
# Serialisation
# ===========================================================================

class TestPlanToDict:
    def _plan(self):
        return _vh.build_derived_vault_plan(
            _service_operator_role(), _secret_entries(),
            now_fn=_fixed_now_fn, passphrase="Secret.pass.99", passphrase_source="t",
        )

    def test_excludes_passphrase_by_default_for_persisted_artifact(self):
        d = _vh.plan_to_dict(self._plan(), include_passphrase=False)
        assert "passphrase" not in d
        assert json.dumps(d)  # round-trips to JSON cleanly
        assert "Secret.pass.99" not in json.dumps(d)

    def test_includes_passphrase_when_requested(self):
        d = _vh.plan_to_dict(self._plan(), include_passphrase=True)
        assert d["passphrase"] == "Secret.pass.99"
        assert d["passphrase_shown_once"] is True

    def test_dict_shape(self):
        d = _vh.plan_to_dict(self._plan(), include_passphrase=False)
        assert d["role"] == "service-operator"
        assert d["entry_count"] == len(self._plan().entries)
        assert d["schema_version"] == _vh.SCHEMA_VERSION
        assert isinstance(d["entries"], list)
        assert all("keepass_path" in e for e in d["entries"])


# ===========================================================================
# HTML twin
# ===========================================================================

class TestScopedVaultPlanHtml:
    def _plan_dict(self):
        plan = _vh.build_derived_vault_plan(
            _service_operator_role(), _secret_entries(),
            now_fn=_fixed_now_fn, passphrase="Hidden.pass.7", passphrase_source="eff",
        )
        return _vh.plan_to_dict(plan, include_passphrase=False)

    def test_html_renders(self):
        html = _hpm.build_scoped_vault_plan_html(self._plan_dict())
        assert "<html" in html
        assert "service-operator" in html
        assert "Derived Vault" in html

    def test_html_documents_authorization_and_revocation(self):
        html = _hpm.build_scoped_vault_plan_html(self._plan_dict())
        assert "Authorization Model" in html
        assert "Revocation" in html
        assert "rotate" in html.lower()
        assert "by construction" in html.lower()

    def test_html_documents_vault_of_vaults(self):
        html = _hpm.build_scoped_vault_plan_html(self._plan_dict())
        assert "Vault-of-Vaults" in html
        assert "Vaults/service-operator/2026-06-08_12_00_00/passphrase" in html

    def test_html_never_contains_passphrase(self):
        html = _hpm.build_scoped_vault_plan_html(self._plan_dict())
        assert "Hidden.pass.7" not in html

    def test_html_lists_in_scope_entries(self):
        html = _hpm.build_scoped_vault_plan_html(self._plan_dict())
        assert "infra-bootstrap-deploy-key" in html
        assert "vm-100-password" in html


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
    _VALID_TIERS = ["service-operator", "node-sysadmin"]
    _TIER_DISPLAY = {"service-operator": "Service Operator", "node-sysadmin": "Node Sysadmin"}

    class TestBuildDerivedVaultPlanProperties:
        def _role(self, tier: str) -> dict:
            return {"name": f"{tier}-role", "tier": tier, "display_name": _TIER_DISPLAY[tier]}

        def _entries(self) -> list:
            return [
                {"name": "infra-key", "keepass_path": "Infra/infra-key",
                 "scope_tier": "service-operator", "secret_type": "deploy_key"},
                {"name": "vm-password", "keepass_path": "VMs/vm-password",
                 "scope_tier": "node-sysadmin", "secret_type": "vm_password"},
            ]

        @given(tier=st.sampled_from(_VALID_TIERS))
        @settings(max_examples=20)
        def test_plan_has_required_attributes(self, tier: str) -> None:
            plan = _vh.build_derived_vault_plan(
                self._role(tier), self._entries(),
                now_fn=lambda: "2026-06-08T12:00:00+00:00",
                passphrase="Test.pass.1",
            )
            assert hasattr(plan, "role")
            assert hasattr(plan, "entries")
            assert hasattr(plan, "db_path")

        @given(tier=st.sampled_from(_VALID_TIERS))
        @settings(max_examples=20)
        def test_plan_role_matches_input(self, tier: str) -> None:
            plan = _vh.build_derived_vault_plan(
                self._role(tier), self._entries(),
                now_fn=lambda: "2026-06-08T12:00:00+00:00",
                passphrase="Test.pass.2",
            )
            assert plan.tier == tier

        @given(tier=st.sampled_from(_VALID_TIERS))
        @settings(max_examples=20)
        def test_plan_to_dict_round_trips_tier(self, tier: str) -> None:
            plan = _vh.build_derived_vault_plan(
                self._role(tier), self._entries(),
                now_fn=lambda: "2026-06-08T12:00:00+00:00",
                passphrase="Test.pass.3",
            )
            d = _vh.plan_to_dict(plan, include_passphrase=False)
            assert d["tier"] == tier

        @given(passphrase=st.text(min_size=8, max_size=64,
               alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"),
                                      whitelist_characters=".")))
        @settings(max_examples=20)
        def test_passphrase_not_leaked_in_dict(self, passphrase: str) -> None:
            assume(passphrase.strip())
            plan = _vh.build_derived_vault_plan(
                self._role("service-operator"), self._entries(),
                now_fn=lambda: "2026-06-08T12:00:00+00:00",
                passphrase=passphrase,
            )
            d = _vh.plan_to_dict(plan, include_passphrase=False)
            assert passphrase not in str(d)
