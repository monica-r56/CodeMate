import os
import sys
from pathlib import Path


def pytest_configure():
    # Ensure `import backend.*` and `import main` (from backend) works in tests.
    repo_root = Path(__file__).resolve().parent.parent
    backend_dir = repo_root / "backend"
    for p in (str(repo_root), str(backend_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)

    # Keep tests deterministic.
    os.environ.setdefault("REPO_PATH", str(repo_root))

