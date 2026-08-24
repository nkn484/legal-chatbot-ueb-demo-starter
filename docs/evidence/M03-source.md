# M03 — Nguồn pháp luật: lõi, hợp đồng và registry

- `evidence_finalized_at`: `2026-08-19T05:34:55.382502+00:00`
- Khuyến nghị trạng thái: **PASS cho DEMO_NOW**.
- Mốc này chỉ hoàn thiện ranh giới nguồn, hợp đồng và adapter demo; không mở rộng sang M04.

## Kiến trúc và ranh giới

- `LegalSourcePort` độc lập nhà cung cấp/transport là ranh giới bắt buộc cho danh sách tài liệu, lấy tài liệu, health check và đóng tài nguyên.
- Các ref, snapshot, provenance và health là model bất biến (frozen). Snapshot mang SHA-256 của nội dung; provenance ghi nguồn, transport, operation, thời điểm lấy và trạng thái TLS.
- `SourceError` chỉ mang mã lỗi và metadata vận hành đã chuẩn hoá; không đưa nội dung phản hồi từ xa vào lỗi.
- Adapter VBQPPL REST đang hoạt động cho demo. Làn SOAP còn lại fail-closed. VNU và UEB trả `SOURCE_NOT_IMPLEMENTED` mà không tạo kết nối mạng.
- Trường logging nguồn/transport/operation/tài liệu/provenance đã được bổ sung. M03 không có lưu DB, ingestion, index hay persistence.

## Registry và allowlist

Registry canonical được kiểm tra bằng model Pydantic: chỉ có ba hệ thống với priority rollout cố định; priority **không** là xếp hạng thẩm quyền pháp lý. Mỗi ID không được trùng, trạng thái lifecycle/demo được kiểm tra chặt.

- VBQPPL chỉ cho phép đúng hai SOAP operation: `GetListVanBanByListSKH` và `GetVanBanById`.
- SOAP read allowlist và REST fallback read/path allowlist đều giới hạn đúng một tài liệu công khai đã phê duyệt trong M00; document number, canonical URL và path được kiểm tra khớp chính xác.
- VNU/UEB không có URL, operation allowlist hoặc read allowlist hoạt động.

## Kiểm chứng live đã chuẩn hoá

### REST

```json
{"probe":"vbqppl_rest_adapter_live","outcome":"PASS","listed_one":true,"fetched":true,"content_chars":75971,"hash_present":true,"canonical":true,"list_duration_ms":0.04,"fetch_duration_ms":379.565,"total_duration_ms":379.604,"tls_verified":true,"transport":"REST_FRONTEND_BACKING_API"}
```

Kết quả REST xác nhận một ref allowlisted, lấy được snapshot có nội dung bị giới hạn, có hash, canonical khớp và TLS đã xác minh. Không ghi lại nội dung, metadata pháp lý hay giá trị hash.

### SOAP

```json
{"probe":"vbqppl_soap_adapter_live","outcome":"BLOCKED_EXTERNAL","status":"unhealthy","error_code":"unavailable","tls_verified":false,"wsdl_requests":1,"soap_posts":0}
```

Đây là `BLOCKED_EXTERNAL`, không phải PASS hay lỗi nội bộ. Adapter không thực hiện SOAP POST sau khi health xác định transport ngoài không sẵn sàng; hành vi fail-closed được giữ nguyên.

## Bảng kiểm thử và an toàn

| Hạng mục | Kết quả | Ghi nhận |
| --- | --- | --- |
| Unit suite | **PASS** | 108 PASS |
| Full suite (PostgreSQL thật, REST live, SOAP live health) | **PASS** | 111 PASS, 1 skipped do SHINE live gate đã đo ở M02; không phải thất bại |
| Hồi quy M00 | **PASS** | 50 PASS |
| REST adapter tests sau sửa lỗi | **PASS** | 23 PASS; live cuối cùng PASS |
| Ruff, format và `pip check` | **PASS** | Hoàn tất không lỗi |
| Source registry JSON | **PASS** | JSON hợp lệ |
| Docker rebuild/start và compose config | **PASS** | Hoàn tất |
| Git diff check | **PASS** | Hoàn tất |
| Quét giá trị credential thực tế | **PASS** | 109 files, 0 matches |
| Oracle final review | **PASS** | Không có mandatory fix |

Lần REST live đầu tiên phát hiện thiếu `Host` do thay toàn bộ manual headers. Lỗi đã được xử lý bằng `httpx.Request` độc lập, giữ `Host` cần thiết đồng thời loại bỏ auth/default header kế thừa; kết quả test và live cuối cùng ở trên xác nhận bản sửa.

## Ngữ nghĩa provenance

Provenance là bằng chứng về đường lấy dữ liệu, không phải chỉ thị cho LLM: văn bản nguồn và dữ liệu ngoài được xem là dữ liệu không tin cậy. Citation về sau phải được giải quyết từ evidence retrieval; M03 không tự suy diễn metadata pháp lý và không lưu snapshot vào persistence.

## Rủi ro còn lại và chưa đo

| Hạng mục | Trạng thái | Hệ quả |
| --- | --- | --- |
| Secure SOAP functional fetch | **NOT_MEASURED** | SOAP live hiện bị external availability chặn; chưa chứng minh fetch chức năng qua TLS |
| VNU/UEB live | **NOT_MEASURED** | Chỉ có placeholder no-network, chưa có adapter/live access |
| Attachments và relations | **NOT_MEASURED** | Chưa nằm trong source slice hiện tại |
| Frontend API SLA | **NOT_MEASURED** | REST fallback là đường demo được allowlist, chưa có SLA/thay thế được bảo đảm |
| Canonical byte equivalence | **NOT_MEASURED** | Chỉ xác nhận canonical/provenance ở mức hợp đồng, không so byte-to-byte |
| Persistence, versioning, chunking | **NOT_MEASURED** | Thuộc M04, chưa triển khai |

Rủi ro chính còn lại là phụ thuộc availability của nguồn bên ngoài và phạm vi allowlist cố ý hẹp. REST fallback chỉ được dùng read-only trong allowlist; SOAP không được hạ cấp thành thành công khi transport ngoài không khả dụng.

## Ngoài phạm vi và điều kiện dừng

Ngoài phạm vi M03: DB model/migration, persistence, ingestion, chunking, embeddings/index, retrieval, attachments/relations và bất kỳ mở rộng API nguồn nào.

- M03: `IN_PROGRESS`, chưa submitted.
- M04: `NOT_STARTED`.

Dừng tại đây: evidence ghi nhận M03 PASS cho DEMO_NOW, nhưng không tự khởi động mốc tiếp theo.
