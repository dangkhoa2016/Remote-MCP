# Khoa Remote Workspace — triển khai Northflank

Gói này chuẩn bị bản triển khai từ **mã Phase 4-A đã kiểm thử**, không thay đổi workspace Codespaces đang chạy. Giữ đăng nhập username/password và SQLite; **không** bật lệnh terminal tùy ý hoặc ghi file.

- Một cổng public HTTPS `8765`: OAuth, MCP và API Agent giới hạn `register`, `poll`, `result`.
- MCP backend `8767` và Relay `8766` chỉ nghe localhost trong container.
- SQLite tại `/data/krw/oauth.sqlite` trên Persistent Volume Single Read/Write.
- Mọi token và khóa chỉ nhập vào Runtime Secrets của Northflank; không commit `.env.dev`, database, patch, hay bản backup.

Đọc `DEPLOY_VI.md` để biết các bước chi tiết. `prepare_deploy_tree.py` tạo **thư mục triển khai riêng** và giữ nguyên mã live. Phải chạy test trước khi đưa lên Northflank.

## Chuẩn bị (trên Codespaces)

```bash
python3 /tmp/krw-northflank-kit/prepare_deploy_tree.py \
  --source /workspaces/khoa-remote-workspace-phase2 \
  --dest /workspaces/krw-northflank-release-20261102
cd /workspaces/krw-northflank-release-20261102
/workspaces/khoa-remote-workspace-phase2/.venv/bin/python -m pytest -q
```

Sau đó làm theo `DEPLOY_VI.md`, cấu hình secrets và volume, kiểm tra HTTP rồi mới chuyển Agent từ Codespaces.
