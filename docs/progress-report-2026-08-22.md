# BÁO CÁO TIẾN ĐỘ XÂY DỰNG CHATBOT PHÁP LUẬT UEB

**Ngày báo cáo:** 22/08/2026  
**Phạm vi:** Toàn bộ hệ thống chatbot pháp luật UEB  
**Nguồn đánh giá:** mã nguồn, hợp đồng milestone, trạng thái demo và các báo cáo kiểm chứng trong repository.

## 1. Tóm tắt điều hành

### Tiến độ chính thức: **80%**

Hệ thống có 10 milestone từ M00 đến M09. Hiện **8/10 milestone đã hoàn thành và được phê duyệt**, M08 đang thực hiện và M09 chưa bắt đầu.

> Công thức: `8 milestone PASS / 10 milestone = 80%`.

Nếu tính thêm phần mã nguồn đã triển khai của M08, mức sẵn sàng kỹ thuật nội bộ có thể cao hơn 80%. Tuy nhiên, báo cáo sử dụng **80%** làm số liệu chính thức để không tính trước phần chưa có bằng chứng nghiệm thu live.

### Trạng thái tổng quan

- Các lớp nền tảng, tích hợp mô hình ngôn ngữ, nguồn pháp luật, nhập liệu, tìm kiếm, trích dẫn, trả lời có căn cứ và hội thoại nhiều lượt đã hoàn thành.
- Kênh Zalo Official Bot đã có adapter, webhook, lưu trạng thái và kiểm thử nội bộ, nhưng chưa hoàn tất kiểm chứng end-to-end trên môi trường Zalo thật.
- Khó khăn lớn nhất hiện nay nằm ở:
  1. **Đọc hiểu và truy xuất văn bản:** dữ liệu pháp luật trong corpus chưa đủ, tìm kiếm runtime còn thiên về từ khóa, semantic retrieval chưa được sử dụng đầy đủ.
  2. **Tương thích chat/Zalo:** chưa có bằng chứng live hoàn chỉnh cho luồng nhận tin nhắn thật → xử lý → trả lời có trích dẫn.

## 2. Tiến độ theo milestone

| Milestone | Hạng mục | Trạng thái | Tỷ trọng nghiệm thu |
|---|---|---:|---:|
| M00 | Kiểm chứng khả năng tích hợp SHINE, VBQPPL và Zalo | Hoàn thành | 10% |
| M01 | Nền tảng hệ thống | Hoàn thành | 10% |
| M02 | Lớp trừu tượng nhà cung cấp LLM | Hoàn thành | 10% |
| M03 | Lớp nguồn pháp luật và tích hợp VBQPPL | Hoàn thành | 10% |
| M04 | Nhập, chuẩn hóa và lập chỉ mục văn bản | Hoàn thành | 10% |
| M05 | Truy xuất và trích dẫn | Hoàn thành | 10% |
| M06 | Chat có căn cứ pháp lý | Hoàn thành | 10% |
| M07 | Hội thoại nhiều lượt | Hoàn thành | 10% |
| M08 | Kênh Zalo | Đang thực hiện | 0% nghiệm thu |
| M09 | Hoàn thiện và gia cố bản demo | Chưa bắt đầu | 0% |
|  | **Tổng cộng đã nghiệm thu** |  | **80%** |

M08 đã có khối lượng triển khai đáng kể nhưng chưa được tính vào tỷ lệ chính thức vì chưa submit/approve và chưa có số đo live hoàn chỉnh.

## 3. Các công việc đã hoàn thành trên toàn hệ thống

### 3.1. Kiến trúc và nền tảng

- Xây dựng hệ thống theo kiến trúc modular monolith.
- Thiết lập đầy đủ ba ranh giới bắt buộc: `LLMProviderPort`, `LegalSourcePort`, `ChannelPort`.
- Xây dựng FastAPI application, health check, readiness check và composition root.
- Thiết lập cấu hình runtime có kiểm tra, structured logging và nguyên tắc không đưa secret vào domain.
- Xây dựng Dockerfile và Docker Compose cho PostgreSQL, pgvector, migration, API và công cụ ingestion.

### 3.2. Tích hợp mô hình ngôn ngữ

- Hoàn thành adapter SHINE SHOP với HTTP bất đồng bộ, timeout, giới hạn dữ liệu và ánh xạ lỗi rõ ràng.
- Giữ logic Chat/Retrieval/Citation độc lập với SDK hoặc client riêng của nhà cung cấp.
- Có registry để mở rộng thêm nhà cung cấp trong tương lai.
- Luồng chat được thiết kế fail-closed: khi không đủ bằng chứng, hệ thống yêu cầu làm rõ hoặc từ chối trả lời thay vì tự suy diễn.

### 3.3. Nguồn pháp luật

