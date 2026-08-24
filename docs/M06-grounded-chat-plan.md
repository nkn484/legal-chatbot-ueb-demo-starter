# M06 — Kế hoạch Grounded Chat

## Mục tiêu và gate bắt buộc

M06 sở hữu lát cắt **Grounded Chat** và yêu cầu demo blocker `ANSWER_OR_REFUSAL` theo nguyên tắc
fail-closed. Milestone này phụ thuộc M02 và M05.

- M02 phải `PASS`.
- Hiện tại M05 là `AWAITING_APPROVAL` và M06 là `NOT_STARTED`.
- Có thể lưu tài liệu kế hoạch này, nhưng **cấm** start hoặc triển khai M06 cho đến khi M05 `PASS` và
  user đưa approval rõ ràng cho M06.
- Chỉ dùng `python scripts/demo_gate.py ...` để xem/chuyển gate; không bao giờ sửa trực tiếp
  `.demo-run/state.json`.

Workflow cho lần sau là inspect → plan → user approval → implement đúng M06 → tests/evidence → submit
→ dừng. Không được coi tài liệu này là approval triển khai.

## Phạm vi demo và ranh giới

M06 tái sử dụng `LLMProviderPort`, `RetrievalService`, `CitationResolverPort` và retrieval run/citation
provenance của M05. Service phải trả một trong `ANSWER`, `CLARIFICATION`, `REFUSAL`; không có đường trả
lời tự do khi evidence không hợp lệ/không đủ điều kiện cấu trúc.

Ngoài phạm vi: M07 history/session/rolling summary, M08 channel/Zalo, semantic/vector retrieval,
source fetching, public API endpoint, chat persistence, migration, và mọi import provider-specific.
SDK/provider-specific tiếp tục nằm sau adapter của `LLMProviderPort`; Chat/Retrieval/Citation không import
SHINE hay Anthropic client.

## Quyết định hành vi

- M06 là internal stateless service, chỉ có bằng chứng integration PostgreSQL/fake-provider; hoãn public
  endpoint `/chat`.
- Service policy quyết định `ANSWER`, `CLARIFICATION`, `REFUSAL`; model không được chọn route.
- `EVIDENCE_AVAILABLE` của M05 chỉ là eligibility cấu trúc để có thể trả lời, không chứng minh relevance,
  sufficiency hay tính đúng pháp lý. Không đặt lexical-score threshold chưa đo.
- `NO_RESULTS` trả clarification cố định, không gọi provider.
- `UNSUPPORTED_TEMPORAL_SCOPE`/current-effect/as-of trả refusal cố định, không gọi provider.
- Evidence không hợp lệ, retrieval/resolver lỗi, hoặc grounding failure trả refusal, không gọi provider.
- Evidence hợp lệ và bounded chỉ gọi provider một lần. Provider error/timeout, output không hợp lệ, hoặc
  revalidation sau generation thất bại đều trả refusal không citations.
- Server sở hữu citation và metadata; provider chỉ sinh prose. Mọi citation sẽ được resolve lại theo
  retrieval run gốc sau generation, trước khi trả kết quả.

## Temporal policy

`ChatRequest` mang `TemporalScope` explicit. Thêm một guard thuần, bảo thủ và bounded nhận diện các cụm
tiếng Việt/Anh về current-effect/as-of (ví dụ yêu cầu “đang có hiệu lực”, “hiện nay”, “as of”,
“currently effective”) rồi nâng request thành temporal scope unsupported. Guard không là date parser,
không suy luận legal effect, và không suy luận từ metadata/full text. Chất lượng false-negative/
false-positive vẫn là **NOT_MEASURED**.

## Grounding seam và mô hình đề xuất

Thêm contract nội bộ thuần `GroundingEvidencePort`/`GroundingEvidence`. Adapter documents PostgreSQL tải
tối đa 3 excerpt theo thứ tự xác định, áp bound từng excerpt và tổng evidence, rồi xác minh lại toàn bộ
chuỗi persisted chính xác:

`citation -> retrieval run -> chunk -> document version -> document -> selected provenance`.

`ResolvedCitation` vẫn content-free. Content excerpt chỉ ở `GroundingEvidence`, không được ghi vào citation
metadata/log/persistence chat. Các tệp gợi ý cho lần triển khai:

- `src/legal_chatbot/chat/{__init__,models,errors,ports,config,policy,prompt,service}.py`
- `src/legal_chatbot/documents/grounding_evidence.py`
- focused unit/integration tests tương ứng.

Không có migration hay chat persistence trong M06.

## Prompt và output safety

- System policy cố định; question và evidence được phân cách rõ, dán nhãn là untrusted data. Không tool
  access, raw HTML, history hoặc credentials trong prompt.
- Các hằng số demo ban đầu, phải được verify chứ không phải tuyên bố performance: question ≤ 4000 chars,
  tối đa 3 citations, excerpt ≤ 2000 chars mỗi cái, total evidence ≤ 6000 chars, total prompt ≤ 12000
  chars, `max_output_tokens=384`, answer ≤ 4000 chars.
