# M01 — Foundation: Báo cáo bằng chứng

- `evidence_finalized_at`: `2026-08-19T02:41:11.609778+00:00`
- Khuyến nghị implementation M01: **PASS**
- Trạng thái milestone hiện tại: **IN_PROGRESS**, chưa submit.
- M00: **PASS**; M02: **NOT_STARTED**.
- Không chỉnh sửa trực tiếp tệp state.

## Trạng thái

M01 đã được xác minh end-to-end trên môi trường cô lập và Docker. Stack hiện vẫn được giữ chạy để phục vụ kiểm chứng demo. Kết quả PASS không thay đổi trạng thái milestone: M01 vẫn là `IN_PROGRESS` và chưa được submit.

## Files/capabilities đã đo

- Nền tảng Python 3.12 với FastAPI, Uvicorn, Pydantic Settings, SQLAlchemy async, asyncpg và Alembic.
- Cấu hình yêu cầu URL `postgresql+asyncpg` đầy đủ, dùng `SecretStr`, fail-fast khi thiếu/không hợp lệ, và bỏ qua các biến môi trường M00 không liên quan.
- Ứng dụng có `/live`, `/ready`, request ID, logging JSON, lỗi an toàn và kiểm tra PostgreSQL + pgvector có giới hạn thời gian.
- Alembic chạy async; migration đầu tiên chỉ bật extension pgvector, không có domain table.
- Compose dùng biến `DATABASE_URL_DOCKER` URL-encoded tách riêng, không ghép raw password.

## Commands đã thực thi

- `pip check`
- `python -m ruff check src tests`
- `python -m ruff format --check src tests`
- `RUN_INTEGRATION=1 python -m pytest`
- `docker compose config --quiet`
- `docker compose up --build -d`

## Kết quả đo đã chuẩn hóa

| Hạng mục | Trạng thái | Kết quả đo |
|---|---|---|
| Python isolated `.venv` | PASS | Python 3.12.10; FastAPI 0.141.1; Uvicorn 0.52.3; Pydantic 2.13.4; SQLAlchemy 2.0.52; Alembic 1.19.1; asyncpg 0.31.0; `pip check` PASS. |
| Ruff | PASS | Check và format check PASS; 15 files formatted. |
| M01 pytest | PASS | Với `RUN_INTEGRATION=1`: 14 PASS, gồm 13 unit và 1 integration PostgreSQL thực. |
| Hồi quy M00 | PASS | 50 PASS. |
| Docker/Compose | PASS | Docker 29.6.2; Compose v5.3.1; `docker compose config --quiet` PASS; `docker compose up --build -d` PASS lặp lại. |
| Dịch vụ hiện tại | PASS | `db` running/healthy trên host port 55432; `migrate` exited 0; `api` running trên 8000. API container chạy non-root uid=100/gid=101. |
| PostgreSQL/pgvector | PASS | Image `pgvector/pgvector:pg16`; extension vector thực tế 0.8.6; Alembic revision `0001_enable_pgvector`. |
| Liveness/readiness khi DB khỏe | PASS | `/live` trả 200 `{status:live}` kèm request ID; `/ready` trả 200 `{status:ready}` kèm request ID. |
| Outage/recovery thực tế | PASS | Khi dừng DB, `/live` vẫn 200 và `/ready` là 503 `{status:not_ready}`; sau khi DB healthy, `/ready` trở lại 200. |
| API log cuối | PASS | 12 dòng, 12 JSON, 0 non-JSON, 4 `request_complete`; không tìm thấy giá trị secret từ `.env`. |
| Quét giá trị thực toàn repo | PASS | 81 files được quét, 0 secret matches. |
| Git diff check | PASS | PASS. |

## Bằng chứng bảo mật

- `DATABASE_URL` được yêu cầu, kiểm tra đầy đủ driver/host/database/username/password và lưu dạng `SecretStr`.
- Lỗi cấu hình và lỗi HTTP không đưa credential, DSN, body, query hoặc header ra log/response.
- Request ID có trong response kiểm tra `/live` và `/ready`; logging cuối cùng là JSON hoàn toàn.
- Quét giá trị thực toàn repository không phát hiện secret match; log API cuối không có giá trị secret từ `.env`.
- Xung đột dependency của Python hệ thống toàn cục không được dùng làm bằng chứng dự án; `.venv` cô lập và Docker đều sạch.

## NOT_MEASURED

| Hạng mục | Trạng thái | Lý do |
|---|---|---|
| Thực thi Alembic downgrade | NOT_MEASURED | Chưa chạy trong bằng chứng này. |
| Production load/HA | NOT_MEASURED | Ngoài phạm vi demo M01. |
| Fresh reset bằng destructive volume deletion | NOT_MEASURED | Chưa thực hiện thao tác xóa volume phá hủy. |

## Rủi ro demo còn lại

- Image hiện có dev dependencies.
- Port có thể cấu hình nên vẫn có rủi ro xung đột port do môi trường vận hành.
- Biến môi trường vẫn do operator quản lý; cần cung cấp đúng cấu hình khi chạy demo.

## Xác nhận ngoài phạm vi

Không triển khai Provider, RAG, source, channel hoặc conversation trong M01.

## Điều kiện dừng

Dừng tại M01. Không bắt đầu M02; M02 vẫn `NOT_STARTED`.
