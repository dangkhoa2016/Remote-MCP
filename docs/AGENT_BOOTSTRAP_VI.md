# Khoa Remote Workspace — Cài đặt Agent từ Render

Gateway cung cấp hai endpoint công khai: `/setup.sh` và `/agent-bundle.tar.gz`. Không thay đổi OAuth, SQLite hoặc các quyền MCP hiện tại.

## Cách sử dụng

Khuyến nghị tải script và đọc trước khi chạy:

```bash
curl -fsSLo setup.sh https://remote-mcp-ka1p.onrender.com/setup.sh
less setup.sh
bash setup.sh
```

Nếu đã tin cậy server và muốn một lệnh:

```bash
curl -fsSL https://remote-mcp-ka1p.onrender.com/setup.sh | bash
# Hoặc:
wget -qO- https://remote-mcp-ka1p.onrender.com/setup.sh | bash
```

Lưu ý: `wget URL | bash` không đúng vì wget thường tải file xuống ổ đĩa; phải sử dụng `-qO-` để đưa nội dung ra stdout.

Installer hỏi mã thiết bị, đường dẫn tuyệt đối tới một workspace đã tồn tại và device token (nhập ẩn). Token phải được đăng ký sẵn trong `KRW_DEVICE_TOKENS_JSON` trên Render; script không tự tạo hoặc lấy token.

- Source Agent: `~/.local/share/krw-agent`
- File chứa token: `~/.config/krw-agent/agent.env` (quyền `0600`, nằm ngoài workspace)
- Chạy lại: `~/.local/share/krw-agent/start.sh`
- Dừng: `Ctrl+C`

Script chỉ tải các file Agent trong danh sách cho phép, xác minh SHA-256 trước khi giải nén, và bắt buộc `KRW_COMMANDS_ENABLED=0` cùng `KRW_ALLOW_TEST_COMMANDS=0`. Không gửi token qua URL, GitHub, log hoặc cuộc trò chuyện.

Khi Colab reset, Agent sẽ offline; cần khôi phục workspace và thông tin xác thực ở môi trường Colab mới. Với Git tools, workspace phải là một Git repository thật.

Việc chạy `curl | bash` hay `wget | bash` có rủi ro thực thi mã từ Internet. Luôn chỉ dùng với endpoint bạn quản lý và nên đọc nội dung script trước.
