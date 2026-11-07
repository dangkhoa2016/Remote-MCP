# Device enrollment and browser approval

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/DEVICE_ENROLLMENT.vi.md)

Remote-MCP supports independently enrolled Agents. Each new Agent generates a persistent device ID and a cryptographically random 256-bit credential. The Gateway stores only a digest of enrolled credentials in SQLite.

## Enrollment

1. Start the verified Agent installer on a trusted Linux/Colab machine with a dedicated workspace.
2. Read the one-time pairing code shown **only on the Agent terminal**.
3. Open the `/devices` page of your Gateway, sign in and approve the matching device.
4. Keep the saved identity in `~/.config/krw-agent/agent.env` (mode 0600), **outside the exposed workspace**. Restart with `~/.local/share/krw-agent/start.sh`.

Pairing codes expire after ten minutes; failed attempts and pending requests are bounded. Revocation blocks future authenticated polling. A Colab reset that loses the saved credential creates a new identity requiring new approval.

## Settings and storage

Gateway settings include `KRW_DEVICE_ENROLLMENT_ENABLED=1`, `KRW_DEVICE_ADMIN_TOOLS_ENABLED=1` and a protected `KRW_DEVICE_DB_PATH`. Do not expose control endpoints or stored credentials. Pairing SQLite and OAuth state require persistent storage across redeploys; a writable Docker-image directory alone does **not** prove persistence.

The browser login uses secure session cookies, CSRF and same-origin validation. A valid authenticated owner and the one-time code are required to approve a device. Never paste credentials, pairing codes or database files into issues or the repository.

## Local verification

`python scripts/device_enrollment_staging_smoke.py` starts isolated local Gateway/Agent simulations to test registration, approval, routing and revocation without contacting production. The real production reconnect and storage durability still require separate verification.

See [Agent bootstrap](AGENT_BOOTSTRAP.md), [README](../README.md) and [release readiness](RELEASE_READINESS.md).
