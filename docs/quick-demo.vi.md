# Quick Demo

> 🌐 Language / Ngôn ngữ: [English](quick-demo.md) | **Tiếng Việt**

Quick Demo là điểm bắt đầu public được khuyến nghị.

Demo dùng dataset đã xác minh `dangkhoa2016/qwen3-embedding-8b-en-vi-100k-index`, gồm 100.000 dòng Wikidata đã căn hàng và corpus vector 4096 chiều đã normalize.

## Phần nào vẫn chạy live

- Khởi động model
- Mọi query embedding của người dùng
- Semantic search tiếng Anh/tiếng Việt
- Cross-lingual retrieval
- Instruction-aware embedding calls
- Tính similarity
- Embedding calls với kích thước linh hoạt
- Phục vụ request đồng thời

Chỉ bước build vector cho toàn bộ corpus — phần tốn thời gian nhất — được tính sẵn.

## Cách đọc kết quả

Bảng search giữ nguyên **QID** Wikidata và hiển thị thêm label tiếng Anh/tiếng Việt bên cạnh.

Phần cross-lingual so sánh query EN/VI tương đương. Phần instruction-aware so sánh cùng một text khi encode như nội dung thường và như retrieval query.

## Runtime mục tiêu

Mục tiêu public là 5–10 phút, hard limit 15 phút. Startup time có thể khác nhau giữa các Kaggle session.

## Kiểm tra sâu hơn

Dùng production và qualification notebook để build lại full corpus và thu evidence sâu hơn.
