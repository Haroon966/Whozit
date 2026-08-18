"""Org tables + stable student_id (class not in the id)."""

from __future__ import annotations

import numpy as np
import pytest

from app.org_store import OrgStore, build_student_id, parse_class_scope, parse_student_id
from app.ref_store import RefStore


def test_build_and_parse_student_id():
    sid = build_student_id("pk", "isbd", "35123456", 42)
    assert sid == "pk+isbd+35123456+042"
    parsed = parse_student_id(sid)
    assert parsed == ("pk", "isbd", "35123456", 42)
    assert parse_student_id("roll-001") is None


def test_parse_class_scope():
    assert parse_class_scope("PK/Lahore-East/School-ABC/Class-5A") == (
        "pk",
        "lahore-east",
        "school-abc",
        "class-5a",
    )
    assert parse_class_scope("pk/c1") is None


def test_seq_unique_per_school(tmp_path):
    db = tmp_path / "whozit.db"
    refs = RefStore(path=db)
    org = OrgStore(path=db)
    emb = np.zeros(4, dtype=np.float32)
    emb[0] = 1.0
    crop = b"\xff\xd8\xff\xd9"
    a = refs.enroll(
        name="Ali",
        scope_key="pk/isbd/111/5a",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r1",
    )
    b = refs.enroll(
        name="Bea",
        scope_key="pk/isbd/222/5a",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r2",
    )
    assert a.ref_id == "pk+isbd+111+001"
    assert b.ref_id == "pk+isbd+222+001"
    assert org.resolve_enroll_id("pk/isbd/111/5a", a.ref_id) == a.ref_id
    klass = org.ensure_class(country="pk", province="isbd", emis="111", grade="5a")
    with pytest.raises(ValueError, match="seq 1 already used"):
        org._upsert_existing(klass, "pk+isbd+111+099", 1)


def test_same_name_two_seqs(tmp_path):
    refs = RefStore(path=tmp_path / "whozit.db")
    emb = np.zeros(8, dtype=np.float32)
    emb[0] = 1.0
    crop = b"\xff\xd8\xff\xd9"
    a = refs.enroll(
        name="Ayesha",
        scope_key="pk/isbd/35123456/5a",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r1",
    )
    b = refs.enroll(
        name="Ayesha",
        scope_key="pk/isbd/35123456/5a",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r2",
    )
    assert a.ref_id != b.ref_id
    assert a.ref_id.startswith("pk+isbd+35123456+")
    org = OrgStore(path=tmp_path / "whozit.db")
    assert org.get_student(a.ref_id).seq == 1
    assert org.get_student(b.ref_id).seq == 2


def test_class_move_keeps_student_id(tmp_path):
    db = tmp_path / "whozit.db"
    refs = RefStore(path=db)
    org = OrgStore(path=db)
    emb = np.zeros(4, dtype=np.float32)
    emb[0] = 1.0
    person = refs.enroll(
        name="Ali",
        scope_key="pk/isbd/35123456/5a",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
    )
    sid = person.ref_id
    moved = refs.move_ref("pk/isbd/35123456/5a", sid, "pk/isbd/35123456/6a")
    assert moved.ref_id == sid
    assert moved.scope_key == "pk/isbd/35123456/6a"
    got = org.get_student(sid)
    assert got is not None
    assert got.grade == "6a"
    assert got.sample_count == 1
    with pytest.raises(ValueError, match="different school"):
        refs.move_ref("pk/isbd/35123456/6a", sid, "pk/isbd/99999999/6a")


def test_reuse_student_id_adds_sample(tmp_path):
    db = tmp_path / "whozit.db"
    refs = RefStore(path=db)
    emb = np.zeros(4, dtype=np.float32)
    crop = b"\xff\xd8\xff\xd9"
    first = refs.enroll(
        name="Ali",
        scope_key="pk/isbd/35123456/5a",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r1",
    )
    second = refs.enroll(
        name="Ali",
        scope_key="pk/isbd/35123456/5a",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r2",
        ref_id=first.ref_id,
    )
    assert second.ref_id == first.ref_id
    assert second.sample_count == 2


def test_backfill_from_legacy_refs(tmp_path):
    db = tmp_path / "whozit.db"
    refs = RefStore(path=db)
    org = OrgStore(path=db)
    emb = np.zeros(4, dtype=np.float32)
    refs.enroll(
        name="Haroon",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
        ref_id="roll-001",
    )
    # 2-part scope is not org-shaped; plant a 4-part ref like migrated data
    now = "2026-01-01T00:00:00+00:00"
    with refs._conn() as conn:
        conn.execute(
            "INSERT INTO refs (scope_key, ref_id, name, created_at, updated_at) VALUES (?,?,?,?,?)",
            ("pk/lahore-east/school-abc/class-5a", "roll-007", "Junaid", now, now),
        )
        conn.commit()
    stats = org.backfill_from_refs()
    assert stats["students"] >= 1
    student = org.get_student("pk+lahore-east+school-abc+007")
    assert student is not None
    assert student.name == "Junaid"
    assert refs.get("pk/lahore-east/school-abc/class-5a", "pk+lahore-east+school-abc+007") is not None


def test_gallery_is_current_class_roster(tmp_path):
    db = tmp_path / "whozit.db"
    refs = RefStore(path=db)
    emb = np.zeros(4, dtype=np.float32)
    emb[0] = 1.0
    crop = b"\xff\xd8\xff\xd9"
    a = refs.enroll(
        name="Ali",
        scope_key="pk/isbd/35123456/5a",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r1",
    )
    b = refs.enroll(
        name="Bea",
        scope_key="pk/isbd/35123456/5a",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r2",
    )
    refs.move_ref("pk/isbd/35123456/5a", a.ref_id, "pk/isbd/35123456/6a")
    g5 = {r.ref_id for r in refs.gallery_for_scope("pk/isbd/35123456/5a")}
    g6 = {r.ref_id for r in refs.gallery_for_scope("pk/isbd/35123456/6a")}
    assert g5 == {b.ref_id}
    assert g6 == {a.ref_id}
