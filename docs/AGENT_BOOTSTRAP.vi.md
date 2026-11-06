# Remote-MCP — Cài đặt Agent trên Linux / Google Colab

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/AGENT_BOOTSTRAP.md) | **Tiếng Việt**

Gateway phục vụ `/setup.sh` và `/agent-bundle.tar.gz`. Mỗi deployment có **hostname HTTPS riêng**. Repository không công khai Gateway đang hoạt động của người duy trì.

## Cài đặt

Thay `https://gateway.example.com` bằng HTTPS origin của **Gateway do bạn triển khai**. Đây chỉ là ví dụ, không phải máy chủ đang hoạt động.

```bash
export REMOTE_MCP_GATEWAY_URL="https://gateway.example.com"
curl -fsSLo setup.sh "$REMOTE_MCP_GATEWAY_URL/setup.sh"
bash -n setup.sh
less setup.sh
bash setup.sh
```

Đọc script sau khi tải và trước khi chạy. Không thực thi trực tiếp nội dung chưa kiểm tra bằng pipe vào shell.

## Ghép nối và kết nối lại

Khi bật ghép nối, Agent tạo Device ID và credentials riêng; duyệt mã một lần tại trang `/devices` trên **Gateway của bạn**. Agent cần workspace riêng đã được cấp quyền. Credentials cũ được dùng lại nếu còn tồn tại.

Credentials được lưu tại `~/.config/krw-agent/agent.env` (quyền `0600`), **ngoài workspace**. Source và Python ở `~/.local/share/krw-agent`. Khởi động lại bằng `~/.local/share/krw-agent/start.sh`.

Installer xác minh SHA-256 gói Agent trong danh sách cho phép. Colab shutdown/reset có thể ngắt kết nối và làm mất danh tính đã lưu cục bộ. Không công khai token, mã ghép nối hoặc credentials trong URL, Git, notebook hay file workspace.

Xem [ghép nối thiết bị](DEVICE_ENROLLMENT.vi.md), [triển khai](../DEPLOY.vi.md) và [README](../README.vi.md).
