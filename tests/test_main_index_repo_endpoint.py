from fastapi.testclient import TestClient

import backend.main as main


def test_index_repo_endpoint_returns_500_on_indexer_failure(monkeypatch, tmp_path):
    # Avoid touching real Qdrant in tests.
    monkeypatch.setattr(main, "delete_by_filter", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "count_points", lambda *args, **kwargs: 0)

    def fail(repo_id: str):
        raise RuntimeError("missing GOOGLE_API_KEY")

    monkeypatch.setattr(main, "index_repo", fail)

    client = TestClient(main.app)
    resp = client.post("/index/repo", json={"repo_path": str(tmp_path)})
    assert resp.status_code == 500
    assert "missing GOOGLE_API_KEY" in resp.text


def test_index_repo_endpoint_returns_429_on_quota(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "delete_by_filter", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "count_points", lambda *args, **kwargs: 0)
    monkeypatch.setattr(main, "get_redis", lambda: None)

    def fail(repo_id: str, index_id: str = None):
        raise RuntimeError("429 Quota exceeded for metric")

    monkeypatch.setattr(main, "index_repo", fail)

    client = TestClient(main.app)
    resp = client.post("/index/repo", json={"repo_path": str(tmp_path)})
    assert resp.status_code == 429
