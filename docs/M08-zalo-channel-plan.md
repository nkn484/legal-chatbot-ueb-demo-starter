# M08 — Kế hoạch Official Zalo Bot Manager

## Mục tiêu và gate

M08 dùng **Official Zalo Bot Manager** và Bot API. M07 là `PASS`; M08 chưa được submit; M09 không
thuộc scope. Chỉ triển khai sau approval rõ ràng, chỉ phục vụ
`DEMO_BLOCKER`, và dừng sau M08.

Nguồn chính thức cần đối chiếu lại trước live gate:

- Zalo Bot Manager: <https://bot.zaloplatforms.com/>.
- Bot API: `POST https://bot-api.zaloplatforms.com/bot<TOKEN>/getMe`, `sendMessage`, và
  `setWebhook`.

## Đối chiếu M00

M00 có evidence đã sanitise cho `getMe`, `testWebhook`, top-level authenticated envelope và một
outbound user-observed qua ngrok. Điều đó không chứng minh adapter M08 hiện tại, cấu hình Manager
mới, persistence/idempotency, callback deadline/retry, giới hạn production hoặc grounded citations
qua đường M08. Các điểm chưa đo phải giữ `NOT_MEASURED`.

## Boundary và dữ liệu

Webhook chính thức đi thẳng vào adapter Python tại boundary `ChannelPort`; outbound dùng Bot API
chính thức từ adapter. Chat/Retrieval/Citation/Conversation không biết token, raw payload, chat ID
hoặc SDK/provider-specific client. Adapter giữ raw recipient data ở boundary; persistence chỉ nhận
identity/delivery HMAC và metadata tối thiểu. Không persist/log token, webhook secret, raw ID,
payload, text, answer, citation hoặc signature.

Config bị tắt mặc định:

- `CHANNEL_ENABLED=false`
- `ZALO_OFFICIAL_BOT_TOKEN` do Manager cấp, nhập thủ công
- `ZALO_OFFICIAL_BOT_WEBHOOK_SECRET` và `CHANNEL_IDENTITY_HMAC_KEY` là hai secret độc lập
- `CHANNEL_MAX_BODY_BYTES=65536`, `CHANNEL_MAX_OUTBOUND_CHARS=1994`,
  `CHANNEL_OUTBOUND_MAX_ATTEMPTS=1`, `CHANNEL_BINDING_LEASE_SECONDS=120`,
  `CHANNEL_TIMEOUT_SECONDS=30`

Giới hạn 1994 là safety bound dưới giới hạn `sendMessage.text` 1–2000 đã được đối chiếu ở M00; không
silent split/truncate. Kết quả vượt giới hạn phải nhận response kênh an toàn, không partial citation.

## Flow và độ tin cậy

1. Adapter xác thực webhook secret, kiểm tra body bound và chuẩn hoá event.
2. Core reserve binding/delivery, gọi M07, và formatter server sở hữu citations.
3. Adapter gọi `sendMessage` đúng một lần cho delivery được reserve; `FAILED`/`UNKNOWN` không tự gửi
   lại và không rerun provider.

Duplicate đã hoàn tất không được rerun M06 hoặc gửi lại. Exactly-once remote send, callback deadline,
callback retries, rate limit và latency là `NOT_MEASURED` cho đến khi live evidence đo được. Nếu
callback timing không dùng được, dừng và xin approval trước bất kỳ worker nào.

## Live evidence và trách nhiệm

Người vận hành tạo HTTPS tunnel công khai thủ công, đăng ký webhook trong Manager hoặc qua
`setWebhook`, rồi verify `testWebhook`/`getMe` mà không in credential. Live acceptance là một private
test message dẫn tới một grounded reply được quan sát; evidence chỉ ghi booleans, counts và timing
sanitise. Ngoài đời, Bot AI chỉ cung cấp thông tin và không thay thế tư vấn pháp lý; người vận hành
chịu trách nhiệm về notice, vận hành và tuân thủ chính sách Zalo.

Đường vận hành chỉ dùng Bot Manager/Bot API và không có automatic send retry. Sự cố
Manager/tunnel/API ngoài được ghi `BLOCKED_EXTERNAL`.
