# M00 — SHINE SHOP

**Trạng thái: PASS**

**evidence_finalized_at (UTC; thời điểm hoàn tất evidence, không nhất thiết là thời điểm request): `2026-08-18T19:10:44.490678+00:00`**

## Normalized sanitized measurements

```json
{"probe":"shine.models","outcome":"PASS","status":200,"duration_ms":1157,"model_count":9,"exact_match":true,"selected_model":"gpt-5.6-sol","x_request_id":null}
```

```json
{"probe":"shine.response","outcome":"PASS","status":200,"duration_ms":5968,"output_items":1,"output_text_chars":5,"x_request_id":"req_6f1c8d7bf8aa4b3d839550f27f171922","attempts":1,"stream":false}
```

Không lưu model list, provider key hoặc output text. POST chỉ có một attempt và không retry.

## Kết luận

SHINE external lane là **PASS**. Nếu cấu hình riêng không sẵn sàng trong lần đo khác, outcome phù hợp là **BLOCKED_EXTERNAL**; không suy diễn availability từ evidence này.
