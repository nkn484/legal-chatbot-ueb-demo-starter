# Project Charter

Mục tiêu: chatbot pháp luật demo cho UEB, trả lời có căn cứ, hội thoại đa lượt, kết nối Zalo cá nhân, dùng SHINE SHOP nhưng không khóa provider, và duy trì registry 3 nguồn VBQPPL → VNU → UEB.

Không xây trước các hạ tầng production không cần cho demo. Mỗi milestone phải tạo ra khả năng chạy/test được.

Vertical slice:
```text
VBQPPL -> ingest/version -> chunk/index -> retrieval -> citation -> SHINE SHOP -> conversation -> Zalo -> user
```
