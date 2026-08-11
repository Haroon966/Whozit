# Adapted from UniFace (MIT) — see THIRD_PARTY_UNIFACE_LICENSE.txt
"""SCRFD model registry for Whozit."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    'DOWNLOAD_CHUNK_SIZE',
    'HASH_CHUNK_SIZE',
    'HF_MIRROR_URL',
    'MODEL_REGISTRY',
    'ModelInfo',
    'ArcFaceWeights',
    'SCRFDWeights',
]


@dataclass(frozen=True, slots=True)
class ModelInfo:
    url: str
    sha256: str


DOWNLOAD_CHUNK_SIZE = 256 * 1024
HASH_CHUNK_SIZE = 1024 * 1024

# Upstream UniFace weight mirror (immutable commit). Weights stay hosted there.
HF_MIRROR_URL = 'https://huggingface.co/yakhyo/uniface-weights/resolve/4c7ed723a20deb7ff154b1ba7d6e73747d954016'


class SCRFDWeights(str, Enum):
    """SCRFD weights trained on WIDER FACE (InsightFace / UniFace releases)."""

    SCRFD_10G_KPS = 'scrfd_10g'
    SCRFD_500M_KPS = 'scrfd_500m'


class ArcFaceWeights(str, Enum):
    """ArcFace weights (InsightFace / UniFace releases)."""

    MNET = 'arcface_mnet'
    RESNET = 'arcface_resnet'


MODEL_REGISTRY: dict[Enum, ModelInfo] = {
    SCRFDWeights.SCRFD_10G_KPS: ModelInfo(
        url='https://github.com/yakhyo/uniface/releases/download/weights/scrfd_10g_kps.onnx',
        sha256='5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91',
    ),
    SCRFDWeights.SCRFD_500M_KPS: ModelInfo(
        url='https://github.com/yakhyo/uniface/releases/download/weights/scrfd_500m_kps.onnx',
        sha256='5e4447f50245bbd7966bd6c0fa52938c61474a04ec7def48753668a9d8b4ea3a',
    ),
    ArcFaceWeights.MNET: ModelInfo(
        url='https://github.com/yakhyo/uniface/releases/download/weights/w600k_mbf.onnx',
        sha256='9cc6e4a75f0e2bf0b1aed94578f144d15175f357bdc05e815e5c4a02b319eb4f',
    ),
    ArcFaceWeights.RESNET: ModelInfo(
        url='https://github.com/yakhyo/uniface/releases/download/weights/w600k_r50.onnx',
        sha256='4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43',
    ),
}
