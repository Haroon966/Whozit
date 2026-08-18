"""Ref store: ref_id identity, same-name collision safety, register cascade."""

from __future__ import annotations

import numpy as np
import pytest

from app.ref_store import RefStore, normalize_scope_key


def test_normalize_scope_key():
    assert normalize_scope_key(" PK/Lahore-East/School-ABC/Class-5A ") == (
        "pk/lahore-east/school-abc/class-5a"
    )
    with pytest.raises(ValueError):
        normalize_scope_key("")
    with pytest.raises(ValueError):
        normalize_scope_key("bad slug!")


def test_same_name_two_refs(tmp_path):
    store = RefStore(path=tmp_path / "whozit.db")
    emb = np.zeros(8, dtype=np.float32)
    emb[0] = 1.0
    crop = b"\xff\xd8\xff\xd9"
    a = store.enroll(
        name="Ayesha",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r1",
        ref_id="roll-1",
    )
    b = store.enroll(
        name="Ayesha",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r2",
        ref_id="roll-2",
    )
    assert a.ref_id != b.ref_id
    assert len(store.list_refs("pk/c1")) == 2


def test_enroll_mints_ref_id(tmp_path):
    store = RefStore(path=tmp_path / "whozit.db")
    emb = np.zeros(4, dtype=np.float32)
    ref = store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.8,
        source_request_id="r1",
    )
    assert ref.ref_id
    assert len(ref.ref_id) >= 8


def test_daily_roll_and_delete_cascade(tmp_path):
    store = RefStore(path=tmp_path / "whozit.db")
    emb = np.zeros(4, dtype=np.float32)
    emb[0] = 1.0
    crop = b"\xff\xd8\xff\xd9"
    a = store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
    )
    b = store.enroll(
        name="Bea",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r2",
        ref_id="b1",
    )
    roll = store.set_daily_roll(
        scope_key="pk/c1",
        attendance_date="2026-08-13",
        present_ref_ids=[a.ref_id, b.ref_id],
    )
    assert len(roll.present) == 2
    assert store.delete_ref("pk/c1", a.ref_id)
    got = store.get_daily_roll("pk/c1", "2026-08-13")
    assert got is not None
    assert {p.ref_id for p in got.present} == {b.ref_id}


def test_bulk_move_scope(tmp_path):
    store = RefStore(path=tmp_path / "whozit.db")
    emb = np.zeros(4, dtype=np.float32)
    crop = b"\xff\xd8\xff\xd9"
    ref = store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=crop,
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
    )
    n = store.move_scope("pk/c1", "pk/c2")
    assert n == 1
    assert store.get("pk/c2", ref.ref_id) is not None
    assert store.get("pk/c1", ref.ref_id) is None
