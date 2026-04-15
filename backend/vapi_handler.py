"""
Vapi tool dispatcher.

When the LLM inside Vapi calls a tool, Vapi posts to our /vapi/webhook.
This module resolves the tool name, retrieves cached context, and returns
voice-optimized responses plus any UI metadata.
"""
import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional

import google.generativeai as genai
from qdrant_service import search, search_all, upsert
from github_tools import (
    get_open_prs, get_pr_details, get_build_status,
    get_recent_commits, create_pull_request
)
from executor import apply_patch, preview_patch, run_tests, create_branch_and_commit, push_branch, read_file, read_file_lines
from memory import get_full_context, add_turn, get_redis
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

# Default repo settings — overridden per request from extension context
DEFAULT_REPO_PATH = os.getenv("REPO_PATH", "/tmp/repo")
DEFAULT_OWNER = os.getenv("GITHUB_OWNER", "")
DEFAULT_REPO_NAME = os.getenv("GITHUB_REPO", "")


def dispatch(tool_name: str, tool_args: Dict[str, Any], user_id: str = "default") -> Any:
    """Route a Vapi tool call to the correct handler."""
    tool_args = tool_args or {}
    user_context = get_user_context(user_id)
    repo_path = tool_args.get("repo_path") or user_context.get("repo_path") or DEFAULT_REPO_PATH
    if repo_path:
        repo_path = os.path.abspath(repo_path)
    owner = tool_args.get("owner") or user_context.get("repo_owner") or DEFAULT_OWNER
    repo_name = tool_args.get("repo") or user_context.get("repo_name") or DEFAULT_REPO_NAME

    if tool_name == "search_knowledge":
        query = tool_args.get("query", "").strip()
        context_hint = tool_args.get("context", "")
        filters = {"repo_path": repo_path} if repo_path else None
        results = search_all(f"{query} {context_hint}", limit=4, filters=filters)
        if not results:
            return voice_response("I couldn't find anything relevant in the knowledge base.")
        chunks = "\n\n---\n\n".join(r.get("text", "") for r in results[:4])
        answer = _synthesize(query, chunks, user_id)
        return voice_response(f"I found relevant context. {answer}", "Want me to act on any of it?")

    elif tool_name == "search_codebase":
        query = tool_args.get("query", "").strip()
        filters = {"repo_path": repo_path} if repo_path else None
        results = search("codebase_chunks", query, limit=4, filters=filters)
        if not results:
            return voice_response("I couldn't locate that piece of code.")
        top = results[0]
        file_path = top.get("file_path", "unknown file")
        line = top.get("start_line", 1)
        speech = voice_response(
            f"I found the likely match in {file_path} around line {line}.",
            "Want me to open it for you?"
        )
        return {
            "speech": speech,
            "action": "navigate",
            "file_path": file_path,
            "line": line
        }

    elif tool_name == "search_docs":
        query = tool_args.get("query", "").strip()
        filters = {"repo_path": repo_path} if repo_path else None
        results = search("documentation", query, limit=4, filters=filters)
        if not results:
            return voice_response("No documentation topics matched that query.")
        chunks = "\n\n".join(r.get("text", "") for r in results[:3])
        source = results[0].get("source", "internal docs")
        answer = _synthesize(query, chunks, user_id)
        return voice_response(
            f"According to {source}, {answer}",
            "Want me to bring up that page?"
        )

    elif tool_name == "fix_bug":
        return handle_fix_bug(tool_args, repo_path, user_context=user_context, user_id=user_id)

    elif tool_name == "read_file_lines":
        file_path = (tool_args.get("file_path") or "").strip()
        if not file_path:
            file_path = (user_context.get("active_file") or "").strip()
        if not file_path:
            return voice_response(
                "Tell me which file to read, or open it in your editor and ask again.",
                "Which file should I open?"
            )

        start_line = tool_args.get("start_line", 1)
        end_line = tool_args.get("end_line")
        result = read_file_lines(repo_path, file_path, start_line=start_line, end_line=end_line)
        if not result.get("success"):
            return voice_response(result.get("error", "I couldn't read that file."), "Want me to search the codebase instead?")

        speech = voice_response(
            f"Here is {file_path} lines {result['start_line']} to {result['end_line']}.",
            "Want me to explain what it does or change it?"
        )
        return {
            "speech": speech,
            "action": "show_output",
            "output": result["text"]
        }

    elif tool_name == "run_tests":
        test_path = tool_args.get("test_path")
        result = run_tests(repo_path, test_path)
        if result["success"]:
            return voice_response(
                f"Tests are passing. {result['summary']}",
                "Want me to do anything else?"
            )
        return {
            "speech": voice_response(
                f"Tests failed. {result['summary']}",
                "Want me to investigate the failures?"
            ),
            "action": "show_output",
            "output": result["output"]
        }

    elif tool_name == "commit_and_push":
        branch = tool_args.get("branch_name", "fix/pairvoice-fix")
        files = tool_args.get("files", [])
        message = tool_args.get("commit_message", "fix: applied by PairVoice")
        result = create_branch_and_commit(repo_path, branch, files, message)
        if result["success"]:
            push_branch(repo_path, branch)
            return voice_response(
                f"I committed and pushed branch {branch}.",
                "Want me to open a pull request?"
            )
        return voice_response(f"Git failed: {result.get('error', 'unknown error')}."
                              " Want me to try again?")

    elif tool_name == "open_pull_request":
        pr_result = create_pull_request(
            owner, repo_name,
            title=tool_args.get("title", "Fix by PairVoice"),
            body=tool_args.get("body", "This fix was applied by PairVoice voice agent."),
            head=tool_args.get("branch", "fix/pairvoice-fix"),
            base=tool_args.get("base", "main"),
            assignee=tool_args.get("assignee")
        )
        return voice_response(f"Pull request created. {pr_result}", "Want me to post it for review?")

    elif tool_name == "get_open_prs":
        guard = require_repo_info(owner, repo_name, "list open pull requests")
        if guard:
            return guard
        raw = get_open_prs(owner, repo_name, tool_args.get("keyword"))
        return summarize_for_voice("Here are the open pull requests.", raw, "Want me to open one?")

    elif tool_name == "get_pr_details":
        guard = require_repo_info(owner, repo_name, "get that PR's details")
        if guard:
            return guard
        pr_number = int(tool_args.get("pr_number", 0))
        raw = get_pr_details(owner, repo_name, pr_number)
        return summarize_for_voice("Details for that PR:", raw, "Should I fetch more context?")

    elif tool_name == "get_build_status":
        guard = require_repo_info(owner, repo_name, "fetch the build status")
        if guard:
            return guard
        branch = tool_args.get("branch", "main")
        raw = get_build_status(owner, repo_name, branch)
        return summarize_for_voice("Build status report:", raw, "Want me to monitor the next run?")

    elif tool_name == "get_recent_commits":
        guard = require_repo_info(owner, repo_name, "read recent commits")
        if guard:
            return guard
        branch = tool_args.get("branch", "main")
        count = int(tool_args.get("count", 5))
        raw = get_recent_commits(owner, repo_name, branch, count)
        return summarize_for_voice("Recent commits:", raw, "Need me to cherry-pick anything?")

    elif tool_name == "recall_context":
        query = tool_args.get("query", "").strip()
        memory = get_full_context(user_id, query)
        memories = [m for m in memory.get("long_term_memories", []) if m]
        if memories:
            summary = " ".join(memories[-2:])
            return voice_response(f"Here is what I remember: {summary}", "Want me to act on it?")
        return voice_response("I don't have any relevant memory for that topic.")

    return voice_response(f"I don't know how to handle the tool '{tool_name}' yet.", "Want me to try something else?")


