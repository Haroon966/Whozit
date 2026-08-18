"""API error shape + optional API key (mocked detector/recognizer)."""

from __future__ import annotations

import base64
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.detector import DetectedFace
from app.ref_store import RefStore


def _jpeg_bytes(size: int = 64) -> bytes:
    img = np.zeros((size, size, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    sqlite = tmp_path / "whozit.db"
    test_settings = Settings(
        api_key=None,
        max_upload_bytes=10 * 1024 * 1024,
        max_inflight=4,
        match_thresh=0.35,
        sqlite_path=sqlite,
        crop_key="test-key",
        rec_log_ttl_days=90,
        gallery_lru_size=8,
        session_ttl_seconds=3600,
        min_enroll_quality=None,
        migrate_v3_path=None,
        require_crop_key=False,
    )
    monkeypatch.setattr("app.main.settings", test_settings)
    monkeypatch.setattr("app.config.settings", test_settings)

    store = RefStore(path=sqlite, crop_key="test-key")
    monkeypatch.setattr("app.main.ref_store", store)
    monkeypatch.setattr("app.recognizer.ref_store", store)

    monkeypatch.setattr("app.main.detector_service.warmup", lambda: None)
    monkeypatch.setattr("app.main.recognizer_service.warmup", lambda: None)
    monkeypatch.setattr("app.main.detector_service.ready", lambda: True)
    monkeypatch.setattr("app.main.recognizer_service.ready", lambda: True)
    monkeypatch.setattr("app.main.db_mod.init_db", lambda path=None: sqlite)

    from app.main import app

    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["auth_enabled"] is False
    assert "ref_count" in body


def test_missing_image_error_shape(client):
    r = client.post("/detect", data={})
    assert r.status_code == 400
    body = r.json()
    assert "request_id" in body
    assert body["error"]["code"] == "missing_image"


def test_detect_json_zero_faces(client, monkeypatch):
    monkeypatch.setattr("app.main.detector_service.detect", lambda *a, **k: [])
    r = client.post(
        "/detect",
        json={"image_base64": base64.b64encode(_jpeg_bytes()).decode()},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["face_count"] == 0


def test_api_key_required(client, monkeypatch):
    monkeypatch.setattr(
        "app.main.settings",
        Settings(
            api_key="secret-key",
            max_upload_bytes=10 * 1024 * 1024,
            max_inflight=4,
            match_thresh=0.35,
            sqlite_path=Path("/tmp/whozit.db"),
            crop_key="secret-crop",
            rec_log_ttl_days=90,
            gallery_lru_size=8,
            session_ttl_seconds=3600,
            min_enroll_quality=None,
            migrate_v3_path=None,
            require_crop_key=False,
        ),
    )

    assert client.get("/health").status_code == 200
    denied = client.post("/detect", data={})
    assert denied.status_code == 401

    ok = client.post("/detect", data={}, headers={"X-API-Key": "secret-key"})
    assert ok.status_code == 400

    bypass = client.post("/detect", data={}, headers={"Sec-Fetch-Site": "same-origin"})
    assert bypass.status_code == 401

    login = client.post("/session", json={"api_key": "secret-key"})
    assert login.status_code == 200
    cookie = login.cookies.get("whozit_session")
    assert cookie
    authed = client.post("/detect", data={}, cookies={"whozit_session": cookie})
    assert authed.status_code == 400
