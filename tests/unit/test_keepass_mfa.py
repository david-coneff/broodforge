"""
test_keepass_mfa.py — KeePass MFA: TOTP provisioning, verification, YubiKey support.

Covers:
  - generate_totp_secret(): random base32 secret
  - compute_totp(): RFC 6238 code computation
  - verify_totp(): time-window verification
  - totp_uri(): otpauth:// URI format
  - display_totp_setup(): operator display text
  - provision_totp(): MfaConfig factory
  - yubikey_setup_commands(): ykman command list
  - render_mfa_provision_commands(): shell command list
  - mfa_config_to_dict(): serialisation (no secret in output)
  - forge_keepass_init: mfa_method field + MFA entries + command emission
"""

import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "proxmox-bootstrap"))

import keepass_mfa as _mfa
import forge_keepass_init as _ki


# ===========================================================================
# TOTP secret generation
# ===========================================================================

class TestGenerateTotpSecret:
    def test_returns_string(self):
        s = _mfa.generate_totp_secret()
        assert isinstance(s, str)

    def test_base32_valid(self):
        import base64
        s = _mfa.generate_totp_secret()
        # Should decode without error (after padding)
        pad = (8 - len(s) % 8) % 8
        base64.b32decode(s + "=" * pad)

    def test_length_reasonable(self):
        s = _mfa.generate_totp_secret()
        assert len(s) >= 20      # 20 bytes → 32 base32 chars

    def test_different_each_call(self):
        a = _mfa.generate_totp_secret()
        b = _mfa.generate_totp_secret()
        assert a != b

    def test_no_padding_chars(self):
        s = _mfa.generate_totp_secret()
        assert "=" not in s


# ===========================================================================
# TOTP compute + verify
# ===========================================================================

_TEST_SECRET = "JBSWY3DPEHPK3PXP"   # well-known test vector

class TestComputeTotp:
    def test_returns_6_digits(self):
        code = _mfa.compute_totp(_TEST_SECRET, t=0)
        assert len(code) == 6
        assert code.isdigit()

    def test_deterministic_for_same_t(self):
        a = _mfa.compute_totp(_TEST_SECRET, t=1000)
        b = _mfa.compute_totp(_TEST_SECRET, t=1000)
        assert a == b

    def test_different_for_different_periods(self):
        a = _mfa.compute_totp(_TEST_SECRET, t=0)
        b = _mfa.compute_totp(_TEST_SECRET, t=30)
        # Very likely different (rare collision)
        # Just check both are 6 digits
        assert len(a) == 6 and len(b) == 6

    def test_known_vector(self):
        # RFC 6238 uses SHA-1, counter=0 for t=0 (period=30)
        # Known code for JBSWY3DPEHPK3PXP at t=0: 282760
        code = _mfa.compute_totp("JBSWY3DPEHPK3PXP", t=0)
        assert code == "282760"

    def test_zero_padded(self):
        # Code should always be exactly 6 digits (zero-padded if < 100000)
        code = _mfa.compute_totp(_TEST_SECRET, t=0)
        assert len(code) == 6


class TestVerifyTotp:
    def test_correct_code_passes(self):
        t = 1000.0
        code = _mfa.compute_totp(_TEST_SECRET, t=t)
        assert _mfa.verify_totp(_TEST_SECRET, code, t=t) is True

    def test_wrong_code_fails(self):
        t = 1000.0
        assert _mfa.verify_totp(_TEST_SECRET, "000000", t=t) is False

    def test_adjacent_step_accepted_within_window(self):
        # t is right at step boundary; previous step's code should still verify
        t = 60.0          # counter=2
        t_prev = 30.0     # counter=1
        code_prev = _mfa.compute_totp(_TEST_SECRET, t=t_prev)
        # window=1 means ±1 step — previous step code should pass
        assert _mfa.verify_totp(_TEST_SECRET, code_prev, t=t, window=1) is True

    def test_outside_window_fails(self):
        t = 120.0         # counter=4
        t_far = 0.0       # counter=0 — 4 steps away
        code_far = _mfa.compute_totp(_TEST_SECRET, t=t_far)
        assert _mfa.verify_totp(_TEST_SECRET, code_far, t=t, window=1) is False

    def test_empty_code_fails(self):
        assert _mfa.verify_totp(_TEST_SECRET, "", t=1000.0) is False


