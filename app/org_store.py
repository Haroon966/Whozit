"""Country / province / school / class / student identity.

student_id = {country}+{province}+{emis}+{seq}  (class is assignment, not in the id)
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app import db as db_mod
from app.config import settings
from app.ref_store import normalize_scope_key

_TOKEN_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_STUDENT_ID_RE = re.compile(
    r"^([a-z0-9]+(?:-[a-z0-9]+)*)\+([a-z0-9]+(?:-[a-z0-9]+)*)\+"
    r"([a-z0-9]+(?:-[a-z0-9]+)*)\+(\d{3,})$"
)
_MAX_TOKEN = 64
_SEQ_WIDTH = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_token(raw: str, *, label: str) -> str:
    token = raw.strip().lower()
    if not token:
        raise ValueError(f"{label} is required")
    if len(token) > _MAX_TOKEN:
        raise ValueError(f"{label} max length is {_MAX_TOKEN}")
    if not _TOKEN_RE.match(token):
        raise ValueError(f"{label} must be lowercase a-z0-9 tokens separated by -")
    return token


def build_student_id(country: str, province: str, emis: str, seq: int) -> str:
    if seq < 1:
        raise ValueError("seq must be >= 1")
    return f"{country}+{province}+{emis}+{seq:0{_SEQ_WIDTH}d}"


def parse_student_id(raw: str) -> tuple[str, str, str, int] | None:
    text = raw.strip().lower()
    match = _STUDENT_ID_RE.match(text)
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3), int(match.group(4))


def class_scope_key(country: str, province: str, emis: str, grade: str) -> str:
    return normalize_scope_key(f"{country}/{province}/{emis}/{grade}")


def parse_class_scope(scope_key: str) -> tuple[str, str, str, str] | None:
    slug = normalize_scope_key(scope_key)
    parts = slug.split("/")
    if len(parts) != 4:
        return None
    try:
        country = normalize_token(parts[0], label="country")
        province = normalize_token(parts[1], label="province")
        emis = normalize_token(parts[2], label="emis")
        grade = normalize_token(parts[3], label="grade")
    except ValueError:
        return None
    return country, province, emis, grade


def seq_from_legacy_ref(ref_id: str) -> int | None:
    digits = re.search(r"(\d+)$", (ref_id or "").strip())
    if not digits:
        return None
    value = int(digits.group(1))
    return value if value >= 1 else None


@dataclass
class School:
    id: int
    country_code: str
    province_code: str
    emis: str
    name: str | None


@dataclass
class ClassRow:
    id: int
    school_id: int
    grade: str
    scope_key: str
    country_code: str
    province_code: str
    emis: str


@dataclass
class Student:
    student_id: str
    name: str
    seq: int
    school_id: int
    class_id: int
    country_code: str
    province_code: str
    emis: str
    grade: str
    scope_key: str
    sample_count: int
    created_at: str
    updated_at: str


class OrgStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.sqlite_path
        self._lock = threading.RLock()
        db_mod.init_db(self.path)

    def _conn(self) -> sqlite3.Connection:
        return db_mod.connect(self.path)

    def list_countries(self) -> list[str]:
        with self._lock, self._conn() as conn:
            rows = conn.execute("SELECT code FROM countries ORDER BY code").fetchall()
            return [r["code"] for r in rows]

    def list_provinces(self, country: str) -> list[str]:
        code = normalize_token(country, label="country")
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT code FROM provinces WHERE country_code = ? ORDER BY code",
                (code,),
            ).fetchall()
            return [r["code"] for r in rows]

    def list_schools(self, country: str, province: str) -> list[School]:
        c = normalize_token(country, label="country")
        p = normalize_token(province, label="province")
        with self._lock, self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM schools WHERE country_code = ? AND province_code = ? ORDER BY emis",
                (c, p),
            ).fetchall()
            return [_school(r) for r in rows]

    def list_classes(self, school_id: int) -> list[ClassRow]:
        with self._lock, self._conn() as conn:
            school = conn.execute("SELECT * FROM schools WHERE id = ?", (school_id,)).fetchone()
            if school is None:
                raise KeyError(f"school not found: {school_id}")
            rows = conn.execute(
                "SELECT * FROM classes WHERE school_id = ? ORDER BY grade",
                (school_id,),
            ).fetchall()
            return [_class_row(r, school) for r in rows]

    def ensure_school(
        self,
        *,
        country: str,
        province: str,
        emis: str,
        name: str | None = None,
    ) -> School:
        c = normalize_token(country, label="country")
        p = normalize_token(province, label="province")
        e = normalize_token(emis, label="emis")
        label = (name or "").strip() or None
        with self._lock, self._conn() as conn:
            school = _ensure_school(conn, c, p, e, label)
            conn.commit()
            return school

    def ensure_class(
        self,
        *,
        country: str,
        province: str,
        emis: str,
        grade: str,
        school_name: str | None = None,
    ) -> ClassRow:
        c = normalize_token(country, label="country")
        p = normalize_token(province, label="province")
        e = normalize_token(emis, label="emis")
        g = normalize_token(grade, label="grade")
        with self._lock, self._conn() as conn:
            school = _ensure_school(conn, c, p, e, school_name)
            row = _ensure_class(conn, school.id, g)
            conn.commit()
            return _class_row(row, school)

    def resolve_enroll_id(self, scope_key: str, ref_id: str | None) -> str | None:
        """If scope is a 4-part class path, return stable student_id (mint or reuse)."""
        parsed = parse_class_scope(scope_key)
        if parsed is None:
            return None
        country, province, emis, grade = parsed
        klass = self.ensure_class(country=country, province=province, emis=emis, grade=grade)
        supplied = (ref_id or "").strip().lower()
        parsed_sid = parse_student_id(supplied) if supplied else None
        if parsed_sid:
            sc, sp, se, seq = parsed_sid
            if (sc, sp, se) != (country, province, emis):
                raise ValueError("student_id does not belong to this school")
            return self._upsert_existing(klass, supplied, seq)
        return self._mint(klass)

    def attach_student_name(self, student_id: str, name: str, class_id: int | None = None) -> None:
        now = _now()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM students WHERE student_id = ?",
                (student_id,),
            ).fetchone()
            if row is None:
                return
            if class_id is None:
                conn.execute(
                    "UPDATE students SET name = ?, updated_at = ? WHERE student_id = ?",
                    (name, now, student_id),
                )
            else:
                conn.execute(
                    "UPDATE students SET name = ?, class_id = ?, updated_at = ? WHERE student_id = ?",
                    (name, class_id, now, student_id),
                )
            conn.commit()

    def set_student_class(self, student_id: str, new_scope_key: str) -> None:
        parsed = parse_class_scope(new_scope_key)
        if parsed is None:
            return
        country, province, emis, grade = parsed
        klass = self.ensure_class(country=country, province=province, emis=emis, grade=grade)
        now = _now()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM students WHERE student_id = ?",
                (student_id,),
            ).fetchone()
            if row is None:
                return
            if int(row["school_id"]) != klass.school_id:
                raise ValueError("cannot move student to a different school; student_id is school-scoped")
            conn.execute(
                "UPDATE students SET class_id = ?, updated_at = ? WHERE student_id = ?",
                (klass.id, now, student_id),
            )
            conn.commit()

    def delete_student(self, student_id: str) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute("DELETE FROM students WHERE student_id = ?", (student_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_student(self, student_id: str) -> Student | None:
        sid = student_id.strip().lower()
        with self._lock, self._conn() as conn:
            row = _student_join(conn, "s.student_id = ?", (sid,))
            return _student(row) if row else None

    def list_students(self, *, school_id: int | None = None, class_id: int | None = None) -> list[Student]:
        if class_id is not None:
            where, args = "s.class_id = ?", (class_id,)
        elif school_id is not None:
            where, args = "s.school_id = ?", (school_id,)
        else:
            raise ValueError("school_id or class_id is required")
        with self._lock, self._conn() as conn:
            rows = _student_join_all(conn, where, args)
            return [_student(r) for r in rows]

    def backfill_from_refs(self) -> dict[str, int]:
        stats = {"students": 0, "updated_refs": 0, "skipped": 0}
        with self._lock, self._conn() as conn:
            refs = conn.execute("SELECT scope_key, ref_id, name, created_at, updated_at FROM refs").fetchall()
            for ref in refs:
                parsed = parse_class_scope(ref["scope_key"])
                if parsed is None:
                    stats["skipped"] += 1
                    continue
                country, province, emis, grade = parsed
                school = _ensure_school(conn, country, province, emis, None)
                class_row = _ensure_class(conn, school.id, grade)
                existing = conn.execute(
                    "SELECT 1 FROM students WHERE student_id = ?",
                    (ref["ref_id"],),
                ).fetchone()
                if existing:
                    stats["skipped"] += 1
                    continue
                parsed_sid = parse_student_id(ref["ref_id"])
                if parsed_sid and parsed_sid[:3] == (country, province, emis):
                    student_id = ref["ref_id"]
                    seq = parsed_sid[3]
                else:
                    seq = seq_from_legacy_ref(ref["ref_id"])
                    if seq is None or _seq_taken(conn, school.id, seq):
                        seq = _next_seq(conn, school.id)
                    student_id = build_student_id(country, province, emis, seq)
                clash = conn.execute(
                    "SELECT 1 FROM students WHERE student_id = ?",
                    (student_id,),
                ).fetchone()
                if clash:
                    stats["skipped"] += 1
                    continue
                if student_id != ref["ref_id"]:
                    taken = conn.execute(
                        "SELECT 1 FROM refs WHERE scope_key = ? AND ref_id = ?",
                        (ref["scope_key"], student_id),
                    ).fetchone()
                    if taken:
                        stats["skipped"] += 1
                        continue
                    conn.execute(
                        "UPDATE refs SET ref_id = ? WHERE scope_key = ? AND ref_id = ?",
                        (student_id, ref["scope_key"], ref["ref_id"]),
                    )
                    stats["updated_refs"] += 1
                conn.execute(
                    "INSERT INTO students (student_id, school_id, class_id, seq, name, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        student_id,
                        school.id,
                        class_row["id"],
                        seq,
                        ref["name"],
                        ref["created_at"],
                        ref["updated_at"],
                    ),
                )
                stats["students"] += 1
            conn.commit()
        return stats

    def _mint(self, klass: ClassRow) -> str:
        now = _now()
        with self._lock, self._conn() as conn:
            seq = _next_seq(conn, klass.school_id)
            student_id = build_student_id(klass.country_code, klass.province_code, klass.emis, seq)
            conn.execute(
                "INSERT INTO students (student_id, school_id, class_id, seq, name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (student_id, klass.school_id, klass.id, seq, "", now, now),
            )
            conn.commit()
            return student_id

    def _upsert_existing(self, klass: ClassRow, student_id: str, seq: int) -> str:
        now = _now()
        with self._lock, self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM students WHERE student_id = ?",
                (student_id,),
            ).fetchone()
            if row:
                if int(row["school_id"]) != klass.school_id:
                    raise ValueError("student_id already belongs to another school")
                return student_id
            taken = conn.execute(
                "SELECT 1 FROM students WHERE school_id = ? AND seq = ?",
                (klass.school_id, seq),
            ).fetchone()
            if taken:
                raise ValueError(f"seq {seq} already used at this school")
            conn.execute(
                "INSERT INTO students (student_id, school_id, class_id, seq, name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (student_id, klass.school_id, klass.id, seq, "", now, now),
            )
            conn.commit()
            return student_id


def _ensure_school(conn: sqlite3.Connection, country: str, province: str, emis: str, name: str | None) -> School:
    conn.execute("INSERT OR IGNORE INTO countries (code) VALUES (?)", (country,))
    conn.execute(
        "INSERT OR IGNORE INTO provinces (country_code, code) VALUES (?, ?)",
        (country, province),
    )
    conn.execute(
        "INSERT OR IGNORE INTO schools (country_code, province_code, emis, name) VALUES (?, ?, ?, ?)",
        (country, province, emis, name),
    )
    if name:
        conn.execute(
            "UPDATE schools SET name = COALESCE(name, ?) WHERE country_code = ? AND province_code = ? AND emis = ?",
            (name, country, province, emis),
        )
    row = conn.execute(
        "SELECT * FROM schools WHERE country_code = ? AND province_code = ? AND emis = ?",
        (country, province, emis),
    ).fetchone()
    return _school(row)


def _ensure_class(conn: sqlite3.Connection, school_id: int, grade: str) -> sqlite3.Row:
    conn.execute(
        "INSERT OR IGNORE INTO classes (school_id, grade) VALUES (?, ?)",
        (school_id, grade),
    )
    return conn.execute(
        "SELECT * FROM classes WHERE school_id = ? AND grade = ?",
        (school_id, grade),
    ).fetchone()


def _next_seq(conn: sqlite3.Connection, school_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) AS n FROM students WHERE school_id = ?",
        (school_id,),
    ).fetchone()
    return int(row["n"]) + 1


def _seq_taken(conn: sqlite3.Connection, school_id: int, seq: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM students WHERE school_id = ? AND seq = ?",
        (school_id, seq),
    ).fetchone()
    return row is not None


def _school(row: sqlite3.Row) -> School:
    return School(
        id=int(row["id"]),
        country_code=row["country_code"],
        province_code=row["province_code"],
        emis=row["emis"],
        name=row["name"],
    )


def _class_row(row: sqlite3.Row, school: sqlite3.Row | School) -> ClassRow:
    if isinstance(school, School):
        country, province, emis, school_id = school.country_code, school.province_code, school.emis, school.id
    else:
        country, province, emis, school_id = (
            school["country_code"],
            school["province_code"],
            school["emis"],
            int(school["id"]),
        )
    grade = row["grade"]
    return ClassRow(
        id=int(row["id"]),
        school_id=school_id,
        grade=grade,
        scope_key=class_scope_key(country, province, emis, grade),
        country_code=country,
        province_code=province,
        emis=emis,
    )


_STUDENT_SELECT = """
SELECT s.*, c.grade, sch.country_code, sch.province_code, sch.emis,
       (SELECT COUNT(*) FROM samples x WHERE x.ref_id = s.student_id) AS sample_count
FROM students s
JOIN classes c ON c.id = s.class_id
JOIN schools sch ON sch.id = s.school_id
"""


def _student_join(conn: sqlite3.Connection, where: str, args: tuple) -> sqlite3.Row | None:
    return conn.execute(f"{_STUDENT_SELECT} WHERE {where}", args).fetchone()


def _student_join_all(conn: sqlite3.Connection, where: str, args: tuple) -> list[sqlite3.Row]:
    return conn.execute(
        f"{_STUDENT_SELECT} WHERE {where} ORDER BY s.name COLLATE NOCASE",
        args,
    ).fetchall()


def _student(row: sqlite3.Row) -> Student:
    country, province, emis, grade = (
        row["country_code"],
        row["province_code"],
        row["emis"],
        row["grade"],
    )
    return Student(
        student_id=row["student_id"],
        name=row["name"],
        seq=int(row["seq"]),
        school_id=int(row["school_id"]),
        class_id=int(row["class_id"]),
        country_code=country,
        province_code=province,
        emis=emis,
        grade=grade,
        scope_key=class_scope_key(country, province, emis, grade),
        sample_count=int(row["sample_count"] or 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


org_store = OrgStore()
