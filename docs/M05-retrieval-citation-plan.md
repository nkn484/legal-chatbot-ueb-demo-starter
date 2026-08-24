# M05 — Kế hoạch Retrieval + Citation

## Mục tiêu

Triển khai lát cắt **Retrieval + Citation** có thể truy vết cho corpus đã ingest. M05 chỉ tạo
evidence retrieval và citation do server/service quản lý; không triển khai M06/Chat/LLM/provider/
channel/conversation hay `ANSWER_OR_REFUSAL`.

## Sự thật hiện tại đã đo

- M04: `PASS`; migration hiện tại là `0002`, có document/version/provenance/chunk/embedding bất biến.
- M05: `IN_PROGRESS` ở pha lập kế hoạch; chưa có mã, migration hoặc test M05.
- `local-hash-v1` là `demo_non_semantic`, `semantic_ready=false`. Chất lượng semantic và retrieval
  chưa được đo.
- PostgreSQL simple FTS cho tiếng Việt, bao gồm hành vi có dấu/không dấu, là `NOT_MEASURED`.

## Tệp tối thiểu (cho lần triển khai sau)

- `alembic/versions/0003_*.py`: schema FTS, retrieval run và citation.
- `src/legal_chatbot/documents/orm.py`, `repository.py`: model và truy vấn/persistence retrieval-citation.
- `src/legal_chatbot/retrieval/` (mới): model, service lexical, resolver citation và hàm RRF thuần.
- Các test ORM/repository, unit retrieval/resolver và integration PostgreSQL/migration tương ứng.

Không thêm port/config semantic, provider, chat hay API channel trong M05.

## Giao diện và model

- `RetrievalRequest`: query chỉ dùng trong bộ nhớ, scope `LATEST_INGESTED`, và các giới hạn query/top-k.
  Service từ chối input vượt giới hạn; không lưu raw query hoặc SHA-256 digest của query.
- `RetrievalResult`: `retrieval_run_id` opaque UUID, candidates/citation IDs, counts và quyết định
  evidence. Không phải kết luận đủ bằng chứng cho câu trả lời pháp lý.
- Enum quyết định retrieval: `EVIDENCE_AVAILABLE`, `NO_RESULTS`,
  `UNSUPPORTED_TEMPORAL_SCOPE`, `INVALID_EVIDENCE_CHAIN` (hoặc enum chính xác tương đương).
- RRF là hàm nhỏ, thuần và chỉ nhận danh sách xếp hạng giả trong unit test; chưa tạo semantic port,
  config, query hay đóng góp RRF trên đường chạy live.

## Persistence/migration

- Thêm Alembic `0003` với cột generated stored trên `document_chunks`:
  `search_vector = to_tsvector('pg_catalog.simple', content_text)`, và GIN index cho cột này.
  Cập nhật ORM cùng migration/schema tests trong lần triển khai sau.
- Thêm `retrieval_runs`: UUID opaque, strategy/version, scope, giới hạn đã áp dụng, counts,
  evidence decision/reason và timestamps. Không lưu raw query, query digest SHA-256, hoặc chunk text.
- Thêm `citation_records`: run ID, đúng chunk ID, selected provenance record ID, rank và lexical score.
  Khi một version có nhiều provenance, chọn theo quy tắc xác định và persist ID đã chọn.
- Ghi một run cùng các citation trong **một transaction**. FK citation tới run/chunk/provenance phải
  `RESTRICT`/`NO ACTION`, không cascade; không có mutation API. Điều này bảo vệ evidence khỏi
  cascade delete qua chuỗi document/version/chunk/provenance. Integration test phải xác minh hành vi.

## Hành vi retrieval

- Đường live chỉ lexical PostgreSQL FTS. Tuyệt đối không sinh vector query, vector SQL, semantic call,
  hoặc RRF contribution live; `pgvector` được cài đặt nhưng semantic chưa khả dụng.
- Scope ban đầu là `LATEST_INGESTED`: với mỗi stable document identity, chỉ version có
  `version_number` lớn nhất tại thời điểm chạy. Đây là snapshot ingest mới nhất, **không** là văn bản
  đang hiệu lực/current/legal effective. Áp scope trước rank và limit.
- Thứ tự xác định: lexical rank giảm dần, sau đó stable ID tăng dần. Query length và top-k luôn bị
  bound; không có query/limit không giới hạn.
