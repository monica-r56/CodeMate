"""
Indexer — chunks and embeds codebase + documents into Qdrant.

Usage:
    python indexer.py --repo /path/to/your/repo
    python indexer.py --doc /path/to/file.md
    python indexer.py --url https://your-confluence-page
"""
import os, sys, argparse, hashlib, re
from pathlib import Path
from qdrant_service import upsert, search, ensure_collections, delete_by_filter
import httpx
from typing import Optional

CODE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rb", ".rs", ".cpp", ".c", ".cs"}
DOC_EXTENSIONS  = {".md", ".rst", ".txt", ".html"}
IGNORE_DIRS     = {"node_modules", ".git", "__pycache__", "dist", "build", ".venv", "venv"}

MAX_CHUNK_CHARS = 1200
OVERLAP_CHARS   = 150


def chunk_code(content: str, filepath: str) -> list[dict]:
    """Split code by function/class boundaries, fall back to fixed-size chunks."""
    chunks = []
    lines  = content.splitlines()

    # Simple boundary detection — works for Python, TS, JS, Go
    boundary_pattern = re.compile(
        r"^\s*(def |async def |class |function |const \w+ = |export function |export default |func )"
    )

    current_chunk_lines = []
    current_start_line  = 1

    for i, line in enumerate(lines, 1):
        if boundary_pattern.match(line) and current_chunk_lines:
            chunk_text = "\n".join(current_chunk_lines).strip()
            if len(chunk_text) > 80:
                chunks.append({
                    "text": chunk_text,
                    "file_path": filepath,
                    "start_line": current_start_line,
                    "end_line": i - 1,
                    "source_type": "code"
                })
            current_chunk_lines = [line]
            current_start_line  = i
        else:
            current_chunk_lines.append(line)

    # Last chunk
    if current_chunk_lines:
        chunk_text = "\n".join(current_chunk_lines).strip()
        if len(chunk_text) > 80:
            chunks.append({
                "text": chunk_text,
                "file_path": filepath,
                "start_line": current_start_line,
                "end_line": len(lines),
                "source_type": "code"
            })

    # If no boundaries found, fixed-size split
    if not chunks and len(content) > 80:
        for i in range(0, len(content), MAX_CHUNK_CHARS - OVERLAP_CHARS):
            chunks.append({
                "text": content[i:i + MAX_CHUNK_CHARS],
                "file_path": filepath,
                "start_line": 0,
                "end_line": 0,
                "source_type": "code"
            })

    return chunks


def chunk_text(content: str, source: str, source_type: str) -> list[dict]:
    """Split documents into overlapping fixed-size chunks."""
    chunks = []
    paragraphs = re.split(r"\n{2,}", content)
    current = ""

    for para in paragraphs:
        if len(current) + len(para) < MAX_CHUNK_CHARS:
            current += "\n\n" + para
        else:
            if current.strip():
                chunks.append({"text": current.strip(), "source": source, "source_type": source_type})
            current = para

    if current.strip():
        chunks.append({"text": current.strip(), "source": source, "source_type": source_type})

    return chunks


def file_hash(content: str) -> str:
    return hashlib.md5(content.encode()).hexdigest()


def file_hash_scoped(content: str, scope: str) -> str:
    """
    Stable point id scoped to a specific workspace/file so chunks from different
    repos don't overwrite each other in Qdrant.
    """
    return hashlib.md5(f"{scope}:{content}".encode()).hexdigest()


def index_repo(repo_path: str, index_id: Optional[str] = None):
    """Walk a repo, index code files and doc files."""
    ensure_collections()
    repo_id = os.path.abspath(repo_path)
    repo = Path(repo_id)
    repo_name = repo.name
    index_id = index_id or "default"
    code_count = doc_count = 0
    code_errors = doc_errors = 0
    last_error: Optional[str] = None

    for path in repo.rglob("*"):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue

        suffix = path.suffix.lower()
        rel_path = str(path.relative_to(repo))

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if suffix in CODE_EXTENSIONS:
            chunks = chunk_code(content, rel_path)
            for chunk in chunks:
                try:
                    chunk_payload = {**chunk, "repo_path": repo_id, "repo_name": repo_name, "index_id": index_id}
                    scope = f"{repo_id}:{chunk.get('file_path','')}:{chunk.get('start_line',0)}:code"
                    chunk_id = file_hash_scoped(chunk["text"], scope)
                    upsert("codebase_chunks", chunk["text"], chunk_payload, point_id=chunk_id)
                    code_count += 1
                except Exception as exc:
                    code_errors += 1
                    last_error = str(exc)
            print(f"  [code] {rel_path} → {len(chunks)} chunks")

        elif suffix in DOC_EXTENSIONS or path.name in {"README", "CONTRIBUTING", "ARCHITECTURE"}:
            chunks = chunk_text(content, rel_path, "local_file")
            for i, chunk in enumerate(chunks):
                try:
                    chunk_payload = {**chunk, "repo_path": repo_id, "repo_name": repo_name, "index_id": index_id}
                    scope = f"{repo_id}:{rel_path}:{i}:docs"
                    chunk_id = file_hash_scoped(chunk["text"], scope)
                    upsert("documentation", chunk["text"], chunk_payload, point_id=chunk_id)
                    doc_count += 1
                except Exception as exc:
                    doc_errors += 1
                    last_error = str(exc)
            print(f"  [docs] {rel_path} → {len(chunks)} chunks")

    print(f"\nIndexing complete: {code_count} code chunks, {doc_count} doc chunks")
    if code_errors or doc_errors:
        print(f"Indexing warnings: {code_errors} code chunk failures, {doc_errors} doc chunk failures")

    # If everything failed, surface the underlying error (e.g., missing GOOGLE_API_KEY) instead of silently returning.
    if (code_count + doc_count) == 0 and (code_errors + doc_errors) > 0:
        raise RuntimeError(last_error or "Indexing failed (no chunks were written).")


