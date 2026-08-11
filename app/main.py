"""Whozit API — detect, enroll, recognize, attendance."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import numpy as np
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.attendance_store import attendance_store
from app.config import settings
from app.detector import detector_service
from app.image_utils import (
    crop_face,
    decode_image_base64,
    decode_image_bytes,
    draw_face_boxes,
    encode_image_base64,
)
from app.people_store import people_store
from app.recognizer import DEFAULT_MATCH_THRESHOLD, recognizer_service

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

logger = logging.getLogger("whozit.api")
logging.basicConfig(level=logging.INFO, format="%(message)s")

_inflight = threading.Semaphore(settings.max_inflight)

app = FastAPI(
    title="Whozit",
    description="Detect faces, enroll people, recognize, and log attendance.",
    version="2.0.0",
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class DetectJsonRequest(BaseModel):
    image_base64: str = Field(..., description="Raw base64 or data-URL image")
    conf_thresh: float = Field(0.5, ge=0.0, le=1.0)
    padding: float = Field(0.2, ge=0.0, le=2.0)
    crop_format: Literal["jpeg", "png"] = "jpeg"
    jpeg_quality: int = Field(90, ge=10, le=100)
    max_faces: int = Field(100, ge=0, le=500)
    include_landmarks: bool = False
    square: bool = Field(True, description="Return 1:1 squared face crops")
    identify: bool = Field(True, description="Match faces to enrolled people")
    match_thresh: float = Field(DEFAULT_MATCH_THRESHOLD, ge=0.0, le=1.0)


class FaceOut(BaseModel):
    id: int
    bbox: list[float]
    confidence: float
    mime_type: str
    image_base64: str
    width: int
    height: int
    square: bool = True
    landmarks: list[list[float]] | None = None
    person_id: str | None = None
    name: str | None = None
    match_score: float | None = None
    matched: bool = False


class DetectResponse(BaseModel):
    request_id: str
    face_count: int
    image_width: int
    image_height: int
    annotated_image_base64: str
    annotated_mime_type: str
    faces: list[FaceOut]


class AttendanceEventOut(BaseModel):
    id: str
    timestamp: str
    person_id: str
    name: str
    matched: bool
    match_score: float
    source_request_id: str
    face_id: int | None = None


class AttendanceResponse(DetectResponse):
    attendance: list[AttendanceEventOut]


class PersonOut(BaseModel):
    id: str
    name: str
    sample_count: int
    created_at: str
    updated_at: str


class EnrollResponse(BaseModel):
    request_id: str
    person: PersonOut
    face_confidence: float
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorBody


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error(status: int, code: str, message: str, request_id: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"request_id": request_id, "error": {"code": code, "message": message}},
    )


def _request_id_from_request(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid.uuid4())


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    if not settings.auth_enabled:
        return
    if x_api_key != settings.api_key:
        rid = _request_id_from_request(request)
        raise _error(401, "unauthorized", "Invalid or missing X-API-Key", rid)


def _run_detect(
    image_bgr: Any,
    *,
    conf_thresh: float,
    padding: float,
    crop_format: Literal["jpeg", "png"],
    jpeg_quality: int,
    max_faces: int,
    include_landmarks: bool,
    square: bool,
    identify: bool,
    match_thresh: float,
    request_id: str,
) -> DetectResponse:
    height, width = image_bgr.shape[:2]
    need_landmarks = identify or include_landmarks
    detected = detector_service.detect(
        image_bgr,
        confidence_threshold=conf_thresh,
        max_faces=max_faces,
        include_landmarks=need_landmarks,
    )

    faces_out: list[FaceOut] = []
    labels: list[str] = []
    for idx, face in enumerate(detected):
        try:
            crop = crop_face(image_bgr, face.bbox, padding=padding, square=square)
            b64, mime = encode_image_base64(crop, crop_format=crop_format, jpeg_quality=jpeg_quality)
        except Exception as exc:  # noqa: BLE001
            raise _error(500, "processing_error", f"Failed to crop face {idx}: {exc}", request_id) from exc

        person_id = None
        name = None
        match_score = None
        matched = False
        if identify and face.landmarks is not None:
            try:
                emb = recognizer_service.embed(image_bgr, np.asarray(face.landmarks, dtype=np.float32))
                match = recognizer_service.match(emb, threshold=match_thresh)
                person_id = match.person_id
                name = match.name
                match_score = match.score
                matched = match.matched
            except Exception as exc:  # noqa: BLE001
                raise _error(500, "recognition_error", f"Failed to identify face {idx}: {exc}", request_id) from exc

        labels.append(name if matched and name else "unknown")

        ch, cw = crop.shape[:2]
        faces_out.append(
            FaceOut(
                id=idx,
                bbox=[round(v, 2) for v in face.bbox],
                confidence=round(face.confidence, 4),
                mime_type=mime,
                image_base64=b64,
                width=cw,
                height=ch,
                square=bool(square and cw == ch),
                landmarks=face.landmarks if include_landmarks else None,
                person_id=person_id,
                name=name,
                match_score=match_score,
                matched=matched,
            )
        )

    try:
        draw_labels = labels if identify else None
        boxed = draw_face_boxes(image_bgr, [f.bbox for f in faces_out], labels=draw_labels)
        annotated_b64, annotated_mime = encode_image_base64(
            boxed, crop_format=crop_format, jpeg_quality=jpeg_quality
        )
    except Exception as exc:  # noqa: BLE001
        raise _error(500, "processing_error", f"Failed to annotate image: {exc}", request_id) from exc

    return DetectResponse(
        request_id=request_id,
        face_count=len(faces_out),
        image_width=width,
        image_height=height,
        annotated_image_base64=annotated_b64,
        annotated_mime_type=annotated_mime,
        faces=faces_out,
    )


def _decode_upload(raw: bytes, request_id: str) -> Any:
    if not raw:
        raise _error(400, "missing_image", "Uploaded file is empty", request_id)
    if len(raw) > settings.max_upload_bytes:
        raise _error(
            413,
            "payload_too_large",
            f"Max upload size is {settings.max_upload_bytes} bytes",
            request_id,
        )
    try:
        return decode_image_bytes(raw)
    except ValueError as exc:
        raise _error(400, "invalid_image", str(exc), request_id) from exc


def _decode_b64(image_base64: str, request_id: str) -> Any:
    if not image_base64.strip():
        raise _error(400, "missing_image", "image_base64 is required", request_id)
    if len(image_base64) > settings.max_upload_bytes * 2:
        raise _error(
            413,
            "payload_too_large",
            f"Max upload size is {settings.max_upload_bytes} bytes",
            request_id,
        )
    try:
        return decode_image_base64(image_base64)
    except ValueError as exc:
        raise _error(400, "invalid_image", str(exc), request_id) from exc


def _validate_detect_params(
    conf_thresh: float,
    padding: float,
    max_faces: int,
    match_thresh: float,
    request_id: str,
) -> None:
    if not (0.0 <= conf_thresh <= 1.0) or padding < 0 or max_faces < 0:
        raise _error(422, "validation_error", "Invalid detection parameters", request_id)
    if not (0.0 <= match_thresh <= 1.0):
        raise _error(422, "validation_error", "Invalid match_thresh", request_id)


async def _enroll_from_image(
    *,
    name: str,
    raw: bytes,
    person_id: str | None,
    conf_thresh: float,
    request_id: str,
) -> EnrollResponse:
    if not name.strip():
        raise _error(400, "validation_error", "name is required", request_id)

    image_bgr = _decode_upload(raw, request_id)
    faces = detector_service.detect(
        image_bgr,
        confidence_threshold=conf_thresh,
        max_faces=5,
        include_landmarks=True,
    )
    if not faces:
        raise _error(400, "no_face", "No face found in enrollment image", request_id)
    face = faces[0]
    if face.landmarks is None:
        raise _error(400, "no_landmarks", "Face landmarks missing; cannot enroll", request_id)

    try:
        emb = recognizer_service.embed(image_bgr, np.asarray(face.landmarks, dtype=np.float32))
        person = people_store.enroll(name=name, embedding=emb, person_id=person_id or None)
    except KeyError as exc:
        raise _error(404, "person_not_found", str(exc), request_id) from exc
    except Exception as exc:  # noqa: BLE001
        raise _error(500, "enroll_error", f"Failed to enroll: {exc}", request_id) from exc

    return EnrollResponse(
        request_id=request_id,
        person=PersonOut(
            id=person.id,
            name=person.name,
            sample_count=len(person.embeddings),
            created_at=person.created_at,
            updated_at=person.updated_at,
        ),
        face_confidence=round(face.confidence, 4),
        message=f"Enrolled '{person.name}' ({person.id})",
    )


def _list_people() -> list[PersonOut]:
    return [
        PersonOut(
            id=p.id,
            name=p.name,
            sample_count=len(p.embeddings),
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in people_store.list_people()
    ]


def _delete_person(person_id: str, request_id: str) -> dict[str, Any]:
    if not people_store.delete(person_id):
        raise _error(404, "person_not_found", f"No person with id {person_id}", request_id)
    return {"request_id": request_id, "deleted": True, "person_id": person_id}


def _attendance_from_detect(detect: DetectResponse) -> AttendanceResponse:
    face_payloads = [
        {
            "matched": f.matched,
            "person_id": f.person_id,
            "name": f.name,
            "match_score": f.match_score,
            "face_id": f.id,
        }
        for f in detect.faces
    ]
    events = attendance_store.record(source_request_id=detect.request_id, faces=face_payloads)
    return AttendanceResponse(
        request_id=detect.request_id,
        face_count=detect.face_count,
        image_width=detect.image_width,
        image_height=detect.image_height,
        annotated_image_base64=detect.annotated_image_base64,
        annotated_mime_type=detect.annotated_mime_type,
        faces=detect.faces,
        attendance=[
            AttendanceEventOut(
                id=e.id,
                timestamp=e.timestamp,
                person_id=e.person_id,
                name=e.name,
                matched=e.matched,
                match_score=e.match_score,
                source_request_id=e.source_request_id,
                face_id=e.face_id,
            )
            for e in events
        ],
    )


def _form_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _form_float(raw: str | None, default: float) -> float:
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _form_int(raw: str | None, default: int) -> int:
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


async def _parse_detect_request(
    request: Request,
    *,
    request_id: str,
    force_identify: bool | None = None,
) -> DetectResponse:
    """Parse multipart or JSON body and run detection."""
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        body = DetectJsonRequest.model_validate(await request.json())
        identify = True if force_identify is True else body.identify
        _validate_detect_params(body.conf_thresh, body.padding, body.max_faces, body.match_thresh, request_id)
        image_bgr = _decode_b64(body.image_base64, request_id)
        return _run_detect(
            image_bgr,
            conf_thresh=body.conf_thresh,
            padding=body.padding,
            crop_format=body.crop_format,
            jpeg_quality=body.jpeg_quality,
            max_faces=body.max_faces,
            include_landmarks=body.include_landmarks,
            square=body.square,
            identify=identify,
            match_thresh=body.match_thresh,
            request_id=request_id,
        )

    form = await request.form()
    upload = form.get("image")
    if upload is None or not hasattr(upload, "read"):
        raise _error(400, "missing_image", "No file / no image_base64", request_id)

    conf_thresh = _form_float(form.get("conf_thresh"), 0.5)  # type: ignore[arg-type]
    padding = _form_float(form.get("padding"), 0.2)  # type: ignore[arg-type]
    crop_format_raw = str(form.get("crop_format") or "jpeg").lower()
    if crop_format_raw not in {"jpeg", "png"}:
        raise _error(422, "validation_error", "crop_format must be jpeg or png", request_id)
    crop_format: Literal["jpeg", "png"] = crop_format_raw  # type: ignore[assignment]
    jpeg_quality = _form_int(form.get("jpeg_quality"), 90)  # type: ignore[arg-type]
    max_faces = _form_int(form.get("max_faces"), 100)  # type: ignore[arg-type]
    include_landmarks = _form_bool(form.get("include_landmarks"), False)  # type: ignore[arg-type]
    square = _form_bool(form.get("square"), True)  # type: ignore[arg-type]
    identify = True if force_identify is True else _form_bool(form.get("identify"), True)  # type: ignore[arg-type]
    match_thresh = _form_float(form.get("match_thresh"), DEFAULT_MATCH_THRESHOLD)  # type: ignore[arg-type]

    _validate_detect_params(conf_thresh, padding, max_faces, match_thresh, request_id)
    raw = await upload.read()  # type: ignore[union-attr]
    image_bgr = _decode_upload(raw, request_id)
    return _run_detect(
        image_bgr,
        conf_thresh=conf_thresh,
        padding=padding,
        crop_format=crop_format,
        jpeg_quality=jpeg_quality,
        max_faces=max_faces,
        include_landmarks=include_landmarks,
        square=square,
        identify=identify,
        match_thresh=match_thresh,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Middleware & exception handlers
# ---------------------------------------------------------------------------


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()

        # Inflight concurrency guard (skip cheap static/health probes)
        path = request.url.path
        gated = path.startswith("/v1/") or path.startswith("/v2/")
        acquired = False
        if gated:
            acquired = _inflight.acquire(blocking=False)
            if not acquired:
                body = {
                    "request_id": request_id,
                    "error": {"code": "overloaded", "message": "Too many concurrent requests"},
                }
                return JSONResponse(status_code=503, content=body, headers={"X-Request-Id": request_id})

        try:
            response = await call_next(request)
        finally:
            if acquired:
                _inflight.release()

        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-Id"] = request_id
        logger.info(
            "request_id=%s method=%s path=%s status=%s ms=%.1f",
            request_id,
            request.method,
            path,
            response.status_code,
            elapsed_ms,
        )
        return response


app.add_middleware(RequestContextMiddleware)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = _request_id_from_request(request)
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        body = detail
        if "request_id" not in body:
            body = {**body, "request_id": request_id}
    else:
        body = {
            "request_id": request_id,
            "error": {"code": "http_error", "message": str(detail)},
        }
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = _request_id_from_request(request)
    return JSONResponse(
        status_code=422,
        content={
            "request_id": request_id,
            "error": {"code": "validation_error", "message": str(exc.errors())},
        },
    )


# ---------------------------------------------------------------------------
# Startup / health / UI
# ---------------------------------------------------------------------------


@app.on_event("startup")
def _startup() -> None:
    detector_service.warmup()
    recognizer_service.warmup()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "detector_loaded": detector_service.ready(),
        "recognizer_loaded": recognizer_service.ready(),
        "people_count": len(people_store.list_people()),
        "attendance_count": attendance_store.count(),
        "auth_enabled": settings.auth_enabled,
        "engine": "whozit/SCRFD+ArcFace",
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/config.js", include_in_schema=False)
def config_js() -> Response:
    """Bootstrap browser UI with API key when auth is enabled (same-origin UI only)."""
    key = settings.api_key or ""
    escaped = (
        key.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "")
        .replace("\n", "")
    )
    return Response(
        content=f'window.WHOZIT_DEFAULT_API_KEY = "{escaped}";\n',
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


# ---------------------------------------------------------------------------
# v1 detect
# ---------------------------------------------------------------------------


@app.post(
    "/v1/detect",
    response_model=DetectResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    dependencies=[Depends(require_api_key)],
)
async def detect(request: Request) -> DetectResponse:
    """Detect faces (multipart `image` or JSON `image_base64`). identify=true attaches names."""
    return await _parse_detect_request(request, request_id=_request_id_from_request(request))


@app.post(
    "/v1/detect/json",
    response_model=DetectResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    dependencies=[Depends(require_api_key)],
)
async def detect_json(request: Request, body: DetectJsonRequest) -> DetectResponse:
    """Alias for JSON detect (same as POST /v1/detect with application/json)."""
    request_id = _request_id_from_request(request)
    _validate_detect_params(body.conf_thresh, body.padding, body.max_faces, body.match_thresh, request_id)
    image_bgr = _decode_b64(body.image_base64, request_id)
    return _run_detect(
        image_bgr,
        conf_thresh=body.conf_thresh,
        padding=body.padding,
        crop_format=body.crop_format,
        jpeg_quality=body.jpeg_quality,
        max_faces=body.max_faces,
        include_landmarks=body.include_landmarks,
        square=body.square,
        identify=body.identify,
        match_thresh=body.match_thresh,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# v1 people (kept for UI / existing clients)
# ---------------------------------------------------------------------------


@app.post(
    "/v1/enroll",
    response_model=EnrollResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    dependencies=[Depends(require_api_key)],
)
async def enroll_person_v1(
    request: Request,
    name: str = Form(..., description="Display name"),
    image: UploadFile = File(..., description="Clear face photo of this person"),
    person_id: str | None = Form(None, description="Optional existing id to add another sample"),
    conf_thresh: float = Form(0.5),
) -> EnrollResponse:
    request_id = _request_id_from_request(request)
    raw = await image.read()
    return await _enroll_from_image(
        name=name, raw=raw, person_id=person_id, conf_thresh=conf_thresh, request_id=request_id
    )


@app.get("/v1/people", response_model=list[PersonOut], dependencies=[Depends(require_api_key)])
def list_people_v1() -> list[PersonOut]:
    return _list_people()


@app.delete("/v1/people/{person_id}", dependencies=[Depends(require_api_key)])
def delete_person_v1(person_id: str, request: Request) -> dict[str, Any]:
    return _delete_person(person_id, _request_id_from_request(request))


# ---------------------------------------------------------------------------
# v2 — PRD identity / attendance surface
# ---------------------------------------------------------------------------


@app.post(
    "/v2/enroll",
    response_model=EnrollResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    dependencies=[Depends(require_api_key)],
)
async def enroll_person_v2(
    request: Request,
    name: str = Form(..., description="Display name"),
    image: UploadFile = File(..., description="Clear face photo of this person"),
    person_id: str | None = Form(None, description="Optional existing id to add another sample"),
    conf_thresh: float = Form(0.5),
) -> EnrollResponse:
    request_id = _request_id_from_request(request)
    raw = await image.read()
    return await _enroll_from_image(
        name=name, raw=raw, person_id=person_id, conf_thresh=conf_thresh, request_id=request_id
    )


@app.get("/v2/people", response_model=list[PersonOut], dependencies=[Depends(require_api_key)])
def list_people_v2() -> list[PersonOut]:
    return _list_people()


@app.delete("/v2/people/{person_id}", dependencies=[Depends(require_api_key)])
def delete_person_v2(person_id: str, request: Request) -> dict[str, Any]:
    return _delete_person(person_id, _request_id_from_request(request))


@app.post(
    "/v2/recognize",
    response_model=DetectResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    dependencies=[Depends(require_api_key)],
)
async def recognize(request: Request) -> DetectResponse:
    """Detect + always match identities (name or unknown)."""
    return await _parse_detect_request(
        request, request_id=_request_id_from_request(request), force_identify=True
    )


@app.post(
    "/v2/attendance",
    response_model=AttendanceResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    dependencies=[Depends(require_api_key)],
)
async def mark_attendance(request: Request) -> AttendanceResponse:
    """Detect + match + record attendance events for matched people."""
    detect_result = await _parse_detect_request(
        request, request_id=_request_id_from_request(request), force_identify=True
    )
    return _attendance_from_detect(detect_result)


@app.get("/v2/attendance", response_model=list[AttendanceEventOut], dependencies=[Depends(require_api_key)])
def list_attendance(limit: int = 100) -> list[AttendanceEventOut]:
    events = attendance_store.list_events(limit=limit)
    return [
        AttendanceEventOut(
            id=e.id,
            timestamp=e.timestamp,
            person_id=e.person_id,
            name=e.name,
            matched=e.matched,
            match_score=e.match_score,
            source_request_id=e.source_request_id,
            face_id=e.face_id,
        )
        for e in events
    ]


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
