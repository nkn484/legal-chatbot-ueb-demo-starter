# Legal Chatbot UEB Demo Starter Pack

Phiên bản: 2026-08-17

## Mục tiêu

Tạo repo mới theo hướng **Demo-first + Modular Monolith + Vertical Slice**, nhưng giữ ba abstraction bắt buộc:

- `LLMProviderPort`
- `LegalSourcePort`
- `ChannelPort`

Demo dùng **SHINE SHOP + VBQPPL + Zalo Personal Bridge**. Kiến trúc mở cho Claude, VNU, UEB và kênh khác.

## Khởi tạo

1. Giải nén toàn bộ starter pack vào repo mới, ví dụ `D:\Projects\legal-chatbot-ueb-demo`.
2. Chạy:

```powershell
python scripts/verify_starter_pack.py
git init
git add .
git commit -m "chore: initialize demo starter"
python scripts/demo_gate.py init
python scripts/demo_gate.py status
```

3. Lấy model ID thật của SHINE SHOP:

```powershell
$env:SHINE_API_KEY = "YOUR_PRIVATE_KEY"
.\scripts\list_shineshop_models.ps1
Remove-Item Env:SHINE_API_KEY
```

4. Sinh `opencode.json`:

```powershell
python scripts/prepare_opencode_config.py --model-id "<EXACT_MODEL_ID>"
```

5. Chạy OpenCode:

```powershell
opencode
```

Trong TUI chạy `/connect` → `Other` → provider id `shineshop` → nhập API key riêng tư. Sau đó `/models` và chọn model đã cấu hình.

6. Bắt đầu milestone:

```powershell
python scripts/demo_gate.py start M00
```

Trong OpenCode:

```text
/m00-spike
```

Review plan, chuyển sang Build, rồi yêu cầu:

```text
Implement the approved M00 plan only. Do not begin M01. Run verification and report measured evidence.
```

Sau implementation:

```text
/review-milestone M00
```

Nếu đạt:

```powershell
python scripts/demo_gate.py submit M00 --note "Implementation reviewed."
python scripts/demo_gate.py approve M00 --by USER --note "PASS for demo."
```

## Milestones

```text
M00 Integration Feasibility Spike
M01 Foundation
M02 Provider Abstraction
M03 Source Abstraction + VBQPPL
M04 Ingestion + Index
M05 Retrieval + Citation
M06 Grounded Chat
M07 Conversation
M08 Zalo Channel
M09 Demo Hardening
```

Nguyên tắc: **đơn giản hóa infrastructure, không đơn giản hóa abstraction boundary**.
