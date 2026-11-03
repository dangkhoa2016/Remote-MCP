# Agent Bootstrap (Render)

Installer: https://remote-mcp-ka1p.onrender.com/setup.sh

Safer: curl -fsSLo setup.sh https://remote-mcp-ka1p.onrender.com/setup.sh ; inspect the file, then run bash setup.sh.

One command on a trusted host: curl -fsSL https://remote-mcp-ka1p.onrender.com/setup.sh | bash

wget alternative: wget -qO- https://remote-mcp-ka1p.onrender.com/setup.sh | bash

Interactive installer asks for device ID, existing absolute workspace path and device token (hidden input). Token must already exist in KRW_DEVICE_TOKENS_JSON on Render. Credentials are saved outside the authorized workspace at ~/.config/krw-agent/agent.env (0600); source and Python environment at ~/.local/share/krw-agent. To reconnect: ~/.local/share/krw-agent/start.sh .

SHA-256 verifies the downloaded, allowlisted Agent bundle. The runner forces KRW_COMMANDS_ENABLED=0. Colab sleep/reset still disconnects the device. Do not include device tokens in URL or Git, and review downloaded scripts before execution.
