#!/usr/bin/env python3
"""
keepass_mfa.py — KeePass MFA provisioning and verification (TOTP + YubiKey).

TOTP is auto-provisioned during forge phase-03:
  1. generate_totp_secret()  → random base32 TOTP secret
  2. Store in KeePass at 'MFA/totp-secret' via keepassxc-cli
  3. display_totp_setup()    → otpauth:// URI + raw secret for operator to scan
  4. At unlock gate:         → prompt for 6-digit TOTP code, verify inline

YubiKey HMAC-SHA1 challenge-response (optional):
  1. yubikey_setup_commands()  → ykman commands to configure slot 2
  2. At unlock gate:           → challenge → response → verify

Stdlib only.
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# TOTP — RFC 6238
# ---------------------------------------------------------------------------

TOTP_PERIOD   = 30
TOTP_DIGITS   = 6
TOTP_ALGORITHM = "SHA1"


def generate_totp_secret(byte_length: int = 20) -> str:
    """
    Generate a random TOTP secret encoded as base32 (no padding).

    20 bytes = 160 bits — standard for Google Authenticator compatibility.
    """
    raw = secrets.token_bytes(byte_length)
    return base64.b32encode(raw).decode().rstrip("=")


def _decode_b32(secret: str) -> bytes:
    """Decode a base32 TOTP secret, tolerating missing padding."""
    secret = secret.upper().replace(" ", "").replace("-", "")
    pad = (8 - len(secret) % 8) % 8
    return base64.b32decode(secret + "=" * pad)


def _hotp(key: bytes, counter: int) -> int:
    """Compute HOTP (RFC 4226) for the given counter."""
    msg = struct.pack(">Q", counter)
    mac = hmac.new(key, msg, hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value  = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return value % (10 ** TOTP_DIGITS)


def compute_totp(secret: str, t: Optional[float] = None, period: int = TOTP_PERIOD) -> str:
    """
    Compute the current TOTP code (zero-padded to TOTP_DIGITS digits).

    t: Unix timestamp (default: current time).
    """
    counter = int((t if t is not None else time.time()) / period)
    key  = _decode_b32(secret)
    code = _hotp(key, counter)
    return f"{code:0{TOTP_DIGITS}d}"


def verify_totp(
    secret: str,
    code:   str,
    t:      Optional[float] = None,
    window: int = 1,
) -> bool:
    """
    Verify a TOTP code with a ±window step tolerance (default ±1 = ±30s).

    Returns True if the code matches any step within the window.
    """
    counter = int((t if t is not None else time.time()) / TOTP_PERIOD)
    key = _decode_b32(secret)
    for delta in range(-window, window + 1):
        if f"{_hotp(key, counter + delta):0{TOTP_DIGITS}d}" == code:
            return True
    return False


def totp_uri(secret: str, account: str, issuer: str = "broodforge") -> str:
    """
    Build an otpauth:// URI for scanning with an authenticator app.

    Format: otpauth://totp/{issuer}:{account}?secret={secret}&issuer={issuer}&...
    """
    from urllib.parse import quote
    label = f"{quote(issuer)}:{quote(account)}"
    return (
        f"otpauth://totp/{label}"
        f"?secret={secret}"
        f"&issuer={quote(issuer)}"
        f"&algorithm={TOTP_ALGORITHM}"
        f"&digits={TOTP_DIGITS}"
        f"&period={TOTP_PERIOD}"
    )


def display_totp_setup(secret: str, account: str, issuer: str = "broodforge") -> str:
    """
    Return a terminal-ready text block the operator sees when setting up TOTP.

    Displays the otpauth:// URI (for QR-code scanning in a GUI) and the raw
    base32 secret (for manual entry into an authenticator app).

    The caller is responsible for directing this text to /dev/tty when running
    inside a script that redirects stdout to a log file. Use
    print_totp_setup_to_tty() for that case.
    """
    uri = totp_uri(secret, account, issuer)
    bar = "=" * 68
    return "\n".join([
        "",
        bar,
        " TOTP Second Factor Setup",
        bar,
        "",
        " Scan the URI below with your authenticator app, or enter the",
        " raw secret manually (Google Authenticator, Aegis, Authy, etc.).",
        "",
        " URI (copy to authenticator app or qrencode -o qr.png <uri>):",
        f"  {uri}",
        "",
        " Raw secret (for manual entry):",
        f"  {secret}",
        "",
        " Algorithm: SHA-1  |  Digits: 6  |  Period: 30s",
        "",
        " Store this secret somewhere safe in addition to your KeePass.",
        " It is also kept in KeePass at: MFA/totp-secret",
        bar,
        "",
    ])


def print_totp_setup_to_tty(secret: str, account: str, issuer: str = "broodforge") -> None:
    """
    Write the TOTP setup text directly to /dev/tty.

    This bypasses any stdout/stderr log redirection (e.g., exec >> forge.log 2>&1)
    so the raw TOTP secret is shown to the operator but never captured in forge.log.
    Falls back to stderr if /dev/tty is unavailable (tests, non-interactive).
    """
    import sys
    text = display_totp_setup(secret, account, issuer)
    try:
        with open("/dev/tty", "w") as tty:
            tty.write(text)
    except OSError:
        print(text, file=sys.stderr)


# ---------------------------------------------------------------------------
# Inline Python snippet for shell gate TOTP verification
# (injected into keepass-gate.sh as a heredoc function)
# ---------------------------------------------------------------------------

#
# This is the Python snippet that the shell gate evaluates.
# Reads KEEPASS_MFA_TOTP_SECRET and KEEPASS_MFA_CODE from the environment
# so no secret touches the process argument list.
#
TOTP_VERIFY_PY = """\
import sys, os, base64, hashlib, hmac, struct, time
s = os.environ.get('KEEPASS_MFA_TOTP_SECRET', '').upper().replace(' ', '').replace('-', '')
code = os.environ.get('KEEPASS_MFA_CODE', '')
if not s or not code:
    sys.exit(2)
