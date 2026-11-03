# Phase 4-C — ghi file có giới hạn và kiểm tra cú pháp

**Trạng thái:** Đang ở nhánh tính năng; Render và Agent đều phải bật quyền riêng trước khi dùng. Chưa bật trên production.

Ba công cụ MCP mới:

- `file_sha256(device_id, path)`: lấy SHA-256 của một file hợp lệ, tối đa 256 KiB.
- `write_file(device_id, path, content, expected_sha256=null)`: tạo một file UTF-8 mới (tối đa 16 KiB), hoặc cập nhật file có sẵn nếu SHA-256 hiện tại khớp `expected_sha256`. Không xóa file, tạo thư mục, đổi quyền hoặc thực hiện Git write.
- `check_syntax(device_id, path)`: phân tích cú pháp Python, JSON hoặc TOML mà **không chạy mã dự án**.

Mặc định mọi quyền mới đều bị khóa. Để cho phép ghi file cần **đồng thời** `KRW_WRITE_ENABLED=1` trên Render và `KRW_ALLOW_FILE_WRITES=1` trên Agent. Để kiểm tra cú pháp cần `KRW_STATIC_CHECKS_ENABLED=1` trên Render và `KRW_ALLOW_STATIC_CHECKS=1` trên Agent. File cấu hình Agent nằm tại `~/.config/krw-agent/agent.env`; chỉnh file riêng tư rồi khởi động lại Agent. Installer mặc định ghi giá trị `0` cho cả hai quyền.

Bảo vệ filesystem: chỉ chấp nhận đường dẫn tương đối dưới workspace được cấp quyền, thư mục cha tồn tại và không symlink, tên file không chứa dấu hiệu secrets, extension nằm trong allowlist, từ chối cập nhật hardlink và dùng `O_NOFOLLOW` để tránh symlink swap. Cập nhật file dựa trên SHA-256 và ghi tạm rồi thay thế nguyên tử. Không chọn `/content` hoặc thư mục HOME làm workspace.

**Giới hạn:** SHA-256 giúp tránh ghi đè vô ý nhưng không phải cơ chế compare-and-swap tuyệt đối nếu nhiều tiến trình khác cùng sửa file. Không cho nhiều tiến trình chỉnh cùng một file trong lúc Agent đang cập nhật.

`execute_command` tiếp tục bị khóa. Phase này **chưa chạy pytest từ xa**, vì pytest có thể thực thi bất kỳ mã nào trong repository và Colab hiện chưa có sandbox cách ly token Agent. `check_syntax` chỉ là kiểm tra cú pháp, không thay thế unit tests.

Trước khi merge: chạy `python3 -m pytest -q`, `python3 -m compileall -q agent gateway` và `bash -n gateway/setup.sh` trên nhánh mới; chỉ triển khai sau khi PASS. Trên Render vẫn giữ `KRW_COMMANDS_ENABLED=0`.
