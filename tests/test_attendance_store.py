"""Attendance store record / dedupe / list."""

from __future__ import annotations

from app.attendance_store import AttendanceStore


def test_record_dedupes_person_per_request(tmp_path):
    store = AttendanceStore(path=tmp_path / "attendance.json")
    faces = [
        {
            "matched": True,
            "person_id": "p1",
            "name": "Ali",
            "match_score": 0.9,
            "face_id": 0,
        },
        {
            "matched": True,
            "person_id": "p1",
            "name": "Ali",
            "match_score": 0.85,
            "face_id": 1,
        },
        {
            "matched": True,
            "person_id": "p2",
            "name": "Sara",
            "match_score": 0.8,
            "face_id": 2,
        },
        {
            "matched": False,
            "person_id": None,
            "name": None,
            "match_score": 0.1,
            "face_id": 3,
        },
    ]
    events = store.record(source_request_id="req-1", faces=faces)
    assert len(events) == 2
    assert {e.person_id for e in events} == {"p1", "p2"}
    assert events[0].source_request_id == "req-1"
    assert events[0].face_id == 0  # first match wins
    assert store.count() == 2

    listed = store.list_events(limit=10)
    assert len(listed) == 2
    # newest first — same timestamp so order is reverse append
    assert listed[0].person_id == "p2"


def test_unknown_faces_not_logged(tmp_path):
    store = AttendanceStore(path=tmp_path / "attendance.json")
    events = store.record(
        source_request_id="req-2",
        faces=[{"matched": False, "person_id": None, "name": None, "match_score": 0.0, "face_id": 0}],
    )
    assert events == []
    assert store.count() == 0
