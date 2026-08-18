# Product Requirements Document (PRD)

## Whozit — Standalone face attendance (v4)

| Field | Value |
| --- | --- |
| **Product** | Whozit |
| **Version** | 4.0 |
| **Status** | Active |
| **Date** | 2026-08-18 |
| **Engine** | In-repo `whozit` (SCRFD + ArcFace) |

---

## 1. Overview

Whozit is a **standalone attendance product**: teachers enroll students, scan a class photo, review matches, and save the daily register — all without another app.

It also exposes a clean HTTP API for integrators who bring their own roster UI.

**Architecture deck:** [docs/architecture.html](docs/architecture.html) (includes product override: names + register live in Whozit).

---

## 2. Goals

- Enrol students with a **display name** and face photo inside a **scope** (`scope_key`).
- Recognize faces in a scope; return **name**, **ref_id**, **score**, **margin**, and top **candidates**.
- Greedy **one-to-one** assignment so one student cannot match two faces in one photo.
- **Max-over-samples** matching (not mean centroid).
- Store **encrypted enrolment crops** for model upgrades.
- Serve **daily attendance** (`POST/GET /attendance/day`) and teacher/dashboard UI.
- **`ref_id` is the only unique key** — duplicate names in one class are allowed.

---

## 3. Non-goals

- Multi-tenant SaaS in one deployment (one program per container/volume/key).
- Public recognition audit API (`rec_log` is internal).
- Calibrating match thresholds automatically (integrator/operator responsibility).
- Real-time video streaming.

---

## 4. Users

| User | Need |
| --- | --- |
| Teacher | Enrol roster, scan class, fix unknowns, save day |
| Admin | Dashboard present/absent by date |
| Integrator | HTTP API with stable `ref_id` contract |

---

## 5. API summary

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/detect` | Count + crops only |
| POST | `/enroll` | `scope_key`, `name`, `image`, optional `ref_id` |
| POST | `/recognize` | Scoped match + evidence |
| GET | `/refs?scope_key=` | Roster |
| DELETE | `/refs/{ref_id}?scope_key=` | Cascade samples + register rows |
| DELETE | `/samples/{id}` | Remove one bad template |
| POST | `/attendance/day` | Upsert present list |
| GET | `/attendance/day/status` | Present + absent |
| POST | `/session` | API key → httpOnly cookie for UI |

Auth: `WHOZIT_API_KEY` required when set. **No** `Sec-Fetch-Site` bypass.

---

## 6. Data retention

- Enrolment **crops**: indefinite by default; encrypted with `WHOZIT_CROP_KEY`.
- **Vectors**: per sample, tagged with `model_version`.
- **rec_log**: internal, TTL default 90 days (`WHOZIT_REC_LOG_TTL_DAYS`).
- **Daily register**: until deleted.

Destroying `WHOZIT_CROP_KEY` crypto-shreds crops for program off-boarding.

---

## 7. Privacy notes

Operators must obtain consent for storing face templates and crops of minors. Whozit stores names as labels tied to `ref_id`; losing the external `ref_id` mapping (if you mirror ids in another system) does not recover galleries from Whozit alone.

---

## 8. Supersedes

- v1/v2 global JSON gallery (`people.json`) — removed.
- v3 route prefix — replaced by v4 paths above.
- Design doc [docs/v3-class-scoped.md](docs/v3-class-scoped.md) — historical; see architecture deck for current model.
