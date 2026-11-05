# Phase 8 — Managed long-running test tasks (v0.9.0)

Phase 8 adds bounded, **Agent-local asynchronous test jobs**. MCP requests return without waiting for test completion, while the Agent continues its outbound-only HTTPS polling. No inbound listener, arbitrary shell, Git mutation or force push is added.

## MCP operations

| Tool | Meaning |
| --- | --- |
| `start_long_task(device_id, task_id, target="", workspace_id="default")` | Queue an approved test and return `job_id` |
| `get_long_task(device_id, job_id, workspace_id="default")` | Read `queued`, `running`, or terminal status |
| `read_long_task_log(device_id, job_id, offset=0, max_bytes=4096, workspace_id="default")` | Read partial combined stdout/stderr; continue with `next_offset` |
| `cancel_long_task(device_id, job_id, workspace_id="default")` | Cancel a queued test or request process-group termination |

Only `pytest`, `rspec` and `rails_test` are eligible for Phase 8. Targets use exactly the Phase 7 validated test-file rules, and the command argv is fixed. `git_status` / `git_log` remain available as normal short Phase 7 tasks, not as long jobs. Test source **executes with Agent OS-user privileges**; this feature is **not a sandbox**.

A job belongs to its selected workspace. A job ID cannot be read or cancelled via another workspace ID. Jobs contain no secret configuration values, but **the test program can print sensitive data that its OS account can access**. Use only trusted test code in disposable, unprivileged, network-limited environments without credentials or private data.

## Bounded execution & lifecycle

- **One running job per Agent**, maximum **two pending**, shared across all configured workspaces.
- **180-second wall-clock timeout** per running job. Timeout terminates its POSIX process group. Longer suites require a future explicit limit change and additional resource review.
- Maximum combined stdout+stderr stored: **256 KiB**. Exceeding it terminates the job. Each log request returns up to **8 KiB**.
- Accepted job IDs: random 128-bit lowercase hex. Job IDs are scoped to a workspace and cannot select arbitrary PIDs.
- Statuses: `queued`, `running`, `succeeded`, `failed`, `cancelled`, `timed_out`, `output_limit`. A cancellation request may return while a process is still terminating; poll status to confirm.
- At most **12 job records** in Agent memory, with completed jobs expiring after **one hour** when new jobs are submitted. Full history returns an explicit error.
- Agent `SIGINT`/`SIGTERM` shutdown attempts to cancel active and pending jobs. Jobs and logs are **not persisted** across Agent restarts, process crashes or Colab resets. A force kill/crash is not guaranteed to terminate external grandchildren.

The normal MCP command execution tool `execute_command` stays **disabled**. The short `run_task` remains available with its own 15-second limit.

## Opt-in setup

Keep the Phase 7 opt-ins. On Render Gateway:

```env
KRW_TASKS_ENABLED=1
KRW_TEST_TASKS_ENABLED=1
KRW_LONG_TASKS_ENABLED=1
```

On Colab Agent, stop the old Agent first, then:

```bash
export KRW_ALLOW_TASKS=1
export KRW_ALLOW_TEST_TASKS=1
export KRW_ALLOW_LONG_TASKS=1
curl -fsSLo /tmp/krw-setup.sh https://remote-mcp-ka1p.onrender.com/setup.sh
bash -n /tmp/krw-setup.sh
bash /tmp/krw-setup.sh
```

The installer preserves previous device secrets and configured workspaces in the owner-only `agent.env`. All **new** long-task opt-in flags default to `0`. Disabling either side prevents new commands and control calls. Review deployment configuration before enabling, and preferably disable long-test execution after test runs.

## Sample end-to-end verification

Use an isolated `secondary` workspace containing `tests/test_phase8_smoke.py` with a trivial pytest function. Run `list_workspaces` and `list_tasks` first, then:

1. `start_long_task(device_id="local-dev", task_id="pytest", target="tests/test_phase8_smoke.py", workspace_id="secondary")`
2. Copy the returned `job_id`.
3. Poll `get_long_task(...)` until `succeeded` or another terminal state.
4. Fetch `read_long_task_log(..., offset=0)`; use the returned `next_offset` to read remaining output.
5. For cancellation, queue a separate trusted **deliberately slow** test and invoke `cancel_long_task`, then poll until `cancelled`. Avoid cancel-testing any real production task.

Use **CI evidence plus real Agent tests** before claiming end-to-end success. Installing code and merging a PR do not deploy the active Render service or restart a Colab Agent.

Related guides: [Phase 7](PHASE7_EN.md), [README](../README.md).
