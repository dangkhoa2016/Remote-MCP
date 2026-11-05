# Changelog

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/CHANGELOG.vi.md)

This project follows semantic versioning for **public source releases**. Development milestones are not separately published versions.

## [1.0.0] — 2026-11-07

First public release of **Remote-MCP**.

- OAuth-protected MCP Gateway with login and device administration.
- Independently enrolled outbound-only Agents with per-device approval and revocation.
- Controlled file, directory and Git operations within authorized workspaces.
- Managed test tasks and asynchronous, opt-in CLI execution with bounded logs.
- English and Vietnamese documentation, deployment guidance, and regression testing on Python 3.10 and 3.13.

Deployment owners must configure their own credentials, permissions and durable device-enrollment storage. This release does not distribute device tokens or a shared public API service.

[1.0.0]: https://github.com/dangkhoa2016/Remote-MCP/releases/tag/v1.0.0