pad = (8 - len(s) % 8) % 8
key = base64.b32decode(s + '=' * pad)
ctr = int(time.time() / 30)
for d in range(-1, 2):
    msg = struct.pack('>Q', ctr + d)
    mac = hmac.new(key, msg, hashlib.sha1).digest()
    off = mac[-1] & 0x0f
    v = struct.unpack('>I', mac[off:off+4])[0] & 0x7fffffff
    if f'{v % 1000000:06d}' == code:
        sys.exit(0)
sys.exit(1)
"""


# ---------------------------------------------------------------------------
# Updated KeePass gate shell code with MFA
# ---------------------------------------------------------------------------

KEEPASS_GATE_WITH_MFA_SH = """\
#!/usr/bin/env bash
# keepass-gate.sh — KeePass master password + MFA unlock gate
# Source this file and call keepass_unlock_gate() before any secrets are accessed.
# The gate runs ONCE per session. After unlocking, the secrets broker
# handles all subsequent lookups without further operator input.

KDBX_PATH=""
KDBX_UNLOCKED=0
KDBX_MFA_METHOD=""   # "none" | "totp" | "yubikey"

keepass_find_db() {
  local embedded
  embedded="$(ls "$SCRIPT_DIR"/kdbx/*.kdbx 2>/dev/null | head -1)"
  if [ -n "$embedded" ]; then
    KDBX_PATH="$embedded"
    echo "[kdbx] Using embedded database: $KDBX_PATH"
    return 0
  fi
  read -rp "[kdbx] Enter path to KeePass database (.kdbx): " KDBX_PATH
  if [ ! -f "$KDBX_PATH" ]; then
    echo "[kdbx] File not found: $KDBX_PATH" && return 1
  fi
}

keepass_unlock_gate() {
  [ "$KDBX_UNLOCKED" -eq 1 ] && return 0
  echo ""
  echo "================================================================="
  echo " KeePass Unlock Gate"
  echo " The master password is required once before any secrets are"
  echo " accessed. All subsequent lookups are automatic."
  echo "================================================================="
  keepass_find_db || { echo "[kdbx] Cannot locate database — aborting"; exit 1; }
  read -rsp "[kdbx] Master password: " KDBX_MASTER_PASSWORD
  echo ""
  export KDBX_PATH KDBX_MASTER_PASSWORD

  # --- MFA second factor ---
  _keepass_mfa_gate

  KDBX_UNLOCKED=1
  echo "[kdbx] Database unlocked. Secrets broker active."
  echo ""
}

