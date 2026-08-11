# Product Requirements Document (PRD)

## Whozit — Face Count & Crop API

| Field | Value |
| --- | --- |
| **Product** | Whozit API |
| **Version** | 1.0 (MVP) → 2.0 (identity / attendance) |
| **Status** | Draft |
| **Date** | 2026-08-10 |
| **Core library** | In-repo `whozit` (SCRFD detect + ArcFace recognize); adapted from [UniFace](https://github.com/yakhyo/uniface) MIT |

---

## 1. Overview

Whozit is an HTTP API that other apps call (e.g. via `curl`) to analyze a photo.

**v1 input:** one image  
**v1 output:** how many people (faces) are in the image, plus cropped head/face images for each detection  

**Later (v2):** match cropped faces to enrolled people and mark attendance.

`whozit` is the processing engine (in-repo library, not a service). The HTTP API wraps SCRFD so any client can send an image and get structured results without installing a third-party face stack.

---

## 2. Problem

- Client apps (mobile, kiosk, door camera, scripts) need face **count** and **face crops** without embedding heavy CV models.
- Teams want a single endpoint callable with standard HTTP/`curl`.
- Attendance systems need a clear path: detect → crop → (later) identify → record presence.

---

## 3. Goals & non-goals

### Goals (v1)

- Accept an image over HTTP (`multipart` upload or base64 JSON).
- Detect faces with in-repo SCRFD (`whozit`).
- Return **head count** (`person_count` / `face_count`).
- Crop each face (with configurable padding) and return crops as **base64** in one JSON response.
- Be callable from any language via `curl` / HTTP.

### Goals (v2 — Whozit)

- Enroll people (name + one or more face images).
- Match new crops to enrolled identities (ArcFace / similar; future in-repo recognition).
- Return identity labels + confidence when a match exists; otherwise `unknown`.
- Optionally log attendance events (who, when, source image id).

### Non-goals (v1)

- Real-time video / WebSocket streaming.
- Age, gender, emotion, gaze, anti-spoofing (can be optional later).
- Storing uploaded images forever (ephemeral processing unless configured).
- Multi-tenant SaaS billing / public marketplace.

---

## 4. Users & use cases

| User | Need |
| --- | --- |
| Backend / script integrator | `curl` or HTTP client posts a photo, gets count + crops |
| Mobile / kiosk app | Capture photo → API → show head count and face thumbnails |
| Attendance operator (v2) | Enroll staff/students; daily scan marks present/absent |
| Developer | Health check, clear JSON contract, documented errors |

### Primary use case (v1)

1. Client sends an image to `POST /v1/detect`.
2. Server runs UniFace detection.
3. Server crops each face bbox (plus padding).
4. Client receives JSON: count, list of faces with bbox, confidence, and `image_base64`.

### Future use case (v2)

1. Admin enrolls “Ali” with face photos → embeddings stored.
2. Classroom photo submitted to `POST /v2/attendance`.
3. API returns count, crops, and matched names (or `unknown`).

---

## 5. Product principle

> **Input = image. Output = head count + cropped head images (JSON + base64).**  
> Identity and attendance are layered on top of that same pipeline.

---

## 6. Functional requirements

### 6.1 Image ingest

| ID | Requirement |
| --- | --- |
| FR-1 | Accept `POST` with `multipart/form-data` field `image` (file). |
| FR-2 | Optionally accept `application/json` with `image_base64` (data URL or raw base64). |
| FR-3 | Support common formats: JPEG, PNG, WebP. |
| FR-4 | Reject empty, corrupt, or oversized files with a clear error code. |
| FR-5 | Default max upload size: **10 MB** (configurable). |

### 6.2 Detection & count

| ID | Requirement |
| --- | --- |
| FR-6 | Detect all faces in the image using UniFace (default detector: SCRFD or RetinaFace). |
| FR-7 | Return `face_count` (integer) = number of detected faces. |
| FR-8 | Apply a minimum confidence threshold (default `0.5`, query/body override allowed). |
| FR-9 | If no faces: `face_count = 0` and `faces = []` with HTTP 200 (not an error). |

### 6.3 Face crop

| ID | Requirement |
| --- | --- |
| FR-10 | For each detection, crop the face region using the bounding box. |
| FR-11 | Support padding around the box (default **20%** of box size) so the full head is included. |
| FR-12 | Clamp crops to image bounds. |
| FR-13 | Encode each crop as JPEG or PNG and return as **base64** string in JSON. |
| FR-14 | Include per-face: `id` (0-based index), `bbox` `[x1,y1,x2,y2]`, `confidence`, `image_base64`, `mime_type`. |

### 6.4 API surface (v1)

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Liveness; optionally report model loaded |
| `POST` | `/v1/detect` | Count faces + return cropped face images |

### 6.5 API surface (v2 — planned)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v2/enroll` | Register a person with face image(s) |
| `GET` | `/v2/people` | List enrolled people |
| `DELETE` | `/v2/people/{id}` | Remove an enrolled person |
| `POST` | `/v2/recognize` | Detect + match identities |
| `POST` | `/v2/attendance` | Detect + match + record attendance event |

---

## 7. API contract (v1)

### 7.1 Request examples

**Multipart (recommended for curl):**

```bash
curl -X POST "http://localhost:8000/v1/detect" \
  -F "image=@group_photo.jpg" \
  -F "conf_thresh=0.5" \
  -F "padding=0.2" \
  -F "crop_format=jpeg"
```

**JSON base64:**

```bash
curl -X POST "http://localhost:8000/v1/detect" \
  -H "Content-Type: application/json" \
  -d '{"image_base64":"<BASE64>","conf_thresh":0.5,"padding":0.2}'
```

### 7.2 Success response (200)

```json
{
  "request_id": "b7c3e9a0-1d2f-4a8b-9c0e-123456789abc",
  "face_count": 3,
  "image_width": 1920,
  "image_height": 1080,
  "faces": [
    {
      "id": 0,
      "bbox": [120, 80, 280, 260],
      "confidence": 0.97,
      "mime_type": "image/jpeg",
      "image_base64": "/9j/4AAQSkZJRgABAQAAAQABAAD..."
    },
    {
      "id": 1,
      "bbox": [500, 90, 660, 270],
      "confidence": 0.94,
      "mime_type": "image/jpeg",
      "image_base64": "/9j/4AAQSkZJRgABAQAAAQABAAD..."
    }
  ]
}
```

Notes:

- `image_base64` is **raw base64** (no `data:` prefix) so clients can decode easily.
- Clients may display as `data:{mime_type};base64,{image_base64}`.
- `bbox` is in original image pixel coordinates: `[x1, y1, x2, y2]`.

### 7.3 Error responses

| HTTP | `error.code` | When |
| --- | --- | --- |
| 400 | `invalid_image` | Unreadable / unsupported format |
| 400 | `missing_image` | No file / no `image_base64` |
| 413 | `payload_too_large` | Over max size |
| 422 | `validation_error` | Bad parameter (e.n. padding &lt; 0) |
| 500 | `processing_error` | Detection/crop failed internally |

Example:

```json
{
  "request_id": "...",
  "error": {
    "code": "invalid_image",
    "message": "Could not decode image bytes."
  }
}
```

---

## 8. Processing pipeline

```text
Client (curl / app)
        │
        ▼
  HTTP API (FastAPI or similar)
        │
        ├─ validate & decode image
        │
        ▼
  UniFace detector (RetinaFace / SCRFD)
        │
        ├─ face list: bbox + confidence (+ landmarks)
        │
        ▼
  Cropper (bbox + padding → JPEG/PNG → base64)
        │
        ▼
  JSON response: face_count + faces[]
        │
        ▼  (v2 only)
  Embedding + match vs enrolled store → names / attendance
```

### UniFace usage (v1)

- Detection only: e.g. `RetinaFace` / `SCRFD` → `detector.detect(image)`.
- `len(faces)` → head count.
- Each `face.bbox` → crop region.
- Landmarks can be returned later; not required for v1 crop output.

### UniFace usage (v2)

- Recognition: ArcFace / AdaFace / MobileFace embeddings.
- Compare against enrolled vectors (threshold-based match; optional FAISS store from UniFace).

---

## 9. Non-functional requirements

| Area | Requirement |
| --- | --- |
| **Latency** | Target &lt; 1s per image for ≤ 10 faces on CPU mid-range; document GPU path via `onnxruntime-gpu`. |
| **Concurrency** | Safe concurrent requests; load detector once at startup (singleton). |
| **Resource** | Configurable max workers / queue; reject or 503 when overloaded. |
| **Security** | Optional API key header for private deploy; no public open relay by default. |
| **Privacy** | Do not persist uploads by default; if logging enabled, document retention. |
| **Ops** | Structured logs with `request_id`; `/health` for probes. |
| **Portability** | Linux first; Docker image recommended for deployment. |

---

## 10. Parameters

| Name | Default | Description |
| --- | --- | --- |
| `conf_thresh` | `0.5` | Min detection confidence |
| `padding` | `0.2` | Extra margin around bbox (fraction of width/height) |
| `crop_format` | `jpeg` | `jpeg` or `png` for returned crops |
| `jpeg_quality` | `90` | Quality when `crop_format=jpeg` |
| `include_landmarks` | `false` | If true, add 5-point landmarks per face (optional) |
| `max_faces` | `100` | Cap returned faces (sorted by confidence) |

---

## 11. Success metrics

| Metric | Target |
| --- | --- |
| Successful detect calls (valid images) | ≥ 99% return 200 with valid schema |
| Count accuracy on clear frontal photos | Competitive with UniFace detector quality on WIDER-style scenes |
| Crop quality | Full face visible with padding; clipped only at image edges |
| Integrator time-to-first-call | `&lt; 5 minutes` with README + curl example |

---

## 12. Out of scope / later backlog

- Age / gender / emotion / anti-spoofing metadata on crops
- Returning annotated full image (boxes drawn) as an extra field
- Batch ZIP upload of many photos in one request
- Web UI for upload/preview
- Native mobile SDKs (HTTP is enough)

---

## 13. Milestones

| Phase | Deliverable |
| --- | --- |
| **M0** | Project scaffold: FastAPI (or Flask), Docker, UniFace install (`cpu`/`gpu`) |
| **M1 — MVP** | `POST /v1/detect`: count + base64 crops; `/health`; curl docs |
| **M2** | Config, API key, size limits, better errors, basic tests |
| **M3 — Attendance** | Enroll / recognize / attendance endpoints; embedding store |
| **M4** | Hardening: GPU deploy notes, load test, privacy retention policy |

---

## 14. Technical recommendations

| Choice | Suggestion | Why |
| --- | --- | --- |
| Framework | FastAPI | Fast, OpenAPI docs auto-generated for integrators |
| Face ML | UniFace `SCRFD` or `RetinaFace` | Production ONNX detectors; simple `detect()` API |
| Response | Single JSON + base64 crops | Easy for any client; one round-trip |
| Deploy | Docker | Reproducible model cache (`UNIFACE_CACHE_DIR`) |
| Recognition (v2) | UniFace ArcFace + cosine threshold | Same library stack as detection |

**Example internal flow (pseudocode):**

```python
faces = detector.detect(image)
crops = [encode_b64(crop(image, f.bbox, padding=0.2)) for f in faces]
return {"face_count": len(faces), "faces": [...]}
```

---

## 15. Risks & mitigations

| Risk | Mitigation |
| --- | --- |
| Large JSON when many faces | Cap `max_faces`; allow lower `jpeg_quality`; document size |
| Missed side/occluded faces | Expose `conf_thresh`; choose stronger detector weights |
| GPU / model download on first run | Warm models at startup; bake cache into Docker image |
| Model licenses | Prefer MIT-friendly UniFace paths; review UniFace attribution for commercial use |
| Privacy of face biometrics (v2) | Encrypt store at rest; retention policy; access control |

---

## 16. Acceptance criteria (v1 done)

- [ ] `curl -F image=@photo.jpg` against `/v1/detect` returns JSON.
- [ ] Response includes integer `face_count` matching number of `faces` entries.
- [ ] Each face includes decodable `image_base64` crop of that head/face.
- [ ] Zero-face images return `face_count: 0` and empty `faces` array.
- [ ] Invalid upload returns documented 4xx error JSON.
- [ ] README shows install, run, and curl examples.
- [ ] OpenAPI/`/docs` describes the endpoint.

---

## 17. Open decisions

| Topic | Decision for this PRD |
| --- | --- |
| Crop return format | **JSON + base64** (confirmed) |
| Product direction | **Full Whozit** — v1 detect/count/crop, then enroll/recognize/attendance |
| Default detector | TBD at implement time: SCRFD (speed) vs RetinaFace (accuracy) |
| Auth | Optional API key; not required for local MVP |
| Persistence | No image persistence in v1; v2 stores embeddings only by default |

---

## 18. Summary

Build a thin HTTP service on top of **UniFace**:

1. **Other apps send an image** (curl / HTTP).
2. **This service detects faces**, returns **how many people**.
3. **Crops each head/face** and returns crops as **base64 inside JSON**.
4. Later: **enroll identities** and turn the same pipeline into **attendance marking**.
