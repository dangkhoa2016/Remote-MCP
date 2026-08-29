# Xử lý sự cố

> 🌐 Language / Ngôn ngữ: [English](troubleshooting.md) | **Tiếng Việt**

## Không tìm thấy model

Kiểm tra `dangkhoa2016/qwen-qwen3-embedding-8b` đã được attach bằng **Add Input → Models**. Không copy model vào `/kaggle/working`.

## Không tìm thấy Quick Demo index

Attach `dangkhoa2016/qwen3-embedding-8b-en-vi-100k-index` bằng **Add Input → Datasets**.

## Chỉ thấy một GPU

Dừng session và chọn **GPU T4 ×2**. Public workflow được hỗ trợ sẽ fail-closed nếu topology mong đợi không có.

## Lỗi package khi bootstrap

Giữ Internet bật trong bước bootstrap. Sau khi dependency và Kaggle Inputs sẵn sàng, model/data loading chạy local.

## Checksum hoặc fingerprint fail

Không bypass check. Hãy detach input cũ, attach đúng artifact đã publish và bắt đầu fresh session.

## Startup chậm hơn run trước

Latency startup/model load trên Kaggle có thể dao động. Hãy đánh giá run theo readiness, failures và runtime ceiling cấu hình thay vì một startup time trước đó.
