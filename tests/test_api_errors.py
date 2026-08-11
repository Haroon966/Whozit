"""API error shape + optional API key (mocked detector/recognizer)."""

from __future__ import annotations

import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.attendance_store import AttendanceStore
from app.config import Settings
from app.detector import DetectedFace
from app.people_store import PeopleStore


def _jpeg_bytes(size: int = 64) -> bytes:
    img = np.zeros((size, size, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    people = tmp_path / "people.json"
    attendance = tmp_path / "attendance.json"
    people.write_text('{"people": []}', encoding="utf-8")
    attendance.write_text('{"events": []}', encoding="utf-8")

    test_settings = Settings(
        api_key=None,
        max_upload_bytes=10 * 1024 * 1024,
        max_inflight=4,
        match_thresh=0.35,
        people_path=people,
        attendance_path=attendance,
    )
    monkeypatch.setattr("app.main.settings", test_settings)

    people_store = PeopleStore(path=people)
    attendance_store = AttendanceStore(path=attendance)
    monkeypatch.setattr("app.main.people_store", people_store)
    monkeypatch.setattr("app.main.attendance_store", attendance_store)

    monkeypatch.setattr("app.main.detector_service.warmup", lambda: None)
    monkeypatch.setattr("app.main.recognizer_service.warmup", lambda: None)
    monkeypatch.setattr("app.main.detector_service.ready", lambda: True)
    monkeypatch.setattr("app.main.recognizer_service.ready", lambda: True)

    from app.main import app

    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "attendance_count" in body
    assert body["auth_enabled"] is False


def test_missing_image_error_shape(client):
    r = client.post("/v1/detect", data={})
    assert r.status_code == 400
    body = r.json()
    assert "request_id" in body
    assert body["error"]["code"] == "missing_image"
    assert "detail" not in body


def test_invalid_image_error(client):
    r = client.post(
        "/v1/detect",
        files={"image": ("bad.txt", b"not-an-image", "text/plain")},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_image"


def test_detect_json_zero_faces(client, monkeypatch):
    monkeypatch.setattr("app.main.detector_service.detect", lambda *a, **k: [])
    r = client.post(
        "/v1/detect",
        json={"image_base64": base64.b64encode(_jpeg_bytes()).decode(), "identify": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["face_count"] == 0
    assert body["faces"] == []


def test_api_key_required(client, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(
        "app.main.settings",
        Settings(
            api_key="secret-key",
            max_upload_bytes=10 * 1024 * 1024,
            max_inflight=4,
            match_thresh=0.35,
            people_path=Path("/tmp/people.json"),
            attendance_path=Path("/tmp/attendance.json"),
        ),
    )

    assert client.get("/health").status_code == 200
    denied = client.post("/v1/detect", data={})
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "unauthorized"

    still = client.post("/v1/detect", data={}, headers={"X-API-Key": "wrong"})
    assert still.status_code == 401

    ok_shape = client.post("/v1/detect", data={}, headers={"X-API-Key": "secret-key"})
    assert ok_shape.status_code == 400
    assert ok_shape.json()["error"]["code"] == "missing_image"


def test_attendance_logs_matched(client, monkeypatch):
    fake_face = DetectedFace(
        bbox=[10.0, 10.0, 50.0, 50.0],
        confidence=0.99,
        landmarks=[[20, 20], [40, 20], [30, 30], [22, 40], [38, 40]],
    )

    class FakeMatch:
        person_id = "pid-1"
        name = "Ali"
        score = 0.88
        matched = True

    monkeypatch.setattr("app.main.detector_service.detect", lambda *a, **k: [fake_face])
    monkeypatch.setattr(
        "app.main.recognizer_service.embed",
        lambda *a, **k: np.zeros(512, dtype=np.float32),
    )
    monkeypatch.setattr("app.main.recognizer_service.match", lambda *a, **k: FakeMatch())

    r = client.post("/v2/attendance", files={"image": ("t.jpg", _jpeg_bytes(), "image/jpeg")})
    assert r.status_code == 200
    body = r.json()
    assert body["face_count"] == 1
    assert len(body["attendance"]) == 1
    assert body["attendance"][0]["name"] == "Ali"
    assert body["faces"][0]["matched"] is True
