"""
tests/unit/test_credential_hierarchy.py — Unit tests for credential_hierarchy.py

Tests:
  test_load_hierarchy_config         — load JSON, get ChildDatabase objects
  test_validate_reference_valid      — valid ref parses to (db, group, entry)
  test_validate_reference_invalid_format — raises ValueError on bad format
  test_validate_reference_unknown_db — raises ValueError on unknown db name
  test_get_child_db_found            — returns correct ChildDatabase
  test_get_child_db_not_found        — returns None
  test_save_roundtrip                — save + load preserves all fields
  test_init_creates_skeleton         — --init writes valid JSON with placeholder paths
"""

import json
from pathlib import Path

import pytest

# Make proxmox-bootstrap importable from the test directory
from credential_hierarchy import (
    ChildDatabase,
    CredentialHierarchy,
    HierarchyManager,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_config(tmp_path: Path) -> Path:
    """Write a sample credential-hierarchy.json and return its path."""
    config = {
        "hierarchy_version": "1",
        "master_db_path": str(tmp_path / "master.kdbx"),
        "child_databases": [
            {
                "name": "forge-autonomous",
                "path": str(tmp_path / "forge-autonomous.kdbx"),
                "master_entry": "Broodforge/child-dbs/forge-autonomous",
                "scope_description": "Autonomous operation credentials",
            },
            {
                "name": "forge-spawn",
                "path": str(tmp_path / "forge-spawn.kdbx"),
                "master_entry": "Broodforge/child-dbs/forge-spawn",
                "scope_description": "Spawn-phase credentials",
            },
            {
                "name": "forge-migrate",
                "path": str(tmp_path / "forge-migrate.kdbx"),
                "master_entry": "Broodforge/child-dbs/forge-migrate",
                "scope_description": "Migration-phase credentials",
            },
        ],
    }
    config_path = tmp_path / "credential-hierarchy.json"
    config_path.write_text(json.dumps(config, indent=2))
    return config_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoadHierarchyConfig:
    def test_load_hierarchy_config(self, tmp_path):
        """load() returns a CredentialHierarchy with correct ChildDatabase objects."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        hierarchy = manager.load()

        assert isinstance(hierarchy, CredentialHierarchy)
        assert hierarchy.hierarchy_version == "1"
        assert hierarchy.master_db_path == tmp_path / "master.kdbx"
        assert len(hierarchy.child_databases) == 3

        child = hierarchy.child_databases[0]
        assert isinstance(child, ChildDatabase)
        assert child.name == "forge-autonomous"
        assert child.path == tmp_path / "forge-autonomous.kdbx"
        assert child.master_entry == "Broodforge/child-dbs/forge-autonomous"
        assert "Autonomous" in child.scope_description


class TestValidateReferenceValid:
    def test_validate_reference_valid(self, tmp_path):
        """Valid child:// reference parses to (db_name, group, entry_title)."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        db_name, group, entry_title = manager.validate_reference(
            "child://forge-autonomous/restic/repo-password"
        )

        assert db_name == "forge-autonomous"
        assert group == "restic"
        assert entry_title == "repo-password"

    def test_validate_reference_multi_segment_entry(self, tmp_path):
        """Entry titles with slashes are preserved."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        db_name, group, entry_title = manager.validate_reference(
            "child://forge-spawn/cloud-init/node-keypair"
        )

        assert db_name == "forge-spawn"
        assert group == "cloud-init"
        assert entry_title == "node-keypair"


class TestValidateReferenceInvalidFormat:
    def test_validate_reference_invalid_format_no_scheme(self, tmp_path):
        """Reference without child:// scheme raises ValueError."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        with pytest.raises(ValueError, match="child://"):
            manager.validate_reference("forge-autonomous/restic/repo-password")

    def test_validate_reference_invalid_format_too_few_parts(self, tmp_path):
        """Reference with fewer than 3 path components raises ValueError."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        with pytest.raises(ValueError):
            manager.validate_reference("child://forge-autonomous/restic")

    def test_validate_reference_invalid_format_empty_part(self, tmp_path):
        """Reference with empty path segment raises ValueError."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        with pytest.raises(ValueError):
            manager.validate_reference("child://forge-autonomous//repo-password")


