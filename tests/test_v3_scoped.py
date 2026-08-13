"""v3 class-scoped SQLite store + slug match isolation."""

from __future__ import annotations

import numpy as np
import pytest

from app.recognizer import FaceRecognizerService
from app.scoped_store import ScopedStore, normalize_class_slug


def test_normalize_class_slug():
    assert normalize_class_slug(" PK/Lahore-East/School-ABC/Class-5A ") == (
        "pk/lahore-east/school-abc/class-5a"
    )
    with pytest.raises(ValueError):
        normalize_class_slug("")
    with pytest.raises(ValueError):
        normalize_class_slug("bad slug!")


def test_slug_isolation_and_name_merge(tmp_path):
    store = ScopedStore(path=tmp_path / "v3.db")
    emb_a = np.zeros(8, dtype=np.float32)
    emb_a[0] = 1.0
    emb_b = np.zeros(8, dtype=np.float32)
    emb_b[1] = 1.0

    a = store.enroll(name="Haroon", class_slug="pk/s1/school/class-a", embedding=emb_a)
    store.enroll(name="Haroon", class_slug="pk/s1/school/class-a", embedding=emb_a)
    assert len(store.get(a.id).embeddings) == 2

    b = store.enroll(name="Haroon", class_slug="pk/s1/school/class-b", embedding=emb_b)
    assert a.id != b.id
    assert len(store.list_people("pk/s1/school/class-a")) == 1
    assert len(store.list_people("pk/s1/school/class-b")) == 1


def test_match_in_slug_only_sees_class(tmp_path, monkeypatch):
    store = ScopedStore(path=tmp_path / "v3.db")
    monkeypatch.setattr("app.recognizer.scoped_store", store)

    emb_a = np.zeros(8, dtype=np.float32)
    emb_a[0] = 1.0
    emb_b = np.zeros(8, dtype=np.float32)
    emb_b[1] = 1.0
    store.enroll(name="Ali", class_slug="pk/c1", embedding=emb_a)
    store.enroll(name="Bea", class_slug="pk/c2", embedding=emb_b)

    svc = FaceRecognizerService(match_threshold=0.5)
    r1 = svc.match_in_slug(emb_a, "pk/c1")
    assert r1.matched and r1.name == "Ali"

    r2 = svc.match_in_slug(emb_a, "pk/c2")
    assert not r2.matched

    r3 = svc.match_in_slug(emb_b, "pk/c2")
    assert r3.matched and r3.name == "Bea"


def test_daily_roll_upsert_present_only(tmp_path):
    store = ScopedStore(path=tmp_path / "v3.db")
    emb = np.zeros(4, dtype=np.float32)
    emb[0] = 1.0
    a = store.enroll(name="Ali", class_slug="pk/c1", embedding=emb)
    b = store.enroll(name="Bea", class_slug="pk/c1", embedding=emb)

    roll = store.set_daily_roll(
        class_slug="pk/c1",
        attendance_date="2026-08-13",
        present_student_ids=[a.id, b.id, a.id],
    )
    assert len(roll.present) == 2
    assert {p.student_id for p in roll.present} == {a.id, b.id}

    roll2 = store.set_daily_roll(
        class_slug="pk/c1",
        attendance_date="2026-08-13",
        present_student_ids=[a.id],
    )
    assert roll2.id == roll.id
    assert [p.student_id for p in roll2.present] == [a.id]

    got = store.get_daily_roll("pk/c1", "2026-08-13")
    assert got is not None
    assert len(got.present) == 1

    with pytest.raises(KeyError):
        store.set_daily_roll(
            class_slug="pk/c1",
            attendance_date="2026-08-13",
            present_student_ids=["missing-id"],
        )


def test_face_events_dedupe_person(tmp_path):
    store = ScopedStore(path=tmp_path / "v3.db")
    emb = np.zeros(4, dtype=np.float32)
    emb[0] = 1.0
    p = store.enroll(name="Ali", class_slug="pk/c1", embedding=emb)
    events = store.record_face_events(
        class_slug="pk/c1",
        source_request_id="req-1",
        faces=[
            {"matched": True, "person_id": p.id, "name": "Ali", "match_score": 0.9, "face_id": 0},
            {"matched": True, "person_id": p.id, "name": "Ali", "match_score": 0.8, "face_id": 1},
            {"matched": False, "person_id": None, "name": None, "match_score": 0.1, "face_id": 2},
        ],
    )
    assert len(events) == 1
    listed = store.list_face_events("pk/c1", limit=10)
    assert len(listed) == 1
