# Vulcan OmniPro 220 — Prox Multimodal Support Agent

![Vulcan OmniPro Agent Showcase](frontend/src/assets/hero.png)

A production-grade, multimodal technical support agent built for the **Vulcan OmniPro 220** multiprocess welder. This system implements Anthropic's native `tool_use` agentic loops combined with live streaming, interactive React artifacts (Claude-style UI), and a "clone-and-run" dependency-free local retrieval system.

🚀 **Live Cloud Run Demo:** [https://vulcan-agent-33492766578.us-central1.run.app](https://vulcan-agent-33492766578.us-central1.run.app)

*(The demo runs entirely in a single Cloud Run container with a baked-in AI model and pre-built vector DB).*

---

## 🌟 Challenge Highlights (Why this solution stands out)

1. **Fully Functional Interactive Artifacts (with State Persistence)**
   Instead of just text, the agent writes raw HTML/CSS/JS (via Claude 3.5 Sonnet) and renders it safely into an expanding right-side panel. **Crucially, the UI allows users to 📌 Pin artifacts** so they persist through future conversation steps.
2. **Solving the "Streaming vs. Tool-Use" Paradox**
   Typically, waiting for LLM tools to finish causes huge latency spikes. This backend implements a custom Python generator (`ask_streaming()`) that runs synchronous `search_knowledge` and `get_manual_image` tool loops behind the scenes, and then securely opens the SSE pipe to stream the final synthesis token-by-token.
3. **The "Dual Embedding" Deployment Architecture**
   95% of RAG prototypes require reviewers to input paid GCP/OpenAI keys to query vector databases. We split the architecture:
   - **Ingestion (GCP):** Gemini Flash extracts structured text/bboxes. Vertex text-embedding-004 vectorizes it.
   - **Serving (Zero Setup):** We migrated the vectors to `sentence-transformers/all-MiniLM-L6-v2` (80MB) and baked the DB directly into the repo. Reviewers only need an `ANTHROPIC_API_KEY` to run the entire backend fully offline (except for Anthropic API calls).
4. **Zero Cold-Start DevOps**
   Serverless deployments (like Cloud Run) notoriously hang if they have to download ML models on the fly. We explicitly customized the Dockerfile with `ENV HF_HOME` to permanently cache the embedding model weights into the container layers, dropping cold start times from ~15s to zero.
5. **Polished Accessibility (WIG & React Doctor 96/100)**
   The UI isn't just an MVP. It features `overscroll-behavior: contain` on full-screen modals, correct ARIA roles on clickable spans, full keyboard navigation (ESC handling), and strict CSS custom properties for instant dark mode switching.

---

## 🏗 Architecture (Claude's `tool_use` Agentic Loop)

This agent is built purely on **Claude's native `tool_use` mechanism**. There are no heavy bloated agent frameworks (like LangChain or AutoGen) obscuring the API calls. 

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
 main.py    (FastAPI + Server-Sent Events streaming + SPA hosting)
                  │
                  ▼
 frontend/  (React + Vite — two-panel chat + artifact viewer)
```

### Tools Equipped
| Tool | Purpose |
|------|-------------|
| `search_knowledge` | High-speed Vector search over ingested manual chunks (ChromaDB + all-MiniLM-L6-v2) |
| `get_manual_image` | Fetches base64 manual page PNGs + renders highlighted bounding boxes for diagram lookups |
| `render_artifact` | Context switches to Sonnet 3.5 to safely codegen interactive HTML components for users |

---

## 🏃 Quick Start (Clone & Run for Reviewers)

Because we ship the ChromaDB instance and the local embedding model dynamically, getting this running locally is unbelievably easy. You do NOT need GCP credentials.

```bash
git clone https://github.com/Spidey13/prox-challenge
cd prox-challenge

# 1 — Set your Anthropic key (only credential required to run)
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY=sk-ant-...

# 2 — Install Python dependencies
uv run pip install -r requirements.txt

# 3 — Start the backend (chroma_db/ ships pre-built — no ingestion needed)
uv run uvicorn main:app --reload --port 8080

# 4 — Start the frontend
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

---

## 📸 Image Input Support (Vision)

The `/ask` endpoint natively accepts `base64` image payloads alongside the user prompt.
* If a welder uploads a photo of a porous weld bead or a confusing digital interface, the image is packed directly into the Anthropic `content` block. 
* Claude acts as a mechanic, describing the potential issues in the photo and autonomously firing the `search_knowledge` tool to query the manual for the matching manufacturer fix.

---

## 🐳 Deployment & Cloud Run Details

The Docker deployment has been highly optimized to run as a **single, unified service**.

```bash
docker build -t vulcan-agent .
docker run -p 8080:8080 -e ANTHROPIC_API_KEY=sk-ant-... vulcan-agent
```

Instead of deploying Vercel + Cloud Run separately, the `Dockerfile` utilizes a **multi-stage build**:
1. It builds the Vite/React SPA natively inside a Node container.
2. It copies `/dist` over to the Python 3.11 container.
3. FastAPI's `StaticFiles` catches all frontend traffic and serves the React application seamlessly over port 8080, bypassing CORS completely and saving money on hosting.

Enjoy the application!