- Hoàn thành registry nguồn theo thứ tự VBQPPL, VNU và UEB.
- Hoàn thành tích hợp VBQPPL theo cơ chế chỉ đọc và allowlist rõ ràng.
- Có adapter SOAP và REST fallback với các giới hạn an toàn về URL, XML, timeout và quyền truy cập.
- VNU và UEB đã có vị trí mở rộng trong registry nhưng connector live được chủ động để sau demo.
- Dữ liệu tải thủ công được đánh dấu là bản chụp thủ công, không giả mạo nguồn chính thức.

### 3.4. Nhập liệu, chuẩn hóa và lập chỉ mục

- Hoàn thành pipeline normalize, chunk, embedding và lưu phiên bản văn bản.
- Lưu metadata nguồn, provenance, version và các chunk phục vụ tìm kiếm.
- Có cơ chế chạy pipeline corpus demo và tiếp tục khi tác vụ bị gián đoạn.
- PostgreSQL đã có pgvector và chỉ mục phục vụ tìm kiếm.

### 3.5. Truy xuất và trích dẫn

- Hoàn thành tìm kiếm lexical trên PostgreSQL.
- Có cơ chế mở rộng truy vấn, hợp nhất kết quả và ưu tiên phiên bản văn bản mới nhất.
- Lưu vết từng lượt retrieval và citation để có thể truy nguyên câu trả lời về bằng chứng.
- Citation resolver kiểm tra quan hệ giữa nguồn, phiên bản, chunk và độ tin cậy trước khi đưa vào câu trả lời.
- Không cho phép mô hình tự tạo metadata nguồn pháp luật hoặc trích dẫn không tồn tại.

### 3.6. Chat có căn cứ pháp lý

- Hoàn thành luồng câu hỏi → truy xuất → tạo evidence → gọi SHINE → kiểm tra đầu ra → xác thực lại citation.
- Hỗ trợ trả lời, yêu cầu làm rõ hoặc từ chối theo chất lượng evidence.
- Giới hạn phần trích dẫn đưa vào prompt và coi nội dung bên ngoài là dữ liệu không đáng tin cậy.

### 3.7. Hội thoại nhiều lượt

- Hoàn thành lưu trạng thái hội thoại trên PostgreSQL.
- Hỗ trợ bounded recent turns, rolling summary, chủ đề pháp lý hiện tại, document ID và citation ID gần đây.
- Có idempotency, lease/concurrency control, replay và compaction để tránh gửi lại lịch sử không giới hạn.

### 3.8. Kênh chat Zalo

- Đã xây dựng adapter cho Official Zalo Bot API.
- Đã xây dựng webhook có kiểm tra secret, giới hạn kích thước body và chuẩn hóa sự kiện.
- Raw user/chat/message ID được giữ trong channel adapter và chuyển thành định danh HMAC trước khi vào domain.
- Có lưu binding, trạng thái gửi và chống xử lý lặp lại.
- Có kiểm thử nội bộ cho duplicate webhook và quy tắc chỉ gửi một lần qua mock transport.
- Chưa có bằng chứng live đã điền cho Official Bot Manager, inbound thật và grounded reply thật.

### 3.9. Dữ liệu, migration và kiểm thử

- Có chuỗi migration từ `0001` đến `0009`, bao gồm pgvector, document/index, retrieval/citation, conversation, channel và semantic score.
- Có test unit và integration cho các vertical slice chính.
- Bằng chứng lịch sử gần nhất ghi nhận **570 test passed, 6 skipped**; số liệu này chưa được chạy lại tại thời điểm lập báo cáo.
- Có các script kiểm tra starter pack, migration lifecycle, Compose và stress test.
- Chưa có CI workflow và chưa có báo cáo test coverage chính thức.

## 4. Khó khăn hiện tại

### 4.1. Hệ thống đọc hiểu và truy xuất văn bản

Đây là khó khăn kỹ thuật quan trọng nhất hiện nay.

**Hiện trạng:**

- Runtime đang sử dụng chủ yếu tìm kiếm lexical/FTS; dữ liệu vector đã có nhưng semantic retrieval chưa được đưa vào luồng tìm kiếm chính.
- Bộ corpus được đo chỉ có một văn bản VBQPPL chính thức phù hợp về provenance và một fixture kiểm thử, chưa bao phủ các lĩnh vực pháp luật đại học.
- Kết quả đánh giá 20 câu hỏi pháp luật đại học cho thấy **0/20 câu có kết quả lexical phù hợp**.
- Cả 20 câu đều được phân loại là chưa có văn bản liên quan trong corpus; nhiều câu còn cần tổng hợp nhiều văn bản và xử lý hiệu lực theo thời gian.
- Query planner mới có bằng chứng trên fixture có kiểm soát; chưa có số đo với LLM thật trên corpus pháp luật đầy đủ.
- Việc mở rộng dữ liệu từ nguồn chính thức còn gặp trở ngại bên ngoài, trong đó có lỗi nhận dạng hostname/chứng thư TLS ở kênh SOAP.

**Đánh giá nguyên nhân:**

