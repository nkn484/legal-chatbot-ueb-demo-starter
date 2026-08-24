# M06 — Grounded Chat

- `evidence_finalized_at`: `2026-08-19T17:57:44.5483207Z`
- Khuyến nghị triển khai M06: **PASS TO SUBMIT**.
- Trạng thái milestone: M06 `AWAITING_APPROVAL`; M07 `NOT_STARTED`.

## Phạm vi đã triển khai

M06 chỉ triển khai **Stateless internal Grounded Chat**. Không có public chat API, conversation,
history/session, channel/Zalo, chat persistence, migration, semantic/vector retrieval hoặc source
fetching. M07 và M08 không bị chỉnh sửa.

| Khối | Bằng chứng triển khai | Trạng thái |
|---|---|---|
| Provider boundary | Tái sử dụng `LLMProviderPort`; provider thực được tạo qua registry/factory | PASS |
| Retrieval/citation | Tái sử dụng M05 retrieval và citation traceability | PASS |
| Grounding | Dùng exact grounding-evidence adapter, sau đó resolver revalidate citation server-owned | PASS |
| Provider output | Provider chỉ trả prose; parser strict JSON chỉ nhận answer | PASS |
| Outcome | `ANSWER` / `CLARIFICATION` / `REFUSAL` xác định; các nhánh không gọi provider và mapping fail-closed | PASS |

Prompt xem question, retrieved text và external text là untrusted data: JSON delimiters/escaping và
giới hạn kích thước được áp dụng. Parser không nhận metadata nguồn do provider tạo. Lỗi được chuẩn hóa;
structured logs chỉ có fixed safe events/fields.

## Hành vi grounding và giới hạn pháp lý

- Citation được server sở hữu và revalidate **sau** generation theo chain M05: retrieval run,
  citation, chunk, immutable version, document và provenance cùng version.
- `ANSWER` chỉ hợp lệ khi có evidence và citation đã revalidate; thiếu evidence, chain lỗi, lỗi
  grounding/provider/parser/resolver đều đi theo `CLARIFICATION` hoặc `REFUSAL` fail-closed đã định
  nghĩa. Refusal fail-closed không phải PASS của positive live smoke.
- Retrieval live vẫn là lexical đơn giản của M05; không có semantic/vector retrieval. Đây không phải
  bằng chứng relevance, entailment, answer correctness hoặc legal correctness.
- Temporal guard chỉ là heuristic bounded; không suy luận legal currentness, amendment, repeal,
  hiệu lực hoặc temporal validity.

## Privacy và traceability

- Application persistence và application logging không lưu/log question, hash của question, prompt,
  excerpt/chunk, model response hoặc provider body. Provider tất yếu nhận question/evidence đã bound để
  sinh câu trả lời; đó là disclosure tại provider boundary, không phải application persistence.
- Logs dùng fixed event/field và normalized code; sentinel tests kiểm tra ranh giới này.
  Retrieval runs/citations chỉ persist traceability M05, không persist chat content.
- Live payload chỉ chứng minh path availability và grounded traceability; không công bố question,
  answer, prompt, excerpt, UUID/citation ID, hash, document metadata, provider body hay credential.

## Khối bằng chứng đo được

| Kiểm tra | Kết quả | Trạng thái |
|---|---:|---|
| Phase 1 final | Ruff/format PASS; 54 unit PASS | PASS |
| Phase 2 | 8 unit PASS; 1 PostgreSQL integration PASS | PASS |
| Phase 3 final sau remediation | Ruff/format PASS; 99 chat/fake integration PASS | PASS |
| Phase 4 PostgreSQL grounded-chat vertical | 1 PASS | PASS |
| M00 regression | 50 PASS | PASS |
| `ruff check src tests` và `ruff format --check src tests` | PASS; 104 files formatted/current | PASS |
| `git diff --check` | PASS | PASS |
| `verify_starter_pack.py` | PASS sau remediation verifier | PASS |
| Docker-isolated `pip check` | Không có broken requirements | PASS |
| Docker image cuối, migration service, DB, `/live`, `/ready` | rebuilt; PASS; healthy; 200; 200 | PASS |

