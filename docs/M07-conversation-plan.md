# M07 — Kế hoạch Bounded Multi-turn Conversation

## Gate bắt buộc và trạng thái hiện tại

M06 là `PASS`; M07 là `NOT_STARTED`; M08 là `NOT_STARTED`. M07 phụ thuộc M06 và sở hữu demo
blocker `multi-turn conversation`. Tài liệu này chỉ là kế hoạch, **không** là approval triển khai.

- Không start hoặc implement M07 trước approval rõ ràng của user.
- Chỉ dùng `python scripts/demo_gate.py ...` để xem/chuyển gate; không bao giờ sửa trực tiếp
  `.demo-run/state.json`.
- Workflow: inspect → plan → user approval → implement M07 hiện tại → tests/evidence → submit → dừng.

## Mục tiêu, phạm vi và ranh giới

M07 thêm conversation state channel-neutral, bounded, nằm trên M06. State bắt buộc gồm recent turns,
rolling summary, active legal topic, referenced document IDs và recent citation IDs; tuyệt đối không gửi
hoặc lưu unlimited history.

Ngoài phạm vi: M08 `ChannelPort`, Zalo payload/session/cookie/bridge, public API, provider/source
adapters, semantic work và M09. Không có Zalo identity trong M07. Identity là `conversation_id` UUID
opaque do server sinh; M07 không tuyên bố authentication/authorization. M08 sau này sở hữu mapping
actor/channel.

## Module, migration và writer scope đề xuất

Các file triển khai tương lai:

- `src/legal_chatbot/conversation/{__init__,models,config,errors,port,policy,service,orm,repository}.py`
- `alembic/versions/0004_conversation_state.py`; cập nhật `alembic/env.py`.
- Focused unit/integration tests và migration lifecycle tests.

Không sửa M08 hoặc làm channel-specific work trong writer scope M07.

## Quyết định persistence

Không dùng free JSONB state bag. Ba bảng normalized, deterministic:

| Bảng | Trường và ràng buộc |
|---|---|
| `conversations` | `id`, `state_version`, `rolling_summary` ≤1500, `active_topic` ≤256, timestamps `created/updated/expires/deleted`. |
| `conversation_exchanges` | `id`, `conversation_id` CASCADE, `delivery_key_sha256` CHAR(64), `ordinal`, status `PROCESSING`/`COMPLETED`/`FAILED`/`ABANDONED`, `lease_expires_at`, `user_text` ≤4000, `assistant_text` ≤4000 nullable đến terminal, chat outcome/reason, `retrieval_run_id` nullable FK RESTRICT, safe optional provider/model/request ID, `created/completed`. Unique `(conversation, delivery digest)` và `(conversation, ordinal)`; partial unique một `PROCESSING` mỗi conversation. |
| `conversation_exchange_references` | `exchange_id` CASCADE, kind `CITATION`/`DOCUMENT`, reference UUID, `ordinal`; rows normalized deterministic, tối đa 6 mỗi kind, unique `(exchange, kind, reference)` và `(exchange, kind, ordinal)`. |

Không FK reference table sang M05 citation/document; M05 vẫn là authority. Không duplicate legal metadata.

## Domain contracts và M06 context seam

- Contracts: create conversation; `ConversationRequest(conversation_id, delivery_id, text, temporal_scope)`;
  statuses/outcomes; derived `ConversationTurn`/`ConversationContext`/`ConversationResult`; narrow
  `GroundedChatPort`.
- `delivery_id` được normalize rồi SHA-256 mới persist; raw delivery ID không bao giờ log.
- M06 được mở rộng backward-compatible bằng `ChatRequest.retrieval_query` server-only optional và
  `conversation_context` bounded optional (hoặc value model tương đương); defaults giữ nguyên hành vi M06.
- Temporal guard chỉ scan current `question`. Retrieval dùng `retrieval_query` do server sinh: current
  question + active topic, ≤4000. Nếu current text >4000, trả fixed clarification trước M06; không im
  lặng truncate current text.
- Prompt thêm conversation context dưới JSON delimiters/escaping riêng, như untrusted data. Prior history
  không phải grounding evidence; `GroundingEvidencePort` vẫn là nguồn excerpt duy nhất.
- Prompt ceiling vẫn 12000, không tăng bound M06. Context tối đa 1000 và bị omit deterministic trước
  current question/evidence khi thiếu chỗ.

## Bounded state và policy mặc định

Tất cả defaults shrink-only: 4 recent completed turns theo oldest→newest; summary 1500; topic 256;
references 6 mỗi kind; context 1000; retained exchanges 32; retention 7 ngày; processing lease 120 giây.

