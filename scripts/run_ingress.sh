#!/usr/bin/env bash
# Fail closed: this legacy entry point conflicts with the previous OAuth schema MCP backend.
set -euo pipefail
echo 'DISABLED: legacy agent ingress on :8767 conflicts with MCP backend. Await secure Agent routing redesign.' >&2
exit 2
