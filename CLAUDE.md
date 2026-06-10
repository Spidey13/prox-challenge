# CLAUDE.md — Diagnostiq

Project brain for Claude Code. Read this before editing. These instructions
override default behavior.

## What this is

**Diagnostiq** — a multimodal technical-support agent for the **Trane Precedent
Rooftop Unit** (HVAC). Built directly on Anthropic's `tool_use` loop — no
LangChain, no AutoGen. This directory (`diagnostiq/`) is its own Git repo;
all work happens here.

> Note: the agent is product-agnostic; products live in `products.json`. Some
> very old strings may still reference a "Vulcan OmniPro 220 welder" — that's
> stale template copy; the real product is the Trane Precedent RTU.

## Commands

Run from `diagnostiq/`. Python 3.11+, managed with `uv`.

```bash
# Backend (chroma_db/ ships pre-built — no ingestion needed to serve)
uv run pip install -r requirements.txt
uv run uvicorn main:app --reload --port 8080

# Frontend
cd frontend && npm install && npm run dev      # → http://localhost:5173
npm run build                                   # → frontend/dist/ (FastAPI serves in prod)

# Tests
uv run pytest tests/                            # unit
uv run pytest tests/test_fence_strip.py -v      # single file
python tests/smoke_test.py                      # API/tool-loop smoke
python tests/eval.py                            # current HTTP eval (server must be running)
```

Only `ANTHROPIC_API_KEY` is required to serve. `GOOGLE_CLOUD_PROJECT` is needed
**only** to re-run ingestion (`ingest.py` → Gemini vision + Vertex embeddings).

## Architecture

```
PDF manuals (files/) → ingest.py (Gemini 2.5 Flash vision + Vertex text-embedding-004)
   → chroma_db/ (shipped in repo; re-embedded to local all-MiniLM-L6-v2)
   → agent.py (Anthropic tool_use loop: Haiku drives, Sonnet codegen)
   → main.py (FastAPI + SSE /ask + SPA hosting)
   → frontend/ (React 19 + Vite, two-panel chat + artifact viewer)
```

| File | Responsibility |
|------|----------------|
| `main.py` | FastAPI; `/ask` SSE stream, `/ingest`, `/image/…`, SPA fallback |
| `agent.py` | `SupportAgent` — sync tool loop + streaming synthesis |
| `config.py` | `Config` + `ProductInfo`/`_registry` loaded from `products.json` |
| `cache.py` | `SemanticCache` — exact-match query cache |
| `session.py` | Thread-safe in-memory conversation history |
| `ingest.py` | `Ingester` — per-PDF/per-page pipeline (GCP-only) |

Models are referenced as `config.haiku` / `config.sonnet` (current defaults:
Haiku 4.5, Sonnet 4.5). Don't hardcode model IDs — read them from `config`.

## Invariants — do not break these

1. **Output modes & routing.** Three outputs: plain text, `render_artifact`
   (Sonnet → self-contained HTML), and `generate_job_card` (Sonnet → validated
   JSON). Haiku decides intent *before* tool calls: fault/diagnosis/maintenance
   → job card; settings/specs/how-to → artifact; simple → text.

2. **Cache key contract** (`cache.py:make_key`). Structured fault queries key on
   `"{product_id}:{fault_category}"` (deterministic across sessions); everything
   else falls back to the raw query string. Don't change this key shape without
   updating both callers and the eval harness.

3. **2-call budget / fast path.** `ask_streaming(intent_known=True, fault_category=…)`
   skips Haiku entirely (1 API call total). Preserve this path — it's the cost
   guarantee.

4. **Job-card hallucination guard (CRITICAL).** Sonnet may only emit a step it
   can back with a `source_citation` from retrieved chunks. No retrieved content
   = no step. Enforce in the **system prompt**, not post-processing.

5. **SSE streaming contract.** `ask_streaming()` is a sync generator yielding
   `(event_type, payload)`: `token`, `job_card_start`, `job_card_step`, `done`.
   The `done` payload keys are `answer, suggestions, artifact, job_card, images`.
   Job cards stream metadata first, then steps progressively. `main.py` bridges
   the sync generator → async SSE via a `queue.Queue`. Don't make `ask_streaming`
   async or reorder these events.

6. **Dual-embedding alignment.** Ingestion = Vertex `text-embedding-004` (768d);
   serving = local `all-MiniLM-L6-v2` (384d). Query and document vectors must
   always use the same model. Never mix.

7. **Products live in `products.json`, not code.** Adding a product = a JSON
   entry + PDFs in its `pdf_directory`. No code change.

## What NOT to touch without explicit ask

- The existing `render_artifact` flow (job cards are additive, must not regress it).
- The SSE event ordering / `done` payload shape.
- `chroma_db/` (shipped, pre-built) — re-ingestion requires GCP creds.
- The dual-embedding model pairing.

## Conventions

- Match surrounding style; the codebase favors typed dataclasses, module-level
  docstrings, and small focused helpers.
- Tool iterations are capped (`_MAX_TOOL_ITERATIONS = 5`; 3 after a job-card call).
- Rate-limit retries: `_with_retry` (13s base, 4 retries, exponential backoff).

## Working style (for Claude Code sessions)

- **Plan first** for anything touching `agent.py`, `cache.py`, or the routing /
  output-mode logic. Use plan mode; get the plan reviewed before writing.
- **Verify with evidence.** After changing `agent.py`, run the relevant test and
  show the actual output — don't assert success.
- Prefer reusing existing helpers (`SemanticCache.make_key`, `_with_retry`,
  `_tool_search_knowledge`, the assertion helpers in `tests/eval.py`).

## Current workstream — eval harness

Building a headless + pytest eval harness (retrieval recall + structural checks +
one binary LLM-judge faithfulness layer). Plan:
`C:\Users\prath\.claude\plans\glistening-rolling-garden.md`.

Phase 0 prerequisite: `ask_streaming()` discards `_tool_search_knowledge` results;
expose a `retrieval_trace` in every `done` payload so retrieval can be graded.
This is safe — headless reads the generator directly, so `main.py`/SSE need no
change.
