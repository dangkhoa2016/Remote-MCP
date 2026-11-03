# Phase 6 — Nhiều workspace, quản lý thư mục và Git (v0.7.0)

Phase 6 mở rộng Agent kết nối một chiều mà không bật shell tùy ý từ xa.

## Các MCP tools mới

- `list_workspaces(device_id)`: liệt kê các thư mục gốc đã được chủ thiết bị cho phép.
- Các công cụ đọc/ghi file, thư mục và Git hiện có nhận thêm `workspace_id` tùy chọn (mặc định `default`, tương thích Phase 5).
- `move_directory`: đổi vị trí/tên thư mục trong một workspace, không chủ ý ghi đè thư mục đích.
- `delete_directory`: xóa thư mục trống; chọn rõ `recursive=true` để xóa cả nội dung (tối đa 1.000 mục và 16 cấp). Không xử lý symlink, tên giống file bí mật hoặc metadata Git. Nếu filesystem thay đổi đồng thời, thao tác có thể xóa được một phần.
- `git_branches`: xem nhánh cục bộ và nhánh hiện tại (chỉ đọc). `git_stage` / `git_unstage`: thêm hoặc bỏ stage từng file. `git_commit`: commit với message và danh tính tác giả; `git_branch_create` / `git_branch_switch`: quản lý nhánh cục bộ. Các lệnh quản lý này vô hiệu hóa hooks và ký commit.
- `git_push`: chỉ push nhánh đang checkout lên remote `origin` HTTPS `github.com`, không force. Push cần bật quyền riêng và token GitHub được lưu ở Agent, bên ngoài workspace.

## Khai báo nhiều workspace trên Agent

`KRW_WORKSPACE_ROOT` hiện tại tiếp tục được dùng với tên `default`. Muốn thêm workspace, thiết lập biến môi trường trước khi chạy lại bộ cài:

```bash
export KRW_WORKSPACES_JSON='{"rails":"/content/my-rails-app","docs":"/content/project-docs"}'
bash /tmp/krw-setup.sh
```

Từng đường dẫn phải là thư mục tuyệt đối đã tồn tại và được chủ thiết bị cấp quyền. Bộ cài giữ lại danh sách trong các lần nâng cấp sau. Khi gọi công cụ, dùng `workspace_id="rails"` hoặc `workspace_id="docs"`. Workspace chưa đăng ký sẽ bị từ chối.

## Phân quyền

Ghi file/thư mục vẫn dùng `KRW_WRITE_ENABLED=1` tại Render và `KRW_ALLOW_FILE_WRITES=1` tại Agent.

Git write có quyền riêng: `KRW_GIT_WRITES_ENABLED=1` trên Render và `KRW_ALLOW_GIT_WRITES=1` trên Agent. Git push cần thêm `KRW_GIT_PUSH_ENABLED=1` và `KRW_ALLOW_GIT_PUSH=1`, cùng `KRW_GIT_PUSH_TOKEN` riêng tại Agent. Token này không lấy từ phiên OAuth ChatGPT.

Mặc định toàn bộ Git write đều TẮT. Repository phải có thư mục `.git` thực sự bên trong workspace; chưa hỗ trợ Git worktree trỏ metadata ra ngoài. Tránh áp dụng trên repository không tin cậy có Git filter tùy biến. Không có Git reset, force push hay arbitrary shell.

## Quy trình phát hành

Yêu cầu regression PASS trên Python 3.10 và 3.13. Deploy Gateway, dừng rồi nâng cấp Agent bằng bộ cài đã xác minh. Refresh danh sách MCP tools trong ChatGPT. Chỉ chạy smoke test thư mục và Git trên dự án thử nghiệm; không thử push vào repository production.
