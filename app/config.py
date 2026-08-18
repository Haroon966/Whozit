"""Env-backed settings for Whozit API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SQLITE = _ROOT / "data" / "whozit.db"


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
    sqlite_path: Path
    crop_key: str | None
    rec_log_ttl_days: int
    gallery_lru_size: int
    session_ttl_seconds: int
    min_enroll_quality: float | None
    migrate_v3_path: Path | None
    require_crop_key: bool

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def crop_key_insecure(self) -> bool:
        return self.crop_key is None


def _optional_float(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return float(raw)


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    api_key = os.environ.get("WHOZIT_API_KEY", "").strip() or None
    sqlite = os.environ.get("WHOZIT_SQLITE_PATH", "").strip()
    crop_key = os.environ.get("WHOZIT_CROP_KEY", "").strip() or None
    migrate_v3 = os.environ.get("WHOZIT_MIGRATE_V3_PATH", "").strip()
    auth_on = bool(api_key)
    return Settings(
        api_key=api_key,
        max_upload_bytes=_int("WHOZIT_MAX_UPLOAD_BYTES", 10 * 1024 * 1024),
        max_inflight=max(1, _int("WHOZIT_MAX_INFLIGHT", 4)),
        match_thresh=_float("WHOZIT_MATCH_THRESH", 0.35),
        sqlite_path=Path(sqlite) if sqlite else _DEFAULT_SQLITE,
        crop_key=crop_key,
        rec_log_ttl_days=max(0, _int("WHOZIT_REC_LOG_TTL_DAYS", 90)),
        gallery_lru_size=max(1, _int("WHOZIT_GALLERY_LRU_SIZE", 32)),
        session_ttl_seconds=max(60, _int("WHOZIT_SESSION_TTL_SECONDS", 8 * 3600)),
        min_enroll_quality=_optional_float("WHOZIT_MIN_ENROLL_QUALITY"),
        migrate_v3_path=Path(migrate_v3) if migrate_v3 else None,
        require_crop_key=_bool("WHOZIT_REQUIRE_CROP_KEY", auth_on),
    )


settings = load_settings()
