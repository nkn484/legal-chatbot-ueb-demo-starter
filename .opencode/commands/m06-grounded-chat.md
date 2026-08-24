# /m06-grounded-chat

Lập kế hoạch và, chỉ sau approval rõ ràng, triển khai M06 Grounded Chat theo nguyên tắc fail-closed.

## Gate bắt buộc

1. Inspect state bằng `python scripts/demo_gate.py ...`; không sửa `.demo-run/state.json`.
2. **Từ chối start/triển khai ngay** nếu M05 chưa `PASS`. Hiện M05 là `AWAITING_APPROVAL`, M06 là
   `NOT_STARTED`; tài liệu kế hoạch có thể tồn tại nhưng không phải approval.
3. Chỉ tiếp tục sau M02/M05 `PASS` và explicit user approval cho M06.
4. Workflow luôn là inspect → plan → user approval → implement M06 hiện tại → tests/evidence → submit →
   dừng. Không tự động bắt đầu M07.

## Guardrails phạm vi

- M06 sở hữu `ANSWER_OR_REFUSAL`: service policy chọn `ANSWER`, `CLARIFICATION`, `REFUSAL`; không để
  model route outcome.
- Tái dùng `LLMProviderPort`, `RetrievalService`, `CitationResolverPort`, M05 retrieval run/citation
  provenance. Không import SHINE/Anthropic SDK trong Chat/Retrieval/Citation.
- Internal stateless service + PostgreSQL/fake-provider evidence; hoãn public `/chat`.
- Loại trừ M07 history/session/rolling summary, M08 channels/Zalo, semantic/vector retrieval, source
  fetching, migration và chat persistence.
- `NO_RESULTS` → clarification cố định/no provider call; `UNSUPPORTED_TEMPORAL_SCOPE`/current-effect/as-of
  → refusal cố định/no provider call; retrieval/resolver/grounding invalid → refusal/no provider call.
- Valid bounded evidence mới được đúng một provider call. Provider error/timeout/invalid output/post-gen
  revalidation failure → refusal không citations.

## Grounding, temporal và safety

- `ChatRequest` có `TemporalScope`; guard thuần/bounded nhận diện bảo thủ cụm Việt/Anh current-effect/as-of
  và nâng thành unsupported. Không date parser hay legal-effect inference; chất lượng heuristic là
  `NOT_MEASURED`.
- Dùng `GroundingEvidencePort`/`GroundingEvidence`; PostgreSQL adapter load tối đa 3 excerpt theo thứ tự,
  bound excerpt/tổng, và xác minh `citation → run → chunk → version → document → provenance`. Giữ
  `ResolvedCitation` content-free.
- Question/evidence là untrusted data, delimiter rõ, system policy cố định, không tools/raw HTML/history/
  credentials. Initial bounds: question 4000, 3 citations, excerpt 2000 mỗi cái, evidence 6000, prompt
  12000, output tokens 384, answer 4000 chars; phải verify, không phải performance claim.
- Provider chỉ trả strict JSON `{ "answer": ... }`; reject fences/key dư/blank/oversize/control chars/URL
  schemes/UUID/provider-authored citation token. Server sở hữu metadata/citations, re-resolve theo original
  run sau generation rồi mới append.
- Trước Phase 3, fail-fast nếu chat prompt/output bounds vượt `ProviderSettings.max_input_chars` hoặc
  `ProviderSettings.max_output_tokens`.
- Không persist/log question, hash, prompt, excerpt/chunk text hay model response/body. Provider nhận
  question + bounded evidence là disclosure cần nêu. Log chỉ fixed IDs/counts/outcome/reason/provider/model/
  sanitized request ID/duration/error code.

## Pha và evidence bắt buộc

1. Contracts/policy/config thuần: outcome table và no-provider-call branches.
2. Grounding evidence PostgreSQL adapter: exact-chain/order/bounds tests.
3. Prompt/parser/orchestration + fake provider: injection sentinels, delimiters, bounds, strict parse,
   server-only citations và post-generation revalidation.
4. PostgreSQL vertical slice: known-hit answer, no-hit clarification, temporal refusal, invalid chain,
   provider failure; logging/persistence scans; provider/retrieval/M00–M05 regressions; Docker health.

Một live SHINE generation chỉ ở phase 4, được gate rõ và sanitize; nó chỉ chứng minh path availability,
không chứng minh legal relevance/entailment/correctness, temporal validity, semantic quality, broad
evaluation hay load. Các mục đó vẫn `NOT_MEASURED`.

Chỉ validation owner (Orchestrator) quyết định validation chạy nào; báo cáo chính xác passed/failed/unknown.
Không migration: rollback M06 bằng bỏ module M06, không rollback schema/dữ liệu.