Summary là cơ học, deterministic từ normalized snippets/outcomes/reference counts của turn bị evict;
không gọi LLM summarization. Chất lượng summary là `NOT_MEASURED`. Active topic là label bounded,
deterministic từ current user text, không phải legal conclusion.

## Service và concurrency flow

1. Transaction A create/get conversation, expire stale `PROCESSING` thành `ABANDONED`, reserve
   idempotent delivery và user data với expected `state_version`; partial unique bảo đảm một processing.
2. Duplicate `COMPLETED` trả persisted result, không gọi M06. Duplicate pending hoặc delivery khác khi
   busy trả `IN_PROGRESS`/`BUSY`, không gọi M06. Delivery expired không auto-replay; cần delivery ID mới.
3. Tạo snapshot/context bounded và gọi M06 đúng một lần **ngoài** transaction/lock.
4. Transaction B CAS revision/status, persist terminal result/references/topic/summary, increment
   `state_version`, compact exchanges/state atomically. Conflict trả retryable `CONVERSATION_CONFLICT`;
   M06 retrieval run có thể còn immutable audit evidence nhưng không attached.
5. `REFUSAL` và `CLARIFICATION` là terminal persisted results, không có references.

## Privacy, retention và logging

Khác M06, M07 cố ý persist user/assistant text. Retention mặc định 7 ngày, chỉ được giảm; cap 32
exchanges. Deletion cascade chỉ xóa M07 rows, không bao giờ xóa M05 evidence.

Không log key/delivery/user/assistant/summary/topic/reference IDs/prompt/provider body. Đề xuất fixed
events: `conversation_reserved`, `conversation_completed`, `conversation_busy`,
`conversation_conflict`, `conversation_expired`, `conversation_failed`; fixed safe fields chỉ gồm
outcome/reason/status/counts/ordinal/state version/duration/normalized error code. Safe errors gồm
`CONVERSATION_NOT_FOUND`, `CONVERSATION_EXPIRED`, `IN_PROGRESS`, `BUSY`,
`CONVERSATION_CONFLICT`, `DELIVERY_INVALID`, `STATE_INVALID`. Encryption, auth và legal retention là
`NOT_MEASURED`.

## Đồ thị triển khai theo pha và Oracle gates

| Pha | Writer scope không chồng lấn | Gate bắt buộc |
|---|---|---|
| 1 | Contracts/policy, M06 seam, schema/migration metadata tests | Oracle: bounds, backward compatibility, no M08/channel work. |
| 2 | Repository, concurrency, idempotency, retention | Oracle: transaction/lease/CAS invariants. |
| 3 | Context/summary/service với fake M06 | Oracle: context separation, one-call behavior, privacy. |
| 4 | PostgreSQL multi-turn vertical, optional live path gated riêng, regressions/evidence/submit | Oracle: vertical/migration/regression/Docker evidence. |

Phase sau không bắt đầu trước Oracle gate phase trước. Live path, nếu có, phải separately gated và không
thay fake/PG tests. Credentials chỉ runtime; không vào Git, prompt hoặc logs.

## Ma trận verification bắt buộc

- Model bounds; no unlimited-history; prompt context separation; retrieval-query/temporal separation.
- Duplicate không gọi M06 lần hai; concurrent cùng/khác delivery; lease expiry không replay; CAS conflict;
  sequence/state-version consistency.
- References server-derived; retention/compaction/deletion; bảo toàn M05 FK/evidence; privacy sentinels.
- Migration lifecycle `0004→0003→0001→0004`; regressions M00–M06; Docker health/startup.

## Mapping acceptance/evidence

| Tiêu chí | Evidence tương lai |
|---|---|
| Multi-turn conversation blocker | Bounded recent turns, summary/topic/refs, fake và PG vertical multi-turn tests. |
| State bounds | Schema/contracts/compaction tests. |
| Traceability | Server-derived deterministic references và preserved M05 evidence. |
| Channel-neutral handoff | No Zalo identity/payload; narrow port cho M08 handoff sau này. |
| Structured logs/tests/startup | Fixed safe logs, privacy sentinels, migration/regressions/Docker health. |

Không được nâng các hạng mục sau thành PASS: legal quality; summary/topic quality; exactly-once crash
behavior; authenticated ownership; cross-device identity; encryption; broad load. Tất cả là
`NOT_MEASURED`.

## Shortcut bị từ chối và điều kiện dừng

Từ chối: JSONB state bag tự do; unlimited history; LLM summary/topic; raw delivery ID/logging; replay
delivery expired; giữ lock khi gọi M06; client-authored references; FK reference trực tiếp làm M05 mất
authority; Zalo/session/channel mapping; public API; semantic work; implementation không có approval.

Sau future implementation và evidence, submit M07 rồi dừng trước M08. Không có implementation hiện tại.
