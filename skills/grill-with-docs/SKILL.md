---
name: grill-with-docs
description: >
  ALWAYS AVAILABLE (Pinky). Relentless interview that also writes CONTEXT.md glossary and
  sparse ADRs. Use when user wants grill with docs, large features needing domain language,
  or paper trail. Load this SKILL.md first; open CONTEXT-FORMAT.md / ADR-FORMAT.md only when
  updating those files. Do not load unrelated skills. Opt out: disable grill-with-docs.
---

# Grill with docs

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing.

If a question can be answered by exploring the codebase, explore the codebase instead.

## Domain awareness

During codebase exploration, also look for existing documentation.

### File structure

Most repos have a single context:

```
/
├── CONTEXT.md
├── docs/
│   └── adr/
└── src/
```

If a `CONTEXT-MAP.md` exists at the root, the repo has multiple contexts. The map points to where each one lives.

Create files lazily — only when you have something to write. If no `CONTEXT.md` exists, create one when the first term is resolved. If no `docs/adr/` exists, create it when the first ADR is needed.

## During the session

### Challenge against the glossary

When the user uses a term that conflicts with the existing language in `CONTEXT.md`, call it out immediately.

### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term.

### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios.

### Cross-reference with code

When the user states how something works, check whether the code agrees. Surface contradictions.

### Update CONTEXT.md inline

When a term is resolved, update `CONTEXT.md` right there. Don't batch. Use the format in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md).

`CONTEXT.md` is a glossary only — no implementation details, no spec dump.

### Offer ADRs sparingly

Only offer an ADR when all three are true:

1. **Hard to reverse**
2. **Surprising without context**
3. **The result of a real trade-off**

If any is missing, skip the ADR. Use [ADR-FORMAT.md](./ADR-FORMAT.md).
