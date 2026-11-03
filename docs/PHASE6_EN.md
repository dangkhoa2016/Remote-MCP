# Phase 6 — Named workspaces, directory management and Git (v0.7.0)

Phase 6 expands the outbound-only Agent without enabling arbitrary remote shell execution.

## New MCP tools

- `list_workspaces(device_id)` lists roots explicitly configured on the device.
- Existing file, directory and Git read actions accept optional `workspace_id` (defaults to `default`, preserving Phase 5 behavior).
- `move_directory` renames a directory within the selected workspace, with no intentional destination overwrite.
- `delete_directory` removes an empty directory; `recursive=true` is explicit for non-empty directories (up to 1,000 entries, 16 levels). The operation refuses symlinks, secret-like names and Git metadata. A concurrent filesystem change may result in partial deletion.
- `git_stage` stages one file at a time; `git_commit` requires a message and author identity; `git_branch_create` and `git_branch_switch` manage local branches. Hooks and signing are disabled for the managed Git commands.
- `git_push` pushes only the currently checked-out branch to a credential-free HTTPS `github.com` origin, without force. Push requires additional opt-in and a GitHub token stored only on the Agent, outside the authorized workspace.

## Configure additional workspaces (Agent)

The existing `KRW_WORKSPACE_ROOT` remains the `default`. To add project roots, set an environment variable before reinstalling/upgrading:

```bash
export KRW_WORKSPACES_JSON='{"rails":"/content/my-rails-app","docs":"/content/project-docs"}'
bash /tmp/krw-setup.sh
```

The paths must already exist, be absolute directories, and be individually authorized by the Agent owner. The installer preserves this mapping on subsequent upgrades. Calls for other workspaces must pass `workspace_id="rails"` or `workspace_id="docs"`; other values are denied.

## Permission settings

File and directory changes continue to use `KRW_WRITE_ENABLED=1` on Render and `KRW_ALLOW_FILE_WRITES=1` on the Agent.

Git writes are *independent*: enable `KRW_GIT_WRITES_ENABLED=1` on Render **and** `KRW_ALLOW_GIT_WRITES=1` on the Agent. Git push additionally requires `KRW_GIT_PUSH_ENABLED=1` and `KRW_ALLOW_GIT_PUSH=1`, plus a private `KRW_GIT_PUSH_TOKEN` on the Agent. Git push does not use or expose your ChatGPT OAuth session.

All Git writes are OFF by default. Git repositories must have an actual in-workspace `.git` directory; Git worktree pointers are not supported. Avoid using untrusted repositories with custom Git filters. No Git reset, force push or arbitrary shell is exposed.

## Release procedure

Require regression PASS on Python 3.10 and 3.13. Deploy the Gateway, then stop and update the Agent with the verified installer. Refresh the MCP tools in ChatGPT. Run the directory and Git smoke tests only on a disposable project. Never test Git push against a production repository.
