# Khoa Remote Workspace Phase 3.1 — Đăng nhập username/password

## Mục tiêu

Không dùng Auth0 hay dịch vụ định danh bên ngoài. Một tài khoản cục bộ với username/password để kết nối ChatGPT vào MCP Server qua Cloudflare Tunnel. **ChatGPT không hỗ trợ HTTP Basic trực tiếp cho custom MCP**, vì thế lớp đăng nhập cục bộ vẫn phải giao tiếp với ChatGPT qua OAuth Authorization Code + PKCE. Đây chỉ là giao thức phiên đăng nhập; người sử dụng chỉ nhập username/password.

**Giới hạn an toàn:** Bản này chỉ hỗ trợ đọc thiết bị; `execute_command` bị khóa cứng dù gọi có token. Không nên coi đây là identity provider production hoặc mở quyền terminal tùy ý. Mật khẩu hash bằng scrypt; khóa ký JWT và secret lưu trong `.env.dev` trên máy, không gửi vào chat/GitHub.

## 1. Cập nhật mã nguồn hiện có

Bạn đang có Relay và Agent hoạt động trên Codespaces `codespaces-04576f` với project `/workspaces/khoa-remote-workspace-phase2`. **Không tạo lại `.env.dev`**, không xóa Agent/Relay. Trước tiên dừng terminal MCP (Ctrl+C), giữ nguyên Relay và Agent.

Tải ZIP `khoa-remote-workspace-phase3-local-login.zip` lên Codespaces, sau đó:

```bash
cd /workspaces/khoa-remote-workspace-phase2
cp gateway/server.py /tmp/krw-server-before-local-login.py
python3 -m zipfile -e /path/to/khoa-remote-workspace-phase3-local-login.zip .
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Đổi `/path/to/...` thành đường dẫn thật của ZIP. Gói không chứa `.env.dev`, credential hoặc OAuth database. `run_relay.sh` và `run_agent.sh` không cần chạy lại khi chúng đang online.

## 2. Lấy OAuth callback URI từ ChatGPT

Vào [ChatGPT Plugins](https://chatgpt.com/plugins) → **Thêm server MCP tùy chỉnh**. Nhập URL Cloudflare đang hoạt động, chọn xác thực **OAuth** và xem callback/redirect URI mà ChatGPT hiển thị cho plugin. Chọn chế độ **OAuth credentials cố định / static Client ID và Client Secret** thay vì DCR/CIMD nếu có lựa chọn. Sao chép **chính xác callback URL**. Chưa cần hoàn tất tạo plugin ở bước này.

Trong ví dụ dưới đây, các giá trị callback chỉ là minh họa; **không được tự đoán callback URL**.

## 3. Tạo tài khoản cục bộ và OAuth client

Chạy trên Codespaces:

```bash
cd /workspaces/khoa-remote-workspace-phase2
.venv/bin/python scripts/setup_local_login.py \
  --mcp-url 'https://outline-worm-orange-violation.trycloudflare.com/mcp' \
  --redirect-uri 'DAN_CHINH_XAC_CHATGPT_CALLBACK_URL_VAO_DAY' \
  --username 'krwadmin'
```

Script yêu cầu nhập mật khẩu mới ít nhất 16 ký tự qua input ẩn, rồi xác nhận lại. Script không lưu mật khẩu thô; nó tự cập nhật `.env.dev`, giữ lại `KRW_AGENT_TOKEN`, `KRW_CONTROL_TOKEN` và các cấu hình Phase 2 khác; đồng thời sinh các khóa ngẫu nhiên. Nếu đã từng chạy setup, script từ chối ghi đè credential. Không chia sẻ nội dung `.env.dev` trong chat.

Trong `.env.dev`, bạn có thể đọc **tại máy** những giá trị sau để nhập vào cấu hình plugin ChatGPT:

- `KRW_OAUTH_CLIENT_ID` — OAuth Client ID cố định.
- `KRW_OAUTH_CLIENT_SECRET` — Client Secret cố định.

Chúng **khác với** username/password dùng để đăng nhập và chỉ cấu hình một lần. Nếu ChatGPT yêu cầu URL của authorization server, dùng hostname Cloudflare hiện tại; authorization endpoint là `/authorize`, token endpoint là `/token`, metadata tự phục vụ tại `/.well-known/oauth-authorization-server`. Scope là `krw:read`.

**Quan trọng:** không chọn `No authentication`. Trên plugin cần chọn OAuth với Client ID/Secret tĩnh; phiên đăng nhập sẽ mở trang `Khoa Remote Workspace` để bạn nhập username/password.

## 4. Chạy Gateway và kiểm tra HTTP

```bash
./scripts/run_mcp.sh
```

Một lệnh chạy hai tiến trình nội bộ: `:8765` là frontend công khai qua Cloudflare, `:8767` là MCP backend chỉ localhost. Tunnel hiện có phải trỏ tới **`http://127.0.0.1:8765`**, không phải `:8767` hoặc Relay `:8766`.

