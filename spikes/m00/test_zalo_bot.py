from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zalo_bot


class ZaloBotTests(unittest.TestCase):
    token = "12345689:abc-xyz"
    secret = "secret-private-123"

    def client(self, handler: httpx.MockTransport) -> httpx.Client:
        return httpx.Client(transport=handler, trust_env=False, follow_redirects=False)

    def test_get_me_posts_once_to_official_encoded_path_and_sanitizes_success(self) -> None:
        requests: list[httpx.Request] = []
        token = f"{self.token}/private?query"

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json={"ok": True, "result": {"id": "private-id", "account_type": "official_account", "can_join_groups": True, "name": "private"}})

        with patch.dict(os.environ, {"ZALO_BOT_TOKEN": token}, clear=False), self.client(httpx.MockTransport(handler)) as client:
            result = zalo_bot.probe_get_me(client=client)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].method, "POST")
        self.assertEqual(requests[0].url.raw_path, b"/bot12345689:abc-xyz%2Fprivate%3Fquery/getMe")
        self.assertEqual(requests[0].content, b"")
        self.assertEqual(result["outcome"], "PASS")
        self.assertTrue(result["bot_id_present"])
        self.assertNotIn("private-id", json.dumps(result))
        self.assertNotIn(token, json.dumps(result))

    def test_get_me_blocks_missing_invalid_transport_and_bad_response_without_leakage(self) -> None:
        cases: list[tuple[str | None, Any, str]] = [
            (None, None, "missing_token"),
            ("bad\x00token", None, "invalid_token"),
            (self.token, httpx.Response(200, content=b"not-json"), "invalid_json"),
            (self.token, httpx.Response(200, content=b"x" * (zalo_bot.MAX_RESPONSE_BYTES + 1)), "response_too_large"),
        ]
        for token, response, error in cases:
            with self.subTest(error=error):
                calls = 0
                def handler(request: httpx.Request) -> httpx.Response:
                    nonlocal calls
                    calls += 1
                    if response is None:
                        raise httpx.ConnectError(f"private {self.token}", request=request)
                    return response
                environment = {} if token is None else {"ZALO_BOT_TOKEN": token}
                with patch.object(zalo_bot.os, "environ", environment), self.client(httpx.MockTransport(handler)) as client:
                    result = zalo_bot.probe_get_me(client=client)
                self.assertEqual(result["error_code"], error)
                self.assertNotIn(self.token, json.dumps(result))
                if token is None or "\x00" in (token or ""):
                    self.assertEqual(calls, 0)

    def test_bot_api_sends_only_fixed_send_message_request_and_sanitizes_failure(self) -> None:
        requests: list[httpx.Request] = []
        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(503, json={"ok": False, "error_code": "UPSTREAM_FAILURE", "description": "private"})
        with self.client(httpx.MockTransport(handler)) as client:
            result = zalo_bot.BotApi(self.token, client).send_message("private-chat", "ECHO: private text")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, f"/bot{self.token}/sendMessage")
        self.assertEqual(json.loads(requests[0].content), {"chat_id": "private-chat", "text": "ECHO: private text"})
        self.assertEqual((result.status, result.ok, result.error_code), (503, False, "UPSTREAM_FAILURE"))
        self.assertNotIn("private", json.dumps(result.result))

    def _server(self, api: Any, lines: list[str]) -> tuple[Any, threading.Thread, zalo_bot.NgrokEchoState]:
        state = zalo_bot.NgrokEchoState(self.secret, api, lines.append)
        server = zalo_bot.ThreadingHTTPServer(("127.0.0.1", 0), zalo_bot.ngrok_echo_handler(state))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, state

    def _post(self, server: Any, payload: object, *, secret: str | None = None, content_type: str = "application/json") -> int:
        body = json.dumps(payload).encode()
        connection = HTTPConnection("127.0.0.1", server.server_port)
        headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
        if secret is not None:
            headers["X-Bot-Api-Secret-Token"] = secret
        connection.request("POST", zalo_bot.WEBHOOK_PATH, body, headers)
        status = connection.getresponse().status
        connection.close()
        return status

    def _message(self, text: str = "private text") -> dict[str, object]:
        return {"chat": {"chat_type": "PRIVATE", "id": "private-chat"}, "from": {"id": "private-sender", "is_bot": False}, "message_id": "private-source", "text": text}

    def test_webhook_authentication_filters_and_echoes_one_measured_top_level_event(self) -> None:
        class Api:
            sent: list[tuple[str, str]] = []
            def send_message(self, chat_id: str, text: str) -> zalo_bot.ApiCall:
                self.sent.append((chat_id, text))
                return zalo_bot.ApiCall(200, True, None, {"message_id": "private-outbound"})
        api, lines = Api(), []
        server, thread, state = self._server(api, lines)
        try:
            top = {"event_name": "message.text.received", "message": self._message()}
            self.assertEqual(self._post(server, top, secret="wrong"), 401)
            self.assertEqual(self._post(server, top, secret=self.secret, content_type="text/plain"), 415)
            group = {"event_name": "message.text.received", "message": {**self._message(), "chat": {"chat_type": "GROUP", "id": "private-chat"}}}
            self.assertEqual(self._post(server, group, secret=self.secret), 200)
            self.assertEqual(self._post(server, top, secret=self.secret), 200)
            self.assertEqual(self._post(server, {"event_name": "message.text.received", "message": self._message("second private")}, secret=self.secret), 200)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertEqual(api.sent, [("private-chat", "ECHO: private text")])
        self.assertTrue(state.event.is_set())
        evidence = [json.loads(line) for line in lines]
        received = [item for item in evidence if item["operation"] == "webhook_receive"]
        self.assertEqual([item.get("ignore_reason") for item in received], ["chat_not_private", None, "duplicate"])
        self.assertEqual(received[1]["envelope_kind"], "top_level")
        self.assertEqual(len([item for item in evidence if item["operation"] == "ngrok_echo_event"]), 1)
        output = "\n".join(lines)
        for value in (self.secret, "wrong", "private-chat", "private-sender", "private-source", "private text", "private-outbound"):
            self.assertNotIn(value, output)

    def test_documented_result_envelope_and_fixed_unknown_diagnostics_do_not_leak(self) -> None:
        message = self._message("private documented text")
        for payload, kind, accepted in (
            ({"ok": True, "result": {"event_name": "message.text.received", "message": message}}, "documented_result", True),
            ({"data": {"event_name": "message.text.received", "message": message}, "private": "value"}, "unsupported", False),
        ):
            with self.subTest(kind=kind):
                inspection = zalo_bot._inspect_authenticated_event(payload)
                evidence = zalo_bot._receive_evidence(inspection, inspection.ignore_reason)
                self.assertEqual(evidence["envelope_kind"], kind)
                self.assertEqual(evidence["supported_event"], accepted)
                self.assertNotIn("private documented text", json.dumps(evidence))
                self.assertNotIn("value", json.dumps(evidence))

    def test_webhook_acknowledges_one_outbound_failure_without_retry(self) -> None:
        class FailingApi:
            calls = 0
            def send_message(self, _chat_id: str, _text: str) -> zalo_bot.ApiCall:
                self.calls += 1
                return zalo_bot.ApiCall(503, False, "UPSTREAM_FAILURE")
        api, lines = FailingApi(), []
        server, thread, state = self._server(api, lines)
        try:
            payload = {"ok": True, "result": {"event_name": "message.text.received", "message": self._message()}}
            self.assertEqual(self._post(server, payload, secret=self.secret), 200)
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertEqual(api.calls, 1)
        self.assertTrue(state.event.is_set())
        outbound = next(json.loads(line) for line in lines if "ngrok_echo_event" in line)
        self.assertEqual((outbound["outcome"], outbound["status"], outbound["error_code"]), ("BLOCKED_EXTERNAL", 503, "UPSTREAM_FAILURE"))

    def test_ngrok_config_check_suppresses_output_and_prevents_start_on_failure(self) -> None:
        commands: list[tuple[tuple[object, ...], dict[str, object]]] = []
        def failed_run(*args: object, **kwargs: object) -> object:
            commands.append((args, kwargs)); return type("Completed", (), {"returncode": 1})()
        with patch.dict(os.environ, {"ZALO_BOT_TOKEN": self.token, "ZALO_BOT_SECRET_TOKEN": self.secret}, clear=False):
            result = zalo_bot.run_ngrok_echo(timeout_seconds=1, emit=lambda _line: None, which=lambda _name: "private-ngrok", run=failed_run, popen=lambda *_args, **_kwargs: self.fail("must not start"), server_factory=lambda *_args: self.fail("must not serve"))
        self.assertEqual(result["error_code"], "ngrok_config_invalid")
        self.assertEqual(commands[0][0][0], ["private-ngrok", "config", "check"])
        self.assertEqual(commands[0][1]["stdout"], zalo_bot.subprocess.DEVNULL)
        self.assertEqual(commands[0][1]["stderr"], zalo_bot.subprocess.DEVNULL)

    def test_ngrok_discovery_accepts_only_one_https_tunnel_for_local_port(self) -> None:
        payload = {"tunnels": [{"public_url": "https://wrong.example", "config": {"addr": "localhost:9999"}}, {"public_url": "https://right.ngrok-free.app", "config": {"addr": "http://127.0.0.1:8787"}}]}
        with self.client(httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))) as client:
            self.assertEqual(zalo_bot._poll_ngrok_agent(client, 8787, sleep=lambda _seconds: None), "https://right.ngrok-free.app")
        ambiguous = {"tunnels": [{"public_url": "https://one.ngrok.app", "config": {"addr": "localhost:8787"}}, {"public_url": "https://two.ngrok.app", "config": {"addr": "localhost:8787"}}]}
        self.assertIsNone(zalo_bot.select_ngrok_public_url(ambiguous, 8787))
        self.assertIsNone(zalo_bot.select_ngrok_public_url({"tunnels": [{"public_url": "http://bad.ngrok.app", "config": {"addr": "localhost:8787"}}]}, 8787))

    def test_ngrok_env_update_preserves_secrets_and_replaces_only_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("ZALO_BOT_TOKEN=private-token\nZALO_BOT_SECRET_TOKEN=private-secret\nZALO_BOT_WEBHOOK_URL=https://old.example\nKEEP=value\n", encoding="utf-8")
            self.assertTrue(zalo_bot.update_ngrok_webhook_url(path, "https://chosen.ngrok-free.app"))
            content = path.read_text(encoding="utf-8")
        self.assertEqual(content, "ZALO_BOT_TOKEN=private-token\nZALO_BOT_SECRET_TOKEN=private-secret\nZALO_BOT_WEBHOOK_URL=https://chosen.ngrok-free.app/zalo-bot/webhook\nKEEP=value\n")

    def test_ngrok_echo_updates_env_sends_once_and_cleans_up(self) -> None:
        real_server, servers, calls, lines = zalo_bot.ThreadingHTTPServer, [], [], []
        class Process:
            stopped = False
            def poll(self) -> int | None: return 0 if self.stopped else None
            def terminate(self) -> None: self.stopped = True
            def wait(self, timeout: float) -> None: self.stopped = True
        process = Process()
        def api_handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={"ok": True, "result": {"message_id": "private-id"}})
        def server_factory(_address: object, handler: Any) -> Any:
            server = real_server(("127.0.0.1", 0), handler); servers.append(server); return server
        def start_ngrok(_args: list[str], **_kwargs: object) -> Process:
            def deliver() -> None:
                payload = {"event_name": "message.text.received", "message": self._message()}
                self._post(servers[0], payload, secret=self.secret)
            threading.Thread(target=deliver, daemon=True).start()
            return process
        agent = {"tunnels": [{"public_url": "https://chosen.ngrok-free.app", "config": {"addr": "localhost:8787"}}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"; path.write_text("KEEP=private-keep\n", encoding="utf-8")
            with patch.dict(os.environ, {"ZALO_BOT_TOKEN": self.token, "ZALO_BOT_SECRET_TOKEN": self.secret}, clear=False), self.client(httpx.MockTransport(api_handler)) as api_client, self.client(httpx.MockTransport(lambda _request: httpx.Response(200, json=agent))) as agent_client:
                result = zalo_bot.run_ngrok_echo(timeout_seconds=2, client=api_client, agent_client=agent_client, emit=lines.append, which=lambda _name: "private-ngrok", run=lambda *_a, **_k: type("Done", (), {"returncode": 0})(), popen=start_ngrok, env_path=path, server_factory=server_factory)
            content = path.read_text(encoding="utf-8")
        self.assertEqual(result, {"operation": "ngrok_echo", "outcome": "PASS", "ok": True})
        self.assertEqual(calls, ["sendMessage"])
        self.assertTrue(process.stopped)
        self.assertIn("ZALO_BOT_WEBHOOK_URL=https://chosen.ngrok-free.app/zalo-bot/webhook", content)
        output = "\n".join(lines)
        self.assertNotIn(self.token, output); self.assertNotIn(self.secret, output); self.assertNotIn("private-keep", output)

    def test_ngrok_echo_timeout_cleans_up_without_outbound_call(self) -> None:
        class Server:
            def serve_forever(self) -> None: pass
            def shutdown(self) -> None: pass
            def server_close(self) -> None: pass
        class Process:
            stopped = False
            def poll(self) -> int | None: return None if not self.stopped else 0
            def terminate(self) -> None: self.stopped = True
            def wait(self, timeout: float) -> None: self.stopped = True
        process, lines = Process(), []
        agent = {"tunnels": [{"public_url": "https://timeout.ngrok.app", "config": {"addr": "localhost:8787"}}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"; path.write_text("X=1\n")
            with patch.dict(os.environ, {"ZALO_BOT_TOKEN": self.token, "ZALO_BOT_SECRET_TOKEN": self.secret}, clear=False), self.client(httpx.MockTransport(lambda request: self.fail(f"unexpected {request.url}"))) as api_client, self.client(httpx.MockTransport(lambda _request: httpx.Response(200, json=agent))) as agent_client:
                result = zalo_bot.run_ngrok_echo(timeout_seconds=1, client=api_client, agent_client=agent_client, emit=lines.append, which=lambda _name: "ngrok", run=lambda *_a, **_k: type("Done", (), {"returncode": 0})(), popen=lambda *_a, **_k: process, env_path=path, server_factory=lambda *_a: Server())
        self.assertEqual(result, {"operation": "ngrok_echo", "outcome": "NOT_MEASURED", "ok": False, "error_code": "event_not_received"})
        self.assertTrue(process.stopped)

    def test_cli_loads_dotenv_and_exposes_only_final_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"; path.write_text("ZALO_BOT_TOKEN=dotenv-private\n")
            observed: list[str | None] = []
            with patch.dict(os.environ, {"ZALO_BOT_TOKEN": ""}, clear=False), patch.object(zalo_bot, "probe_get_me", lambda: observed.append(os.environ.get("ZALO_BOT_TOKEN")) or {"outcome": "PASS"}):
                self.assertEqual(zalo_bot.main(["get-me"], dotenv_path=path), 0)
            self.assertEqual(observed, ["dotenv-private"])
        observed_args: list[dict[str, object]] = []
        with patch.object(zalo_bot, "run_ngrok_echo", lambda **kwargs: observed_args.append(kwargs) or {"outcome": "PASS"}):
            self.assertEqual(zalo_bot.main(["ngrok-echo", "--timeout-seconds", "2", "--port", "8788"], dotenv_path=Path("test.env")), 0)
        self.assertEqual(observed_args, [{"timeout_seconds": 2, "port": 8788, "env_path": Path("test.env")}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
