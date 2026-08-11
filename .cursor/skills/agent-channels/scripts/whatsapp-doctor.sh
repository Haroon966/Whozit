#!/usr/bin/env bash
# Pinky WhatsApp doctor — catch the failure modes real users hit.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/../.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"
ok=0
warn=0
fail=0

pass() { echo "OK   $*"; ok=$((ok+1)); }
warn_() { echo "WARN $*"; warn=$((warn+1)); }
fail_() { echo "FAIL $*"; fail=$((fail+1)); }

echo "Pinky WhatsApp doctor"
echo "Project: $ROOT"
echo "WA dir:  $DIR"
echo

# owner
if [[ -f "$DIR/owner.json" ]]; then
  if python3 -c 'import json,sys; o=json.load(open(sys.argv[1])); assert o.get("jid") and "@" in o["jid"]' "$DIR/owner.json" 2>/dev/null; then
    pass "owner.json has jid"
  else
    fail_ "owner.json missing/invalid jid — ask owner number via /agent-channels"
  fi
else
  fail_ "no owner.json — set owner number (phone agent may talk to)"
fi

# session
if [[ -f "$DIR/creds.json" ]]; then
  pass "creds.json present (paired)"
else
  fail_ "not paired — USER runs: bash $DIR/login.sh  (QR in THEIR terminal)"
fi

# scripts
for s in login.sh watch.sh doctor.sh; do
  if [[ -x "$DIR/$s" ]]; then
    pass "$s executable"
  elif [[ -f "$DIR/$s" ]]; then
    warn_ "$s exists but not executable — chmod +x $DIR/$s"
  else
    fail_ "missing $s — re-run install.sh or copy from skills/agent-channels/scripts/"
  fi
done

# cursor agent CLI
if command -v agent >/dev/null 2>&1; then
  pass "cursor agent CLI: $(command -v agent)"
  if agent -p --help >/dev/null 2>&1; then
    # login probe: headless without trust may still print Not logged in
    if agent status 2>&1 | grep -qi 'not logged in'; then
      fail_ "agent not logged in — run: agent login"
    elif agent status 2>&1 | grep -qi 'logged in\|email\|account'; then
      pass "agent looks logged in"
    else
      # status may not exist — try tiny ask with timeout
      out="$(timeout 20 agent -p --trust --mode ask --output-format text 'Reply with exactly: pong' 2>&1 || true)"
      if echo "$out" | grep -qi 'not logged in\|unauthorized\|auth'; then
        fail_ "agent auth failed — run: agent login"
      elif echo "$out" | grep -qi 'pong'; then
        pass "agent headless ask works"
      else
        warn_ "could not confirm agent auth (run: agent login if replies fail)"
      fi
    fi
  fi
else
  fail_ "agent CLI missing — curl https://cursor.com/install -fsS | bash && export PATH=\"\$HOME/.local/bin:\$PATH\" && agent login"
fi

# conflict: baileys-mcp on same auth
if pgrep -af "baileys-mcp.*${DIR}" >/dev/null 2>&1; then
  fail_ "baileys-mcp using this auth dir — disable Cursor MCP whatsapp (causes disconnect 440)"
else
  pass "no baileys-mcp conflict on this auth dir"
fi

if [[ -f "${HOME}/.cursor/mcp.json" ]] && grep -q '"whatsapp"' "${HOME}/.cursor/mcp.json" 2>/dev/null; then
  warn_ "~/.cursor/mcp.json still has whatsapp — turn OFF while watch.sh runs"
fi

# gitignore
if [[ -f "$ROOT/.gitignore" ]] && grep -qxF '.pinky/' "$ROOT/.gitignore"; then
  pass ".gitignore has .pinky/"
else
  warn_ "add .pinky/ to .gitignore (sessions must not ship to GitHub)"
fi

echo
echo "Summary: $ok ok · $warn warn · $fail fail"
echo
if [[ "$fail" -gt 0 ]]; then
  echo "Fix fails, then:"
  echo "  bash $DIR/login.sh     # once, QR in YOUR terminal"
  echo "  bash $DIR/watch.sh     # keep open; PC stays on"
  echo "Owner texts the LINKED WhatsApp account (the one you QR-scanned)."
  exit 1
fi

echo "Ready. Keep one terminal on:"
echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
echo "  bash $DIR/watch.sh"
echo
echo "From owner phone → message the LINKED account (not a random chat)."
exit 0
