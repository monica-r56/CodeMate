from pathlib import Path

import backend.indexer as indexer


def test_index_file_scoped_upserts_repo_payload(monkeypatch, tmp_path):
    calls = {"delete": [], "upsert": []}

    monkeypatch.setattr(indexer, "ensure_collections", lambda: None)

    def fake_delete_by_filter(collection, filters):
        calls["delete"].append((collection, filters))

    def fake_upsert(collection, text, payload, point_id=None):
        calls["upsert"].append((collection, text, payload, point_id))
        return point_id or "id"

    monkeypatch.setattr(indexer, "delete_by_filter", fake_delete_by_filter)
    monkeypatch.setattr(indexer, "upsert", fake_upsert)

    f = tmp_path / "doc.txt"
    f.write_text("Para one.\n\nPara two.\n", encoding="utf-8")

    n = indexer.index_file_scoped(
        str(f),
        repo_path=str(tmp_path / "repo"),
        source="upload:doc.txt",
        repo_name="repo",
    )

    assert n > 0
    assert calls["delete"] == [("documentation", {"repo_path": str(Path(tmp_path / "repo").resolve()), "source": "upload:doc.txt"})]
    assert calls["upsert"]
    collection, _text, payload, point_id = calls["upsert"][0]
    assert collection == "documentation"
    assert payload["repo_name"] == "repo"
    assert payload["repo_path"] == str(Path(tmp_path / "repo").resolve())
    assert payload["source"] == "upload:doc.txt"
    assert point_id


def test_index_url_scoped_deletes_and_upserts(monkeypatch, tmp_path):
    calls = {"delete": [], "upsert": []}

    monkeypatch.setattr(indexer, "ensure_collections", lambda: None)

    def fake_delete_by_filter(collection, filters):
        calls["delete"].append((collection, filters))

    def fake_upsert(collection, text, payload, point_id=None):
        calls["upsert"].append((collection, text, payload, point_id))
        return point_id or "id"

    class FakeResp:
        text = "<html><body>Hello world</body></html>"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(indexer, "delete_by_filter", fake_delete_by_filter)
    monkeypatch.setattr(indexer, "upsert", fake_upsert)
    monkeypatch.setattr(indexer.httpx, "get", lambda *args, **kwargs: FakeResp())

    url = "https://example.com/docs"
    n = indexer.index_url_scoped(url, repo_path=str(tmp_path / "repo"), repo_name="repo")

    assert n > 0
    assert calls["delete"] == [("documentation", {"repo_path": str(Path(tmp_path / "repo").resolve()), "source": url})]
    assert calls["upsert"]
    collection, _text, payload, point_id = calls["upsert"][0]
    assert collection == "documentation"
    assert payload["repo_path"] == str(Path(tmp_path / "repo").resolve())
    assert payload["source"] == url
    assert point_id