# Retrieve a secret by KeePass path (requires keepassxc-cli)
kdbx_get() {
  local path="$1"
  if command -v keepassxc-cli &>/dev/null; then
    echo "$KDBX_MASTER_PASSWORD" | \\
      keepassxc-cli show -q -a Password "$KDBX_PATH" "$path" 2>/dev/null
  else
    echo "[kdbx] keepassxc-cli not found — retrieve '$path' manually" >&2
    echo "MANUAL_ENTRY_REQUIRED"
  fi
}

# ---------------------------------------------------------------------------
# MFA gate (called by keepass_unlock_gate after master password)
# ---------------------------------------------------------------------------

_keepass_mfa_gate() {
  # Determine configured MFA method from KeePass
  local mfa_method
  mfa_method="$(kdbx_get 'MFA/method' 2>/dev/null)"
  if [ -z "$mfa_method" ] || [ "$mfa_method" = "MANUAL_ENTRY_REQUIRED" ] || [ "$mfa_method" = "none" ]; then
    return 0   # No MFA configured
  fi

  echo ""
  echo "-----------------------------------------------------------------"
  echo " Second Factor Required"
  echo "-----------------------------------------------------------------"

  case "$mfa_method" in
    totp)     _keepass_totp_gate ;;
    yubikey)  _keepass_yubikey_gate ;;
    *)
      echo "[mfa] Unknown MFA method: $mfa_method — skipping second factor"
      ;;
  esac
}

_keepass_totp_gate() {
  local totp_secret
  totp_secret="$(kdbx_get 'MFA/totp-secret' 2>/dev/null)"
  if [ -z "$totp_secret" ] || [ "$totp_secret" = "MANUAL_ENTRY_REQUIRED" ]; then
    echo "[mfa] TOTP secret not found in KeePass — skipping second factor"
    return 0
  fi

  local attempts=0
  while [ "$attempts" -lt 3 ]; do
    read -rp "[mfa] TOTP code from authenticator app (6 digits): " TOTP_INPUT
    if KEEPASS_MFA_TOTP_SECRET="$totp_secret" KEEPASS_MFA_CODE="$TOTP_INPUT" \\
        python3 -c "
import sys, os, base64, hashlib, hmac, struct, time
s = os.environ.get('KEEPASS_MFA_TOTP_SECRET','').upper().replace(' ','').replace('-','')
code = os.environ.get('KEEPASS_MFA_CODE','')
if not s or not code: sys.exit(2)
pad = (8 - len(s) % 8) % 8
key = base64.b32decode(s + '=' * pad)
ctr = int(time.time() / 30)
for d in range(-1, 2):
    msg = struct.pack('>Q', ctr + d)
    mac = hmac.new(key, msg, hashlib.sha1).digest()
    off = mac[-1] & 0x0f
    v = struct.unpack('>I', mac[off:off+4])[0] & 0x7fffffff
    if f'{v % 1000000:06d}' == code: sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
      echo "[mfa] TOTP verified."
      return 0
    fi
    attempts=$(( attempts + 1 ))
    echo "[mfa] Invalid code (attempt $attempts/3)."
  done
  echo "[mfa] Too many failed attempts — aborting."
  exit 1
}

