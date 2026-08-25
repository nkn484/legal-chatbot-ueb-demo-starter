# Set B Material Sub-intent Oracle — Independent Legal Reviewer

- Version: `1.0.0`
- Review date: `2026-08-25`
- Canonical SHA-256: `4280261908FC01C57715D63B5981CF5490D975D77D1CEE9F17F5CC40314AE7D8`
- Scope: P2 analyzer evaluation only.
- Production runtime access: **FORBIDDEN**.
- Expected document IDs/titles: **NOT INCLUDED**.
- Gate: `>=90%` exact normalized parent-set agreement across at least 30 paraphrases.

## Parent gold sets

### Q01

**Question:** Sinh viên UEB muốn học vượt và học lại để cải thiện điểm thì phải đáp ứng những điều kiện nào?

**Material sub-intents:**
- `UNDERGRAD_STUDY_AHEAD_CONDITIONS`
- `UNDERGRAD_RETAKE_IMPROVEMENT_CONDITIONS`

**Reviewer rationale:** Hai yêu cầu vật chất độc lập: điều kiện học vượt và điều kiện học lại/học cải thiện.

### Q02

**Question:** UEB thu thập, sử dụng và chia sẻ dữ liệu người học thì phải tuân thủ những quy định nào?

**Material sub-intents:**
- `PERSONAL_DATA_COLLECTION_COMPLIANCE`
- `PERSONAL_DATA_USE_COMPLIANCE`
- `PERSONAL_DATA_SHARING_COMPLIANCE`
- `PERSONAL_DATA_SAFEGUARDS_RIGHTS`

**Reviewer rationale:** Ba hành vi xử lý dữ liệu được nêu trực tiếp; bảo mật/quyền-trách nhiệm là chiều tuân thủ vật chất bắt buộc.

### Q03

**Question:** Cuối năm, viên chức UEB được đánh giá và xếp loại theo những tiêu chí và quy trình nào?

**Material sub-intents:**
- `STAFF_EVALUATION_CRITERIA`
- `STAFF_EVALUATION_PROCESS`

**Reviewer rationale:** Câu hỏi có hai chiều chính: tiêu chí/căn cứ và quy trình; thẩm quyền nằm trong quy trình.

### Q04

**Question:** UEB xác định và quản lý tài liệu thuộc bí mật nhà nước trong lĩnh vực giáo dục như thế nào?

**Material sub-intents:**
- `STATE_SECRET_IDENTIFICATION_CLASSIFICATION`
- `STATE_SECRET_MANAGEMENT_PROTECTION`

**Reviewer rationale:** Tách xác định/phân loại bí mật khỏi quản lý và bảo vệ.

### Q05

**Question:** Một nhiệm vụ nghiên cứu và phát triển công nghệ chiến lược do UEB thực hiện ở cấp ĐHQGHN phải tuân thủ những quy định nào về quản lý và tài chính?

**Material sub-intents:**
- `STRATEGIC_RND_TASK_APPLICABILITY`
- `STRATEGIC_RND_TASK_MANAGEMENT`
- `STRATEGIC_RND_FINANCE`

**Reviewer rationale:** Phải xác định phạm vi áp dụng trước, sau đó tách quản lý nhiệm vụ và cơ chế tài chính.

### Q06

**Question:** UEB mua sắm một tài sản mới rồi đưa vào quản lý và kiểm kê thì thẩm quyền và quy trình thực hiện như thế nào?

**Material sub-intents:**
- `ASSET_PURCHASE_AUTHORITY`
- `ASSET_PURCHASE_PROCEDURE`
- `ASSET_POST_PURCHASE_MANAGEMENT`
- `ASSET_INVENTORY`

**Reviewer rationale:** Chuỗi nghiệp vụ bốn phần: thẩm quyền mua, thủ tục mua, quản lý sau mua, kiểm kê.

### Q07

**Question:** Nghiên cứu sinh tại UEB phải tuân thủ những quy định nào trong quá trình đào tạo tiến sĩ?

**Material sub-intents:**
- `DOCTORAL_TRAINING_DURATION_PLAN`
- `DOCTORAL_SUPERVISION_TOPIC_PROGRESS`
- `DOCTORAL_ACADEMIC_RESEARCH_REQUIREMENTS`
- `DOCTORAL_EVALUATION_DEFENSE_COMPLETION`

**Reviewer rationale:** Câu hỏi vòng đời tiến sĩ: kế hoạch/thời gian; hướng dẫn-đề tài-tiến độ; yêu cầu học thuật-nghiên cứu; đánh giá-bảo vệ-hoàn thành.

### Q08

**Question:** Học viên thạc sĩ tại UEB phải tuân thủ những quy định nào trong quá trình đào tạo?

**Material sub-intents:**
- `MASTERS_TRAINING_DURATION_PLAN`
- `MASTERS_COURSEWORK_ASSESSMENT`
- `MASTERS_THESIS_PROJECT_SUPERVISION`
- `MASTERS_COMPLETION_GRADUATION`

**Reviewer rationale:** Câu hỏi vòng đời thạc sĩ: kế hoạch/thời gian; học phần-đánh giá; luận văn/đề án-hướng dẫn; hoàn thành-tốt nghiệp.

### Q09

**Question:** Hồ sơ và văn bản điện tử tại UEB phải được lập, quản lý và lưu trữ như thế nào?

**Material sub-intents:**
- `ELECTRONIC_RECORD_CREATION`
- `ELECTRONIC_RECORD_MANAGEMENT`
- `ELECTRONIC_RECORD_ARCHIVING_RETENTION`

**Reviewer rationale:** Ba giai đoạn vật chất: tạo lập; quản lý/lập hồ sơ; lưu trữ-bảo quản.

### Q10

**Question:** Sinh viên UEB bị cảnh báo học tập hoặc xem xét buộc thôi học thì căn cứ và quy trình áp dụng như thế nào?

**Material sub-intents:**
- `ACADEMIC_WARNING_GROUNDS`
- `ACADEMIC_DISMISSAL_GROUNDS`
- `ACADEMIC_WARNING_DISMISSAL_PROCESS`

**Reviewer rationale:** Tách căn cứ cảnh báo, căn cứ buộc thôi học và quy trình/thẩm quyền.

## Frozen evaluation rule

1. Resolve each Set B item's `parent_case_id`.
2. Read that parent's gold set from the JSON oracle.
3. Normalize analyzer outputs with the frozen evaluator-only taxonomy.
4. Ignore order and deduplicate.
5. Exact normalized set match = 1; any missing, extra, or unmapped material sub-intent = 0.
6. Agreement = matched / measured.
7. Require at least 30 measured paraphrases and agreement `>=0.90`.

This Oracle measures question decomposition only. It does not establish retrieval correctness, authority, applicability/current effect, or final legal-answer correctness.