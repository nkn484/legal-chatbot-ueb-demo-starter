# M08 — Runbook Zalo Bot Manager chính thức

> Bot trả lời bằng AI chỉ mang tính thông tin, không thay thế tư vấn pháp lý. Người vận hành chịu
> trách nhiệm về thông báo, nội dung đã công bố, quyền sử dụng Bot và tuân thủ chính sách Zalo.

## 1. Tạo Bot và cấu hình bí mật

1. Tạo/quản lý Bot trong Zalo Bot Manager chính thức: <https://bot.zaloplatforms.com/>.
2. Nhập token Bot được Manager cấp vào `ZALO_OFFICIAL_BOT_TOKEN` trong `.env` đã bị Git ignore.
   Không in, commit, dán vào shell history hoặc đưa token vào evidence.
3. Tạo hai secret độc lập, không ghi đè giá trị đã có:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\new_m08_secrets.ps1 -EnvFile .\.env
   ```

   Lệnh chỉ thêm `ZALO_OFFICIAL_BOT_WEBHOOK_SECRET` và `CHANNEL_IDENTITY_HMAC_KEY`; token Bot là
   credential do Zalo cấp và phải được nhập thủ công.

## 2. Khởi động API

```powershell
docker compose --env-file .env -f compose.yaml -f compose.m08.yaml up -d db
docker compose --env-file .env -f compose.yaml -f compose.m08.yaml run --rm migrate
docker compose --env-file .env -f compose.yaml -f compose.m08.yaml up -d api
Invoke-WebRequest -UseBasicParsing http://localhost:8000/live
```

Đường chính thức chỉ chạy API trong Compose; không cần tiến trình phụ.

## 3. HTTPS public và webhook

Tạo tunnel HTTPS public đến API bằng công cụ do người vận hành chọn và giữ tunnel chạy. Xác nhận
URL HTTPS public trước khi đăng ký webhook. Đăng ký URL qua giao diện Bot Manager, hoặc theo endpoint
Bot API chính thức `POST https://bot-api.zaloplatforms.com/bot<TOKEN>/setWebhook`; không in token khi
thực hiện. API Bot cùng dùng các endpoint `getMe` và `sendMessage` trên
`https://bot-api.zaloplatforms.com/bot<TOKEN>/...`.

Thiết lập webhook secret từ `.env` trong giao diện Manager. Không đưa URL tunnel riêng, token,
secret, payload, ID người dùng hoặc nội dung tin nhắn vào evidence.

## 4. Kiểm tra an toàn và live path

Trong Manager, chạy `testWebhook`. Kiểm tra `getMe` bằng credential cục bộ mà không in request URL,
token hoặc response body; chỉ ghi nhận status/boolean. Sau đó gửi **một** tin nhắn riêng tư từ người
dùng thử nghiệm và quan sát **một** grounded reply có citations được server sở hữu.

Ghi booleans, counts và thời lượng vào
`docs/evidence/M08-zalo-bot-live-template.md`; không ghi text, citation, ID, token, secret hoặc raw
payload. Callback deadline và retry của callback là `NOT_MEASURED`; không có automatic send retry.

Nếu Manager, tunnel hoặc API bên ngoài không khả dụng, ghi `BLOCKED_EXTERNAL`; không tự chuyển sang
cơ chế khác hoặc retry gửi tự động.

## 5. Kết thúc

```powershell
docker compose --env-file .env -f compose.yaml -f compose.m08.yaml down
```

Giữ `.env` cục bộ và xoay token/secret theo quy trình quản trị khi cần.
