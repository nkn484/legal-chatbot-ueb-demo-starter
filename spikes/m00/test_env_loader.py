from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import env_loader


class EnvLoaderTests(unittest.TestCase):
    def load(self, content: bytes | str, environment: dict[str, str] | None = None) -> tuple[env_loader.EnvLoadStatus, dict[str, str]]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
            target = {} if environment is None else environment
            return env_loader.load_repo_env(path, environ=target), target

    def test_loads_only_allowed_keys_and_supports_matching_quotes(self) -> None:
        result, environment = self.load(
            "# local credentials\nSHINE_API_KEY=shine-private\nVBQPPL_TLS_VERIFY=false\nZALO_BOT_SECRET_TOKEN='secret private'\nZALO_BOT_TOKEN=\"bot:private\"\nZALO_BOT_WEBHOOK_URL=https://example.workers.dev/zalo-bot/webhook\nIGNORED_KEY=$(not-executed)\n"
        )

        self.assertEqual(result.status, "LOADED")
        self.assertEqual(result.loaded_keys, env_loader.ALLOWED_ENV_KEYS)
        self.assertEqual(environment, {"SHINE_API_KEY": "shine-private", "VBQPPL_TLS_VERIFY": "false", "ZALO_BOT_SECRET_TOKEN": "secret private", "ZALO_BOT_TOKEN": "bot:private", "ZALO_BOT_WEBHOOK_URL": "https://example.workers.dev/zalo-bot/webhook"})

    def test_nonempty_process_environment_takes_precedence(self) -> None:
        result, environment = self.load("SHINE_API_KEY=file-secret\nZALO_BOT_TOKEN=bot-secret\n", {"SHINE_API_KEY": "process-secret", "ZALO_BOT_TOKEN": ""})

        self.assertEqual(result.status, "LOADED")
        self.assertEqual(result.loaded_keys, frozenset({"ZALO_BOT_TOKEN"}))
        self.assertEqual(environment["SHINE_API_KEY"], "process-secret")
        self.assertEqual(environment["ZALO_BOT_TOKEN"], "bot-secret")

    def test_duplicate_or_malformed_allowed_lines_reject_atomically(self) -> None:
        malformed = (
            "SHINE_API_KEY=one\nSHINE_API_KEY=two\n",
            "SHINE_API_KEY =value\n",
            "export SHINE_API_KEY=value\n",
            "SHINE_API_KEY=${INTERPOLATED}\n",
            "SHINE_API_KEY=embedded\x00control\n",
            "ZALO_BOT_TOKEN='unterminated\n",
            "ZALO_BOT_SECRET_TOKEN=contains space\n",
        )
        for content in malformed:
            with self.subTest(content=content):
                target = {"UNCHANGED": "yes"}
                result, environment = self.load(content, target)
                self.assertEqual(result.status, "REJECTED")
                self.assertEqual(result.loaded_keys, frozenset())
                self.assertEqual(environment, {"UNCHANGED": "yes"})

    def test_unknown_keys_are_ignored_even_when_not_dotenv_syntax(self) -> None:
        result, environment = self.load("UNKNOWN without equals\nUNKNOWN_KEY=$(command)\nSHINE_API_KEY=allowed\n")

        self.assertEqual(result.status, "LOADED")
        self.assertEqual(result.loaded_keys, frozenset({"SHINE_API_KEY"}))
        self.assertEqual(environment, {"SHINE_API_KEY": "allowed"})

    def test_oversize_and_non_utf8_files_are_rejected(self) -> None:
        for content in (b"x" * (env_loader.MAX_DOTENV_BYTES + 1), b"SHINE_API_KEY=\xff"):
            with self.subTest(content_length=len(content)):
                result, environment = self.load(content)
                self.assertEqual(result.status, "REJECTED")
                self.assertEqual(result.loaded_keys, frozenset())
                self.assertEqual(environment, {})

    def test_status_never_contains_secret_values(self) -> None:
        secret = "secret-value-must-not-escape"
        result, _environment = self.load(f"SHINE_API_KEY={secret}\n")

        safe_output = json.dumps({"status": result.status, "loaded_keys": sorted(result.loaded_keys)})
        self.assertNotIn(secret, safe_output)

    def test_missing_file_has_a_safe_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = env_loader.load_repo_env(Path(directory) / ".env", environ={})

        self.assertEqual(result, env_loader.EnvLoadStatus("MISSING", frozenset()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