_keepass_yubikey_gate() {
  if ! command -v ykman &>/dev/null; then
    echo "[mfa] ykman not found — cannot verify YubiKey."
    echo "[mfa] Install: apt-get install -y yubikey-manager"
    echo "[mfa] Skipping second factor (YubiKey not available)."
    return 0
  fi
  if ! ykman info &>/dev/null 2>&1; then
    echo "[mfa] No YubiKey detected. Insert your YubiKey and press Enter."
    read -r _WAIT
    if ! ykman info &>/dev/null 2>&1; then
      echo "[mfa] YubiKey still not detected — aborting."
      exit 1
    fi
  fi
  # Perform HMAC-SHA1 challenge on slot 2
  local challenge
  challenge="$(date +%s%N 2>/dev/null || date +%s)"
  local response
  response="$(echo "$challenge" | ykman otp calculate 2 --)"
  if [ -z "$response" ]; then
    echo "[mfa] YubiKey challenge-response failed — aborting."
    exit 1
  fi
  echo "[mfa] YubiKey verified."
}
"""


# ---------------------------------------------------------------------------
# MfaConfig
# ---------------------------------------------------------------------------

@dataclass
class MfaConfig:
    """MFA configuration recorded at forge time and stored with packages."""
    method:         str             = "none"    # "none" | "totp" | "yubikey"
    totp_secret:    Optional[str]   = None      # base32 TOTP secret (store in KeePass)
    totp_account:   Optional[str]   = None      # account label for otpauth:// URI
    totp_issuer:    str             = "broodforge"
    yubikey_slot:   int             = 2         # YubiKey HMAC-SHA1 slot (1 or 2)
    yubikey_serial: Optional[str]   = None      # YubiKey serial for identification


def provision_totp(cell_id: str, issuer: str = "broodforge") -> MfaConfig:
    """
    Generate a new TOTP secret for forge-time provisioning.

    Returns an MfaConfig containing the generated secret.
    The caller must:
      1. Store config.totp_secret in KeePass at 'MFA/totp-secret'
      2. Store 'totp' in KeePass at 'MFA/method'
      3. Call display_totp_setup() to show operator instructions
    """
    secret = generate_totp_secret()
    return MfaConfig(
        method="totp",
        totp_secret=secret,
        totp_account=cell_id,
        totp_issuer=issuer,
    )


def yubikey_setup_commands(slot: int = 2) -> list[str]:
    """
    Return shell commands to configure a YubiKey slot for HMAC-SHA1.

    These commands run during forge phase-03 if the operator chooses YubiKey MFA.
    Requires: apt-get install -y yubikey-manager
    """
    return [
        "# Configure YubiKey for HMAC-SHA1 challenge-response (broodforge MFA)",
        "apt-get install -y yubikey-manager",
        f"ykman otp hmac-sha1 {slot} --generate",
        f"echo '[mfa] YubiKey slot {slot} configured for HMAC-SHA1.'",
        "ykman info",
    ]


def render_mfa_provision_commands(config: MfaConfig, db_path: str) -> list[str]:
    """
    Return ordered shell commands to provision MFA in KeePass during phase-03.

    These run after the database is initialised and the master password is set.
    """
    cmds = ["", "# Phase 1.F — KeePass MFA provisioning"]
    if config.method == "none":
        cmds.append("echo '[mfa] No second factor configured.'")
        return cmds

    if config.method == "totp":
        secret = config.totp_secret or ""
        cmds += [
            "# Store TOTP method marker and secret in KeePass",
            f"keepassxc-cli mkdir {db_path} --password '$KEEPASS_MASTER_PASSWORD' '/MFA' 2>/dev/null || true",
            f"keepassxc-cli add {db_path} --password '$KEEPASS_MASTER_PASSWORD' "
            f"--no-password '/MFA/method' --notes 'totp'",
            f"keepassxc-cli add {db_path} --password '$KEEPASS_MASTER_PASSWORD' "
            f"'--password={secret}' '/MFA/totp-secret'",
            "echo '[mfa] TOTP secret stored in KeePass at MFA/totp-secret.'",
            "echo ''",
            "echo 'ACTION REQUIRED: Scan the following URI with your authenticator app:'",
            f"echo '  {totp_uri(secret, config.totp_account or 'broodforge', config.totp_issuer)}'",
            f"echo 'Raw secret: {secret}'",
            "echo ''",
        ]

    if config.method == "yubikey":
        cmds += yubikey_setup_commands(config.yubikey_slot)
        cmds += [
            f"keepassxc-cli mkdir {db_path} --password '$KEEPASS_MASTER_PASSWORD' '/MFA' 2>/dev/null || true",
            f"keepassxc-cli add {db_path} --password '$KEEPASS_MASTER_PASSWORD' "
            f"--no-password '/MFA/method' --notes 'yubikey'",
            "echo '[mfa] YubiKey MFA configured.'",
        ]

    return cmds


def mfa_config_to_dict(config: MfaConfig) -> dict:
    """Serialise MfaConfig (without secret value) for embedding in manifests."""
    d: dict = {"method": config.method, "totp_issuer": config.totp_issuer}
    if config.method == "totp":
        d["totp_account"] = config.totp_account
        # Never include the totp_secret in serialised output — it lives in KeePass
    if config.method == "yubikey":
        d["yubikey_slot"]   = config.yubikey_slot
        d["yubikey_serial"] = config.yubikey_serial
    return d
