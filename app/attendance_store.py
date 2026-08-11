"""Local JSON store for attendance events."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

DEFAULT_STORE_PATH = settings.attendance_path


@dataclass
class AttendanceEvent:
    id: str
    timestamp: str
    person_id: str
    name: str
    matched: bool
    match_score: float
    source_request_id: str
    face_id: int | None = None


class AttendanceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_STORE_PATH
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"events": []})

    def _read(self) -> dict:
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.path)

    def count(self) -> int:
        with self._lock:
            return len(self._read().get("events", []))

    def list_events(self, limit: int = 100) -> list[AttendanceEvent]:
        with self._lock:
            events = self._read().get("events", [])
        events = list(reversed(events))  # newest first
        if limit > 0:
            events = events[:limit]
        return [self._to_event(e) for e in events]

    def record(
        self,
        *,
        source_request_id: str,
        faces: list[dict],
    ) -> list[AttendanceEvent]:
        """Persist one event per matched person_id (first face wins within request)."""
        now = datetime.now(timezone.utc).isoformat()
        seen: set[str] = set()
        to_add: list[dict] = []
        for face in faces:
            if not face.get("matched"):
                continue
            person_id = face.get("person_id")
            name = face.get("name")
            if not person_id or not name:
                continue
            if person_id in seen:
                continue
            seen.add(person_id)
            to_add.append(
                {
                    "id": str(uuid.uuid4()),
                    "timestamp": now,
                    "person_id": person_id,
                    "name": name,
                    "matched": True,
                    "match_score": float(face.get("match_score") or 0.0),
                    "source_request_id": source_request_id,
                    "face_id": face.get("face_id"),
                }
            )

        if not to_add:
            return []

        with self._lock:
            data = self._read()
            events = data.setdefault("events", [])
            events.extend(to_add)
            self._write(data)

        return [self._to_event(e) for e in to_add]

    @staticmethod
    def _to_event(raw: dict) -> AttendanceEvent:
        return AttendanceEvent(
            id=raw["id"],
            timestamp=raw["timestamp"],
            person_id=raw["person_id"],
            name=raw["name"],
            matched=bool(raw.get("matched", True)),
            match_score=float(raw.get("match_score") or 0.0),
            source_request_id=raw.get("source_request_id", ""),
            face_id=raw.get("face_id"),
        )


attendance_store = AttendanceStore()
