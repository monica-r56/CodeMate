import backend.vapi_handler as vapi_handler


def test_fix_bug_defaults_to_active_file_and_applies(monkeypatch):
    calls = {"applied": False}

    def fake_preview_patch(file_path, original, fixed):
        assert file_path == "src/app.py"
        assert "old" in original
        assert "new" in fixed
        return {"success": True, "diff": "---x\n+++y\n-old\n+new\n", "lines_changed": 2, "file_path": file_path}

    def fake_apply_patch(repo_path, file_path, original, fixed):
        calls["applied"] = True
        assert file_path == "src/app.py"
        return {"success": True, "file_path": file_path, "diff": "diff", "lines_changed": 2}

    monkeypatch.setattr(vapi_handler, "preview_patch", fake_preview_patch)
    monkeypatch.setattr(vapi_handler, "apply_patch", fake_apply_patch)
    monkeypatch.setattr(vapi_handler, "read_file", lambda repo_path, file_path: "old")
    monkeypatch.setattr(vapi_handler, "_generate_fix", lambda original, desc, ctx: "new")

    out = vapi_handler.handle_fix_bug(
        {"error_description": "remove unwanted string"},
        "/tmp/repo",
        user_context={"active_file": "src/app.py"},
        user_id="u1",
    )

    assert calls["applied"] is True
    assert out["action"] == "diff"
    assert out["file_path"] == "src/app.py"
    assert "diff" in out
    assert out["new_content"] == "new"


def test_fix_bug_requires_a_target_file(monkeypatch):
    # No file_path, no active_file, no match found -> should not claim a fix.
    monkeypatch.setattr(vapi_handler, "search", lambda *args, **kwargs: [])

    out = vapi_handler.handle_fix_bug(
        {"error_description": "remove unwanted string"},
        "/tmp/repo",
        user_context={},
        user_id="u1",
    )

    assert out["action"] == "none"
    assert "need to know which file" in out["speech"].lower()

