# Hướng dẫn deploy Khoa Remote Workspace lên Northflank

Ngày: 2026-11-02. Phạm vi: **deployment test**, không khẳng định production security. Không build lại các phần Phase 3.1/4-A đã PASS.

## 0. Chốt kiến trúc

- Một Northflank Combined Service, 1 instance; public port **8765**, Docker app bind `0.0.0.0:8765`.
- Bên trong container, Gateway OAuth `8765`, MCP backend `127.0.0.1:8767`, Relay `127.0.0.1:8766`.
- Có route `/v1/agent/{register|poll|result}` trên gateway public; các route khác thuộc Relay control **không** public.
- SQLite `/data/krw/oauth.sqlite` trên **Single Read/Write** Persistent Volume. Đừng dùng Multi Read/Write cho SQLite.
- Codespaces chạy Device Agent, kết nối ra HTTPS; không copy workspace hoặc Agent tokens vào Docker image.

## 1. Tạo mã deployment *riêng* trên Codespaces

Tải và giải nén ZIP kit vào `/tmp/krw-northflank-kit`. Trên Codespaces:

```bash
python3 /tmp/krw-northflank-kit/prepare_deploy_tree.py \
  --source /workspaces/khoa-remote-workspace-phase2 \
  --dest /workspaces/krw-northflank-release-20261102
cd /workspaces/krw-northflank-release-20261102
/workspaces/khoa-remote-workspace-phase2/.venv/bin/python -m pytest -q
```

Đòi hỏi PASS toàn bộ tests. Preparer sẽ dừng nếu source khác Phase 4-A hoặc dest đã tồn tại. Không dùng ZIP Phase 2/3 để overwrite bản live.

## 2. GitHub private repository

Tạo repository **private** mới tên `khoa-remote-workspace` trên GitHub, không chọn khởi tạo README. Trong thư mục deployment vừa tạo:

```bash
git init -b main
git add .
git status --short
# Kiểm tra không có .env*, .krw-local-state, *.sqlite*, token hay thông tin thật.
git commit -m "Prepare isolated Northflank deployment for Khoa Remote Workspace"
GITHUB_USER=dangkhoa2016  # sửa nếu tên GitHub của bạn khác
git remote add origin "git@github.com:${GITHUB_USER}/khoa-remote-workspace.git"
git push -u origin main
```

Dùng SSH remote nếu Codespaces đã được cấu hình. Không đưa file `.env.dev` lên GitHub, kể cả repository private.

## 3. Northflank Project, Combined Service

Mở https://app.northflank.com/ → kết nối GitHub và cho phép repo private → tạo Project `khoa-remote-workspace`, chọn region Asia Southeast nếu có.

Create New → Service → **Combined**, service name `krw-gateway`, repo `khoa-remote-workspace`, branch `main`, **Dockerfile** ở root, build context root.

Resources: chọn mức có đủ RAM cho ba Python processes (thử 1 GiB, tăng lên nếu có OOM). **Instances=1**.

Configure → Networking: một cổng **8765 / HTTP / Public**. Dockerfile chỉ EXPOSE 8765; không tạo public ports 8766/8767. Northflank tự TLS trên cổng public.

## 4. Persistent Volume

Trong Service → Volumes → Add volume:

- Name `krw-oauth-state`
- Mode **Single Read/Write**
- Mount path `/data/krw`
- Size: mức nhỏ nhất UI cho phép và phù hợp quota

Một instance, không horizontal scale. Runtime container phải ghi được `/data/krw`; image sử dụng uid/gid `10001:10001`. Nếu startup báo volume không writable, sửa ownership/mount theo Northflank UI rồi thử lại. Volume là bắt buộc vì script chỉ xác minh đường dẫn writable; không tự nhận biết loại storage.

## 5. Tạo domain trước khi kiểm tra OAuth public

Dùng `mcp.dangkhoa.dev` **chỉ nếu bạn sở hữu và đã cấu hình domain này**, hoặc một subdomain khác do bạn quản lý. Northflank → Domains: add domain, tạo TXT verification và CNAME theo giá trị Northflank cung cấp. Sau đó Service → Configure → Networking → gắn custom domain vào port 8765. **Không tự đoán DNS record**.

Lý do: local OAuth config yêu cầu hostname công khai chính xác, và TrustedHost sẽ chặn Host khác. Northflank-generated `*.code.run` chưa chắc dùng được khi service đang cấu hình `mcp.dangkhoa.dev`.

## 6. Runtime environment/secrets (KHÔNG paste vào chat)

Chỉ copy từng giá trị cần thiết từ `.env.dev` đang chạy vào Northflank Runtime Environment/Secret Group, không phải build args:

```
KRW_OAUTH_ENABLED=1
KRW_MCP_TOOLS_ENABLED=1
KRW_COMMANDS_ENABLED=0
KRW_RELAY_URL=http://127.0.0.1:8766
KRW_MCP_PUBLIC_URL=https://mcp.dangkhoa.dev/mcp
KRW_MCP_PUBLIC_HOST=mcp.dangkhoa.dev
KRW_AUTH_DB_PATH=/data/krw/oauth.sqlite
```

