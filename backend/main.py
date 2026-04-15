"""
PairVoice Backend — FastAPI

Endpoints:
  POST /vapi/webhook        — Vapi sends all events here
  POST /index/repo          — trigger codebase indexing
  POST /index/document      — upload + index a document
  POST /index/url           — index a URL
  POST /index/file-update   — incremental re-index on file save
  GET  /health              — health check
"""
import asyncio
import json
import logging
import os
import tempfile
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from qdrant_service import count_points, delete_by_filter, ensure_collections, upsert
from vapi_handler import dispatch
from indexer import chunk_code, file_hash_scoped, index_file, index_file_scoped, index_repo, index_url, index_url_scoped
from memory import add_turn, get_redis

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = FastAPI(title="PairVoice Backend", version="1.0.0")

app.add_middleware(
  CORSMiddleware,
  allow_origins=["*"],
  allow_methods=["*"],
  allow_headers=["*"],
)


class HealthResponse(BaseModel):
    status: str
    service: str


@app.on_event("startup")
async def startup():
    ensure_collections()
    logging.info("PairVoice backend started. Collections ready.")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="pairvoice-backend")


# ── Vapi Webhook ──────────────────────────────────────────────────────────────

@app.post("/vapi/webhook")
async def vapi_webhook(request: Request):
    """
    Vapi sends tool-call events here.
    Each tool call has: { message: { type, toolCallList, call: { id } } }
    """
    body = await request.json()
    msg  = body.get("message", {})
    msg_type = msg.get("type", "")

    # Handle tool calls
    if msg_type == "tool-calls":
        tool_calls  = msg.get("toolCallList", [])
        call_id     = msg.get("call", {}).get("id", "default")
        tasks = [asyncio.to_thread(process_tool_call, tc, call_id) for tc in tool_calls]
        responses = await asyncio.gather(*tasks)
        return {"results": responses}

    # Handle end of call — persist final memory
    if msg_type == "end-of-call-report":
        return {"status": "recorded"}

    return {"status": "ignored"}


# ── Indexing endpoints ────────────────────────────────────────────────────────

class RepoIndexRequest(BaseModel):
    repo_path: str
    owner: str = ""
    repo_name: str = ""


class RepoIndexResponse(BaseModel):
    status: str
    repo_path: str
    code_chunks: int = 0
    doc_chunks: int = 0


class DocumentIndexResponse(BaseModel):
    status: str
    filename: str


class UrlIndexRequest(BaseModel):
    url: str
    repo_path: str = ""


class UrlIndexResponse(BaseModel):
    status: str
    url: str


class FileUpdateRequest(BaseModel):
    file_path: str
    content: str
    repo_path: str


class FileUpdateResponse(BaseModel):
    status: str
    chunks_updated: int


class IndexStatusResponse(BaseModel):
    status: str
    repo_path: str
    code_chunks: int
    doc_chunks: int


class ContextPayload(BaseModel):
    user_id: str
    active_file: str = ""
    active_file_content: str = ""
    selected_text: str = ""
    terminal_output: str = ""
    repo_owner: str = ""
    repo_name: str = ""
    repo_path: str = ""


class ContextResponse(BaseModel):
    status: str


@app.post("/index/repo", response_model=RepoIndexResponse)
def index_repo_endpoint(req: RepoIndexRequest) -> RepoIndexResponse:
    try:
        repo_id = os.path.abspath(req.repo_path)
        # Two-phase indexing: write new chunks under a fresh `index_id`, then delete the previous index only on success.
        # This prevents "0 chunks" regressions when embedding quotas/rate-limits are hit mid-index.
        r = get_redis()
        index_key = f"pairvoice:index:{repo_id}"
        previous_index_id = r.get(index_key) if r else None
        new_index_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"

        index_repo(repo_id, index_id=new_index_id)

        # Count what we just wrote.
        code_chunks_new = count_points("codebase_chunks", filters={"repo_path": repo_id, "index_id": new_index_id})
        doc_chunks_total = count_points("documentation", filters={"repo_path": repo_id})

        # Cleanup old code/docs from the previous successful index, but keep external docs (uploads/urls) which don't have that old index_id.
        if previous_index_id:
            delete_by_filter("codebase_chunks", {"repo_path": repo_id, "index_id": previous_index_id})
            delete_by_filter("documentation", {"repo_path": repo_id, "index_id": previous_index_id})

        if r:
            r.set(index_key, new_index_id)

        return RepoIndexResponse(status="ok", repo_path=repo_id, code_chunks=code_chunks_new, doc_chunks=doc_chunks_total)
    except Exception as exc:
        logging.error("Repo indexing failed for %s: %s", req.repo_path, exc, exc_info=True)
        detail = f"Repository indexing failed: {exc}"
        if "429" in str(exc) or "Quota exceeded" in str(exc) or "rate limit" in str(exc).lower():
            raise HTTPException(status_code=429, detail=detail)
        raise HTTPException(status_code=500, detail=detail)


