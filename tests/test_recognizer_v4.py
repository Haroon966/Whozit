"""Recognizer: max-over-samples, margin, greedy one-to-one."""

from __future__ import annotations

import numpy as np

from app.recognizer import (
    FaceRecognizerService,
    _GalleryEntry,
    greedy_assign,
    max_sample_score,
    score_one_face,
)


def test_max_sample_beats_mean():
    emb = np.zeros(8, dtype=np.float32)
    emb[0] = 1.0
    good = emb.copy()
    bad = np.zeros(8, dtype=np.float32)
    bad[1] = 1.0
    mean = (good + bad) / 2
    mean /= np.linalg.norm(mean)
    assert max_sample_score(emb, [good, bad]) > float(np.dot(emb, mean))


def test_margin_when_two_clear():
    emb = np.zeros(4, dtype=np.float32)
    emb[0] = 1.0
    gallery = [
        _GalleryEntry(ref_id="a", name="A", vectors=[emb]),
        _GalleryEntry(
            ref_id="b",
            name="B",
            vectors=[np.array([0.9, 0.1, 0, 0], dtype=np.float32)],
        ),
    ]
    result = score_one_face(emb, gallery, thresh=0.5)
    assert result.matched
    assert result.margin is not None
    assert result.margin >= 0


def test_greedy_one_to_one_two_faces():
    emb_a = np.zeros(4, dtype=np.float32)
    emb_a[0] = 1.0
    emb_b = np.zeros(4, dtype=np.float32)
    emb_b[1] = 1.0
    gallery = [
        _GalleryEntry(ref_id="a", name="A", vectors=[emb_a]),
        _GalleryEntry(ref_id="b", name="B", vectors=[emb_b]),
    ]
    results = greedy_assign([emb_a, emb_b], gallery, thresh=0.5)
    assert len(results) == 2
    assert results[0].ref_id == "a"
    assert results[1].ref_id == "b"


def test_scope_cache_invalidate(tmp_path, monkeypatch):
    from app.ref_store import RefStore

    store = RefStore(path=tmp_path / "whozit.db")
    monkeypatch.setattr("app.recognizer.ref_store", store)
    emb = np.zeros(8, dtype=np.float32)
    emb[0] = 1.0
    store.enroll(
        name="Ali",
        scope_key="pk/c1",
        embedding=emb,
        crop_jpeg=b"\xff\xd8\xff\xd9",
        quality=0.9,
        source_request_id="r1",
        ref_id="a1",
    )
    svc = FaceRecognizerService(match_threshold=0.5)
    r1 = svc.match_in_scope(emb, "pk/c1")
    assert r1.matched and r1.name == "Ali"
    svc.invalidate_scope("pk/c1")
    r2 = svc.match_in_scope(emb, "pk/c1")
    assert r2.matched
