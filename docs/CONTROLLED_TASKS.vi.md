# Tác vụ workspace được kiểm soát

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/CONTROLLED_TASKS.md) | **Tiếng Việt**

Agent hỗ trợ các tác vụ đã được cấp quyền trong workspace:

| Task ID | Chức năng |
| --- | --- |
| `git_status` | Git status đã lọc |
| `git_log` | Lịch sử commit có giới hạn |
| `pytest` | Test Python |
| `rspec` | Test Ruby RSpec |
| `rails_test` | Test Rails |

`list_tasks(device_id, workspace_id="default")` liệt kê task. `run_task(device_id, task_id, target="", workspace_id="default")` chỉ chạy task đã biết; target tùy chọn phải là file test hợp lệ. Không nhận chuỗi lệnh shell hoặc flags tùy ý.

Gateway dùng `KRW_TASKS_ENABLED`, `KRW_TEST_TASKS_ENABLED`; Agent dùng `KRW_ALLOW_TASKS`, `KRW_ALLOW_TEST_TASKS`. Cả hai phía phải cho phép. Agent đã cài giữ quyền đã lưu; cài mới có thể bật quyền mặc định.

Task ngắn có timeout **15 giây** và giới hạn output. Test Python/Ruby chạy bằng quyền OS-user, **không có sandbox**. Chỉ chạy mã tin cậy trên môi trường cách ly, không chứa credentials quan trọng. Endpoint `execute_command` cũ vẫn bị khóa; `run_cli` / `run_shell` có quyền và giới hạn riêng.

Xem [background test jobs](BACKGROUND_TEST_JOBS.vi.md) hoặc [README](../README.vi.md) về CLI.
