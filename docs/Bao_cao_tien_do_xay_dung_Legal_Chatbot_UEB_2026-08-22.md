# BÁO CÁO TIẾN ĐỘ XÂY DỰNG HỆ THỐNG LEGAL CHATBOT UEB

**Ngày báo cáo:** 22/08/2026  
**Phạm vi:** Hệ thống chatbot pháp lý UEB từ nguồn dữ liệu, xử lý tài liệu, truy hồi, sinh câu trả lời,
hội thoại nhiều lượt đến tích hợp Zalo.

## 1. Tóm tắt điều hành

Hệ thống đã hoàn thành phần lớn nền tảng kỹ thuật và đã hình thành được một lát cắt end-to-end:

```text
Zalo webhook → Conversation → Retrieval → Evidence/Citation → SHINE SHOP → Zalo reply
```

Các thành phần nền tảng, cơ sở dữ liệu, provider, ingestion, citation, conversation và API đã được xây
dựng và kiểm thử. Tuy nhiên, khó khăn trọng yếu hiện nay không còn nằm ở việc đọc được file PDF, mà nằm
ở khả năng **hiểu câu hỏi tự nhiên, xác định đúng văn bản và chọn đúng đoạn căn cứ**. Điều này ảnh hưởng
trực tiếp đến khả năng tương thích giữa khâu truy hồi tài liệu và khâu sinh câu trả lời hội thoại.

### Tỷ lệ hoàn thành tổng thể

**76%** — tính theo trọng số chức năng và mức độ sẵn sàng sử dụng thực tế.

Tỷ lệ này không chỉ dựa trên số lượng file hoặc module đã viết. Các năng lực quyết định chất lượng sản
phẩm như đọc hiểu câu hỏi, xác định đúng văn bản, tổng hợp đa nguồn và chất lượng trả lời được gán trọng
số cao hơn.

| Nhóm năng lực | Trọng số | Mức hoàn thành | Đóng góp |
|---|---:|---:|---:|
| Kiến trúc và các abstraction boundary | 8% | 100% | 8,0% |
| Nền tảng, cấu hình, PostgreSQL, Docker, migration | 10% | 95% | 9,5% |
| Tích hợp LLM SHINE SHOP | 8% | 95% | 7,6% |
| Nguồn dữ liệu và quản lý corpus | 12% | 85% | 10,2% |
| OCR, ingestion, chunking và indexing | 12% | 80% | 9,6% |
| Truy hồi và đọc hiểu/xác định đúng văn bản | 20% | 40% | 8,0% |
| Grounded Chat, citation và kiểm soát câu trả lời | 10% | 75% | 7,5% |
| Hội thoại nhiều lượt | 7% | 90% | 6,3% |
| Kênh Zalo Official Bot | 7% | 80% | 5,6% |
| Stress test, đánh giá và demo hardening | 6% | 65% | 3,9% |
| **Tổng** | **100%** |  | **76,2% ≈ 76%** |

## 2. Trạng thái milestone

| Milestone | Nội dung | Trạng thái |
|---|---|---|
| M00 | Integration Feasibility Spike | PASS |
| M01 | Foundation | PASS |
| M02 | Provider Abstraction | PASS |
| M03 | Source Abstraction và VBQPPL | PASS |
| M04 | Ingestion và Index | PASS |
| M05 | Retrieval và Citation | PASS |
| M06 | Grounded Chat | PASS |
| M07 | Conversation | PASS |
| M08 | Zalo Channel và các cải tiến retrieval | IN_PROGRESS |
| M09 | Demo Hardening | NOT_STARTED |

M00–M07 đã được hoàn thành và phê duyệt. M08 đang triển khai; M09 chưa bắt đầu.

## 3. Các công việc đã hoàn thành trên toàn hệ thống

### 3.1 Kiến trúc và nền tảng

- Xây dựng modular monolith bằng Python 3.12, FastAPI và SQLAlchemy async.
- Duy trì các boundary bắt buộc:
  - `LLMProviderPort`;
  - `LegalSourcePort`;
  - `ChannelPort`.
- PostgreSQL 16 và pgvector được quản lý qua Alembic migration.
- Có cấu hình runtime được kiểm tra bằng Pydantic Settings.
- Có structured logging và cơ chế không ghi credential/raw identity vào log.
- Docker Compose đã có các service DB, migration, API và tools ingestion.

### 3.2 Tích hợp LLM

