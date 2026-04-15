# PairVoice — Voice-Native Pair Programmer

> Speak to understand, fix, and ship code. A VS Code extension powered by Vapi + Qdrant.

---

## What it does

- **Ask about errors** → agent explains + offers to fix
- **Ask about code** → semantic search over your codebase
- **Ask about docs** → searches indexed runbooks, wikis, ADRs
- **PR & CI status** → "what's the status of the payment PR?"
- **Fix bugs by voice** → writes the patch, shows diff, applies on approval
- **Run tests** → "run the tests" → speaks results
- **Commit & PR** → "commit this and open a PR, assign to Alice"
- **Memory** → remembers context across the day

---

## Setup in 5 steps

### Step 1 — Get your API keys

| Service | Where to get it | Free tier |
|---------|----------------|-----------|
| **Vapi** | vapi.ai → Dashboard → API Keys | Yes |
| **Qdrant** | cloud.qdrant.io → Create Cluster | Yes (1GB) |
| **OpenAI** | platform.openai.com → API Keys | Pay per use |
| **GitHub** | github.com → Settings → Developer Settings → PAT | Free |
| **Redis** | upstash.com → Create Database | Yes |

### Step 2 — Set up the backend

```bash
cd backend
cp .env.example .env
# Fill in all values in .env

pip install -r requirements.txt

# Start the server
python main.py
# → Running at http://localhost:8000
```

### Step 3 — Expose backend to Vapi (for webhooks)

```bash
# Install ngrok: https://ngrok.com/download
ngrok http 8000
# → Copy the https URL e.g. https://abc123.ngrok.io
```

### Step 4 — Create your Vapi Assistant

1. Go to vapi.ai → Assistants → Create
2. Set **System Prompt**:
   ```
   You are a senior software engineer pair programmer called PairVoice.
   You help developers understand their codebase, fix bugs, check PRs,
   and run tests — all by voice. Be concise (2-4 sentences). Speak naturally.
   After answering, always offer to take action if one is available.
   ```
3. Set **Server URL**: `https://YOUR-NGROK-URL.ngrok.io/vapi/webhook`
4. Add these **Tools** (type: Function):

   - `search_knowledge` — args: `query` (string), `context` (string)
   - `search_codebase` — args: `query` (string)
   - `search_docs` — args: `query` (string)
   - `fix_bug` — args: `file_path`, `error_description`, `original_code`, `fixed_code`
   - `run_tests` — args: `test_path` (optional string)
   - `commit_and_push` — args: `branch_name`, `files` (array), `commit_message`
   - `open_pull_request` — args: `title`, `body`, `branch`, `base`, `assignee`
   - `get_open_prs` — args: `keyword` (optional)
   - `get_pr_details` — args: `pr_number` (integer)
   - `get_build_status` — args: `branch` (string)
   - `get_recent_commits` — args: `branch`, `count`
   - `recall_context` — args: `query` (string)

5. Copy your **Assistant ID**

### Step 5 — Install the VS Code extension

```bash
cd extension
npm install
npm run compile

# Install locally in VS Code:
# Press F5 in VS Code to launch Extension Development Host
# OR package it:
npx vsce package
# → generates pairvoice-0.1.0.vsix
# Install: code --install-extension pairvoice-0.1.0.vsix
```

### Step 6 — Configure the extension

In VS Code: `Ctrl+,` → search "PairVoice" → set:
- **Backend URL**: `http://localhost:8000`
- **Vapi Public Key**: from vapi.ai dashboard
- **Vapi Assistant ID**: from step 4

### Step 7 — Index your codebase

```bash
# From the backend directory:
python indexer.py --repo /path/to/your/project

# Index a document:
python indexer.py --doc /path/to/runbook.md

# Index a URL:
python indexer.py --url https://your-confluence-page

# OR use the VS Code command:
# Ctrl+Shift+P → "PairVoice: Index This Workspace"
```

---

## Usage

| Action | How |
|--------|-----|
| Start listening | `Ctrl+Shift+V` (or click mic button) |
| Stop | `Ctrl+Shift+V` again |
| Open panel | `Ctrl+Shift+P` → "PairVoice: Open Panel" |
| Index workspace | `Ctrl+Shift+P` → "PairVoice: Index This Workspace" |
| Attach document | `Ctrl+Shift+P` → "PairVoice: Attach Document" |

---

## Example voice commands

```
"What does the PaymentService class do?"
"I'm getting a KeyError on customer_id — what's happening?"
"Fix this bug"
"Are there any open PRs on the auth service?"
"What's the build status on main?"
"Run the tests"
"Commit this fix and open a PR, assign it to alice"
"What were we working on yesterday?"
```

---

## Architecture

```
VS Code Extension (TypeScript)
  ↕ Vapi Web SDK (voice in/out)
  ↕ context (active file, selection, git remote)
        ↓
FastAPI Backend (Python)
  ├── Vapi webhook handler
  ├── Qdrant (semantic search)
  │     ├── codebase_chunks
  │     ├── documentation
  │     ├── error_patterns
  │     └── conversation_memory
  ├── OpenAI (embeddings + synthesis)
  ├── GitHub API (PRs, CI, commits)
  ├── Redis (session memory)
  └── Executor (patch, test, git)
```

---

## Hackathon demo script

1. Open the sample repo in VS Code — panel opens automatically
2. Index the workspace (pre-run this before the demo)
3. Open a file with a deliberate bug
4. Press `Ctrl+Shift+V` — speak: *"I'm getting a null reference error in the webhook handler, what's causing it?"*
5. Agent explains the bug
6. Agent offers: *"Want me to fix this?"* — say *"Yes"*
7. Diff appears in the panel — agent applies the patch
8. Say *"Run the tests"* — agent runs pytest, speaks results
9. Say *"Commit this and open a PR, assign to Alice"* — PR opens on GitHub
10. 🎤 Done. Judges applaud.