Phase 4 dùng real M05 repository/retrieval, Phase-2 grounding adapter, resolver,
`GroundedChatService` và strict parser. Các case đã đo: known-hit `ANSWER`, no-hit
`CLARIFICATION`, temporal explicit + guard `REFUSAL`, cross-version grounding `REFUSAL` và provider
failure `REFUSAL`; đồng thời có privacy/schema/count checks.

`verify_starter_pack.py` ban đầu có false positive từ `.opencode/node_modules` generated. Verifier đã
được sửa để bỏ qua generated dependency/cache/build directories khi scan source; kết quả cuối PASS.
Docker không kỳ vọng chat endpoint; `/live` và `/ready` là 200, không có public chat API.
Migration vẫn ở head `0003`; không có migration M06 hoặc chat tables.

### Real SHINE live smoke

Live smoke real provider có kết quả **1 PASS trong 10.66s**: đúng một real generation call, health
`healthy`, provider `shineshop`, model `gpt-5.6-sol`, outcome `ANSWER` /
`ANSWER_GROUNDED`, 3 citations `VBQPPL`, traceability complete và `semantic_used=false`.

| Trường payload đã sanitize | Giá trị |
|---|---|
| Health request ID | `req_6867e1cbeec04400a82132c27c9140e4` |
| Generation request ID | `req_a514eda9f1c44baf993ed5a8fa0246f0` |
| Generation calls | `1` |
| Citation count | `3` |
| Traceability complete | `true` |
| Semantic used | `false` |

Lần gated đầu tiên có **zero provider calls** và chỉ fail ở global shared-DB precondition quá chặt,
yêu cầu toàn bộ database phải chỉ có VBQPPL. Precondition này không phù hợp với DB stateful có synthetic
integration fixtures. Test được sửa có giới hạn: không source fetch/ingestion/delete/cleanup, retrieval
từ existing DB, và chỉ PASS khi mọi citation **trả về** là `VBQPPL`; lần final với một generation PASS.

Full suite cuối với PostgreSQL, migration lifecycle, REST/SOAP live gates, ingestion live và M06 live
vẫn gated off: **294 PASS; 2 skipped trong 17.31s**. Hai skip là M02 SHINE live gate hiện có và M06
live gate; cả hai được đo riêng, trong đó M06 live PASS như nêu trên.

## Mapping tiêu chí chấp nhận

| Tiêu chí/blocker | Bằng chứng M06 |
|---|---|
| `LLMProviderPort` / SHINE | Provider đi qua port và registry/factory; health + đúng một live generation đã PASS. |
| Retrieval/citation traceability | M05 run/citation chain, exact grounding và post-generation resolver revalidation. |
| `ANSWER_OR_REFUSAL` fail-closed | Outcome deterministic, no-provider branches và normalized refusal mapping đã có unit/fake/vertical evidence. |
| Structured logging | Fixed safe events/fields, normalized errors và sentinel tests. |
| Vertical tests | PostgreSQL vertical và SHINE live smoke real provider PASS. |
| Docker startup | Image rebuild, migration service, DB health, dependency check, `/live` và `/ready` PASS. |

## Oracle và residual risk

- Oracle Gate 1, Gate 2 và Gate 3 đã PASS sau các bounded remediation.
- Final Phase-4/evidence Oracle review: **PASS TO SUBMIT**.

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| Legal relevance | `NOT_MEASURED` | Lexical retrieval đơn giản không chứng minh relevance pháp lý. |
| Entailment, answer/legal correctness | `NOT_MEASURED` | Grounding traceability không chứng minh câu trả lời suy ra đúng từ evidence hoặc đúng pháp luật. |
| Legal currentness/temporal validity | `NOT_MEASURED` | Không suy luận hiệu lực, amendment, repeal hoặc thời điểm pháp lý. |
| Semantic quality | `NOT_MEASURED` | Semantic/vector retrieval không được dùng. |
| Temporal heuristic precision/recall | `NOT_MEASURED` | Guard là heuristic bounded, không phải đánh giá chất lượng rộng. |
| Broad evaluation/load | `NOT_MEASURED` | Chưa có evaluation corpus hoặc load test rộng. |
| Privileged DB mutation | `NOT_MEASURED` | Không được chứng minh bởi vertical smoke hoặc các transaction hiện có. |

## Điều kiện dừng

M06 đã submit và đang `AWAITING_APPROVAL`. Không bắt đầu M07.
