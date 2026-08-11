"""Image decode / crop helpers."""

from __future__ import annotations

import base64
import io
import re
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageOps

CropFormat = Literal["jpeg", "png"]

_DATA_URL_RE = re.compile(r"^data:image/[^;]+;base64,", re.IGNORECASE)


def _pil_to_bgr(pil_image: Image.Image) -> np.ndarray:
    """Convert a Pillow image to OpenCV BGR uint8."""
    if pil_image.mode == "RGBA":
        bg = Image.new("RGB", pil_image.size, (255, 255, 255))
        bg.paste(pil_image, mask=pil_image.split()[3])
        pil_image = bg
    elif pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")
    rgb = np.asarray(pil_image)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def decode_image_bytes(data: bytes) -> np.ndarray:
    """Decode image bytes to BGR numpy array, auto-rotating via EXIF orientation.

    Phone cameras often store sideways pixels with an Orientation EXIF tag.
    OpenCV ignores that tag; Pillow's exif_transpose applies it so detection
    runs on an upright image.
    """
    if not data:
        raise ValueError("Empty image payload")

    try:
        with Image.open(io.BytesIO(data)) as pil_image:
            pil_image.load()
            upright = ImageOps.exif_transpose(pil_image)
            return _pil_to_bgr(upright)
    except Exception:
        # Fall back to OpenCV for uncommon formats Pillow cannot open.
        arr = np.frombuffer(data, dtype=np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Could not decode image bytes") from None
        return image


def decode_image_base64(image_base64: str) -> np.ndarray:
    payload = image_base64.strip()
    payload = _DATA_URL_RE.sub("", payload)
    try:
        raw = base64.b64decode(payload, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Invalid base64 image data") from exc
    return decode_image_bytes(raw)


def _clamp_box(left: float, top: float, right: float, bottom: float, w: int, h: int) -> tuple[int, int, int, int]:
    left_i = int(np.floor(left))
    top_i = int(np.floor(top))
    right_i = int(np.ceil(right))
    bottom_i = int(np.ceil(bottom))

    left_i = max(0, min(left_i, w - 1))
    top_i = max(0, min(top_i, h - 1))
    right_i = max(left_i + 1, min(right_i, w))
    bottom_i = max(top_i + 1, min(bottom_i, h))
    return left_i, top_i, right_i, bottom_i


def crop_face(
    image_bgr: np.ndarray,
    bbox: list[float],
    padding: float = 0.2,
    square: bool = True,
) -> np.ndarray:
    """Crop face with padding. When square=True, expand to a 1:1 head crop."""
    h, w = image_bgr.shape[:2]
    x1, y1, x2, y2 = bbox
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0

    if square:
        side = max(bw, bh) * (1.0 + 2.0 * padding)
        half = side / 2.0
        left = cx - half
        top = cy - half
        right = cx + half
        bottom = cy + half

        # Shift square into frame when near borders (keep size when possible).
        if right - left > w:
            left, right = 0.0, float(w)
        else:
            if left < 0:
                right -= left
                left = 0.0
            if right > w:
                left -= right - w
                right = float(w)
        if bottom - top > h:
            top, bottom = 0.0, float(h)
        else:
            if top < 0:
                bottom -= top
                top = 0.0
            if bottom > h:
                top -= bottom - h
                bottom = float(h)

        left_i, top_i, right_i, bottom_i = _clamp_box(left, top, right, bottom, w, h)
        crop = image_bgr[top_i:bottom_i, left_i:right_i].copy()

        # Pad with edge color if clamp made it non-square (corner cases).
        ch, cw = crop.shape[:2]
        side_px = max(ch, cw, 1)
        if ch != side_px or cw != side_px:
            canvas = np.zeros((side_px, side_px, 3), dtype=image_bgr.dtype)
            canvas[:] = crop.mean(axis=(0, 1), dtype=np.float64).astype(image_bgr.dtype)
            y0 = (side_px - ch) // 2
            x0 = (side_px - cw) // 2
            canvas[y0 : y0 + ch, x0 : x0 + cw] = crop
            crop = canvas
        return crop

    pad_x = bw * padding
    pad_y = bh * padding
    left_i, top_i, right_i, bottom_i = _clamp_box(
        x1 - pad_x, y1 - pad_y, x2 + pad_x, y2 + pad_y, w, h
    )
    return image_bgr[top_i:bottom_i, left_i:right_i].copy()


def draw_face_boxes(
    image_bgr: np.ndarray,
    bboxes: list[list[float]],
    *,
    labels: list[str] | None = None,
    color_bgr: tuple[int, int, int] = (76, 107, 15),
) -> np.ndarray:
    """Copy image and draw detection rectangles (optional name labels)."""
    out = image_bgr.copy()
    h, w = out.shape[:2]
    thickness = max(2, int(round(min(w, h) / 400)))
    font_scale = max(0.4, min(w, h) / 900)
    for idx, bbox in enumerate(bboxes):
        if len(bbox) < 4:
            continue
        x1, y1, x2, y2 = (int(round(v)) for v in bbox[:4])
        x1 = max(0, min(x1, w - 1))
        y1 = max(0, min(y1, h - 1))
        x2 = max(x1 + 1, min(x2, w))
        y2 = max(y1 + 1, min(y2, h))
        cv2.rectangle(out, (x1, y1), (x2, y2), color_bgr, thickness)
        if labels and idx < len(labels) and labels[idx]:
            label = str(labels[idx])
            (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, max(1, thickness - 1))
            ty = max(0, y1 - 4)
            cv2.rectangle(out, (x1, ty - th - baseline - 2), (x1 + tw + 4, ty + 2), color_bgr, -1)
            cv2.putText(
                out,
                label,
                (x1 + 2, ty - baseline),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                (255, 255, 255),
                max(1, thickness - 1),
                cv2.LINE_AA,
            )
    return out


def encode_image_base64(
    image_bgr: np.ndarray,
    crop_format: CropFormat = "jpeg",
    jpeg_quality: int = 90,
) -> tuple[str, str]:
    """Return (raw_base64, mime_type)."""
    if crop_format == "png":
        ok, buf = cv2.imencode(".png", image_bgr)
        mime = "image/png"
    else:
        quality = int(np.clip(jpeg_quality, 10, 100))
        ok, buf = cv2.imencode(".jpg", image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        mime = "image/jpeg"
    if not ok:
        raise RuntimeError("Failed to encode image")
    return base64.b64encode(buf.tobytes()).decode("ascii"), mime