Từ terminal thứ hai:

```bash
curl -sS 'https://outline-worm-orange-violation.trycloudflare.com/.well-known/oauth-authorization-server' | python3 -m json.tool
curl -i 'https://outline-worm-orange-violation.trycloudflare.com/mcp' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}'
```

**Kỳ vọng** metadata trả 200, còn POST `/mcp` khi không có access token phải trả **401**, không được trả 200. Chỉ sau khi nhận 401 và đăng nhập thành công qua ChatGPT mới chuyển qua bước 5.

## 5. Kết nối ChatGPT và mở quyền đọc

Cấu hình/cài đặt plugin qua HTTPS MCP URL hiện tại. ChatGPT chuyển hướng đến trang đăng nhập của Gateway. Đăng nhập bằng username `krwadmin` (hoặc username bạn chọn) và mật khẩu vừa đặt. Sau đó thử `health_check` và `list_capabilities`. Mặc định kết quả vẫn `mode=locked`: đây là chủ đích.

Sau khi thực sự xác minh plugin chỉ cho phép truy cập sau OAuth, và `scripts/check_devices.py` vẫn cho thấy `local-dev` online, bạn có thể đổi duy nhất `KRW_MCP_TOOLS_ENABLED=1` ở `.env.dev` và restart **MCP** để đọc file, xem thiết bị. Chỉ bật trên workspace thử nghiệm không có bí mật. `execute_command` vẫn luôn bị khóa ở mã nguồn, ngay cả khi `KRW_COMMANDS_ENABLED=1`.

## 6. Khi Quick Tunnel cấp URL mới

Dừng MCP, rồi cập nhật hostname (không đổi username/password):

```bash
.venv/bin/python scripts/update_cloudflare_host.py \
  --mcp-url 'https://HOST_MOI.trycloudflare.com/mcp'
```

Script cập nhật `.env.dev` và thu hồi các login code/refresh token lưu trong DB mặc định. Nếu đã chỉnh `KRW_AUTH_DB_PATH` thì phải chủ động thu hồi ở DB đó. Restart MCP, cập nhật URL ChatGPT plugin và đăng nhập lại. **Cloudflare Named Tunnel hostname cố định** thuận tiện hơn vì không phải lặp lại việc này.

## 7. Bảo mật và giới hạn

- Gateway chạy cả authorization server và resource server trên cùng một máy. Đây là một triển khai OAuth nhỏ cho một chủ tài khoản, **chưa trải qua kiểm toán bảo mật độc lập**, không có 2FA hay cơ chế chặn tấn công quy mô lớn.
- Đăng nhập sai bị giới hạn số lần theo cửa sổ thời gian (toàn cục, có thể gây khóa tạm thời). Authorization code chỉ dùng một lần; PKCE S256 là bắt buộc. Access token có hạn 15 phút, refresh token 7 ngày và được xoay vòng khi sử dụng.
- `KRW_MCP_TOOLS_ENABLED=0` theo mặc định; không có quyền thực thi lệnh. Chỉ thiết lập lại `1` sau khi toàn bộ OAuth và phạm vi thư mục được kiểm thử end-to-end.
- Không commit `.env.dev`, `.krw-local-state/` hoặc token. Trong quá trình chẩn đoán chỉ chia sẻ HTTP status/metadata không chứa secret.
- **Đã PASS LIVE (2026-11-02):** ChatGPT custom MCP OAuth và các công cụ `health_check`, `list_capabilities`, `list_devices`, `get_device_info`, `list_directory`, `read_file` trên Codespaces. Vẫn chưa production-ready; quyền terminal bị khóa cứng.
- **Phase 4-A:** tạm vô hiệu hóa hai script legacy `agent_quick_tunnel.sh` và `run_ingress.sh` do xung đột cổng `8767` với backend MCP riêng tư. Chỉ tunnel MCP frontend `127.0.0.1:8765`. CSRF/OAuth và ingress đa mạng cần được audit kỹ hơn trước khi mở rộng.

## 8. Sự cố

- `Invalid Host header`: hostname trong `KRW_MCP_PUBLIC_URL`/`KRW_MCP_PUBLIC_HOST` chưa khớp hostname Cloudflare mới.
- `invalid_client`: Client ID/Secret trong ChatGPT không đúng với `.env.dev`.
- `invalid_request`: callback, resource, scope, hoặc PKCE không trùng với cấu hình.
- `401` khi chưa login là đúng; nếu đã login mà vẫn 401, kiểm tra token audience/issuer/clock, URL Cloudflare và trạng thái phiên đăng nhập.
- `503 local MCP backend unavailable`: kiểm tra terminal của `./scripts/run_mcp.sh` và port `8767`.
- ChatGPT không có chế độ điền Client ID/Secret tĩnh hoặc không chấp nhận callback đã cấu hình: phải dừng và điều chỉnh phương án tương thích, không tắt OAuth cho công cụ đọc thiết bị.
