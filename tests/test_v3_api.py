"""HTTP-level v3 API tests (mocked detector / no ONNX)."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.attendance_store import AttendanceStore
from app.config import Settings
from app.people_store import PeopleStore
from app.scoped_store import ScopedStore


@pytest.fixture()
def v3_client(tmp_path, monkeypatch):
    people = tmp_path / "people.json"
    attendance = tmp_path / "attendance.json"
    sqlite = tmp_path / "v3.db"
    people.write_text('{"people": []}', encoding="utf-8")
    attendance.write_text('{"events": []}', encoding="utf-8")

    test_settings = Settings(
        api_key=None,
        max_upload_bytes=10 * 1024 * 1024,
        max_inflight=4,
        match_thresh=0.35,
        people_path=people,
        attendance_path=attendance,
        sqlite_path=sqlite,
    )
    monkeypatch.setattr("app.main.settings", test_settings)
    monkeypatch.setattr("app.config.settings", test_settings)

    people_store = PeopleStore(path=people)
    attendance_store = AttendanceStore(path=attendance)
    scoped = ScopedStore(path=sqlite)
    monkeypatch.setattr("app.main.people_store", people_store)
    monkeypatch.setattr("app.main.attendance_store", attendance_store)
    monkeypatch.setattr("app.main.scoped_store", scoped)

    monkeypatch.setattr("app.main.detector_service.warmup", lambda: None)
    monkeypatch.setattr("app.main.recognizer_service.warmup", lambda: None)
    monkeypatch.setattr("app.main.detector_service.ready", lambda: True)
    monkeypatch.setattr("app.main.recognizer_service.ready", lambda: True)
    monkeypatch.setattr("app.main.db_mod.init_db", lambda path=None: sqlite)

    from app.main import app

    with TestClient(app) as c:
        yield c, scoped


def test_v3_people_and_daily_roll_roundtrip(v3_client):
    client, scoped = v3_client
    emb = np.zeros(8, dtype=np.float32)
    emb[0] = 1.0
    a = scoped.enroll(name="Ali", class_slug="pk/c1", embedding=emb)
    b = scoped.enroll(name="Bea", class_slug="pk/c1", embedding=emb)

    listed = client.get("/v3/people", params={"class_slug": "pk/c1"})
    assert listed.status_code == 200
    names = {p["name"] for p in listed.json()}
    assert names == {"Ali", "Bea"}

    post = client.post(
        "/v3/attendance/day",
        json={
            "class_slug": "pk/c1",
            "date": "2026-08-13",
            "present_student_ids": [a.id, b.id],
        },
    )
    assert post.status_code == 200
    body = post.json()
    assert body["date"] == "2026-08-13"
    assert {p["student_id"] for p in body["present"]} == {a.id, b.id}

    got = client.get(
        "/v3/attendance/day",
        params={"class_slug": "pk/c1", "date": "2026-08-13"},
    )
    assert got.status_code == 200
    assert len(got.json()["present"]) == 2

    # Upsert: only Ali present
    post2 = client.post(
        "/v3/attendance/day",
        json={
            "class_slug": "pk/c1",
            "date": "2026-08-13",
            "present_student_ids": [a.id],
        },
    )
    assert post2.status_code == 200
    assert post2.json()["id"] == body["id"]
    assert [p["student_id"] for p in post2.json()["present"]] == [a.id]


def test_v3_enroll_missing_class_slug(v3_client):
    client, _ = v3_client
    # multipart without class_slug → FastAPI 422 validation, or our 400 if empty string
    r = client.post(
        "/v3/enroll",
        data={"name": "Ali"},
        files={"image": ("x.jpg", b"not-image", "image/jpeg")},
    )
    assert r.status_code in {400, 422}


def test_v3_invalid_slug_on_people(v3_client):
    client, _ = v3_client
    r = client.get("/v3/people", params={"class_slug": "bad slug!"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_v3_daily_roll_unknown_student(v3_client):
    client, _ = v3_client
    r = client.post(
        "/v3/attendance/day",
        json={
            "class_slug": "pk/c1",
            "date": "2026-08-13",
            "present_student_ids": ["no-such-id"],
        },
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_health_includes_scoped_count(v3_client):
    client, _ = v3_client
    r = client.get("/health")
    assert r.status_code == 200
    assert "scoped_students_count" in r.json()


def test_v3_classes_and_day_status(v3_client):
    client, scoped = v3_client
    emb = np.zeros(8, dtype=np.float32)
    emb[0] = 1.0
    a = scoped.enroll(name="Ali", class_slug="pk/c1", embedding=emb)
    b = scoped.enroll(name="Bea", class_slug="pk/c1", embedding=emb)
    scoped.enroll(name="Zed", class_slug="pk/c2", embedding=emb)

    classes = client.get("/v3/classes")
    assert classes.status_code == 200
    assert classes.json() == ["pk/c1", "pk/c2"]

    empty = client.get(
        "/v3/attendance/day/status",
        params={"class_slug": "pk/c1", "date": "2026-08-13"},
    )
    assert empty.status_code == 200
    body = empty.json()
    assert body["has_roll"] is False
    assert body["present_count"] == 0
    assert body["absent_count"] == 2
    assert body["attendance_pct"] is None

    client.post(
        "/v3/attendance/day",
        json={
            "class_slug": "pk/c1",
            "date": "2026-08-13",
            "present_student_ids": [a.id],
        },
    )
    status = client.get(
        "/v3/attendance/day/status",
        params={"class_slug": "pk/c1", "date": "2026-08-13"},
    ).json()
    assert status["has_roll"] is True
    assert status["present_count"] == 1
    assert status["absent_count"] == 1
    assert status["present"][0]["student_id"] == a.id
    assert status["absent"][0]["student_id"] == b.id
    assert status["attendance_pct"] == 50.0


def test_attendance_ui_pages(v3_client):
    client, _ = v3_client
    teacher_page = client.get("/teacher")
    assert teacher_page.status_code == 200
    assert "Attendance results" in teacher_page.text
    assert 'startCam("scan")' in teacher_page.text
    assert client.get("/dashboard").status_code == 200
    select_page = client.get("/attendance/new")
    assert select_page.status_code == 200
    assert "Select class" in select_page.text
    # Dashboard must not fan out parallel day-status calls (max_inflight → 503).
    assert "Promise.all(chartDates" not in client.get("/dashboard").text
    assert "Promise.all(slugs.map" not in select_page.text
    assert "text/html" in client.get("/teacher").headers["content-type"]
