---
description: Plan M08 Official Zalo Bot Manager channel; never implement without approval
agent: plan
---

Before planning:
- read `AGENTS.md`, `contracts/demo-profile.json`, M00 evidence, and the M07 plan;
- inspect repository and `.demo-run/state.json` if present, but never edit state directly;
- planning-only: require explicit implementation approval and use only `demo_gate` for gates.

# M08 — Official Zalo Bot Manager

Target bắt buộc là Official Zalo Bot Manager và Bot API, không phải Personal automation. Cite/review
Manager <https://bot.zaloplatforms.com/> và API `POST
https://bot-api.zaloplatforms.com/bot<TOKEN>/getMe|sendMessage|setWebhook` trước live gate. M00 chỉ
chứng minh sanitised `getMe`, `testWebhook`, supported envelope và một outbound observed path; không
chứng minh M08 adapter/configuration, citations, retry/deadline hay production behavior.

Giữ provider/source/channel boundary: official SDK/HTTP chỉ ở adapter; Chat/Retrieval/Citation/
Conversation không raw payload/chat ID/token. Webhook secret auth, body bound, identity/delivery HMAC,
durable binding/outbound state, server-owned citation formatting và at-most-one send attempt cần được
verify. Không persist/log token, secret, payload, text, raw IDs, answer, citation hoặc signature.

Config disabled-by-default gồm `CHANNEL_ENABLED`, externally issued `ZALO_OFFICIAL_BOT_TOKEN`, hai
secret độc lập `ZALO_OFFICIAL_BOT_WEBHOOK_SECRET`/`CHANNEL_IDENTITY_HMAC_KEY`, body `65536`, outbound
`1994`, attempt `1`, lease `120`, timeout `30`. Không silent split/truncate; overflow phải channel-safe
và không partial citations. `FAILED`/`UNKNOWN` không automatic send retry hoặc provider rerun.

Live path dùng HTTPS tunnel do operator tạo, webhook đăng ký qua Manager hoặc `setWebhook`, kiểm tra
an toàn `testWebhook`/`getMe`, rồi đúng một private test message → grounded reply. Evidence chỉ ghi
booleans/counts/timing. Callback deadline/retries, rate limits, latency và exactly-once remote send là
`NOT_MEASURED` đến khi đo. Có notice AI/informational; operator chịu trách nhiệm vận hành và compliance.
Sự cố external ghi `BLOCKED_EXTERNAL`. Sau M08 dừng, không bắt đầu M09.
