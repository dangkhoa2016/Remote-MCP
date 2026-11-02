#!/usr/bin/env bash
# Fail closed: this legacy entry point conflicts with the Phase 3.1 MCP backend.
set -euo pipefail
echo 'DISABLED: legacy agent ingress on :8767 conflicts with MCP backend. Await Phase 4-E redesign.' >&2
exit 2