Vấn đề không chỉ nằm ở khả năng hiểu ngôn ngữ tự nhiên của mô hình. Nút thắt chính là sự kết hợp của ba yếu tố:

1. Corpus pháp luật chưa đủ độ phủ.
2. Tìm kiếm semantic và xử lý truy vấn chưa hoạt động đầy đủ trong runtime.
3. Chưa có bộ gold benchmark để đo relevance, entailment, legal correctness và hiệu lực văn bản.

**Ảnh hưởng:**

- Hệ thống có thể không tìm thấy bằng chứng dù câu hỏi hợp lệ.
- Chat phải trả lời theo hướng yêu cầu làm rõ hoặc từ chối, làm giảm trải nghiệm demo.
- Chưa thể khẳng định chất lượng đọc hiểu pháp lý chỉ dựa trên số lượng test kỹ thuật.

### 4.2. Tương thích chat và Zalo Official Bot

**Hiện trạng:**

- Phần code của adapter, webhook, lưu trạng thái và chống gửi lặp đã được xây dựng.
- Kênh Zalo đang tắt mặc định; overlay M08 mới chỉ bật cờ cấu hình.
- Báo cáo live M08 hiện vẫn là template, chưa có số liệu về đăng ký webhook, inbound message, grounded reply và callback duration.
- Kiểm thử hiện tại chủ yếu dùng mock HTTP transport, chưa thay thế được kiểm chứng với Bot Manager thật.
- Một số tài liệu cũ còn đề cập Zalo Personal Bridge, trong khi mục tiêu hiện tại là Official Zalo Bot Manager; cần đồng bộ để tránh triển khai sai kênh.

**Ảnh hưởng:**

- Chưa thể xác nhận tương thích hoàn chỉnh với payload, callback, retry và giới hạn thực tế của Zalo.
- Chưa chứng minh được luồng end-to-end: người dùng gửi tin → webhook nhận → hội thoại/retrieval/chat xử lý → Zalo nhận câu trả lời có citation.
- M08 chưa đủ điều kiện nghiệm thu và M09 chưa thể bắt đầu theo quan hệ phụ thuộc milestone.

## 5. Các rủi ro cần theo dõi

| Rủi ro | Mức độ | Biện pháp kiểm soát hiện có |
|---|---|---|
| Thiếu văn bản pháp luật đúng phạm vi | Cao | Fail-closed, provenance, allowlist nguồn |
| Tìm kiếm từ khóa không hiểu đủ ý câu hỏi | Cao | Query expansion/planner đã có nền tảng; semantic retrieval cần hoàn thiện |
| Trả lời thiếu hoặc sai căn cứ | Cao | Citation resolver và tái xác thực citation |
| Zalo live khác với mock test | Cao | Webhook boundary và adapter tách biệt; còn cần live acceptance |
| Tài liệu Zalo không thống nhất | Trung bình | Chốt Official Bot Manager làm target duy nhất và cập nhật tài liệu |
| Chưa có CI/test coverage | Trung bình | Có test suite và script cục bộ; cần bổ sung trong giai đoạn hardening |

## 6. Ưu tiên công việc tiếp theo

1. Mở rộng allowlist và ingest đủ corpus pháp luật chính thức cho 20 câu hỏi kiểm thử.
2. Đo lại raw retrieval trên corpus mới, sau đó mới đánh giá query planner và semantic retrieval.
3. Xây dựng gold benchmark cho document/chunk/scope, relevance và legal correctness.
4. Thực hiện live acceptance với Official Zalo Bot Manager bằng bằng chứng đã loại bỏ dữ liệu nhạy cảm.
5. Đồng bộ toàn bộ tài liệu từ Zalo Personal Bridge sang Official Zalo Bot Manager.
6. Hoàn tất M08, sau đó triển khai M09 gồm full regression, CI/coverage cần thiết, runbook end-to-end và kiểm tra demo cuối.

## 7. Kết luận

Hệ thống đã hoàn thành phần lớn lõi kỹ thuật của chatbot pháp luật: kiến trúc, tích hợp LLM, nguồn dữ liệu, ingestion, retrieval, citation, grounded chat và hội thoại nhiều lượt. **Tiến độ nghiệm thu hiện tại là 80%**.

Phần việc còn lại tập trung vào chất lượng thực tế thay vì chỉ bổ sung cấu trúc: tăng độ phủ văn bản để hệ thống đọc hiểu và tìm đúng căn cứ, kiểm chứng semantic/planner bằng dữ liệu thật, hoàn tất tương thích Zalo Official Bot trên môi trường live và gia cố bản demo.

---

### Tài liệu căn cứ chính

- `contracts/milestones.json`
- `.demo-run/state.json` — chỉ đọc, trạng thái cập nhật gần nhất ngày 20/08/2026
- `contracts/demo-profile.json`
- `docs/evidence/M08.1-20-question-retrieval-evaluation.md`
- `docs/evidence/M08-zalo-bot-live-template.md`
- Các báo cáo M05, M06, M07 và M08 trong `docs/evidence/`
