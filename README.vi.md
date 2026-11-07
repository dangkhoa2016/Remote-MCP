# Remote-MCP — MCP Gateway cho workspace được cấp quyền

🌐 Ngôn ngữ / Language: [English](https://github.com/dangkhoa2016/Remote-MCP/blob/main/README.md) | **Tiếng Việt**

Dự án MCP Gateway bảo vệ bằng OAuth, triển khai trên Render và kết nối Agent qua HTTPS theo chiều đi ra. Gateway chỉ mở cổng HTTPS cho OAuth và MCP; MCP backend và Agent Relay chỉ nghe localhost trong container Render.

[![CI](https://github.com/dangkhoa2016/Remote-MCP/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/dangkhoa2016/Remote-MCP/actions/workflows/ci.yml) [![Release](https://img.shields.io/badge/release-v1.0.0-2563EB)](https://github.com/dangkhoa2016/Remote-MCP/releases/tag/v1.0.0) [![License: MIT](https://img.shields.io/badge/license-MIT-16A34A)](LICENSE) [![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.13-3776AB?logo=python&logoColor=white)](.github/workflows/ci.yml)
[![MCP](https://img.shields.io/badge/MCP-Gateway-0F766E)](README.md) [![Auth](https://img.shields.io/badge/auth-OAuth%20%2B%20PKCE-6D28D9)](docs/README.md) [![Render](https://img.shields.io/badge/deploy-Render-111827)](DEPLOY.md) [![Agents](https://img.shields.io/badge/Agents-outbound--only-475569)](docs/AGENT_BOOTSTRAP.md)


**Phiên bản phát hành đầu tiên: 1.0.0.** Remote-MCP bao gồm đăng nhập OAuth, phê duyệt thiết bị, thao tác workspace/Git có kiểm soát, chạy test, CLI bất đồng bộ, giao diện quản trị responsive và chẩn đoán HTTP. Các chức năng được phát triển trước lần phát hành này đều thuộc 1.0.0, không phải các phiên bản phát hành riêng. Kiểm tra phiên bản Gateway đang chạy bằng `health_check` và cập nhật Agent độc lập.

## Kết nối Agent (Linux / Google Colab)

Nên tải và kiểm tra script trước khi chạy. Thay `https://gateway.example.com` bằng HTTPS origin của **Gateway do bạn triển khai**; đây chỉ là ví dụ:

```bash
export REMOTE_MCP_GATEWAY_URL="https://gateway.example.com"
curl -fsSLo setup.sh "$REMOTE_MCP_GATEWAY_URL/setup.sh"
bash -n setup.sh
less setup.sh
bash setup.sh
```

Khi đã tin cậy máy chủ, có thể cài bằng một lệnh:

```bash
wget -qO- "$REMOTE_MCP_GATEWAY_URL/setup.sh" | bash
```

Khi bật đăng ký thiết bị, lần cài đầu Agent tự tạo Device ID và secret riêng; admin duyệt mã ghép nối một lần lấy từ terminal máy. Vẫn cần thư mục workspace riêng. Các Agent cũ tiếp tục dùng ID/token đã lưu. Không chọn `/content`, thư mục HOME hoặc thư mục chứa secrets. Token được lưu **bên ngoài workspace** tại `~/.config/krw-agent/agent.env` với quyền `0600`. Để chạy lại dùng `~/.local/share/krw-agent/start.sh`. Gói Agent được xác minh SHA-256 trước khi cài.

## Khả năng của hệ thống

- Xem thông tin thiết bị, liệt kê thư mục và đọc file UTF-8 trong workspace được cấp quyền.
- Đọc Git status, diff từng file và lịch sử commit trong Git repository thật nằm bên trong workspace.
- An toàn workspace có `file_sha256`, `write_file` (tối đa 1 MiB) và `check_syntax` (Python, JSON, TOML) không thực thi mã dự án.
- Thao tác file gồm `edit_file`, `search_files`, `create_directory`, `move_file`, `delete_file`; đọc tối đa 256 KiB mỗi lần, hỗ trợ dotfile thông thường và file nguồn UTF-8 không có phần mở rộng.
- Workspace và Git hỗ trợ `list_workspaces` và tham số `workspace_id` tùy chọn, `move_directory`, `delete_directory`, `git_branches`, `git_stage`, `git_unstage`, `git_commit`, `git_branch_create`, `git_branch_switch`, `git_push`.
- Cách ly workspace cho phép chuyển nhánh khi file untracked không xung đột, vẫn bảo vệ thay đổi tracked/staged; từ chối cấu hình nhiều workspace có thư mục gốc trùng hoặc lồng nhau.
- Tác vụ kiểm soát gồm `list_tasks` và `run_task` với các ID cố định `git_status`, `git_log`, `pytest`, `rspec`, `rails_test` trong workspace được chọn, cho phép chỉ định file test hợp lệ.
- Tác vụ test bất đồng bộ gồm `start_long_task`, `get_long_task`, `read_long_task_log`, `cancel_long_task` cho các bài test được duyệt. Mỗi Agent chỉ chạy một task, chờ tối đa hai; timeout 180 giây, log tối đa 256 KiB. Trạng thái task chỉ lưu tạm trong Agent và tách biệt theo workspace.
- Đăng ký thiết bị: secret 256-bit riêng từng máy, ghép nối phải phê duyệt, SQLite chỉ lưu hash và thu hồi độc lập. Xem [ghép nối thiết bị](docs/DEVICE_ENROLLMENT.vi.md). Ghép nối bằng trình duyệt: mở trang `/devices` trên Gateway của bạn, đăng nhập với tài khoản Gateway cũ, nhập mã trên terminal để duyệt, không cần Render Shell.
- `execute_command` cũ vẫn bị khóa. Git write, Git push và chạy test có quyền bật riêng. Các công cụ `run_cli` và `run_shell` cho phép thực thi lệnh tùy ý khi cả Gateway và Agent cấp quyền riêng; đây không phải OS sandbox. Công cụ Git push được quản lý không force-push. **Test task thực thi mã dự án và không phải sandbox cấp OS**.

Muốn ghi file/thư mục cần bật quyền **cả trên Render và Agent** (`KRW_WRITE_ENABLED=1`, `KRW_ALLOW_FILE_WRITES=1`). Git write có quyền độc lập (`KRW_GIT_WRITES_ENABLED=1`, `KRW_ALLOW_GIT_WRITES=1`); push cần bật thêm quyền và token tại Agent. Runner có quyền riêng: `KRW_TASKS_ENABLED` / `KRW_TEST_TASKS_ENABLED` (Render), `KRW_ALLOW_TASKS` / `KRW_ALLOW_TEST_TASKS` (Agent). Background test jobs cần bật thêm `KRW_LONG_TASKS_ENABLED` (Render) và `KRW_ALLOW_LONG_TASKS` (Agent); cần kiểm tra quyền ở cả hai phía; Gateway có cấu hình độc lập và cài Agent mới có thể dùng quyền mặc định đã bật. Xem [background test jobs](docs/BACKGROUND_TEST_JOBS.vi.md) về cài đặt, bảo mật và vòng đời task.

## Triển khai và kiểm chứng

Docker service dùng cổng public `8765` cho OAuth/MCP, cổng localhost `8766` cho Relay và `8767` cho MCP backend. SQLite của OAuth lưu trên persistent disk tại `/data/krw/oauth.sqlite`. Không commit mật khẩu, token, file cấu hình riêng hoặc SQLite.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
python3 -m compileall -q agent gateway
bash -n gateway/setup.sh
```

Tài liệu: [triển khai](DEPLOY.vi.md), [cài Agent](docs/AGENT_BOOTSTRAP.vi.md), [workspace safety](docs/WORKSPACE_SAFETY.vi.md), [file operations](docs/FILE_OPERATIONS.vi.md), [workspace and Git operations](docs/WORKSPACE_GIT_OPERATIONS.vi.md), [controlled tasks](docs/CONTROLLED_TASKS.vi.md), [background test jobs](docs/BACKGROUND_TEST_JOBS.vi.md). Hệ thống hiện chạy trên Render; xem tài liệu triển khai hiện hành.

## Đồng bộ Git qua MCP
Hai công cụ `git_fetch(device_id)` và `git_pull(device_id, branch="main")` hoạt động trên repository trong workspace được cấp quyền. Remote `origin` hỗ trợ HTTPS, HTTPS có token, `git@github.com:OWNER/REPO.git` và `ssh://git@github.com/OWNER/REPO.git`. Git chỉ nhận URL HTTPS GitHub đã loại bỏ credentials; token được cấp qua HTTP header giới hạn theo host. Vẫn chặn host không phải GitHub, HTTP, cổng tùy biến, helper, redirect và URL rewrite.

Với GitHub private repository, xác thực **trên tài khoản hệ điều hành của Agent** theo thứ tự ưu tiên: `KRW_GIT_PUSH_TOKEN` (tương thích cũ), `KRW_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, token đã có trong HTTPS remote hoặc GitHub CLI đã đăng nhập (`gh auth login`; Agent gọi `gh auth token --hostname github.com`). Nên dùng token riêng của Agent hoặc `gh`, vì token trong URL sẽ nằm trong `.git/config`. Fetch/pull cần quyền đọc repository; push cần quyền ghi và MCP push đã cấp phép.

`git_status` giờ hiển thị thư mục chưa được Git theo dõi nếu tên thư mục an toàn (ví dụ `?? benchmarks/`), đồng thời trả thêm `working_tree_clean` và `hidden_changes`. Tên đường dẫn nhạy cảm và symlink vẫn bị che giấu; `entries` rỗng **không có nghĩa** working tree sạch. `git_pull` tiếp tục từ chối mọi thay đổi chưa được xử lý, kể cả mục bị ẩn.

`git_fetch` chỉ cập nhật `origin/*`. `git_pull` yêu cầu working tree hoàn toàn sạch, kể cả file chưa track, và chỉ fast-forward; không merge commit, rebase hoặc force. Khi lịch sử phân nhánh, MCP trả lỗi cụ thể `Pull rejected: divergent history; fast-forward is not possible`; lỗi xác thực hoặc mạng vẫn sử dụng thông báo chung đã lọc, không để lộ stderr hoặc thông tin xác thực. Repository `git init` chưa có commit có thể checkout `origin/main`. **Redeploy Render không tự cập nhật Agent đang chạy trên Colab**: cần cập nhật mã Agent bằng setup hiện có rồi restart, giữ nguyên Device ID và pairing.

**Cài Agent mới** sẽ mặc định bật quyền ghi file, kiểm tra cú pháp, Git write/push, task, test task và long task. Các quyền này cho phép thao tác mã nguồn và chạy test của dự án, nên chỉ dùng workspace đáng tin cậy. Shell tùy ý vẫn **tắt**; push vẫn cần token và quyền Gateway riêng. Người dùng có thể đặt biến `KRW_ALLOW_*=0` để tắt. **Agent đã cài** giữ nguyên các cờ đã lưu sau khi chạy installer lại; để bật quyền của Agent cũ, truyền các biến `KRW_ALLOW_*=1` khi chạy installer. Device ID và secret cũ không bị thay đổi. Các quyền Gateway phía Render là lớp kiểm soát độc lập.

Để nâng cấp Agent cũ từng lưu quyền tắt, chạy lại installer với **`KRW_ENABLE_DEFAULT_PERMISSIONS=1`** (chỉ một biến môi trường). Giữ nguyên Device ID và secret đã được duyệt; tùy chọn `KRW_ALLOW_GIT_PUSH=0` hoặc các cờ từ chối khác truyền trực tiếp sẽ luôn được ưu tiên.

## Sẵn sàng phát hành

Trước khi gắn tag stable, xem [checklist phát hành tiếng Việt](docs/RELEASE_READINESS.vi.md). Test tự động multi-device và reconnect không thay thế nghiệm thu ít nhất hai Agent thật và restart Gateway có kiểm soát.

## Chạy CLI/Bash khi đã cấp quyền

**Mặc định TẮT.** Bật `KRW_CLI_ENABLED=1` trên Render Gateway, chạy lại installer Agent với `KRW_ALLOW_CLI=1`, sau đó khởi động lại Agent. Cả hai quyền phải được bật độc lập. Agent đã cài giữ quyền trong `agent.env`. Tùy chọn `KRW_ENABLE_DEFAULT_PERMISSIONS=1` **không tự bật** chạy CLI tùy ý.

Sử dụng `run_cli(device_id, argv, workspace_id="default")` và `run_shell(device_id, script, workspace_id="default")`:

```text
run_cli(device_id, ["python3", "script.py"])
run_cli(device_id, ["node", "app.js"])
run_cli(device_id, ["ruby", "script.rb"])
run_cli(device_id, ["bash", "setup.sh"])
run_shell(device_id, "pwd && ls -la")
```

**Bảo mật:** Các công cụ trên chạy mã tùy ý bằng quyền tài khoản OS của Agent. Chỉ giới hạn thư mục làm việc (cwd), **KHÔNG tạo OS sandbox**; tiến trình có thể truy cập các đường dẫn khác mà user OS có quyền. Chỉ sử dụng trong Colab/container cách ly và với mã tin cậy. Không có terminal tương tác hay stdin; timeout tối đa 300 giây qua background job, giới hạn output. Môi trường HOME/PATH tạm không tự truyền token Agent, vì vậy CLI bên ngoài có xác thực cần cấu hình credential riêng. Chưa hỗ trợ CLI tương tác; các lệnh không tương tác được chạy tối đa 5 phút. Công cụ `execute_command(command_id)` cũ vẫn bị khóa.


## CLI 5 phút và lỗi mất enrollment sau redeploy

`run_cli` / `run_shell` hiện trả về `job_id` ngay, cho phép tiến trình chạy đến **300 giây** mà không chặn HTTPS polling. Sử dụng `get_cli_job(device_id, job_id)`, `read_cli_log(device_id, job_id, offset=0)` và `cancel_cli_job(device_id, job_id)` để kiểm tra trạng thái, đọc log và hủy job. Job được lưu tạm trong RAM của Agent; khi tiến trình Agent dừng, job sẽ bị hủy. Timeout riêng của test runner 15 giây không thay đổi.

**Giao diện đăng nhập và chẩn đoán:** Trang `/authorize` và `/devices` sử dụng giao diện responsive đồng nhất. Username được loại bỏ toàn bộ Unicode whitespace (gồm xuống dòng CR/LF và tab) ở Python; JavaScript cũng tự làm sạch khi nhập/gửi form. **Không chuẩn hóa password.** Nonce một lần, CSRF, Origin, PKCE, cookie và giới hạn đăng nhập vẫn được bảo vệ. Mỗi request tới MCP frontend có header `X-KRW-Request-ID`; bật `KRW_MCP_LOG_PROTOCOL_ERRORS=1` để ghi log lỗi HTTP đã lọc gồm nguồn lỗi, status, loại phương thức và request ID (không ghi token, nội dung lệnh hoặc thông tin xác thực). Yêu cầu bị chặn từ lớp phía trước sẽ không có log trong frontend. Lịch sử CLI/test giữ tối đa 12 bản ghi; khi đầy chỉ xóa bản ghi đã kết thúc cũ nhất, không xóa job đang chạy/chờ; bản ghi đã kết thúc cũng hết hạn sau một giờ và được dọn khi tạo job mới. **Cần triển khai Gateway và cập nhật Agent** tương ứng để có hiệu lực.

**Lỗi mất trạng thái cấp quyền:** database SQLite lưu enrollment phải nằm trên Render persistent disk. Docker image tạo sẵn `/data/krw`, vì vậy thư mục tồn tại/ghi được **không chứng minh** đã mount disk. `list_capabilities` giờ báo `enrollment_separate_mount_detected` và `relay_uptime_seconds`. Nếu không thấy mount riêng và danh sách Agent đã duyệt biến mất sau redeploy, cần sửa storage chứ không liên tục phê duyệt lại.

Trong Render Dashboard, mở dịch vụ → **Disk** → gắn persistent disk tại **`/data/krw`** và xác minh `KRW_AUTH_DB_PATH=/data/krw/oauth.sqlite`, `KRW_DEVICE_DB_PATH=/data/krw/devices.sqlite` (hoặc tên file enrollment thực tế đang cấu hình). Redeploy sau khi gắn disk, rồi phê duyệt Agent một lần. Khi disk đã được gắn, có thể đặt `KRW_REQUIRE_PERSISTENT_ENROLLMENT_DISK=1` để từ chối khởi động nếu không thấy mount riêng. Đừng đổi token hoặc Device ID khi không cần.

Persistent disk của Render cần gói dịch vụ hỗ trợ; sau khi có disk, redeploy có thể gây gián đoạn ngắn nhưng SQLite sẽ được lưu bền vững. Không có persistent disk thì phải pairing lại sau khi container mới được tạo.

## Cộng đồng và giấy phép

[Đóng góp](CONTRIBUTING.md) · [Quy tắc ứng xử](.github/CODE_OF_CONDUCT.md) · [Bảo mật](SECURITY.md) · [Hỗ trợ](.github/SUPPORT.md) · [Lịch sử phát hành](CHANGELOG.md) · [Gửi issue](https://github.com/dangkhoa2016/Remote-MCP/issues/new/choose)

Mã nguồn và tài liệu gốc của dự án được cấp phép theo [MIT License](LICENSE). Các thư viện bên thứ ba tuân theo giấy phép riêng.

**Tác giả duy trì:** Đăng Khoa <i.am@dangkhoa.dev>.
