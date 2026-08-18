"""AES-GCM encryption for enrolment crops. Destroy WHOZIT_CROP_KEY to crypto-shred."""

from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_DEV_KEY_MATERIAL = b"whozit-dev-insecure-crop-key"

MODEL_VERSION = "arcface_mnet"


def crop_key_bytes(secret: str | None) -> bytes:
    material = secret.encode("utf-8") if secret else _DEV_KEY_MATERIAL
    return hashlib.sha256(material).digest()


def encrypt_crop(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def decrypt_crop(key: bytes, blob: bytes) -> bytes:
    if len(blob) < 13:
        raise ValueError("crop ciphertext too short")
    nonce, ct = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ct, None)
