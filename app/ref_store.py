"""SQLite store: refs keyed by (scope_key, ref_id), samples, rec_log, daily register."""

from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from app import db as db_mod
from app.config import settings
from app.crop_crypto import MODEL_VERSION, crop_key_bytes, encrypt_crop

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:[/_-][a-z0-9]+)*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MAX_SLUG_LEN = 200
_MAX_REF_LEN = 200
_MAX_NAME_LEN = 200


def normalize_scope_key(raw: str) -> str:
    slug = raw.strip().lower()
    while "//" in slug:
        slug = slug.replace("//", "/")
    slug = slug.strip("/")
    if not slug:
        raise ValueError("scope_key is required")
    if len(slug) > _MAX_SLUG_LEN:
        raise ValueError(f"scope_key max length is {_MAX_SLUG_LEN}")
    if not _SLUG_RE.match(slug):
        raise ValueError(
            "scope_key must be path-like lowercase tokens "
            "(a-z0-9) separated by / _ or -"
        )
    return slug


def normalize_ref_id(raw: str) -> str:
    rid = raw.strip()
    if not rid:
        raise ValueError("ref_id is required")
    if len(rid) > _MAX_REF_LEN:
        raise ValueError(f"ref_id max length is {_MAX_REF_LEN}")
    if any(ch in rid for ch in "/\\\x00\n\r"):
        raise ValueError("ref_id must not contain slashes or control characters")
    return rid


def validate_attendance_date(raw: str) -> str:
    date = raw.strip()
    if not _DATE_RE.match(date):
        raise ValueError("date must be YYYY-MM-DD")
    return date


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vector_to_blob(embedding: np.ndarray) -> bytes:
    return embedding.astype(np.float32, copy=False).ravel().tobytes()


def _blob_to_vector(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).copy()


@dataclass
class Ref:
    scope_key: str
    ref_id: str
    name: str
    sample_count: int
    created_at: str
    updated_at: str
    sample_ids: list[int] = field(default_factory=list)


@dataclass
class DailyPresent:
    ref_id: str
    name: str


@dataclass
class DailyRoll:
    id: str
    scope_key: str
    attendance_date: str
    present: list[DailyPresent]
    created_at: str
    updated_at: str


@dataclass
class DayStatus:
    scope_key: str
    attendance_date: str
    has_roll: bool
    present: list[DailyPresent]
    absent: list[DailyPresent]


@dataclass
class SampleVec:
    sample_id: int
    vector: np.ndarray
    model_version: str


@dataclass
class GalleryRef:
    ref_id: str
    name: str
    samples: list[SampleVec]


@dataclass
class SampleRow:
    id: int
    scope_key: str
    ref_id: str
    model_version: str
    quality: float | None
    created_at: str
    has_crop: bool


@dataclass
class RecLogRow:
    id: int
    scope_key: str
    ref_id: str
    name: str
    score: float
    margin: float | None
    model_version: str
    timestamp: str
    source_request_id: str | None


