"""Subprocess coverage for the local-only M08 Official Bot secret helper."""

import base64
import shutil
import subprocess
from pathlib import Path

import pytest

_POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
pytestmark = pytest.mark.skipif(_POWERSHELL is None, reason="PowerShell is not available")

_KEYS = ("ZALO_OFFICIAL_BOT_WEBHOOK_SECRET", "CHANNEL_IDENTITY_HMAC_KEY")
_EXTERNAL_TOKEN_KEY = "ZALO_OFFICIAL_BOT_TOKEN"
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "new_m08_secrets.ps1"


def _run_helper(env_file: Path) -> subprocess.CompletedProcess[str]:
    assert _POWERSHELL is not None
    return subprocess.run(
        [
            _POWERSHELL,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_SCRIPT),
            "-EnvFile",
            str(env_file),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _entries(env_file: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in env_file.read_text(encoding="utf-8").splitlines())


def test_secret_helper_generates_two_distinct_base64_values_without_output(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / "private" / "runtime.env"
    env_file.parent.mkdir()
    external_token = "manager-issued-token"
    env_file.write_text(
        f"{_EXTERNAL_TOKEN_KEY}={external_token}\nUNRELATED=value", encoding="utf-8"
    )

    result = _run_helper(env_file)

    assert result.returncode == 0
    entries = _entries(env_file)
    assert entries[_EXTERNAL_TOKEN_KEY] == external_token
    values = [entries[key] for key in _KEYS]
    assert len(set(values)) == 2
    for value in values:
        assert base64.b64encode(base64.b64decode(value, validate=True)).decode() == value
        assert len(base64.b64decode(value, validate=True)) == 32
        assert value not in result.stdout
        assert value not in result.stderr
    assert external_token not in result.stdout
    assert external_token not in result.stderr


def test_secret_helper_refuses_existing_target_without_mutating_values(tmp_path: Path) -> None:
    env_file = tmp_path / "runtime.env"
    existing_value = "already-present-test-value"
    original = f"{_KEYS[0]}={existing_value}\n{_EXTERNAL_TOKEN_KEY}=manager-token\n"
    env_file.write_text(original, encoding="utf-8")

    result = _run_helper(env_file)

    assert result.returncode != 0
    assert env_file.read_text(encoding="utf-8") == original
    assert existing_value not in result.stdout
    assert existing_value not in result.stderr


def test_secret_helper_never_handles_the_externally_issued_bot_token() -> None:
    source = _SCRIPT.read_text(encoding="utf-8")

    assert _EXTERNAL_TOKEN_KEY not in source
    assert "Write-Host" not in source
