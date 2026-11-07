# Background test jobs

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/BACKGROUND_TEST_JOBS.vi.md)

For authorized test suites that exceed the short task window, Remote-MCP offers asynchronous Agent-local jobs while the Agent continues outbound polling.

| Operation | Purpose |
| --- | --- |
| `start_long_task` | Queue an approved test and return its `job_id` |
| `get_long_task` | Inspect queued/running/finished state |
| `read_long_task_log` | Read bounded log chunks |
| `cancel_long_task` | Request cancellation |

Only `pytest`, `rspec` and `rails_test` are eligible. Test targets follow the same validation rules as controlled tasks; command lines remain fixed. Job IDs are workspace-scoped.

Limits: one active job, up to two queued, **180-second** timeout, **256 KiB** combined output limit, and up to 12 in-memory records. Completed results expire after an hour when new jobs are submitted. Job state does not survive Agent restarts. Cancellation of an active job is asynchronous; poll to confirm terminal state.

Permissions: keep controlled-task flags enabled and also set `KRW_LONG_TASKS_ENABLED=1` on Gateway and `KRW_ALLOW_LONG_TASKS=1` on Agent. Verify both settings. All task code executes with Agent OS-user privileges; this is **not an OS sandbox**.

Example: `start_long_task(device_id, task_id="pytest", target="tests/test_safe.py", workspace_id="default")`, then poll `get_long_task` and retrieve `read_long_task_log`.

See [controlled tasks](CONTROLLED_TASKS.md) and [README](../README.md).
