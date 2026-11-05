# Khoa Remote Workspace — MCP Gateway cho workspace được cấp quyền

Dự án MCP Gateway bảo vệ bằng OAuth, triển khai trên Render và kết nối Agent qua HTTPS theo chiều đi ra. Gateway chỉ mở cổng HTTPS cho OAuth và MCP; MCP backend và Agent Relay chỉ nghe localhost trong container Render.

**Bản phát triển:** Phase 8 (v0.9.0) bổ sung task test chạy dài trên Agent, hàng đợi có giới hạn, trạng thái riêng, log phân trang và khả năng hủy. Cần deploy Gateway, cập nhật Agent và xác minh bằng `health_check`.

## Kết nối Agent (Linux / Google Colab)

Nên tải và kiểm tra script trước khi chạy:

```bash
curl -fsSLo setup.sh https://remote-mcp-ka1p.onrender.com/setup.sh
bash -n setup.sh
less setup.sh
bash setup.sh
```

Khi đã tin cậy máy chủ, có thể cài bằng một lệnh:

```bash
wget -qO- https://remote-mcp-ka1p.onrender.com/setup.sh | bash
```

Cần cung cấp Device ID/token đã đăng ký và một thư mục workspace riêng đã tồn tại. Không chọn `/content`, thư mục HOME hoặc thư mục chứa secrets. Token được lưu **bên ngoài workspace** tại `~/.config/krw-agent/agent.env` với quyền `0600`. Để chạy lại dùng `~/.local/share/krw-agent/start.sh`. Gói Agent được xác minh SHA-256 trước khi cài.

## Khả năng của hệ thống

- Xem thông tin thiết bị, liệt kê thư mục và đọc file UTF-8 trong workspace được cấp quyền.
- Đọc Git status, diff từng file và lịch sử commit trong Git repository thật nằm bên trong workspace.
- Phase 4-C có `file_sha256`, `write_file` (tối đa 1 MiB) và `check_syntax` (Python, JSON, TOML) không thực thi mã dự án.
- Phase 5 bổ sung `edit_file`, `search_files`, `create_directory`, `move_file`, `delete_file`; đọc tối đa 256 KiB mỗi lần, hỗ trợ dotfile thông thường và file nguồn UTF-8 không có phần mở rộng.
- Phase 6 bổ sung `list_workspaces` và tham số `workspace_id` tùy chọn, `move_directory`, `delete_directory`, `git_branches`, `git_stage`, `git_unstage`, `git_commit`, `git_branch_create`, `git_branch_switch`, `git_push`.
- Phase 6.1 cho phép chuyển nhánh khi file untracked không xung đột, vẫn bảo vệ thay đổi tracked/staged; từ chối cấu hình nhiều workspace có thư mục gốc trùng hoặc lồng nhau.
- Phase 7 bổ sung `list_tasks` và `run_task` với các ID cố định `git_status`, `git_log`, `pytest`, `rspec`, `rails_test` trong workspace được chọn, cho phép chỉ định file test hợp lệ.
- Phase 8 bổ sung `start_long_task`, `get_long_task`, `read_long_task_log`, `cancel_long_task` cho các bài test được duyệt. Mỗi Agent chỉ chạy một task, chờ tối đa hai; timeout 180 giây, log tối đa 256 KiB. Trạng thái task chỉ lưu tạm trong Agent và tách biệt theo workspace.
- `execute_command` cũ vẫn bị khóa. Git write, Git push và chạy test có quyền bật riêng. Không hỗ trợ shell tùy ý hoặc force push. **Test task thực thi mã dự án và không phải sandbox cấp OS**.

Muốn ghi file/thư mục cần bật quyền **cả trên Render và Agent** (`KRW_WRITE_ENABLED=1`, `KRW_ALLOW_FILE_WRITES=1`). Git write có quyền độc lập (`KRW_GIT_WRITES_ENABLED=1`, `KRW_ALLOW_GIT_WRITES=1`); push cần bật thêm quyền và token tại Agent. Runner có quyền riêng: `KRW_TASKS_ENABLED` / `KRW_TEST_TASKS_ENABLED` (Render), `KRW_ALLOW_TASKS` / `KRW_ALLOW_TEST_TASKS` (Agent). Phase 8 cần bật thêm `KRW_LONG_TASKS_ENABLED` (Render) và `KRW_ALLOW_LONG_TASKS` (Agent); mặc định đều TẮT. Xem [Phase 8](docs/PHASE8_VI.md) về cài đặt, bảo mật và vòng đời task.

## Triển khai và kiểm chứng

Docker service dùng cổng public `8765` cho OAuth/MCP, cổng localhost `8766` cho Relay và `8767` cho MCP backend. SQLite của OAuth lưu trên persistent disk tại `/data/krw/oauth.sqlite`. Không commit mật khẩu, token, file cấu hình riêng hoặc SQLite.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
python3 -m compileall -q agent gateway
bash -n gateway/setup.sh
```

Tài liệu: [triển khai](DEPLOY_VI.md), [cài Agent](docs/AGENT_BOOTSTRAP_VI.md), [Phase 4-C](docs/PHASE4C_VI.md), [Phase 5](docs/PHASE5_VI.md), [Phase 6](docs/PHASE6_VI.md), [Phase 7](docs/PHASE7_VI.md), [Phase 8](docs/PHASE8_VI.md). Tài liệu Northflank cũ được giữ lại để tham khảo lịch sử; hiện tại hệ thống chạy trên Render.
