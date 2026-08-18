"""One-shot migration from v3 SQLite (students/embeddings) to v4 (refs/samples)."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

from app import db as db_mod
from app.crop_crypto import MODEL_VERSION, encrypt_crop
from app.ref_store import RefStore, crop_key_bytes

_PLACEHOLDER_JPEG = bytes([
    0xFF, 0xD8, 0xFF, 0xDB, 0x00, 0x43, 0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08,
    0x07, 0x07, 0x07, 0x09, 0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C,
    0x19, 0x12, 0x13, 0x0F, 0xFF, 0xD9,
])


def _has_v3_schema(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='students'"
    ).fetchone()
    return row is not None


def _has_v4_schema(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='refs'"
    ).fetchone()
    return row is not None


def migrate_v3_db(source: Path, dest: Path, *, crop_key: str | None = None) -> dict[str, int]:
    """Copy v3 rows into dest v4 schema. Creates dest if missing."""
    if not source.exists():
        raise FileNotFoundError(f"source not found: {source}")

    db_mod.init_db(dest)
    aes = crop_key_bytes(crop_key)
    placeholder_enc = encrypt_crop(aes, _PLACEHOLDER_JPEG)

    src = sqlite3.connect(str(source))
    src.row_factory = sqlite3.Row
    if not _has_v3_schema(src):
        src.close()
        raise ValueError(f"source is not a v3 database: {source}")

    dst = sqlite3.connect(str(dest))
    dst.row_factory = sqlite3.Row
    dst.execute("PRAGMA foreign_keys = ON")
    if not _has_v4_schema(dst):
        dst.close()
        src.close()
        raise ValueError(f"dest missing v4 schema: {dest}")

    stats = {"refs": 0, "samples": 0, "daily_present": 0, "skipped_refs": 0}

    students = src.execute("SELECT * FROM students").fetchall()
    id_map: dict[str, tuple[str, str]] = {}  # old student id -> (scope_key, ref_id)

    for s in students:
        scope_key = (s["class_slug"] or "").strip().lower()
        ref_id = (s["student_id"] or s["id"] or "").strip()
        if not scope_key or not ref_id:
            stats["skipped_refs"] += 1
            continue
        id_map[s["id"]] = (scope_key, ref_id)
        existing = dst.execute(
            "SELECT 1 FROM refs WHERE scope_key = ? AND ref_id = ?",
            (scope_key, ref_id),
        ).fetchone()
        if existing:
            continue
        dst.execute(
            "INSERT INTO refs (scope_key, ref_id, name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (scope_key, ref_id, s["name"], s["created_at"], s["updated_at"]),
        )
        stats["refs"] += 1

    for row in src.execute("SELECT * FROM embeddings").fetchall():
        mapped = id_map.get(row["student_id"])
        if mapped is None:
            continue
        scope_key, ref_id = mapped
        try:
            vec = json.loads(row["vector"])
            blob = np.asarray(vec, dtype=np.float32).ravel().tobytes()
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        st = src.execute("SELECT updated_at FROM students WHERE id = ?", (row["student_id"],)).fetchone()
        created_at = st["updated_at"] if st else "1970-01-01T00:00:00+00:00"
        dst.execute(
            "INSERT INTO samples (scope_key, ref_id, vector, crop_enc, model_version, quality, "
            "created_at, source_request_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                scope_key,
                ref_id,
                blob,
                placeholder_enc,
                MODEL_VERSION,
                None,
                created_at,
                "migrate-v3",
            ),
        )
        stats["samples"] += 1

    # daily rolls: class_slug + student_id -> scope_key + ref_id
    for daily in src.execute("SELECT * FROM daily_attendance").fetchall():
        scope_key = (daily["class_slug"] or "").strip().lower()
        if not scope_key:
            continue
        existing = dst.execute(
            "SELECT id FROM daily_attendance WHERE scope_key = ? AND attendance_date = ?",
            (scope_key, daily["attendance_date"]),
        ).fetchone()
        if existing:
            daily_id = existing["id"]
        else:
            daily_id = daily["id"]
            dst.execute(
                "INSERT INTO daily_attendance (id, scope_key, attendance_date, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (daily_id, scope_key, daily["attendance_date"], daily["created_at"], daily["updated_at"]),
            )
        for p in src.execute(
            "SELECT * FROM daily_attendance_present WHERE daily_id = ?",
            (daily["id"],),
        ).fetchall():
            mapped = id_map.get(p["student_id"])
            if mapped is None:
                continue
            sk, rid = mapped
            try:
                dst.execute(
                    "INSERT OR IGNORE INTO daily_attendance_present (daily_id, scope_key, ref_id) "
                    "VALUES (?, ?, ?)",
                    (daily_id, sk, rid),
                )
                stats["daily_present"] += 1
            except sqlite3.Error:
                pass

    dst.commit()
    src.close()
    dst.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate Whozit v3 SQLite to v4 schema")
    parser.add_argument("--source", type=Path, required=True, help="Path to whozit_v3.db")
    parser.add_argument("--dest", type=Path, required=True, help="Path to whozit.db (v4)")
    parser.add_argument("--crop-key", default="", help="WHOZIT_CROP_KEY for placeholder crops")
    args = parser.parse_args(argv)
    key = args.crop_key.strip() or None
    stats = migrate_v3_db(args.source, args.dest, crop_key=key)
    print(
        f"Migrated refs={stats['refs']} samples={stats['samples']} "
        f"daily_present={stats['daily_present']} skipped={stats['skipped_refs']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
