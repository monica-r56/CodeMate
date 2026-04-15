"""
Utility to provision the PairVoice assistant on Vapi and persist the assistant ID.

Run once: python vapi_setup.py
"""
import os

import httpx
from dotenv import load_dotenv, find_dotenv, set_key

load_dotenv()

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search the codebase, documentation, and error patterns for relevant context",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for"},
                    "context": {"type": "string", "description": "Additional conversation context"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_codebase",
            "description": "Perform a semantic search limited to the codebase index",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Code lookup query"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": "Search the documentation index for answers",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Documentation query"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fix_bug",
            "description": "Propose (and optionally apply) a fix for a file, returning a diff and new file contents",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path to the file (optional; defaults to active editor file)"},
                    "error_description": {"type": "string", "description": "Error details"},
                    "original_code": {"type": "string", "description": "Existing source when available"},
                    "fixed_code": {"type": "string", "description": "New version of the source"},
                    "apply": {"type": "boolean", "description": "If true, apply the fix immediately on disk"}
                },
                "required": ["error_description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file_lines",
            "description": "Read specific line(s) from a repo file (used to answer questions like 'what is on line 7')",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Relative path to the file (optional; defaults to active editor file)"},
                    "start_line": {"type": "integer", "description": "1-based line number to start reading"},
                    "end_line": {"type": "integer", "description": "1-based line number to stop reading (optional; defaults to start_line)"}
                },
                "required": ["start_line"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the relevant test suite or a targeted test",
            "parameters": {
                "type": "object",
                "properties": {
                    "test_path": {"type": "string", "description": "Optional path to specific tests"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "commit_and_push",
            "description": "Commit staged changes and push a branch",
            "parameters": {
                "type": "object",
                "properties": {
                    "branch_name": {"type": "string"},
                    "commit_message": {"type": "string"},
                    "files": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_pull_request",
            "description": "Open a pull request for the current branch",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "branch": {"type": "string"},
                    "base": {"type": "string"},
                    "assignee": {"type": "string"}
                },
                "required": ["branch"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_open_prs",
            "description": "List open pull requests",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Optional keyword to filter titles"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pr_details",
            "description": "Get details about a specific PR",
            "parameters": {
                "type": "object",
                "properties": {
                    "pr_number": {"type": "integer"}   
                },
                "required": ["pr_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_build_status",
            "description": "Retrieve the latest CI/CD status",
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {"type": "string"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_commits",
            "description": "List the most recent commits on a branch",
            "parameters": {
                "type": "object",
                "properties": {
                    "branch": {"type": "string"},
                    "count": {"type": "integer", "description": "Maximum number of commits to return"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recall_context",
            "description": "Recall past conversation snippets or summaries",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic to recall"}
                }
            }
        }
    }
]

SYSTEM_PROMPT = """
You are PairVoice — a senior software engineer pair programmer.
You have access to the developer's codebase, documentation, git history, and CI/CD systems.

Rules:
- Always respond in 2-4 natural spoken sentences. No markdown. No lists.
- After answering, offer the next action: "Want me to fix this?", "Should I run the tests?", "Shall I open a PR?"
- Never invent or guess a person's name. Do not address the user by name unless they explicitly told you their name in this session.
- When you change code, do it via tools. Do not claim a file was changed unless you actually applied the change.
- If the user asks to modify code (fix an error, remove a string, refactor), call fix_bug with apply=true. Use file_path if known; otherwise omit it to default to the active editor file.
- If the user asks what's in a file at a specific line (or asks about a constant/function in a file), use read_file_lines first to fetch the exact code, then answer.
- When you fix something, confirm the change and offer to commit it.
- If you don't know something, say so and suggest where to look.

You have context about:
- Active file: {{active_file}}
- Selected text: {{selected_text}}
- Repo: {{repo_owner}}/{{repo_name}}
- User ID: {{user_id}}
"""


def create_assistant():
    api_key = os.getenv("VAPI_API_KEY")
    webhook = os.getenv("VAPI_WEBHOOK_URL")
    assistant_name = os.getenv("VAPI_ASSISTANT_NAME", "PairVoice Assistant")
    description = "Voice-native PairVoice assistant for Vapi.ai"
    first_message_mode = os.getenv("VAPI_FIRST_MESSAGE_MODE", "disabled")
    first_message = os.getenv("VAPI_FIRST_MESSAGE", "PairVoice is ready.")
    max_tokens = int(os.getenv("VAPI_MAX_TOKENS", "512"))
    speech_model = os.getenv("VAPI_SPEECH_MODEL", "gpt-4o-mini")

    if not api_key or not webhook:
        raise RuntimeError("VAPI_API_KEY and VAPI_WEBHOOK_URL must be set in .env.")

    payload = {
        "name": assistant_name,
        "description": description,
        "webhook_url": webhook,
        "tools": TOOLS,
        "system_prompt": SYSTEM_PROMPT,
        "first_message_mode": first_message_mode,
        "first_message": first_message,
        "speech_model": speech_model,
        "max_tokens": max_tokens,
        "language": "en"
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    with httpx.Client(timeout=15) as client:
        response = client.post("https://api.vapi.ai/assistant", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    assistant_id = data.get("assistant_id") or data.get("id")
    if not assistant_id:
        raise RuntimeError(f"Assistant creation succeeded but no ID was returned: {data}")

    dotenv_path = find_dotenv() or ".env"
    with open(dotenv_path, "a"):
        pass
    set_key(dotenv_path, "VAPI_ASSISTANT_ID", assistant_id)
    print(f"Created assistant '{assistant_name}' with ID {assistant_id}")


if __name__ == "__main__":
    create_assistant()