def get_user_context(user_id: str) -> Dict[str, Any]:
    """Read the cached editor context for this user from Redis."""
    r = get_redis()
    raw = r.get(f"pairvoice:context:{user_id}")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logging.warning("Failed to parse context for %s", user_id)
        return {}


def store_error_pattern(error_desc: str, fix_description: str, file_path: str):
    """Store resolved errors so future queries find similar fixes quickly."""
    if not error_desc or not fix_description:
        return
    payload = {
        "error": error_desc,
        "fix": fix_description,
        "file_path": file_path,
        "source_type": "resolved_error"
    }
    try:
        point_id = hashlib.md5(f"{error_desc}:{file_path}".encode()).hexdigest()
        upsert("error_patterns", error_desc, payload, point_id=point_id)
    except Exception as exc:
        logging.error("Failed to store error pattern: %s", exc, exc_info=True)


def voice_response(text: str, offer_action: str = None) -> str:
    """Normalize any response into natural spoken sentences with optional offer."""
    clean = clean_text(text)
    if not clean:
        clean = "Done."
    if clean[-1] not in ".!?":
        clean = f"{clean}."
    if offer_action:
        return f"{clean} {offer_action}"
    return clean


def require_repo_info(owner: str, repo: str, action: str) -> Optional[str]:
    if owner and repo:
        return None
    return voice_response(
        f"I need the repository owner and name to {action}.",
        "Please open the repo from VS Code or set GITHUB_OWNER and GITHUB_REPO in the environment."
    )


