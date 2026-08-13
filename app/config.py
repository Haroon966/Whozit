"""Env-backed settings for Whozit API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PEOPLE = _ROOT / "data" / "people.json"
_DEFAULT_ATTENDANCE = _ROOT / "data" / "attendance.json"
_DEFAULT_SQLITE = _ROOT / "data" / "whozit_v3.db"


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    max_upload_bytes: int
    max_inflight: int
    match_thresh: float
    people_path: Path
    attendance_path: Path
    sqlite_path: Path

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key)


def load_settings() -> Settings:
    api_key = os.environ.get("WHOZIT_API_KEY", "").strip() or None
    people = os.environ.get("WHOZIT_PEOPLE_PATH", "").strip()
    attendance = os.environ.get("WHOZIT_ATTENDANCE_PATH", "").strip()
    sqlite = os.environ.get("WHOZIT_SQLITE_PATH", "").strip()
    return Settings(
        api_key=api_key,
        max_upload_bytes=_int("WHOZIT_MAX_UPLOAD_BYTES", 10 * 1024 * 1024),
        max_inflight=max(1, _int("WHOZIT_MAX_INFLIGHT", 4)),
        match_thresh=_float("WHOZIT_MATCH_THRESH", 0.35),
        people_path=Path(people) if people else _DEFAULT_PEOPLE,
        attendance_path=Path(attendance) if attendance else _DEFAULT_ATTENDANCE,
        sqlite_path=Path(sqlite) if sqlite else _DEFAULT_SQLITE,
    )


settings = load_settings()
