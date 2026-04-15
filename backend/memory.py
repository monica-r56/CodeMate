import os, json, time
from dotenv import load_dotenv
import redis as redis_lib
from qdrant_service import upsert, search, embed

load_dotenv()

_redis = None

def get_redis():
    global _redis
    if _redis is None:
        url = os.getenv("REDIS_URL", "redis://localhost:6379")
        _redis = redis_lib.from_url(url, decode_responses=True)
    return _redis


SESSION_TTL = 60 * 60 * 4   # 4 hours
MAX_TURNS   = 10
SUMMARIZE_EVERY = 5


def session_key(user_id: str) -> str:
    return f"pairvoice:session:{user_id}"


def add_turn(user_id: str, role: str, content: str):
    r = get_redis()
    key = session_key(user_id)
    turns = get_session(user_id)
    turns.append({"role": role, "content": content, "ts": time.time()})
    # Keep last MAX_TURNS
    if len(turns) > MAX_TURNS:
        turns = turns[-MAX_TURNS:]
    r.setex(key, SESSION_TTL, json.dumps(turns))

    # Every SUMMARIZE_EVERY turns, summarize into long-term memory
    if len(turns) % SUMMARIZE_EVERY == 0:
        _persist_to_long_term(user_id, turns)


def get_session(user_id: str) -> list[dict]:
    r = get_redis()
    raw = r.get(session_key(user_id))
    return json.loads(raw) if raw else []


def get_full_context(user_id: str, query: str) -> dict:
    """Return both short-term session and relevant long-term memories."""
    session = get_session(user_id)
    long_term = search(
        "conversation_memory", query,
        limit=3,
        filters={"user_id": user_id}
    )
    return {
        "recent_turns": session,
        "long_term_memories": [m.get("summary", "") for m in long_term]
    }


def _persist_to_long_term(user_id: str, turns: list[dict]):
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    model = genai.GenerativeModel('gemini-1.5-flash')

    conversation_text = "\n".join(
        f"{t['role'].upper()}: {t['content']}" for t in turns[-SUMMARIZE_EVERY:]
    )

    prompt = f"Summarize this developer conversation in 2-3 sentences, focusing on what was being worked on, what was found, and what actions were taken:\n\n{conversation_text}"
    
    summary_response = model.generate_content(prompt)
    summary = summary_response.text

    upsert("conversation_memory", summary, {
        "user_id": user_id,
        "summary": summary,
        "timestamp": time.time(),
        "turn_count": len(turns)
    })


def clear_session(user_id: str):
    get_redis().delete(session_key(user_id))