- Không suy diễn sửa đổi, thay thế, bãi bỏ, hiệu lực hay legal effect từ full text, `effective_date`,
  `legal_status` hoặc metadata. Yêu cầu temporal/as-of/current-effect trả
  `UNSUPPORTED_TEMPORAL_SCOPE`, không phát citation gây hiểu nhầm. Extraction/verification legal effect
  thuộc phạm vi tương lai.

## Hành vi citation

- Server/service, không phải LLM, tạo metadata citation và resolver đi đúng chuỗi:
  `citation -> chunk -> document_version -> document -> selected_provenance`.
- Resolver xác minh selected provenance thuộc chính document version của chunk, citation thuộc run
  được yêu cầu, và chain/scope hợp lệ. Từ chối citation dangling/malformed, foreign hoặc mismatched run,
  provenance-version mismatch, hay explicit retrieval-scope violation.
- Citation lịch sử bất biến vẫn resolve sau khi ingest version mới; không gắn nhãn stale chỉ vì không
  còn là `LATEST_INGESTED`. Việc kiểm tra latest scope chỉ áp dụng khi tạo evidence cho retrieval run,
  không làm hỏng chain lịch sử.

## Quyết định evidence

`EVIDENCE_AVAILABLE` chỉ nói retrieval có candidate evidence/citation chain hợp lệ; lexical hit không
chứng minh đủ bằng chứng hoặc đúng câu trả lời. Không đặt ngưỡng lexical score chưa đo. M06 tiêu thụ
quyết định này để thực hiện answer/clarify/refuse và sở hữu trách nhiệm `ANSWER_OR_REFUSAL`.

## Đường test/bằng chứng

Lần triển khai sau phải đo và báo cáo:

- upgrade/downgrade `0003`, generated vector và GIN index;
- lexical known-hit/no-hit; smoke tiếng Việt có dấu/không dấu được gắn là **measured behavior**, không
  phải proof về relevance;
- `LATEST_INGESTED` loại chunk version cũ trước top-k; bounds query/top-k và tie xác định;
- request temporal/current-effective trả unsupported; không có semantic SQL/call; RRF chỉ fake lists;
- citation cũ resolve sau version mới; resolver trả exact chain và từ chối dangling/foreign/provenance
  mismatch;
- transaction run+citation atomic, không có partial evidence khi ingest đồng thời;
- DB và log, kể cả error path (logger hiện có thể emit `getMessage`), không chứa raw query/chunk text;
- full suite, migration lifecycle, hồi quy M00; sau đó viết measured evidence report và dừng.

## Giả định bên ngoài

- PostgreSQL 16; `pgvector` đã cài nhưng semantic không khả dụng.
- Chỉ VBQPPL là nguồn demo active; VNU/UEB chưa active.
- Priority source registry là thứ tự rollout, không phải legal authority.

## Rủi ro/fallback

- Simple FTS có giới hạn tiếng Việt; corpus hiện chỉ có một nguồn; provenance có thể đa trị; FK cascade
  cần được bảo toàn; và ingestion đồng thời có thể tạo race.
- Nếu scope, chain, transaction hoặc temporal/legal-effect semantics không xác minh được, fail closed:
  trả no/unsupported/invalid evidence thay vì mở rộng corpus hoặc suy diễn/khẳng định pháp lý.

## Ngoài phạm vi

Semantic retrieval thật, vector ranking, live RRF, relevance tuning, legal-effect extraction/
verification, temporal-effective retrieval, Chat/M06, LLM, provider, channel và conversation.

## Tiêu chí chấp nhận

- Mỗi candidate evidence có retrieval run opaque và mỗi citation truy vết xác định tới exact
  chunk/version/document/provenance, được persist atomically và được bảo vệ khỏi cascade deletion.
- Live retrieval lexical, bounded, deterministic, đúng `LATEST_INGESTED`, không semantic/vector và
  không rò raw query/chunk text vào DB/log kể cả lỗi.
- Temporal/legal-effect request fail closed; citation lịch sử hợp lệ vẫn resolve sau ingest mới.
- Bằng chứng test/migration đầy đủ được báo cáo. Ranh giới trách nhiệm vẫn giữ
  `ANSWER_OR_REFUSAL` cho M06, không cho M05 khẳng định legal answer sufficiency.

## Điều kiện dừng

Sau lần triển khai M05, chỉ chạy test/bằng chứng được yêu cầu, báo cáo measured evidence và chờ user
approval. Không tự động bắt đầu M06.
