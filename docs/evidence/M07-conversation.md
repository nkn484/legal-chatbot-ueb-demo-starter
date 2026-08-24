# M07 — Bounded Conversation

- `evidence_finalized_at`: `2026-08-19T21:00:05.846494Z`
- Khuyến nghị: **PENDING FINAL ORACLE REVIEW**.
- Trạng thái milestone: M07 `AWAITING_APPROVAL`; M08 `NOT_STARTED`.

## Phạm vi đã triển khai

M07 chỉ triển khai conversation multi-turn bounded, channel-neutral. Không có public API, `ChannelPort`,
Zalo payload/session/cookie/bridge, M08, thay đổi provider/source adapter hoặc semantic work. M08 chưa bị
chỉnh sửa.

Migration head là `0004_conversation_state`, thêm ba bảng chuẩn hóa M07:
`conversations`, `conversation_exchanges`, và `conversation_exchange_references`. Việc persist bounded
`user_text`, `assistant_text`, rolling summary và topic là disclosure privacy mới, chủ động và giới hạn.

| Khối | Hành vi | Trạng thái |
|---|---|---|
| Identity/state | `conversation_id` là UUID server opaque; không có claim auth/ownership | PASS |
| Bounded state | recent turns 4; summary 1500; topic 256; context 1000; refs 6/kind | PASS |
| Lifecycle | retention 7 ngày; lease PROCESSING 120s; terminal retained tối đa 32 | PASS |
| Idempotency | delivery ID chuẩn hóa rồi chỉ persist SHA-256; không có raw delivery ID | PASS |
| Traceability | answer refs server-owned; replay re-resolve citation ID qua M05 | PASS |
| Compaction/purge | compact terminal cũ atomically; chỉ xóa M07, giữ M05 evidence | PASS |

Một conversation chỉ có một `PROCESSING`. Duplicate completed replay không gọi M06/provider và
re-resolve citations theo thứ tự persisted. Duplicate processing/busy không gọi M06. Lease hết hạn được
chuyển `ABANDONED`; không auto replay. Finalization dùng CAS, không retry. Compaction xóa exact oldest
terminal rows trong cùng transaction; purge/deletion chỉ tác động M07, không xóa M05 evidence.

## M06 seam và giới hạn context

- Current question luôn tách khỏi prior context. Temporal guard chỉ áp dụng current request.
- Retrieval query server-owned có thể thêm active topic; conversation context là untrusted, separately
  delimited, non-evidence.
- Khi prompt pressure, context bị omission trước question/evidence. Không có unlimited history.
- Summary/topic là deterministic, không gọi LLM. Chất lượng summary/topic là `NOT_MEASURED`.
- Compaction summary dùng separator hiển thị một dòng ` | `; không nới validator và không cho phép control
  character. Candidate vẫn theo oldest→newest và chỉ giữ newest bounded suffix.

## Privacy, logging và traceability

- M07 persist bounded `user_text`, `assistant_text`, summary/topic đến retention/deletion; M07 structured
  application events không log các field này, raw delivery/digest, conversation/reference IDs,
  context/query/prompt/provider body hoặc error text.
- Delivery digest được persist nhưng không được log. Provider nhận bounded M06 question/evidence/context,
  là disclosure kế thừa M06.
- Không có cột raw `delivery_id`; refs được normalized; không duplicate legal metadata. Bảng M05 không có
  chat content.
- Vertical sentinel/log checks xác nhận M07 events không chứa question, excerpt, summary, provider
  output/exception, conversation/reference UUID hoặc delivery digest trong record dict lẫn JSON formatter
  output.

## Khối bằng chứng đo được

| Kiểm tra | Kết quả | Trạng thái |
|---|---:|---|
| Phase 1 final | Ruff/format PASS; 86 unit PASS; lifecycle disposable `0004→0003→0004→0001→0004` PASS | PASS |
| Phase 2 final sau remediation | 24 unit PASS; 3 PostgreSQL integration PASS; SQLSTATE `23505` race classification và M05 fixture hợp lệ | PASS |
| Phase 3 final | Ruff/format PASS; 67 unit PASS; 5 PostgreSQL integration PASS; duplicate ownership remediation | PASS |
| Phase 4 focused final | Ruff/format PASS; 70 unit PASS; 7 PostgreSQL vertical/repository/migration PASS | PASS |
| Full regression đầu tiên | 375 PASS; 1 FAIL; 2 skipped — sole failure là shared demo DB còn Alembic `0003` | MEASURED |
| Full regression authoritative | 376 PASS; 2 skipped trong 21.36s, sau rebuild migration image/upgrade DB `0004` | PASS |
| M00 regression | 50 PASS | PASS |
| `ruff check src tests` | PASS | PASS |
| `ruff format --check src tests` | 128 files current | PASS |
| `git diff --check` / starter verify | PASS / PASS | PASS |
| Docker compose config, Alembic, migration service, DB, container `pip check`, `/live`, `/ready` | head `0004`; PASS; healthy; PASS; 200; 200 | PASS |

