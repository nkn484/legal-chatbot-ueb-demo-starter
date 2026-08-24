# CODING AGENT PROMPT PACK — LEGAL CHATBOT UEB
## Mục tiêu
Tìm đúng nguyên nhân và sửa các failure được phát hiện khi đối chiếu toàn văn 10 câu stress test.

**Ground truth đánh giá:** `Ket_qua_cham_toan_van_Stress_test_Legal_Chatbot_UEB_2026-08-22.xlsx`

### Baseline đã xác minh
- Provider-output whitespace fix: PASS.
- 10/10 câu hiện có thể đi tới `ANSWER_GROUNDED`.
- Nhưng đối chiếu toàn văn chỉ 4/10 câu đạt ngưỡng >= 7,0.
- Điểm trung bình theo 10 điểm từng câu: 5,49/10.
- Failure trọng tâm: document selection, query decomposition, legal hierarchy, version/status, false insufficient evidence.
- Không được hard-code 10 câu, số hiệu văn bản hoặc câu trả lời benchmark vào production logic.

---

# PROMPT 01 — ROOT CAUSE TRACE: WHY GROUNDED IS NOT LEGALLY COMPLETE

Bạn là Tech Lead/Principal Engineer chịu trách nhiệm diagnostic cho Legal Chatbot UEB.

## Input bắt buộc
1. Đọc toàn bộ source-code hiện tại.
2. Đọc file `Ket_qua_cham_toan_van_Stress_test_Legal_Chatbot_UEB_2026-08-22.xlsx`.
3. Dùng 10 câu trong sheet `Kết quả 10 câu` làm evaluation set.
4. Dùng sheet `Chấm điểm` làm ground truth về failure, KHÔNG dùng để hard-code retrieval.

## Mục tiêu
Giải thích bằng runtime evidence tại sao hệ thống có thể báo `ANSWER_GROUNDED` nhưng vẫn:
- lấy văn bản cũ/thay thế;
- bỏ văn bản điều chỉnh trực tiếp;
- lấy văn bản gần nghĩa nhưng sai đối tượng;
- không đi đủ VBQPPL → VNU → UEB;
- kết luận `insufficient evidence` khi đúng văn bản đang tồn tại trong corpus.

## Bắt buộc trace mỗi câu
Capture:
- raw_question
- normalized_question
- intent
- entities / organization
- legal topics
- sub-intents
- query plan
- expanded queries
- source scope
- metadata filters
- version/effectivity filters
- lexical candidates top 50
- semantic candidates top 50 (nếu feature tồn tại)
- merged candidates
- pre-rerank rank
- post-rerank rank
- evidence selected
- evidence rejected + reason
- corpus-insight decision
- final answer state

Nếu field không tồn tại: ghi `NOT_IMPLEMENTED`.

## Phân tích 5 class failure bắt buộc
1. `DIRECT_DOCUMENT_MISS`
2. `LEGAL_HIERARCHY_MISS`
3. `VERSION_STATUS_FAILURE`
4. `SUB_INTENT_DECOMPOSITION_FAILURE`
5. `FALSE_INSUFFICIENT_EVIDENCE`

## Control tests
Với từng câu chạy:
A. Natural question  
B. Concept-expanded query  
C. Source-aware legal query, nhưng KHÔNG dùng số hiệu văn bản  
D. Exact document number — CONTROL ONLY

Phải xác định expected document mất ở:
- pre-filter;
- lexical/semantic candidate generation;
- top-k cutoff;
- reranker;
- version/status resolver;
- evidence gate;
- answer planner.

## Output
Tạo:
`docs/diagnostics/stress-test-fulltext-root-cause.md`

Bảng bắt buộc:
| Q | Expected direct docs | Found top50? | Found final? | Wrong docs selected | Failure stage | Root cause | Confidence |

## Definition of Done
Không đề xuất sửa cho tới khi:
- giải thích được Q5, Q6, Q8 vì sao hard retrieval miss;
- giải thích được Q1/Q10 vì sao hierarchy/version không resolve;
- giải thích được Q2 vì sao nói thiếu “thu thập” dù evidence có trong corpus;
- chỉ ra code path/file/function cụ thể cho mỗi root cause.

---

# PROMPT 02 — IMPLEMENT RETRIEVAL REPAIR WITHOUT BENCHMARK HARDCODING

Chỉ bắt đầu prompt này sau khi Prompt 01 hoàn tất và root cause đã được chứng minh.

## Mục tiêu
Sửa retrieval để tăng **direct-document recall + legal source coverage**, không tối ưu bằng cách ghi nhớ 10 câu.

## Nguyên tắc cứng
- KHÔNG hard-code Q01–Q10.
- KHÔNG hard-code các số hiệu expected document vào query logic.
- KHÔNG special-case chuỗi “UEB”, “học vượt”, “thạc sĩ” chỉ để pass benchmark.
- Mọi thay đổi phải tổng quát cho câu hỏi pháp lý mới.
- Provider-output validator fix hiện tại phải được giữ nguyên.
- Không nới schema, citation security hoặc evidence-token security.

## Corrective architecture tối thiểu
### A. Query decomposition
Một câu có nhiều hành động pháp lý phải tách thành sub-intent.

Ví dụ generic:
`mua sắm → quản lý → kiểm kê`
phải tạo ít nhất 3 retrieval intents.

### B. Legal vocabulary expansion
Sinh query biến thể từ:
- hành vi người dùng;
- thuật ngữ pháp lý;
- loại văn bản/quy chế;
- đối tượng;
- cấp ban hành.

Không tạo document number.

