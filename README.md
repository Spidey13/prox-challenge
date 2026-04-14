# Vulcan OmniPro 220 — Technical Support Agent

A multimodal technical support agent for the **Vulcan OmniPro 220** multiprocess welder. Ask it anything — duty cycle calculations, polarity setup, wire feed settings, troubleshooting — and it responds with precise answers, interactive HTML artifacts, and highlighted manual images. Upload a photo of your weld bead or machine screen for visual diagnosis.

## Quick Start (clone and run)

```bash
git clone <repo>
cd prox-challenge

# 1 — Set your Anthropic key (only credential required to run)
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY=sk-ant-...

# 2 — Install Python dependencies
pip install -r requirements.txt
# (sentence-transformers model ~80MB, downloads on first run)

# 3 — Start the backend (chroma_db/ ships pre-built — no ingestion needed)
uvicorn main:app --reload --port 8080

# 4 — Start the frontend
cd frontend && npm install && npm run dev
# → http://localhost:5173
```

> No Google Cloud credentials required to run the agent. GCP is only needed if you want to **re-ingest** the PDFs from scratch.

---

## Architecture

```
PDF manuals (files/)
      │
      ▼
 ingest.py  (Gemini 2.5 Flash vision + structured extraction)
                  │ Vertex text-embedding-004 (ingestion only)
                  ▼
            chroma_db/   ← shipped in repo (all-MiniLM-L6-v2 embeddings)
                  │
                  ▼
 agent.py   (Anthropic tool_use agentic loop)
            ├─ Haiku  — agentic loop + text answers
            └─ Sonnet — interactive HTML artifact generation
                  │
                  ▼
 main.py    (FastAPI + Server-Sent Events streaming)
                  │
                  ▼
 frontend/  (React + Vite — two-panel chat + artifact viewer)
```

---

## Agent Architecture — Claude's tool_use Agentic Loop

This agent is built on **Claude's native `tool_use` mechanism** — the actual agentic primitive provided by Anthropic. There is no separate "Agent SDK" package; the agentic loop *is* the `tool_use` pattern.

### The canonical agentic loop (from [Anthropic's documentation](https://docs.anthropic.com/en/docs/build-with-claude/tool-use))

```python
response = client.messages.create(model=..., tools=tools, messages=messages)

while response.stop_reason == "tool_use":
    # Extract tool call(s) from the response
    # Execute each tool locally
    # Append tool_result(s) back into messages
    response = client.messages.create(...)  # next iteration
# stop_reason == "end_turn" → final answer
```

Our `SupportAgent.ask_streaming()` implements exactly this pattern:

1. **Initial call** — Claude sees the user's question (and optional image) plus tool definitions
2. **Tool loop** — while `stop_reason == "tool_use"`, execute tools and feed results back
3. **Streaming synthesis** — after `end_turn`, stream Claude's final answer via `messages.stream()` so tokens arrive live

### Tools defined

| Tool | What it does |
|------|-------------|
| `search_knowledge` | Vector search over ingested manual chunks (ChromaDB + all-MiniLM-L6-v2) |
| `get_manual_image` | Fetches rendered manual page PNG URL + optional highlight bbox |
| `render_artifact` | Calls Sonnet to generate self-contained interactive HTML |

### Model assignments

| Role | Model | Credentials |
|------|-------|-------------|
| Agentic loop + text answers | Claude Haiku 4.5 (direct Anthropic API) | `ANTHROPIC_API_KEY` |
| HTML artifact generation | Claude Sonnet 4.5 (direct Anthropic API) | `ANTHROPIC_API_KEY` |
| PDF ingestion vision + structured extraction | Gemini 2.5 Flash (Vertex AI) | GCP only for ingestion |
| Ingestion embeddings | `text-embedding-004` (Vertex AI) | GCP only for ingestion |
| **Query-time embeddings** | **`all-MiniLM-L6-v2` (local, CPU)** | **None — ships in repo** |

### Embedding strategy

The `chroma_db/` directory is **shipped pre-built** in this repository. All 316 knowledge chunks are embedded with `sentence-transformers/all-MiniLM-L6-v2` (384-dim, ~80 MB, runs on CPU). This means:

- **Reviewers**: set only `ANTHROPIC_API_KEY` → clone → run ✅
- **Ingestion** (if re-building from PDFs): requires GCP credentials + Vertex AI; run `migrate_embeddings.py` afterward to convert to local embeddings

---

## Key Design Decisions

- **Deterministic image bboxes**: `pymupdf page.get_image_info()` gives exact bounding boxes with no LLM needed — Gemini only captions inside those regions.
- **Percentage-based coordinates**: bboxes stored as `{x,y,w,h}` fractions of page dimensions so the frontend overlay works at any CSS size.
- **Chunk-type routing**: queries are classified into "structured-first", "vision-first", or "text-first" retrieval before hitting ChromaDB.
- **Idempotent ingestion**: chunk IDs are MD5 hashes of `product_id + page + type + index` — re-running ingestion upserts without creating duplicates.
- **Fallback chain**: `render_artifact` retries Sonnet with a simplified prompt, then falls back to a hardcoded HTML table — never returns empty.
- **Dual-mode embeddings**: Vertex `text-embedding-004` at ingest time (highest quality); local `all-MiniLM-L6-v2` at query time (no API key required).
- **Real streaming**: tool loop runs synchronously (tool calls must complete); final synthesis uses `messages.stream()` so tokens appear immediately.

---

## Image Input Support

The `/ask` endpoint accepts an optional base64-encoded image alongside the text query:

```json
POST /ask
{
  "message": "Why is my weld bead so porous?",
  "product_id": "vulcan_220",
  "conversation_id": "...",
  "image_data": "<base64 string>",
  "image_media_type": "image/jpeg"
}
```

Claude receives the image as a vision content block and can describe what it sees, identify the welding process, spot setup errors, and cross-reference with the manual knowledge base.

The frontend chat input includes a 📎 attach button with an inline image preview.

---

## Setup (Full Ingestion from Scratch)

> Only needed if you want to re-ingest the PDFs. The shipped `chroma_db/` already contains all embeddings.

### Prerequisites

- Python 3.11+, Node 18+
- A Google Cloud project with:
  - **Vertex AI API** enabled
  - Application Default Credentials: `gcloud auth application-default login`

### 1. Configure environment

```bash
cp .env.example .env
# Set ANTHROPIC_API_KEY and GOOGLE_CLOUD_PROJECT
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Ingest the manuals

```bash
python run_ingest.py vulcan_220
```

### 4. Migrate embeddings to local model (required after ingestion)

```bash
python migrate_embeddings.py --product-id vulcan_220
```

### 5. Start the services

```bash
uvicorn main:app --reload --port 8080
cd frontend && npm install && npm run dev
```

---

## Docker (demo deployment)

```bash
docker build -t vulcan-agent .
docker run -p 8080:8080 -e ANTHROPIC_API_KEY=sk-ant-... vulcan-agent
```

> `chroma_db/` and `assets/` are copied into the image. No GCP credentials needed at runtime.

---

## Deploy to Cloud Run + Vercel

**Backend (Cloud Run):**
```bash
gcloud run deploy vulcan-agent \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars ANTHROPIC_API_KEY=sk-ant-...,FRONTEND_URL=https://your-app.vercel.app
```

**Frontend (Vercel):**
```bash
cd frontend
vercel --prod
# Set VITE_API_URL env var in Vercel dashboard to your Cloud Run URL
```
