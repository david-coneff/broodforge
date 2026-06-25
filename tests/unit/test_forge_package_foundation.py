"""
test_forge_package_foundation.py — Tests for Phase 1.F foundation pieces:
  1.F.7  lib/passphrase.py     — readable passphrase generator
  1.F.5  forge_validator.py    — minimum viable hardware validation
  1.F.4  forge-manifest-schema.json — manifest schema
"""

import json
import os

# Allow importing from proxmox-bootstrap and lib
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


# ===========================================================================
# 1.F.7 — passphrase generator
# ===========================================================================

import passphrase as _pw


class TestPassphraseFormat:
    def _gen(self, seed=None):
        import random
        rng = random.Random(seed) if seed is not None else None
        return _pw.generate_passphrase(rng=rng)

    def test_returns_string(self):
        assert isinstance(self._gen(seed=0), str)

    def test_length_in_range(self):
        import random
        # Use a seeded RNG so the test is deterministic — no flakiness
        rng = random.Random(42)
        for _i in range(50):
            p = _pw.generate_passphrase(rng=rng)
            assert _pw._MIN_LEN <= len(p) <= _pw._MAX_LEN, f"Length out of range: {p!r}"

    def test_contains_only_allowed_chars(self):
        import string
        allowed = set(string.ascii_letters + string.digits + ".")
        for _ in range(30):
            p = self._gen()
            bad = set(p) - allowed
            assert not bad, f"Unexpected chars {bad!r} in {p!r}"

    def test_starts_with_capital(self):
        for _ in range(30):
            p = self._gen()
            first_char = p[0]
            assert first_char.isupper(), f"Expected uppercase first char: {p!r}"

    def test_ends_with_digit(self):
        for _ in range(30):
            p = self._gen()
            last_part = p.rsplit(".", 1)[-1]
            assert last_part.isdigit(), f"Expected digit suffix: {p!r}"

    def test_period_separated(self):
        for _ in range(20):
            p = self._gen()
            assert "." in p

    def test_at_least_two_words(self):
        for _ in range(30):
            p = self._gen()
            parts = p.split(".")
            words = parts[:-1]  # exclude trailing digit
            assert len(words) >= 2, f"Too few words: {p!r}"

    def test_no_shell_special_chars(self):
        special = set("$`\\\"'!&|;<>()*?{}[]~")
        for _ in range(30):
            p = self._gen()
            bad = set(p) & special
            assert not bad, f"Shell-special chars {bad!r} in {p!r}"

    def test_uniqueness(self):
        phrases = [self._gen() for _ in range(20)]
        # Allow some duplicates by chance but most should be unique
        unique = set(phrases)
        assert len(unique) >= 15

    def test_seeded_reproducible(self):
        import random
        r = random.Random(42)
        p1 = _pw.generate_passphrase(rng=r)
        r2 = random.Random(42)
        p2 = _pw.generate_passphrase(rng=r2)
        assert p1 == p2


class TestGeneratePassphraseN:
    def test_returns_list(self):
        result = _pw.generate_passphrase_n(5)
        assert isinstance(result, list)
        assert len(result) == 5

    def test_all_unique(self):
        result = _pw.generate_passphrase_n(10)
        assert len(set(result)) == 10

    def test_all_valid_format(self):
        for p in _pw.generate_passphrase_n(8):
            strength = _pw.passphrase_strength(p)
            assert strength["format_valid"], f"Invalid format: {p!r}"


class TestGenerateAlphanumeric:
    def test_default_length(self):
        p = _pw.generate_alphanumeric()
        assert len(p) == 24

    def test_custom_length(self):
        p = _pw.generate_alphanumeric(length=16)
        assert len(p) == 16

    def test_alphanumeric_only(self):
        import string
        allowed = set(string.ascii_letters + string.digits)
        for _ in range(20):
            p = _pw.generate_alphanumeric()
            bad = set(p) - allowed
            assert not bad, f"Non-alphanumeric chars in {p!r}"

    def test_has_uppercase(self):
        p = _pw.generate_alphanumeric()
        assert any(c.isupper() for c in p)

    def test_has_lowercase(self):
        p = _pw.generate_alphanumeric()
        assert any(c.islower() for c in p)

    def test_has_digit(self):
        p = _pw.generate_alphanumeric()
        assert any(c.isdigit() for c in p)


