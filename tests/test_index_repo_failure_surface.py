from pathlib import Path

import backend.indexer as indexer


def test_index_repo_raises_when_all_chunks_fail(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def hello():\n  return 1\n", encoding="utf-8")

    monkeypatch.setattr(indexer, "ensure_collections", lambda: None)

    def boom(*args, **kwargs):
        raise RuntimeError("GOOGLE_API_KEY is required for embeddings.")

    monkeypatch.setattr(indexer, "upsert", boom)

    try:
        indexer.index_repo(str(repo))
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "GOOGLE_API_KEY" in str(exc)

