# Qualification

> 🌐 Language / Ngôn ngữ: [English](qualification.md) | **Tiếng Việt**

Qualification tách rõ public showcase ngắn với release evidence.

## Quick Demo

Quick Demo chứng minh luồng người dùng public, live query, bilingual retrieval, instruction-aware ranking, flexible dimensions và hoạt động của hai worker.

## Full production acceptance

`notebooks/kaggle-t4x2-production-demo.ipynb` build lại canonical index 100K từ đầu và xác minh production lifecycle trong fresh T4×2 session.

## Full qualification

`kaggle/demo.ipynb` chạy các check sâu hơn về semantic, model capability, hardware, long-context, regression và evidence.

## Biên evidence

Runtime evidence được bind với đúng Git revision đã tạo ra nó. Nếu executable notebook logic thay đổi, exact-SHA GPU acceptance phải chạy lại trước khi revision mới được kế thừa claim PASS.

## Chính sách fail-closed

Thiếu model/data input, fingerprint sai, checksum mismatch, GPU topology không hỗ trợ, worker failure hoặc vượt hard runtime limit đều làm acceptance fail thay vì bị bỏ qua.