def index_file(file_path: str):
    """Index a single document file (unscoped)."""
    ensure_collections()
    path = Path(file_path)
    content = path.read_text(encoding="utf-8", errors="ignore")
    chunks = chunk_text(content, str(path), "uploaded_file")
    for chunk in chunks:
        upsert("documentation", chunk["text"], chunk)
    print(f"Indexed {len(chunks)} chunks from {path.name}")


def index_file_scoped(file_path: str, *, repo_path: str, source: str, repo_name: Optional[str] = None) -> int:
    """
    Index a single document file into the documentation collection, scoped to a workspace.
    This enables per-workspace filtering and accurate /index/status counts.
    """
    ensure_collections()
    repo_id = os.path.abspath(repo_path)
    repo_name = repo_name or Path(repo_id).name
    path = Path(file_path)
    content = path.read_text(encoding="utf-8", errors="ignore")

    # Remove any prior chunks for this source within this workspace before re-indexing.
    delete_by_filter("documentation", {"repo_path": repo_id, "source": source})

    chunks = chunk_text(content, source, "uploaded_file")
    for i, chunk in enumerate(chunks):
        payload = {**chunk, "repo_path": repo_id, "repo_name": repo_name}
        scope = f"{repo_id}:{source}:{i}:docs"
        chunk_id = file_hash_scoped(chunk["text"], scope)
        upsert("documentation", chunk["text"], payload, point_id=chunk_id)

    return len(chunks)


def index_url(url: str):
    """Fetch a URL and index its text content (unscoped)."""
    ensure_collections()
    response = httpx.get(url, follow_redirects=True, timeout=15)
    response.raise_for_status()

    # Strip HTML tags simply
    text = re.sub(r"<[^>]+>", " ", response.text)
    text = re.sub(r"\s+", " ", text).strip()

    chunks = chunk_text(text, url, "web_url")
    for chunk in chunks:
        upsert("documentation", chunk["text"], chunk)
    print(f"Indexed {len(chunks)} chunks from {url}")


def index_url_scoped(url: str, *, repo_path: str, repo_name: Optional[str] = None) -> int:
    """Fetch a URL and index its text content, scoped to a workspace."""
    ensure_collections()
    repo_id = os.path.abspath(repo_path)
    repo_name = repo_name or Path(repo_id).name

    # Remove any prior chunks for this URL within this workspace before re-indexing.
    delete_by_filter("documentation", {"repo_path": repo_id, "source": url})

    response = httpx.get(url, follow_redirects=True, timeout=15)
    response.raise_for_status()

    text = re.sub(r"<[^>]+>", " ", response.text)
    text = re.sub(r"\s+", " ", text).strip()

    chunks = chunk_text(text, url, "web_url")
    for i, chunk in enumerate(chunks):
        payload = {**chunk, "repo_path": repo_id, "repo_name": repo_name}
        scope = f"{repo_id}:{url}:{i}:docs"
        chunk_id = file_hash_scoped(chunk["text"], scope)
        upsert("documentation", chunk["text"], payload, point_id=chunk_id)

    return len(chunks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PairVoice Indexer")
    parser.add_argument("--repo", help="Path to a code repository to index")
    parser.add_argument("--doc",  help="Path to a document file to index")
    parser.add_argument("--url",  help="URL to fetch and index")
    args = parser.parse_args()

    if args.repo:
        print(f"Indexing repo: {args.repo}")
        index_repo(args.repo)
    elif args.doc:
        print(f"Indexing document: {args.doc}")
        index_file(args.doc)
    elif args.url:
        print(f"Indexing URL: {args.url}")
        index_url(args.url)
    else:
        parser.print_help()
