"""Face detection service powered by Whozit SCRFD."""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
from whozit.detection import SCRFD


@dataclass
class DetectedFace:
    bbox: list[float]
    confidence: float
    landmarks: list[list[float]] | None = None


class FaceDetectorService:
    """Lazy singleton wrapper around SCRFD."""

    def __init__(self, confidence_threshold: float = 0.5) -> None:
        self._lock = threading.Lock()
        self._detector: SCRFD | None = None
        self._default_conf = confidence_threshold

    def _get_detector(self, confidence_threshold: float) -> SCRFD:
        with self._lock:
            if self._detector is None:
                self._detector = SCRFD(confidence_threshold=confidence_threshold)
            else:
                self._detector.confidence_threshold = confidence_threshold
            return self._detector

    def ready(self) -> bool:
        return self._detector is not None

    def warmup(self) -> None:
        """Load model weights at startup."""
        self._get_detector(self._default_conf)

    def detect(
        self,
        image_bgr: np.ndarray,
        confidence_threshold: float = 0.5,
        max_faces: int = 100,
        include_landmarks: bool = False,
    ) -> list[DetectedFace]:
        detector = self._get_detector(confidence_threshold)
        faces = detector.detect(image_bgr)
        faces = sorted(faces, key=lambda f: float(f.confidence), reverse=True)
        faces = faces[: max(0, max_faces)]

        results: list[DetectedFace] = []
        for face in faces:
            bbox = [float(x) for x in np.asarray(face.bbox).reshape(-1)[:4]]
            landmarks = None
            if include_landmarks and face.landmarks is not None:
                landmarks = np.asarray(face.landmarks, dtype=float).reshape(-1, 2).tolist()
            results.append(
                DetectedFace(
                    bbox=bbox,
                    confidence=float(face.confidence),
                    landmarks=landmarks,
                )
            )
        return results


detector_service = FaceDetectorService()
