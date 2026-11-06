# Remote-MCP — Triển khai trên Render

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/DEPLOY.md) | **Tiếng Việt**

Remote-MCP sử dụng Gateway có xác thực OAuth trên Render và Agent chỉ tạo kết nối đi ra. Quy trình cài đặt Northflank/Codespaces cũ đã ngừng sử dụng và không áp dụng cho repository hiện tại.

## Kiến trúc triển khai

- Triển khai `Dockerfile` tại root từ nhánh `main`. HTTPS công khai kết nối đến Gateway frontend qua cổng container 8765.
- Agent Relay cổng 8766 và MCP backend cổng 8767 chỉ bind loopback; không mở hai cổng này ra Internet.
- Chỉ lưu thông tin đăng nhập OAuth, signing key, Agent credentials và token Relay trong cấu hình runtime được bảo vệ, không đưa vào Git.
- Cấu hình đúng hostname và OAuth callback ChatGPT của deployment. Dùng địa chỉ HTTPS của Gateway do bạn triển khai. `https://gateway.example.com` chỉ là ví dụ. Đặt `KRW_MCP_PUBLIC_URL` bằng URL HTTPS thật, kết thúc bằng `/mcp`.

## Lưu trữ và ghép nối thiết bị

SQLite cho OAuth và enrollment cần tồn tại qua lần thay container để giữ phiên đăng nhập và thiết bị đã duyệt. Thư mục `/data/krw` có thể ghi không chứng minh đã gắn persistent disk; kiểm tra `enrollment_separate_mount_detected` và thử nghiệm sau lần triển khai mới. Render miễn phí có thể không hỗ trợ persistent disk.

Để kết nối Agent, kiểm tra installer `/setup.sh`, chạy trên máy tin cậy rồi duyệt mã một lần từ terminal trên trang `/devices` của Gateway của bạn. Giữ nguyên Device ID và credentials đã lưu ngoài workspace khi khởi động lại.

## Nghiệm thu

Chạy `python3 -m pip install -r requirements-dev.txt` và `python3 -m pytest -q`. Kiểm tra `/health`, OAuth discovery, MCP có xác thực và khả năng reconnect. Xác nhận request chưa đăng nhập không truy cập được công cụ được bảo vệ.

Xem [README](README.vi.md), [cài Agent](docs/AGENT_BOOTSTRAP.vi.md) và [checklist phát hành](docs/RELEASE_READINESS.vi.md).
