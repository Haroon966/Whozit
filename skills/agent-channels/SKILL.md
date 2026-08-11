---
name: agent-channels
description: >
  Connect WhatsApp phone control (user-run login + watch + Cursor CLI agent) or
  Slack MCP. Always ask owner number. Never run QR/login/watch yourself — give
  commands. After Pinky install channel ask, or /agent-channels / connect WhatsApp.
---

# Agent channels (WhatsApp / Slack)

## When to run

- Right after Pinky install (step 6): **WhatsApp** · **Slack** · **skip**.
- User asks to connect / reconnect later.

## Lessons (do not repeat)

| User pain | Fix |
|-----------|-----|
| Agent runs login → no scannable QR in chat | **User** runs `login.sh` in **their** terminal |
| MCP + `watch.sh` same auth → disconnect **440** | **Never** run Baileys MCP and watch together |
| “Same message” spam | No fixed auto-ack; agent reply only |
| Laptop chat required | `watch.sh` + Cursor CLI `agent` (PC stays on, IDE optional) |
| Owner texts wrong number | Owner texts the **linked** (QR) account |
| Inbox empty / LID mismatch | Login once; watch saves `lid` in `owner.json` |
| `agent` trust / auth fails | `agent login` + `--trust` in watch |
| Secrets on GitHub | `.pinky/` gitignored |

Unofficial WhatsApp Web clients can conflict with WhatsApp ToS — prefer a **dedicated** number for the linked device.

## Safety

- Everything under `.pinky/` is **local** (gitignored). Never commit sessions/tokens.
- Never print tokens/secrets.

## Ask

1. Channel: WhatsApp · Slack · skip (multi-select OK).
2. If WhatsApp: **owner number** (who may message the agent). Save `.pinky/whatsapp/owner.json`.

---

## WhatsApp — phone controls Cursor (supported path)

**Do NOT** run `login.sh` / `watch.sh` / QR yourself. Print exact commands. Wait for user.

### 1. Files

Ensure under `.pinky/whatsapp/`:

- `login.sh`, `watch.sh`, `doctor.sh` (from `skills/agent-channels/scripts/`)
- `chmod +x` those scripts

### 2. Owner

Ask phone. Normalize JID (PK `0343…` → `92343…@s.whatsapp.net`). Write `owner.json`:

```json
{ "phone": "03435971748", "jid": "923435971748@s.whatsapp.net" }
```

### 3. Doctor (give user)

```bash
export PATH="$HOME/.local/bin:$PATH"
bash /path/to/project/.pinky/whatsapp/doctor.sh
```

Fix every FAIL (install `agent`, `agent login`, pair, kill MCP whatsapp conflict).

### 4. Pair (user terminal — QR visible there)

```bash
bash /path/to/project/.pinky/whatsapp/login.sh
```

Phone: WhatsApp → Linked Devices → Link a device → scan → wait `OK — paired`.

### 5. Watch (user terminal — keep open)

```bash
export PATH="$HOME/.local/bin:$PATH"
bash /path/to/project/.pinky/whatsapp/watch.sh
```

- PC stays awake. No Cursor window required.
- Owner phones the **linked** account (QR’d number), not a random chat.
- Flow: owner text → Cursor CLI `agent` → WhatsApp reply.
- Q&A = ask mode (fast). Words like fix/edit/improve/implement → full agent.

### 6. Do not enable WhatsApp MCP while watch runs

MCP Baileys + watch = **440** session fight. Prefer **watch-only** for phone control. (Optional MCP templates exist for IDE tool-calling only — never together with watch.)

---

## Slack (MCP)

1. Create Slack app → bot scopes → install → token + team id.
2. Store in `.pinky/slack/env` (never commit).
3. Merge `templates/mcp-slack.snippet.json` into user MCP config.
4. Reload MCP; verify tools.

---

## After setup

Remind: `.pinky/` local only. Watch terminal must stay up for phone control.

## Out of scope

Cloud agent without a running PC. Agent-run QR/watch. Running WhatsApp MCP + watch on the same auth dir.