Sử dụng giá trị thật từ `.env.dev` cho các mục dưới đây (GIỮ BÍ MẬT):

```
KRW_LOGIN_USERNAME
KRW_LOGIN_PASSWORD_HASH
KRW_LOGIN_SALT
KRW_OAUTH_CLIENT_ID
KRW_OAUTH_CLIENT_SECRET
KRW_OAUTH_SIGNING_KEY
KRW_OAUTH_REDIRECT_URI
KRW_CONTROL_TOKEN
KRW_DEVICE_TOKENS_JSON
```

Callback URI phải khớp chính xác URI của plugin ChatGPT cho connection mới. Nếu plugin mới có callback URI khác, chỉ cập nhật `KRW_OAUTH_REDIRECT_URI` cho instance Northflank, không reset toàn bộ tài khoản.

Không nhập `KRW_WORKSPACE_ROOT` hoặc `KRW_AGENT_TOKEN` vào Northflank Gateway. Các biến đó chỉ thuộc Agent trên Codespaces. Không đổi `KRW_AGENT_TOKEN` hiện dùng trừ khi chủ động rotate cùng `KRW_DEVICE_TOKENS_JSON`.

## 7. Deploy và kiểm tra public endpoints

Northflank sẽ build từ branch `main`. Nên cấu hình health check TCP port **8765** trước (không phụ thuộc Host header khi chưa gắn domain). Kiểm tra container logs thấy cả ba server chạy; startup sẽ fail nếu secrets hoặc volume thiếu.

Chạy từ Codespaces (thay domain nếu khác):

```bash
HOST='https://mcp.dangkhoa.dev'
curl -fsS "$HOST/.well-known/oauth-authorization-server"
curl -fsS "$HOST/health"
curl -sS -o /dev/null -w 'MCP unauthenticated HTTP %{http_code}\n' \
  "$HOST/mcp" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
curl -sS -o /dev/null -w 'Control endpoint HTTP %{http_code}\n' "$HOST/v1/control/devices"
```

Kỳ vọng metadata 200; health 200; MCP không token **401**; `/v1/control/devices` **404**. Nếu `Host header` HTTP 400, kiểm tra domain `KRW_MCP_PUBLIC_URL` và DNS. Chạy `python scripts/check_mcp_discovery.py` trong Northflank service shell để thử MCP có token nội bộ (không in token).

## 8. Chuyển Agent trên Codespaces, không sửa .env.dev gốc

Chỉ sau khi gateway kiểm tra thành công: dừng terminal Agent cũ bằng Ctrl+C, rồi ở terminal mới:

```bash
cd /workspaces/khoa-remote-workspace-phase2
set -a
source .env.dev
set +a
KRW_COMMANDS_ENABLED=0 KRW_RELAY_URL='https://mcp.dangkhoa.dev' \
  .venv/bin/python -m agent.agent
```

Không thêm `/mcp` cuối URL của Agent; Agent cần POST `/v1/agent/register`, `/poll`, `/result`. Quan sát log `registered device=local-dev` và Northflank logs, sau đó từ Northflank console chạy `python scripts/check_devices.py`, phải `online:true`.

Nếu lỗi, Ctrl+C Agent mới và chạy `./scripts/run_agent.sh` để quay lại relay cũ. Không cần thay đổi token.

## 9. Plugin ChatGPT

Khi Agent online trên Northflank, đổi URL MCP plugin thành `https://mcp.dangkhoa.dev/mcp` nếu UI hỗ trợ. Nếu không thể sửa, tạo plugin mới để test, nhưng **giữ plugin cũ** tới khi mới PASS. Đăng nhập qua OAuth theo username/password hiện tại, kiểm tra `health_check`, `list_devices`, `read_file`. Không tạo lại credential nếu callback cũ vẫn chính xác.

## 10. Hạn chế và rollback

- Không kết luận production-ready từ test local. Vẫn phải audit OAuth Origin:null, refresh rotation, brute-force, symlink/TOCTOU và cross-host security.
- Service có Single R/W Volume chỉ chạy một instance, và khi redeploy có khoảng dừng do pod cũ phải ngừng trước pod mới.
- SQLite WAL cần xác minh locking/shared-memory trên loại volume thực tế; thử restart và kiểm tra tính toàn vẹn rồi mới tin cậy. Backup dùng SQLite Online Backup API hoặc snapshot nhất quán; đừng chỉ copy file `.sqlite` khi đang WAL.
- Không bật terminal/write_file. Hai scripts ingress legacy Phase 4-A trên Codespaces vẫn fail-closed.
- Rollback về Agent cũ bằng `./scripts/run_agent.sh` và giữ nguyên Northflank thử nghiệm tách biệt; không tác động bản Phase 3.1 local đang chạy.
