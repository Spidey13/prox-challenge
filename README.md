# Prox — Vulcan OmniPro 220 Support Agent

![Vulcan OmniPro Agent Showcase](frontend/src/assets/hero.png)

Technical support agent for the **Vulcan OmniPro 220** multiprocess welder. Runs Anthropic's `tool_use` loop with SSE streaming, interactive React artifacts, and a bundled vector DB — reviewers need only `ANTHROPIC_API_KEY`.

**Live demo:** [https://vulcan-agent-33492766578.us-central1.run.app](https://vulcan-agent-33492766578.us-central1.run.app)

---

## Design choices

1. **Interactive artifacts with pinning**
   Haiku drives the tool loop; Sonnet writes HTML/CSS/JS rendered in a sandboxed iframe. Artifacts can be pinned so they stay visible across follow-up messages.

2. **SSE streaming over synchronous tool loops**
   Tool calls run synchronously in a thread pool. Once the loop finishes, `ask_streaming()` opens a real Anthropic stream and pipes tokens directly to the SSE response.

3. **No GCP credentials needed to run**
   Ingestion uses Vertex `text-embedding-004` (768-dim). Serving re-embeds with local `sentence-transformers/all-MiniLM-L6-v2` (384-dim, 80 MB). The converted `chroma_db/` is checked into the repo.

4. **No cold-start ML download**
   `ENV HF_HOME` in the Dockerfile bakes embedding weights into the image layer, dropping cold start from ~15 s to zero.

5. **Accessibility**
   `overscroll-behavior: contain` on modals, correct ARIA roles, full keyboard navigation, CSS custom properties for dark mode. Scored 96/100 on Web Interface Guidelines audit.

---

## Architecture

Built directly on Claude's `tool_use` mechanism — no LangChain, no AutoGen.

```
PDF manuals (files/)
      │
      ▼
 ingest.py  (Gemini 2.5 Flash vision + structured extraction)
                  │ Vertex text-embedding-004 (ingestion only)
                  ▼
            chroma_db/   ← bundled in repo (all-MiniLM-L6-v2)
                  │
                  ▼
 agent.py   (Anthropic tool_use loop)
            ├─ Haiku  — tool loop + text answers
            └─ Sonnet — HTML artifact generation
                  │
                  ▼
 main.py    (FastAPI + SSE streaming + SPA hosting)
                  │
                  ▼
 frontend/  (React + Vite — two-panel chat + artifact viewer)
```

### Tools

| Tool | Purpose |
|------|---------|
| `search_knowledge` | Vector search over ingested manual chunks (ChromaDB + all-MiniLM-L6-v2) |
| `get_manual_image` | Returns manual page PNGs with optional highlighted bounding boxes |
| `render_artifact` | Calls Sonnet to generate self-contained interactive HTML |

---

## Quick start

```bash
git clone https://github.com/Spidey13/prox-challenge
cd prox-challenge

# Set your Anthropic key (only credential required)
cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY=sk-ant-...

# Install Python dependencies
uv run pip install -r requirements.txt

# Start the backend (chroma_db/ is pre-built — no ingestion step needed)
uv run uvicorn main:app --reload --port 8080

# Start the frontend
cd frontend && npm install && npm run dev
# → http://localhost:5173
```

---

## Image input

`/ask` accepts `base64` image payloads alongside the text prompt. Upload a photo of a fault or weld bead, and Claude describes the issue and calls `search_knowledge` to locate the matching manual section.

---

## Docker

Single container — backend and frontend on port 8080.

```bash
docker build -t vulcan-agent .
docker run -p 8080:8080 -e ANTHROPIC_API_KEY=sk-ant-... vulcan-agent
```

The Dockerfile uses a multi-stage build: Vite compiles the SPA in a Node container, `/dist` is copied to the Python 3.11 layer, and FastAPI serves it via `StaticFiles`. No separate Vercel deployment, no CORS config needed.