@app.post("/index/document", response_model=DocumentIndexResponse)
async def index_document_endpoint(
    file: UploadFile = File(...),
    repo_path: str = Form("")
) -> DocumentIndexResponse:
    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        if repo_path:
            index_file_scoped(tmp_path, repo_path=repo_path, source=f"upload:{file.filename}")
        else:
            index_file(tmp_path)
        return DocumentIndexResponse(status="ok", filename=file.filename)
    except Exception as exc:
        logging.error("Document indexing failed for %s: %s", file.filename, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Document indexing failed")
    finally:
        os.unlink(tmp_path)


@app.post("/index/url", response_model=UrlIndexResponse)
def index_url_endpoint(req: UrlIndexRequest) -> UrlIndexResponse:
    try:
        if req.repo_path:
            index_url_scoped(req.url, repo_path=req.repo_path)
        else:
            index_url(req.url)
        return UrlIndexResponse(status="ok", url=req.url)
    except Exception as exc:
        logging.error("URL indexing failed for %s: %s", req.url, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="URL indexing failed")


@app.post("/index/file-update", response_model=FileUpdateResponse)
def file_update(req: FileUpdateRequest) -> FileUpdateResponse:
    try:
        repo_id = os.path.abspath(req.repo_path)
        delete_by_filter("codebase_chunks", {"repo_path": repo_id, "file_path": req.file_path})
        chunks = chunk_code(req.content, req.file_path)
        repo_name = Path(repo_id).name
        updated = 0
        for chunk in chunks:
            try:
                chunk_payload = {**chunk, "repo_path": repo_id, "repo_name": repo_name}
                scope = f"{repo_id}:{chunk.get('file_path','')}:{chunk.get('start_line',0)}:code"
                point_id = file_hash_scoped(chunk["text"], scope)
                upsert("codebase_chunks", chunk["text"], chunk_payload, point_id=point_id)
                updated += 1
            except Exception as exc:
                logging.warning("Chunk upsert failed for %s: %s", req.file_path, exc)
        return FileUpdateResponse(status="ok", chunks_updated=updated)
    except Exception as exc:
        logging.error("Incremental indexing failed for %s: %s", req.file_path, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"File re-index failed: {exc}")


@app.get("/index/status", response_model=IndexStatusResponse)
def index_status(repo_path: str) -> IndexStatusResponse:
    """
    Return indexing stats for a repo, based on Qdrant payload filters.
    """
    try:
        repo_id = os.path.abspath(repo_path)
        filters = {"repo_path": repo_id}
        code_chunks = count_points("codebase_chunks", filters=filters)
        doc_chunks = count_points("documentation", filters=filters)
        return IndexStatusResponse(
            status="ok",
            repo_path=repo_id,
            code_chunks=code_chunks,
            doc_chunks=doc_chunks
        )
    except Exception as exc:
        logging.error("Index status failed for %s: %s", repo_path, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Index status failed")


@app.post("/context", response_model=ContextResponse)
def receive_context(payload: ContextPayload) -> ContextResponse:
    """
    Extension sends editor context before/during a voice session.
    We store it in a per-user context cache for the tool handlers.
    """
    import redis as redis_lib
    r = redis_lib.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
    normalized = payload.model_dump()
    if normalized.get("repo_path"):
        normalized["repo_path"] = os.path.abspath(normalized["repo_path"])
    r.setex(
        f"pairvoice:context:{payload.user_id}",
        3600,
        json.dumps(normalized)
    )
    logging.info("Stored context for user %s (repo: %s)", payload.user_id, normalized.get("repo_path"))
    return ContextResponse(status="ok")


def process_tool_call(tool_call: dict[str, Any], user_id: str) -> dict[str, Any]:
    tool_name = tool_call.get("function", {}).get("name", "")
    raw_args = tool_call.get("function", {}).get("arguments", "{}")
    if isinstance(raw_args, str):
        try:
            tool_args = json.loads(raw_args)
        except json.JSONDecodeError:
            tool_args = {}
    else:
        tool_args = raw_args or {}

    try:
        result = dispatch(tool_name, tool_args, user_id=user_id)
    except Exception as exc:
        logging.error("Tool %s failed for user %s: %s", tool_name, user_id, exc, exc_info=True)
        spoken = "I hit an internal error handling that request."
        add_turn(user_id, "tool", f"{tool_name}: {spoken}")
        return {"toolCallId": tool_call.get("id"), "result": spoken}

    if isinstance(result, dict):
        spoken = result.get("speech", "Done.")
    else:
        spoken = str(result)

    add_turn(user_id, "tool", f"{tool_name}: {spoken[:200]}")
    return {"toolCallId": tool_call.get("id"), "result": spoken}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
