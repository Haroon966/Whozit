"""ArcFace embed + match against enrolled people."""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
from whozit.face_utils import compute_similarity
from whozit.recognition import ArcFace

from app.config import settings
from app.people_store import people_store
from app.scoped_store import scoped_store

DEFAULT_MATCH_THRESHOLD = settings.match_thresh


@dataclass
class MatchResult:
    person_id: str | None
    name: str | None
    score: float
    matched: bool


@dataclass
class _GalleryEntry:
    person_id: str
    name: str
    mean: np.ndarray


class FaceRecognizerService:
    def __init__(self, match_threshold: float | None = None) -> None:
        self._lock = threading.Lock()
        self._recognizer: ArcFace | None = None
        self.match_threshold = DEFAULT_MATCH_THRESHOLD if match_threshold is None else match_threshold
        # ponytail: in-memory mean cache keyed by people.json mtime; upgrade → invalidate hooks or vector index
        self._gallery: list[_GalleryEntry] | None = None
        self._gallery_mtime: float | None = None
        # ponytail: per-slug cache unbounded; upgrade → LRU when many classes
        self._slug_galleries: dict[str, list[_GalleryEntry]] = {}

    def _get(self) -> ArcFace:
        with self._lock:
            if self._recognizer is None:
                self._recognizer = ArcFace()
            return self._recognizer

    def ready(self) -> bool:
        return self._recognizer is not None

    def warmup(self) -> None:
        self._get()

    def invalidate_gallery(self) -> None:
        with self._lock:
            self._gallery = None
            self._gallery_mtime = None

    def invalidate_slug(self, class_slug: str) -> None:
        with self._lock:
            self._slug_galleries.pop(class_slug, None)

    def _load_gallery(self) -> list[_GalleryEntry]:
        path = people_store.path
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = -1.0
        with self._lock:
            if self._gallery is not None and self._gallery_mtime == mtime:
                return self._gallery
        people = people_store.list_people()
        entries: list[_GalleryEntry] = []
        for person in people:
            if not person.embeddings:
                continue
            entries.append(
                _GalleryEntry(
                    person_id=person.id,
                    name=person.name,
                    mean=person.mean_embedding(),
                )
            )
        with self._lock:
            self._gallery = entries
            self._gallery_mtime = mtime
            return self._gallery

    def _load_slug_gallery(self, class_slug: str) -> list[_GalleryEntry]:
        with self._lock:
            cached = self._slug_galleries.get(class_slug)
            if cached is not None:
                return cached
        raw = scoped_store.gallery_for_slug(class_slug)
        entries = [
            _GalleryEntry(person_id=e.person_id, name=e.name, mean=e.mean) for e in raw
        ]
        with self._lock:
            self._slug_galleries[class_slug] = entries
            return self._slug_galleries[class_slug]

    def embed(self, image_bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        landmarks = np.asarray(landmarks, dtype=np.float32).reshape(5, 2)
        return self._get().get_normalized_embedding(image_bgr, landmarks)

    def match(self, embedding: np.ndarray, threshold: float | None = None) -> MatchResult:
        thresh = self.match_threshold if threshold is None else threshold
        gallery = self._load_gallery()
        return self._match_gallery(embedding, gallery, thresh)

    def match_in_slug(
        self,
        embedding: np.ndarray,
        class_slug: str,
        threshold: float | None = None,
    ) -> MatchResult:
        thresh = self.match_threshold if threshold is None else threshold
        gallery = self._load_slug_gallery(class_slug)
        return self._match_gallery(embedding, gallery, thresh)

    @staticmethod
    def _match_gallery(
        embedding: np.ndarray,
        gallery: list[_GalleryEntry],
        thresh: float,
    ) -> MatchResult:
        if not gallery:
            return MatchResult(person_id=None, name=None, score=0.0, matched=False)

        best: _GalleryEntry | None = None
        best_score = -1.0
        for entry in gallery:
            score = float(compute_similarity(embedding, entry.mean, normalized=True))
            if score > best_score:
                best_score = score
                best = entry

        if best is None or best_score < thresh:
            return MatchResult(person_id=None, name=None, score=round(best_score, 4), matched=False)

        return MatchResult(
            person_id=best.person_id,
            name=best.name,
            score=round(best_score, 4),
            matched=True,
        )


recognizer_service = FaceRecognizerService()
