# An toàn workspace và kiểm tra cú pháp

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/WORKSPACE_SAFETY.md) | **Tiếng Việt**

Remote-MCP 1.0.0 giới hạn thao tác file trong các workspace được chủ sở hữu Agent cấp quyền.

- `file_sha256(device_id, path)` tính SHA-256 của file được phép.
- `write_file(device_id, path, content, expected_sha256=null)` ghi văn bản UTF-8 tối đa 1 MiB; có thể dùng hash để phát hiện xung đột. Cần `overwrite=true` khi chủ động ghi đè file hiện có.
- `check_syntax(device_id, path)` phân tích cú pháp Python, JSON hoặc TOML mà không chạy mã nguồn.

Ghi file cần `KRW_WRITE_ENABLED=1` ở Gateway và `KRW_ALLOW_FILE_WRITES=1` ở Agent. Kiểm tra cú pháp cần `KRW_STATIC_CHECKS_ENABLED=1` và `KRW_ALLOW_STATIC_CHECKS=1` tương ứng.

Đường dẫn phải tương đối theo workspace đã duyệt. Hệ thống chặn symlink escape, tên nhạy cảm và thao tác file nguy hiểm. Điều kiện hash giảm nguy cơ ghi đè ngoài ý muốn nhưng không đảm bảo giao dịch hoàn toàn với tiến trình bên ngoài.

**Bảo mật:** kiểm tra cú pháp không chạy code. Công cụ test hoặc CLI riêng có thể chạy mã và *không* phải OS sandbox. Chỉ dùng workspace đáng tin cậy.

Xem [thao tác file](FILE_OPERATIONS.vi.md), [tác vụ kiểm soát](CONTROLLED_TASKS.vi.md) và [README](../README.vi.md).
