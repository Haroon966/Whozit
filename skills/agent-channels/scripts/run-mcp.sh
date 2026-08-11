#!/usr/bin/env bash
# Pinky WhatsApp MCP launcher — keeps MCP stdio clean.
set -euo pipefail
AUTH_DIR="$(cd "$(dirname "$0")" && pwd)"
GUARD="$AUTH_DIR/mcp-stdout-guard.cjs"
export NODE_OPTIONS="${NODE_OPTIONS:+$NODE_OPTIONS }--require ${GUARD}"
exec npx -y baileys-mcp --auth-dir "$AUTH_DIR"
