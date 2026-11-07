# Remote-MCP — Secure MCP Gateway for authorized workspaces

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/README.vi.md)

A private OAuth-protected MCP Gateway hosted on Render, with outbound-only device Agents. The Gateway and OAuth frontend use public HTTPS; the MCP backend and Agent Relay remain bound to localhost inside the Render container.

[![CI](https://github.com/dangkhoa2016/Remote-MCP/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/dangkhoa2016/Remote-MCP/actions/workflows/ci.yml) [![Release](https://img.shields.io/badge/release-v1.0.0-2563EB)](https://github.com/dangkhoa2016/Remote-MCP/releases/tag/v1.0.0) [![License: MIT](https://img.shields.io/badge/license-MIT-16A34A)](LICENSE) [![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.13-3776AB?logo=python&logoColor=white)](.github/workflows/ci.yml)
[![MCP](https://img.shields.io/badge/MCP-Gateway-0F766E)](README.md) [![Auth](https://img.shields.io/badge/auth-OAuth%20%2B%20PKCE-6D28D9)](docs/README.md) [![Render](https://img.shields.io/badge/deploy-Render-111827)](DEPLOY.md) [![Agents](https://img.shields.io/badge/Agents-outbound--only-475569)](docs/AGENT_BOOTSTRAP.md)


**First release: 1.0.0.** Remote-MCP includes OAuth sign-in, device approval, managed workspace and Git operations, controlled tests, asynchronous CLI jobs, responsive administration, and HTTP diagnostics. Features developed before this release are included in 1.0.0; they were not separately published releases. Confirm the version of the running Gateway with `health_check` and update Agent installations independently.

## Connect an Agent (Linux / Google Colab)

Download and review the installer before running it. Replace `https://gateway.example.com` with the HTTPS origin of **your own Gateway**; the example is not a running service:

```bash
export REMOTE_MCP_GATEWAY_URL="https://gateway.example.com"
curl -fsSLo setup.sh "$REMOTE_MCP_GATEWAY_URL/setup.sh"
bash -n setup.sh
less setup.sh
bash setup.sh
```

For a trusted server, the equivalent one-liner is:

```bash
wget -qO- "$REMOTE_MCP_GATEWAY_URL/setup.sh" | bash
```

When enrollment is enabled, the first installation generates its own Device ID and secret; an authenticated administrator approves the one-time terminal pairing code. A dedicated workspace directory is still required. Legacy Agents continue using their configured credentials. Never use `/content`, `$HOME`, or a directory containing secrets as the workspace. The token is stored outside the workspace at `~/.config/krw-agent/agent.env` (mode 0600). Restart later using `~/.local/share/krw-agent/start.sh`. Agent source archives are SHA-256 verified before installation.

## Available capabilities

- Read device information, list permitted workspace directories, and read UTF-8 source files.
- Read-only Git status, per-file diff and commit log on a real in-workspace Git repository.
- Workspace safety: `file_sha256`, `write_file` (up to 1 MiB), and non-executing `check_syntax` for Python, JSON and TOML.
- File operations: `edit_file`, `search_files`, `create_directory`, `move_file` and `delete_file`. Read up to 256 KiB per call; normal dotfiles and extensionless UTF-8 source files are supported.
- Workspace and Git operations: `list_workspaces` and optional `workspace_id` on existing file/Git actions, `move_directory`, `delete_directory`, `git_branches`, `git_stage`, `git_unstage`, `git_commit`, `git_branch_create`, `git_branch_switch`, and `git_push`.
- Workspace isolation: `git_branch_switch` preserves safe untracked files but refuses tracked/staged changes and untracked collisions; named workspace roots must not overlap or alias each other.
- Controlled tasks: `list_tasks` and `run_task` support fixed IDs `git_status`, `git_log`, `pytest`, `rspec`, `rails_test` in a selected workspace with an optional validated test-file target.
- Background test jobs: `start_long_task`, `get_long_task`, `read_long_task_log` and `cancel_long_task` for approved test commands. One active/two queued per Agent; max 180 seconds and 256 KiB combined logs. Results are ephemeral and workspace-scoped.
- Per-device enrollment: 256-bit secrets, time-limited approval, SQLite hashed credentials and independent revocation. See [device enrollment](docs/DEVICE_ENROLLMENT.md). Browser pairing: open the `/devices` page on your Gateway, sign in using the existing Gateway username/password, and approve each new Agent with its terminal code—no Render Shell.
- Legacy `execute_command` stays disabled. Git write, Git push and test execution have separate opt-in permissions. Optional `run_cli` and `run_shell` can execute arbitrary commands when explicitly permitted on both Gateway and Agent; this is not an OS sandbox. The managed Git push tool does not force-push. Test tasks **execute project code and are not an OS sandbox**.

File and directory writes require *both* Render and Agent flags (`KRW_WRITE_ENABLED=1` and `KRW_ALLOW_FILE_WRITES=1`). Git writes have separate flags (`KRW_GIT_WRITES_ENABLED=1`, `KRW_ALLOW_GIT_WRITES=1`), while push requires additional opt-in and an Agent-side token. Task runner settings are separately configured using `KRW_TASKS_ENABLED` / `KRW_TEST_TASKS_ENABLED` (Render), and `KRW_ALLOW_TASKS` / `KRW_ALLOW_TEST_TASKS` (Agent). Background test jobs require additional `KRW_LONG_TASKS_ENABLED` (Render) and `KRW_ALLOW_LONG_TASKS` (Agent), the Gateway setting remains independent; Agent defaults depend on its installation configuration. Read [background test jobs](docs/BACKGROUND_TEST_JOBS.md) for setup, safety and lifecycle constraints.

## Deployment & verification

The existing Docker deployment uses public port `8765` for OAuth and MCP; loopback Relay `8766` and MCP backend `8767`. OAuth SQLite persists at `/data/krw/oauth.sqlite`. Credentials belong only in runtime environment settings or private Agent configuration; never commit credentials or SQLite.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
python3 -m compileall -q agent gateway
bash -n gateway/setup.sh
```

Further details: [Deployment guide](DEPLOY.md), [Agent bootstrap](docs/AGENT_BOOTSTRAP.md), [workspace safety](docs/WORKSPACE_SAFETY.md), [file operations](docs/FILE_OPERATIONS.md), [workspace and Git operations](docs/WORKSPACE_GIT_OPERATIONS.md), [controlled tasks](docs/CONTROLLED_TASKS.md), [background test jobs](docs/BACKGROUND_TEST_JOBS.md). The current deployment runs on Render; refer to the deployment guide for this setup.

## Git synchronization
`git_fetch(device_id)` and `git_pull(device_id, branch="main")` operate in authorized workspace repositories. The GitHub origin may use HTTPS, HTTPS with an existing token, `git@github.com:OWNER/REPO.git`, or `ssh://git@github.com/OWNER/REPO.git`. Git operations use only a canonical credential-free HTTPS URL, with optional host-scoped auth header. Non-GitHub hosts, HTTP, custom ports, external helpers, redirects and URL rewrites remain blocked.

Private GitHub repositories are authenticated **on the Agent OS account**, in precedence order: `KRW_GIT_PUSH_TOKEN` (legacy), `KRW_GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_TOKEN`, an existing HTTPS origin token, or authenticated GitHub CLI (`gh auth login`; Agent runs `gh auth token --hostname github.com`). Prefer Agent-local credentials or `gh` over token-in-URL: the latter leaves secrets in `.git/config`. Fetch/pull need repository read permission; push requires write permission plus independent MCP push authorization.

`git_status` now includes safe untracked directory entries (e.g. `?? benchmarks/`) and returns `working_tree_clean` plus `hidden_changes` flags; restricted names and symlinks remain hidden. An empty `entries` array alone does **not** establish a clean tree. `git_pull` still rejects any non-clean worktree, including hidden/untracked changes.

`git_fetch` updates `origin/*` tracking refs only. `git_pull` requires a clean working tree including untracked files, and only fast-forwards (no merge commits, rebase, or force). A divergent history now returns `Pull rejected: divergent history; fast-forward is not possible`, while authentication/network failures retain a sanitized generic error. Git stderr and credentials are never returned. Fresh `git init` repositories may perform an initial checkout of `origin/main`. **Redeploying Render does not upgrade an existing Colab Agent**: update the Agent source with its installed setup mechanism and restart the Agent while preserving device ID/enrollment.

A **fresh Agent installation** now defaults file writes, static checks, Git writes/push, controlled tasks, test tasks and long tasks to ON. This grants meaningful control over the chosen workspace, including execution of project tests; only use trusted notebooks/projects. Arbitrary shell execution remains OFF and Git push still needs a separately configured token and Gateway permission. Any explicit `KRW_ALLOW_*=0` setting is respected. Existing Agents keep their saved permission settings on upgrade: for an existing Agent that has disabled flags, rerun the installer with explicitly set environment variables to enable them. Existing device ID/secret are preserved. Gateway opt-in flags remain independent and are not changed by setup.

To upgrade an existing Agent that saved disabled permissions, rerun the installer with `KRW_ENABLE_DEFAULT_PERMISSIONS=1` (one environment variable). This enables all default privileges while preserving the same approved Device ID and token. An explicit `KRW_ALLOW_GIT_PUSH=0` or other per-flag override still takes precedence.

## Release readiness

Before tagging a stable release, follow the [English release-readiness checklist](docs/RELEASE_READINESS.md). Automated multi-device and reconnect regressions do not replace simultaneous testing with two real Agents or a controlled Gateway restart.

## Opt-in CLI and shell execution

**Off by default.** Set `KRW_CLI_ENABLED=1` in the Render Gateway environment and `KRW_ALLOW_CLI=1` in the Agent installation environment, then restart the Agent. Both independently controlled permissions must be enabled. Existing Agents keep the CLI setting in their saved `agent.env`; rerun `setup.sh` with `KRW_ALLOW_CLI=1` to enable it. `KRW_ENABLE_DEFAULT_PERMISSIONS=1` intentionally does **not** enable arbitrary CLI.

Run commands on one selected device with `run_cli(device_id, argv, workspace_id="default")` or `run_shell(device_id, script, workspace_id="default")`.

```text
run_cli(device_id, ["python3", "script.py"])
run_cli(device_id, ["node", "app.js"])
run_cli(device_id, ["ruby", "script.rb"])
run_cli(device_id, ["bash", "setup.sh"])
run_shell(device_id, "pwd && ls -la")
```

**Security:** These tools execute arbitrary code as the Agent OS account. CWD is scoped to the selected workspace but **is NOT an OS sandbox**, and child processes may access other filesystem paths accessible to that account. Use a dedicated isolated Colab/container without sensitive data and only trusted code. Commands run without a TTY or stdin, have a 300-second asynchronous job timeout and bounded output. An isolated temporary HOME/PATH environment avoids inheriting Agent tokens, but also means external authenticated CLI tools may need separately provisioned credentials. Interactive CLI sessions are not supported in this release. The old `execute_command(command_id)` tool remains disabled.


## CLI jobs and durable enrollment

`run_cli` and `run_shell` now **return a job ID immediately**. CLI jobs run for up to **300 seconds**, do not block the Agent HTTPS polling loop, and are managed with `get_cli_job(device_id, job_id)`, `read_cli_log(device_id, job_id, offset=0)`, and `cancel_cli_job(device_id, job_id)`. Output is bounded; jobs are ephemeral and are cancelled when the Agent process shuts down. The old 15-second controlled test runner retains its own limits.

**Login UI and diagnostics:** `/authorize` and `/devices` share a responsive design. Username fields remove all Unicode whitespace (including CR/LF and tabs) in the Python handler; JavaScript also removes whitespace while typing/submitting. **Passwords are never normalized.** One-time nonce, CSRF, Origin, PKCE, cookies and rate limits remain enforced. Each `/mcp` frontend request has an `X-KRW-Request-ID` response header; set `KRW_MCP_LOG_PROTOCOL_ERRORS=1` to log sanitized HTTP error source, status, method category and request ID (no token, raw request, CLI arguments or credentials). A request rejected upstream cannot be traced by the frontend. Agent CLI/test history retains at most 12 records; when full, completed jobs are evicted oldest first while queued/running jobs are preserved; completed history also expires after an hour upon subsequent job submissions. **Gateway and Agent updates are required** for respective changes to take effect.

**Important: persistent device approvals.** The Gateway's SQLite enrollment database must be stored on a Render persistent disk. The Docker image creates `/data/krw` as a regular writable directory, so a startup check for directory existence alone cannot guarantee persistence. Live `list_capabilities` provides `enrollment_separate_mount_detected` and `relay_uptime_seconds`. A false mount detection accompanied by disappearing registered devices after a deploy indicates an ephemeral database; re-approving devices does not fix the underlying issue.

In Render Dashboard, open the service's **Disk** page, attach a paid persistent disk at **`/data/krw`**, and confirm the environment paths `KRW_AUTH_DB_PATH=/data/krw/oauth.sqlite` and `KRW_DEVICE_DB_PATH=/data/krw/devices.sqlite` (use the actual configured enrollment filename if different). Once the disk has been attached, redeploy and approve each device one final time. To enforce storage presence on subsequent startups, set `KRW_REQUIRE_PERSISTENT_ENROLLMENT_DISK=1`. This opt-in makes startup fail if a separate mount is not detected; enable it only after the disk is attached. Do not change or rotate Agent tokens unnecessarily.

Render disk attachments prevent zero-downtime deploys, but preserve data across deployments. If you intentionally run without persistent storage, pairing must be repeated after each fresh Gateway container, and the service cannot be considered production-stable.

## Community and license

[Contributing](CONTRIBUTING.md) · [Code of conduct](.github/CODE_OF_CONDUCT.md) · [Security](SECURITY.md) · [Support](.github/SUPPORT.md) · [Changelog](CHANGELOG.md) · [Report an issue](https://github.com/dangkhoa2016/Remote-MCP/issues/new/choose)

The project's original source code and documentation are released under the [MIT License](LICENSE). Third-party dependencies remain subject to their own licenses.

**Maintainer:** Đăng Khoa <i.am@dangkhoa.dev>.
