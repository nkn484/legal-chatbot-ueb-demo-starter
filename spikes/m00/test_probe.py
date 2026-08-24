from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.shineshop.dev")


class ProbeTests(unittest.TestCase):
    def test_recursive_redaction_and_normalized_json(self):
        result = probe.ProbeResult("x", "PASS", details={"token": "no", "nested": {"api_key": "no", "safe": "yes"}})
        rendered = result.to_json()
        self.assertNotIn('"no"', rendered)
        self.assertIn("[REDACTED]", rendered)
        self.assertEqual(json.loads(rendered)["outcome"], "PASS")

    def test_models_requires_exact_membership_and_does_not_emit_key(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            return httpx.Response(200, json={"data": [{"id": "shine-model"}, {"id": "shine-model-plus"}]})

        with client_for(handler) as client:
            good = probe.probe_shine_models("very-secret", "shine-model", client=client)
        self.assertEqual(good.outcome, "PASS")
        self.assertNotIn("very-secret", good.to_json())
        assert good.details is not None
        self.assertEqual(good.details["model_ids"], ["shine-model", "shine-model-plus"])
        with client_for(lambda _request: httpx.Response(200, json={"data": [{"id": "SHINE-MODEL"}]})) as client:
            bad = probe.probe_shine_models("very-secret", "shine-model", client=client)
        self.assertEqual(bad.outcome, "BLOCKED_EXTERNAL")

    def test_models_discovers_without_a_guessed_model_id(self):
        with client_for(lambda _request: httpx.Response(200, json={"data": [{"id": "shine-model"}]})) as client:
            result = probe.probe_shine_models("very-secret", client=client)
        self.assertEqual(result.outcome, "PASS")
        assert result.details is not None
        self.assertEqual(result.details, {"model_ids": ["shine-model"], "model_count": 1, "exact_match": True})

    def test_get_retries_only_once_for_retryable_status(self):
        calls = []

        def handler(_request):
            calls.append(1)
            return httpx.Response(503 if len(calls) == 1 else 200, json={"data": [{"id": "m"}]})

        with client_for(handler) as client:
            result = probe.probe_shine_models("k", "m", client=client, sleep=lambda _seconds: None)
        self.assertEqual(result.outcome, "PASS")
        self.assertEqual(len(calls), 2)

    def test_get_does_not_retry_non_retryable_status(self):
        calls = []
        with client_for(lambda _request: (calls.append(1), httpx.Response(401))[1]) as client:
            result = probe.probe_shine_models("k", "m", client=client)
        self.assertEqual(result.outcome, "BLOCKED_EXTERNAL")
        self.assertEqual(len(calls), 1)

    def test_response_is_one_post_attempt_and_sanitizes_output(self):
        calls = []

        def handler(request):
            calls.append(request)
            self.assertEqual(request.method, "POST")
            self.assertEqual(json.loads(request.content), {"model": "m", "input": "Reply with READY.", "max_output_tokens": 20, "stream": False})
            return httpx.Response(503, headers={"x-request-id": "req-1", "Retry-After": "999"}, json={"error": {"type": "server_error", "code": "overloaded", "message": "do not disclose"}})

        with client_for(handler) as client:
            result = probe.probe_shine_response("k", "m", client=client)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.x_request_id, "req-1")
        self.assertEqual(result.outcome, "BLOCKED_EXTERNAL")
        self.assertEqual(result.error, {"type": "server_error", "code": "overloaded"})
        self.assertEqual(result.details, {"retryable": True, "retry_after_seconds": probe.MAX_RETRY_AFTER_SECONDS})
        self.assertNotIn("do not disclose", result.to_json())

    def test_response_summary_never_contains_output_text(self):
        with client_for(lambda _request: httpx.Response(200, json={"output": [{"content": [{"text": "private answer"}]}]})) as client:
            result = probe.probe_shine_response("k", "m", client=client)
        self.assertEqual(result.outcome, "PASS")
        self.assertNotIn("private answer", result.to_json())
        assert result.details is not None
        self.assertEqual(result.details["output_text_chars"], 14)

    def test_shine_default_clients_disable_environment_trust_and_never_emit_key_or_output(self):
        real_client = httpx.Client
        trust_env_values = []

        def handler(request):
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": "m"}]})
            self.assertEqual(request.method, "POST")
            return httpx.Response(200, json={"output": [{"content": [{"text": "private provider output"}]}]})

        def factory(*args, **kwargs):
            trust_env_values.append(kwargs["trust_env"])
            return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

        with patch.object(probe.httpx, "Client", side_effect=factory):
            models = probe.probe_shine_models("private-api-key", "m")
            response = probe.probe_shine_response("private-api-key", "m")
        self.assertEqual(trust_env_values, [False, False])
        self.assertEqual((models.outcome, response.outcome), ("PASS", "PASS"))
        rendered = models.to_json() + response.to_json()
        self.assertNotIn("private-api-key", rendered)
        self.assertNotIn("private provider output", rendered)

    def test_response_requires_an_explicit_bounded_model_without_posting(self):
        calls = []
        with client_for(lambda request: (calls.append(request), httpx.Response(200))[1]) as client:
            result = probe.probe_shine_response("k", "", client=client)
        self.assertEqual(result.error, {"type": "config", "code": "explicit_model_required"})
        self.assertEqual(calls, [])

    def test_wsdl_allowlist_is_exact_and_rejects_old_search_operation(self):
        self.assertEqual(probe.VBQPPL_ALLOWLIST, frozenset({"GetListVanBanByListSKH", "GetVanBanById"}))
        old_wsdl = self.wsdl_with_actions().replace(b"GetListVanBanByListSKH", b"TimKiemVanBanNew")
        calls = []
        with client_for(lambda request: (calls.append(request.method), httpx.Response(200, content=old_wsdl))[1]) as client:
            result = probe.probe_vbqppl("https://example.test/wsdl", client=client)
        self.assertEqual(result.error, {"type": "wsdl", "code": "allowlist_not_confirmed"})
        self.assertEqual(calls, ["GET"])

    def test_vbqppl_default_client_keeps_tls_verification_enabled(self):
        real_client = httpx.Client
        verify_values = []

        def factory(*args, **kwargs):
            verify_values.append(kwargs["verify"])
            return real_client(*args, transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=self.wsdl_with_actions())), **kwargs)

        with patch.object(probe.httpx, "Client", side_effect=factory):
            result = probe.probe_vbqppl("https://example.test/wsdl")
        self.assertEqual(result.outcome, "PASS")
        self.assertEqual(verify_values, [True])

    def test_vbqppl_explicit_insecure_tls_disables_verification_and_never_passes(self):
        real_client = httpx.Client
        verify_values = []

        def factory(*args, **kwargs):
            verify_values.append(kwargs["verify"])
            return real_client(*args, transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=self.wsdl_with_actions())), **kwargs)

        with patch.object(probe.httpx, "Client", side_effect=factory):
            result = probe.probe_vbqppl("https://ws.vbpl.vn/vbqppl.asmx?WSDL", insecure_tls=True)

        self.assertEqual(verify_values, [False])
        self.assertEqual(result.outcome, "BLOCKED_EXTERNAL")
        self.assertEqual(result.error, {"type": "tls", "code": "insecure_diagnostic"})

    def test_insecure_tls_is_host_scoped_and_http_is_denied(self):
        calls = []
        with client_for(lambda request: (calls.append(request), httpx.Response(200, content=self.wsdl_with_actions()))[1]) as client:
            wrong_host = probe.probe_vbqppl("https://other.example/wsdl", insecure_tls=True, client=client)
            http_url = probe.probe_vbqppl("http://ws.vbpl.vn/vbqppl.asmx?WSDL", insecure_tls=True, client=client)
        self.assertEqual(wrong_host.error, {"type": "tls", "code": "insecure_tls_host_not_allowed"})
        self.assertEqual(http_url.error, {"type": "tls", "code": "https_required"})
        self.assertEqual(calls, [])

    def test_exact_known_document_envelopes_actions_and_selection(self):
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "GET":
                return httpx.Response(200, content=self.wsdl_with_actions())
            if len(requests) == 2:
                return httpx.Response(200, content=self.discovery_xml())
            return httpx.Response(200, content=self.detail_xml())

        with client_for(handler) as client:
            result = probe.probe_vbqppl("https://example.test/wsdl", live_known_document=True, document_number="63/2025/QH15", expected_document_id=175258, client=client)

        self.assertEqual(result.outcome, "PASS")
        self.assertEqual([request.method for request in requests], ["GET", "POST", "POST"])
        discovery, detail = requests[1:]
        self.assertEqual(discovery.headers["soapaction"], '"http://tempuri.org/GetListVanBanByListSKH"')
        self.assertEqual(detail.headers["soapaction"], '"http://tempuri.org/GetVanBanById"')
        discovery_xml = discovery.content.decode("utf-8")
        self.assertIn('<GetListVanBanByListSKH xmlns="http://tempuri.org/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><skh>63/2025/QH15</skh><ngaybanhanh xsi:nil="true"/><ngaycohieuluc xsi:nil="true"/></GetListVanBanByListSKH>', discovery_xml)
        self.assertNotIn("coquan", discovery_xml)
        self.assertIn('<GetVanBanById xmlns="http://tempuri.org/"><ItemID>8675309</ItemID></GetVanBanById>', detail.content.decode("utf-8"))
        assert result.details is not None
        self.assertTrue(result.details["functional_read_pass"])
        self.assertFalse(result.details["public_id_matches_soap_id"])
        self.assertNotIn("175258", result.to_json())
        self.assertNotIn("8675309", result.to_json())
        self.assertNotIn("999", result.to_json())
        self.assertNotIn("63/2025/QH15", result.to_json())
        self.assertNotIn("safe title", result.to_json())
        self.assertNotIn("full legal text", result.to_json())

    def test_known_document_requires_exactly_one_matching_signature(self):
        for response in (self.discovery_xml(signature_count=0), self.discovery_xml(signature_count=2)):
            with self.subTest(response=response):
                calls = []

                def handler(request):
                    calls.append(request.method)
                    return httpx.Response(200, content=self.wsdl_with_actions() if request.method == "GET" else response)

                with client_for(handler) as client:
                    result = probe.probe_vbqppl("https://example.test/wsdl", live_known_document=True, document_number="63/2025/QH15", expected_document_id=175258, client=client)
                self.assertEqual(result.error, {"type": "validation", "code": "functional_read_failed"})
                self.assertEqual(calls, ["GET", "POST"])
                assert result.details is not None
                self.assertFalse(result.details["discovery_pass"])

    def test_soap_fault_blocks_before_detail_and_exposes_only_fault_facts(self):
        fault = b"<soap:Envelope xmlns:soap='http://schemas.xmlsoap.org/soap/envelope/'><soap:Body><soap:Fault><faultcode>soap:Server</faultcode><faultstring>secret message</faultstring></soap:Fault></soap:Body></soap:Envelope>"
        calls = []
        with client_for(lambda request: (calls.append(request.method), httpx.Response(200, content=self.wsdl_with_actions() if request.method == "GET" else fault))[1]) as client:
            result = probe.probe_vbqppl("https://example.test/wsdl", live_known_document=True, document_number="63/2025/QH15", expected_document_id=175258, client=client)
        self.assertEqual(calls, ["GET", "POST"])
        assert result.details is not None
        self.assertTrue(result.details["discovery_fault_present"])
        self.assertEqual(result.details["discovery_fault_code"], "soap:Server")
        self.assertNotIn("secret message", result.to_json())

    def test_empty_detail_content_blocks_with_only_facts(self):
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, content=self.wsdl_with_actions())
            return httpx.Response(200, content=self.discovery_xml() if request.headers["soapaction"] == '"http://tempuri.org/GetListVanBanByListSKH"' else self.detail_xml(content=""))

        with client_for(handler) as client:
            result = probe.probe_vbqppl("https://example.test/wsdl", live_known_document=True, document_number="63/2025/QH15", expected_document_id=175258, client=client)
        self.assertEqual(result.error, {"type": "validation", "code": "functional_read_failed"})
        assert result.details is not None
        self.assertTrue(result.details["metadata_present"])
        self.assertFalse(result.details["content_present"])
        self.assertEqual(result.details["content_chars"], 0)

    def test_functional_insecure_success_remains_blocked_but_secure_can_pass(self):
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, content=self.wsdl_with_actions())
            return httpx.Response(200, content=self.discovery_xml() if request.headers["soapaction"] == '"http://tempuri.org/GetListVanBanByListSKH"' else self.detail_xml())

        with client_for(handler) as client:
            insecure = probe.probe_vbqppl("https://ws.vbpl.vn/vbqppl.asmx?WSDL", live_known_document=True, document_number="63/2025/QH15", expected_document_id=175258, insecure_tls=True, client=client)
        self.assertEqual(insecure.outcome, "BLOCKED_EXTERNAL")
        self.assertEqual(insecure.error, {"type": "tls", "code": "insecure_diagnostic"})
        assert insecure.details is not None
        for key in ("functional_read_pass", "discovery_pass", "detail_pass", "metadata_present", "content_present"):
            self.assertTrue(insecure.details[key])
        self.assertFalse(insecure.details["tls_verified"])
        with client_for(handler) as client:
            secure = probe.probe_vbqppl("https://example.test/wsdl", live_known_document=True, document_number="63/2025/QH15", expected_document_id=175258, client=client)
        self.assertEqual(secure.outcome, "PASS")

    def test_same_or_different_public_reference_does_not_change_functional_pass(self):
        def handler(request):
            if request.method == "GET":
                return httpx.Response(200, content=self.wsdl_with_actions())
            return httpx.Response(200, content=self.discovery_xml() if request.headers["soapaction"] == '"http://tempuri.org/GetListVanBanByListSKH"' else self.detail_xml())

        for public_id, public_match in ((8675309, True), (175258, False)):
            with self.subTest(public_id=public_id):
                with client_for(handler) as client:
                    result = probe.probe_vbqppl("https://example.test/wsdl", live_known_document=True, document_number="63/2025/QH15", expected_document_id=public_id, client=client)
                self.assertEqual(result.outcome, "PASS")
                assert result.details is not None
                self.assertEqual(result.details["public_id_matches_soap_id"], public_match)
                self.assertTrue(result.details["functional_read_pass"])

    def test_invalid_known_document_input_and_ambiguous_action_make_no_soap_calls(self):
        calls = []
        with client_for(lambda request: (calls.append(request.method), httpx.Response(200, content=self.wsdl_with_actions()))[1]) as client:
            invalid = probe.probe_vbqppl("https://example.test/wsdl", live_known_document=True, document_number="bad value", expected_document_id=175258, client=client)
        self.assertEqual(invalid.error, {"type": "config", "code": "invalid_known_document_input"})
        self.assertEqual(calls, [])
        ambiguous = self.wsdl_with_actions().replace(b"http://tempuri.org/GetListVanBanByListSKH\"/>", b"http://tempuri.org/GetListVanBanByListSKH\"/><soap:operation xmlns:soap=\"http://schemas.xmlsoap.org/wsdl/soap/\" soapAction=\"other\"/>", 1)
        with client_for(lambda request: (calls.append(request.method), httpx.Response(200, content=ambiguous))[1]) as client:
            blocked = probe.probe_vbqppl("https://example.test/wsdl", live_known_document=True, document_number="63/2025/QH15", expected_document_id=175258, client=client)
        self.assertEqual(blocked.error, {"type": "wsdl", "code": "soap_action_not_established"})
        self.assertEqual(calls, ["GET"])

    def test_discovery_accepts_only_direct_signature_and_id(self):
        xml = b"""<root>
            <VanBanItem><ID>8675309</ID><wrapper><VBPQSokyhieu>63/2025/QH15</VBPQSokyhieu></wrapper></VanBanItem>
            <VanBanItem><VBPQSokyhieu>63/2025/QH15</VBPQSokyhieu><wrapper><ID>8675309</ID></wrapper><ItemID>8675309</ItemID></VanBanItem>
            <VanBanItem><ID>999</ID><OtherID>8675309</OtherID><VBPQSokyhieu>other</VBPQSokyhieu></VanBanItem>
        </root>"""
        self.assertEqual(probe._discovery_selection(xml, "63/2025/QH15"), (3, 1, None))
        calls = []

        def handler(request):
            calls.append(request.method)
            return httpx.Response(200, content=self.wsdl_with_actions() if request.method == "GET" else xml)

        with client_for(handler) as client:
            result = probe.probe_vbqppl("https://example.test/wsdl", live_known_document=True, document_number="63/2025/QH15", expected_document_id=175258, client=client)
        self.assertEqual(result.error, {"type": "validation", "code": "functional_read_failed"})
        self.assertEqual(calls, ["GET", "POST"])

    def test_detail_accepts_only_direct_result_id(self):
        xml = b"""<GetVanBanByIdResponse><GetVanBanByIdResult>
            <ItemID>8675309</ItemID><wrapper><ID>8675309</ID></wrapper><ID>999</ID>
            <Title>safe title</Title><VBPQToanVan>content</VBPQToanVan>
        </GetVanBanByIdResult></GetVanBanByIdResponse>"""
        self.assertEqual(probe._direct_detail_summary(xml, 8675309), (False, True, True, 7))

    def test_parse_tls_verify_config_accepts_only_strict_boolean_values(self):
        self.assertTrue(probe.parse_tls_verify_config(None))
        self.assertTrue(probe.parse_tls_verify_config("TrUe"))
        self.assertFalse(probe.parse_tls_verify_config("FALSE"))
        for value in ("", " true", "false ", "1", "yes"):
            with self.subTest(value=value):
                self.assertIsNone(probe.parse_tls_verify_config(value))

    def test_vbqppl_cli_dotenv_sets_effective_insecure_flag_without_network(self):
        for dotenv_value, explicit_flag, expected_insecure in (("false", False, True), ("TRUE", False, False), ("true", True, True)):
            with self.subTest(dotenv_value=dotenv_value, explicit_flag=explicit_flag):
                with tempfile.TemporaryDirectory() as directory:
                    dotenv_path = Path(directory) / ".env"
                    dotenv_path.write_text(f"VBQPPL_TLS_VERIFY={dotenv_value}\n", encoding="utf-8")
                    observed: list[bool] = []

                    def fake_probe(_wsdl_url, **kwargs):
                        observed.append(kwargs["insecure_tls"])
                        return probe.ProbeResult("vbqppl", "BLOCKED_EXTERNAL", error={"type": "test", "code": "mocked"})

                    arguments = ["vbqppl", "--wsdl-url", "https://ws.vbpl.vn/vbqppl.asmx?WSDL", "--live-known-document", "--document-number", "63/2025/QH15", "--expected-document-id", "175258"]
                    if explicit_flag:
                        arguments.append("--insecure-tls")
                    with patch.dict(os.environ, {"VBQPPL_TLS_VERIFY": ""}, clear=False), patch.object(probe, "probe_vbqppl", fake_probe), redirect_stdout(StringIO()):
                        exit_code = probe._main(arguments, dotenv_path=dotenv_path)

                self.assertEqual(exit_code, 2)
                self.assertEqual(observed, [expected_insecure])

    def test_vbqppl_cli_rejects_invalid_dotenv_tls_before_http_without_printing_value(self):
        invalid_value = "not-a-valid-private-setting"
        with tempfile.TemporaryDirectory() as directory:
            dotenv_path = Path(directory) / ".env"
            dotenv_path.write_text(f"VBQPPL_TLS_VERIFY={invalid_value}\n", encoding="utf-8")
            stdout = StringIO()
            with patch.dict(os.environ, {"VBQPPL_TLS_VERIFY": ""}, clear=False), patch.object(probe, "probe_vbqppl", side_effect=AssertionError("must not call HTTP probe")), redirect_stdout(stdout):
                exit_code = probe._main(["vbqppl", "--wsdl-url", "https://ws.vbpl.vn/vbqppl.asmx?WSDL"], dotenv_path=dotenv_path)

        rendered = stdout.getvalue()
        self.assertEqual(exit_code, 2)
        self.assertEqual(json.loads(rendered), {"details": None, "duration_ms": None, "error": {"code": "invalid_tls_verify_config", "type": "config"}, "outcome": "BLOCKED_EXTERNAL", "probe": "vbqppl", "status": None, "x_request_id": None})
        self.assertNotIn(invalid_value, rendered)

    def test_rest_known_document_exact_read_only_urls_and_sanitized_success(self):
        requests = []

        def handler(request):
            requests.append(request)
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.content, b"")
            self.assertNotIn("authorization", request.headers)
            self.assertNotIn("cookie", request.headers)
            if request.url == httpx.URL(probe.VBQPPL_REST_GATEWAY_URL):
                self.assertNotEqual(request.headers["user-agent"], probe.VBQPPL_CANONICAL_PAGE_HEADERS["User-Agent"])
                return httpx.Response(200, json=self.rest_gateway_payload())
            self.assertEqual(request.url, httpx.URL(probe.VBQPPL_CANONICAL_PAGE_URL))
            self.assertEqual(request.headers["user-agent"], "legal-chatbot-ueb-demo-m00/1.0")
            self.assertEqual(request.headers["accept"], "text/html,application/xhtml+xml")
            return httpx.Response(200, content=self.canonical_html())

        with client_for(handler) as client:
            result = probe.probe_vbqppl_rest_known_document(client=client)
        self.assertEqual(result.outcome, "PASS")
        self.assertEqual([str(request.url) for request in requests], [probe.VBQPPL_REST_GATEWAY_URL, probe.VBQPPL_CANONICAL_PAGE_URL])
        assert result.details is not None
        self.assertEqual(result.details["fallback_transport"], "REST_FRONTEND_BACKING_API")
        self.assertTrue(result.details["tls_verified"])
        self.assertEqual((result.details["gateway_calls"], result.details["page_calls"]), (1, 1))
        for key in ("metadata_present", "updated_date_present", "content_present", "article_markup_present", "canonical_match", "functional_read_pass"):
            self.assertTrue(result.details[key])
        rendered = result.to_json()
        for private_value in ("private legal title", "private legal content", "175258", "63/2025/QH15", "private-agency", "legal-chatbot-ueb-demo-m00/1.0", "text/html,application/xhtml+xml"):
            self.assertNotIn(private_value, rendered)

    def test_rest_known_document_blocks_id_or_number_mismatch_before_page(self):
        for field, value in (("id", "175259"), ("docNum", "other")):
            with self.subTest(field=field):
                calls = []
                payload = self.rest_gateway_payload()
                payload["data"][field] = value
                with client_for(lambda request: (calls.append(str(request.url)), httpx.Response(200, json=payload))[1]) as client:
                    result = probe.probe_vbqppl_rest_known_document(client=client)
                self.assertEqual(result.error, {"type": "validation", "code": "functional_read_failed"})
                self.assertEqual(calls, [probe.VBQPPL_REST_GATEWAY_URL])

    def test_rest_known_document_blocks_empty_or_oversize_content(self):
        empty = self.rest_gateway_payload()
        empty["data"]["documentContent"]["content"] = ""
        with client_for(lambda request: httpx.Response(200, json=empty)) as client:
            empty_result = probe.probe_vbqppl_rest_known_document(client=client)
        self.assertEqual(empty_result.error, {"type": "validation", "code": "functional_read_failed"})
        oversized = self.rest_gateway_payload()
        oversized["data"]["documentContent"]["content"] = "<p>" + ("x" * probe.MAX_REST_RESPONSE_BYTES) + "</p>"
        with client_for(lambda request: httpx.Response(200, content=json.dumps(oversized).encode("utf-8"))) as client:
            oversized_result = probe.probe_vbqppl_rest_known_document(client=client)
        self.assertEqual(oversized_result.error, {"type": "response", "code": "response_too_large"})

    def test_rest_known_document_blocks_invalid_json_canonical_mismatch_and_transport_failure(self):
        with client_for(lambda _request: httpx.Response(200, content=b"not-json")) as client:
            invalid_json = probe.probe_vbqppl_rest_known_document(client=client)
        self.assertEqual(invalid_json.error, {"type": "response", "code": "invalid_gateway_json"})

        def canonical_mismatch(request):
            return httpx.Response(200, json=self.rest_gateway_payload()) if str(request.url) == probe.VBQPPL_REST_GATEWAY_URL else httpx.Response(200, content=b"<link rel='canonical' href='https://vbpl.vn/not-the-document'>")

        with client_for(canonical_mismatch) as client:
            mismatch = probe.probe_vbqppl_rest_known_document(client=client)
        self.assertEqual(mismatch.error, {"type": "validation", "code": "functional_read_failed"})
        assert mismatch.details is not None
        self.assertFalse(mismatch.details["canonical_match"])

        def transport_failure(request):
            raise httpx.ConnectError("private transport detail", request=request)

        with client_for(transport_failure) as client:
            failed = probe.probe_vbqppl_rest_known_document(client=client)
        self.assertEqual(failed.error, {"type": "transport", "code": "transport_error"})
        self.assertNotIn("private transport detail", failed.to_json())

    def test_rest_known_document_rejects_nonfixed_input_and_redirect_without_extra_calls(self):
        calls = []
        with client_for(lambda request: (calls.append(request), httpx.Response(200))[1]) as client:
            invalid = probe.probe_vbqppl_rest_known_document(document_id=1, client=client)
        self.assertEqual(invalid.error, {"type": "config", "code": "invalid_known_document_input"})
        self.assertEqual(calls, [])
        redirects = []
        with client_for(lambda request: (redirects.append(str(request.url)), httpx.Response(302, headers={"Location": "https://example.test/redirect"}))[1]) as client:
            redirected = probe.probe_vbqppl_rest_known_document(client=client)
        self.assertEqual(redirected.error, {"type": "http", "code": "gateway_http_status"})
        self.assertEqual(redirects, [probe.VBQPPL_REST_GATEWAY_URL])

    def test_rest_default_client_uses_verified_tls_and_source_registry_declares_fallback(self):
        real_client = httpx.Client
        observed = []

        def factory(*args, **kwargs):
            observed.append((kwargs["verify"], kwargs["follow_redirects"]))
            return real_client(*args, transport=httpx.MockTransport(lambda request: httpx.Response(500)), **kwargs)

        with patch.object(probe.httpx, "Client", side_effect=factory):
            probe.probe_vbqppl_rest_known_document()
        self.assertEqual(observed, [(True, False)])
        registry = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "source-registry.json").read_text(encoding="utf-8"))
        vbqppl = next(item for item in registry["systems"] if item["id"] == "VBQPPL")
        self.assertEqual(vbqppl["transport"], "SOAP")
        self.assertEqual(vbqppl["access_mode"], "READ_ONLY_ALLOWLIST")
        self.assertEqual(vbqppl["fallback_transport"], "REST_FRONTEND_BACKING_API")
        self.assertEqual(vbqppl["fallback_base_url"], probe.VBQPPL_REST_BASE_URL)
        self.assertEqual(vbqppl["fallback_access_mode"], "READ_ONLY_EXACT_PATH_ALLOWLIST")
        self.assertEqual(vbqppl["canonical_page_origin"], "https://vbpl.vn")

    @staticmethod
    def wsdl_with_actions():
        return b'''<definitions xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/"><binding name="soap11"><operation name="GetListVanBanByListSKH"><soap:operation soapAction="http://tempuri.org/GetListVanBanByListSKH"/></operation><operation name="GetVanBanById"><soap:operation soapAction="http://tempuri.org/GetVanBanById"/></operation></binding><service><port><soap:address location="https://ws.vbpl.vn/vbqppl.asmx"/></port></service></definitions>'''

    @staticmethod
    def discovery_xml(signature_count=1, soap_id=8675309):
        expected = b"".join(f"<VanBanItem><ID>{soap_id}</ID><VBPQSokyhieu>63/2025/QH15</VBPQSokyhieu></VanBanItem>".encode() for _ in range(signature_count))
        return b"<root><VanBanItem><ID>999</ID><VBPQSokyhieu>other</VBPQSokyhieu></VanBanItem>" + expected + b"</root>"

    @staticmethod
    def detail_xml(content="full legal text", soap_id=8675309):
        return f"<GetVanBanByIdResponse><GetVanBanByIdResult><ID>{soap_id}</ID><Title>safe title</Title><VBPQToanVan>{content}</VBPQToanVan></GetVanBanByIdResult></GetVanBanByIdResponse>".encode()

    @staticmethod
    def rest_gateway_payload():
        return {
            "success": True,
            "statusCode": 200,
            "data": {
                "id": "175258",
                "docNum": "63/2025/QH15",
                "title": "private legal title",
                "issueDate": "2025-01-01",
                "agencyName": "private-agency",
                "updatedDate": "2025-01-02",
                "hasContent": True,
                "documentContent": {"content": "<article class='prov-article'>private legal content</article>"},
            },
        }

    @staticmethod
    def canonical_html():
        return f"<html><head><link rel='canonical' href='{probe.VBQPPL_CANONICAL_PAGE_URL}'></head></html>".encode("utf-8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
