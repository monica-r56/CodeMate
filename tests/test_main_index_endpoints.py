from fastapi.testclient import TestClient

import backend.main as main


def test_index_document_scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "ensure_collections", lambda: None)

    called = {"scoped": False}

    def fake_index_file_scoped(file_path, repo_path, source, repo_name=None):
        called["scoped"] = True
        assert repo_path == str(tmp_path)
        assert source == "upload:note.txt"
        return 1

    monkeypatch.setattr(main, "index_file_scoped", fake_index_file_scoped)
    monkeypatch.setattr(main, "index_file", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unscoped called")))

    client = TestClient(main.app)
    resp = client.post(
        "/index/document",
        files={"file": ("note.txt", b"hello", "text/plain")},
        data={"repo_path": str(tmp_path)},
    )
    assert resp.status_code == 200
    assert called["scoped"] is True


def test_index_url_scoped(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "ensure_collections", lambda: None)

    called = {"scoped": False}

    def fake_index_url_scoped(url, repo_path, repo_name=None):
        called["scoped"] = True
        assert url == "https://example.com"
        assert repo_path == str(tmp_path)
        return 1

    monkeypatch.setattr(main, "index_url_scoped", fake_index_url_scoped)
    monkeypatch.setattr(main, "index_url", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unscoped called")))

    client = TestClient(main.app)
    resp = client.post("/index/url", json={"url": "https://example.com", "repo_path": str(tmp_path)})
    assert resp.status_code == 200
    assert called["scoped"] is True

