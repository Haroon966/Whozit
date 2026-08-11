# Adapted from UniFace (MIT) — see THIRD_PARTY_UNIFACE_LICENSE.txt
"""Download and verify SCRFD ONNX weights."""

from __future__ import annotations

from enum import Enum
import hashlib
import os
import tempfile
import time

import requests
from tqdm import tqdm

import whozit.constants as const
from whozit.log import Logger

__all__ = ['get_cache_dir', 'set_cache_dir', 'verify_model_weights']

_DEFAULT_CACHE_DIR = '~/.whozit/models'
_ENV_KEY = 'WHOZIT_CACHE_DIR'


def get_cache_dir() -> str:
    return os.path.expanduser(os.environ.get(_ENV_KEY, _DEFAULT_CACHE_DIR))


def set_cache_dir(path: str) -> None:
    os.environ[_ENV_KEY] = path
    Logger.info(f'Cache directory set to: {path}')


def _mirror_url(model_name: Enum, url: str) -> str:
    return f'{const.HF_MIRROR_URL}/{model_name.value}{os.path.splitext(url)[1]}'


def verify_model_weights(
    model_name: Enum,
    root: str | None = None,
    timeout: int = 60,
    max_retries: int = 3,
) -> str:
    root = os.path.expanduser(root) if root is not None else get_cache_dir()
    os.makedirs(root, exist_ok=True)

    model_info = const.MODEL_REGISTRY.get(model_name)
    if not model_info:
        Logger.error(f"No entry found in MODEL_REGISTRY for model '{model_name}'")
        raise ValueError(f"Unknown model identifier: '{model_name}'")

    url = model_info.url
    expected_hash = model_info.sha256

    file_ext = os.path.splitext(url)[1]
    model_path = os.path.normpath(os.path.join(root, f'{model_name.value}{file_ext}'))

    if os.path.exists(model_path) and expected_hash and not verify_file_hash(model_path, expected_hash):
        Logger.warning(f"Cached weights for '{model_name.value}' are corrupted; re-downloading.")
        os.remove(model_path)

    # Reuse prior FaceAttendance / UniFace caches if Whozit cache is empty (same SHA).
    if not os.path.exists(model_path):
        import shutil

        for legacy_root, label in (
            ('~/.faceattendance/models', 'FaceAttendance'),
            ('~/.uniface/models', 'UniFace'),
        ):
            legacy_path = os.path.normpath(
                os.path.join(os.path.expanduser(legacy_root), f'{model_name.value}{file_ext}')
            )
            if os.path.exists(legacy_path) and (not expected_hash or verify_file_hash(legacy_path, expected_hash)):
                shutil.copy2(legacy_path, model_path)
                Logger.info(f"Copied '{model_name.value}' from legacy {label} cache to {model_path}")
                break

    if not os.path.exists(model_path):
        sources = (('GH Releases', url), ('HF Mirror', _mirror_url(model_name, url)))
        last_error: Exception | None = None

        for index, (origin, source) in enumerate(sources):
            Logger.info(f"Downloading model '{model_name.value}' from {origin}: {source}")
            try:
                download_file(source, model_path, expected_hash=expected_hash, timeout=timeout, max_retries=max_retries)
            except ConnectionError as e:
                last_error = e
                if index + 1 < len(sources):
                    Logger.warning(f"{origin} failed for '{model_name.value}' ({e}); trying {sources[index + 1][0]}.")
                continue

            if index:
                Logger.warning(f"Recovered '{model_name.value}' from {origin}.")
            Logger.info(f"Successfully downloaded '{model_name.value}' to {model_path}")
            return model_path

        tried = ' and '.join(origin for origin, _ in sources)
        Logger.error(f"Failed to download '{model_name.value}' from {tried}: {last_error}")
        raise ConnectionError(
            f"Download failed for '{model_name.value}' from {tried}, {max_retries} attempts each"
        ) from last_error

    return model_path


def download_file(
    url: str,
    dest_path: str,
    expected_hash: str | None = None,
    timeout: int = 60,
    max_retries: int = 3,
) -> None:
    last_error = None
    dest_dir = os.path.dirname(dest_path) or '.'
    for attempt in range(max_retries):
        tmp_path = None
        try:
            response = requests.get(url, stream=True, timeout=timeout)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))

            fd, tmp_path = tempfile.mkstemp(dir=dest_dir, suffix='.tmp')
            with (
                os.fdopen(fd, 'wb') as file,
                tqdm(
                    total=total_size,
                    desc=f'Attempt {attempt + 1}/{max_retries}',
                    unit='B',
                    unit_scale=True,
                    unit_divisor=1024,
                ) as progress,
            ):
                for chunk in response.iter_content(chunk_size=const.DOWNLOAD_CHUNK_SIZE):
                    if chunk:
                        file.write(chunk)
                        progress.update(len(chunk))

            if expected_hash and not verify_file_hash(tmp_path, expected_hash):
                raise ValueError('SHA-256 hash mismatch on downloaded file')

            os.replace(tmp_path, dest_path)
            return
        except (OSError, requests.RequestException, ValueError) as e:
            last_error = e
            if attempt < max_retries - 1:
                Logger.info(f'Attempt {attempt + 1}/{max_retries} failed for {url}: {e}. Retrying...')
                time.sleep(2**attempt)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)

    raise ConnectionError(f'Failed to download file from {url}. Error: {last_error}')


def verify_file_hash(file_path: str, expected_hash: str) -> bool:
    file_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(const.HASH_CHUNK_SIZE), b''):
            file_hash.update(chunk)
    actual_hash = file_hash.hexdigest()
    if actual_hash != expected_hash:
        Logger.warning(f'Expected hash: {expected_hash}, but got: {actual_hash}')
    return actual_hash == expected_hash
