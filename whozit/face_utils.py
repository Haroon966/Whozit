# Adapted from UniFace (MIT) — see THIRD_PARTY_UNIFACE_LICENSE.txt
"""Face alignment + cosine similarity (OpenCV; no scikit-image)."""

from __future__ import annotations

import cv2
import numpy as np

__all__ = [
    'compute_similarity',
    'face_alignment',
    'reference_alignment',
]


# Standard 5-point facial landmark reference for ArcFace alignment (112x112)
reference_alignment: np.ndarray = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def estimate_norm(
    landmark: np.ndarray,
    image_size: int | tuple[int, int] = 112,
) -> tuple[np.ndarray, np.ndarray]:
    if landmark.shape != (5, 2):
        raise ValueError(
            f'estimate_norm requires 5 alignment landmarks, got shape {landmark.shape}.'
        )

    if isinstance(image_size, tuple):
        size = image_size[0]
    else:
        size = image_size

    if size % 112 != 0 and size % 128 != 0:
        raise ValueError(f'image_size must be a multiple of 112 or 128, got {size}')

    if size % 112 == 0:
        ratio = float(size) / 112.0
        diff_x = 0.0
    else:
        ratio = float(size) / 128.0
        diff_x = 8.0 * ratio

    alignment = reference_alignment * ratio
    alignment[:, 0] += diff_x

    # ponytail: cv2 similarity approx instead of skimage SimilarityTransform; upgrade if match quality drifts
    matrix, _ = cv2.estimateAffinePartial2D(
        landmark.astype(np.float32),
        alignment.astype(np.float32),
        method=cv2.LMEDS,
    )
    if matrix is None:
        raise ValueError('Failed to estimate face alignment transform')

    inverse_matrix = cv2.invertAffineTransform(matrix)
    return matrix, inverse_matrix


def face_alignment(
    image: np.ndarray,
    landmark: np.ndarray,
    image_size: int | tuple[int, int] = 112,
) -> tuple[np.ndarray, np.ndarray]:
    transform_matrix, inverse_transform = estimate_norm(landmark, image_size)

    if isinstance(image_size, int):
        output_size = (image_size, image_size)
    else:
        output_size = image_size

    warped = cv2.warpAffine(image, transform_matrix, output_size, borderValue=0.0)
    return warped, inverse_transform


def compute_similarity(feat1: np.ndarray, feat2: np.ndarray, normalized: bool = False) -> np.float32:
    feat1 = feat1.ravel()
    feat2 = feat2.ravel()
    if normalized:
        return np.float32(np.dot(feat1, feat2))
    return np.float32(np.dot(feat1, feat2) / (np.linalg.norm(feat1) * np.linalg.norm(feat2) + 1e-5))