class RefStore:
    def __init__(self, path: Path | None = None, crop_key: str | None = None) -> None:
        self.path = path or settings.sqlite_path
        self._lock = threading.Lock()
        self._aes_key = crop_key_bytes(crop_key if crop_key is not None else settings.crop_key)
        db_mod.init_db(self.path)

    def _org(self):
        from app.org_store import OrgStore

        return OrgStore(path=self.path)

    def _conn(self) -> sqlite3.Connection:
        return db_mod.connect(self.path)

    def count_refs(self) -> int:
        with self._lock, self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM refs").fetchone()
            return int(row["n"])

    def list_refs(self, scope_key: str) -> list[Ref]:
        slug = normalize_scope_key(scope_key)
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT r.*, "
                "(SELECT COUNT(*) FROM samples s WHERE s.scope_key = r.scope_key AND s.ref_id = r.ref_id) "
                "AS sample_count "
                "FROM refs r WHERE r.scope_key = ? ORDER BY r.name COLLATE NOCASE",
                (slug,),
            ).fetchall()
            return [self._ref_from_row(r) for r in rows]

    def get(self, scope_key: str, ref_id: str) -> Ref | None:
        slug = normalize_scope_key(scope_key)
        rid = normalize_ref_id(ref_id)
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT r.*, "
                "(SELECT COUNT(*) FROM samples s WHERE s.scope_key = r.scope_key AND s.ref_id = r.ref_id) "
                "AS sample_count "
                "FROM refs r WHERE r.scope_key = ? AND r.ref_id = ?",
                (slug, rid),
            ).fetchone()
            if row is None:
                return None
            return self._ref_from_row(row)

    def gallery_for_scope(self, scope_key: str) -> list[GalleryRef]:
        slug = normalize_scope_key(scope_key)
        with self._lock, self._conn() as conn:
            ref_rows = conn.execute(
                "SELECT scope_key, ref_id, name FROM refs WHERE scope_key = ?",
                (slug,),
            ).fetchall()
            sample_rows = conn.execute(
                "SELECT id, ref_id, vector, model_version FROM samples WHERE scope_key = ? ORDER BY id",
                (slug,),
            ).fetchall()
        by_ref: dict[str, list[SampleVec]] = {}
        for s in sample_rows:
            by_ref.setdefault(s["ref_id"], []).append(
                SampleVec(
                    sample_id=int(s["id"]),
                    vector=_blob_to_vector(s["vector"]),
                    model_version=s["model_version"],
                )
            )
        out: list[GalleryRef] = []
        for r in ref_rows:
            samples = by_ref.get(r["ref_id"]) or []
            if not samples:
                continue
            out.append(GalleryRef(ref_id=r["ref_id"], name=r["name"], samples=samples))
        return out

    def enroll(
        self,
        *,
        name: str,
        scope_key: str,
        embedding: np.ndarray,
        crop_jpeg: bytes,
        quality: float | None,
        source_request_id: str,
        ref_id: str | None = None,
        model_version: str = MODEL_VERSION,
    ) -> Ref:
        name = name.strip()
        if not name:
            raise ValueError("name is required")
        if len(name) > _MAX_NAME_LEN:
            raise ValueError(f"name max length is {_MAX_NAME_LEN}")
        slug = normalize_scope_key(scope_key)
        resolved = self._org().resolve_enroll_id(slug, ref_id)
        if resolved is not None:
            rid = resolved
        elif ref_id is None or not str(ref_id).strip():
            rid = str(uuid.uuid4())
        else:
            rid = normalize_ref_id(str(ref_id))
        student = self._org().get_student(rid)
        if student is not None and student.scope_key != slug:
            if self.get(student.scope_key, rid) is not None:
                self.move_ref(student.scope_key, rid, slug)
        now = _now()
        vec = _vector_to_blob(embedding)
        crop_enc = encrypt_crop(self._aes_key, crop_jpeg)

        with self._lock, self._conn() as conn:
            existing = conn.execute(
                "SELECT * FROM refs WHERE scope_key = ? AND ref_id = ?",
                (slug, rid),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO refs (scope_key, ref_id, name, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (slug, rid, name, now, now),
                )
            else:
                conn.execute(
                    "UPDATE refs SET name = ?, updated_at = ? WHERE scope_key = ? AND ref_id = ?",
                    (name, now, slug, rid),
                )
            conn.execute(
                "INSERT INTO samples (scope_key, ref_id, vector, crop_enc, model_version, quality, "
                "created_at, source_request_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (slug, rid, vec, crop_enc, model_version, quality, now, source_request_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT r.*, "
                "(SELECT COUNT(*) FROM samples s WHERE s.scope_key = r.scope_key AND s.ref_id = r.ref_id) "
                "AS sample_count "
                "FROM refs r WHERE r.scope_key = ? AND r.ref_id = ?",
                (slug, rid),
            ).fetchone()
        self._org().attach_student_name(rid, name)
        return self._ref_from_row(row)

    def delete_ref(self, scope_key: str, ref_id: str) -> bool:
        slug = normalize_scope_key(scope_key)
        rid = normalize_ref_id(ref_id)
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM refs WHERE scope_key = ? AND ref_id = ?",
                (slug, rid),
            )
            conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            self._org().delete_student(rid)
        return deleted

    def delete_sample(self, sample_id: int) -> tuple[str, str] | None:
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT scope_key, ref_id FROM samples WHERE id = ?",
                (sample_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute("DELETE FROM samples WHERE id = ?", (sample_id,))
            conn.commit()
            return row["scope_key"], row["ref_id"]

    def record_matches(
        self,
        *,
        scope_key: str,
        source_request_id: str,
        matches: list[dict],
        model_version: str = MODEL_VERSION,
    ) -> None:
        slug = normalize_scope_key(scope_key)
        now = _now()
        cutoff = None
        if settings.rec_log_ttl_days > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.rec_log_ttl_days)).isoformat()
        rows = [
            (
                slug,
                m["ref_id"],
                float(m["score"]),
                m.get("margin"),
                model_version,
                now,
                source_request_id,
            )
            for m in matches
            if m.get("ref_id")
        ]
        with self._lock, self._conn() as conn:
            if cutoff:
                conn.execute("DELETE FROM rec_log WHERE timestamp < ?", (cutoff,))
            if rows:
                conn.executemany(
                    "INSERT INTO rec_log (scope_key, ref_id, score, margin, model_version, timestamp, source_request_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
            conn.commit()

    def set_daily_roll(
        self,
        *,
        scope_key: str,
        attendance_date: str,
        present_ref_ids: list[str],
    ) -> DailyRoll:
        slug = normalize_scope_key(scope_key)
        date = validate_attendance_date(attendance_date)
        seen: set[str] = set()
        ids: list[str] = []
        for pid in present_ref_ids:
            pid = (pid or "").strip()
            if not pid or pid in seen:
                continue
            seen.add(pid)
            ids.append(normalize_ref_id(pid))

        now = _now()
        with self._lock, self._conn() as conn:
            present_rows: list[tuple[str, str]] = []
            for pid in ids:
                row = conn.execute(
                    "SELECT ref_id, name FROM refs WHERE scope_key = ? AND ref_id = ?",
                    (slug, pid),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown ref_id: {pid}")
                present_rows.append((row["ref_id"], row["name"]))

            existing = conn.execute(
                "SELECT id, created_at FROM daily_attendance WHERE scope_key = ? AND attendance_date = ?",
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
                    "INSERT INTO daily_attendance (id, scope_key, attendance_date, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (daily_id, slug, date, created_at, now),
                )

            if present_rows:
                conn.executemany(
                    "INSERT INTO daily_attendance_present (daily_id, scope_key, ref_id) VALUES (?, ?, ?)",
                    [(daily_id, slug, rid) for rid, _name in present_rows],
                )
            conn.commit()
            return DailyRoll(
                id=daily_id,
                scope_key=slug,
                attendance_date=date,
                present=[DailyPresent(ref_id=r, name=n) for r, n in present_rows],
                created_at=created_at,
                updated_at=now,
            )

    def get_daily_roll(self, scope_key: str, attendance_date: str) -> DailyRoll | None:
        slug = normalize_scope_key(scope_key)
        date = validate_attendance_date(attendance_date)
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM daily_attendance WHERE scope_key = ? AND attendance_date = ?",
                (slug, date),
            ).fetchone()
            if row is None:
                return None
            presents = conn.execute(
                "SELECT p.ref_id, r.name FROM daily_attendance_present p "
                "JOIN refs r ON r.scope_key = p.scope_key AND r.ref_id = p.ref_id "
                "WHERE p.daily_id = ? ORDER BY r.name COLLATE NOCASE",
                (row["id"],),
            ).fetchall()
            return DailyRoll(
                id=row["id"],
                scope_key=row["scope_key"],
                attendance_date=row["attendance_date"],
                present=[DailyPresent(ref_id=p["ref_id"], name=p["name"]) for p in presents],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def list_scopes(self) -> list[str]:
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT scope_key FROM refs ORDER BY scope_key"
            ).fetchall()
            return [r["scope_key"] for r in rows]

    def day_status(self, scope_key: str, attendance_date: str) -> DayStatus:
        slug = normalize_scope_key(scope_key)
        date = validate_attendance_date(attendance_date)
        people = self.list_refs(slug)
        roster = [DailyPresent(ref_id=p.ref_id, name=p.name) for p in people]
        roll = self.get_daily_roll(slug, date)
        if roll is None:
            return DayStatus(
                scope_key=slug,
                attendance_date=date,
                has_roll=False,
                present=[],
                absent=roster,
            )
        present_ids = {p.ref_id for p in roll.present}
        present = list(roll.present)
        absent = [p for p in roster if p.ref_id not in present_ids]
        return DayStatus(
            scope_key=slug,
            attendance_date=date,
            has_roll=True,
            present=present,
            absent=absent,
        )

    def move_ref(self, scope_key: str, ref_id: str, new_scope_key: str) -> Ref:
        old = normalize_scope_key(scope_key)
        new = normalize_scope_key(new_scope_key)
        rid = normalize_ref_id(ref_id)
        from app.org_store import parse_class_scope

        old_org = parse_class_scope(old)
        new_org = parse_class_scope(new)
        if old_org and new_org and old_org[:3] != new_org[:3]:
            raise ValueError("cannot move student to a different school; student_id is school-scoped")
        if old == new:
            got = self.get(old, rid)
            if got is None:
                raise KeyError(f"ref_id not found: {rid}")
            return got
        now = _now()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM refs WHERE scope_key = ? AND ref_id = ?",
                (old, rid),
            ).fetchone()
            if row is None:
                raise KeyError(f"ref_id not found: {rid}")
            clash = conn.execute(
                "SELECT 1 FROM refs WHERE scope_key = ? AND ref_id = ?",
                (new, rid),
            ).fetchone()
            if clash is not None:
                raise ValueError(f"ref_id {rid} already exists in {new}")
            conn.execute(
                "DELETE FROM daily_attendance_present WHERE scope_key = ? AND ref_id = ?",
                (old, rid),
            )
            conn.execute(
                "UPDATE refs SET scope_key = ?, updated_at = ? WHERE scope_key = ? AND ref_id = ?",
                (new, now, old, rid),
            )
            conn.commit()
        self._org().set_student_class(rid, new)
        got = self.get(new, rid)
        assert got is not None
        return got

    def move_scope(self, old_scope_key: str, new_scope_key: str) -> int:
        old = normalize_scope_key(old_scope_key)
        new = normalize_scope_key(new_scope_key)
        if old == new:
            return 0
        from app.org_store import parse_class_scope

        old_org = parse_class_scope(old)
        new_org = parse_class_scope(new)
        if old_org and new_org and old_org[:3] != new_org[:3]:
            raise ValueError("cannot move class to a different school; student_id is school-scoped")
        now = _now()
        with self._lock, self._conn() as conn:
            clash = conn.execute(
                "SELECT r.ref_id FROM refs r "
                "WHERE r.scope_key = ? AND EXISTS ("
                "  SELECT 1 FROM refs x WHERE x.scope_key = ? AND x.ref_id = r.ref_id"
                ")",
                (old, new),
            ).fetchone()
            if clash is not None:
                raise ValueError(f"ref_id {clash['ref_id']} already exists in {new}")
            cur = conn.execute(
                "UPDATE refs SET scope_key = ?, updated_at = ? WHERE scope_key = ?",
                (new, now, old),
            )
            conn.execute(
                "UPDATE daily_attendance SET scope_key = ? WHERE scope_key = ?",
                (new, old),
            )
            conn.commit()
            n = cur.rowcount
        org = self._org()
        for person in self.list_refs(new):
            org.set_student_class(person.ref_id, new)
        return n

    def purge_rec_log(self) -> int:
        if settings.rec_log_ttl_days <= 0:
            return 0
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=settings.rec_log_ttl_days)
        ).isoformat()
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM rec_log WHERE timestamp < ?", (cutoff,))
            conn.commit()
            return cur.rowcount

    def update_ref_name(self, scope_key: str, ref_id: str, name: str) -> Ref:
        name = name.strip()
        if not name:
            raise ValueError("name is required")
        if len(name) > _MAX_NAME_LEN:
            raise ValueError(f"name max length is {_MAX_NAME_LEN}")
        slug = normalize_scope_key(scope_key)
        rid = normalize_ref_id(ref_id)
        now = _now()
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "UPDATE refs SET name = ?, updated_at = ? WHERE scope_key = ? AND ref_id = ?",
                (name, now, slug, rid),
            )
            if cur.rowcount == 0:
                raise KeyError(f"ref_id not found: {rid}")
            conn.commit()
        self._org().attach_student_name(rid, name)
        got = self.get(slug, rid)
        assert got is not None
        return got

    def list_samples(self, scope_key: str, ref_id: str) -> list[SampleRow]:
        slug = normalize_scope_key(scope_key)
        rid = normalize_ref_id(ref_id)
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT id, scope_key, ref_id, model_version, quality, created_at, "
                "length(crop_enc) AS crop_len FROM samples "
                "WHERE scope_key = ? AND ref_id = ? ORDER BY id",
                (slug, rid),
            ).fetchall()
            return [
                SampleRow(
                    id=int(r["id"]),
                    scope_key=r["scope_key"],
                    ref_id=r["ref_id"],
                    model_version=r["model_version"],
                    quality=r["quality"],
                    created_at=r["created_at"],
                    has_crop=int(r["crop_len"] or 0) > 20,
                )
                for r in rows
            ]

    def list_rec_log(self, scope_key: str | None = None, limit: int = 100) -> list[RecLogRow]:
        limit = max(1, min(limit, 500))
        with self._lock, self._conn() as conn:
            if scope_key:
                slug = normalize_scope_key(scope_key)
                rows = conn.execute(
                    "SELECT l.*, r.name FROM rec_log l "
                    "JOIN refs r ON r.scope_key = l.scope_key AND r.ref_id = l.ref_id "
                    "WHERE l.scope_key = ? ORDER BY l.timestamp DESC LIMIT ?",
                    (slug, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT l.*, r.name FROM rec_log l "
                    "JOIN refs r ON r.scope_key = l.scope_key AND r.ref_id = l.ref_id "
                    "ORDER BY l.timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                RecLogRow(
                    id=int(r["id"]),
                    scope_key=r["scope_key"],
                    ref_id=r["ref_id"],
                    name=r["name"],
                    score=float(r["score"]),
                    margin=r["margin"],
                    model_version=r["model_version"],
                    timestamp=r["timestamp"],
                    source_request_id=r["source_request_id"],
                )
                for r in rows
            ]

    def iter_samples_for_reembed(self, scope_key: str | None = None) -> list[sqlite3.Row]:
        with self._lock, self._conn() as conn:
            if scope_key:
                slug = normalize_scope_key(scope_key)
                return conn.execute(
                    "SELECT id, scope_key, ref_id, vector, crop_enc, model_version FROM samples "
                    "WHERE scope_key = ? ORDER BY id",
                    (slug,),
                ).fetchall()
            return conn.execute(
                "SELECT id, scope_key, ref_id, vector, crop_enc, model_version FROM samples ORDER BY id"
            ).fetchall()

    def update_sample_vector(
        self, sample_id: int, embedding: np.ndarray, model_version: str
    ) -> None:
        vec = _vector_to_blob(embedding)
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "UPDATE samples SET vector = ?, model_version = ? WHERE id = ?",
                (vec, model_version, sample_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"sample not found: {sample_id}")
            conn.commit()

    def wipe_program_data(self) -> dict[str, int]:
        """Delete all refs (cascades samples, rec_log, daily present)."""
        with self._lock, self._conn() as conn:
            n_refs = conn.execute("SELECT COUNT(*) AS n FROM refs").fetchone()["n"]
            conn.execute("DELETE FROM daily_attendance_present")
            conn.execute("DELETE FROM daily_attendance")
            conn.execute("DELETE FROM refs")
            conn.execute("DELETE FROM students")
            conn.execute("DELETE FROM classes")
            conn.execute("DELETE FROM schools")
            conn.execute("DELETE FROM provinces")
            conn.execute("DELETE FROM countries")
            conn.commit()
            return {"refs_deleted": int(n_refs)}

    @staticmethod
    def _ref_from_row(row) -> Ref:
        return Ref(
            scope_key=row["scope_key"],
            ref_id=row["ref_id"],
            name=row["name"],
            sample_count=int(row["sample_count"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


ref_store = RefStore()

# Back-compat alias used by older comments; prefer normalize_scope_key.
normalize_class_slug = normalize_scope_key