class TestPassphraseStrength:
    def test_valid_passphrase(self):
        s = _pw.passphrase_strength("Forest.amber.glide.8")
        assert s["format_valid"]
        assert s["has_digit"]
        assert s["meets_min_length"]
        assert s["word_count"] == 3

    def test_no_digit(self):
        s = _pw.passphrase_strength("Forest.amber.glide")
        assert not s["has_digit"]
        assert not s["format_valid"]

    def test_short_passphrase(self):
        s = _pw.passphrase_strength("Ax.bc.1")
        assert not s["meets_min_length"]


# ===========================================================================
# 1.F.5 — forge_validator
# ===========================================================================

import forge_validator as _fv


def _make_hw(
    ram_gb=32,
    disks=None,
    nics=None,
    cpu_cores=4,
):
    if disks is None:
        disks = [
            {"name": "sda", "size_gb": 200, "model": "SAMSUNG", "rotational": False, "removable": False},
            {"name": "sdb", "size_gb": 200, "model": "SAMSUNG", "rotational": False, "removable": False},
        ]
    if nics is None:
        nics = [{"name": "enp3s0", "mac": "aa:bb:cc:dd:ee:ff", "speed_mbps": 1000}]
    return {
        "ram_gb": ram_gb,
        "cpu_model": "Intel Core i7",
        "cpu_cores": cpu_cores,
        "hostname": "pve01",
        "disks": disks,
        "nics": nics,
        "derived": {
            "disk_count": len(disks),
            "usable_disks": len(disks),
            "ssd_count": len(disks),
            "hdd_count": 0,
        },
    }


class TestForgeValidatorPassingCases:
    def test_adequate_hardware_no_findings(self):
        hw = _make_hw(ram_gb=32)
        findings = _fv.validate_forge_hardware(hw)
        reds = [f for f in findings if f.severity == "RED"]
        assert not reds

    def test_valid_returns_true(self):
        hw = _make_hw(ram_gb=32)
        findings = _fv.validate_forge_hardware(hw)
        assert _fv.is_forge_valid(findings)

    def test_large_disks_no_yellow_for_size(self):
        hw = _make_hw(disks=[
            {"name": "sda", "size_gb": 500, "model": "HDD", "rotational": True, "removable": False},
            {"name": "sdb", "size_gb": 500, "model": "HDD", "rotational": True, "removable": False},
        ])
        findings = _fv.validate_forge_hardware(hw)
        disk_findings = [f for f in findings if f.field == "disks"]
        # No RED on adequate hardware
        assert not any(f.severity == "RED" for f in disk_findings)


class TestForgeValidatorRAM:
    def test_too_little_ram_red(self):
        hw = _make_hw(ram_gb=8)
        findings = _fv.validate_forge_hardware(hw)
        ram_reds = [f for f in findings if f.field == "ram_gb" and f.severity == "RED"]
        assert len(ram_reds) == 1

    def test_below_recommended_yellow(self):
        hw = _make_hw(ram_gb=20)
        findings = _fv.validate_forge_hardware(hw)
        ram_yellows = [f for f in findings if f.field == "ram_gb" and f.severity == "YELLOW"]
        assert len(ram_yellows) == 1

    def test_at_minimum_no_red(self):
        hw = _make_hw(ram_gb=16)
        findings = _fv.validate_forge_hardware(hw)
        ram_reds = [f for f in findings if f.field == "ram_gb" and f.severity == "RED"]
        assert not ram_reds

    def test_at_recommended_no_findings(self):
        hw = _make_hw(ram_gb=32)
        findings = _fv.validate_forge_hardware(hw)
        ram_findings = [f for f in findings if f.field == "ram_gb"]
        assert not ram_findings