- Đã triển khai adapter SHINE SHOP qua `LLMProviderPort`.
- Health check hiện tại: **healthy**.
- Model đang sử dụng: `gpt-5.6-sol`.
- Generation smoke test đã PASS.
- Đã sửa lỗi health probe `GET /models` do header `Content-Type` không phù hợp.
- Claude/Anthropic vẫn được giữ là extension point, chưa kích hoạt.

### 3.3 Nguồn dữ liệu và corpus

- Đã đọc, chuẩn hóa và import đủ **1.104 bản ghi metadata** từ:
  - `RAWDATA_QPPL`: 454;
  - `RAWDATA_VNU`: 305;
  - `RAWDATA_UEB`: 345.
- Đã xây dựng catalog ingestion có trạng thái:
  - `DISCOVERED`;
  - `FILE_PENDING`;
  - `OCR_REQUIRED`;
  - `INDEXED`;
  - `QUARANTINED`;
  - `FAILED`.
- Dữ liệu Google Drive được ghi rõ là `MANUAL_SNAPSHOT`, không giả mạo nguồn chính thức.
- Đã có cơ chế idempotent, resumable, hash file và tracking tiến độ.

### 3.4 OCR và indexing

- Đã rà 977 liên kết file trực tiếp:
  - 407 PDF có sẵn text layer;
  - 565 PDF cần OCR;
  - 5 file/link lỗi;
  - 127 bản ghi không có file trực tiếp.
- Đã OCR và index hoàn tất nhóm UEB và VNU.
- Trạng thái corpus hiện tại:

| Nguồn | Indexed | Chờ OCR | Chờ file | Quarantine | Failed/khác |
|---|---:|---:|---:|---:|---:|
| UEB | 310 | 0 | 27 | 6 | 2 |
| VNU | 271 | 0 | 6 | 26 | 2 |
| VBQPPL | 87 | 302 | 62 | 0 | 3 |
| **Tổng** | **668** | **302** | **95** | **32** | **7** |

- Đã xuất danh sách 668 văn bản indexed tại:
  `docs/evidence/demo-corpus-indexed-documents.xlsx`.

### 3.5 Retrieval và citation

- Đã triển khai PostgreSQL Full-Text Search trên chunk nội dung.
- Mỗi lần truy hồi tạo một `RetrievalRun` và các `CitationRecord` bất biến.
- Citation được resolve và kiểm tra lại trước khi trả lời.
- Đã kiểm soát:
  - source scope;
  - latest document version;
  - provenance/trust;
  - citation identity;
  - fail-closed khi evidence không hợp lệ.
- Đã triển khai lexical repair ở chế độ đánh giá opt-in nhưng giữ mặc định tắt do precision chưa đạt.
- Đã đánh giá LLM Query Planner; planner timeout 20/20 lần và đã được giữ mặc định tắt.

### 3.6 Grounded Chat và phong cách trả lời

- Bot chỉ được trả lời từ evidence đã truy hồi.
- Output LLM phải đúng JSON `{ "answer": "..." }`.
- Không chấp nhận URL, UUID, citation ID hoặc metadata nội bộ do LLM tự tạo.
- Citation do server quản lý, không do LLM tạo.
- Đã bổ sung phong cách giao tiếp:
  - bot xưng “em”;
  - gọi người dùng là “thầy/cô”;
  - dùng “Dạ” tự nhiên;
  - từ chối rõ ràng, lễ phép;
  - không làm thay đổi nguyên văn trích dẫn;
  - citation giữ nhãn trung lập “Nguồn”, “Số văn bản”, “Tiêu đề”.

### 3.7 Hội thoại nhiều lượt

- Có recent turns giới hạn.
- Có rolling summary.
- Có active topic.
- Có idempotency và concurrency control.
- Không gửi lịch sử hội thoại không giới hạn cho LLM.
- Không trộn trạng thái hội thoại giữa các người dùng.

### 3.8 Kênh Zalo

- Đã triển khai Official Zalo Bot adapter và webhook `/webhooks/zalo-bot`.
- Zalo `getMe`: PASS.
- Webhook thiếu secret bị từ chối đúng với HTTP 401.
- API hiện phản hồi:
  - `/live`: HTTP 200;
  - `/ready`: HTTP 200.
- Channel token, webhook secret và identity HMAC đã được cấu hình.
- Chưa hoàn tất đầy đủ live evidence bằng tin nhắn thật qua webhook công khai và quan sát outbound trên
  tài khoản Zalo trong milestone M08.

### 3.9 Kiểm thử và đánh giá

