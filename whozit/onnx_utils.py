# Adapted from UniFace (MIT) — see THIRD_PARTY_UNIFACE_LICENSE.txt
"""ONNX Runtime session helpers."""

from __future__ import annotations

import functools

try:
    import onnxruntime as ort
except ImportError as e:
    raise ImportError(
        'onnxruntime is not installed. Install with:\n'
        '  pip install onnxruntime          # CPU\n'
        '  pip install onnxruntime-gpu      # NVIDIA GPU\n'
        'Do not install both — they conflict.'
    ) from e

from whozit.log import Logger

__all__ = ['create_onnx_session', 'get_available_providers']


@functools.lru_cache(maxsize=1)
def get_available_providers() -> list[str]:
    available = ort.get_available_providers()
    providers = []

    if 'CoreMLExecutionProvider' in available:
        providers.append('CoreMLExecutionProvider')
        Logger.info('CoreML acceleration enabled (Apple Silicon)')

    if 'CUDAExecutionProvider' in available:
        providers.append('CUDAExecutionProvider')
        Logger.info('CUDA acceleration enabled (NVIDIA GPU)')

    providers.append('CPUExecutionProvider')

    if len(providers) == 1:
        Logger.info('Using CPU execution (no hardware acceleration detected)')

    return providers


def create_onnx_session(
    model_path: str,
    providers: list[str] | None = None,
) -> ort.InferenceSession:
    if providers is None:
        providers = get_available_providers()

    sess_options = ort.SessionOptions()
    sess_options.log_severity_level = 3

    try:
        session = ort.InferenceSession(model_path, sess_options=sess_options, providers=providers)
        active_provider = session.get_providers()[0]
        Logger.debug(f'Session created with provider: {active_provider}')
        return session
    except Exception as e:
        Logger.error(f'Failed to create ONNX session: {e}', exc_info=True)
        raise RuntimeError(f'Failed to initialize ONNX Runtime session: {e}') from e
