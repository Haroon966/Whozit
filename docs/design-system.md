# Whozit UI design system

Generated via **ui-ux-pro-max** for Teacher / Dashboard / demo UI.

## Direction

| Token | Choice | Source |
| --- | --- | --- |
| Style | Flat Design (no heavy shadows / decorative gradients) | ui-ux-pro-max style |
| Pattern | Minimal single-column, mobile-first | product pattern |
| Colors | E-learning: teal primary + orange CTA | color domain “Online Course” |
| Type | Plus Jakarta Sans | Friendly SaaS typography |
| Effects | 150–200ms ease-out hover/focus; `prefers-reduced-motion` | UX guidelines |

## Palette

| Role | Hex |
| --- | --- |
| Primary | `#0D9488` |
| Secondary | `#2DD4BF` |
| CTA | `#F97316` |
| Background | `#F0FDFA` |
| Text | `#134E4A` |
| Paper | `#FFFFFF` |
| Line | `#99F6E4` |

**Note:** Default design-system indigo/violet (`#6366F1` / `#F5F3FF`) was rejected to avoid purple-on-white AI cliché; e-learning teal palette from the same skill is used instead.

## Files

- [`static/whozit-shell.css`](../static/whozit-shell.css) — shared tokens + topbar
- [`static/teacher.html`](../static/teacher.html)
- [`static/dashboard.html`](../static/dashboard.html)
- [`static/index.html`](../static/index.html) — tokens remapped to same system

## Checklist

- [x] No emoji icons
- [x] Focus-visible on controls
- [x] Cursor pointer on buttons / drops
- [x] Labels on form fields
- [x] Reduced motion respected
- [x] Flat surfaces (borders, not multi-layer shadows)
