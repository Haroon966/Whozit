# Install Pinky (for agents)

**When the user pastes this repo URL and asks to install Pinky:**

Do the install steps, then the channel ask. Nothing else.

## Steps (required)

1. Find the **consumer project root** (the user's app / git repo). Work there. Do **not** make the Pinky kit the project.
2. Clone this kit into a **temporary directory only** (not inside the project):

```bash
PINKY_TMP="$(mktemp -d)"
git clone --depth 1 https://github.com/Haroon966/pinky-cursor.git "$PINKY_TMP/pinky-cursor"
```

3. Run the installer **into the consumer project**:

```bash
cd /path/to/consumer-project
bash "$PINKY_TMP/pinky-cursor/install.sh"
# add --with-ui only if user wants UI UX Pro Max
```

4. **Delete the temp clone** immediately:

```bash
rm -rf "$PINKY_TMP"
```

5. Confirm only Pinky **payload** files exist in the project (see allowlist below).

6. **Ask which phone channel to connect** (multi-select OK): **WhatsApp** · **Slack** · **skip**.
   - If not skip → follow `skills/agent-channels/SKILL.md`.
   - **WhatsApp (phone without IDE):** ask **owner number** → give user (do **not** run yourself):
     1. `bash .pinky/whatsapp/doctor.sh`
     2. `bash .pinky/whatsapp/login.sh` (QR in **their** terminal)
     3. `bash .pinky/whatsapp/watch.sh` (keep open; needs Cursor CLI `agent` + `agent login`)
     - Owner texts the **linked** WhatsApp account. Never enable MCP `whatsapp` while watch runs (440).
   - Then reopen / new agent chat if needed.

## Forbidden

- Do **not** leave a `pinky-cursor/` folder (or any clone of this kit) inside the project.
- Do **not** copy this kit’s `README.md`, `assets/`, `LICENSE`, `.github/`, `install.sh`, `scripts/`, or `adapters/` source tree into the project.
- Do **not** `git submodule` or subtree-merge this repo into the project.
- Do **not** commit the temp clone.
- Do **not** commit `.pinky/` (sessions, tokens) — installer gitignores it.

## Payload allowlist (may exist after install)

| Path | Host |
|------|------|
| `AGENTS.md` | Codex + shared |
| `CLAUDE.md` | Claude Code |
| `.cursor/rules/*.mdc` | Cursor |
| `skills/**` | root / scanners |
| `.cursor/skills/**` | Cursor |
| `.claude/skills/**` | Claude Code |
| `.codex/skills/**` | Codex |
| `.agents/skills/**` | Codex |
| `docs/pinky-customization-guide.md` | docs |
| `docs/pinky-agent-compat.md` | docs |
| `docs/pinky-install-for-agents.md` | docs (copy of this guide) |
| `.pinky/` (local scaffold, gitignored) | channel sessions / secrets — never commit |
| `.gitignore` entry for `.pinky/` | local hygiene |
| UI UX Pro Max paths (only if `--with-ui`) | optional |

Anything from this kit **outside** that list must not remain in the consumer project.

## One-liner (same idea)

```bash
PINKY_TMP="$(mktemp -d)" && \
  git clone --depth 1 https://github.com/Haroon966/pinky-cursor.git "$PINKY_TMP/pinky-cursor" && \
  bash "$PINKY_TMP/pinky-cursor/install.sh" && \
  rm -rf "$PINKY_TMP"
```

(Run from the consumer project root.)

Flags: `--force` · `--dry-run` · `--with-ui` · `--agents=cursor,claude,codex`