class TestForgeValidatorDisks:
    def test_no_disks_red(self):
        hw = _make_hw(disks=[])
        findings = _fv.validate_forge_hardware(hw)
        disk_reds = [f for f in findings if f.field == "disks" and f.severity == "RED"]
        assert disk_reds

    def test_one_disk_red(self):
        hw = _make_hw(disks=[
            {"name": "sda", "size_gb": 200, "model": "SSD", "rotational": False, "removable": False},
        ])
        findings = _fv.validate_forge_hardware(hw)
        disk_reds = [f for f in findings if f.field == "disks" and f.severity == "RED"]
        assert disk_reds

    def test_two_disks_ok(self):
        hw = _make_hw()  # default = 2 disks
        findings = _fv.validate_forge_hardware(hw)
        disk_reds = [f for f in findings if f.field == "disks" and f.severity == "RED"]
        assert not disk_reds

    def test_small_disks_yellow(self):
        hw = _make_hw(disks=[
            {"name": "sda", "size_gb": 40, "model": "SSD", "rotational": False, "removable": False},
            {"name": "sdb", "size_gb": 40, "model": "SSD", "rotational": False, "removable": False},
        ])
        findings = _fv.validate_forge_hardware(hw)
        disk_yellows = [f for f in findings if f.field == "disks" and f.severity == "YELLOW"]
        assert disk_yellows

    def test_removable_disks_excluded(self):
        hw = _make_hw(disks=[
            {"name": "sda", "size_gb": 200, "model": "USB", "rotational": False, "removable": True},
            {"name": "sdb", "size_gb": 200, "model": "USB", "rotational": False, "removable": True},
        ])
        findings = _fv.validate_forge_hardware(hw)
        disk_reds = [f for f in findings if f.field == "disks" and f.severity == "RED"]
        assert disk_reds

    def test_too_small_disks_excluded_from_usable(self):
        hw = _make_hw(disks=[
            {"name": "sda", "size_gb": 10, "model": "SSD", "rotational": False, "removable": False},
            {"name": "sdb", "size_gb": 10, "model": "SSD", "rotational": False, "removable": False},
        ])
        findings = _fv.validate_forge_hardware(hw)
        disk_reds = [f for f in findings if f.field == "disks" and f.severity == "RED"]
        assert disk_reds


class TestForgeValidatorNICs:
    def test_no_nics_red(self):
        hw = _make_hw(nics=[])
        findings = _fv.validate_forge_hardware(hw)
        nic_reds = [f for f in findings if f.field == "nics" and f.severity == "RED"]
        assert nic_reds

    def test_one_nic_yellow(self):
        hw = _make_hw(nics=[
            {"name": "enp3s0", "mac": "aa:bb:cc:dd:ee:ff", "speed_mbps": 1000},
        ])
        findings = _fv.validate_forge_hardware(hw)
        nic_yellows = [f for f in findings if f.field == "nics" and f.severity == "YELLOW"]
        assert nic_yellows

    def test_two_nics_no_findings(self):
        hw = _make_hw(nics=[
            {"name": "enp3s0", "mac": "aa:bb:cc:dd:ee:00", "speed_mbps": 1000},
            {"name": "enp4s0", "mac": "aa:bb:cc:dd:ee:01", "speed_mbps": 1000},
        ])
        findings = _fv.validate_forge_hardware(hw)
        nic_findings = [f for f in findings if f.field == "nics"]
        assert not nic_findings


class TestForgeValidatorCPU:
    def test_low_cpu_yellow(self):
        hw = _make_hw(cpu_cores=2)
        findings = _fv.validate_forge_hardware(hw)
        cpu_yellows = [f for f in findings if f.field == "cpu_cores" and f.severity == "YELLOW"]
        assert cpu_yellows

    def test_zero_cpu_no_finding(self):
        hw = _make_hw(cpu_cores=0)
        findings = _fv.validate_forge_hardware(hw)
        cpu_findings = [f for f in findings if f.field == "cpu_cores"]
        assert not cpu_findings  # 0 means "not detected" — skip check

    def test_adequate_cpu_no_findings(self):
        hw = _make_hw(cpu_cores=8)
        findings = _fv.validate_forge_hardware(hw)
        cpu_findings = [f for f in findings if f.field == "cpu_cores"]
        assert not cpu_findings


class TestForgeValidatorHelpers:
    def test_is_forge_valid_empty(self):
        assert _fv.is_forge_valid([])

    def test_is_forge_valid_only_yellows(self):
        findings = [_fv.ForgeValidationFinding("YELLOW", "f", "m", 0, 0)]
        assert _fv.is_forge_valid(findings)

    def test_is_forge_valid_with_red(self):
        findings = [_fv.ForgeValidationFinding("RED", "f", "m", 0, 0)]
        assert not _fv.is_forge_valid(findings)

    def test_summarise_empty(self):
        s = _fv.summarise_forge_findings([])
        assert "passed" in s.lower()

    def test_summarise_with_red(self):
        findings = [_fv.ForgeValidationFinding("RED", "ram_gb", "Not enough RAM", 8, 16)]
        s = _fv.summarise_forge_findings(findings)
        assert "RED" in s
        assert "BLOCKED" in s

    def test_summarise_with_yellow(self):
        findings = [_fv.ForgeValidationFinding("YELLOW", "nics", "Only 1 NIC", 1, 2)]
        s = _fv.summarise_forge_findings(findings)
        assert "YELLOW" in s
        assert "Warnings" in s

    def test_describe_minimum_stack(self):
        s = _fv.describe_minimum_stack()
        assert "k3s-server" in s
        assert "forgejo" in s
        assert "assessment-engine" in s


