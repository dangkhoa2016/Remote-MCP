# Phase 7 — Controlled workspace tasks (v0.8.0)

Phase 7 adds a **fixed-task runner**, not an arbitrary command execution API. OAuth, device authentication, per-workspace authorization and the outbound-only Agent architecture remain in place.

## Tools and supported tasks

- `list_tasks(device_id, workspace_id="default")`: list fixed tasks and whether the Agent permits them.
- `run_task(device_id, task_id, target="", workspace_id="default")`: run one fixed task in the selected authorized workspace.

| Task ID | Operation | Extra permission |
| --- | --- | --- |
| `git_status` | Sanitized read-only Git status | Tasks |
| `git_log` | Sanitized last 10 commit records | Tasks |
| `pytest` | `pytest -q --disable-warnings` (or Agent Python `-m pytest`) | Tasks + test tasks |
| `rspec` | `bundle exec rspec --format progress` | Tasks + test tasks |
| `rails_test` | `bundle exec rails test` | Tasks + test tasks |

The optional `target` must be a real, non-symlink test file: Python `.py` under `test/` or `tests/`, RSpec `.rb` under `spec/`, Rails `.rb` under `test/`. Omit `target` to run the corresponding test suite. No custom shell, flags, environment, command chaining, Git push or mutation of Git refs is accepted by this tool.

The legacy `execute_command` MCP action **remains disabled**, regardless of the task settings. Existing Git stage/commit/push tools use their separate Phase 6 permissions.

## Explicit permissions (both sides)

On **Render Gateway** set these environment variables, then deploy/restart:

```env
KRW_TASKS_ENABLED=1
KRW_TEST_TASKS_ENABLED=1
```

On **Agent / Colab**, stop the Agent and enable permissions by exporting them before running the verified installer:

```bash
export KRW_ALLOW_TASKS=1
export KRW_ALLOW_TEST_TASKS=1
curl -fsSLo /tmp/krw-setup.sh https://remote-mcp-ka1p.onrender.com/setup.sh
bash -n /tmp/krw-setup.sh
bash /tmp/krw-setup.sh
```

The installer preserves these settings in owner-only `~/.config/krw-agent/agent.env` (mode 0600). To disable again, set both Render flags to `0` and disable the Agent flags before restarting. Default is **disabled** on both sides.

## Runtime controls and limitations

- Fixed argv; never `shell=True` and never evaluate an arbitrary command string.
- The Agent selects installed test executables from a restricted PATH, with an Agent-Python fallback for pytest. Ruby/Bundler/test dependencies must already be installed on the device.
- Runner timeout: **15 seconds**, within the relay request budget. Long suites need an explicitly designed queued/asynchronous task architecture in a future release.
- Captured stdout/stderr: **16 KiB each**, with a **1 MiB combined output budget**; excessive output terminates the process group.
- A new POSIX process group is used for timeouts and basic CPU/file-size limits are applied.
- Environment is minimized; the Agent token and GitHub push token are not passed to the subprocess. The runner reports exit status and bounded output.

**Security boundary:** test tasks execute repository code (including imports, Ruby initialization, framework hooks, plugins and subprocesses). The task runner **is not an operating-system sandbox**. Code can still access files and networks permitted to the Agent OS user; minimized environment and process limits do not stop a determined malicious test. Use only trusted source code, preferably in a separate disposable container, unprivileged OS account and network-restricted environment without secrets. Never enable test tasks against arbitrary user-submitted repositories.

## Verification and rollout

1. Run the regression suite on Python 3.10 and 3.13, check the installer and bundle allowlist, and merge only after PASS.
2. Deploy Gateway v0.8.0 and verify with `health_check`.
3. Stop/update/restart the Agent, then refresh ChatGPT MCP tool discovery.
4. Confirm `list_tasks` returns exactly five IDs and the expected enabled flags.
5. On an isolated test workspace, run `git_status` and a tiny `pytest` fixture; check output and timeout handling.
6. Keep legacy `execute_command` unavailable. Do **not** test on the user's production Ruby/Rails project.

Documentation: [main README](../README.md) and [Phase 6](PHASE6_EN.md).
