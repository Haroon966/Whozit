"""Smoke checks for crop / annotate helpers."""

from __future__ import annotations

import numpy as np

from app.image_utils import draw_face_boxes, encode_image_base64


def test_draw_face_boxes_marks_pixels() -> None:
    img = np.zeros((100, 120, 3), dtype=np.uint8)
    boxed = draw_face_boxes(img, [[10.0, 20.0, 40.0, 50.0]])
    assert boxed is not img
    # Top-left corner of rect should be painted (BGR accent).
    assert tuple(int(v) for v in boxed[20, 10]) == (76, 107, 15)
    assert tuple(int(v) for v in boxed[0, 0]) == (0, 0, 0)


def test_encode_annotated_roundtrip() -> None:
    img = np.full((32, 32, 3), 40, dtype=np.uint8)
    boxed = draw_face_boxes(img, [[5, 5, 25, 25]])
    b64, mime = encode_image_base64(boxed, crop_format="jpeg", jpeg_quality=90)
    assert mime == "image/jpeg"
    assert len(b64) > 20
