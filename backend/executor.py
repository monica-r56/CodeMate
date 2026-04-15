import os, subprocess, tempfile, difflib
from pathlib import Path


def apply_patch(repo_path: str, file_path: str, original: str, fixed: str) -> dict:
    """
    Apply a code fix — writes the fixed content to the file.
    Returns a unified diff for the UI to display.
    """
    full_path = Path(repo_path) / file_path
    if not full_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    diff_lines = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        fixed.splitlines(keepends=True),
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm=""
    ))
    diff_text = "".join(diff_lines)

    full_path.write_text(fixed, encoding="utf-8")

    return {
        "success": True,
        "file_path": file_path,
        "diff": diff_text,
        "lines_changed": len([l for l in diff_lines if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))])
    }


def preview_patch(file_path: str, original: str, fixed: str) -> dict:
    """
    Build a unified diff for UI review without writing to disk.
    """
    diff_lines = list(difflib.unified_diff(
        original.splitlines(keepends=True),
        fixed.splitlines(keepends=True),
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm=""
    ))
    diff_text = "".join(diff_lines)
    return {
        "success": True,
        "file_path": file_path,
        "diff": diff_text,
        "lines_changed": len([l for l in diff_lines if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))])
    }


def run_tests(repo_path: str, test_path: str = None) -> dict:
    """Run pytest or npm test and return results."""
    repo = Path(repo_path)

    # Detect test framework
    if (repo / "pytest.ini").exists() or (repo / "pyproject.toml").exists() or (repo / "setup.py").exists():
        cmd = ["python", "-m", "pytest", test_path or ".", "-v", "--tb=short", "-q"]
    elif (repo / "package.json").exists():
        cmd = ["npm", "test", "--", "--watchAll=false"]
    else:
        return {"success": False, "output": "Could not detect test framework (pytest or npm test)."}

    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=60
        )
        output = result.stdout + result.stderr
        passed = result.returncode == 0

        # Parse pytest summary line
        summary = "Tests completed."
        for line in output.splitlines():
            if "passed" in line or "failed" in line or "error" in line:
                summary = line.strip()
                break

        return {
            "success": passed,
            "summary": summary,
            "output": output[-2000:],  # last 2000 chars
            "return_code": result.returncode
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "Tests timed out after 60 seconds."}
    except FileNotFoundError as e:
        return {"success": False, "output": f"Test runner not found: {e}"}


def create_branch_and_commit(repo_path: str, branch_name: str,
                              files_changed: list[str], commit_message: str) -> dict:
    """Create a git branch, stage changed files, and commit."""
    try:
        # Create branch
        subprocess.run(["git", "checkout", "-b", branch_name],
                       cwd=repo_path, check=True, capture_output=True)

        # Stage files
        for f in files_changed:
            subprocess.run(["git", "add", f], cwd=repo_path, check=True, capture_output=True)

        # Commit
        subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=repo_path, check=True, capture_output=True
        )

        return {"success": True, "branch": branch_name, "message": commit_message}
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": e.stderr.decode() if e.stderr else str(e)}


def push_branch(repo_path: str, branch_name: str) -> dict:
    try:
        result = subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=repo_path, capture_output=True, text=True
        )
        if result.returncode == 0:
            return {"success": True}
        return {"success": False, "error": result.stderr}
    except Exception as e:
        return {"success": False, "error": str(e)}


def read_file(repo_path: str, file_path: str) -> str:
    """Read a file from the repo for context."""
    full = Path(repo_path) / file_path
    if full.exists():
        return full.read_text(encoding="utf-8", errors="ignore")
    return ""


def read_file_lines(
    repo_path: str,
    file_path: str,
    start_line: int,
    end_line: int = None,
    max_chars: int = 6000,
) -> dict:
    """
    Read a slice of a repo file with basic path safety.
    Returns a dict with `success`, `file_path`, `start_line`, `end_line`, and `text` (with line numbers).
    """
    root = Path(repo_path).resolve()
    target = (root / file_path).resolve()

    if root != target and root not in target.parents:
        return {"success": False, "error": "Invalid file path (outside repo)."}

    if not target.exists() or not target.is_file():
        return {"success": False, "error": f"File not found: {file_path}"}

    try:
        # Avoid huge reads.
        if target.stat().st_size > 1_500_000:
            return {"success": False, "error": f"File too large to read safely: {file_path}"}
    except Exception:
        pass

    content = target.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()
    total = len(lines)

    try:
        start = int(start_line)
    except Exception:
        start = 1
    if start < 1:
        start = 1
    if start > total:
        start = total if total > 0 else 1

    if end_line is None:
        end = start
    else:
        try:
            end = int(end_line)
        except Exception:
            end = start
    if end < start:
        end = start
    if end > total:
        end = total

    # Build numbered output (1-based).
    out_lines = []
    for i in range(start, end + 1):
        prefix = f"{i:>4} | "
        out_lines.append(prefix + (lines[i - 1] if i - 1 < total else ""))
        if sum(len(x) + 1 for x in out_lines) > max_chars:
            break

    text = "\n".join(out_lines).rstrip()
    return {
        "success": True,
        "file_path": file_path,
        "start_line": start,
        "end_line": min(end, start + len(out_lines) - 1),
        "text": text,
        "total_lines": total,
    }
