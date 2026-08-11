# Adapted from UniFace (MIT) — see THIRD_PARTY_UNIFACE_LICENSE.txt
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

import numpy as np

from whozit.types import Face

__all__ = ['BaseDetector']


class BaseDetector(ABC):
    supports_landmarks: bool = False
    supports_alignment: bool = False

    def __init__(self, **kwargs: Any) -> None:
        self.config: dict[str, Any] = kwargs

    @abstractmethod
    def detect(self, image: np.ndarray, **kwargs: Any) -> list[Face]:
        ...

    @abstractmethod
    def preprocess(self, image: np.ndarray) -> np.ndarray:
        ...

    @abstractmethod
    def postprocess(self, outputs: Any, **kwargs: Any) -> Any:
        ...

    def __call__(self, image: np.ndarray, **kwargs: Any) -> list[Face]:
        return self.detect(image, **kwargs)

    def _select_top_detections(
        self,
        detections: np.ndarray,
        landmarks: np.ndarray,
        max_num: int,
        original_shape: tuple[int, int],
        metric: Literal['default', 'max'] = 'max',
        center_weight: float = 2.0,
    ) -> tuple[np.ndarray, np.ndarray]:
        if max_num <= 0 or detections.shape[0] <= max_num:
            return detections, landmarks

        area = (detections[:, 2] - detections[:, 0]) * (detections[:, 3] - detections[:, 1])

        center_y, center_x = original_shape[0] // 2, original_shape[1] // 2
        offsets = np.vstack(
            [
                (detections[:, 0] + detections[:, 2]) / 2 - center_x,
                (detections[:, 1] + detections[:, 3]) / 2 - center_y,
            ]
        )
        offset_dist_squared = np.sum(np.power(offsets, 2.0), axis=0)

        if metric == 'max':
            scores = area
        else:
            scores = area - offset_dist_squared * center_weight

        top_indices = np.argsort(scores)[::-1][:max_num]
        return detections[top_indices], landmarks[top_indices]

    @staticmethod
    def _detections_to_faces(detections: np.ndarray, landmarks: np.ndarray) -> list[Face]:
        faces = []
        for i in range(detections.shape[0]):
            faces.append(
                Face(
                    bbox=detections[i, :4],
                    confidence=float(detections[i, 4]),
                    landmarks=landmarks[i],
                )
            )
        return faces
