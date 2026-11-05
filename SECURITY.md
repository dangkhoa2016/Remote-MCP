# Security policy

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/SECURITY.vi.md)

Remote-MCP grants controlled access to authorized device workspaces. Misconfiguration can expose credentials, source files, or remote execution capabilities.

## Supported version

The first public source release is **1.0.0**. Security review and maintenance apply to the current maintained release; no earlier 0.x versions were published as standalone releases.

## Reporting vulnerabilities

**Do not disclose vulnerabilities, access tokens, pairing codes, or credentials in a public GitHub issue.** Contact the maintainer privately at **Đăng Khoa <i.am@dangkhoa.dev>**, including a sanitized reproduction and impact summary. Avoid accessing or disclosing data belonging to other users.

## Deployment precautions

- Treat Agent CLI execution as arbitrary OS-level code execution, **not** an operating-system sandbox.
- Enable Gateway and Agent permissions independently, on trusted hosts only.
- Keep authentication, device-enrollment, and OAuth databases on suitable persistent storage.
- Never commit passwords, OAuth signing keys, pairing credentials, tokens or environment files.
- Do not publicly expose the loopback-bound Relay or MCP backend ports.
- Review all deployment-specific hostnames, OAuth callback URLs and permissions before use.

The [deployment guide](DEPLOY.md), [Vietnamese deployment guide](DEPLOY.vi.md), and [release-readiness checklist](docs/RELEASE_READINESS.md) provide additional checks. Passing CI does not constitute a security certification.
