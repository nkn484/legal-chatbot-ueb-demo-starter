"""Bounded M00 Zalo Bot get-me probe and ngrok webhook echo."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from unicodedata import category
from urllib.parse import quote, urlsplit

import httpx

from env_loader import load_repo_env, repo_env_path


BOT_API_ORIGIN = "https://bot-api.zaloplatforms.com"
WEBHOOK_PATH = "/zalo-bot/webhook"
MAX_RESPONSE_BYTES = 64 * 1024
MAX_WEBHOOK_BODY_BYTES = 64 * 1024
MAX_TOKEN_CHARS = 512
MAX_SECRET_TOKEN_CHARS = 256
MIN_SECRET_TOKEN_CHARS = 8
MAX_ID_CHARS = 256
MAX_ECHO_TEXT_CHARS = 1_994
MAX_RECEIVE_DIAGNOSTICS = 10
DEFAULT_TUNNEL_PORT = 8787
DEFAULT_TUNNEL_TIMEOUT_SECONDS = 300
MIN_TUNNEL_TIMEOUT_SECONDS = 1
MAX_TUNNEL_TIMEOUT_SECONDS = 600
NGROK_CONFIG_TIMEOUT_SECONDS = 10.0
NGROK_AGENT_STARTUP_TIMEOUT_SECONDS = 30.0
NGROK_AGENT_MAX_ATTEMPTS = 30
NGROK_AGENT_POLL_INTERVAL_SECONDS = 0.25
MAX_NGROK_ADDRESS_CHARS = 512
NGROK_AGENT_API_URL = "http://127.0.0.1:4040/api/tunnels"
TIMEOUT = httpx.Timeout(10.0, connect=3.0)
NGROK_AGENT_TIMEOUT = httpx.Timeout(2.0, connect=1.0)


def _duration_ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))


def _has_control_characters(value: str) -> bool:
    return any(category(character) == "Cc" for character in value)


def _bounded_string(value: Any, limit: int, *, controls_allowed: bool = False) -> str | None:
    if not isinstance(value, str) or not value or len(value) > limit:
        return None
    return value if controls_allowed or not _has_control_characters(value) else None


def _safe_error_code(payload: Any) -> int | str | None:
    candidate = payload.get("error_code") if isinstance(payload, Mapping) else None
    if candidate is None and isinstance(payload, Mapping) and isinstance(payload.get("error"), Mapping):
        candidate = payload["error"].get("code")
    if isinstance(candidate, int) and not isinstance(candidate, bool) and -9_999_999 <= candidate <= 9_999_999:
        return candidate
    if isinstance(candidate, str) and len(candidate) <= 64 and candidate.replace("_", "").replace("-", "").isalnum():
        return candidate
    return None


def _read_limited(response: httpx.Response, limit: int = MAX_RESPONSE_BYTES) -> bytes | None:
    try:
        if (length := response.headers.get("content-length")) is not None and int(length) > limit:
            return None
    except ValueError:
        pass
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _encoded_token_path(token: str) -> str:
    return f"{BOT_API_ORIGIN}/bot{quote(token, safe=':-._~')}"


def _failure(*, status: int | None = None, error_code: int | str | None = None) -> dict[str, object]:
    result: dict[str, object] = {"outcome": "BLOCKED_EXTERNAL", "status": status, "ok": False}
    if error_code is not None:
        result["error_code"] = error_code
    return result


def probe_get_me(*, client: httpx.Client | None = None) -> dict[str, object]:
    """Make one safe, retry-free request to the official getMe endpoint."""

    started = time.monotonic()
    token = os.environ.get("ZALO_BOT_TOKEN")
    if not token:
        return _failure(error_code="missing_token")
    if len(token) > MAX_TOKEN_CHARS or _has_control_characters(token):
        return _failure(error_code="invalid_token")
    owns_client = client is None
    active_client = client or httpx.Client(timeout=TIMEOUT, trust_env=False, follow_redirects=False)
    try:
        try:
            with active_client.stream("POST", f"{_encoded_token_path(token)}/getMe") as response:
                status, body = response.status_code, _read_limited(response)
        except httpx.HTTPError:
            return _failure(error_code="transport_error")
        if body is None:
            return _failure(status=status, error_code="response_too_large")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _failure(status=status, error_code="invalid_json")
        if not isinstance(payload, Mapping):
            return _failure(status=status, error_code="json_object_required")
        if not 200 <= status < 300 or payload.get("ok") is not True:
            return _failure(status=status, error_code=_safe_error_code(payload))
        details: Mapping[str, Any] = payload["result"] if isinstance(payload.get("result"), Mapping) else {}
        bot_id = details.get("id")
        account_type = details.get("account_type")
        return {
            "outcome": "PASS", "status": status, "duration_ms": _duration_ms(started), "ok": True,
            "bot_id_present": isinstance(bot_id, (str, int)) and not isinstance(bot_id, bool) and bool(str(bot_id)),
            "account_type": account_type if isinstance(account_type, str) and len(account_type) <= 64 and account_type.replace("_", "").isalnum() else "unknown",
            "can_join_groups": details.get("can_join_groups") is True,
        }
    finally:
        if owns_client:
            active_client.close()


@dataclass(frozen=True)
class ApiCall:
    status: int | None
    ok: bool
    error_code: int | str | None
    result: Mapping[str, Any] | None = None


class SendMessageApi(Protocol):
    def send_message(self, chat_id: str, text: str) -> ApiCall: ...


class BotApi:
    """The sole Bot API operation used by the final echo path."""

    def __init__(self, token: str, client: httpx.Client) -> None:
        self._token, self._client = token, client

    def send_message(self, chat_id: str, text: str) -> ApiCall:
        try:
            with self._client.stream("POST", f"{_encoded_token_path(self._token)}/sendMessage", json={"chat_id": chat_id, "text": text}) as response:
                status, body = response.status_code, _read_limited(response)
        except httpx.HTTPError:
            return ApiCall(None, False, "transport_error")
        if body is None:
            return ApiCall(status, False, "response_too_large")
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ApiCall(status, False, "invalid_json")
        if not isinstance(payload, Mapping):
            return ApiCall(status, False, "json_object_required")
        result = payload.get("result") if isinstance(payload.get("result"), Mapping) else None
        if not 200 <= status < 300 or payload.get("ok") is not True:
            return ApiCall(status, False, _safe_error_code(payload), result)
        return ApiCall(status, True, None, result)


@dataclass(frozen=True)
class EventInspection:
    chat_id: str | None
    text: str | None
    diagnostic: dict[str, object]
    ignore_reason: str | None


def _inspect_authenticated_event(payload: Any) -> EventInspection:
    """Accept only the measured top-level or documented result event envelopes."""

    outer = payload if isinstance(payload, Mapping) else None
    result = outer.get("result") if outer is not None else None
    top_level = outer is not None and outer.get("event_name") == "message.text.received"
    documented_result = outer is not None and outer.get("ok") is True and isinstance(result, Mapping) and result.get("event_name") == "message.text.received"
    if documented_result and isinstance(result, Mapping):
        message, envelope_kind = result.get("message"), "documented_result"
    elif top_level and outer is not None:
        message, envelope_kind = outer.get("message"), "top_level"
    else:
        message, envelope_kind = None, "unsupported"
    chat = message.get("chat") if isinstance(message, Mapping) else None
    sender = message.get("from") if isinstance(message, Mapping) else None
    chat_id = _bounded_string(chat.get("id"), MAX_ID_CHARS) if isinstance(chat, Mapping) else None
    sender_id = _bounded_string(sender.get("id"), MAX_ID_CHARS) if isinstance(sender, Mapping) else None
    message_id = _bounded_string(message.get("message_id"), MAX_ID_CHARS) if isinstance(message, Mapping) else None
    text = _bounded_string(message.get("text"), MAX_ECHO_TEXT_CHARS, controls_allowed=True) if isinstance(message, Mapping) else None
    sender_is_bot = isinstance(sender, Mapping) and sender.get("is_bot") is True
    diagnostic: dict[str, object] = {
        "operation": "webhook_receive", "authenticated": True, "envelope_kind": envelope_kind,
        "outer_ok_true": outer is not None and outer.get("ok") is True,
        "top_event_name_present": outer is not None and "event_name" in outer,
        "top_event_supported": top_level,
        "top_message_object": outer is not None and isinstance(outer.get("message"), Mapping),
        "result_object": isinstance(result, Mapping),
        "result_event_name_present": isinstance(result, Mapping) and "event_name" in result,
        "result_event_supported": documented_result,
        "result_message_object": isinstance(result, Mapping) and isinstance(result.get("message"), Mapping),
        "message_object": isinstance(message, Mapping), "text_present": text is not None,
        "message_id_present": message_id is not None, "sender_id_present": sender_id is not None,
        "chat_id_present": chat_id is not None, "sender_is_bot": sender_is_bot, "supported_event": False,
    }
    if envelope_kind == "unsupported":
        reason = "event_name_unsupported" if outer is not None and "event_name" in outer else "outer_ok_not_true"
    elif not isinstance(message, Mapping):
        reason = "message_not_object"
    elif not isinstance(chat, Mapping) or chat.get("chat_type") != "PRIVATE":
        reason = "chat_not_private"
    elif not isinstance(sender, Mapping):
        reason = "sender_not_object"
    elif sender_is_bot:
        reason = "sender_is_bot"
    elif chat_id is None or sender_id is None or message_id is None or text is None:
        reason = "missing_required_field"
    else:
        reason = None
    return EventInspection(chat_id, text, diagnostic, reason)


def _receive_evidence(inspection: EventInspection, ignore_reason: str | None) -> dict[str, object]:
    evidence = dict(inspection.diagnostic)
    evidence["supported_event"] = ignore_reason is None
    evidence["outcome"] = "PASS" if ignore_reason is None else "NOT_MEASURED"
    if ignore_reason is not None:
        evidence["ignore_reason"] = ignore_reason
    return evidence


def _send_evidence(call: ApiCall, duration_ms: int) -> dict[str, object]:
    message_id = call.result.get("message_id") if call.result else None
    evidence: dict[str, object] = {"operation": "ngrok_echo_event", "outcome": "PASS" if call.ok else "BLOCKED_EXTERNAL", "status": call.status, "ok": call.ok, "duration_ms": duration_ms, "message_id_present": _bounded_string(message_id, MAX_ID_CHARS) is not None, "inbound_authenticated": True, "supported_event": True, "source_message_id_present": True}
    if call.error_code is not None:
        evidence["error_code"] = call.error_code
    return evidence


class NgrokEchoState:
    def __init__(self, secret_token: str, api: SendMessageApi, emit: Callable[[str], None]) -> None:
        self.secret_token, self.api, self.emit = secret_token, api, emit
        self.event = threading.Event()
        self._lock = threading.Lock()
        self._claimed = False
        self._diagnostics = 0
        self.send_succeeded = False

    def claim_event(self) -> bool:
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True

    def receive(self, evidence: dict[str, object]) -> None:
        with self._lock:
            if self._diagnostics >= MAX_RECEIVE_DIAGNOSTICS:
                return
            self._diagnostics += 1
        self.emit(json.dumps(evidence, sort_keys=True, separators=(",", ":")))

    def record_send(self, call: ApiCall) -> None:
        with self._lock:
            self.send_succeeded = call.ok
        self.event.set()


def _handler_response(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: bytes = b'{"status":"ok"}') -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)


def ngrok_echo_handler(state: NgrokEchoState) -> type[BaseHTTPRequestHandler]:
    class NgrokEchoHandler(BaseHTTPRequestHandler):
        server_version, sys_version = "M00ZaloBotNgrok", ""

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            _handler_response(self, HTTPStatus.OK if self.path == "/health" else HTTPStatus.NOT_FOUND, b'{"status":"ok"}' if self.path == "/health" else b'{"error":"not_found"}')

        def do_POST(self) -> None:  # noqa: N802
            if self.path != WEBHOOK_PATH:
                _handler_response(self, HTTPStatus.NOT_FOUND, b'{"error":"not_found"}')
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                _handler_response(self, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, b'{"error":"json_required"}')
                return
            supplied = self.headers.get("X-Bot-Api-Secret-Token")
            if not supplied or not hmac.compare_digest(supplied, state.secret_token):
                _handler_response(self, HTTPStatus.UNAUTHORIZED, b'{"error":"unauthorized"}')
                return
            try:
                length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                length = -1
            if length < 0:
                _handler_response(self, HTTPStatus.LENGTH_REQUIRED, b'{"error":"content_length_required"}')
                return
            if length > MAX_WEBHOOK_BODY_BYTES:
                _handler_response(self, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b'{"error":"body_too_large"}')
                return
            body = self.rfile.read(length)
            if len(body) != length:
                _handler_response(self, HTTPStatus.BAD_REQUEST, b'{"error":"incomplete_body"}')
                return
            try:
                inspection = _inspect_authenticated_event(json.loads(body))
            except (UnicodeDecodeError, json.JSONDecodeError):
                _handler_response(self, HTTPStatus.BAD_REQUEST, b'{"error":"invalid_json"}')
                return
            reason = inspection.ignore_reason
            if reason is None and not state.claim_event():
                reason = "duplicate"
            state.receive(_receive_evidence(inspection, reason))
            if reason is None and inspection.chat_id is not None and inspection.text is not None:
                started = time.monotonic()
                call = state.api.send_message(inspection.chat_id, f"ECHO: {inspection.text}")
                state.emit(json.dumps(_send_evidence(call, _duration_ms(started)), sort_keys=True, separators=(",", ":")))
                state.record_send(call)
            _handler_response(self, HTTPStatus.OK)

    return NgrokEchoHandler


def _find_ngrok(which: Callable[[str], str | None] = shutil.which) -> str | None:
    return which("ngrok")


def _ngrok_config_is_valid(executable: str, *, run: Any = subprocess.run) -> bool:
    try:
        completed = run([executable, "config", "check"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=NGROK_CONFIG_TIMEOUT_SECONDS, check=False, shell=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _start_ngrok(executable: str, port: int, *, popen: Any = subprocess.Popen) -> Any | None:
    try:
        return popen([executable, "http", str(port), "--log=stdout", "--log-format=json"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
    except OSError:
        return None


def _stop_process(process: Any | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _valid_ngrok_public_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > MAX_NGROK_ADDRESS_CHARS or _has_control_characters(value):
        return None
    try:
        parsed, port = urlsplit(value), urlsplit(value).port
    except ValueError:
        return None
    host = parsed.hostname
    if parsed.scheme.lower() != "https" or host is None or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment or "." not in host:
        return None
    labels = host.split(".")
    if any(not label or len(label) > 63 or not label.replace("-", "").isalnum() or label.startswith("-") or label.endswith("-") for label in labels):
        return None
    return f"https://{host.lower()}{f':{port}' if port is not None else ''}"


def _ngrok_address_matches(value: Any, port: int) -> bool:
    if not isinstance(value, str) or not value or len(value) > MAX_NGROK_ADDRESS_CHARS or _has_control_characters(value):
        return False
    try:
        parsed = urlsplit(value if "://" in value else f"//{value}")
        target_port = parsed.port
    except ValueError:
        return False
    return not parsed.username and not parsed.password and not parsed.path.rstrip("/") and not parsed.query and not parsed.fragment and parsed.hostname in {"127.0.0.1", "localhost"} and target_port == port


def select_ngrok_public_url(payload: Any, port: int) -> str | None:
    tunnels = payload.get("tunnels") if isinstance(payload, Mapping) else None
    if not isinstance(tunnels, list):
        return None
    matches = [url for tunnel in tunnels if isinstance(tunnel, Mapping) and isinstance(tunnel.get("config"), Mapping) and _ngrok_address_matches(tunnel["config"].get("addr"), port) if (url := _valid_ngrok_public_url(tunnel.get("public_url"))) is not None]
    return matches[0] if len(matches) == 1 else None


def _poll_ngrok_agent(client: httpx.Client, port: int, *, monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> str | None:
    deadline = monotonic() + NGROK_AGENT_STARTUP_TIMEOUT_SECONDS
    for attempt in range(NGROK_AGENT_MAX_ATTEMPTS):
        if monotonic() >= deadline:
            break
        try:
            with client.stream("GET", NGROK_AGENT_API_URL) as response:
                body = _read_limited(response)
                if 200 <= response.status_code < 300 and body is not None:
                    try:
                        if (url := select_ngrok_public_url(json.loads(body), port)) is not None:
                            return url
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        pass
        except httpx.HTTPError:
            pass
        if attempt + 1 < NGROK_AGENT_MAX_ATTEMPTS and monotonic() < deadline:
            sleep(NGROK_AGENT_POLL_INTERVAL_SECONDS)
    return None


def update_ngrok_webhook_url(env_path: Path, public_url: str) -> bool:
    """Atomically update only the local URL field; this function never logs env data."""

    try:
        raw = env_path.read_bytes()
        if len(raw) > MAX_RESPONSE_BYTES:
            return False
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    newline = "\r\n" if "\r\n" in text else "\n"
    replacement = f"ZALO_BOT_WEBHOOK_URL={public_url}{WEBHOOK_PATH}{newline}"
    lines, replaced = [], False
    for line in text.splitlines(keepends=True):
        if line.rstrip("\r\n").startswith("ZALO_BOT_WEBHOOK_URL="):
            if not replaced:
                lines.append(replacement)
                replaced = True
        else:
            lines.append(line)
    if not replaced:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines.append(newline)
        lines.append(replacement)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("wb", dir=env_path.parent, prefix=".m00-ngrok-", delete=False) as file:
            temporary = Path(file.name)
            file.write("".join(lines).encode("utf-8"))
        os.replace(temporary, env_path)
        return True
    except OSError:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def _emit(emit: Callable[[str], None], payload: dict[str, object]) -> None:
    emit(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def run_ngrok_echo(*, timeout_seconds: int = DEFAULT_TUNNEL_TIMEOUT_SECONDS, port: int = DEFAULT_TUNNEL_PORT, client: httpx.Client | None = None, agent_client: httpx.Client | None = None, emit: Callable[[str], None] | None = None, popen: Any = subprocess.Popen, run: Any = subprocess.run, which: Callable[[str], str | None] = shutil.which, env_path: Path | None = None, server_factory: Any = ThreadingHTTPServer, monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> dict[str, object]:
    """Run one authenticated private-text echo through ngrok; the Bot UI owns webhook setup."""

    output = emit or (lambda line: print(line, flush=True))
    if not MIN_TUNNEL_TIMEOUT_SECONDS <= timeout_seconds <= MAX_TUNNEL_TIMEOUT_SECONDS or not 1 <= port <= 65_535:
        result = _failure(error_code="invalid_tunnel_configuration")
        _emit(output, result)
        return result
    token, secret = os.environ.get("ZALO_BOT_TOKEN"), os.environ.get("ZALO_BOT_SECRET_TOKEN")
    if not token:
        result = _failure(error_code="missing_token")
    elif len(token) > MAX_TOKEN_CHARS or _has_control_characters(token):
        result = _failure(error_code="invalid_token")
    elif not secret:
        result = _failure(error_code="missing_secret_token")
    elif not MIN_SECRET_TOKEN_CHARS <= len(secret) <= MAX_SECRET_TOKEN_CHARS or _has_control_characters(secret):
        result = _failure(error_code="invalid_secret_token")
    elif (executable := _find_ngrok(which)) is None:
        result = _failure(error_code="ngrok_unavailable")
    elif not _ngrok_config_is_valid(executable, run=run):
        result = _failure(error_code="ngrok_config_invalid")
    else:
        result = _failure(error_code="ngrok_not_started")
        owns_client, owns_agent = client is None, agent_client is None
        api_client = client or httpx.Client(timeout=TIMEOUT, trust_env=False, follow_redirects=False)
        local_agent = agent_client or httpx.Client(timeout=NGROK_AGENT_TIMEOUT, trust_env=False, follow_redirects=False)
        server = process = None
        thread: threading.Thread | None = None
        try:
            state = NgrokEchoState(secret, BotApi(token, api_client), output)
            server = server_factory(("127.0.0.1", port), ngrok_echo_handler(state))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            process = _start_ngrok(executable, port, popen=popen)
            if process is None:
                result = _failure(error_code="ngrok_start_failed")
            elif (public_url := _poll_ngrok_agent(local_agent, port, monotonic=monotonic, sleep=sleep)) is None:
                result = _failure(error_code="ngrok_tunnel_unavailable")
            elif not update_ngrok_webhook_url(env_path or repo_env_path(), public_url):
                result = _failure(error_code="webhook_url_update_failed")
            else:
                output(f"Webhook URL: {public_url}{WEBHOOK_PATH}")
                output("Set Webhook URL and ZALO_BOT_SECRET_TOKEN in the Zalo Bot UI, then send one PRIVATE text.")
                received = state.event.wait(timeout_seconds)
                result = {"operation": "ngrok_echo", "outcome": "PASS" if received and state.send_succeeded else "BLOCKED_EXTERNAL" if received else "NOT_MEASURED", "ok": received and state.send_succeeded}
                if not received:
                    result["error_code"] = "event_not_received"
        except OSError:
            result = _failure(error_code="local_server_unavailable")
        finally:
            _stop_process(process)
            if server is not None:
                server.shutdown()
                server.server_close()
            if thread is not None:
                thread.join(timeout=5)
            if owns_agent:
                local_agent.close()
            if owns_client:
                api_client.close()
        _emit(output, result)
        return result
    _emit(output, result)
    return result


def main(argv: list[str] | None = None, *, dotenv_path: Path | None = None) -> int:
    load_repo_env(dotenv_path)
    parser = argparse.ArgumentParser(description="M00 safe Zalo Bot probe")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("get-me")
    ngrok_echo = commands.add_parser("ngrok-echo")
    ngrok_echo.add_argument("--timeout-seconds", type=int, default=DEFAULT_TUNNEL_TIMEOUT_SECONDS)
    ngrok_echo.add_argument("--port", type=int, default=DEFAULT_TUNNEL_PORT)
    args = parser.parse_args(argv)
    if args.command == "get-me":
        result = probe_get_me()
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    else:
        result = run_ngrok_echo(timeout_seconds=args.timeout_seconds, port=args.port, env_path=dotenv_path)
    return 0 if result["outcome"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
