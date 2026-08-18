"""ArcFace embed + max-over-samples match with greedy one-to-one assignment."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field

import cv2
import numpy as np
from whozit.face_utils import compute_similarity, face_alignment
from whozit.recognition import ArcFace

from app.config import settings
from app.crop_crypto import MODEL_VERSION
from app.ref_store import GalleryRef, ref_store

DEFAULT_MATCH_THRESHOLD = settings.match_thresh


@dataclass
class Candidate:
    ref_id: str
    name: str
    score: float


@dataclass
class MatchResult:
    ref_id: str | None
    name: str | None
    score: float
    matched: bool
    margin: float | None = None
    candidates: list[Candidate] = field(default_factory=list)


@dataclass
class _GalleryEntry:
    ref_id: str
    name: str
    vectors: list[np.ndarray]


class FaceRecognizerService:
    def __init__(self, match_threshold: float | None = None) -> None:
        self._lock = threading.Lock()
        self._recognizer: ArcFace | None = None
        self.match_threshold = DEFAULT_MATCH_THRESHOLD if match_threshold is None else match_threshold
        self.model_version = MODEL_VERSION
        # ponytail: LRU of per-scope galleries; upgrade → shared cache / mmap
        self._slug_galleries: OrderedDict[str, list[_GalleryEntry]] = OrderedDict()
        self._lru_size = settings.gallery_lru_size

    def _get(self) -> ArcFace:
        with self._lock:
            if self._recognizer is None:
                self._recognizer = ArcFace()
            return self._recognizer

    def ready(self) -> bool:
        return self._recognizer is not None

    def warmup(self) -> None:
        self._get()

    def invalidate_scope(self, scope_key: str) -> None:
        with self._lock:
            self._slug_galleries.pop(scope_key, None)

    def invalidate_all(self) -> None:
        with self._lock:
            self._slug_galleries.clear()

    def aligned_crop_jpeg(self, image_bgr: np.ndarray, landmarks: np.ndarray, quality: int = 90) -> bytes:
        landmarks = np.asarray(landmarks, dtype=np.float32).reshape(5, 2)
        aligned, _ = face_alignment(image_bgr, landmarks, image_size=(112, 112))
        ok, buf = cv2.imencode(".jpg", aligned, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise RuntimeError("failed to encode aligned crop")
        return buf.tobytes()

    def _load_scope_gallery(self, scope_key: str) -> list[_GalleryEntry]:
        with self._lock:
            cached = self._slug_galleries.get(scope_key)
            if cached is not None:
                self._slug_galleries.move_to_end(scope_key)
                return cached
        raw = ref_store.gallery_for_scope(scope_key)
        entries = _gallery_from_raw(raw, self.model_version)
        with self._lock:
            self._slug_galleries[scope_key] = entries
            self._slug_galleries.move_to_end(scope_key)
            while len(self._slug_galleries) > self._lru_size:
                self._slug_galleries.popitem(last=False)
            return self._slug_galleries[scope_key]

    def embed(self, image_bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        landmarks = np.asarray(landmarks, dtype=np.float32).reshape(5, 2)
        return self._get().get_normalized_embedding(image_bgr, landmarks)

    def match_in_scope(
        self,
        embedding: np.ndarray,
        scope_key: str,
        threshold: float | None = None,
    ) -> MatchResult:
        thresh = self.match_threshold if threshold is None else threshold
        gallery = self._load_scope_gallery(scope_key)
        return score_one_face(embedding, gallery, thresh)

    def assign_faces(
        self,
        embeddings: list[np.ndarray],
        scope_key: str,
        threshold: float | None = None,
    ) -> list[MatchResult]:
        thresh = self.match_threshold if threshold is None else threshold
        gallery = self._load_scope_gallery(scope_key)
        return greedy_assign(embeddings, gallery, thresh)


def _gallery_from_raw(raw: list[GalleryRef], live_version: str) -> list[_GalleryEntry]:
    entries: list[_GalleryEntry] = []
    for item in raw:
        vecs = [s.vector for s in item.samples if s.model_version == live_version]
        if not vecs:
            continue
        entries.append(_GalleryEntry(ref_id=item.ref_id, name=item.name, vectors=vecs))
    return entries


def max_sample_score(embedding: np.ndarray, vectors: list[np.ndarray]) -> float:
    best = -1.0
    for vec in vectors:
        score = float(compute_similarity(embedding, vec, normalized=True))
        if score > best:
            best = score
    return best


def score_one_face(
    embedding: np.ndarray,
    gallery: list[_GalleryEntry],
    thresh: float,
    *,
    exclude: set[str] | None = None,
) -> MatchResult:
    ranked = _rank_refs(embedding, gallery, exclude)
    if not ranked:
        return MatchResult(ref_id=None, name=None, score=0.0, matched=False, margin=None, candidates=[])
    best = ranked[0]
    runner = ranked[1].score if len(ranked) > 1 else 0.0
    margin = round(best.score - runner, 4)
    matched = best.score >= thresh
    return MatchResult(
        ref_id=best.ref_id if matched else None,
        name=best.name if matched else None,
        score=round(best.score, 4),
        matched=matched,
        margin=margin if matched else None,
        candidates=ranked[:3],
    )


def _rank_refs(
    embedding: np.ndarray,
    gallery: list[_GalleryEntry],
    exclude: set[str] | None = None,
) -> list[Candidate]:
    ranked: list[Candidate] = []
    for entry in gallery:
        if exclude and entry.ref_id in exclude:
            continue
        score = max_sample_score(embedding, entry.vectors)
        ranked.append(Candidate(ref_id=entry.ref_id, name=entry.name, score=round(score, 4)))
    ranked.sort(key=lambda c: c.score, reverse=True)
    return ranked


def greedy_assign(
    embeddings: list[np.ndarray],
    gallery: list[_GalleryEntry],
    thresh: float,
) -> list[MatchResult]:
    """Sort (face, ref) pairs by score; assign if neither is taken."""
    n = len(embeddings)
    if n == 0:
        return []
    if not gallery:
        return [
            MatchResult(ref_id=None, name=None, score=0.0, matched=False, margin=None, candidates=[])
            for _ in embeddings
        ]

    pairs: list[tuple[float, int, _GalleryEntry]] = []
    per_face: list[list[Candidate]] = []
    for fi, emb in enumerate(embeddings):
        ranked = _rank_refs(emb, gallery, None)
        per_face.append(ranked)
        by_id = {c.ref_id: c.score for c in ranked}
        for entry in gallery:
            pairs.append((by_id[entry.ref_id], fi, entry))
    pairs.sort(key=lambda p: p[0], reverse=True)

    taken_faces: set[int] = set()
    taken_refs: set[str] = set()
    assigned: dict[int, tuple[_GalleryEntry, float]] = {}
    for score, fi, entry in pairs:
        if score < thresh:
            continue
        if fi in taken_faces or entry.ref_id in taken_refs:
            continue
        taken_faces.add(fi)
        taken_refs.add(entry.ref_id)
        assigned[fi] = (entry, score)

    results: list[MatchResult] = []
    for fi in range(n):
        ranked = per_face[fi]
        if fi not in assigned:
            best_score = ranked[0].score if ranked else 0.0
            results.append(
                MatchResult(
                    ref_id=None,
                    name=None,
                    score=best_score,
                    matched=False,
                    margin=None,
                    candidates=ranked[:3],
                )
            )
            continue
        entry, score = assigned[fi]
        runner = 0.0
        for c in ranked:
            if c.ref_id != entry.ref_id:
                runner = c.score
                break
        results.append(
            MatchResult(
                ref_id=entry.ref_id,
                name=entry.name,
                score=round(score, 4),
                matched=True,
                margin=round(score - runner, 4),
                candidates=ranked[:3],
            )
        )
    return results


recognizer_service = FaceRecognizerService()
