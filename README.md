# Whozit

HTTP API + simple UI: detect faces, return **head count** + **base64 crops**, **enroll** people, **recognize** names (ArcFace), and **log attendance**.

Own SCRFD + ArcFace under `whozit/` (adapted from [UniFace](https://github.com/yakhyo/uniface), MIT). Product requirements: [`PRD.md`](PRD.md).

| Version | Endpoints | Output |
| --- | --- | --- |
| v1 | `/v1/detect`, `/v1/enroll`, `/v1/people` | Count + crops (+ optional identify) |
| v2 | `/v2/enroll`, `/v2/people`, `/v2/recognize`, `/v2/attendance` | Identity + attendance events |

---

## Setup

```bash
cd Whozit   # or your clone path

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# optional: cp .env.example .env
# GPU (NVIDIA): pip uninstall -y onnxruntime && pip install onnxruntime-gpu
```

First run downloads SCRFD + ArcFace weights into `~/.whozit/models` (reuses `~/.faceattendance/models` or `~/.uniface/models` if present). Override with `WHOZIT_CACHE_DIR`.

Runtime / local data (**not** in git):

- `data/people.json` — embeddings
- `data/attendance.json` — attendance events
- `slack_export/` — optional local Slack photo import (faces + emails); keep private

---

## Run

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8088
```

- UI: http://localhost:8088/
- OpenAPI: http://localhost:8088/docs
- Health: http://localhost:8088/health

### Docker (CPU)

```bash
docker build -t whozit .
docker run --rm -p 8088:8088 \
  -v whozit-data:/data \
  -v whozit-models:/models \
  -e WHOZIT_PEOPLE_PATH=/data/people.json \
  -e WHOZIT_ATTENDANCE_PATH=/data/attendance.json \
  -e WHOZIT_CACHE_DIR=/models \
  whozit
```

First start downloads models into the `/models` volume (slow once). For GPU, use a CUDA base image and install `onnxruntime-gpu` instead of `onnxruntime` in the image.

### Tests

```bash
pip install pytest httpx
python -m pytest tests/ -q
```

### Load smoke (sequential)

```bash
for i in $(seq 1 10); do
  curl -s -o /dev/null -w "%{http_code} %{time_total}\n" \
    -F "image=@photo.jpg" "http://localhost:8088/v1/detect"
done
```

---

## Environment

| Variable | Default | Description |
| --- | --- | --- |
| `WHOZIT_API_KEY` | (unset) | If set, require `X-API-Key` on `/v1/*` and `/v2/*` (not `/health` or UI) |
| `WHOZIT_MAX_UPLOAD_BYTES` | `10485760` (10 MB) | Max upload size |
| `WHOZIT_MAX_INFLIGHT` | `4` | Concurrent `/v1`/`/v2` requests; else `503 overloaded` |
| `WHOZIT_MATCH_THRESH` | `0.35` | Default ArcFace cosine threshold |
| `WHOZIT_PEOPLE_PATH` | `data/people.json` | People store path |
| `WHOZIT_ATTENDANCE_PATH` | `data/attendance.json` | Attendance store path |
| `WHOZIT_CACHE_DIR` | `~/.whozit/models` | ONNX model cache |

---

## Curl examples

### Detect (multipart)

```bash
curl -s -X POST "http://localhost:8088/v1/detect" \
  -F "image=@/path/to/photo.jpg" \
  -F "conf_thresh=0.5" \
  -F "padding=0.2" \
  -F "crop_format=jpeg" | jq .
```

### Detect (JSON base64 on same path)

```bash
B64=$(base64 -w0 photo.jpg)
curl -s -X POST "http://localhost:8088/v1/detect" \
  -H "Content-Type: application/json" \
  -d "{\"image_base64\":\"$B64\",\"identify\":true}" | jq '{face_count, faces: [.faces[] | {id, name, matched}]}'
```

(`/v1/detect/json` remains as an alias.)

### Enroll / people (v1 or v2)

```bash
curl -s -X POST "http://localhost:8088/v2/enroll" \
  -F "name=Ali" \
  -F "image=@ali_face.jpg" | jq .

curl -s http://localhost:8088/v2/people | jq .
curl -s -X DELETE "http://localhost:8088/v2/people/<person_id>" | jq .
```

### Recognize (always identify)

```bash
curl -s -X POST "http://localhost:8088/v2/recognize" \
  -F "image=@photo.jpg" | jq '{face_count, faces: [.faces[] | {id, name, matched, match_score}]}'
```

### Attendance (recognize + log)

```bash
curl -s -X POST "http://localhost:8088/v2/attendance" \
  -F "image=@classroom.jpg" | jq '{face_count, attendance, faces: [.faces[] | {id, name, matched}]}'

curl -s "http://localhost:8088/v2/attendance?limit=20" | jq .
```

### API key (when configured)

```bash
export WHOZIT_API_KEY=my-secret
# restart server, then:
curl -s -X POST "http://localhost:8088/v1/detect" \
  -H "X-API-Key: my-secret" \
  -F "image=@photo.jpg" | jq .
```

### Health

```bash
curl -s http://localhost:8088/health | jq .
```

---

## API summary

### `POST /v1/detect`

Multipart **or** JSON (`image_base64`). Fields: `conf_thresh`, `padding`, `crop_format`, `jpeg_quality`, `max_faces`, `include_landmarks`, `square`, `identify`, `match_thresh`.

### `POST /v2/recognize`

Same inputs; always runs identity match (`name` / `unknown`).

### `POST /v2/attendance`

Same as recognize, plus appends matched people to `data/attendance.json` (one event per `person_id` per request). Response includes `attendance: [...]`.

### Errors (PRD shape)

```json
{
  "request_id": "...",
  "error": { "code": "invalid_image", "message": "..." }
}
```

Codes include: `missing_image`, `invalid_image`, `payload_too_large`, `validation_error`, `unauthorized`, `overloaded`, `processing_error`.

---

## Privacy

- Uploaded images are **not** persisted by default (processed in memory).
- Stored on disk: **face embeddings** (`people.json`) and **attendance events** (`attendance.json`) — not raw photos.
- Retention is operator-controlled: delete or rotate those files as needed.
- Prefer enabling `WHOZIT_API_KEY` on any network-exposed deploy.
- Do **not** commit `data/`, `slack_export/`, `.env`, or model caches — they may hold biometrics / emails.

---

## Project layout

```
Whozit/
├── PRD.md
├── README.md
├── Dockerfile
├── requirements.txt
├── app/
│   ├── main.py
│   ├── config.py
│   ├── detector.py
│   ├── recognizer.py
│   ├── people_store.py
│   ├── attendance_store.py
│   └── image_utils.py
├── whozit/
├── tests/
├── data/                # runtime JSON (gitignored)
└── static/
```

---

## Notes

- Max upload size: **10 MB** (configurable).
- Images are **auto-rotated from EXIF Orientation** before detection.
- No faces → HTTP 200 with `face_count: 0` and `faces: []`.
- Overload → HTTP 503 `overloaded`.
