# Nhiều workspace và thao tác Git

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/WORKSPACE_GIT_OPERATIONS.md) | **Tiếng Việt**

Remote-MCP 1.0.0 hỗ trợ nhiều workspace được cấp quyền độc lập, quản lý thư mục an toàn và thao tác Git.

## Khai báo workspace

`KRW_WORKSPACE_ROOT` là workspace `default`. Các workspace khác được khai báo bằng `KRW_WORKSPACES_JSON`, sử dụng đường dẫn tuyệt đối, có sẵn và không chồng lấn:

```bash
export KRW_WORKSPACES_JSON='{"rails":"/content/my-rails-app","docs":"/content/project-docs"}'
```

`list_workspaces(device_id)` liệt kê các workspace. Lệnh file/Git nhận `workspace_id` khi sử dụng workspace khác `default`.

## Thư mục và quyền Git

`move_directory`, `delete_directory` chỉ hoạt động trong workspace đã chọn. Xóa đệ quy cần xác nhận riêng và có giới hạn; chặn symlink và tên được bảo vệ.

Git có các công cụ đọc branch, status, diff, log, fetch/pull và các công cụ ghi stage, unstage, commit, tạo/chuyển branch, push. Ghi Git cần `KRW_GIT_WRITES_ENABLED=1` trên Gateway và `KRW_ALLOW_GIT_WRITES=1` trên Agent; push cần quyền riêng tại hai nơi và credentials GitHub cục bộ của Agent.

`git_pull` chỉ fast-forward khi working tree sạch. `git_push` không force mặc định. CLI có quyền **riêng**, có thể chạy lệnh Git tùy ý và không phải sandbox chỉ dành cho Git.

Chuyển branch bảo vệ thay đổi tracked/staged và xung đột với file untracked; file untracked không xung đột có thể được giữ nguyên. Chỉ sử dụng repository đáng tin cậy.

Xem [thao tác file](FILE_OPERATIONS.vi.md), [README](../README.vi.md) và [triển khai](../DEPLOY.vi.md).
