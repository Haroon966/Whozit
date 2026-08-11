"""Local JSON store for enrolled people + face embeddings."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.config import settings

DEFAULT_STORE_PATH = settings.people_path


@dataclass
class Person:
    id: str
    name: str
    embeddings: list[list[float]]
    created_at: str
    updated_at: str

    def mean_embedding(self) -> np.ndarray:
        arr = np.asarray(self.embeddings, dtype=np.float32)
        mean = arr.mean(axis=0)
        norm = np.linalg.norm(mean)
        return mean / norm if norm > 0 else mean


class PeopleStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_STORE_PATH
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"people": []})

    def _read(self) -> dict:
        with self.path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.path)

    def list_people(self) -> list[Person]:
        with self._lock:
            data = self._read()
        return [self._to_person(p) for p in data.get("people", [])]

    def get(self, person_id: str) -> Person | None:
        for person in self.list_people():
            if person.id == person_id:
                return person
        return None

    def enroll(
        self,
        *,
        name: str,
        embedding: np.ndarray,
        person_id: str | None = None,
    ) -> Person:
        name = name.strip()
        if not name:
            raise ValueError("name is required")
        emb = embedding.astype(np.float32).ravel().tolist()
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            data = self._read()
            people = data.setdefault("people", [])
            target = None
            if person_id:
                for p in people:
                    if p["id"] == person_id:
                        target = p
                        break
                if target is None:
                    raise KeyError(f"person_id not found: {person_id}")
                target["name"] = name
                target["embeddings"].append(emb)
                target["updated_at"] = now
            else:
                # Match existing by exact name (case-insensitive) so re-enroll adds sample.
                for p in people:
                    if p["name"].strip().lower() == name.lower():
                        target = p
                        break
                if target is None:
                    target = {
                        "id": str(uuid.uuid4()),
                        "name": name,
                        "embeddings": [emb],
                        "created_at": now,
                        "updated_at": now,
                    }
                    people.append(target)
                else:
                    target["embeddings"].append(emb)
                    target["updated_at"] = now

            self._write(data)
            return self._to_person(target)

    def delete(self, person_id: str) -> bool:
        with self._lock:
            data = self._read()
            people = data.get("people", [])
            new_people = [p for p in people if p["id"] != person_id]
            if len(new_people) == len(people):
                return False
            data["people"] = new_people
            self._write(data)
            return True

    @staticmethod
    def _to_person(raw: dict) -> Person:
        return Person(
            id=raw["id"],
            name=raw["name"],
            embeddings=raw.get("embeddings") or [],
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
        )


people_store = PeopleStore()
