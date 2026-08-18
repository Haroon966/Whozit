# Whozit

Standalone face attendance: enroll students by **name**, scan a class photo, save the daily register — no external app required.

HTTP API + teacher UI + dashboard. Own SCRFD + ArcFace under `whozit/` (adapted from [UniFace](https://github.com/yakhyo/uniface), MIT).

**Architecture:** [docs/architecture.html](docs/architecture.html) · full proposal: [docs/proposal-by-shoaib.md](docs/proposal-by-shoaib.md)

**Website:** [https://haroon966.github.io/Whozit/](https://haroon966.github.io/Whozit/) (GitHub Pages from `/docs`).

| Surface | Purpose |
| --- | --- |
| `POST /detect` | Stateless face count + crops |
| `POST /enroll` | `(scope_key or country+province+emis+grade, name, image)` → stable `student_id` |
| `GET /students/{id}` | Other apps: name, school, class, face sample count |
| `GET /org/countries` | Org tree for pickers |
| `POST /recognize` | Match faces in one scope; returns `name`, `score`, `margin`, candidates |
| `GET /refs` | Roster for a scope |
| `POST/GET /attendance/day` | Daily present list |
| `POST /admin/reembed` | Re-embed all stored crops after model bump |
| `POST /admin/wipe` | Wipe all program data (confirm body) |
| `GET /internal/rec_log` | Support/debug recognition log |
| `PATCH /refs/{ref_id}` | Rename without new photo |

Migrate v3 DB:

```bash
python -m app.migrate_v3 --source data/whozit_v3.db --dest data/whozit.db
# or set WHOZIT_MIGRATE_V3_PATH on first startup
```

Map existing `roll-*` refs into org rows + stable IDs (`pk+province+emis+seq`):

```bash
python -m app.migrate_org --db data/whozit.db
```

Docker + Litestream:

```bash
docker compose up --build
```

**Teacher UI:** http://localhost:8088/teacher  
**Dashboard:** http://localhost:8088/dashboard

---

## Identity contract

- **`scope_key`** — opaque class path, e.g. `pk/punjab/rawalpindi/sch-10482/sec-5a`
- **`ref_id`** — unique identity key (caller-supplied or minted UUID). **Names are not unique** — two "Ayesha"s are two `ref_id`s.
- **Enrolment crops** retained indefinitely by default (encrypted at rest with `WHOZIT_CROP_KEY`). See consent wording in your deployment policy.
- **Threshold** `WHOZIT_MATCH_THRESH` defaults to `0.35` — a placeholder; calibrate on your classroom photos.

---

## Setup

```bash
cd Whozit

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# optional: cp .env.example .env
```

First run downloads SCRFD + ArcFace weights into `~/.whozit/models`. Runtime data (**not** in git):

- `data/whozit.db` — refs, samples, daily register, internal rec_log

---

## Run

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8088
```

- UI: http://localhost:8088/
- OpenAPI: http://localhost:8088/docs
- Health: http://localhost:8088/health

### Auth

Set `WHOZIT_API_KEY`. Browser UI calls `POST /session` with the key once to get an httpOnly cookie — the key never ships in page JS.

### Docker (CPU)

```bash
docker build -t whozit .
docker run --rm -p 8088:8088 \
  -v whozit-data:/data \
  -v whozit-models:/models \
  -e WHOZIT_SQLITE_PATH=/data/whozit.db \
  -e WHOZIT_CROP_KEY=change-me-in-production \
  -e WHOZIT_CACHE_DIR=/models \
  whozit
```

Optional SQLite replication: [docs/litestream.md](docs/litestream.md)

### Tests

```bash
pip install pytest httpx cryptography
python -m pytest tests/ -q
```

---

## Example

```bash
# Enrol (ref_id optional — minted if omitted)
curl -s -X POST http://localhost:8088/enroll \
  -F scope_key=pk/demo/class-5a \
  -F name="Ali Khan" \
  -F image=@face.jpg | jq .

# Recognize
curl -s -X POST http://localhost:8088/recognize \
  -F scope_key=pk/demo/class-5a \
  -F image=@classroom.jpg | jq '.faces[] | {name, ref_id, score, margin, matched}'

# Save daily roll
curl -s -X POST http://localhost:8088/attendance/day \
  -H 'Content-Type: application/json' \
  -d '{"scope_key":"pk/demo/class-5a","date":"2026-08-18","present_ref_ids":["<ref_id>"]}' | jq .
```

---

## Layout

```
Whozit/
├── app/
│   ├── main.py          # FastAPI routes
│   ├── org_store.py     # Country / school / class / stable student_id
│   ├── ref_store.py     # SQLite refs / samples / register
│   ├── recognizer.py    # Match + greedy assignment
│   ├── crop_crypto.py   # Encrypted enrolment crops
│   └── db.py            # Schema
├── whozit/              # SCRFD + ArcFace library
├── static/              # Teacher + dashboard UI
├── docs/
│   ├── architecture.html
│   └── litestream.md
└── tests/
```

Product requirements: [`PRD.md`](PRD.md)
