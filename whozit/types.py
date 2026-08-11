# Adapted from UniFace (MIT) — see THIRD_PARTY_UNIFACE_LICENSE.txt
"""Detection result types for Whozit."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ['Face']


@dataclass(slots=True)
class Face:
    """One detected face: box, score, optional landmarks."""

    bbox: np.ndarray
    confidence: float
    landmarks: np.ndarray