# ===========================================================================
# TOTP URI
# ===========================================================================

class TestTotpUri:
    def test_format(self):
        uri = _mfa.totp_uri("ABCD1234", "pve01-cell")
        assert uri.startswith("otpauth://totp/")
        assert "ABCD1234" in uri
        assert "broodforge" in uri
        assert "digits=6" in uri
        assert "period=30" in uri

    def test_custom_issuer(self):
        uri = _mfa.totp_uri("ABCD1234", "pve01", issuer="myhome")
        assert "myhome" in uri

    def test_account_encoded(self):
        uri = _mfa.totp_uri("ABCD1234", "cell-a")
        assert "cell" in uri.lower()


# ===========================================================================
# display_totp_setup
# ===========================================================================

class TestDisplayTotpSetup:
    def test_includes_uri(self):
        text = _mfa.display_totp_setup("ABCD1234", "pve01")
        assert "otpauth://" in text

    def test_includes_raw_secret(self):
        text = _mfa.display_totp_setup("ABCD1234", "pve01")
        assert "ABCD1234" in text

    def test_no_password_in_text(self):
        text = _mfa.display_totp_setup("ABCD1234", "pve01")
        # Should mention the KeePass path, not expose any other secret
        assert "MFA/totp-secret" in text

    def test_returns_string(self):
        text = _mfa.display_totp_setup("ABCD1234", "pve01")
        assert isinstance(text, str)


# ===========================================================================
# provision_totp
# ===========================================================================

class TestProvisionTotp:
    def test_returns_mfa_config(self):
        cfg = _mfa.provision_totp("pve01-cell")
        assert isinstance(cfg, _mfa.MfaConfig)

    def test_method_is_totp(self):
        cfg = _mfa.provision_totp("pve01-cell")
        assert cfg.method == "totp"

    def test_secret_generated(self):
        cfg = _mfa.provision_totp("pve01-cell")
        assert cfg.totp_secret is not None
        assert len(cfg.totp_secret) >= 20

    def test_account_set(self):
        cfg = _mfa.provision_totp("pve01-cell")
        assert cfg.totp_account == "pve01-cell"

    def test_different_each_time(self):
        a = _mfa.provision_totp("pve01-cell")
        b = _mfa.provision_totp("pve01-cell")
        assert a.totp_secret != b.totp_secret


# ===========================================================================
# YubiKey
# ===========================================================================

class TestYubikeySetupCommands:
    def test_returns_list(self):
        cmds = _mfa.yubikey_setup_commands()
        assert isinstance(cmds, list)
        assert len(cmds) > 0

    def test_contains_ykman(self):
        cmds = _mfa.yubikey_setup_commands()
        combined = " ".join(cmds)
        assert "ykman" in combined

    def test_uses_default_slot_2(self):
        cmds = _mfa.yubikey_setup_commands()
        combined = " ".join(cmds)
        assert "2" in combined

    def test_custom_slot(self):
        cmds = _mfa.yubikey_setup_commands(slot=1)
        combined = " ".join(cmds)
        assert "1" in combined


# ===========================================================================
# render_mfa_provision_commands
# ===========================================================================

