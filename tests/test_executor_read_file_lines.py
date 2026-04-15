from pathlib import Path

import backend.executor as executor


def test_read_file_lines_reads_exact_lines(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    f = repo / "a.txt"
    f.write_text("one\ntwo\nthree\n", encoding="utf-8")

    out = executor.read_file_lines(str(repo), "a.txt", start_line=2, end_line=3)
    assert out["success"] is True
    assert out["file_path"] == "a.txt"
    assert out["start_line"] == 2
    assert out["end_line"] == 3
    assert "2 | two" in out["text"]
    assert "3 | three" in out["text"]


def test_read_file_lines_blocks_path_traversal(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")

    out = executor.read_file_lines(str(repo), "../outside.txt", start_line=1, end_line=1)
    assert out["success"] is False
    assert "outside repo" in out["error"].lower()


def test_read_file_lines_missing_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    out = executor.read_file_lines(str(repo), "missing.txt", start_line=1, end_line=1)
    assert out["success"] is False
    assert "file not found" in out["error"].lower()

