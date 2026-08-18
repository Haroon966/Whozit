"""Tests for v3→v4 migration."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from app.migrate_v3 import migrate_v3_db


def _make_v3_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE students (
            id TEXT PRIMARY KEY,
            class_slug TEXT NOT NULL,
            name TEXT NOT NULL,
            student_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            vector TEXT NOT NULL
        );
        CREATE TABLE daily_attendance (
            id TEXT PRIMARY KEY,
            class_slug TEXT NOT NULL,
            attendance_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(class_slug, attendance_date)
        );
        CREATE TABLE daily_attendance_present (
            daily_id TEXT NOT NULL,
            student_id TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (daily_id, student_id)
        );
        """
    )
    conn.execute(
        "INSERT INTO students VALUES (?,?,?,?,?,?)",
        ("uuid-1", "pk/c1", "Ali", "roll-1", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO students VALUES (?,?,?,?,?,?)",
        ("uuid-2", "pk/c1", "Ayesha", None, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    vec = json.dumps(np.zeros(8, dtype=np.float32).tolist())
    conn.execute("INSERT INTO embeddings (student_id, vector) VALUES (?, ?)", ("uuid-1", vec))
    conn.execute("INSERT INTO embeddings (student_id, vector) VALUES (?, ?)", ("uuid-2", vec))
    conn.execute(
        "INSERT INTO daily_attendance VALUES (?,?,?,?,?)",
        ("d1", "pk/c1", "2026-08-13", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    )
    conn.execute(
        "INSERT INTO daily_attendance_present VALUES (?,?,?)",
        ("d1", "uuid-1", "Ali"),
    )
    conn.commit()
    conn.close()


def test_migrate_v3_creates_refs_and_samples(tmp_path):
    src = tmp_path / "v3.db"
    dest = tmp_path / "v4.db"
    _make_v3_db(src)
    stats = migrate_v3_db(src, dest, crop_key="test-key")
    assert stats["refs"] == 2
    assert stats["samples"] == 2
    assert stats["daily_present"] >= 1

    conn = sqlite3.connect(str(dest))
    conn.row_factory = sqlite3.Row
    refs = conn.execute("SELECT * FROM refs WHERE scope_key = 'pk/c1'").fetchall()
    assert len(refs) == 2
    ref_ids = {r["ref_id"] for r in refs}
    assert "roll-1" in ref_ids
    assert "uuid-2" in ref_ids  # minted from student id when student_id null
    conn.close()
