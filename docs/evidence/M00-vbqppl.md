# M00 — VBQPPL

**Trạng thái DEMO_NOW: PASS** qua REST fallback được user phê duyệt. SOAP primary là residual **BLOCKED_EXTERNAL** risk.

**evidence_finalized_at (UTC; thời điểm hoàn tất evidence, không nhất thiết là thời điểm request): `2026-08-18T19:10:44.490678+00:00`**

## REST fallback live measurement

```json
{"probe":"vbqppl.rest","outcome":"PASS","status":200,"total_duration_ms":453,"fallback_transport":"REST_FRONTEND_BACKING_API","tls_verified":true,"gateway_status":200,"gateway_duration_ms":156,"gateway_calls":1,"page_status":200,"page_duration_ms":141,"page_calls":1,"metadata_present":true,"updated_date_present":true,"content_present":true,"content_chars":75971,"article_markup_present":true,"canonical_match":true,"functional_read_pass":true}
```

REST fallback dùng exact read-only allowlist; không auth, retry, redirect hoặc mutation. Current frontend backing API không có documented SLA hoặc replacement policy: đây là demo risk.

## SOAP primary residual history

- Certificate mismatch và insecure opt-in diagnostic khiến SOAP primary vẫn **BLOCKED_EXTERNAL**; không có SOAP secure **PASS**.
- Discovery read-only cho bốn official documents không chọn được item/signature; direct allowlisted detail diagnostic trả SOAP Fault. Metadata/content qua safely established SOAP runtime semantics là **NOT_MEASURED**.
- SOAP primary được supersede cho DEMO_NOW bởi REST fallback, nhưng không được tuyên bố PASS.

M00 state vẫn **IN_PROGRESS / not submitted**; M01 là **NOT_STARTED**.
