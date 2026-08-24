# M05 — Retrieval + Citation

- `evidence_finalized_at`: `2026-08-19T15:14:20.5252723Z`
- Khuyến nghị triển khai M05: **APPROVE M05**; final assurance `93% — High`.
- Trạng thái milestone: `AWAITING_APPROVAL`; M06: `NOT_STARTED`.

## Phạm vi đã triển khai

M05 chỉ triển khai **Retrieval + Citation**. Không có Chat, LLM, provider, channel, conversation
hoặc API endpoint trong phạm vi này. `ANSWER_OR_REFUSAL` vẫn thuộc trách nhiệm M06, không phải
quyết định evidence retrieval của M05.

| Khối | Bằng chứng triển khai | Trạng thái |
|---|---|---|
| Migration | Head `0003_retrieval_citation`; `search_vector` generated stored bằng `to_tsvector('pg_catalog.simple', content_text)` và GIN index | PASS |
| Traceability | `retrieval_runs` và `citation_records`; FK evidence restrictive để bảo vệ citation | PASS |
| Retrieval live | Lexical PostgreSQL FTS, `websearch_to_tsquery` parameterized, repeatable-read transaction | PASS |
| Citation | Server/service tạo citation và resolve chain chứng cứ chính xác | PASS |
| Temporal | Persist zero-evidence `UNSUPPORTED_TEMPORAL_SCOPE` | PASS |

## Hành vi retrieval và giới hạn pháp lý

- Query bị bound tối đa 4000 ký tự; `top_k` từ 1 đến 20.
- Scope `LATEST_INGESTED` lọc version lớn nhất của mỗi document identity **trước** rank/limit,
  sau đó sắp xếp xác định theo score rồi UUID. Đây là snapshot ingest mới nhất, **không** phải
  văn bản legally current/effective.
- Đường live chỉ lexical. `local-hash-v1` vẫn là `demo_non_semantic`: không query vector, vector
  SQL, semantic call hoặc đóng góp RRF live. RRF chỉ là helper unit thuần cho fake ranking lists.
- Request temporal/as-of/current-effect ghi run không evidence với
  `UNSUPPORTED_TEMPORAL_SCOPE`. M05 không suy diễn amendment, replacement, repeal, validity hoặc
  legal effect từ full text, `effective_date` hay `legal_status`.

## Citation và an toàn dữ liệu

- Citation do server/service tạo; chain resolve là `citation -> run -> chunk -> immutable version
  -> document -> exact persisted provenance`.
- Khi ghi và resolve, provenance phải thuộc cùng version với chunk. Citation lịch sử vẫn resolve
  sau version/provenance mới; không bị coi là stale chỉ vì ingestion mới hơn.
- `ResolvedCitation` không chứa `content_text`.
- M05 application persistence và structured application logs không persist/log raw query hoặc SHA
  digest của query; log chỉ dùng fixed safe fields/static events và normalized error codes.

## Khối bằng chứng đo được

| Kiểm tra | Kết quả | Trạng thái |
|---|---:|---|
| Full suite PostgreSQL stateful sau remediation, migration lifecycle, VBQPPL REST/SOAP live gates và ingestion live | 185 PASS; 1 skipped trong 11.18s | PASS |
| M00 regression | 50 PASS | PASS |
| Remediation focused: live ingestion + migration lifecycle | 2 PASS | PASS |
| Phase 2 focused | 43 unit PASS; 5 PostgreSQL integration PASS | PASS |
| Schema/contracts focused trước đó | 14 unit PASS; 2 PostgreSQL integration PASS | PASS (đã nằm trong full suite, không double-count) |
| M05-scoped Ruff check và Ruff format | PASS sau formatting | PASS |
| `git diff --check` | PASS | PASS |
| Docker-isolated `pip check` | PASS | PASS |
| Docker image cuối, DB, `/live`, `/ready` | rebuilt; healthy; 200; 200 | PASS |

SHINE live vẫn gated và đã được đo ở M02, là lý do một test full suite được skip. Host `pip check`
có xung đột global không thuộc dự án: `composio-core` yêu cầu `Pillow<11`, trong khi host có
`Pillow 12.3.0`; bằng chứng dependency của project là Docker-isolated `pip check` PASS.

### Post-audit compatibility, remediation và trạng thái re-review

- Post-submit compatibility audit ban đầu rerun full suite stateful ghi nhận `184 PASS; 1 FAIL; 1 skipped`.
  Failure duy nhất là live M04 test cũ xóa destructively fixed VBQPPL document, trong khi M05 citations
  đúng đắn bảo vệ provenance/chunks của document đó bằng `RESTRICT`. Đây là regression-harness
  incompatibility, không phải production ingestion API failure đã được chứng minh.
