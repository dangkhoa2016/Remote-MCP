# Remote-MCP 1.0.0 — Release readiness

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/RELEASE_READINESS.vi.md)

**First intended public release: 1.0.0.** No separate 0.x product releases are part of this release history. Development milestones are not release tags.

## Verified in the current source review

- The Remote-MCP Git history is organized into 14 feature and documentation commits with add-only file changes.
- Full Python regression: 209 tests passed in the most recent acceptance run.
- The login/Devices frontend and authorized Agent tools were tested on the connected infrastructure.
- GitHub main is the delivery source; a code push alone does not prove Render has deployed the same revision.

## Remaining production checks

- [ ] Confirm GitHub Actions passes on every supported Python version (3.10 and 3.13).
- [ ] Confirm the live Gateway health reports version **1.0.0** after deployment.
- [ ] Verify authenticated login and Devices workflows in the live UI.
- [ ] Verify two or more real Agents can connect independently, and can reconnect after an Agent restart without new pairing.
- [ ] Validate OAuth and enrollment SQLite persistence through a controlled Gateway replacement and consistent backup/restore.
- [ ] Verify revocation and security boundaries in an isolated test environment.
- [ ] Ensure the Git tag `v1.0.0` points to the reviewed first-release source commit.

## Operational cautions

- A running Agent may reconnect after network errors, but an expired Colab runtime will not restart itself.
- In-flight Relay jobs and queues are in memory and are not guaranteed to survive Gateway restart.
- Render needs a genuine persistent mount for database durability; a writable directory alone does not suffice.
- Tests and CLI commands execute source code and are **not** OS sandboxes.
- Do not interrupt production services simply to complete checklist items.
