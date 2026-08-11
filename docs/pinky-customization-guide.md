# Pinky customization guide

## Always on / opt out

After install, Cursor rules are `alwaysApply: true` and skills are available by default.

| User says | Effect |
|-----------|--------|
| `stop caveman` / `normal mode` | Caveman off for session |
| `don't use pinky` | Pause Pinky layers for session |
| `disable grill-me` (etc.) | Skip that skill |

Agents must **not** load all skills into context — only the one matching the prompt. See `AGENTS.md` → Context discipline and Cursor rule `09-context-discipline.mdc`.

## Install from repo URL (agents)

Follow [pinky-install-for-agents.md](pinky-install-for-agents.md) (same as the kit’s `INSTALL.md` on GitHub).

1. Clone kit to a **temp** directory (not inside this project).
2. Run `install.sh` with cwd = this project (`--with-ui` only if asked).
3. Delete the temp clone.
4. Keep only payload files — never leave a nested `pinky-cursor/` folder.

## After install

Reopen your agent (new chat / reload window) so it picks up `AGENTS.md`, Cursor rules, and skills.

Pinky targets **Cursor**, **Claude Code**, and **Codex** only.

## Safer re-runs

```bash
git clone --depth 1 https://github.com/Haroon966/pinky-cursor.git /tmp/pinky-cursor
cd your-project
bash /tmp/pinky-cursor/install.sh
rm -rf /tmp/pinky-cursor
```

```bash
bash install.sh --dry-run                 # preview; write nothing
bash install.sh                           # safe write (*.pinky* siblings if files exist)
bash install.sh --force                   # replace Pinky-owned files
bash install.sh --with-ui                 # also UI UX Pro Max (needs npx)
bash install.sh --agents=cursor,claude    # subset
```

Without `--force`, existing files are kept and a sibling is written. Merge manually or re-run with `--force`.

## Trim what you don’t need

| Goal | Action |
|------|--------|
| No Caveman prose | Delete `.cursor/rules/caveman.mdc` and `skills/caveman/` copies; edit Communication section out of `AGENTS.md` |
| No Ponytail | Remove `ponytail.mdc` and ladder section from `AGENTS.md` |
| Frontend-only | Delete `05-frontend.mdc` / `frontend-craft` skill copies |
| Backend-only | Delete `06-backend.mdc` / `backend-apis` |
| No grill skills | Remove `grill-me` and `grill-with-docs` under skill dirs |
| Cursor only | `bash install.sh --agents=cursor` |
| Claude only | `bash install.sh --agents=claude` |
| Codex only | `bash install.sh --agents=codex` |

## grill-me vs grill-with-docs

- `/grill-me` — interview only; no files written
- `/grill-with-docs` — same interview; writes `CONTEXT.md` glossary and sparse `docs/adr/` ADRs

## Stack-specific rules

Add your own `.cursor/rules/my-stack.mdc` with globs for your framework. Keep Pinky rules stack-agnostic.

## UI UX Pro Max

```bash
bash install.sh --with-ui
# or later:
npx uipro-cli@latest init --ai cursor
```

(`@latest` is unpinned — pin a version in your own docs if you need reproducibility.)

## Sync after editing the kit

Canonical sources: `AGENTS.md`, `CLAUDE.md`, `skills/`, `adapters/cursor/`, `INSTALL.md`. After changing them, re-run `install.sh` in consumer projects (with `--force` to replace existing Pinky files).
