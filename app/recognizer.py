"""ArcFace embed + match against enrolled people."""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
from whozit.face_utils import compute_similarity
from whozit.recognition import ArcFace

from app.config import settings
from app.people_store import Person, people_store

DEFAULT_MATCH_THRESHOLD = settings.match_thresh


@dataclass
class MatchResult:
    person_id: str | None
    name: str | None
    score: float
    matched: bool


class FaceRecognizerService:
    def __init__(self, match_threshold: float | None = None) -> None:
        self._lock = threading.Lock()
        self._recognizer: ArcFace | None = None
        self.match_threshold = DEFAULT_MATCH_THRESHOLD if match_threshold is None else match_threshold

    def _get(self) -> ArcFace:
        with self._lock:
            if self._recognizer is None:
                self._recognizer = ArcFace()
            return self._recognizer

    def ready(self) -> bool:
        return self._recognizer is not None

    def warmup(self) -> None:
        self._get()

    def embed(self, image_bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        landmarks = np.asarray(landmarks, dtype=np.float32).reshape(5, 2)
        return self._get().get_normalized_embedding(image_bgr, landmarks)

    def match(self, embedding: np.ndarray, threshold: float | None = None) -> MatchResult:
        thresh = self.match_threshold if threshold is None else threshold
        people = people_store.list_people()
        if not people:
            return MatchResult(person_id=None, name=None, score=0.0, matched=False)

        best: Person | None = None
        best_score = -1.0
        for person in people:
            if not person.embeddings:
                continue
            ref = person.mean_embedding()
            score = float(compute_similarity(embedding, ref, normalized=True))
            if score > best_score:
                best_score = score
                best = person

        if best is None or best_score < thresh:
            return MatchResult(person_id=None, name=None, score=round(best_score, 4), matched=False)

        return MatchResult(
            person_id=best.id,
            name=best.name,
            score=round(best_score, 4),
            matched=True,
        )


recognizer_service = FaceRecognizerService()