def clean_text(text: str) -> str:
    """Strip markdown fences and bullet prefixes."""
    return text.replace("```", "").replace("*", "").replace("•", "").strip()


def summarize_for_voice(prefix: str, raw: str, offer_action: str = None) -> str:
    cleaned_lines = [line.strip("• ").strip() for line in raw.splitlines() if line.strip()]
    summary = " ".join(cleaned_lines)
    summary = summary[:280]
    return voice_response(f"{prefix} {summary}", offer_action)


def handle_fix_bug(
    tool_args: Dict[str, Any],
    repo_path: str,
    *,
    user_context: Optional[Dict[str, Any]] = None,
    user_id: str = "default",
) -> Dict[str, Any]:
    user_context = user_context or {}

    # Prefer explicit tool args, then the active editor file, then an inferred match from search.
    file_path = (tool_args.get("file_path") or "").strip()
    if not file_path:
        file_path = (user_context.get("active_file") or "").strip()
    if not file_path:
        filters = {"repo_path": repo_path} if repo_path else None
        inferred = search("codebase_chunks", tool_args.get("error_description", "Code issue"), limit=1, filters=filters)
        if inferred:
            file_path = (inferred[0].get("file_path") or "").strip()

    error_desc = tool_args.get("error_description", "Code issue")
    original = tool_args.get("original_code", "")
    fixed = tool_args.get("fixed_code", "")

    if not file_path:
        return {
            "speech": voice_response(
                "I can generate a fix, but I need to know which file to edit.",
                "Open the file in VS Code and try again, or tell me the file path."
            ),
            "action": "none"
        }

    if not original or not fixed:
        filters = {"repo_path": repo_path} if repo_path else None
        rag_results = search_all(error_desc, limit=3, filters=filters)
        context_bits = [r.get("text", "") for r in rag_results if r.get("text")]
        selected_text = (user_context.get("selected_text") or "").strip()
        terminal_output = (user_context.get("terminal_output") or "").strip()
        active_file = (user_context.get("active_file") or "").strip()
        active_file_content = user_context.get("active_file_content") or ""

        if selected_text:
            context_bits.append(f"Selected snippet (if relevant):\n{selected_text}")
        if terminal_output:
            context_bits.append(f"Terminal output (if relevant):\n{terminal_output[-1500:]}")
        context_text = "\n\n".join(context_bits)

        if not original:
            if active_file and active_file == file_path and active_file_content:
                original = active_file_content
            else:
                original = read_file(repo_path, file_path)

        if not fixed:
            fixed = _generate_fix(original, error_desc, context_text)

    result = preview_patch(file_path, original, fixed)

    # Default to applying fixes on disk. The UI still receives the diff for review.
    auto_apply = bool(tool_args.get("apply", True))
    applied = None
    if auto_apply:
        applied = apply_patch(repo_path, file_path, original, fixed)

    if auto_apply and applied and applied.get("success"):
        speech = voice_response(
            f"I applied a fix to {file_path} affecting {result['lines_changed']} lines.",
            "Want me to run tests?"
        )
    else:
        speech = voice_response(
            f"I prepared a fix for {file_path} affecting {result['lines_changed']} lines.",
            "Want me to apply it?"
        )
    return {
        "speech": speech,
        "action": "diff",
        "diff": result["diff"],
        "file_path": file_path,
        "new_content": fixed
    }


def _synthesize(query: str, context: str, user_id: str) -> str:
    """Use Gemini to synthesize a spoken answer from retrieved chunks."""
    memory = get_full_context(user_id, query)
    recent = "\n".join(
        f"{t['role']}: {t['content']}" for t in memory.get("recent_turns", [])[-4:]
    )

    prompt = (
        "You are PairVoice — a senior engineer pair programmer. Answer in 2-4 concise spoken sentences. "
        "No markdown, no lists. Speak naturally and offer the next action when there is one."
        f"\n\nRecent conversation:\n{recent}\n\nContext:\n{context}\n\nQuestion: {query}"
    )
    response = model.generate_content(prompt)
    return response.text


def _generate_fix(original_code: str, error_description: str, context: str) -> str:
    """Generate fixed code using Gemini."""
    prompt = (
        "You are a senior engineer. Return ONLY the complete fixed code file. No explanation, no markdown fences.\n\n"
        f"Error: {error_description}\n\nContext:\n{context}\n\nOriginal code:\n{original_code}"
    )
    response = model.generate_content(prompt)
    return response.text
