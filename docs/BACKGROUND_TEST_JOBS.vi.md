# Background test jobs

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/BACKGROUND_TEST_JOBS.md) | **Tiếng Việt**

Remote-MCP hỗ trợ các bài test bất đồng bộ trong Agent đã cấp quyền, trong khi Agent vẫn polling HTTPS theo chiều đi ra.

| Công cụ | Chức năng |
| --- | --- |
| `start_long_task` | Xếp test vào hàng đợi và trả về `job_id` |
| `get_long_task` | Xem trạng thái đang chờ/chạy/kết thúc |
| `read_long_task_log` | Đọc log theo đoạn có giới hạn |
| `cancel_long_task` | Yêu cầu hủy task |

Chỉ hỗ trợ `pytest`, `rspec` và `rails_test`. Target phải qua kiểm tra giống controlled task; command cố định. Job ID thuộc một workspace cụ thể.

Giới hạn: một job chạy, tối đa hai job chờ, timeout **180 giây**, log tổng **256 KiB** và tối đa 12 bản ghi trong RAM. Kết quả đã kết thúc hết hạn sau một giờ khi có job mới. Trạng thái không còn sau khi Agent restart. Hủy job đang chạy là bất đồng bộ; cần kiểm tra trạng thái cuối.

Cần bật quyền controlled task, đồng thời `KRW_LONG_TASKS_ENABLED=1` trên Gateway và `KRW_ALLOW_LONG_TASKS=1` trên Agent. Code test chạy bằng quyền OS-user của Agent và **không có sandbox**.

Ví dụ: gọi `start_long_task(device_id, task_id="pytest", target="tests/test_safe.py", workspace_id="default")`, kiểm tra bằng `get_long_task`, đọc log bằng `read_long_task_log`.

Xem [controlled tasks](CONTROLLED_TASKS.vi.md) và [README](../README.vi.md).
