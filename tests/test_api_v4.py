"""HTTP-level v4 API tests (mocked detector / no ONNX)."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.detector import DetectedFace
from app.ref_store import RefStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    sqlite = tmp_path / "whozit.db"
    test_settings = Settings(
        api_key=None,
        max_upload_bytes=10 * 1024 * 1024,
        max_inflight=4,
        match_thresh=0.35,
        sqlite_path=sqlite,
        crop_key="test-crop-key",
        rec_log_ttl_days=90,
        gallery_lru_size=8,
        session_ttl_seconds=3600,
        min_enroll_quality=None,
        migrate_v3_path=None,
        require_crop_key=False,
    )
    monkeypatch.setattr("app.main.settings", test_settings)
    monkeypatch.setattr("app.config.settings", test_settings)

    store = RefStore(path=sqlite, crop_key="test-crop-key")
    monkeypatch.setattr("app.main.ref_store", store)
    monkeypatch.setattr("app.recognizer.ref_store", store)

    monkeypatch.setattr("app.main.detector_service.warmup", lambda: None)
    monkeypatch.setattr("app.main.recognizer_service.warmup", lambda: None)
    monkeypatch.setattr("app.main.detector_service.ready", lambda: True)
    monkeypatch.setattr("app.main.recognizer_service.ready", lambda: True)
    monkeypatch.setattr("app.main.db_mod.init_db", lambda path=None: sqlite)

    from app.main import app

    with TestClient(app) as c:
        yield c, store


def _jpeg_bytes(size: int = 64) -> bytes:
    import cv2

    img = np.zeros((size, size, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def test_refs_and_daily_roll_roundtrip(client):
    c, store = client
    emb = np.zeros(8, dtype=np.float32)
    emb[0] = 1.0
    a = store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
    )
    b = store.enroll(
        name="Bea",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r2",
        ref_id="b1",
    )

    listed = c.get("/refs", params={"scope_key": "pk/c1"})
    assert listed.status_code == 200
    names = {p["name"] for p in listed.json()}
    assert names == {"Ali", "Bea"}

    scopes = c.get("/scopes")
    assert scopes.status_code == 200
    assert scopes.json() == ["pk/c1"]

    post = c.post(
        "/attendance/day",
        json={
            "scope_key": "pk/c1",
            "date": "2026-08-13",
            "present_ref_ids": [a.ref_id, b.ref_id],
        },
    )
    assert post.status_code == 200
    body = post.json()
    assert body["date"] == "2026-08-13"
    assert {p["ref_id"] for p in body["present"]} == {a.ref_id, b.ref_id}

    got = c.get("/attendance/day", params={"scope_key": "pk/c1", "date": "2026-08-13"})
    assert got.status_code == 200
    assert len(got.json()["present"]) == 2


def test_auth_rejects_sec_fetch_bypass(client, monkeypatch):
    c, _ = client
    from pathlib import Path

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
    denied = c.post("/detect", data={}, headers={"Sec-Fetch-Site": "same-origin"})
    assert denied.status_code == 401


def test_recognize_includes_name(client, monkeypatch):
    c, store = client
    emb_a = np.zeros(8, dtype=np.float32)
    emb_a[0] = 1.0
    store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb_a,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
    )
    fake_face = DetectedFace(
        bbox=[10.0, 10.0, 50.0, 50.0],
        confidence=0.99,
        landmarks=[[20, 20], [40, 20], [30, 30], [22, 40], [38, 40]],
    )
    monkeypatch.setattr("app.main.detector_service.detect", lambda *a, **k: [fake_face])
    monkeypatch.setattr(
        "app.main.recognizer_service.embed",
        lambda *a, **k: emb_a,
    )
    monkeypatch.setattr(
        "app.main.recognizer_service.assign_faces",
        lambda embs, slug, threshold=None: [
            type(
                "M",
                (),
                {
                    "ref_id": "a1",
                    "name": "Ali",
                    "score": 0.88,
                    "matched": True,
                    "margin": 0.2,
                    "candidates": [],
                },
            )()
        ],
    )
    r = c.post(
        "/recognize",
        data={"scope_key": "pk/c1"},
        files={"image": ("t.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert r.status_code == 200
    face = r.json()["faces"][0]
    assert face["name"] == "Ali"
    assert face["ref_id"] == "a1"
    assert face["margin"] == 0.2
