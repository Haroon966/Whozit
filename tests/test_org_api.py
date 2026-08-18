"""HTTP tests for org + stable student lookup."""

from __future__ import annotations

from urllib.parse import quote

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.org_store import OrgStore
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
    org = OrgStore(path=sqlite)
    monkeypatch.setattr("app.main.ref_store", store)
    monkeypatch.setattr("app.main.org_store", org)
    monkeypatch.setattr("app.recognizer.ref_store", store)
    monkeypatch.setattr("app.main.detector_service.warmup", lambda: None)
    monkeypatch.setattr("app.main.recognizer_service.warmup", lambda: None)
    monkeypatch.setattr("app.main.detector_service.ready", lambda: True)
    monkeypatch.setattr("app.main.recognizer_service.ready", lambda: True)
    monkeypatch.setattr("app.main.db_mod.init_db", lambda path=None: sqlite)

    from app.main import app

    with TestClient(app) as c:
        yield c, store, org


def test_org_class_and_student_lookup(client):
    c, store, org = client
    created = c.post(
        "/org/classes",
        json={"country": "pk", "province": "isbd", "emis": "35123456", "grade": "5a"},
    )
    assert created.status_code == 200
    body = created.json()
    assert body["scope_key"] == "pk/isbd/35123456/5a"

    emb = np.zeros(8, dtype=np.float32)
    emb[0] = 1.0
    person = store.enroll(
        name="Ali",
        scope_key=body["scope_key"],
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
    )
    got = c.get(f"/students/{quote(person.ref_id, safe='')}")
    assert got.status_code == 200
    data = got.json()
    assert data["student_id"] == person.ref_id
    assert data["name"] == "Ali"
    assert data["country"] == "pk"
    assert data["grade"] == "5a"
    listed = c.get("/students", params={"class_id": body["id"]})
    assert listed.status_code == 200
    assert listed.json()[0]["student_id"] == person.ref_id

    roll = c.post(
        "/attendance/day",
        json={"scope_key": body["scope_key"], "date": "2026-08-18", "present_ref_ids": [person.ref_id]},
    )
    assert roll.status_code == 200
    assert roll.json()["present"][0]["ref_id"] == person.ref_id


def test_countries_after_ensure(client):
    c, _store, _org = client
    c.post(
        "/org/schools",
        json={"country": "pk", "province": "isbd", "emis": "35123456"},
    )
    countries = c.get("/org/countries")
    assert countries.status_code == 200
    assert "pk" in countries.json()
    provinces = c.get("/org/provinces", params={"country": "pk"})
    assert "isbd" in provinces.json()
