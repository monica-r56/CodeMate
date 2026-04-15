from fastapi.testclient import TestClient

import backend.main as main


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value


def test_index_repo_does_not_delete_previous_on_failure(monkeypatch, tmp_path):
    deleted = []
    monkeypatch.setattr(main, "delete_by_filter", lambda collection, filters: deleted.append((collection, filters)))
    monkeypatch.setattr(main, "count_points", lambda *args, **kwargs: 0)

    r = FakeRedis()
    repo_id = str(tmp_path)
    r.set(f"pairvoice:index:{repo_id}", "prev123")
    monkeypatch.setattr(main, "get_redis", lambda: r)

    def fail(repo_id: str, index_id: str = None):
        raise RuntimeError("429 Quota exceeded")

    monkeypatch.setattr(main, "index_repo", fail)

    client = TestClient(main.app)
    resp = client.post("/index/repo", json={"repo_path": repo_id})
    assert resp.status_code == 429
    assert deleted == []  # previous index preserved


def test_index_repo_deletes_previous_on_success(monkeypatch, tmp_path):
    deleted = []

    def fake_delete_by_filter(collection, filters):
        deleted.append((collection, filters))

    monkeypatch.setattr(main, "delete_by_filter", fake_delete_by_filter)

    # Return some new chunk count for the new index_id; total docs can be 0.
    def fake_count_points(collection, filters=None):
        if collection == "codebase_chunks" and filters and filters.get("index_id"):
            return 12
        if collection == "documentation":
            return 3
        return 0

    monkeypatch.setattr(main, "count_points", fake_count_points)

    r = FakeRedis()
    repo_id = str(tmp_path)
    r.set(f"pairvoice:index:{repo_id}", "prev123")
    monkeypatch.setattr(main, "get_redis", lambda: r)

    monkeypatch.setattr(main, "index_repo", lambda repo_id, index_id=None: None)

    client = TestClient(main.app)
    resp = client.post("/index/repo", json={"repo_path": repo_id})
    assert resp.status_code == 200

    # Old chunks are deleted after success.
    assert ("codebase_chunks", {"repo_path": repo_id, "index_id": "prev123"}) in deleted
    assert ("documentation", {"repo_path": repo_id, "index_id": "prev123"}) in deleted
    assert r.get(f"pairvoice:index:{repo_id}") != "prev123"
