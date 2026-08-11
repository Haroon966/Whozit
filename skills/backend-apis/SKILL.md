---
name: backend-apis
description: >
  ALWAYS AVAILABLE (Pinky). Stack-agnostic backend and API craft: validation, authz, errors,
  logging, and safe data access. Use when changing servers, APIs, jobs, auth, or databases.
  Load only this SKILL.md — not frontend-craft or grill skills unless also needed. Opt out:
  disable backend-apis / don't use backend skill.
---

# Backend APIs

## Do

- Validate at trust boundaries (external input, webhooks, user-controlled IDs).
- Check authorization before reading or mutating sensitive data.
- Prefer structured errors and logs; never log secrets, tokens, or raw passwords.
- Fail closed on auth/authz mistakes. Be explicit about idempotency for retries.
- Match existing API/error conventions in the repo (status codes, envelope shape).
- Smallest correct change (Ponytail-compatible). Reuse helpers already present.

## Don't

- Hardcode secrets or credentials.
- Trust client-supplied roles, prices, or tenant IDs without server-side checks.
- Swallow errors silently.
- Add frameworks or ORMs when the existing stack already solves the problem.

## Check before done

- Happy path and one failure path considered
- Authz path reviewed for the resources touched
- Migrations/backfills (if any) are safe and reversible or clearly documented
