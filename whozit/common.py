# Adapted from UniFace (MIT) — see THIRD_PARTY_UNIFACE_LICENSE.txt
"""Image helpers used by SCRFD."""

from __future__ import annotations

import cv2
import numpy as np

__all__ = [
    'distance2bbox',
    'distance2kps',
    'non_max_suppression',
    'resize_image',
    'validate_image',
]


def validate_image(image: np.ndarray) -> None:
    if not isinstance(image, np.ndarray) or image.size == 0:
        raise ValueError('Input image must be a non-empty numpy array.')
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f'Expected a BGR image of shape (H, W, 3), got {image.shape}. Convert with cv2.cvtColor.')
    if image.dtype != np.uint8:
        raise ValueError(f'Expected dtype uint8, got {image.dtype}. Scale to [0, 255] and cast with .astype(np.uint8).')


def resize_image(
    frame: np.ndarray,
    target_shape: tuple[int, int] = (640, 640),
) -> tuple[np.ndarray, float]:
    validate_image(frame)
    width, height = target_shape

    im_ratio = float(frame.shape[0]) / frame.shape[1]
    model_ratio = height / width
    if im_ratio > model_ratio:
        new_height = height
        new_width = int(new_height / im_ratio)
    else:
        new_width = width
        new_height = int(new_width * im_ratio)

    resize_factor = float(new_height) / frame.shape[0]
    resized_frame = cv2.resize(frame, (new_width, new_height))

    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:new_height, :new_width, :] = resized_frame

    return image, resize_factor


def non_max_suppression(dets: np.ndarray, threshold: float) -> list[int]:
    x1 = dets[:, 0]
    y1 = dets[:, 1]
    x2 = dets[:, 2]
    y2 = dets[:, 3]
    scores = dets[:, 4]

    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter)

        inds = np.where(ovr <= threshold)[0]
        order = order[inds + 1]

    return keep


def distance2bbox(
    points: np.ndarray,
    distance: np.ndarray,
    max_shape: tuple[int, int] | None = None,
) -> np.ndarray:
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]

    if max_shape is not None:
        x1 = np.clip(x1, 0, max_shape[1])
        y1 = np.clip(y1, 0, max_shape[0])
        x2 = np.clip(x2, 0, max_shape[1])
        y2 = np.clip(y2, 0, max_shape[0])
    else:
        x1 = np.maximum(x1, 0)
        y1 = np.maximum(y1, 0)
        x2 = np.maximum(x2, 0)
        y2 = np.maximum(y2, 0)

    return np.stack([x1, y1, x2, y2], axis=-1)


def distance2kps(
    points: np.ndarray,
    distance: np.ndarray,
    max_shape: tuple[int, int] | None = None,
) -> np.ndarray:
    preds = []
    for i in range(0, distance.shape[1], 2):
        px = points[:, i % 2] + distance[:, i]
        py = points[:, i % 2 + 1] + distance[:, i + 1]
        if max_shape is not None:
            px = np.clip(px, 0, max_shape[1])
            py = np.clip(py, 0, max_shape[0])
        preds.append(px)
        preds.append(py)
    return np.stack(preds, axis=-1)
