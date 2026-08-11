"""People store enroll/match basics."""

from __future__ import annotations

import numpy as np

from app.people_store import PeopleStore
from app.recognizer import FaceRecognizerService


def test_enroll_and_match(tmp_path):
    store = PeopleStore(path=tmp_path / "people.json")
    emb_a = np.zeros(512, dtype=np.float32)
    emb_a[0] = 1.0
    emb_b = np.zeros(512, dtype=np.float32)
    emb_b[1] = 1.0

    person = store.enroll(name="Ali", embedding=emb_a)
    assert person.name == "Ali"
    assert len(person.embeddings) == 1

    svc = FaceRecognizerService(match_threshold=0.5)
    # monkeypatch list via replacing module store used inside matcher — call match with injected people
    from whozit.face_utils import compute_similarity

    people = store.list_people()
    score = float(compute_similarity(emb_a, people[0].mean_embedding(), normalized=True))
    assert score > 0.99

    # orthogonal vector should be low
    score_b = float(compute_similarity(emb_b, people[0].mean_embedding(), normalized=True))
    assert score_b < 0.1

    # re-enroll same name adds sample
    store.enroll(name="Ali", embedding=emb_a)
    assert len(store.get(person.id).embeddings) == 2
