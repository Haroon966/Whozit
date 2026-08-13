"""SQLite store for v3 class-scoped students, face events, and daily rolls."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app import db as db_mod
from app.config import settings

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:[/_-][a-z0-9]+)*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_SLUG_LEN = 200


def normalize_class_slug(raw: str) -> str:
    slug = raw.strip().lower()
    while "//" in slug:
        slug = slug.replace("//", "/")
    slug = slug.strip("/")
    if not slug:
        raise ValueError("class_slug is required")
    if len(slug) > _MAX_SLUG_LEN:
        raise ValueError(f"class_slug max length is {_MAX_SLUG_LEN}")
    if not _SLUG_RE.match(slug):
        raise ValueError(
            "class_slug must be path-like lowercase tokens "
            "(a-z0-9) separated by / _ or -"
        )
    return slug


def validate_attendance_date(raw: str) -> str:
    date = raw.strip()
    if not _DATE_RE.match(date):
        raise ValueError("date must be YYYY-MM-DD")
    return date


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mean_embedding(vectors: list[list[float]]) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    mean = arr.mean(axis=0)
    norm = np.linalg.norm(mean)
    return mean / norm if norm > 0 else mean


@dataclass
class ScopedStudent:
    id: str
    class_slug: str
    name: str
    student_id: str | None
    embeddings: list[list[float]]
    created_at: str
    updated_at: str

    def mean_embedding(self) -> np.ndarray:
        return _mean_embedding(self.embeddings)


@dataclass
class ScopedAttendanceEvent:
    id: str
    class_slug: str
    student_id: str
    name: str
    match_score: float
    timestamp: str
    source_request_id: str
    face_id: int | None


@dataclass
class DailyPresent:
    student_id: str
    name: str


@dataclass
class DailyRoll:
    id: str
    class_slug: str
    attendance_date: str
    present: list[DailyPresent]
    created_at: str
    updated_at: str


@dataclass
class DayStatus:
    class_slug: str
    attendance_date: str
    has_roll: bool
    present: list[DailyPresent]
    absent: list[DailyPresent]


@dataclass
class GalleryEntry:
    person_id: str
    name: str
    mean: np.ndarray


class ScopedStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.sqlite_path
        self._lock = threading.Lock()
        db_mod.init_db(self.path)

    def _conn(self) -> sqlite3.Connection:
        return db_mod.connect(self.path)

    def count_students(self) -> int:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM students").fetchone()
            return int(row["n"])

    def list_people(self, class_slug: str) -> list[ScopedStudent]:
        slug = normalize_class_slug(class_slug)
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM students WHERE class_slug = ? ORDER BY name COLLATE NOCASE",
                (slug,),
            ).fetchall()
            return [self._student_from_row(conn, r) for r in rows]

    def get(self, person_id: str) -> ScopedStudent | None:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT * FROM students WHERE id = ?", (person_id,)).fetchone()
            if row is None:
                return None
            return self._student_from_row(conn, row)

    def gallery_for_slug(self, class_slug: str) -> list[GalleryEntry]:
        slug = normalize_class_slug(class_slug)
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM students WHERE class_slug = ?",
                (slug,),
            ).fetchall()
            entries: list[GalleryEntry] = []
            for r in rows:
                vectors = self._load_vectors(conn, r["id"])
                if not vectors:
                    continue
                entries.append(
                    GalleryEntry(
                        person_id=r["id"],
                        name=r["name"],
                        mean=_mean_embedding(vectors),
                    )
                )
            return entries

    def enroll(
        self,
        *,
        name: str,
        class_slug: str,
        embedding: np.ndarray,
        person_id: str | None = None,
        student_id: str | None = None,
    ) -> ScopedStudent:
        name = name.strip()
        if not name:
            raise ValueError("name is required")
        slug = normalize_class_slug(class_slug)
        sid = student_id.strip() if student_id and student_id.strip() else None
        emb = embedding.astype(np.float32).ravel().tolist()
        now = _now()

        with self._lock, self._conn() as conn:
            target_id: str | None = None
            if person_id:
                row = conn.execute(
                    "SELECT * FROM students WHERE id = ?", (person_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"person_id not found: {person_id}")
                if row["class_slug"] != slug:
                    raise ValueError("person_id does not belong to class_slug")
                target_id = row["id"]
                conn.execute(
                    "UPDATE students SET name = ?, student_id = COALESCE(?, student_id), updated_at = ? WHERE id = ?",
                    (name, sid, now, target_id),
                )
            else:
                if sid:
                    row = conn.execute(
                        "SELECT * FROM students WHERE class_slug = ? AND student_id = ?",
                        (slug, sid),
                    ).fetchone()
                    if row is not None:
                        target_id = row["id"]
                        conn.execute(
                            "UPDATE students SET name = ?, updated_at = ? WHERE id = ?",
                            (name, now, target_id),
                        )
                if target_id is None:
                    row = conn.execute(
                        "SELECT * FROM students WHERE class_slug = ? AND lower(name) = lower(?)",
                        (slug, name),
                    ).fetchone()
                    if row is not None:
                        target_id = row["id"]
                        conn.execute(
                            "UPDATE students SET name = ?, student_id = COALESCE(?, student_id), updated_at = ? WHERE id = ?",
                            (name, sid, now, target_id),
                        )
                if target_id is None:
                    target_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO students (id, class_slug, name, student_id, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (target_id, slug, name, sid, now, now),
                    )

            conn.execute(
                "INSERT INTO embeddings (student_id, vector) VALUES (?, ?)",
                (target_id, json.dumps(emb)),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM students WHERE id = ?", (target_id,)).fetchone()
            return self._student_from_row(conn, row)

    def delete(self, person_id: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM students WHERE id = ?", (person_id,))
            conn.commit()
            return cur.rowcount > 0

    def record_face_events(
        self,
        *,
        class_slug: str,
        source_request_id: str,
        faces: list[dict],
    ) -> list[ScopedAttendanceEvent]:
        slug = normalize_class_slug(class_slug)
        now = _now()
        seen: set[str] = set()
        to_add: list[tuple] = []
        for face in faces:
            if not face.get("matched"):
                continue
            student_id = face.get("person_id")
            name = face.get("name")
            if not student_id or not name:
                continue
            if student_id in seen:
                continue
            seen.add(student_id)
            to_add.append(
                (
                    str(uuid.uuid4()),
                    slug,
                    student_id,
                    name,
                    float(face.get("match_score") or 0.0),
                    now,
                    source_request_id,
                    face.get("face_id"),
                )
            )
        if not to_add:
            return []

        with self._lock, self._conn() as conn:
            conn.executemany(
                "INSERT INTO attendance_events "
                "(id, class_slug, student_id, name, match_score, timestamp, source_request_id, face_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                to_add,
            )
            conn.commit()

        return [
            ScopedAttendanceEvent(
                id=r[0],
                class_slug=r[1],
                student_id=r[2],
                name=r[3],
                match_score=r[4],
                timestamp=r[5],
                source_request_id=r[6],
                face_id=r[7],
            )
            for r in to_add
        ]

    def list_face_events(self, class_slug: str, limit: int = 100) -> list[ScopedAttendanceEvent]:
        slug = normalize_class_slug(class_slug)
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM attendance_events WHERE class_slug = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (slug, max(0, limit)),
            ).fetchall()
            return [
                ScopedAttendanceEvent(
                    id=r["id"],
                    class_slug=r["class_slug"],
                    student_id=r["student_id"],
                    name=r["name"],
                    match_score=float(r["match_score"]),
                    timestamp=r["timestamp"],
                    source_request_id=r["source_request_id"],
                    face_id=r["face_id"],
                )
                for r in rows
            ]

    def set_daily_roll(
        self,
        *,
        class_slug: str,
        attendance_date: str,
        present_student_ids: list[str],
    ) -> DailyRoll:
        slug = normalize_class_slug(class_slug)
        date = validate_attendance_date(attendance_date)
        # Deduplicate while preserving order
        seen: set[str] = set()
        ids: list[str] = []
        for pid in present_student_ids:
            pid = (pid or "").strip()
            if not pid or pid in seen:
                continue
            seen.add(pid)
            ids.append(pid)

        now = _now()
        with self._lock, self._conn() as conn:
            present_rows: list[tuple[str, str]] = []
            for pid in ids:
                row = conn.execute(
                    "SELECT id, name, class_slug FROM students WHERE id = ?",
                    (pid,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown student_id: {pid}")
                if row["class_slug"] != slug:
                    raise ValueError(f"student {pid} not in class_slug {slug}")
                present_rows.append((row["id"], row["name"]))

            existing = conn.execute(
                "SELECT id, created_at FROM daily_attendance WHERE class_slug = ? AND attendance_date = ?",
                (slug, date),
            ).fetchone()
            if existing:
                daily_id = existing["id"]
                created_at = existing["created_at"]
                conn.execute(
                    "UPDATE daily_attendance SET updated_at = ? WHERE id = ?",
                    (now, daily_id),
                )
                conn.execute("DELETE FROM daily_attendance_present WHERE daily_id = ?", (daily_id,))
            else:
                daily_id = str(uuid.uuid4())
                created_at = now
                conn.execute(
                    "INSERT INTO daily_attendance (id, class_slug, attendance_date, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (daily_id, slug, date, created_at, now),
                )

            if present_rows:
                conn.executemany(
                    "INSERT INTO daily_attendance_present (daily_id, student_id, name) VALUES (?, ?, ?)",
                    [(daily_id, sid, name) for sid, name in present_rows],
                )
            conn.commit()

            return DailyRoll(
                id=daily_id,
                class_slug=slug,
                attendance_date=date,
                present=[DailyPresent(student_id=s, name=n) for s, n in present_rows],
                created_at=created_at,
                updated_at=now,
            )

    def get_daily_roll(self, class_slug: str, attendance_date: str) -> DailyRoll | None:
        slug = normalize_class_slug(class_slug)
        date = validate_attendance_date(attendance_date)
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM daily_attendance WHERE class_slug = ? AND attendance_date = ?",
                (slug, date),
            ).fetchone()
            if row is None:
                return None
            presents = conn.execute(
                "SELECT student_id, name FROM daily_attendance_present WHERE daily_id = ? ORDER BY name COLLATE NOCASE",
                (row["id"],),
            ).fetchall()
            return DailyRoll(
                id=row["id"],
                class_slug=row["class_slug"],
                attendance_date=row["attendance_date"],
                present=[DailyPresent(student_id=p["student_id"], name=p["name"]) for p in presents],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def list_class_slugs(self) -> list[str]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT class_slug FROM students ORDER BY class_slug"
            ).fetchall()
            return [r["class_slug"] for r in rows]

    def day_status(self, class_slug: str, attendance_date: str) -> DayStatus:
        slug = normalize_class_slug(class_slug)
        date = validate_attendance_date(attendance_date)
        people = self.list_people(slug)
        roster = [
            DailyPresent(student_id=p.id, name=p.name)
            for p in people
        ]
        roll = self.get_daily_roll(slug, date)
        if roll is None:
            return DayStatus(
                class_slug=slug,
                attendance_date=date,
                has_roll=False,
                present=[],
                absent=roster,
            )
        present_ids = {p.student_id for p in roll.present}
        present = list(roll.present)
        absent = [p for p in roster if p.student_id not in present_ids]
        return DayStatus(
            class_slug=slug,
            attendance_date=date,
            has_roll=True,
            present=present,
            absent=absent,
        )

    @staticmethod
    def _load_vectors(conn, student_id: str) -> list[list[float]]:
        rows = conn.execute(
            "SELECT vector FROM embeddings WHERE student_id = ? ORDER BY id",
            (student_id,),
        ).fetchall()
        return [json.loads(r["vector"]) for r in rows]

    def _student_from_row(self, conn, row) -> ScopedStudent:
        return ScopedStudent(
            id=row["id"],
            class_slug=row["class_slug"],
            name=row["name"],
            student_id=row["student_id"],
            embeddings=self._load_vectors(conn, row["id"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


scoped_store = ScopedStore()
