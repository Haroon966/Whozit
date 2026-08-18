"""SQLite connection + schema for refs / samples / rec_log / daily register."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS refs (
    scope_key TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope_key, ref_id)
);

CREATE INDEX IF NOT EXISTS idx_refs_scope ON refs(scope_key);

CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_key TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    vector BLOB NOT NULL,
    crop_enc BLOB NOT NULL,
    model_version TEXT NOT NULL,
    quality REAL,
    created_at TEXT NOT NULL,
    source_request_id TEXT,
    FOREIGN KEY (scope_key, ref_id) REFERENCES refs(scope_key, ref_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_samples_ref ON samples(scope_key, ref_id);

CREATE TABLE IF NOT EXISTS rec_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_key TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    score REAL NOT NULL,
    margin REAL,
    model_version TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    source_request_id TEXT,
    FOREIGN KEY (scope_key, ref_id) REFERENCES refs(scope_key, ref_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rec_log_scope_ts ON rec_log(scope_key, timestamp DESC);

CREATE TABLE IF NOT EXISTS daily_attendance (
    id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    attendance_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(scope_key, attendance_date)
);

CREATE TABLE IF NOT EXISTS daily_attendance_present (
    daily_id TEXT NOT NULL REFERENCES daily_attendance(id) ON DELETE CASCADE,
    scope_key TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    PRIMARY KEY (daily_id, ref_id),
    FOREIGN KEY (scope_key, ref_id) REFERENCES refs(scope_key, ref_id)
        ON DELETE CASCADE ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS countries (
    code TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS provinces (
    country_code TEXT NOT NULL REFERENCES countries(code) ON UPDATE CASCADE,
    code TEXT NOT NULL,
    PRIMARY KEY (country_code, code)
);

CREATE TABLE IF NOT EXISTS schools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country_code TEXT NOT NULL,
    province_code TEXT NOT NULL,
    emis TEXT NOT NULL,
    name TEXT,
    UNIQUE (country_code, province_code, emis),
    FOREIGN KEY (country_code, province_code)
        REFERENCES provinces(country_code, code) ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    grade TEXT NOT NULL,
    UNIQUE (school_id, grade)
);

CREATE TABLE IF NOT EXISTS students (
    student_id TEXT PRIMARY KEY,
    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    class_id INTEGER NOT NULL REFERENCES classes(id),
    seq INTEGER NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (school_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_students_class ON students(class_id);
CREATE INDEX IF NOT EXISTS idx_students_school ON students(school_id);
"""

_lock = threading.Lock()
_initialized: set[str] = set()


def connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = path or settings.sqlite_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path | None = None) -> Path:
    db_path = path or settings.sqlite_path
    key = str(db_path.resolve())
    with _lock:
        if key in _initialized and db_path.exists():
            return db_path
        with connect(db_path) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()
        _initialized.add(key)
    return db_path