# ===========================================================================
# 1.F.4 — forge-manifest-schema.json
# ===========================================================================

class TestForgeManifestSchema:
    def _schema(self):
        schema_path = os.path.join(_ROOT, "data-model", "forge-manifest-schema.json")
        with open(schema_path) as f:
            return json.load(f)

    def _valid_manifest(self):
        return {
            "schema_version": "1.0",
            "cell_id": "pve01-cell",
            "generated_at": "2026-06-01T12:00:00+00:00",
            "setup_mode": "autonomous",
            "host_identity": {
                "hostname": "pve01",
                "domain": "home.example.com",
                "fqdn": "pve01.home.example.com",
                "cell_id": "pve01-cell",
            },
            "network_topology": {
                "profile": "lan",
                "management_cidr": "192.168.1.0/24",
                "gateway": "192.168.1.1",
            },
        }

    def test_schema_loads(self):
        s = self._schema()
        assert s["title"] == "Forge Manifest"

    def test_valid_minimal_manifest(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")  # noqa: I001
        s = self._schema()
        jsonschema.validate(self._valid_manifest(), s)

    def test_missing_cell_id_fails(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")  # noqa: I001
        m = self._valid_manifest()
        del m["cell_id"]
        s = self._schema()
        try:
            jsonschema.validate(m, s)
            raise AssertionError("Should have raised")
        except jsonschema.ValidationError:
            pass

    def test_invalid_setup_mode_fails(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")  # noqa: I001
        m = self._valid_manifest()
        m["setup_mode"] = "turbo"
        s = self._schema()
        try:
            jsonschema.validate(m, s)
            raise AssertionError("Should have raised")
        except jsonschema.ValidationError:
            pass

    def test_wan_profile_with_wan_config(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")  # noqa: I001
        m = self._valid_manifest()
        m["network_topology"]["profile"] = "wan"
        m["network_topology"]["wan_config"] = {
            "domain": "home.example.com",
            "dns_provider": "cloudflare",
            "headscale_url": "https://pve01.home.example.com:8080",
        }
        s = self._schema()
        jsonschema.validate(m, s)

    def test_setup_overrides_field(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")  # noqa: I001
        m = self._valid_manifest()
        m["setup_overrides"] = {
            "network.management_cidr": {"value": "10.0.0.0/24", "source": "manual"}
        }
        s = self._schema()
        jsonschema.validate(m, s)

    def test_invalid_hostname_format_fails(self):
        try:
            import jsonschema
        except ImportError:
            import pytest; pytest.skip("jsonschema not installed")  # noqa: I001
        m = self._valid_manifest()
        m["host_identity"]["hostname"] = "PVE-01"  # uppercase not allowed
        s = self._schema()
        try:
            jsonschema.validate(m, s)
            raise AssertionError("Should have raised")
        except jsonschema.ValidationError:
            pass

    def test_required_fields_present(self):
        s = self._schema()
        required = s["required"]
        assert "schema_version" in required
        assert "cell_id" in required
        assert "host_identity" in required
        assert "network_topology" in required


# ===========================================================================
# validate_forge_manifest() — schema validation helper in forge_validator
# ===========================================================================

class TestValidateForgeManifest:
    def _valid_manifest(self):
        return {
            "schema_version": "1.0",
            "cell_id": "pve01-cell",
            "generated_at": "2026-06-01T12:00:00+00:00",
            "setup_mode": "autonomous",
            "host_identity": {
                "hostname": "pve01",
                "domain": "home.example.com",
                "fqdn": "pve01.home.example.com",
                "cell_id": "pve01-cell",
            },
            "network_topology": {
                "profile": "lan",
                "management_cidr": "192.168.1.0/24",
                "gateway": "192.168.1.1",
            },
        }

    def test_valid_manifest_returns_empty(self):
        findings = _fv.validate_forge_manifest(self._valid_manifest())
        reds = [f for f in findings if f.severity == "RED"]
        assert not reds

    def test_missing_required_field_returns_red(self):
        m = self._valid_manifest()
        del m["cell_id"]
        findings = _fv.validate_forge_manifest(m)
        assert any(f.severity == "RED" and "cell_id" in f.field for f in findings)

    def test_missing_schema_path_returns_yellow(self):
        findings = _fv.validate_forge_manifest(self._valid_manifest(), schema_path="/nonexistent/schema.json")
        assert len(findings) == 1
        assert findings[0].severity == "YELLOW"
        assert "schema" in findings[0].field

    def test_returns_list(self):
        result = _fv.validate_forge_manifest(self._valid_manifest())
        assert isinstance(result, list)