- Provider phải trả strict JSON object có **chính xác** key `answer`. Từ chối markdown fence, key dư,
  blank/oversize/control chars, URL scheme, UUID, hoặc citation token do provider tạo.
- Server mới append citations đã resolve; prose provider không được điều khiển citation/metadata.
- Trước Phase 3 provider orchestration, composition root bắt buộc kiểm tra
  `ChatSettings.prompt_max_chars <= ProviderSettings.max_input_chars` và
  `ChatSettings.max_output_tokens <= ProviderSettings.max_output_tokens`; cấu hình không tương thích phải
  fail-fast trước provider call.

## Privacy và logging

Không persist hoặc log question, hash question, prompt, excerpt/chunk text, model response/body. Provider
nhất thiết nhận question và bounded evidence để generation; đây là disclosure giới hạn phải được nêu rõ
trong evidence. Structured log chỉ được có fixed IDs/counts/outcome/reason/provider/model/sanitized request
ID/duration/error code; không raw payload kể cả error path.

## Đồ thị triển khai theo pha

| Pha | Phạm vi writer đề xuất, không chồng lấn | Phụ thuộc | Oracle/gate |
| --- | --- | --- | --- |
| 1 | Writer A: `chat` contracts, config, temporal/policy thuần và unit tests | M02 `PASS`, M05 `PASS`, approval M06 | Outcome table và mọi nhánh no-provider-call pass |
| 2 | Writer B: `documents/grounding_evidence.py` và exact-chain PostgreSQL tests | Pha 1 contracts; M05 run/citation schema/service | Tối đa/bounds/order và citation→run→chunk→version→document→provenance đều pass |
| 3 | Writer C: prompt/parser/orchestration, fake provider và focused tests | Pha 1–2 | Delimiter/output safety, server-only citation, post-generation revalidation pass |
| 4 | Writer D: PostgreSQL vertical slice, một live SHINE generation được gate rõ, regressions/evidence/submit | Pha 1–3; credentials chỉ qua runtime adapter | Vertical tests, scans, regressions, Docker health; live output sanitized |

Writer chỉ sửa scope của pha mình; phase sau không bắt đầu khi Oracle của phase trước chưa pass. Live SHINE
generation không thay fake-provider tests và chỉ được chạy khi gate/approval/credential runtime hợp lệ;
không đưa credential vào Git, log hay prompt.

## Ma trận verification và evidence bắt buộc

- Unit outcome table: `ANSWER` eligible path; `NO_RESULTS` clarification; unsupported temporal, invalid
  chain/retrieval/resolver/grounding và provider failures refusal; xác nhận các nhánh bắt buộc không gọi
  provider.
- Prompt safety: sentinel prompt injection, delimiter, mọi bound, strict output parse và các dạng output
  bị từ chối.
- Citation: citation do server-only tạo và post-generation re-resolve theo original run trước return.
- PostgreSQL vertical tests: known-hit answer, no-hit clarification, temporal refusal, invalid chain và
  provider failure.
- Privacy: sentinel scan logging/persistence, gồm error path, để chứng minh không có question/hash/prompt/
  excerpt/chunk/model body.
- Hồi quy đầy đủ provider/retrieval/M00–M05 và Docker health/startup.
- Một live output được sanitize chỉ chứng minh path availability; không chứng minh legal answer quality.

Validation owner là Orchestrator; implementer chỉ chạy đúng validation được giao. Kết quả phải phân biệt
passed/failed/unknown và không nâng các tuyên bố chưa đo thành PASS.

## Tiêu chí chấp nhận và giới hạn evidence claim

- `ANSWER_OR_REFUSAL` fail-closed hoạt động: eligible evidence có thể `ANSWER`; thiếu/unsupported/invalid/
  provider failure không thành answer không-grounded.
- Provider boundary còn nguyên qua `LLMProviderPort`; service không import SDK/provider-specific client.
- Retrieval/citation traceability tồn tại qua original M05 run và exact persisted provenance; citation chỉ
  do server gắn sau revalidation.
- Structured logging tuân thủ giới hạn privacy; vertical tests và startup/Docker health được báo cáo.
- Legal relevance, entailment, legal correctness, temporal validity, semantic quality, broad evaluation và
  load đều là **NOT_MEASURED**. `EVIDENCE_AVAILABLE` và live path không được dùng để tuyên bố các thuộc
  tính này.

## Rủi ro, shortcut bị từ chối, rollback và điều kiện dừng

Rủi ro gồm evidence cấu trúc nhưng không relevant/đủ, heuristic temporal bỏ sót/nhầm, provider output phá
format, và leak qua logging/error path. Fail closed bằng clarification/refusal thay vì mở rộng claim.

Từ chối các shortcut: model route outcome, model-authored citations/metadata, bỏ post-generation
revalidation, lexical threshold chưa đo, semantic/vector retrieval, date/legal-effect inference, raw
prompt/evidence logging, public `/chat`, history/session và provider-specific import.

M06 không migration và không persistence chat; rollback là bỏ các module service/adapter M06 đã thêm mà
không cần rollback schema hay dữ liệu. Sau khi evidence của M06 được submit, dừng và chờ user approval;
không tự động bắt đầu M07.
