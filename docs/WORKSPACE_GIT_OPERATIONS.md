# Named workspaces and Git operations

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/WORKSPACE_GIT_OPERATIONS.vi.md)

Remote-MCP 1.0.0 supports multiple independently authorized workspace roots, safe directory operations and Git actions.

## Named workspaces

`KRW_WORKSPACE_ROOT` is the `default` workspace. Additional roots are specified by `KRW_WORKSPACES_JSON` with absolute, existing, distinct paths:

```bash
export KRW_WORKSPACES_JSON='{"rails":"/content/my-rails-app","docs":"/content/project-docs"}'
```

Workspace roots may not overlap. `list_workspaces(device_id)` lists configured roots; file/Git calls use `workspace_id` when a non-default workspace is intended.

## Directory and Git permissions

`move_directory` and `delete_directory` are scoped to the selected workspace; recursive deletion must be explicit and is bounded. Symlink and protected-name checks apply.

Git read actions include branch listing, status, diffs, logs, fetch and pull. Git write actions include stage, unstage, commit, branch creation/switching and push. Git writes require `KRW_GIT_WRITES_ENABLED=1` on Gateway and `KRW_ALLOW_GIT_WRITES=1` on Agent. Push requires separate Gateway/Agent opt-ins and Agent-local GitHub credentials.

`git_pull` requires a clean working tree and fast-forward history. `git_push` does not force-push by default. CLI tools have their **own** permissions and may run arbitrary Git commands; do not mistake CLI authorization for a Git-specific sandbox.

Switching branches protects tracked/staged changes and untracked path collisions; non-conflicting untracked files can be retained. Existing repositories and Git hooks/filters require normal operator caution.

Use only trusted repositories. See [file operations](FILE_OPERATIONS.md), [README](../README.md), and [deployment](../DEPLOY.md).
