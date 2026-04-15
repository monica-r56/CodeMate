from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue, PayloadSchemaType
)
import google.generativeai as genai
import os, uuid, json
from dotenv import load_dotenv

load_dotenv()

qdrant = QdrantClient(url=os.getenv("QDRANT_URL"), api_key=os.getenv("QDRANT_API_KEY"))
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

EMBED_MODEL = "models/gemini-embedding-001"
VECTOR_SIZE = 3072

COLLECTIONS = ["codebase_chunks", "documentation", "error_patterns", "conversation_memory"]


def ensure_collections():
    existing = [c.name for c in qdrant.get_collections().collections]
    for name in COLLECTIONS:
        if name in existing:
            # Check if vector size matches
            collection_info = qdrant.get_collection(name)
            current_size = collection_info.config.params.vectors.size
            if current_size != VECTOR_SIZE:
                print(f"Recreating collection {name} due to vector size mismatch ({current_size} -> {VECTOR_SIZE})")
                qdrant.delete_collection(name)
                qdrant.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
                )
        else:
            qdrant.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
            )
            print(f"Created collection: {name}")

        # Qdrant Cloud can require payload indexes for filtered operations.
        _ensure_payload_indexes(name)


def _ensure_payload_indexes(collection: str):
    # Only index fields we use for filters (delete/count/search scoping).
    if collection == "codebase_chunks":
        fields = ["repo_path", "file_path", "index_id"]
    elif collection == "documentation":
        fields = ["repo_path", "source", "index_id"]
    elif collection == "error_patterns":
        fields = ["file_path", "source_type"]
    else:
        fields = []

    for field in fields:
        try:
            qdrant.create_payload_index(
                collection_name=collection,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception:
            # Index may already exist, or the backend may not support it; ignore.
            pass


def embed(text: str) -> list[float]:
    if not os.getenv("GOOGLE_API_KEY"):
        raise RuntimeError("GOOGLE_API_KEY is required for embeddings.")
    response = genai.embed_content(model=EMBED_MODEL, content=text)
    return response["embedding"]


def upsert(collection: str, text: str, payload: dict, point_id: str = None):
    vector = embed(text)
    point_id = point_id or str(uuid.uuid4())
    qdrant.upsert(
        collection_name=collection,
        points=[PointStruct(id=point_id, vector=vector, payload={**payload, "text": text})]
    )
    return point_id


def search(collection: str, query: str, limit: int = 5, filters: dict = None) -> list[dict]:
    vector = embed(query)
    filter_obj = None
    if filters:
        conditions = [FieldCondition(key=k, match=MatchValue(value=v)) for k, v in filters.items()]
        filter_obj = Filter(must=conditions)

    results = qdrant.search(
        collection_name=collection,
        query_vector=vector,
        limit=limit,
        query_filter=filter_obj,
        with_payload=True
    )
    return [{"score": r.score, **r.payload} for r in results]


def search_all(query: str, limit: int = 4, filters: dict = None) -> list[dict]:
    """Search across codebase + docs simultaneously and merge results."""
    code_results = search("codebase_chunks", query, limit=limit, filters=filters)
    doc_results = search("documentation", query, limit=limit, filters=filters)
    error_results = search("error_patterns", query, limit=2)

    all_results = code_results + doc_results + error_results
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return all_results[:limit + 2]


def count_points(collection: str, filters: dict = None) -> int:
    filter_obj = None
    if filters:
        conditions = [FieldCondition(key=k, match=MatchValue(value=v)) for k, v in filters.items()]
        filter_obj = Filter(must=conditions)
    result = qdrant.count(
        collection_name=collection,
        count_filter=filter_obj,
        exact=True
    )
    return int(getattr(result, "count", 0))


def delete_by_filter(collection: str, filters: dict):
    from qdrant_client.models import FilterSelector
    conditions = [FieldCondition(key=k, match=MatchValue(value=v)) for k, v in filters.items()]
    qdrant.delete(
        collection_name=collection,
        points_selector=FilterSelector(filter=Filter(must=conditions))
    )
