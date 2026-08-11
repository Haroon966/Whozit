# SCRFD + ArcFace adapted from UniFace (MIT) — see THIRD_PARTY_UNIFACE_LICENSE.txt
"""Whozit vision core: face detection + recognition."""

from __future__ import annotations

__version__ = '0.2.0'

from whozit.detection import SCRFD
from whozit.face_utils import compute_similarity
from whozit.log import Logger, enable_logging
from whozit.model_store import get_cache_dir, set_cache_dir, verify_model_weights
from whozit.recognition import ArcFace
from whozit.types import Face

__all__ = [
    'ArcFace',
    'Face',
    'Logger',
    'SCRFD',
    '__version__',
    'compute_similarity',
    'enable_logging',
    'get_cache_dir',
    'set_cache_dir',
    'verify_model_weights',
]
