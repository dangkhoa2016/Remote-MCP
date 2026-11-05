# Phase 8 — Quản lý bài test chạy dài (v0.9.0)

Phase 8 bổ sung **task bất đồng bộ lưu trạng thái trong Agent**, có hạn mức rõ ràng. MCP trả về ID ngay mà không chờ bài test hoàn thành; Agent vẫn polling HTTPS theo chiều đi ra. Không bổ sung inbound listener, shell tùy ý, ghi Git hoặc force push.

## Các công cụ MCP

| Tool | Chức năng |
| --- | --- |
| `start_long_task(device_id, task_id, target="", workspace_id="default")` | Đưa bài test hợp lệ vào hàng đợi và trả về `job_id` |
| `get_long_task(device_id, job_id, workspace_id="default")` | Xem trạng thái đang chờ, chạy hoặc đã kết thúc |
| `read_long_task_log(device_id, job_id, offset=0, max_bytes=4096, workspace_id="default")` | Đọc từng phần stdout/stderr chung, tiếp tục bằng `next_offset` |
| `cancel_long_task(device_id, job_id, workspace_id="default")` | Hủy task đang chờ hoặc yêu cầu kết thúc cả process group |

Phase 8 **chỉ** hỗ trợ `pytest`, `rspec` và `rails_test`. Tham số `target` phải là file test hợp lệ theo Phase 7. Không có tham số shell hay flags tùy ý. Git read-only tiếp tục qua Phase 7; không đưa vào hàng đợi task dài.

**Cảnh báo:** Test thực thi mã repository dưới quyền OS user của Agent. Task runner **không phải sandbox**. Mã test có thể đọc file hoặc gửi dữ liệu qua mạng nếu OS user có quyền. Chỉ chạy mã tin cậy trong container tách biệt, không có credentials, hạn chế mạng và không dùng quyền root nếu có thể.

## Giới hạn và vòng đời

- Tối đa **1 task đang chạy trên toàn Agent**, cùng lúc tối đa **2 task đang chờ**, dù có nhiều workspace.
- Timeout theo thời gian thực **180 giây/task**. Quá hạn sẽ hủy process group. Bộ test lớn hơn cần đánh giá lại timeout/tài nguyên.
- Tổng log stdout+stderr lưu tối đa **256 KiB**; vượt quá sẽ dừng task. Mỗi lần đọc tối đa **8 KiB**.
- ID task là 128 bit random (32 ký tự hex) và gắn với workspace; không thể gửi PID tùy ý.
- Trạng thái: `queued`, `running`, `succeeded`, `failed`, `cancelled`, `timed_out`, `output_limit`. Hủy task đang chạy có thể trả về trước khi process thực sự dừng, cần poll lại.
- Giữ tối đa **12 bản ghi task trong RAM**. Task đã kết thúc hết hạn sau **1 giờ** và được dọn khi có task mới. Nếu đầy, API báo lỗi.
- Khi Agent nhận SIGINT/SIGTERM sẽ cố gắng hủy các task. **Không lưu bền** sau restart, crash hay reset Colab; force kill không bảo đảm dừng mọi tiến trình con bên ngoài.

`execute_command` cũ vẫn **khóa hoàn toàn**. `run_task` Phase 7 vẫn có giới hạn 15 giây riêng.

## Cấu hình cần bật thủ công

Trên Render Gateway:

```env
KRW_TASKS_ENABLED=1
KRW_TEST_TASKS_ENABLED=1
KRW_LONG_TASKS_ENABLED=1
```

Trên Agent Colab, dừng Agent cũ trước, rồi chạy:

```bash
export KRW_ALLOW_TASKS=1
export KRW_ALLOW_TEST_TASKS=1
export KRW_ALLOW_LONG_TASKS=1
curl -fsSLo /tmp/krw-setup.sh https://remote-mcp-ka1p.onrender.com/setup.sh
bash -n /tmp/krw-setup.sh
bash /tmp/krw-setup.sh
```

Bộ cài giữ lại token thiết bị và cấu hình workspace trong `agent.env` (chỉ chủ sở hữu đọc được). Quyền chạy task dài **mặc định tắt** trên cả hai phía. Khi nghiệm thu xong nên cân nhắc tắt quyền chạy test từ xa.

## Kịch bản nghiệm thu thực tế

Dùng workspace `secondary` riêng, có file `tests/test_phase8_smoke.py` kiểm tra đơn giản. Xác nhận `list_workspaces` và `list_tasks` trước, sau đó:

1. `start_long_task(device_id="local-dev", task_id="pytest", target="tests/test_phase8_smoke.py", workspace_id="secondary")`.
2. Lấy `job_id` được trả về.
3. Dùng `get_long_task` cho đến trạng thái cuối, kỳ vọng `succeeded`.
4. Dùng `read_long_task_log` với `offset=0`, tăng `offset` theo `next_offset`.
5. Kiểm tra hủy bằng một bài test cố ý ngủ đủ lâu trong workspace thử nghiệm; dùng `cancel_long_task` rồi xác nhận trạng thái `cancelled`. Không hủy job production để thử nghiệm.

Cần có **CI PASS và test thực tế** trước khi tuyên bố hoàn tất end-to-end. Merge GitHub không đồng nghĩa Render đã deploy hay Agent Colab đã cập nhật.

Tài liệu liên quan: [Phase 7](PHASE7_VI.md), [README tiếng Việt](../README.vi.md).
