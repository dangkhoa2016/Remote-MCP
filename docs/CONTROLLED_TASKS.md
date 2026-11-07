# Controlled workspace tasks

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/CONTROLLED_TASKS.vi.md)

The Agent can run a small set of explicitly authorized tasks within a selected workspace:

| Task ID | Operation |
| --- | --- |
| `git_status` | Sanitized Git status |
| `git_log` | Bounded commit log |
| `pytest` | Python tests |
| `rspec` | Ruby RSpec |
| `rails_test` | Rails tests |

`list_tasks(device_id, workspace_id="default")` lists available task IDs. `run_task(device_id, task_id, target="", workspace_id="default")` runs a known task; the optional target must be a validated test path. This runner does not accept custom command lines or arbitrary shell flags.

Gateway flags: `KRW_TASKS_ENABLED`, `KRW_TEST_TASKS_ENABLED`. Agent flags: `KRW_ALLOW_TASKS`, `KRW_ALLOW_TEST_TASKS`. Both sides must permit the operation. Existing installations retain their saved settings; fresh installations may use enabled defaults.

Short tasks have a **15-second** timeout and bounded output. Python/Ruby test code executes with OS-user privileges, **not in a sandbox**. Use only trusted source code in isolated environments without valuable credentials. The legacy `execute_command` endpoint remains disabled; separately authorized `run_cli` / `run_shell` have different execution limits.

For longer tests see [background test jobs](BACKGROUND_TEST_JOBS.md); for CLI execution consult [README](../README.md).