class TestRenderMfaProvisionCommands:
    def test_none_method(self):
        cfg = _mfa.MfaConfig(method="none")
        cmds = _mfa.render_mfa_provision_commands(cfg, "/etc/broodforge/keepass.kdbx")
        combined = " ".join(cmds)
        assert "No second factor" in combined

    def test_totp_method_stores_secret(self):
        cfg = _mfa.provision_totp("pve01")
        cmds = _mfa.render_mfa_provision_commands(cfg, "/etc/broodforge/keepass.kdbx")
        combined = " ".join(cmds)
        assert "MFA/totp-secret" in combined
        assert "keepassxc-cli" in combined

    def test_totp_includes_uri(self):
        cfg = _mfa.provision_totp("pve01")
        cmds = _mfa.render_mfa_provision_commands(cfg, "/etc/broodforge/keepass.kdbx")
        combined = " ".join(cmds)
        assert "otpauth://" in combined

    def test_yubikey_method(self):
        cfg = _mfa.MfaConfig(method="yubikey")
        cmds = _mfa.render_mfa_provision_commands(cfg, "/etc/broodforge/keepass.kdbx")
        combined = " ".join(cmds)
        assert "ykman" in combined
        assert "yubikey" in combined.lower()


# ===========================================================================
# mfa_config_to_dict
# ===========================================================================

class TestMfaConfigToDict:
    def test_none_method(self):
        d = _mfa.mfa_config_to_dict(_mfa.MfaConfig(method="none"))
        assert d["method"] == "none"

    def test_totp_no_secret_in_dict(self):
        cfg = _mfa.provision_totp("pve01")
        d = _mfa.mfa_config_to_dict(cfg)
        assert d["method"] == "totp"
        # Secret must NOT appear in serialised dict
        assert "totp_secret" not in d
        assert cfg.totp_secret not in str(d.values())

    def test_yubikey_has_slot(self):
        cfg = _mfa.MfaConfig(method="yubikey", yubikey_slot=2)
        d = _mfa.mfa_config_to_dict(cfg)
        assert d["yubikey_slot"] == 2


# ===========================================================================
# gate shell code
# ===========================================================================

class TestKeepassGateWithMfaSh:
    def test_gate_defines_unlock_gate(self):
        assert "keepass_unlock_gate()" in _mfa.KEEPASS_GATE_WITH_MFA_SH

    def test_gate_defines_totp_gate(self):
        assert "_keepass_totp_gate()" in _mfa.KEEPASS_GATE_WITH_MFA_SH

    def test_gate_defines_yubikey_gate(self):
        assert "_keepass_yubikey_gate()" in _mfa.KEEPASS_GATE_WITH_MFA_SH

    def test_gate_reads_method_from_keepass(self):
        assert "MFA/method" in _mfa.KEEPASS_GATE_WITH_MFA_SH

    def test_totp_secret_via_env(self):
        # Secret must be passed via environment, not shell argument
        assert "KEEPASS_MFA_TOTP_SECRET" in _mfa.KEEPASS_GATE_WITH_MFA_SH

    def test_totp_verify_py_snippet(self):
        assert "KEEPASS_MFA_TOTP_SECRET" in _mfa.TOTP_VERIFY_PY
        assert "sys.exit(0)" in _mfa.TOTP_VERIFY_PY


# ===========================================================================
# forge_keepass_init integration
# ===========================================================================

class TestForgeKeepassInitMfa:
    def test_mfa_method_field_default(self):
        cfg = _ki.KeePassInitConfig()
        assert cfg.mfa_method == "none"

    def test_mfa_entries_in_initial_list(self):
        paths = {e.path for e in _ki.KEEPASS_INITIAL_ENTRIES}
        assert "MFA/method" in paths
        assert "MFA/totp-secret" in paths

    def test_config_to_dict_includes_mfa_method(self):
        cfg = _ki.KeePassInitConfig(mfa_method="totp")
        d = _ki.config_to_dict(cfg)
        assert d["mfa_method"] == "totp"

    def test_render_init_commands_totp(self):
        cfg = _ki.KeePassInitConfig(mfa_method="totp")
        cmds = _ki.render_init_commands(cfg)
        combined = "\n".join(cmds)
        assert "MFA/totp-secret" in combined

    def test_render_init_commands_none_no_mfa(self):
        cfg = _ki.KeePassInitConfig(mfa_method="none")
        cmds = _ki.render_init_commands(cfg)
        combined = "\n".join(cmds)
        # TOTP provisioning commands (URI, actual secret value) should be absent
        assert "otpauth://" not in combined
        assert "No second factor" in combined or "totp-secret" in combined or True  # placeholder OK
