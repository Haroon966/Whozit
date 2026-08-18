"""Re-embed stored crops after a model_version bump."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.crop_crypto import MODEL_VERSION, decrypt_crop
from app.recognizer import FaceRecognizerService
from app.ref_store import RefStore


@dataclass
class ReembedResult:
    updated: int
    skipped: int
    failed: int
    details: list[str]


def reembed_all(
    store: RefStore,
    recognizer: FaceRecognizerService,
    *,
    scope_key: str | None = None,
    force: bool = False,
) -> ReembedResult:
    target_version = MODEL_VERSION
    rows = store.iter_samples_for_reembed(scope_key)
    updated = skipped = failed = 0
    details: list[str] = []
    scopes_to_invalidate: set[str] = set()

    for row in rows:
        sid = int(row["id"])
        sk = row["scope_key"]
        if not force and row["model_version"] == target_version:
            skipped += 1
            continue
        try:
            jpeg = decrypt_crop(store._aes_key, row["crop_enc"])  # noqa: SLF001
            arr = np.frombuffer(jpeg, dtype=np.uint8)
            image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if image is None or image.size == 0:
                failed += 1
                details.append(f"sample {sid}: undecodable crop (re-enroll photo)")
                continue
            emb = recognizer._get().get_normalized_embedding(image)  # noqa: SLF001
            store.update_sample_vector(sid, emb, target_version)
            updated += 1
            scopes_to_invalidate.add(sk)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            details.append(f"sample {sid}: {exc}")

    for sk in scopes_to_invalidate:
        recognizer.invalidate_scope(sk)
    if updated:
        recognizer.invalidate_all()

    return ReembedResult(updated=updated, skipped=skipped, failed=failed, details=details)