class TestValidateReferenceUnknownDb:
    def test_validate_reference_unknown_db(self, tmp_path):
        """Reference to an undeclared DB name raises ValueError."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        with pytest.raises(ValueError, match="Unknown child DB"):
            manager.validate_reference(
                "child://forge-nonexistent/restic/repo-password"
            )

    def test_validate_reference_unknown_db_message_contains_known(self, tmp_path):
        """Error message lists the known database names."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        with pytest.raises(ValueError) as exc_info:
            manager.validate_reference("child://bad-db/group/entry")

        msg = str(exc_info.value)
        assert "forge-autonomous" in msg


class TestGetChildDb:
    def test_get_child_db_found(self, tmp_path):
        """get_child_db returns the correct ChildDatabase for a known name."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        child = manager.get_child_db("forge-spawn")

        assert child is not None
        assert child.name == "forge-spawn"
        assert child.master_entry == "Broodforge/child-dbs/forge-spawn"

    def test_get_child_db_not_found(self, tmp_path):
        """get_child_db returns None for an unknown name."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        result = manager.get_child_db("forge-nonexistent")

        assert result is None


class TestSaveRoundtrip:
    def test_save_roundtrip(self, tmp_path):
        """save() + load() preserves all fields exactly."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        original = manager.load()

        # Modify and save
        original.hierarchy_version = "2"
        original.child_databases[0].scope_description = "Modified description"
        manager.save(original)

        # Reload and verify
        reloaded = manager.load()
        assert reloaded.hierarchy_version == "2"
        assert reloaded.master_db_path == original.master_db_path
        assert len(reloaded.child_databases) == 3
        assert reloaded.child_databases[0].scope_description == "Modified description"
        assert reloaded.child_databases[0].name == "forge-autonomous"
        assert reloaded.child_databases[1].name == "forge-spawn"
        assert reloaded.child_databases[2].name == "forge-migrate"

    def test_save_roundtrip_paths(self, tmp_path):
        """Path fields survive JSON serialisation and deserialisation."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        original = manager.load()
        manager.save(original)
        reloaded = manager.load()

        for orig_child, rel_child in zip(
            original.child_databases, reloaded.child_databases, strict=False
        ):
            assert rel_child.path == orig_child.path
            assert rel_child.master_entry == orig_child.master_entry


class TestInitCreatesSkeleton:
    def test_init_creates_skeleton(self, tmp_path):
        """--init (init_skeleton) writes valid JSON with placeholder paths."""
        config_path = tmp_path / "credential-hierarchy.json"
        manager = HierarchyManager(config_path=config_path)

        hierarchy = manager.init_skeleton()

        # File must exist and be valid JSON
        assert config_path.exists()
        raw = json.loads(config_path.read_text())
        assert "hierarchy_version" in raw
        assert "master_db_path" in raw
        assert "child_databases" in raw
        assert len(raw["child_databases"]) == 3

        # All three expected child DBs present
        names = {c["name"] for c in raw["child_databases"]}
        assert names == {"forge-autonomous", "forge-spawn", "forge-migrate"}

        # All entries have required fields
        for child in raw["child_databases"]:
            assert "name" in child
            assert "path" in child
            assert "master_entry" in child
            assert "scope_description" in child
            assert child["master_entry"].startswith("Broodforge/child-dbs/")

        # Returned object is correct type
        assert isinstance(hierarchy, CredentialHierarchy)
        assert len(hierarchy.child_databases) == 3

    def test_init_raises_if_exists(self, tmp_path):
        """init_skeleton raises FileExistsError if config already exists."""
        config_path = _sample_config(tmp_path)
        manager = HierarchyManager(config_path=config_path)

        with pytest.raises(FileExistsError):
            manager.init_skeleton()

    def test_init_custom_master_db(self, tmp_path):
        """--init with --master-db sets master_db_path in the skeleton."""
        config_path = tmp_path / "credential-hierarchy.json"
        manager = HierarchyManager(config_path=config_path)
        custom_path = str(tmp_path / "my-master.kdbx")

        hierarchy = manager.init_skeleton(master_db_path=custom_path)

        assert str(hierarchy.master_db_path) == custom_path
        raw = json.loads(config_path.read_text())
        assert raw["master_db_path"] == custom_path
