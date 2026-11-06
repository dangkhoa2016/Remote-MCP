# Remote-MCP — Xác thực và truy cập thiết bị

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/README.md) | **Tiếng Việt**

Remote-MCP là MCP Gateway có xác thực OAuth dành cho các workspace được cấp quyền. Bắt đầu từ [README](../README.vi.md) và [hướng dẫn Render](../DEPLOY.vi.md). Các lệnh chuyển đổi Cloudflare Tunnel/Codespaces cũ không còn là hướng dẫn cài đặt hiện tại.

## Xác thực

ChatGPT sử dụng OAuth authorization code với PKCE; chủ sở hữu đăng nhập bằng username và password cục bộ đã cấu hình. Frontend công khai xử lý `/authorize`, `/token` và `/mcp`; Relay và backend chỉ bind loopback. Trang đăng nhập và trang Devices có cùng giao diện responsive. Username được bỏ khoảng trắng khi gửi form và ở server; password không bị sửa.

## Ghép nối thiết bị

Cài Agent trên máy tin cậy bằng installer `/setup.sh` của Gateway, sau đó vào trang `/devices` trên Gateway do bạn triển khai để duyệt mã ghép nối một lần hiển thị tại terminal. Mỗi thiết bị có credentials riêng, được lưu bên ngoài workspace được cấp quyền.

Không commit credentials hoặc SQLite. Kiểm tra reconnect, các quyền độc lập và ranh giới OAuth. Xem [cài Agent](AGENT_BOOTSTRAP.vi.md) và [checklist phát hành](RELEASE_READINESS.vi.md).
