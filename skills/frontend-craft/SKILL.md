---
name: frontend-craft
description: >
  ALWAYS AVAILABLE (Pinky). Stack-agnostic frontend craft for UI, components, pages, CSS,
  accessibility, and responsive work. Use when building or changing user interfaces. Load
  only this SKILL.md — not backend-apis or grill skills unless also needed. Opt out: disable
  frontend-craft / don't use frontend skill.
---

# Frontend craft

## Do

- Prefer semantic HTML and existing design-system patterns in the repo.
- Keyboard focus, visible focus states, and meaningful labels for interactive controls.
- Respect `prefers-reduced-motion`. Keep motion purposeful, not decorative noise.
- Ensure text contrast; do not rely on color alone for meaning.
- Scope UI changes to the task. Match local conventions (components, styling approach).
- Use SVG/icon components already in the project — not emoji as icons.
- When inventing a new look, also use `/ui-ux-pro-max` if installed.

## Don't

- Leak secrets or private API keys into client bundles.
- Add unsolicited design systems, UI libraries, or large CSS frameworks.
- Ship inaccessible click targets or missing hover/focus states on clickable elements.
- Overlay detached promo badges/chips on hero media unless the product already does.

## Check before done

- Usable at ~375px and desktop widths
- Interactive elements have `cursor`/hover affordances consistent with the stack
- No broken empty states or missing alt text for meaningful images