### C. Hierarchical source expansion
Nếu subject thuộc UEB:
- không filter chỉ UEB;
- tìm đồng thời hoặc theo tầng: VBQPPL → VNU → UEB;
- ưu tiên UEB cho quy tắc cụ thể nhưng vẫn giữ căn cứ cấp trên.

### D. Direct-title / subject match
Candidate generation cần có arm lexical/title metadata mạnh cho các văn bản có tiêu đề trực tiếp trùng legal topic.
Semantic similarity không được là arm duy nhất.

### E. Candidate merge
Merge multi-query/multi-source:
- dedupe theo legal_document_id/version;
- giữ provenance query nào tìm ra candidate;
- không để 1 sub-query chiếm toàn top-k.

## Evaluation
So sánh:
- default baseline;
- repaired retrieval evaluation mode.

Metrics:
- expected direct-document recall@8/@20/@50;
- source coverage;
- wrong-document rate;
- false insufficient evidence;
- per-question regression.

## Acceptance
Không được merge nếu chỉ cải thiện 10 câu nhưng làm giảm control set.
Phải bổ sung ít nhất 20 câu paraphrase/control không chứa document number.

---

# PROMPT 03 — LEGAL HIERARCHY, VERSION/STATUS, AND EVIDENCE COMPLETENESS REPAIR

## Mục tiêu
Ngăn hệ thống:
1. dùng văn bản hết hiệu lực khi có bản hiện hành;
2. bỏ văn bản sửa đổi/bổ sung;
3. dùng quy định cấp trên thay cho quy định UEB cụ thể;
4. nói “chưa có bằng chứng” khi corpus thực tế có văn bản trực tiếp.

## A. Version/effectivity resolver
Đọc data model/migrations để xác định:
- legal_document_id
- document_version_id
- status/effective_status
- replaces/supersedes/amends nếu có.

Tạo rule:
- candidate superseded không được thắng candidate hiện hành cùng subject nếu không có lý do pháp lý rõ.
- base regulation phải được liên kết với amendment đang hiệu lực.
- log `version_resolution_reason`.

Không suy đoán quan hệ sửa đổi nếu database không có evidence.

## B. Legal hierarchy resolver
Cho mỗi legal issue, đánh giá:
- general rule;
- VNU rule;
- UEB implementing/specific rule.

Answer planner phải phân biệt:
`quy định khung` vs `quy định áp dụng/cụ thể tại UEB`.

Không áp dụng máy móc “văn bản cấp thấp thắng”; phải dựa phạm vi, đối tượng, hiệu lực và quan hệ cụ thể hóa.

## C. Evidence completeness gate
Trước khi trả `INSUFFICIENT_EVIDENCE`:
1. kiểm tra direct-title/topic candidate;
2. chạy repair retrieval với missing sub-intent;
3. mở rộng source tier còn thiếu;
4. kiểm tra current/superseding version.

Chỉ sau đó mới được kết luận evidence thiếu.

Log:
- missing_issue
- repair_query
- repair_candidates
- why_still_insufficient

## D. Grounded ≠ complete
Bổ sung metric riêng:
- `grounded_answer = yes/no`
- `direct_authority_coverage`
- `source_tier_coverage`
- `sub_intent_coverage`
- `version_resolution_ok`

Không đổi nghĩa `ANSWER_GROUNDED` nếu điều đó phá compatibility; có thể bổ sung quality telemetry/status riêng.

## Tests
Phải có regression test cho:
- superseded vs current;
- base + amendment;
- general VNU rule + specific UEB rule;
- evidence exists but initial top-k misses;
- multiple sub-intents;
- unrelated high-semantic candidate.

---

# PROMPT 04 — FINAL REGRESSION, ABLATION, AND RELEASE GATE

## Mục tiêu
Chứng minh fix thực sự cải thiện Legal QA chứ không chỉ benchmark fitting.

## Test sets
### Set A — 10 câu stress test gốc
Dùng đúng file Excel ground truth.

### Set B — Paraphrase set
Ít nhất 3 paraphrase/câu → >=30 câu.

### Set C — Negative/control set
Ít nhất 20 câu:
- câu chỉ cần 1 nguồn;
- câu không có evidence;
- câu có văn bản hết hiệu lực và văn bản thay thế;
- câu chứa UEB nhưng không cần VNU/VBQPPL;
- câu không liên quan UEB.

## Ablation
So sánh:
1. Current default
2. Retrieval repair only
3. + hierarchy/version
4. + completeness repair
5. Full evaluated configuration

## Metrics bắt buộc
- ANSWER_GROUNDED rate
- expected/direct document recall@8,20,50
- source-tier coverage
- sub-intent coverage
- current-version selection rate
- false insufficient evidence rate
- irrelevant citation rate
- answer factual/legal score
- latency
- DB/query cost

## Release gate đề xuất
PASS chỉ khi:
- 10/10 không có hard retrieval miss;
- >=8/10 đạt >=7 điểm khi chấm toàn văn;
- không có câu nào dùng văn bản hết hiệu lực làm căn cứ chính khi bản hiện hành có trong corpus;
- false insufficient evidence = 0 trên Set A;
- không regression đáng kể trên Set B/C;
- không hard-code document IDs/query strings của benchmark.

## Output
Tạo:
- `docs/evals/stress-test-post-fix.md`
- machine-readable JSON/CSV per-question trace
- bảng before/after
- danh sách remaining failures

## Final response format
RELEASE EVALUATION
- Before: 4/10 quality PASS; avg 5.49/10
- After: x/10 quality PASS; avg x/10
- Direct-doc recall: before → after
- False insufficient: before → after
- Version/hierarchy failures: before → after
- Regressions: ...
- Recommendation: RELEASE / HOLD
