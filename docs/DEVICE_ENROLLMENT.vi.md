# Ghép nối thiết bị và phê duyệt trên trình duyệt

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/DEVICE_ENROLLMENT.md) | **Tiếng Việt**

Remote-MCP hỗ trợ các Agent có danh tính độc lập. Khi cài mới, Agent tạo Device ID bền vững và credentials ngẫu nhiên 256-bit. Gateway chỉ lưu digest của credentials đã duyệt trong SQLite.

## Ghép nối

1. Chạy Agent installer đã kiểm tra trên máy Linux/Colab tin cậy với workspace chuyên dụng.
2. Xem mã ghép nối dùng một lần **trên terminal của Agent**.
3. Mở trang `/devices` trên Gateway do bạn triển khai, đăng nhập và duyệt đúng thiết bị.
4. Giữ cấu hình tại `~/.config/krw-agent/agent.env` (quyền 0600) **ngoài workspace được mở qua MCP**. Khởi động lại bằng `~/.local/share/krw-agent/start.sh`.

Mã ghép nối hết hạn sau mười phút; số lần thử sai và request chờ có giới hạn. Thu hồi thiết bị chặn các lần polling có xác thực tiếp theo. Nếu Colab reset làm mất credentials, thiết bị tạo danh tính mới và cần duyệt lại.

## Cấu hình và lưu bền

Gateway sử dụng `KRW_DEVICE_ENROLLMENT_ENABLED=1`, `KRW_DEVICE_ADMIN_TOOLS_ENABLED=1` và đường dẫn `KRW_DEVICE_DB_PATH` bảo vệ. Không mở control endpoints hoặc công khai credentials. SQLite lưu ghép nối và OAuth phải tồn tại qua redeploy; thư mục có thể ghi trong Docker image **không chứng minh** đã có persistent disk.

Đăng nhập qua trình duyệt dùng cookie bảo mật, CSRF và kiểm tra nguồn request. Chỉ admin đã đăng nhập với mã một lần mới được duyệt thiết bị. Không đưa credentials, mã ghép nối hoặc database lên issue/Git.

## Kiểm thử độc lập

`python scripts/device_enrollment_staging_smoke.py` thử nghiệm Gateway/Agent localhost cách ly để kiểm tra đăng ký, duyệt, điều phối và thu hồi mà không liên hệ production. Khả năng reconnect và lưu bền production vẫn cần nghiệm thu riêng.

Xem [cài Agent](AGENT_BOOTSTRAP.vi.md), [README](../README.vi.md) và [checklist phát hành](RELEASE_READINESS.vi.md).