Hai skip của full suite là existing M02 SHINE gate và M06 SHINE gate; mỗi gate được đo riêng. M07 không cần
live provider mới vì chỉ thêm state và tái sử dụng M06 provider boundary/live evidence. Không có conversation
endpoint được kỳ vọng; `/live` và `/ready` 200 không suy ra public conversation API.

Real PostgreSQL multi-turn vertical compose real M05
`PostgresLexicalRetrievalRepository`/`RetrievalService`, real M06 grounding adapter/citation resolver/service
và strict parser, cùng no-network counting fake provider. Fixture dùng source ID unique
`TESTM07VERTICAL`, immutable document/version/provenance/chunks; không chạm VBQPPL/live data. Cases đã đo:

1. First và second grounded turn, bounded prior context và topic query.
2. Duplicate completed: không provider call mới, citation re-resolution đúng thứ tự.
3. No-hit clarification; temporal refusal; pending duplicate/busy/lease hết hạn không replay.
4. Exchange thứ 33 real-M06 compact đúng terminal row cũ, summary continuity và reference counts; M05 giữ lại.
5. Purge M07 giữ retrieval run/citation/document/version/chunk/provenance M05.
6. Privacy/schema inventory và sentinel assertions như nêu trên.

Lỗi production được vertical phát hiện: compaction summary từng join bằng newline, bị strict summary validator
reject. Đã sửa bounded thành separator visible một dòng ` | `, không làm yếu validator; vertical cuối PASS.

## Mapping tiêu chí chấp nhận

| Tiêu chí/blocker | Bằng chứng M07 |
|---|---|
| Multi-turn bounded state | Recent turns, summary/topic/context và retained exchanges đều bounded; không unlimited history. |
| Idempotency/concurrency | Conversation lock, one processing partial unique guard, duplicate states, lease và CAS; repository integration. |
| Traceability/replay | Persisted server refs; duplicate completed re-resolve M05 citations, không gọi provider. |
| Channel-neutral M08 handoff | UUID opaque, không channel data; M08 untouched. |
| Logging/privacy | Fixed safe events, sentinel tests, digest-only persistence và schema inventory. |
| Startup/migration | `0004` head, lifecycle, Docker migration/health checks PASS. |

## Oracle và residual risk

- Oracle Gates 1, 2 và 3: **PASS** sau bounded remediation.
- Final Phase-4/evidence Oracle review: **PASS WITH BOUNDED DOCUMENTATION REMEDIATION**.

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| Legal relevance, answer correctness, currentness | `NOT_MEASURED` | Grounding/traceability không chứng minh legal quality hoặc hiệu lực pháp lý. |
| Semantic quality | `NOT_MEASURED` | Không có semantic/vector retrieval evaluation. |
| Summary/topic quality | `NOT_MEASURED` | Deterministic, không đánh giá semantic quality. |
| Temporal heuristic | `NOT_MEASURED` | Không đánh giá precision/recall hoặc legal temporal validity. |
| Exactly-once provider sau crash | `NOT_MEASURED` | Reservation/lease không chứng minh exactly-once qua crash boundary. |
| Ownership, cross-device identity, encryption, legal retention | `NOT_MEASURED` | UUID opaque không phải authenticated ownership; chưa có encryption/legal retention assessment. |
| Broad load, multi-worker stress, abuse | `NOT_MEASURED` | Chưa có stress/load/abuse evaluation rộng. |
| Digest guessability | `NOT_MEASURED` | Digest vẫn là residual risk nếu delivery identifier có entropy thấp. |

## Điều kiện dừng

M07 đã submit và đang `AWAITING_APPROVAL`. Không bắt đầu M08.
