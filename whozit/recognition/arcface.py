# Adapted from UniFace (MIT) — see THIRD_PARTY_UNIFACE_LICENSE.txt
from __future__ import annotations

from whozit.constants import ArcFaceWeights
from whozit.model_store import verify_model_weights

from .base import BaseRecognizer, PreprocessConfig

__all__ = ['ArcFace']


class ArcFace(BaseRecognizer):
    """ArcFace face recognition (InsightFace weights via UniFace releases)."""

    def __init__(
        self,
        *,
        model_name: ArcFaceWeights = ArcFaceWeights.MNET,
        preprocessing: PreprocessConfig | None = None,
        providers: list[str] | None = None,
    ) -> None:
        if preprocessing is None:
            preprocessing = PreprocessConfig(input_mean=127.5, input_std=127.5, input_size=(112, 112))
        model_path = verify_model_weights(model_name)
        super().__init__(model_path=model_path, preprocessing=preprocessing, providers=providers)
