"""Gallery mean-embedding cache for match()."""

from __future__ import annotations

import numpy as np

from app.people_store import PeopleStore
from app.recognizer import FaceRecognizerService


def test_gallery_cache_reuses_until_store_changes(tmp_path, monkeypatch):
    path = tmp_path / "people.json"
    path.write_text('{"people": []}', encoding="utf-8")
    store = PeopleStore(path=path)
    monkeypatch.setattr("app.recognizer.people_store", store)

    svc = FaceRecognizerService(match_threshold=0.1)
    emb_a = np.zeros(4, dtype=np.float32)
    emb_a[0] = 1.0
    store.enroll(name="Ali", embedding=emb_a)

    calls = {"n": 0}
    real_list = store.list_people

    def counted_list():
        calls["n"] += 1
        return real_list()

    monkeypatch.setattr(store, "list_people", counted_list)

    q = emb_a.copy()
    r1 = svc.match(q)
    r2 = svc.match(q)
    assert r1.matched and r1.name == "Ali"
    assert r2.matched
    assert calls["n"] == 1

    emb_b = np.zeros(4, dtype=np.float32)
    emb_b[1] = 1.0
    store.enroll(name="Bea", embedding=emb_b)
    # mtime change after write → cache miss
    r3 = svc.match(emb_b)
    assert r3.matched and r3.name == "Bea"
    assert calls["n"] == 2

    svc.invalidate_gallery()
    svc.match(emb_a)
    assert calls["n"] == 3
