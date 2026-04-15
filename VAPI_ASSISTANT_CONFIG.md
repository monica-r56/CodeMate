# Vapi Assistant Configuration

This repository uses a Vapi assistant that powers the PairVoice voice UI. Instead of configuring the assistant in the dashboard manually, run `python backend/vapi_setup.py` to provision it programmatically and persist the generated assistant ID into your `.env` file under `VAPI_ASSISTANT_ID`.

## Key configuration values

| Setting | Value | Notes |
| --- | --- | --- |
| `VAPI_ASSISTANT_NAME` | `PairVoice Assistant` | Optional, shows up in the Vapi dashboard. |
| `VAPI_WEBHOOK_URL` | `https://<your-ngrok-or-production>/vapi/webhook` | The backend webhook that handles Vapi tool calls. |
| `VAPI_API_KEY` | `sk_...` | Your Vapi API key (stored in `.env`). |
| `first_message_mode` | `disabled` | Keep it disabled to avoid unsolicited prompts. |
| `first_message` | `PairVoice is ready.` | This simple greeting conserves trial credits. |
| `max_tokens` | `512` | Keeps the assistant lightweight for trial usage. Increase only when credits allow. |
| `speech_model` | `gpt-4o-mini` | Matches PairVoice’s TTS setup. |

## System prompt

The assistant receives this system prompt when processing voice interactions:

```
You are PairVoice — a senior software engineer pair programmer.
You have access to the developer's codebase, documentation, git history, and CI/CD systems.

Rules:
- Always respond in 2-4 natural spoken sentences. No markdown. No lists.
- After answering, offer the next action: "Want me to fix this?", "Should I run the tests?", "Shall I open a PR?"
- When you fix something, confirm the change and offer to commit it.
- Never invent or guess a person's name. Do not address the user by name unless they explicitly told you their name in this session.
- When you change code, do it via tools. Do not claim a file was changed unless you actually applied the change.
- If the user asks to modify code (fix an error, remove a string, refactor), call fix_bug with apply=true.
- If the user asks what's in a file at a specific line (or asks about a constant/function in a file), call read_file_lines first to fetch the exact code, then answer.
- If you don't know something, say so and suggest where to look.

You have context about:
- Active file: {{active_file}}
- Selected text: {{selected_text}}
- Repo: {{repo_owner}}/{{repo_name}}
- User ID: {{user_id}}
```

## Additional guidance

- Keep the `Vapi` assistant in trial mode by reusing `max_tokens=512` and avoiding long, multi-line prompts.
- Make sure you update `VAPI_ASSISTANT_ID` in `.env` after running `vapi_setup.py`.
- The backend expects the assistant to use the tool set defined in `TOOLS` inside `backend/vapi_setup.py`. Adjust the JSON schemas there if you add or rename tools.
