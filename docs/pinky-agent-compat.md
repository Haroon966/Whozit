# Pinky agent compatibility

After `install.sh`, Pinky wires **Cursor**, **Claude Code**, and **Codex** only.

## Payload vs kit source

`install.sh` writes **payload** files into the consumer project only (`AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, skill dirs, Pinky docs). It does **not** copy kit `README`, `assets/`, `LICENSE`, `.github/`, or `install.sh` into the project.

Agents given this repo URL must temp-clone → install → delete clone. See [INSTALL.md](../INSTALL.md).

## Depth tiers

| Tier | What you get | Host |
|------|----------------|------|
| **Full** | Cursor `.mdc` rules (core, Ponytail, Caveman ALWAYS ON, architecture, testing, FE/BE, git authorship) + skills | Cursor |
| **Instructions + skills** | `AGENTS.md` (+ `CLAUDE.md` for Claude) and skill dirs | Claude Code, Codex |

## Always-on instructions

| Host | Path |
|------|------|
| Codex (+ shared spine) | `AGENTS.md` |
| Claude Code | `CLAUDE.md` + `AGENTS.md` |
| Cursor | `.cursor/rules/*.mdc` |

## Skills

Same skills are copied into:

| Host | Directory |
|------|-----------|
| Kit / root scanners | `skills/` |
| Cursor | `.cursor/skills/` |
| Claude Code | `.claude/skills/` |
| Codex | `.codex/skills/` and `.agents/skills/` |

Skills included: `caveman`, `grill-me`, `grill-with-docs`, `agent-channels`, `frontend-craft`, `backend-apis`. UI UX Pro Max is **opt-in** via `install.sh --with-ui` (needs Node/`npx`). After install, agents ask WhatsApp / Slack / skip. WhatsApp phone control: user-run `doctor.sh` → `login.sh` (QR) → `watch.sh` + Cursor CLI `agent` (not IDE chat). Local sessions under gitignored `.pinky/`. Never run WhatsApp MCP and `watch.sh` together.

## Optional upstream plugins

Pinky’s file fan-out is enough for behavior. For marketplace plugins with hooks/mode switches:

- [Ponytail](https://github.com/DietrichGebert/ponytail) — Claude Code / Codex plugins
- [Caveman](https://github.com/JuliusBrussee/caveman) — `npx skills add JuliusBrussee/caveman`