- Remediation hoàn tất tại `tests/integration/test_ingestion_live.py` mà không weaken hoặc delete
  evidence: test non-destructive, state-tolerant; ingestion đầu có thể `created`/`unchanged`, ingestion
  thứ hai phải `unchanged`, cùng document/version và chunk/embedding counts dương, bằng nhau. Không có
  citation/run/provenance deletion và không có FK change.
- Disposable migration lifecycle đã đo và PASS:
  `0003 head -> 0002 -> 0003 head -> 0001_enable_pgvector -> 0003 head`. Tại `0001`, vector extension
  vẫn hiện diện còn M04/M05 tables/indexes vắng mặt; final head schema được restore. Kết quả này thay thế
  mọi hàm ý `NOT_MEASURED` trước đó cho composed lifecycle `0003 -> 0001 -> 0003`.
- Focused remediation evidence: M05-scoped Ruff check/Ruff format `PASS`; live ingestion + migration
  lifecycle `2 PASS`; M00 regression `50 PASS`. Full suite stateful cuối sau remediation là bằng chứng
  regression hiện hành: `185 PASS; 1 skipped` trong `11.18s`.
- Oracle post-remediation re-review: **APPROVE M05**; final assurance `93% — High`.

### Probe corpus live đã làm sạch

Không công bố query, nội dung, UUID hoặc hash. Probe ghi nhận:

| Tình huống | Candidates / citations | Decision |
|---|---:|---|
| Legal term đã biết | 3 / 3 | `EVIDENCE_AVAILABLE` |
| Vietnamese term có dấu | 3 / 3 | `EVIDENCE_AVAILABLE` |
| Tương đương không dấu | 0 / 0 | `NO_RESULTS` |
| No-match đã biết | 0 / 0 | `NO_RESULTS` |

Citation resolve có cùng run/citation/chunk; source là VBQPPL; external/version/provenance IDs hiện
diện; `content_text` vắng mặt. Probe persist tăng 4 runs và 6 citations;
`semantic_used=false`; `raw_query_persisted=false`.

## Oracle và residual risk

- Oracle Gate 1: `PASS WITH` bounded remediation; remediation đã hoàn tất.
- Oracle Gate 2: `PASS TO PHASE 3`.
- Lịch sử Final Oracle Gate 3 trước audit/remediation: **PASS WITH BOUNDED DOCUMENTATION REMEDIATION**.
- Oracle post-remediation re-review: **APPROVE M05**.

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| Vietnamese relevance/recall | `NOT_MEASURED` | PostgreSQL simple FTS không có stemming/diacritic normalization; hành vi có dấu/không dấu đã đo nhưng không phải proof relevance pháp lý. |
| Semantic retrieval/relevance | `NOT_MEASURED` | Đã disabled; embedding demo non-semantic. |
| Legal effect, amendment/repeal, temporal validity | `NOT_MEASURED` / ngoài phạm vi | Không được suy diễn bởi M05. |
| Full-repository Ruff | Residual pre-existing | Không sạch do 423 legacy M00 spike findings và 19 findings có sẵn tại Alembic `0001`/`0002`/`env`; mọi tệp M05-owned/touched đều PASS. |
| Direct DB mutation đặc quyền; corpus/load quality rộng hơn | `NOT_MEASURED` | Không được che giấu bởi transaction/FK hiện có. |

## Mapping tiêu chí chấp nhận

| Tiêu chí | Bằng chứng M05 |
|---|---|
| Retrieval traceability | Run opaque, scope/decision/reason/counts persisted; lexical retrieval bounded và xác định. |
| Citation traceability | Citation liên kết exact chunk, immutable version, document và provenance cùng version; resolver kiểm tra chain. |
| Fail closed | Temporal scope không hỗ trợ tạo zero evidence; chain sai dùng normalized evidence/error outcome, không mở rộng claim. |
| Bảo vệ evidence | Run+citation atomic và citation FK restrictive; không có raw query/chunk text trong M05 application persistence hoặc structured application logs đã kiểm thử. |
| Ranh giới answer | M05 chỉ trả retrieval-level evidence; M06 sở hữu `ANSWER_OR_REFUSAL`, answer/clarify/refuse. |

## Điều kiện dừng

M05 đã submit để user approval và dừng tại `AWAITING_APPROVAL`. Không tự động bắt đầu M06.