- Full unit regression gần nhất trước Phase 3: **575 tests PASS**.
- Focused PostgreSQL retrieval: **9 tests PASS**.
- Migration lifecycle: PASS.
- Stress runner đã chạy:
  - 60 mechanical calls mỗi báo cáo;
  - 100 API health probes;
  - SHINE và Zalo smoke checks;
  - cleanup retrieval run/citation sau test.

## 4. Khó khăn trọng yếu hiện nay

## 4.1 Khó khăn số 1 — Hệ thống đọc được văn bản nhưng chưa “hiểu và xác định đúng văn bản”

OCR đã chuyển phần lớn PDF thành text và các chunk đã được lưu trong PostgreSQL. Tuy nhiên, OCR chỉ giải
quyết việc **đọc được ký tự**, không tự giải quyết việc hiểu câu hỏi pháp lý và ánh xạ câu hỏi sang đúng
văn bản/điều khoản.

Stress test 10 câu hỏi cho thấy:

- Cơ chế raw lexical mặc định: 10/10 câu trả `NO_RESULTS`.
- Nguyên nhân: toàn bộ câu hỏi tự nhiên bị chuyển thành một truy vấn AND rất dài; nhiều từ phải cùng xuất
  hiện trong một chunk 1.200 ký tự.
- Lexical repair opt-in giảm `NO_RESULTS`, nhưng expected-document hit vẫn bằng 0 và có kết quả sai chủ
  đề; vì vậy tính năng này không được bật mặc định.
- Query Planner gọi SHINE 20 lần nhưng 20/20 lần chạm timeout 3 giây; fallback hoạt động an toàn nhưng
  không cải thiện retrieval.

Điểm nghẽn cụ thể:

1. Câu hỏi tự nhiên và ngôn ngữ trong văn bản pháp lý khác nhau.
2. PostgreSQL `simple` FTS không có semantic understanding tiếng Việt.
3. Metadata như số văn bản, tiêu đề, cơ quan ban hành chưa đủ khả năng dẫn hướng nội dung.
4. Một câu hỏi có thể cần nhiều văn bản ở ba tầng VBQPPL–VNU–UEB.
5. Ý trả lời có thể nằm ở nhiều chunk hoặc nhiều Điều/Khoản khác nhau.
6. Corpus còn thiếu `2725/QĐ-ĐHKT`; `5858/QĐ-ĐHQGHN` vẫn bị quarantine.

## 4.2 Khó khăn số 2 — Tương thích giữa retrieval và chat

Luồng chat kỹ thuật đã hoạt động, nhưng chất lượng câu trả lời phụ thuộc hoàn toàn vào evidence đầu vào.

- Nếu retrieval không tìm được evidence, bot từ chối/làm rõ và không gọi LLM.
- Nếu retrieval tìm sai tài liệu, LLM vẫn có thể tổng hợp một câu trả lời có vẻ hợp lý nhưng dựa trên căn
  cứ không đúng chủ đề.
- Output contract hiện rất nghiêm ngặt; một số lần SHINE trả output không hợp lệ dẫn đến
  `INVALID_PROVIDER_OUTPUT` dù retrieval đã có evidence.
- Query Planner không đáp ứng được timeout 3 giây nên chưa thể hỗ trợ diễn giải câu hỏi.
- Câu hỏi về “hiện nay”, “đang có hiệu lực”, “tại thời điểm X” vẫn fail-closed do chưa có dữ liệu quan hệ
  sửa đổi/thay thế/hiệu lực đầy đủ.
- Multi-source evidence sufficiency chưa được triển khai; hệ thống chưa thể khẳng định mỗi câu trả lời đã
  đủ căn cứ ở các tầng nguồn cần thiết.

Nói cách khác, hệ thống đã **tương thích về giao thức và luồng xử lý**, nhưng chưa đạt mức tương thích cao
về **ngữ nghĩa giữa câu hỏi, evidence và câu trả lời**.

## 4.3 Khó khăn tích hợp hiện tại của Phase 3

Phase 3 semantic/hybrid retrieval đã hoàn thành khâu nghiên cứu và khóa thiết kế:

- model dự kiến: `intfloat/multilingual-e5-small`, 384 chiều;
- FastEmbed/ONNX CPU;
- hybrid lexical + semantic bằng RRF;
- mặc định tắt, chỉ bật sau benchmark.

Hiện mới hoàn thành một phần score-audit migration ở mức focused tests. Semantic adapter, model prefetch,
backfill 21.345 chunk và hybrid retrieval chưa hoàn tất. Code migration head đã tiến tới `0009`, trong khi
DB vận hành hiện ở `0008`; image migration hiện tại cần được rebuild và tích hợp trước khi tiếp tục. Đây
là trạng thái phát triển dở của Phase 3, chưa ảnh hưởng API đang chạy nhưng chưa sẵn sàng để restart theo
code schema mới.

