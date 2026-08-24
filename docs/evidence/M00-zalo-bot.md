# M00 — Zalo Bot / ngrok webhook

**Trạng thái lane: PASS**

**evidence_finalized_at (UTC; thời điểm hoàn tất evidence, không nhất thiết là thời điểm request): `2026-08-18T19:10:44.490678+00:00`**

## Normalized sanitized measurements

```json
{"probe":"zalo.getMe","outcome":"PASS","status":200,"duration_ms":313,"account_type":"BASIC","bot_id_present":true,"can_join_groups":true}
```

```json
{"probe":"zalo.testWebhook","outcome":"PASS","outer_status":200,"ok":true,"callback_status":200,"callback_ok":true,"webhook_outcome":"webhook.ok","latency_ms":260,"url_matches_env":true}
```

```json
{"probe":"zalo.payload_envelope","outcome":"PASS","top_level_authenticated":true,"top_event_supported":true,"top_message_object":true}
```

Payload live dùng authenticated top-level envelope được parser hỗ trợ. User đã quan sát outbound `ECHO`; full live path là **PASS**. Không tuyên bố exact echo timestamp. ngrok endpoint chỉ online khi process liên quan đang chạy.

## Superseded Cloudflare history

Cloudflare callback 403 lịch sử đã được supersede bởi ngrok live **PASS**. Superseded source artifacts và resources đã được remove; không còn là blocker cho lane này.

M00 state vẫn **IN_PROGRESS / not submitted**; M01 là **NOT_STARTED**.
