#!/usr/bin/env bash
# Fail closed: must never expose the previous OAuth schema MCP backend as an agent ingress.
set -euo pipefail
echo 'DISABLED: legacy tunnel targets :8767 (private MCP backend). Do not expose that port.' >&2
exit 2
