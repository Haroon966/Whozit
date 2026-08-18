"""Admin routes, patch ref, samples, rec_log, purge, quality gate."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.crop_crypto import MODEL_VERSION
from app.ref_store import RefStore


def _settings(tmp_path, **overrides):
    base = dict(
        api_key=None,
        max_upload_bytes=10 * 1024 * 1024,
        max_inflight=4,
        match_thresh=0.35,
        sqlite_path=tmp_path / "whozit.db",
        crop_key="test-key",
        rec_log_ttl_days=90,
        gallery_lru_size=8,
        session_ttl_seconds=3600,
        min_enroll_quality=None,
        migrate_v3_path=None,
        require_crop_key=False,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    sqlite = tmp_path / "whozit.db"
    test_settings = _settings(tmp_path)
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
        yield c, store


def test_patch_ref_name(client):
    c, store = client
    emb = np.zeros(8, dtype=np.float32)
    ref = store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
    )
    r = c.patch("/refs/a1?scope_key=pk/c1", json={"name": "Ali Khan"})
    assert r.status_code == 200
    assert r.json()["name"] == "Ali Khan"


def test_list_samples(client):
    c, store = client
    emb = np.zeros(8, dtype=np.float32)
    store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
    )
    r = c.get("/refs/a1/samples?scope_key=pk/c1")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["has_crop"] is True


def test_internal_rec_log(client):
    c, store = client
    emb = np.zeros(8, dtype=np.float32)
    store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
    )
    store.record_matches(
        scope_key="pk/c1",
        source_request_id="req-1",
        matches=[{"ref_id": "a1", "score": 0.9, "margin": 0.1}],
    )
    r = c.get("/internal/rec_log?scope_key=pk/c1")
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_move_ref_and_scope_http(client):
    c, store = client
    emb = np.zeros(8, dtype=np.float32)
    store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
    )
    r = c.post("/refs/a1/move", json={"scope_key": "pk/c1", "new_scope_key": "pk/c2"})
    assert r.status_code == 200
    assert r.json()["scope_key"] == "pk/c2"

    store.enroll(
        name="Bea",
        scope_key="pk/x1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r2",
        ref_id="b1",
    )
    r2 = c.post("/scopes/move", json={"old_scope_key": "pk/x1", "new_scope_key": "pk/x2"})
    assert r2.status_code == 200
    assert r2.json()["moved"] == 1


def test_delete_sample_http(client):
    c, store = client
    emb = np.zeros(8, dtype=np.float32)
    store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
    )
    samples = store.list_samples("pk/c1", "a1")
    r = c.delete(f"/samples/{samples[0].id}")
    assert r.status_code == 200


def test_admin_wipe(client):
    c, store = client
    emb = np.zeros(8, dtype=np.float32)
    store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
    )
    r = c.post("/admin/wipe", json={"confirm": "DELETE ALL DATA"})
    assert r.status_code == 200
    assert store.count_refs() == 0


def test_purge_rec_log(tmp_path):
    store = RefStore(path=tmp_path / "w.db", crop_key="k")
    emb = np.zeros(4, dtype=np.float32)
    store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
    )
    store.record_matches(
        scope_key="pk/c1",
        source_request_id="x",
        matches=[{"ref_id": "a1", "score": 0.5, "margin": 0.1}],
    )
    n = store.purge_rec_log()
    assert n >= 0


def test_model_version_mismatch(client, monkeypatch):
    import cv2

    c, store = client
    emb = np.zeros(512, dtype=np.float32)
    emb[0] = 1.0
    store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
        model_version="old_model",
    )
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    monkeypatch.setattr("app.main.detector_service.detect", lambda *a, **k: [])
    r = c.post(
        "/recognize",
        data={"scope_key": "pk/c1"},
        files={"image": ("t.jpg", buf.tobytes(), "image/jpeg")},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "model_version_mismatch"
