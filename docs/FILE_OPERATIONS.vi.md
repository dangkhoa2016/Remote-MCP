# Thao tác file trong workspace

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/FILE_OPERATIONS.md) | **Tiếng Việt**

Agent cung cấp các công cụ thao tác file và thư mục trong Remote-MCP 1.0.0.

| Công cụ | Chức năng |
| --- | --- |
| `read_file` | Đọc UTF-8 với giới hạn output |
| `file_sha256` | Tính hash file được phép |
| `write_file` | Tạo file hoặc ghi đè có xác nhận |
| `edit_file` | Thay thế đúng đoạn text và kiểm tra xung đột |
| `search_files` | Tìm tên file/nội dung trong workspace |
| `create_directory` | Tạo thư mục, có thể tạo parent |
| `move_file` | Di chuyển file UTF-8, không tự ghi đè |
| `delete_file` | Xóa file được phép với hash tùy chọn |
| `check_syntax` | Kiểm tra Python, JSON, TOML mà không thực thi |

Giới hạn hiện tại: `write_file` 1 MiB; `read_file` 256 KiB/lần; kiểm tra cú pháp 1 MiB; `search_files` tối đa 100 kết quả trong 2.000 file và tám cấp thư mục. Có hỗ trợ dotfile thông thường và file nguồn không có phần mở rộng, ngoại trừ tên bị bảo vệ và metadata Git.

Ghi file cần bật quyền **cả Gateway** (`KRW_WRITE_ENABLED=1`) **và Agent** (`KRW_ALLOW_FILE_WRITES=1`). Cài Agent mới có thể bật quyền mặc định của Agent, nhưng quyền Gateway vẫn độc lập. Các cờ tắt do người dùng đặt vẫn có hiệu lực.

Chỉ cho phép đường dẫn tương đối theo workspace; chặn symlink escape và ghi đè bất ngờ. Thay đổi đồng thời từ tiến trình khác có thể khiến move/delete hoàn tất một phần; cần kiểm tra kết quả.

Xem [an toàn workspace](WORKSPACE_SAFETY.vi.md), [Git](WORKSPACE_GIT_OPERATIONS.vi.md) và [README](../README.vi.md).
