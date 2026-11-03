# Khoa Remote Workspace — MCP Gateway cho workspace được cấp quyền

Dự án MCP Gateway bảo vệ bằng OAuth, triển khai trên Render và kết nối Agent qua HTTPS theo chiều đi ra. Gateway chỉ mở cổng HTTPS cho OAuth và MCP; MCP backend và Agent Relay chỉ nghe localhost trong container Render.

**Production hiện tại:** Phase 4-B (v0.4.0), chỉ đọc. **Đang đề xuất:** Phase 4-C (v0.5.0), ghi file có giới hạn và kiểm tra cú pháp *không chạy mã dự án*. Chưa bật Phase 4-C cho tới khi toàn bộ regression tests PASS.

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
- Phase 4-C đề xuất ba công cụ `file_sha256`, `write_file`, `check_syntax` (Python, JSON, TOML) với giới hạn rõ ràng.
- `execute_command` vẫn bị khóa; không cung cấp shell tùy ý, `pytest`, xóa file, Git write hoặc thực thi mã dự án.

Muốn bật Phase 4-C phải cấu hình quyền **cả ở Render và Agent**. Đọc [thiết kế bảo mật Phase 4-C](docs/PHASE4C_VI.md) trước khi bật. Mặc định không cho phép ghi.

## Triển khai và kiểm chứng

Docker service dùng cổng public `8765` cho OAuth/MCP, cổng localhost `8766` cho Relay và `8767` cho MCP backend. SQLite của OAuth lưu trên persistent disk tại `/data/krw/oauth.sqlite`. Không commit mật khẩu, token, file cấu hình riêng hoặc SQLite.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
python3 -m compileall -q agent gateway
bash -n gateway/setup.sh
```

Tài liệu: [triển khai](DEPLOY_VI.md), [cài Agent](docs/AGENT_BOOTSTRAP_VI.md), [Phase 4-C](docs/PHASE4C_VI.md). Tài liệu Northflank cũ được giữ lại để tham khảo lịch sử; hiện tại hệ thống chạy trên Render.
