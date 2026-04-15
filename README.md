
## CodeMate — Voice-Native Pair Programmer

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
cp .env
pip install -r requirements.txt

# Start the server
python3 -m uvicorn main:app --port 8000
# → Running at http://localhost:8000
```

### Step 3 — Expose backend to Vapi (for webhooks) - optional

```bash
# Install ngrok: https://ngrok.com/download
ngrok http 8000
# → Copy the https URL e.g. https://abc123.ngrok.io
```

### Step 4 — Create your Vapi Assistant

- Setup Vapi assistant as given in the file  VAPI_ASSISTANT_CONFIG.md
- Copy your **Assistant ID**

### Step 5 — Install and launch the VS Code extension

```bash
cd extension
npm install
npm run compile
```

Then in VS Code:
1. Open the `extension` folder.
2. Open the Run & Debug panel.
3. Start debugging with `Launch Extension`.
4. This opens a new Extension Development Host window.

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
