"""Whozit API — detect, enroll, recognize, daily register."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
import threading
import uuid
from contextlib import asynccontextmanager
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

from app import db as db_mod
from app.config import settings
from app.crop_crypto import MODEL_VERSION
from app.detector import detector_service
from app.image_utils import (
    crop_face,
    decode_image_base64,
    decode_image_bytes,
    draw_face_boxes,
    encode_image_base64,
)
from app.recognizer import DEFAULT_MATCH_THRESHOLD, Candidate, recognizer_service
from app.reembed import ReembedResult, reembed_all
from app.org_store import (
    class_scope_key,
    org_store,
)
from app.ref_store import (
    normalize_scope_key,
    ref_store,
    validate_attendance_date,
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
SESSION_COOKIE = "whozit_session"

logger = logging.getLogger("whozit.api")
logging.basicConfig(level=logging.INFO, format="%(message)s")

_inflight = threading.Semaphore(settings.max_inflight)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.require_crop_key and settings.crop_key_insecure:
        raise RuntimeError(
            "WHOZIT_CROP_KEY is required when auth is enabled (set WHOZIT_REQUIRE_CROP_KEY=0 to override)"
        )
    db_mod.init_db()
    if settings.migrate_v3_path and settings.migrate_v3_path.exists():
        from app.migrate_v3 import migrate_v3_db

        stats = migrate_v3_db(
            settings.migrate_v3_path,
            settings.sqlite_path,
            crop_key=settings.crop_key,
        )
        logger.info("v3 migration: %s", stats)
    from app.org_store import OrgStore

    org_stats = OrgStore(settings.sqlite_path).backfill_from_refs()
    if org_stats["students"]:
        logger.info("org backfill: %s", org_stats)
    purged = ref_store.purge_rec_log()
    if purged:
        logger.info("rec_log purge: deleted %s rows", purged)
    detector_service.warmup()
    recognizer_service.warmup()
    yield


app = FastAPI(
    title="Whozit",
    description="Standalone face attendance: enroll by name, recognize in a scope, save a daily register.",
    version="4.0.0",
    lifespan=lifespan,
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


class CandidateOut(BaseModel):
    ref_id: str
    name: str
    score: float


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
    matched: bool = False
    ref_id: str | None = None
    name: str | None = None
    score: float | None = None
    margin: float | None = None
    candidates: list[CandidateOut] = Field(default_factory=list)


class DetectResponse(BaseModel):
    request_id: str
    face_count: int
    image_width: int
    image_height: int
    annotated_image_base64: str
    annotated_mime_type: str
    faces: list[FaceOut]


class RefOut(BaseModel):
    ref_id: str
    scope_key: str
    name: str
    sample_count: int
    created_at: str
    updated_at: str


class EnrollResponse(BaseModel):
    request_id: str
    ref: RefOut
    face_confidence: float
    message: str


class RecognizeResponse(DetectResponse):
    scope_key: str
    unknown_count: int


class DailyRollRequest(BaseModel):
    scope_key: str
    date: str = Field(..., description="YYYY-MM-DD (client timezone)")
    present_ref_ids: list[str] = Field(default_factory=list)


class DailyPresentOut(BaseModel):
    ref_id: str
    name: str


class DailyRollOut(BaseModel):
    id: str
    scope_key: str
    date: str
    present: list[DailyPresentOut]
    created_at: str
    updated_at: str


class DayStatusOut(BaseModel):
    scope_key: str
    date: str
    has_roll: bool
    present: list[DailyPresentOut]
    absent: list[DailyPresentOut]
    present_count: int
    absent_count: int
    roster_count: int
    attendance_pct: float | None = None


class MoveRefRequest(BaseModel):
    scope_key: str
    new_scope_key: str


class MoveScopeRequest(BaseModel):
    old_scope_key: str
    new_scope_key: str


class RefPatchRequest(BaseModel):
    name: str


class ReembedRequest(BaseModel):
    scope_key: str | None = None
    force: bool = False


class WipeConfirm(BaseModel):
    confirm: str = Field(..., description='Must be "DELETE ALL DATA"')


class SchoolCreate(BaseModel):
    country: str
    province: str
    emis: str
    name: str | None = None


class ClassCreate(BaseModel):
    country: str
    province: str
    emis: str
    grade: str
    school_name: str | None = None


class SchoolOut(BaseModel):
    id: int
    country: str
    province: str
    emis: str
    name: str | None = None


class ClassOut(BaseModel):
    id: int
    school_id: int
    grade: str
    scope_key: str
    country: str
    province: str
    emis: str


class StudentOut(BaseModel):
    student_id: str
    name: str
    seq: int
    school_id: int
    class_id: int
    country: str
    province: str
    emis: str
    grade: str
    scope_key: str
    sample_count: int
    created_at: str
    updated_at: str


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorBody


class SampleOut(BaseModel):
    id: int
    scope_key: str
    ref_id: str
    model_version: str
    quality: float | None
    created_at: str
    has_crop: bool


class RecLogOut(BaseModel):
    id: int
    scope_key: str
    ref_id: str
    name: str
    score: float
    margin: float | None
    model_version: str
    timestamp: str
    source_request_id: str | None


class ReembedOut(BaseModel):
    request_id: str
    updated: int
    skipped: int
    failed: int
    details: list[str]


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


def _session_mac(expiry: str) -> str:
    key = (settings.api_key or "").encode("utf-8")
    return hmac.new(key, expiry.encode("utf-8"), hashlib.sha256).hexdigest()


def make_session_value() -> str:
    expiry = str(int(time.time()) + settings.session_ttl_seconds)
    return f"{expiry}.{_session_mac(expiry)}"


def session_is_valid(value: str | None) -> bool:
    if not value or not settings.api_key or "." not in value:
        return False
    expiry, mac = value.split(".", 1)
    try:
        exp = int(expiry)
    except ValueError:
        return False
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(mac, _session_mac(expiry))


async def require_auth(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    if not settings.auth_enabled:
        return
    if x_api_key == settings.api_key:
        return
    if session_is_valid(request.cookies.get(SESSION_COOKIE)):
        return
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
    request_id: str,
) -> DetectResponse:
    height, width = image_bgr.shape[:2]
    detected = detector_service.detect(
        image_bgr,
        confidence_threshold=conf_thresh,
        max_faces=max_faces,
        include_landmarks=include_landmarks,
    )

    faces_out: list[FaceOut] = []
    for idx, face in enumerate(detected):
        try:
            crop = crop_face(image_bgr, face.bbox, padding=padding, square=square)
            b64, mime = encode_image_base64(crop, crop_format=crop_format, jpeg_quality=jpeg_quality)
        except Exception as exc:  # noqa: BLE001
            raise _error(500, "processing_error", f"Failed to crop face {idx}: {exc}", request_id) from exc

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
            )
        )

    try:
        boxed = draw_face_boxes(image_bgr, [f.bbox for f in faces_out], labels=None)
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
    request_id: str,
    match_thresh: float | None = None,
) -> None:
    if not (0.0 <= conf_thresh <= 1.0) or padding < 0 or max_faces < 0:
        raise _error(422, "validation_error", "Invalid detection parameters", request_id)
    if match_thresh is not None and not (0.0 <= match_thresh <= 1.0):
        raise _error(422, "validation_error", "Invalid match_thresh", request_id)


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


async def _parse_detect_request(request: Request, *, request_id: str) -> DetectResponse:
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        body = DetectJsonRequest.model_validate(await request.json())
        _validate_detect_params(body.conf_thresh, body.padding, body.max_faces, request_id)
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

    _validate_detect_params(conf_thresh, padding, max_faces, request_id)
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
        request_id=request_id,
    )


def _parse_scope_key(raw: str | None, request_id: str) -> str:
    if raw is None or not str(raw).strip():
        raise _error(400, "validation_error", "scope_key is required", request_id)
    try:
        return normalize_scope_key(str(raw))
    except ValueError as exc:
        raise _error(422, "validation_error", str(exc), request_id) from exc


def _candidates_out(cands: list[Candidate]) -> list[CandidateOut]:
    return [CandidateOut(ref_id=c.ref_id, name=c.name, score=c.score) for c in cands]


def _ref_out(ref) -> RefOut:
    return RefOut(
        ref_id=ref.ref_id,
        scope_key=ref.scope_key,
        name=ref.name,
        sample_count=ref.sample_count,
        created_at=ref.created_at,
        updated_at=ref.updated_at,
    )


def _check_gallery_version(scope_key: str, request_id: str) -> None:
    raw = ref_store.gallery_for_scope(scope_key)
    any_sample = False
    any_live = False
    for item in raw:
        for sample in item.samples:
            any_sample = True
            if sample.model_version == MODEL_VERSION:
                any_live = True
    if any_sample and not any_live:
        raise _error(
            409,
            "model_version_mismatch",
            f"Gallery embeddings are not {MODEL_VERSION}; re-embed crops or re-enroll",
            request_id,
        )


# ---------------------------------------------------------------------------
# Middleware & exception handlers
# ---------------------------------------------------------------------------


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()

        path = request.url.path
        gated = path in {"/detect", "/enroll", "/recognize"} or path.startswith("/detect")
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
# Health / UI / session
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "detector_loaded": detector_service.ready(),
        "recognizer_loaded": recognizer_service.ready(),
        "ref_count": ref_store.count_refs(),
        "auth_enabled": settings.auth_enabled,
        "model_version": MODEL_VERSION,
        "engine": "whozit/SCRFD+ArcFace",
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/config.js", include_in_schema=False)
def config_js() -> Response:
    """UI bootstrap placeholder — never embeds the API key in browser-visible JS."""
    return Response(
        content="window.WHOZIT_DEFAULT_API_KEY = \"\";\n",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.post("/session")
async def open_session(request: Request) -> JSONResponse:
    """Exchange an API key (JSON body or X-API-Key) for a short-lived httpOnly cookie."""
    request_id = _request_id_from_request(request)
    if not settings.auth_enabled:
        return JSONResponse({"request_id": request_id, "auth_enabled": False, "ok": True})
    header_key = request.headers.get("x-api-key")
    body_key = None
    try:
        payload = await request.json()
        if isinstance(payload, dict):
            body_key = payload.get("api_key")
    except Exception:  # noqa: BLE001
        payload = None
    supplied = header_key or body_key
    if supplied != settings.api_key:
        raise _error(401, "unauthorized", "Invalid or missing X-API-Key", request_id)
    response = JSONResponse({"request_id": request_id, "ok": True})
    response.set_cookie(
        SESSION_COOKIE,
        make_session_value(),
        httponly=True,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    return response


@app.delete("/session")
def close_session(request: Request) -> JSONResponse:
    response = JSONResponse({"request_id": _request_id_from_request(request), "ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


# ---------------------------------------------------------------------------
# Detect (stateless)
# ---------------------------------------------------------------------------


@app.post(
    "/detect",
    response_model=DetectResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    dependencies=[Depends(require_auth)],
)
async def detect(request: Request) -> DetectResponse:
    """Detect faces (multipart `image` or JSON `image_base64`). No identity."""
    return await _parse_detect_request(request, request_id=_request_id_from_request(request))


# ---------------------------------------------------------------------------
# Enroll / refs
# ---------------------------------------------------------------------------


@app.post(
    "/enroll",
    response_model=EnrollResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    dependencies=[Depends(require_auth)],
)
async def enroll(
    request: Request,
    name: str = Form(..., description="Display name (not unique)"),
    image: UploadFile = File(..., description="Clear face photo"),
    scope_key: str | None = Form(None, description="Class path country/province/emis/grade"),
    country: str | None = Form(None),
    province: str | None = Form(None),
    emis: str | None = Form(None),
    grade: str | None = Form(None),
    ref_id: str | None = Form(None, description="Existing student_id; minted if omitted"),
    student_id: str | None = Form(None),
    conf_thresh: float = Form(0.5),
) -> EnrollResponse:
    request_id = _request_id_from_request(request)
    if not name.strip():
        raise _error(400, "validation_error", "name is required", request_id)
    try:
        if country and province and emis and grade:
            slug = class_scope_key(country, province, emis, grade)
        elif scope_key:
            slug = _parse_scope_key(scope_key, request_id)
        else:
            raise _error(
                400,
                "validation_error",
                "scope_key or country+province+emis+grade is required",
                request_id,
            )
    except ValueError as exc:
        raise _error(400, "validation_error", str(exc), request_id) from exc
    identity = (student_id or ref_id or "").strip() or None
    raw = await image.read()
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
    if settings.min_enroll_quality is not None and face.confidence < settings.min_enroll_quality:
        raise _error(
            422,
            "quality_too_low",
            f"Face detection confidence {face.confidence:.3f} below "
            f"WHOZIT_MIN_ENROLL_QUALITY={settings.min_enroll_quality}",
            request_id,
        )

    try:
        landmarks = np.asarray(face.landmarks, dtype=np.float32)
        emb = recognizer_service.embed(image_bgr, landmarks)
        crop_jpeg = recognizer_service.aligned_crop_jpeg(image_bgr, landmarks)
        person = ref_store.enroll(
            name=name,
            scope_key=slug,
            embedding=emb,
            crop_jpeg=crop_jpeg,
            quality=float(face.confidence),
            source_request_id=request_id,
            ref_id=identity,
            model_version=MODEL_VERSION,
        )
        recognizer_service.invalidate_scope(slug)
    except ValueError as exc:
        raise _error(422, "validation_error", str(exc), request_id) from exc
    except Exception as exc:  # noqa: BLE001
        raise _error(500, "enroll_error", f"Failed to enroll: {exc}", request_id) from exc

    return EnrollResponse(
        request_id=request_id,
        ref=_ref_out(person),
        face_confidence=round(face.confidence, 4),
        message=f"Enrolled '{person.name}' in {person.scope_key} ({person.ref_id})",
    )


@app.get("/refs", response_model=list[RefOut], dependencies=[Depends(require_auth)])
def list_refs(request: Request, scope_key: str) -> list[RefOut]:
    request_id = _request_id_from_request(request)
    slug = _parse_scope_key(scope_key, request_id)
    return [_ref_out(p) for p in ref_store.list_refs(slug)]


@app.patch("/refs/{ref_id}", response_model=RefOut, dependencies=[Depends(require_auth)])
def patch_ref(ref_id: str, request: Request, body: RefPatchRequest, scope_key: str) -> RefOut:
    request_id = _request_id_from_request(request)
    slug = _parse_scope_key(scope_key, request_id)
    try:
        ref = ref_store.update_ref_name(slug, ref_id, body.name)
    except KeyError as exc:
        raise _error(404, "person_not_found", str(exc), request_id) from exc
    except ValueError as exc:
        raise _error(422, "validation_error", str(exc), request_id) from exc
    return _ref_out(ref)


@app.get("/refs/{ref_id}/samples", response_model=list[SampleOut], dependencies=[Depends(require_auth)])
def list_ref_samples(ref_id: str, request: Request, scope_key: str) -> list[SampleOut]:
    request_id = _request_id_from_request(request)
    slug = _parse_scope_key(scope_key, request_id)
    if ref_store.get(slug, ref_id) is None:
        raise _error(404, "person_not_found", f"No ref {ref_id} in {slug}", request_id)
    return [
        SampleOut(
            id=s.id,
            scope_key=s.scope_key,
            ref_id=s.ref_id,
            model_version=s.model_version,
            quality=s.quality,
            created_at=s.created_at,
            has_crop=s.has_crop,
        )
        for s in ref_store.list_samples(slug, ref_id)
    ]


@app.delete("/refs/{ref_id}", dependencies=[Depends(require_auth)])
def delete_ref(ref_id: str, request: Request, scope_key: str) -> dict[str, Any]:
    request_id = _request_id_from_request(request)
    slug = _parse_scope_key(scope_key, request_id)
    if not ref_store.delete_ref(slug, ref_id):
        raise _error(404, "person_not_found", f"No ref {ref_id} in {slug}", request_id)
    recognizer_service.invalidate_scope(slug)
    return {"request_id": request_id, "deleted": True, "scope_key": slug, "ref_id": ref_id}


@app.delete("/samples/{sample_id}", dependencies=[Depends(require_auth)])
def delete_sample(sample_id: int, request: Request) -> dict[str, Any]:
    request_id = _request_id_from_request(request)
    loc = ref_store.delete_sample(sample_id)
    if loc is None:
        raise _error(404, "not_found", f"No sample {sample_id}", request_id)
    slug, rid = loc
    recognizer_service.invalidate_scope(slug)
    return {
        "request_id": request_id,
        "deleted": True,
        "sample_id": sample_id,
        "scope_key": slug,
        "ref_id": rid,
    }


@app.post("/refs/{ref_id}/move", response_model=RefOut, dependencies=[Depends(require_auth)])
def move_ref(ref_id: str, request: Request, body: MoveRefRequest) -> RefOut:
    request_id = _request_id_from_request(request)
    slug = _parse_scope_key(body.scope_key, request_id)
    new_slug = _parse_scope_key(body.new_scope_key, request_id)
    try:
        ref = ref_store.move_ref(slug, ref_id, new_slug)
    except KeyError as exc:
        raise _error(404, "person_not_found", str(exc), request_id) from exc
    except ValueError as exc:
        raise _error(409, "conflict", str(exc), request_id) from exc
    recognizer_service.invalidate_scope(slug)
    recognizer_service.invalidate_scope(new_slug)
    return _ref_out(ref)


@app.get("/scopes", response_model=list[str], dependencies=[Depends(require_auth)])
def list_scopes() -> list[str]:
    return ref_store.list_scopes()


def _student_out(s) -> StudentOut:
    return StudentOut(
        student_id=s.student_id,
        name=s.name,
        seq=s.seq,
        school_id=s.school_id,
        class_id=s.class_id,
        country=s.country_code,
        province=s.province_code,
        emis=s.emis,
        grade=s.grade,
        scope_key=s.scope_key,
        sample_count=s.sample_count,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


@app.get("/org/countries", dependencies=[Depends(require_auth)])
def org_countries() -> list[str]:
    return org_store.list_countries()


@app.get("/org/provinces", dependencies=[Depends(require_auth)])
def org_provinces(country: str) -> list[str]:
    try:
        return org_store.list_provinces(country)
    except ValueError as exc:
        raise _error(400, "validation_error", str(exc), "local") from exc


@app.get("/org/schools", response_model=list[SchoolOut], dependencies=[Depends(require_auth)])
def org_schools(country: str, province: str) -> list[SchoolOut]:
    try:
        rows = org_store.list_schools(country, province)
    except ValueError as exc:
        raise _error(400, "validation_error", str(exc), "local") from exc
    return [
        SchoolOut(id=s.id, country=s.country_code, province=s.province_code, emis=s.emis, name=s.name)
        for s in rows
    ]


@app.post("/org/schools", response_model=SchoolOut, dependencies=[Depends(require_auth)])
def org_create_school(request: Request, body: SchoolCreate) -> SchoolOut:
    request_id = _request_id_from_request(request)
    try:
        school = org_store.ensure_school(
            country=body.country, province=body.province, emis=body.emis, name=body.name
        )
    except ValueError as exc:
        raise _error(400, "validation_error", str(exc), request_id) from exc
    return SchoolOut(
        id=school.id,
        country=school.country_code,
        province=school.province_code,
        emis=school.emis,
        name=school.name,
    )


@app.get("/org/classes", response_model=list[ClassOut], dependencies=[Depends(require_auth)])
def org_classes(school_id: int) -> list[ClassOut]:
    try:
        rows = org_store.list_classes(school_id)
    except KeyError as exc:
        raise _error(404, "not_found", str(exc), "local") from exc
    return [
        ClassOut(
            id=c.id,
            school_id=c.school_id,
            grade=c.grade,
            scope_key=c.scope_key,
            country=c.country_code,
            province=c.province_code,
            emis=c.emis,
        )
        for c in rows
    ]


@app.post("/org/classes", response_model=ClassOut, dependencies=[Depends(require_auth)])
def org_create_class(request: Request, body: ClassCreate) -> ClassOut:
    request_id = _request_id_from_request(request)
    try:
        klass = org_store.ensure_class(
            country=body.country,
            province=body.province,
            emis=body.emis,
            grade=body.grade,
            school_name=body.school_name,
        )
    except ValueError as exc:
        raise _error(400, "validation_error", str(exc), request_id) from exc
    return ClassOut(
        id=klass.id,
        school_id=klass.school_id,
        grade=klass.grade,
        scope_key=klass.scope_key,
        country=klass.country_code,
        province=klass.province_code,
        emis=klass.emis,
    )


@app.get("/students", response_model=list[StudentOut], dependencies=[Depends(require_auth)])
def list_students(
    request: Request,
    school_id: int | None = None,
    class_id: int | None = None,
) -> list[StudentOut]:
    request_id = _request_id_from_request(request)
    try:
        rows = org_store.list_students(school_id=school_id, class_id=class_id)
    except ValueError as exc:
        raise _error(400, "validation_error", str(exc), request_id) from exc
    return [_student_out(s) for s in rows]


@app.get("/students/{student_id:path}", response_model=StudentOut, dependencies=[Depends(require_auth)])
def get_student(student_id: str, request: Request) -> StudentOut:
    request_id = _request_id_from_request(request)
    row = org_store.get_student(student_id)
    if row is None:
        raise _error(404, "person_not_found", f"No student {student_id}", request_id)
    return _student_out(row)


@app.post("/scopes/move", dependencies=[Depends(require_auth)])
def move_scope(request: Request, body: MoveScopeRequest) -> dict[str, Any]:
    request_id = _request_id_from_request(request)
    old = _parse_scope_key(body.old_scope_key, request_id)
    new = _parse_scope_key(body.new_scope_key, request_id)
    try:
        n = ref_store.move_scope(old, new)
    except ValueError as exc:
        raise _error(409, "conflict", str(exc), request_id) from exc
    recognizer_service.invalidate_scope(old)
    recognizer_service.invalidate_scope(new)
    return {"request_id": request_id, "moved": n, "old_scope_key": old, "new_scope_key": new}


@app.get("/internal/rec_log", response_model=list[RecLogOut], dependencies=[Depends(require_auth)])
def internal_rec_log(
    request: Request,
    scope_key: str | None = None,
    limit: int = 100,
) -> list[RecLogOut]:
    request_id = _request_id_from_request(request)
    if scope_key:
        _parse_scope_key(scope_key, request_id)
    rows = ref_store.list_rec_log(scope_key, limit=limit)
    return [
        RecLogOut(
            id=r.id,
            scope_key=r.scope_key,
            ref_id=r.ref_id,
            name=r.name,
            score=r.score,
            margin=r.margin,
            model_version=r.model_version,
            timestamp=r.timestamp,
            source_request_id=r.source_request_id,
        )
        for r in rows
    ]


@app.post("/admin/reembed", response_model=ReembedOut, dependencies=[Depends(require_auth)])
def admin_reembed(request: Request, body: ReembedRequest | None = None) -> ReembedOut:
    request_id = _request_id_from_request(request)
    scope_key = None
    force = False
    if body is not None:
        scope_key = body.scope_key
        force = body.force
    if scope_key:
        scope_key = _parse_scope_key(scope_key, request_id)
    result: ReembedResult = reembed_all(ref_store, recognizer_service, scope_key=scope_key, force=force)
    return ReembedOut(
        request_id=request_id,
        updated=result.updated,
        skipped=result.skipped,
        failed=result.failed,
        details=result.details[:50],
    )


@app.post("/admin/wipe", dependencies=[Depends(require_auth)])
def admin_wipe(request: Request, body: WipeConfirm) -> dict[str, Any]:
    request_id = _request_id_from_request(request)
    if body.confirm != "DELETE ALL DATA":
        raise _error(422, "validation_error", 'confirm must be exactly "DELETE ALL DATA"', request_id)
    stats = ref_store.wipe_program_data()
    recognizer_service.invalidate_all()
    return {"request_id": request_id, **stats}


# ---------------------------------------------------------------------------
# Recognize
# ---------------------------------------------------------------------------


def _run_recognize(
    image_bgr: Any,
    *,
    scope_key: str,
    conf_thresh: float,
    padding: float,
    crop_format: Literal["jpeg", "png"],
    jpeg_quality: int,
    max_faces: int,
    include_landmarks: bool,
    square: bool,
    match_thresh: float,
    request_id: str,
) -> RecognizeResponse:
    _check_gallery_version(scope_key, request_id)
    height, width = image_bgr.shape[:2]
    detected = detector_service.detect(
        image_bgr,
        confidence_threshold=conf_thresh,
        max_faces=max_faces,
        include_landmarks=True,
    )

    embeddings: list[np.ndarray] = []
    embed_ok: list[bool] = []
    for face in detected:
        if face.landmarks is None:
            embeddings.append(np.zeros(1, dtype=np.float32))
            embed_ok.append(False)
            continue
        try:
            emb = recognizer_service.embed(image_bgr, np.asarray(face.landmarks, dtype=np.float32))
            embeddings.append(emb)
            embed_ok.append(True)
        except Exception as exc:  # noqa: BLE001
            raise _error(500, "recognition_error", f"Failed to embed face: {exc}", request_id) from exc

    live_embs = [e for e, ok in zip(embeddings, embed_ok) if ok]
    assigned = recognizer_service.assign_faces(live_embs, scope_key, threshold=match_thresh)
    assign_iter = iter(assigned)

    faces_out: list[FaceOut] = []
    labels: list[str] = []
    matches_for_log: list[dict] = []
    for idx, face in enumerate(detected):
        try:
            crop = crop_face(image_bgr, face.bbox, padding=padding, square=square)
            b64, mime = encode_image_base64(crop, crop_format=crop_format, jpeg_quality=jpeg_quality)
        except Exception as exc:  # noqa: BLE001
            raise _error(500, "processing_error", f"Failed to crop face {idx}: {exc}", request_id) from exc

        match = next(assign_iter) if embed_ok[idx] else None
        matched = bool(match and match.matched)
        name = match.name if match else None
        labels.append(name if matched and name else "unknown")
        if matched and match is not None:
            matches_for_log.append(
                {"ref_id": match.ref_id, "score": match.score, "margin": match.margin}
            )

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
                matched=matched,
                ref_id=match.ref_id if match else None,
                name=name,
                score=match.score if match else None,
                margin=match.margin if match else None,
                candidates=_candidates_out(match.candidates) if match else [],
            )
        )

    if matches_for_log:
        ref_store.record_matches(
            scope_key=scope_key,
            source_request_id=request_id,
            matches=matches_for_log,
            model_version=MODEL_VERSION,
        )

    try:
        boxed = draw_face_boxes(image_bgr, [f.bbox for f in faces_out], labels=labels)
        annotated_b64, annotated_mime = encode_image_base64(
            boxed, crop_format=crop_format, jpeg_quality=jpeg_quality
        )
    except Exception as exc:  # noqa: BLE001
        raise _error(500, "processing_error", f"Failed to annotate image: {exc}", request_id) from exc

    unknown_count = sum(1 for f in faces_out if not f.matched)
    return RecognizeResponse(
        request_id=request_id,
        face_count=len(faces_out),
        image_width=width,
        image_height=height,
        annotated_image_base64=annotated_b64,
        annotated_mime_type=annotated_mime,
        faces=faces_out,
        scope_key=scope_key,
        unknown_count=unknown_count,
    )


@app.post(
    "/recognize",
    response_model=RecognizeResponse,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    dependencies=[Depends(require_auth)],
)
async def recognize(request: Request) -> RecognizeResponse:
    request_id = _request_id_from_request(request)
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        body = await request.json()
        slug = _parse_scope_key(body.get("scope_key") or body.get("class_slug"), request_id)
        conf_thresh = float(body.get("conf_thresh", 0.5))
        padding = float(body.get("padding", 0.2))
        crop_format_raw = str(body.get("crop_format") or "jpeg").lower()
        if crop_format_raw not in {"jpeg", "png"}:
            raise _error(422, "validation_error", "crop_format must be jpeg or png", request_id)
        crop_format: Literal["jpeg", "png"] = crop_format_raw  # type: ignore[assignment]
        jpeg_quality = int(body.get("jpeg_quality", 90))
        max_faces = int(body.get("max_faces", 100))
        include_landmarks = bool(body.get("include_landmarks", False))
        square = bool(body.get("square", True))
        match_thresh = float(body.get("match_thresh", DEFAULT_MATCH_THRESHOLD))
        _validate_detect_params(conf_thresh, padding, max_faces, request_id, match_thresh)
        image_bgr = _decode_b64(str(body.get("image_base64") or ""), request_id)
        return _run_recognize(
            image_bgr,
            scope_key=slug,
            conf_thresh=conf_thresh,
            padding=padding,
            crop_format=crop_format,
            jpeg_quality=jpeg_quality,
            max_faces=max_faces,
            include_landmarks=include_landmarks,
            square=square,
            match_thresh=match_thresh,
            request_id=request_id,
        )

    form = await request.form()
    slug = _parse_scope_key(form.get("scope_key") or form.get("class_slug"), request_id)  # type: ignore[arg-type]
    upload = form.get("image")
    if upload is None or not hasattr(upload, "read"):
        raise _error(400, "missing_image", "No file / no image_base64", request_id)
    conf_thresh = _form_float(form.get("conf_thresh"), 0.5)  # type: ignore[arg-type]
    padding = _form_float(form.get("padding"), 0.2)  # type: ignore[arg-type]
    crop_format_raw = str(form.get("crop_format") or "jpeg").lower()
    if crop_format_raw not in {"jpeg", "png"}:
        raise _error(422, "validation_error", "crop_format must be jpeg or png", request_id)
    crop_format = crop_format_raw  # type: ignore[assignment]
    jpeg_quality = _form_int(form.get("jpeg_quality"), 90)  # type: ignore[arg-type]
    max_faces = _form_int(form.get("max_faces"), 100)  # type: ignore[arg-type]
    include_landmarks = _form_bool(form.get("include_landmarks"), False)  # type: ignore[arg-type]
    square = _form_bool(form.get("square"), True)  # type: ignore[arg-type]
    match_thresh = _form_float(form.get("match_thresh"), DEFAULT_MATCH_THRESHOLD)  # type: ignore[arg-type]
    _validate_detect_params(conf_thresh, padding, max_faces, request_id, match_thresh)
    raw = await upload.read()  # type: ignore[union-attr]
    image_bgr = _decode_upload(raw, request_id)
    return _run_recognize(
        image_bgr,
        scope_key=slug,
        conf_thresh=conf_thresh,
        padding=padding,
        crop_format=crop_format,
        jpeg_quality=jpeg_quality,
        max_faces=max_faces,
        include_landmarks=include_landmarks,
        square=square,
        match_thresh=match_thresh,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Daily register
# ---------------------------------------------------------------------------


@app.post(
    "/attendance/day",
    response_model=DailyRollOut,
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    dependencies=[Depends(require_auth)],
)
def set_daily_attendance(request: Request, body: DailyRollRequest) -> DailyRollOut:
    request_id = _request_id_from_request(request)
    slug = _parse_scope_key(body.scope_key, request_id)
    try:
        validate_attendance_date(body.date)
        roll = ref_store.set_daily_roll(
            scope_key=slug,
            attendance_date=body.date,
            present_ref_ids=body.present_ref_ids,
        )
    except KeyError as exc:
        raise _error(422, "validation_error", str(exc), request_id) from exc
    except ValueError as exc:
        raise _error(422, "validation_error", str(exc), request_id) from exc
    return DailyRollOut(
        id=roll.id,
        scope_key=roll.scope_key,
        date=roll.attendance_date,
        present=[DailyPresentOut(ref_id=p.ref_id, name=p.name) for p in roll.present],
        created_at=roll.created_at,
        updated_at=roll.updated_at,
    )


@app.get(
    "/attendance/day/status",
    response_model=DayStatusOut,
    dependencies=[Depends(require_auth)],
)
def get_day_status(request: Request, scope_key: str, date: str) -> DayStatusOut:
    request_id = _request_id_from_request(request)
    slug = _parse_scope_key(scope_key, request_id)
    try:
        status = ref_store.day_status(slug, date)
    except ValueError as exc:
        raise _error(422, "validation_error", str(exc), request_id) from exc
    present_n = len(status.present)
    absent_n = len(status.absent)
    roster_n = present_n + absent_n
    pct = round(100.0 * present_n / roster_n, 1) if roster_n and status.has_roll else None
    return DayStatusOut(
        scope_key=status.scope_key,
        date=status.attendance_date,
        has_roll=status.has_roll,
        present=[DailyPresentOut(ref_id=p.ref_id, name=p.name) for p in status.present],
        absent=[DailyPresentOut(ref_id=p.ref_id, name=p.name) for p in status.absent],
        present_count=present_n,
        absent_count=absent_n,
        roster_count=roster_n,
        attendance_pct=pct,
    )


@app.get(
    "/attendance/day",
    response_model=DailyRollOut,
    responses={404: {"model": ErrorResponse}},
    dependencies=[Depends(require_auth)],
)
def get_daily_attendance(request: Request, scope_key: str, date: str) -> DailyRollOut:
    request_id = _request_id_from_request(request)
    slug = _parse_scope_key(scope_key, request_id)
    try:
        validate_attendance_date(date)
    except ValueError as exc:
        raise _error(422, "validation_error", str(exc), request_id) from exc
    roll = ref_store.get_daily_roll(slug, date)
    if roll is None:
        raise _error(404, "not_found", f"No daily roll for {slug} on {date}", request_id)
    return DailyRollOut(
        id=roll.id,
        scope_key=roll.scope_key,
        date=roll.attendance_date,
        present=[DailyPresentOut(ref_id=p.ref_id, name=p.name) for p in roll.present],
        created_at=roll.created_at,
        updated_at=roll.updated_at,
    )


@app.get("/teacher")
def teacher_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "teacher.html")


@app.get("/dashboard")
def dashboard_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/attendance/new")
def select_attendance_class_ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "select-class.html")


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