## 5. Mức độ sẵn sàng hiện tại

| Góc đánh giá | Mức sẵn sàng | Nhận định |
|---|---:|---|
| Hạ tầng/API/DB | 92% | API và DB hoạt động; cần hoàn tất tích hợp migration Phase 3 |
| Provider SHINE | 95% | Health và generation smoke PASS |
| Corpus VNU/UEB | 90% | 581 tài liệu indexed; còn một số pending/quarantine |
| Corpus VBQPPL | 35% | 87 indexed, 302 chờ OCR |
| Citation/provenance | 90% | Chuỗi evidence an toàn, manual snapshot được phân biệt |
| Hội thoại nhiều lượt | 90% | Hoạt động theo bounded state |
| Zalo kỹ thuật | 80% | Adapter/API/token sẵn sàng; thiếu live end-to-end evidence hoàn chỉnh |
| Đọc hiểu và xác định đúng văn bản | 40% | Là điểm nghẽn chính |
| Chất lượng câu trả lời tự nhiên đa nguồn | 40–50% | Chưa đạt yêu cầu demo rộng bằng 10 câu stress |

## 6. Kế hoạch công việc tiếp theo

### Ưu tiên 1 — Hoàn tất semantic/hybrid retrieval

- Hoàn thiện adapter FastEmbed cho `multilingual-e5-small`.
- Prefetch và xác minh model theo revision/hash cố định.
- Backfill semantic embedding cho khoảng 21.345 chunk.
- Chạy semantic-only và hybrid lexical+semantic bằng exact cosine.
- Chạy lại 10 câu stress và đo expected-document hit, source coverage, latency, wrong-scope.

### Ưu tiên 2 — Parent-child context và reranking

- Tìm bằng chunk nhỏ nhưng nạp thêm Điều/Khoản cha và chunk lân cận.
- Rerank một tập candidate giới hạn bằng multilingual reranker.
- Không thay đổi citation gốc.

### Ưu tiên 3 — Evidence sufficiency policy

- Xác định loại câu hỏi nào cần VBQPPL, VNU, UEB hoặc kết hợp.
- Nếu thiếu tầng nguồn bắt buộc thì làm rõ/từ chối thay vì cho LLM tự bù.
- Không coi số lượng nguồn là thứ bậc pháp lý.

### Ưu tiên 4 — Hoàn thiện M08 và M09

- Kiểm thử live Zalo end-to-end với webhook công khai.
- Đo callback latency và outbound behavior.
- Hoàn thiện demo hardening, runbook, rollback và báo cáo evidence.

## 7. Mục tiêu chất lượng cho giai đoạn tiếp theo

Trên cùng bộ 10 câu stress test:

- `NO_RESULTS` tối đa 2/10 đối với các câu có đủ văn bản indexed.
- Expected indexed-document Hit@10 tối thiểu 70%.
- Source coverage trung bình tối thiểu 70% theo khung chấm.
- Wrong-scope rate không tăng.
- Citation/provenance hợp lệ 100%.
- Retrieval p95 mục tiêu dưới 1 giây sau khi tối ưu.
- Legal correctness tiếp tục ở trạng thái `NOT_MEASURED_REQUIRES_HUMAN_REVIEW` cho đến khi chuyên gia
  pháp lý đánh giá.

## 8. Kết luận

Hệ thống đã hoàn thành khoảng **76%** khối lượng xây dựng theo trọng số chất lượng sản phẩm. Nền tảng kỹ
thuật, corpus, OCR, citation, conversation, SHINE và Zalo adapter đã đạt mức hoàn thiện cao. Phần còn lại
có tỷ trọng quan trọng nhất là **đọc hiểu câu hỏi, xác định đúng văn bản, tổng hợp đa nguồn và bảo đảm câu
trả lời phù hợp với evidence**.

Do đó, hệ thống hiện phù hợp để demo kỹ thuật có kiểm soát và thử các câu hỏi đã biết trước, nhưng chưa
nên tuyên bố sẵn sàng cho phạm vi câu hỏi pháp lý tự nhiên rộng. Trọng tâm phát triển tiếp theo cần là
semantic/hybrid retrieval, reranking và evidence sufficiency, thay vì tiếp tục mở rộng hạ tầng hoặc OCR
đơn thuần.
