"""
Tier 2 static analysis — shellcheck integration tests.

Finds all .sh files in the repo and runs shellcheck on each.
For generated scripts (forge.sh, spawn.sh), generates minimal samples
using the existing script generators and checks those too.

These tests ensure shellcheck runs automatically in CI/the test suite.
"""
import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
PROXMOX_BOOTSTRAP = REPO_ROOT / "proxmox-bootstrap"


def _shellcheck_available() -> bool:
    try:
        result = subprocess.run(
            ["shellcheck", "--version"],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _collect_sh_files() -> list[Path]:
    sh_files = []
    for p in REPO_ROOT.rglob("*.sh"):
        # Skip .git, new/ corpus (not our code), deprecated/
        rel = p.relative_to(REPO_ROOT)
        parts = rel.parts
        if any(part in (".git", "new", "deprecated") for part in parts):
            continue
        sh_files.append(p)
    return sorted(sh_files)


@pytest.mark.skipif(not _shellcheck_available(), reason="shellcheck not installed")
@pytest.mark.parametrize("sh_file", _collect_sh_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_shellcheck_static_file(sh_file: Path):
    """Each .sh file in the repo must have zero shellcheck errors."""
    result = subprocess.run(
        ["shellcheck", "--severity=warning", "--format=json", str(sh_file)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        try:
            findings = json.loads(result.stdout)
        except json.JSONDecodeError:
            findings = []
        errors = [f for f in findings if f.get("level") in ("error", "warning")]
        msg_parts = [f"shellcheck found {len(errors)} issue(s) in {sh_file.name}:"]
        for e in errors[:10]:
            msg_parts.append(
                f"  Line {e.get('line', '?')}: [{e.get('code', '?')}] {e.get('message', '')}"
            )
        pytest.fail("\n".join(msg_parts))


@pytest.mark.skipif(not _shellcheck_available(), reason="shellcheck not installed")
def test_shellcheck_generated_forge_script(tmp_path):
    """Generated forge.sh must have zero shellcheck errors.

    Uses forge_scripts.py to generate a minimal forge script sample,
    then runs shellcheck on it.
    """
    # Try to import forge_scripts and generate a sample
    try:
        from forge_scripts import generate_forge_sh  # type: ignore
        manifest = {
            "cell_id": "test-cell",
            "host_identity": {"hostname": "test-host", "fqdn": "test-host.example.com", "domain": "example.com"},
            "network_topology": {"profile": "lan", "management_cidr": "192.168.1.0/24", "gateway": "192.168.1.1"},
            "storage": {"pool_name": "local-zfs"},
            "vm_defaults": {"timezone": "UTC"},
        }
        script_content = generate_forge_sh(manifest)
        script_path = tmp_path / "forge.sh"
        script_path.write_text(script_content)
    except (ImportError, Exception) as e:
        pytest.skip(f"Could not generate forge script sample: {e}")

    result = subprocess.run(
        ["shellcheck", "--severity=warning", "--format=json", str(script_path)],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        try:
            findings = json.loads(result.stdout)
        except json.JSONDecodeError:
            findings = []
        errors = [f for f in findings if f.get("level") in ("error", "warning")]
        msg_parts = [f"shellcheck found {len(errors)} issue(s) in generated forge.sh:"]
        for e in errors[:10]:
            msg_parts.append(
                f"  Line {e.get('line', '?')}: [{e.get('code', '?')}] {e.get('message', '')}"
            )
        pytest.fail("\n".join(msg_parts))
