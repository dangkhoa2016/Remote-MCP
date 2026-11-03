# Phase 5 — Công cụ quản lý workspace linh hoạt (v0.6.0)

Phase 5 bổ sung năm công cụ mà không bật shell từ xa hoặc Git write.

| Công cụ | Mục đích |
|---|---|
| `edit_file` | Thay thế đoạn văn bản chính xác, SHA-256 có thể cung cấp tùy chọn |
| `search_files` | Tìm theo tên và nội dung trong các thư mục workspace |
| `create_directory` | Tạo thư mục và có thể tự tạo thư mục cha |
| `move_file` | Di chuyển một file UTF-8; không âm thầm ghi đè đích |
| `delete_file` | Xóa một file văn bản thông thường; có thể kiểm tra SHA-256 |

Các công cụ hiện có `write_file`, `read_file`, `file_sha256` và `check_syntax` vẫn được giữ lại.

## Giới hạn và cách hoạt động

- `write_file`: tối đa 1 MiB văn bản UTF-8 mỗi lần (trước đây là 16 KiB).
- `read_file`: tối đa 256 KiB mỗi lần (mặc định vẫn là 8 KiB).
- SHA-256 file hiện có: tối đa 2 MiB. Kiểm tra cú pháp: tối đa 1 MiB.
- `search_files`: tối đa 100 kết quả, quét 2.000 file và 8 cấp thư mục trong mỗi lần gọi.
- Hỗ trợ dotfile thông thường như `.gitignore` và file không có phần mở rộng như `Gemfile`. Tên file có dấu hiệu chứa bí mật và thư mục `.git` vẫn bị giới hạn.
- `edit_file` mặc định yêu cầu chính xác một vị trí khớp. Công cụ tự so sánh SHA-256 khi sửa để giảm nguy cơ ghi đè không chủ ý; người dùng thường không cần tự nhập hash.
- `move_file` tạo file đích rồi xóa file nguồn. Nếu xóa nguồn thất bại, chương trình thử thu hồi bản sao mới; cần kiểm tra kết quả nếu gặp lỗi.
- Chỉ dùng cho văn bản UTF-8, không dùng cho file nhị phân.
- Mọi thao tác vẫn ở trong workspace của thiết bị đã được cấp quyền; không cho thoát thư mục qua `..` hoặc symlink.

## Bật tính năng và cập nhật

Trên Render, bật `KRW_WRITE_ENABLED=1` cho các thao tác ghi/di chuyển/xóa.
Trên Agent, bật `KRW_ALLOW_FILE_WRITES=1`. Có thể giữ cấu hình đã bật từ Phase 4-C.
`search_files` chỉ đọc nên không cần bật quyền ghi.
Sau khi deploy Gateway, cập nhật và khởi động lại Agent bằng bộ cài đã được kiểm chứng để nhận module Worker mới. Tiếp đó refresh tool discovery trong ChatGPT.

## Điều kiện phát hành

Yêu cầu regression jobs Python 3.10 và 3.13 PASS trên pull request trước khi merge. Sau đó xác minh trên workspace thử nghiệm trước khi tác động đến dự án thực tế.
