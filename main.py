"""FastAPI application — multi-product technical support agent."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agent import SupportAgent
from cache import SemanticCache
from config import config
from ingest import Ingester, ingest_product
from session import SessionStore

log = logging.getLogger(__name__)

app = FastAPI(title="Product Support Agent", version="2.0.0")

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

_origins = ["http://localhost:5173"]
_frontend_url = os.getenv("FRONTEND_URL", "").strip()
if _frontend_url:
    _origins.append(_frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Singletons (created once on startup)
# ---------------------------------------------------------------------------

_session_store = SessionStore()
_cache = SemanticCache()
_agent: SupportAgent | None = None


def _get_agent() -> SupportAgent:
    global _agent
    if _agent is None:
        _agent = SupportAgent()
    return _agent

@app.on_event("startup")
async def startup_event():
    # Pre-warm the agent and ML models so the first request doesn't hang
    log.info("Pre-warming SupportAgent and loading ML models...")
    _get_agent()
    log.info("ML models and agent initialized.")


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class IngestRequest(BaseModel):
    product_id: str
    pdf_path: str | None = None  # if omitted, auto-discover all PDFs via product registry
    fresh: bool = False           # if True, clear existing data before ingesting


class AskRequest(BaseModel):
    message: str
    product_id: str
    conversation_id: str
    image_data: str | None = None        # base64-encoded image (optional)
    image_media_type: str | None = None  # e.g. "image/jpeg", "image/png"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


@app.post("/ingest")
async def ingest(req: IngestRequest) -> dict:
    """Run the PDF ingestion pipeline (blocking — run once or on demand).

    If pdf_path is provided, ingests that single PDF.
    If pdf_path is omitted, discovers all PDFs via the product registry.
    Set fresh=true to clear existing data and re-ingest from scratch.
    """
    loop = asyncio.get_event_loop()

    if req.pdf_path:
        # Single-PDF mode (backward-compatible)
        ingester = Ingester(product_id=req.product_id, pdf_path=req.pdf_path)
        report = await loop.run_in_executor(None, ingester.run)
        return {
            "status": "ok",
            "mode": "single",
            "chunks_written": report["chunks_written"],
            "pages_processed": report["pages_processed"],
            "annotations_saved": report["annotations_saved"],
        }
    else:
        # Multi-PDF mode: ingest all docs in product.pdf_directory
        reports = await loop.run_in_executor(
            None, lambda: ingest_product(req.product_id, fresh=req.fresh)
        )
        return {
            "status": "ok",
            "mode": "multi",
            "documents": len(reports),
            "chunks_written": sum(r["chunks_written"] for r in reports),
            "pages_processed": sum(r["pages_processed"] for r in reports),
            "annotations_saved": sum(r["annotations_saved"] for r in reports),
        }


@app.post("/ask")
async def ask(req: AskRequest) -> EventSourceResponse:
    """Stream agent response via Server-Sent Events.

    Event types emitted:
      ``{"type": "token",  "content": "..."}``   — streaming text tokens
      ``{"type": "done",   "suggestions": [...],
          "artifact": {...}|null,
          "images": [...]}``                      — final metadata
    """
    agent = _get_agent()

    # Check exact-match cache first
    cached = _cache.get(req.message)
    if cached:
        cached_data = json.loads(cached)
        async def cached_stream():
            # Stream the answer word-by-word so the UI still animates
            for word in cached_data.get("answer", "").split(" "):
                yield {"data": json.dumps({"type": "token", "content": word + " "})}
            yield {"data": json.dumps({
                "type": "done",
                "suggestions": cached_data.get("suggestions", []),
                "artifact": cached_data.get("artifact"),
                "images": cached_data.get("images", []),
            })}
        return EventSourceResponse(cached_stream())

    _session_store.append(req.conversation_id, "user", req.message)
    history = _session_store.get(req.conversation_id)
    # Exclude the message we just appended from history passed to agent
    history_without_latest = history[:-1]

    async def event_stream():
        try:
            # Run the streaming agent in a thread pool.
            # ask_streaming() is a synchronous generator — we collect events
            # from it inside run_in_executor so the event loop stays free.
            loop = asyncio.get_event_loop()

            # Wrap the synchronous generator in a queue so we can bridge
            # the thread-pool world into async.
            import queue as _queue
            q: _queue.Queue = _queue.Queue()
            _SENTINEL = object()

            def _run_generator():
                try:
                    for event_type, payload in agent.ask_streaming(
                        query=req.message,
                        product_id=req.product_id,
                        history=history_without_latest,
                        image_data=req.image_data,
                        image_media_type=req.image_media_type,
                    ):
                        q.put((event_type, payload))
                except Exception as exc:
                    q.put(("error", str(exc)))
                finally:
                    q.put(_SENTINEL)

            # Run the blocking generator in a thread.
            loop.run_in_executor(None, _run_generator)

            answer_accumulated = ""
            while True:
                # Poll the queue; yield control to the event loop between polls.
                try:
                    item = q.get_nowait()
                except _queue.Empty:
                    await asyncio.sleep(0.01)
                    continue

                if item is _SENTINEL:
                    break

                event_type, payload = item

                if event_type == "token":
                    answer_accumulated += payload
                    yield {"data": json.dumps({"type": "token", "content": payload})}

                elif event_type == "done":
                    answer = payload.get("answer", "")
                    # Append assistant turn to session
                    _session_store.append(req.conversation_id, "assistant", answer)
                    # Cache the full result for exact-match future hits
                    _cache.set(req.message, json.dumps({
                        "answer": answer,
                        "suggestions": payload.get("suggestions", []),
                        "artifact": payload.get("artifact"),
                        "images": payload.get("images", []),
                    }))
                    yield {"data": json.dumps({
                        "type": "done",
                        "suggestions": payload.get("suggestions", []),
                        "artifact": payload.get("artifact"),
                        "images": payload.get("images", []),
                    })}

                elif event_type == "error":
                    yield {"data": json.dumps({
                        "type": "done",
                        "suggestions": [],
                        "artifact": None,
                        "images": [],
                        "error": payload,
                    })}

        except Exception as exc:
            log.exception("Agent error: %s", exc)
            yield {"data": json.dumps({
                "type": "done",
                "suggestions": [],
                "artifact": None,
                "images": [],
                "error": str(exc),
            })}

    return EventSourceResponse(event_stream())



@app.get("/image/{product_id}/{doc_slug}/{page_number}")
async def get_image(product_id: str, doc_slug: str, page_number: int) -> FileResponse:
    """Serve a rendered page PNG with a 1-hour cache header.

    Assets are stored at assets/{product_id}/pages/{doc_slug}/page_{page_number}.png
    """
    path = (
        Path(config.assets_path)
        / product_id
        / "pages"
        / doc_slug
        / f"page_{page_number}.png"
    )
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(
        str(path),
        media_type="image/png",
        headers={"Cache-Control": "max-age=3600"},
    )


@app.get("/annotations/{product_id}/{doc_slug}/{page_number}")
async def get_annotations(
    product_id: str, doc_slug: str, page_number: int
) -> JSONResponse:
    """Serve the annotation JSON for a page."""
    path = (
        Path(config.assets_path)
        / product_id
        / "annotations"
        / doc_slug
        / f"page_{page_number}.json"
    )
    if not path.exists():
        raise HTTPException(status_code=404, detail="Annotations not found")
    return JSONResponse(json.loads(path.read_text()))


@app.get("/documents/{product_id}")
async def list_documents(product_id: str) -> JSONResponse:
    """List all ingested documents (doc_slugs) for a product."""
    pages_dir = Path(config.assets_path) / product_id / "pages"
    if not pages_dir.exists():
        return JSONResponse({"product_id": product_id, "documents": []})
    slugs = sorted(d.name for d in pages_dir.iterdir() if d.is_dir())
    docs = []
    for slug in slugs:
        page_count = len(list((pages_dir / slug).glob("page_*.png")))
        docs.append({"doc_slug": slug, "page_count": page_count})
    return JSONResponse({"product_id": product_id, "documents": docs})


# ---------------------------------------------------------------------------
# Frontend — serve the built React app (frontend/dist/) as static files.
# Must be mounted AFTER all API routes so the API takes priority.
# ---------------------------------------------------------------------------

_FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    # Serve JS/CSS/images under /assets (Vite's default output path)
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="vite-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Return index.html for any path not matched by an API route.

        The React router handles client-side navigation; every URL that
        doesn't map to a file on disk should serve index.html.
        """
        index = _FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(str(index))
        raise HTTPException(status_code=404, detail="Frontend not built")
else:
    log.warning(
        "frontend/dist/ not found — React UI not available. "
        "Run 'cd frontend && npm run build' to build the frontend."
    )
