"""Static Compose coverage for the M08 Official Zalo Bot deployment lane."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL_ENVIRONMENT = (
    "CHANNEL_ENABLED",
    "ZALO_OFFICIAL_BOT_TOKEN",
    "ZALO_OFFICIAL_BOT_WEBHOOK_SECRET",
    "CHANNEL_IDENTITY_HMAC_KEY",
    "CHANNEL_MAX_BODY_BYTES",
    "CHANNEL_MAX_OUTBOUND_CHARS",
    "CHANNEL_OUTBOUND_MAX_ATTEMPTS",
    "CHANNEL_BINDING_LEASE_SECONDS",
    "CHANNEL_TIMEOUT_SECONDS",
    "DEMO_CORPUS_ENABLED",
    "DEMO_CORPUS_RETRIEVAL_SOURCE_IDS",
)


def _compose_config(*files: str) -> dict[str, object]:
    environment = os.environ.copy()
    for name in OFFICIAL_ENVIRONMENT:
        environment[name] = ""
    environment.update(
        {
            "POSTGRES_DB": "compose_test",
            "POSTGRES_USER": "compose_user",
            "POSTGRES_PASSWORD": "compose-password",
            "DATABASE_URL_DOCKER": (
                "postgresql+asyncpg://compose_user:compose-password@db:5432/compose_test"
            ),
            "LLM_PROVIDER": "",
            "LLM_BASE_URL": "",
            "LLM_MODEL": "",
            "LLM_API_KEY": "",
            "SHINE_API_KEY": "",
        }
    )
    command = ["docker", "compose"]
    for file in files:
        command.extend(("-f", file))
    command.extend(("config", "--format", "json"))
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _services(config: dict[str, object]) -> dict[str, dict[str, Any]]:
    return cast(dict[str, dict[str, Any]], config["services"])


def _environment(service: dict[str, Any]) -> dict[str, str]:
    return cast(dict[str, str], service["environment"])


def _assert_personal_artifacts_absent(config: dict[str, object]) -> None:
    rendered = json.dumps(config).casefold()
    for forbidden in (
        "zalo-personal",
        "zca-js",
        "node",
        "qr",
        "session",
        "cookie",
        "imei",
        "user-agent",
        "bridge",
        "m08_private",
        "runtime_dir",
    ):
        assert forbidden not in rendered


def test_base_compose_config_is_disabled_and_has_only_base_services() -> None:
    config = _compose_config("compose.yaml")
    services = _services(config)
    api_environment = _environment(services["api"])

    assert set(services) == {"api", "db", "migrate"}
    assert "  ingest:\n" in (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert {name for name, service in services.items() if "ports" in service} == {"api", "db"}
    assert api_environment["CHANNEL_ENABLED"] == "false"
    assert api_environment["ZALO_OFFICIAL_BOT_TOKEN"] == ""
    assert api_environment["ZALO_OFFICIAL_BOT_WEBHOOK_SECRET"] == ""
    assert api_environment["CHANNEL_IDENTITY_HMAC_KEY"] == ""
    assert api_environment["CHANNEL_MAX_BODY_BYTES"] == "65536"
    assert api_environment["CHANNEL_MAX_OUTBOUND_CHARS"] == "1994"
    assert api_environment["CHANNEL_OUTBOUND_MAX_ATTEMPTS"] == "1"
    assert api_environment["CHANNEL_BINDING_LEASE_SECONDS"] == "120"
    assert api_environment["CHANNEL_TIMEOUT_SECONDS"] == "30"
    assert api_environment["LLM_PROVIDER"] == "shineshop"
    assert {"LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "SHINE_API_KEY"} <= set(api_environment)
    assert api_environment["RETRIEVAL_PLANNER_ENABLED"] == "false"
    assert api_environment["RETRIEVAL_LEXICAL_REPAIR_ENABLED"] == "false"
    assert api_environment["RETRIEVAL_PLANNER_MAX_INPUT_CHARS"] == "900"
    assert api_environment["RETRIEVAL_PLANNER_MAX_OUTPUT_TOKENS"] == "96"
    assert api_environment["RETRIEVAL_PLANNER_TIMEOUT_SECONDS"] == "3"
    assert api_environment["RETRIEVAL_PLANNER_MAX_EXPANSION_TERMS"] == "4"
    assert api_environment["RETRIEVAL_PLANNER_MAX_PHRASES"] == "2"
    assert api_environment["RETRIEVAL_PLANNER_MAX_QUERY_COUNT"] == "2"
    assert api_environment["DEMO_CORPUS_ENABLED"] == "false"
    assert api_environment["DEMO_CORPUS_RETRIEVAL_SOURCE_IDS"] == "VBQPPL,VNU,UEB"
    assert "  demo-corpus:\n" in (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "m08_private" not in cast(dict[str, Any], config["networks"])
    _assert_personal_artifacts_absent(config)


def test_m08_overlay_only_enables_official_channel_without_secret_values() -> None:
    config = _compose_config("compose.yaml", "compose.m08.yaml")
    api_environment = _environment(_services(config)["api"])

    assert api_environment["CHANNEL_ENABLED"] == "true"
    assert api_environment["ZALO_OFFICIAL_BOT_TOKEN"] == ""
    assert api_environment["ZALO_OFFICIAL_BOT_WEBHOOK_SECRET"] == ""
    assert api_environment["CHANNEL_IDENTITY_HMAC_KEY"] == ""
    _assert_personal_artifacts_absent(config)
