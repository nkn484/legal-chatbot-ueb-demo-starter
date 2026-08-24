# M04 — Ingestion

- `evidence_finalized_at`: `2026-08-19T08:25:14.488178+00:00`
- Trạng thái milestone: `IN_PROGRESS` — chưa nộp/submit.
- M05: `NOT_STARTED`.
- Trạng thái stack tại thời điểm chốt bằng chứng: đang chạy.

## Phạm vi đã triển khai

M04 cung cấp ingestion trung lập với nguồn (source-neutral), không đưa chi tiết SDK nguồn vào
pipeline. Luồng xử lý gồm lấy snapshot qua cổng nguồn, kiểm tra hash nội dung thô, chuẩn hoá,
chia chunk xác định, embedding theo batch, kiểm tra tính khớp vector, rồi ghi dữ liệu bất biến.

| Khối | Bằng chứng triển khai | Trạng thái |
|---|---|---|
| Orchestration | `IngestionService` source-neutral; xử lý theo snapshot và theo tham chiếu nguồn | PASS |
| Phiên bản bất biến | Document, version, provenance, chunk và embedding được ghi trong transaction repository | PASS |
| Chuẩn hoá/chunk | HTML normalization xác định; chunk có offset, hash và locator nguồn | PASS |
| Embedding | `EmbeddingPort`; `local-hash-v1`, 384 chiều, `demo_non_semantic` | PASS |
| Migration | Alembic revision `0002` tạo các bảng ingestion | PASS |
| Vector index | HNSW cosine index tồn tại và được kiểm tra sau migration | PASS |
| Runtime tool | CLI ingestion và Compose profile `tools` | PASS |

Không có Retrieval, Citation hoặc công việc M05 trong phạm vi M04.

## Phiên bản, idempotency và provenance

Snapshot hash canonical liên kết chứng cứ ổn định với ingestion profile: phiên bản normalizer,
phiên bản chunker, giới hạn/overlap chunk, model và dimension embedding, cùng kind
`demo_non_semantic`. Thời điểm truy xuất và batch size embedding không làm phát sinh phiên bản
mới. Thay đổi nội dung, metadata ổn định hoặc ingestion profile tạo version bất biến mới.

Provenance được lưu cùng version. Mỗi chunk liên kết tới version; mỗi embedding liên kết tới
chunk. HNSW cosine index phục vụ lớp vector của demo, không xác nhận chất lượng ngữ nghĩa.

## Khối bằng chứng đo được

| Kiểm tra | Kết quả | Trạng thái |
|---|---:|---|
| Unit tests | 144 PASS | PASS |
| Full suite với PostgreSQL thật, source live REST/SOAP, ingestion live, migration lifecycle | 151 PASS; 1 skipped (SHINE live đã đo ở M02) | PASS |
| Hồi quy M00 | 50 PASS | PASS |
| Ruff, format, pip check, Compose và diff | PASS | PASS |
| Docker rebuild cuối và khởi động | healthy | PASS |
| Migration live | head tại `0002` | PASS |
| Lifecycle DB tạm | upgrade head → downgrade `0001` → upgrade head; vector giữ được, bảng/HNSW được khôi phục | PASS |
| PostgreSQL synthetic integration | identical là unchanged; content, metadata và profile tạo version; chain/vector/index hợp lệ | PASS |
| Concurrent writers | đúng một `created`, một `unchanged`; một document/version/provenance; số chunk/embedding chính xác | PASS |
| Oracle cuối | không có mandatory fix | PASS |

### Đầu ra live đã được làm sạch

Đầu ra ingestion live chỉ chứa các trường vận hành sau; không ghi nội dung đầy đủ hoặc giá trị
hash:

```json
{"first_chunk_count":53,"first_outcome":"created","hash_present":true,"second_chunk_count":53,"second_outcome":"unchanged","semantic_ready":false}
```

Lần chạy CLI cuối sau live trả về `unchanged`, với `block_count=226`, `chunk_count=53`,
`embedding_count=53`, model `local-hash-v1`, `semantic_ready=false` và summary `failed=0`.
Không ghi UUID cơ sở dữ liệu trong bằng chứng CLI.

### Trạng thái DB cuối cho document allowlist chính xác

| Đối tượng | Số lượng / thuộc tính | Trạng thái |
|---|---:|---|
| Alembic | `0002` | PASS |
| Document | 1 | PASS |
| Version | 1 | PASS |
| Provenance | 1 | PASS |
| Chunk | 53 | PASS |
| Embedding | 53 | PASS |
| Embedding dimension/kind | 384 / `demo_non_semantic` | PASS |
| HNSW cosine index | hiện diện | PASS |

## Bảo mật và quan sát vận hành

- Log API: 8/8 JSON, 0 non-JSON, không có secret: PASS.
- CLI cuối không có log httpx chứa URL đầy đủ: PASS.
- Quét credential: 131 files, 0 phát hiện: PASS.
- Nội dung pháp lý, metadata nguồn chi tiết, vector values, secret, raw identifier và hash value
  không được ghi vào tài liệu bằng chứng hoặc output live đã công bố: PASS.

## Rủi ro còn lại và phần chưa đo

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| Chất lượng semantic của embedding demo | NOT_MEASURED | `local-hash-v1` là demo non-semantic, không phải đánh giá relevance pháp lý. |
| Chất lượng Retrieval/Citation M05 | NOT_MEASURED | Ngoài phạm vi; M05 chưa bắt đầu. |
| Load test và HNSW tuning | NOT_MEASURED | Chưa đo tải, latency hoặc tham số vận hành tối ưu. |
| Chống sửa trực tiếp bởi DB user có đặc quyền | NOT_MEASURED | Transaction/immutable model không thay thế kiểm soát đặc quyền DB. |
| HTML fidelity rộng hơn tập mẫu demo | NOT_MEASURED | Chưa bao phủ toàn bộ biến thể HTML nguồn. |

Không có hạng mục `BLOCKED_EXTERNAL` tại thời điểm chốt: nguồn live, PostgreSQL, migration và
Docker đã được đo thành công. Các mục `NOT_MEASURED` ở trên là residual risks và không phải
demo blocker của M04.

## Ngoài phạm vi

M04 không triển khai semantic retrieval, ranking, citation resolution, hội thoại, M05, hoặc cơ
chế chống can thiệp trực tiếp từ tài khoản DB đặc quyền. Những phần này không được suy diễn từ
bằng chứng ingestion.
