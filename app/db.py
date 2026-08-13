"""SQLite connection + schema for v3 class-scoped data."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id TEXT PRIMARY KEY,
    class_slug TEXT NOT NULL,
    name TEXT NOT NULL,
    student_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_students_slug_name
    ON students(class_slug, lower(name));

CREATE UNIQUE INDEX IF NOT EXISTS idx_students_slug_student_id
    ON students(class_slug, student_id) WHERE student_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    vector TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_embeddings_student ON embeddings(student_id);

CREATE TABLE IF NOT EXISTS attendance_events (
    id TEXT PRIMARY KEY,
    class_slug TEXT NOT NULL,
    student_id TEXT NOT NULL,
    name TEXT NOT NULL,
    match_score REAL NOT NULL,
    timestamp TEXT NOT NULL,
    source_request_id TEXT NOT NULL,
    face_id INTEGER
);

CREATE INDEX IF NOT EXISTS idx_attendance_events_slug_ts
    ON attendance_events(class_slug, timestamp DESC);

CREATE TABLE IF NOT EXISTS daily_attendance (
    id TEXT PRIMARY KEY,
    class_slug TEXT NOT NULL,
    attendance_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(class_slug, attendance_date)
);

CREATE TABLE IF NOT EXISTS daily_attendance_present (
    daily_id TEXT NOT NULL REFERENCES daily_attendance(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (daily_id, student_id)
);
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
