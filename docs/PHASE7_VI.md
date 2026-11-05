# Phase 7 — Chạy tác vụ có kiểm soát (v0.8.0)

Phase 7 bổ sung **trình chạy tác vụ cố định**, không mở API thực thi lệnh tùy ý. Hệ thống vẫn dùng OAuth, xác thực thiết bị, phân quyền từng workspace và Agent kết nối HTTPS chiều đi ra.

## Công cụ và tác vụ hỗ trợ

- `list_tasks(device_id, workspace_id="default")`: xem danh sách tác vụ cố định và quyền trên Agent.
- `run_task(device_id, task_id, target="", workspace_id="default")`: chạy một tác vụ được cho phép trong workspace đã đăng ký.

| Task ID | Thao tác | Quyền bổ sung |
| --- | --- | --- |
| `git_status` | Đọc Git status đã lọc thông tin | Task |
| `git_log` | Đọc tối đa 10 commit Git đã lọc | Task |
| `pytest` | `pytest -q --disable-warnings` (hoặc Python của Agent chạy `-m pytest`) | Task + test |
| `rspec` | `bundle exec rspec --format progress` | Task + test |
| `rails_test` | `bundle exec rails test` | Task + test |

`target` không bắt buộc, nhưng nếu cung cấp phải là file test có thật, không phải symlink: Python `.py` trong `test/` hoặc `tests/`, RSpec `.rb` trong `spec/`, Rails `.rb` trong `test/`. Để trống `target` để chạy toàn bộ bộ test. Không hỗ trợ nhập shell, flags, biến môi trường, nối lệnh, Git push hoặc sửa Git refs thông qua runner.

MCP action `execute_command` cũ **vẫn bị khóa**, bất kể cấu hình task. Git stage/commit/push hiện có vẫn dùng quyền riêng của Phase 6.

## Phân quyền riêng tại hai nơi

Trên **Render Gateway**, cấu hình rồi deploy/restart:

```env
KRW_TASKS_ENABLED=1
KRW_TEST_TASKS_ENABLED=1
```

Trên **Agent / Colab**, dừng Agent cũ, sau đó thiết lập biến môi trường trước khi chạy bộ cài đã xác minh:

```bash
export KRW_ALLOW_TASKS=1
export KRW_ALLOW_TEST_TASKS=1
curl -fsSLo /tmp/krw-setup.sh https://remote-mcp-ka1p.onrender.com/setup.sh
bash -n /tmp/krw-setup.sh
bash /tmp/krw-setup.sh
```

Bộ cài sẽ giữ các quyền trong `~/.config/krw-agent/agent.env` (chỉ chủ thiết bị đọc được, mode 0600). Muốn tắt, chuyển cả hai biến Render về `0`, tắt biến Agent rồi restart. **Mặc định mọi quyền task đều TẮT.**

## Giới hạn và bảo mật

- Chỉ chạy argv cố định; không dùng `shell=True`, không chấp nhận chuỗi lệnh tùy ý.
- Test executable phải được cài sẵn và có trong PATH được hạn chế; pytest có thể dùng Python của Agent khi thiếu executable; Ruby/Bundler và dependency dự án phải cài trước.
- Timeout **15 giây** để phù hợp giới hạn relay. Bộ test dài cần kiến trúc hàng đợi chạy không đồng bộ ở phiên bản tương lai.
- Mỗi luồng stdout/stderr được giữ tối đa **16 KiB**; tổng output đọc tối đa **1 MiB**, vượt quá sẽ dừng process group.
- Chạy bằng POSIX process group riêng, áp dụng một số giới hạn CPU/kích thước file.
- Môi trường con được tối giản, không truyền Agent token hay GitHub push token. Trả về mã thoát và output đã giới hạn.

**Lưu ý quan trọng:** Test task **thực sự chạy mã của repository** (bao gồm import, khởi tạo Ruby, hook framework, plugin và subprocess). Runner **không phải sandbox cấp hệ điều hành**. Mã test vẫn có thể đọc file hoặc truy cập mạng trong phạm vi quyền tài khoản OS đang chạy Agent. Cần dùng mã tin cậy, tốt nhất trên container dùng một lần, user không đặc quyền, giới hạn mạng và không chứa secrets. Không bật test task đối với repository do người lạ cung cấp.

## Triển khai và nghiệm thu

1. Test regression Python 3.10/3.13, kiểm tra bộ cài/bundle, chỉ merge khi PASS.
2. Deploy Gateway v0.8.0, xác minh bằng `health_check`.
3. Dừng và cập nhật Agent, refresh MCP tools trên ChatGPT.
4. Dùng `list_tasks` xác minh năm task ID và quyền bật.
5. Chạy `git_status` và pytest nhỏ trong workspace thử nghiệm, kiểm tra timeout và output.
6. Giữ `execute_command` cũ bị khóa, không test trên dự án Rails production.

Tài liệu: [README tiếng Việt](../README.vi.md) và [Phase 6](PHASE6_VI.md).
