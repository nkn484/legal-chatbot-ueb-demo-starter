# M02 — Provider: Báo cáo bằng chứng

- `evidence_finalized_at`: `2026-08-19T04:07:34.419711+00:00`
- Khuyến nghị implementation M02: **PASS**
- Trạng thái milestone hiện tại: **IN_PROGRESS**, chưa submit.
- M03: **NOT_STARTED**.

## Trạng thái và khuyến nghị

M02 đạt **PASS** theo kết quả kiểm thử, kiểm chứng Docker và oracle final review. Kết quả này là khuyến nghị cho implementation; không thay đổi trạng thái milestone. M02 vẫn `IN_PROGRESS`, chưa submit, và dừng trước M03.

## Kiến trúc và boundary

- Hợp đồng provider-neutral gồm `GenerationRequest`, `GenerationResult` và `ProviderHealth` bất biến (frozen).
- `LLMProviderPort` là boundary async; Chat/RAG không phụ thuộc SDK hoặc HTTP client đặc thù provider.
- `ProviderError` chỉ mang mã lỗi an toàn, cùng metadata retry/status/request ID đã được chuẩn hóa.
- `ProviderSettings` tách riêng, được kiểm tra; `LLM_API_KEY` là biến ưu tiên và `SHINE_API_KEY` là alias chuyển tiếp.
- `ProviderRegistry` cùng default SHINE factory import adapter theo lazy path. Claude/Anthropic hiện là extension point chưa đăng ký.
- Có `ShineShopAdapter` async và các trường logging JSON cố định cho provider.
- `httpx` là runtime dependency.
- Provider chưa được nối vào app readiness theo thiết kế; chỉ được nối ở milestone Chat.

## Kết quả live đã chuẩn hóa

Live test được chạy **đúng một lần** sau healthy exact-model check. Output text không được in ra hoặc lưu lại.

```json
{"generation_attempts":1,"generation_duration_ms":3943.577,"generation_request_id":"req_8adb8977ce2c4c68b9ddddffa9bfdf4f","health_duration_ms":872.055,"health_request_id":"req_0196aece9b0146fea1e8ddc604328c9d","model":"gpt-5.6-sol","outcome":"PASS","output_text_chars":5,"probe":"shineshop_adapter_live","provider":"shineshop","stream":false}
```

## Retry và error behavior

- Mocked evidence xác nhận generate thực hiện đúng một `POST`, không retry, và luôn `stream=false`.
- Input/output/response/timeouts đều bị giới hạn.
- Error mapping đã kiểm tra cho 400/401/403/404/408/413/429/5xx.
- Request ID an toàn; health `GET` retry có giới hạn; hỗ trợ `Retry-After` dạng numeric và HTTP-date.
- Exact model, redaction, ownership close, registry và Claude fake extension đều đã được kiểm tra bằng mocked evidence.

## Bảng kiểm thử và bảo mật

| Hạng mục | Trạng thái | Kết quả đo |
|---|---|---|
| Provider/foundation unit suite | PASS | 65 PASS. |
| M01/M02 non-live với PostgreSQL thực | PASS | 66 PASS; 1 live SHINE bị gate skip. |
| M00 regression | PASS | 50 PASS. |
| Ruff check và format | PASS | PASS. |
| Isolated venv `pip check` | PASS | PASS. |
| Docker rebuild/start | PASS | PASS. |
| Compose config | PASS | PASS. |
| Git diff check | PASS | PASS. |
| Credential actual-value scan | PASS | 93 files, 0 matches. |
| Oracle final review | PASS | PASS, không có mandatory fix. |
| Live SHINE probe | PASS | Chạy đúng một lần; kết quả đã chuẩn hóa ở trên. |

## Bằng chứng bảo mật

- Secret provider dùng cấu hình tách riêng, có redaction và kiểm tra fail-fast.
- Key ưu tiên/chuyển tiếp được kiểm tra mà không đưa credential vào log, exception hoặc báo cáo.
- Provider logging chỉ dùng các trường JSON cố định; request ID được sanitize.
- Scan giá trị thực xác nhận 0 credential match trên 93 files.
- Output của live probe không được in hoặc lưu; chỉ số ký tự output được lưu trong kết quả chuẩn hóa.

## NOT_MEASURED

| Hạng mục | Trạng thái | Lý do |
|---|---|---|
| Claude adapter | NOT_MEASURED | Chỉ có extension point chưa đăng ký, chưa có adapter. |
| Live error paths | NOT_MEASURED | Không tạo lỗi live ngoài probe được gate. |
| Streaming | NOT_MEASURED | M02 chỉ kiểm chứng non-streaming (`stream=false`). |
| Future provider availability, quota, schema | NOT_MEASURED | Phụ thuộc provider bên ngoài và chưa nằm trong probe hiện tại. |

## Rủi ro còn lại

- Availability, quota và schema tương lai của provider là yếu tố bên ngoài cần operator theo dõi.
- Claude/Anthropic chưa có adapter; chỉ có registry extension point.
- Provider chưa được nối vào application flow cho đến milestone Chat.

## Xác nhận ngoài phạm vi

Không triển khai Chat, RAG, source, channel, app readiness integration hoặc migration trong M02.

## Điều kiện dừng

M02 dừng tại đây: vẫn `IN_PROGRESS`, chưa submit; không bắt đầu M03 và M03 vẫn `NOT_STARTED`. Docker stack M01 hiện vẫn chạy và healthy để phục vụ demo verification.
