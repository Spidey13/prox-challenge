"""Multi-product support agent — Anthropic tool_use agentic loop.

Claude decides which tools to call. We execute them and feed results back.
The loop runs until stop_reason != "tool_use" (end_turn, max_tokens, etc.).

Model assignments:
  Haiku  — agent loop (query rewriting implicitly via system prompt + context)
  Sonnet — render_artifact HTML codegen AND generate_job_card JSON generation
  Gemini — ingestion only (see ingest.py; NOT called from this module)

Rate limit: Free tier is 5 RPM across all models. Every messages.create()
call is wrapped with exponential-backoff retry on RateLimitError.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import anthropic
import chromadb
from sentence_transformers import SentenceTransformer

from config import ProductInfo, _registry, config, get_product

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_TOOL_ITERATIONS = 8       # enough for ~5 searches + image + job_card/artifact
_RETRY_BASE_SECS     = 13.0    # 60s / 5 RPM + 1s buffer
_MAX_RETRIES         = 4

# System prompt for HTML artifact generation.
# Mirrors the Claude Artifacts text/html contract: single-file, inline only,
# full document wrapper required so _wrap_html_fragment never needs to act.
_HTML_SYSTEM_PROMPT = (
    "You generate self-contained HTML applications that render correctly in an iframe srcDoc.\n"
    "Rules:\n"
    "1. Output a COMPLETE HTML document starting with <!DOCTYPE html> and ending with </html>.\n"
    "2. All CSS must be inside a <style> tag in <head>.\n"
    "3. All JavaScript must be inside a <script> tag before </body>.\n"
    "4. No external dependencies, no CDN imports, no remote images, no fetch() calls.\n"
    "5. Do NOT wrap the output in markdown code fences (no ```html ... ```).\n"
    "6. Output ONLY the HTML document. No explanation before or after it."
)

# ---------------------------------------------------------------------------
# System prompt template (filled per-query with product metadata)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are the technical support expert for the {product_name}. \
You have deep knowledge of its {product_description}.

{product_persona}

TOOL RULES — follow strictly:
1. ALWAYS call search_knowledge first before answering any technical \
   question. Never answer from memory alone.
2. After search_knowledge returns, choose output type by query intent:
   FAULT/DIAGNOSIS — any query describing a symptom, malfunction, or failure \
     mode. Triggers: "not working", "won't", "stops", "error", "fault", \
     "problem", "maintenance", "unstable", "tripping", "overheating", {fault_triggers}, \
     or any question asking "why is X happening" or "how do I fix". \
     → call generate_job_card IMMEDIATELY after search_knowledge. \
     Do NOT call get_manual_image before generate_job_card for fault queries. \
     Set fault_description to the user's exact phrasing. \
     Set context to the 3 most relevant search result texts joined with newlines. \
     Examples: {fault_examples}
   SETTINGS/SPECS/VISUAL — user explicitly asks for a diagram, table, \
     spec reference, or uses "show me". Triggers: "settings", \
     "wiring", "terminal", "pinout", "connector", "diagram", "show me", \
     "what is the setting for", "layout", "table", "reference", "LED code", \
     "flash code", "fault code lookup". \
     → call render_artifact with the appropriate artifact_type from: {artifact_types}. \
     Do NOT answer wiring/LED code/terminal queries in plain text — always use render_artifact.
   PLAIN KNOWLEDGE — factual lookup with no fault and no visual needed. \
     → call get_manual_image only if the user asks for something visual, \
     then answer in plain text.
   Never call both generate_job_card and render_artifact in one turn. \
   When in doubt between fault and knowledge, prefer generate_job_card.
3. For truly ambiguous questions with no symptom ("it's not working" alone), \
   ask ONE clarifying question in plain text without calling any tools.
4. Never invent specifications. If search_knowledge returns nothing \
   useful, say "I don't see that in the manual" and cite the closest \
   page found.
5. get_manual_image is ONLY for visual/layout questions. Never call it \
   for fault diagnosis — generate_job_card handles those entirely.

RESPONSE FORMAT:
After all tool calls are done, write your answer as plain prose. \
End with exactly this block (no extra text before or after the dashes):

---SUGGESTIONS---
1. <first follow-up question>
2. <second follow-up question>
3. <third follow-up question>
---END---
"""


def _build_system_prompt(product: "ProductInfo") -> str:
    fault_triggers = ", ".join(f'"{t}"' for t in product.fault_triggers) if product.fault_triggers else '"failure", "issue", "broken"'
    fault_examples = "\n     ".join(product.fault_examples) if product.fault_examples else '"unit not working" → job card.'
    artifact_types = ", ".join(product.artifact_types.keys()) if product.artifact_types else "wiring_diagram, settings_configurator"
    return _SYSTEM_PROMPT_TEMPLATE.format(
        product_name=product.name,
        product_description=product.description,
        product_persona=product.persona,
        fault_triggers=fault_triggers,
        fault_examples=fault_examples,
        artifact_types=artifact_types,
    )


# ---------------------------------------------------------------------------
# Tool definitions (JSON Schema, passed to Claude in each request)
# ---------------------------------------------------------------------------

def _build_tools(product_id: str) -> list[dict]:
    """Return tool schema with the correct product_id default."""
    # Load artifact types from product registry for this product
    try:
        _product = get_product(product_id)
        artifact_type_keys = list(_product.artifact_types.keys())
        artifact_type_names = ", ".join(artifact_type_keys)
    except Exception:
        artifact_type_keys = ["wiring_diagram", "settings_configurator"]
        artifact_type_names = "wiring_diagram, settings_configurator"

    return [
        {
            "name": "search_knowledge",
            "description": (
                f"Search the {product_id} knowledge base (all ingested documents). "
                "Returns the most relevant text chunks with page numbers and doc_slug. "
                "Call this before answering any technical question."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Specific technical query to search for.",
                    },
                    "product_id": {
                        "type": "string",
                        "description": f"Product identifier (default: {product_id}).",
                        "default": product_id,
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_manual_image",
            "description": (
                "Return the URL for a rendered manual page image plus an optional "
                "highlight bbox for a specific diagram region. Use this when the "
                "user asks about something visual: a wiring diagram, module layout, "
                "terminal strip, or any 'show me' question. "
                "Use the doc_slug from search results to target the right document."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "default": product_id},
                    "doc_slug": {
                        "type": "string",
                        "description": (
                            "Document slug from search results, e.g. 'owner-manual' or "
                            "'quick-start-guide'. Omit to use the first available document."
                        ),
                    },
                    "page_number": {
                        "type": "integer",
                        "description": "0-indexed page number from the document.",
                    },
                    "highlight_label": {
                        "type": "string",
                        "description": "Optional label to highlight a specific region on the page.",
                    },
                },
                "required": ["page_number"],
            },
        },
        {
            "name": "render_artifact",
            "description": (
                "Generate a self-contained interactive HTML artifact. "
                f"Use for: {artifact_type_names}. "
                "Pass the relevant retrieved context so the artifact contains real data."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "artifact_type": {
                        "type": "string",
                        "enum": artifact_type_keys,
                    },
                    "context": {
                        "type": "string",
                        "description": "Manual data / retrieved chunks to base the artifact on.",
                    },
                    "product_id": {"type": "string", "default": product_id},
                },
                "required": ["artifact_type", "context"],
            },
        },
        {
            "name": "generate_job_card",
            "description": (
                "Generate a structured JSON diagnostic job card for fault diagnosis, "
                "maintenance procedures, or 'not working' queries. "
                "Use ONLY after search_knowledge has returned relevant chunks. "
                "Do NOT use for settings, specs, or visual diagrams — "
                "use render_artifact for those."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "fault_description": {
                        "type": "string",
                        "description": "The fault or symptom exactly as described by the user.",
                    },
                    "context": {
                        "type": "string",
                        "description": (
                            "All relevant text chunks from search_knowledge "
                            "joined as a single string with newlines. "
                            "Use the 3 most relevant chunks only."
                        ),
                    },
                    "product_id": {
                        "type": "string",
                        "default": product_id,
                    },
                },
                "required": ["fault_description", "context"],
            },
        },
    ]


# ---------------------------------------------------------------------------
# Artifact prompts (Sonnet-generated HTML) — product name injected at render time
# ---------------------------------------------------------------------------

_FALLBACK_HTML_PROMPT = (
    "The previous attempt produced unusable output. "
    "Simplify but keep interactivity:\n\n"
    "DATA:\n{context}\n\n"
    "Produce a COMPLETE HTML document with:\n"
    "- A styled header (Fraunces serif, warm-paper palette)\n"
    "- An interactive element (at minimum: clickable rows that highlight, "
    "or a filter/search input)\n"
    "- A data table or list with the content from DATA above\n\n"
    "Warm paper theme: body background #f3ede1, text #1d1a15, accent #d96b2e, "
    "surface #fbf6ea, border #d9cfba, ink-2 #5a5245, mono #8a8275.\n"
    "Import Fraunces + Geist + Geist Mono from Google Fonts in <head>.\n"
    "body font-family: 'Geist', system-ui, sans-serif.\n"
    "Vanilla JS only, no external libraries (Google Fonts link tag is allowed)."
)

# Generic fallback artifact prompts used when a product has no artifact_types defined
_GENERIC_ARTIFACT_PROMPTS: dict[str, str] = {
    "wiring_diagram": (
        "Generate a self-contained HTML page with an SVG wiring diagram "
        "for the {product_name} using this data:\n{context}\n\n"
        "Must show:\n"
        "- Clean SVG schematic of the relevant connections\n"
        "- Labeled terminals and cables\n"
        "- Color-coded by voltage/signal type\n"
        "- A brief text explanation below the diagram\n"
        "No external dependencies. Output ONLY the HTML."
    ),
    "settings_configurator": (
        "Generate a self-contained HTML settings configurator for the "
        "{product_name} using this data:\n{context}\n\n"
        "Must have:\n"
        "- Selectable inputs for relevant parameters from the manual\n"
        "- Output panel showing recommended values from the data\n"
        "- Real-time update as user changes inputs (vanilla JS)\n"
        "No external dependencies. Output ONLY the HTML."
    ),
}


def _build_artifact_prompts(product_name: str, product_id: str | None = None) -> dict[str, str]:
    """Build artifact prompt templates for the given product.

    Loads templates from the product registry if available, otherwise falls
    back to generic templates. Templates use {context} as the data placeholder.
    """
    templates: dict[str, str] = {}

    if product_id:
        try:
            from config import get_product
            product = get_product(product_id)
            if product.artifact_types:
                # Registry templates use {context} directly (no double-brace needed)
                for key, tmpl in product.artifact_types.items():
                    templates[key] = tmpl.replace("{product_name}", product_name)
                return templates
        except Exception:
            pass

    # Generic fallback: substitute product name only
    for key, tmpl in _GENERIC_ARTIFACT_PROMPTS.items():
        templates[key] = tmpl.replace("{product_name}", product_name)
    return templates


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

def _with_retry(fn, *args, **kwargs):
    """Call fn(*args, **kwargs), retrying on RateLimitError with backoff."""
    delay = _RETRY_BASE_SECS
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except anthropic.RateLimitError as exc:
            if attempt == _MAX_RETRIES:
                raise
            log.warning(
                "Rate limit hit (attempt %d/%d), sleeping %.1fs: %s",
                attempt + 1, _MAX_RETRIES, delay, exc,
            )
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
        except anthropic.APIStatusError as exc:
            log.error("Anthropic API error: %s", exc)
            raise


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class SupportAgent:
    """Multi-product support agent using the Anthropic tool_use loop."""

    def __init__(self) -> None:
        self._claude = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self._assets = Path(config.assets_path)

        # Per-product ChromaDB collections, lazily opened on first query.
        self._chroma_collections: dict[str, chromadb.Collection] = {}

        self._embed_model: SentenceTransformer | None = None
        self._chroma_client: chromadb.PersistentClient | None = None
        self._init_retrieval()

    # ------------------------------------------------------------------
    # Retrieval initialisation — local sentence-transformers (no GCP needed)
    # ------------------------------------------------------------------

    def _init_retrieval(self) -> None:
        """Load the local embedding model and open the ChromaDB client.

        Uses sentence-transformers/all-MiniLM-L6-v2 (384-dim, CPU-friendly, ~80 MB).
        No GCP credentials required — works with only ANTHROPIC_API_KEY.
        The chroma_db/ shipped in the repo was migrated to use this model via
        migrate_embeddings.py, so query + document vectors are always aligned.
        """
        try:
            log.info("Loading local embedding model: %s", config.local_embed_model)
            self._embed_model = SentenceTransformer(config.local_embed_model)
            self._chroma_client = chromadb.PersistentClient(path=config.chroma_path)
            log.info("Retrieval ready (local embeddings, no GCP required).")
        except Exception as exc:
            log.warning("Retrieval init failed (agent will run without vector search): %s", exc)

    def _get_chroma_collection(self, product_id: str) -> chromadb.Collection | None:
        """Return (or open) the ChromaDB collection for a product."""
        if self._chroma_client is None:
            return None
        if product_id not in self._chroma_collections:
            try:
                self._chroma_collections[product_id] = (
                    self._chroma_client.get_or_create_collection(
                        name=product_id,
                        metadata={"hnsw:space": "cosine"},
                    )
                )
            except Exception as exc:
                log.warning("Could not open ChromaDB collection %r: %s", product_id, exc)
                return None
        return self._chroma_collections[product_id]

    # ------------------------------------------------------------------
    # Streaming entry point (used by main.py SSE generator)
    # ------------------------------------------------------------------

    def ask_streaming(
        self,
        query: str,
        product_id: str,
        history: list[dict],
        image_data: str | None = None,
        image_media_type: str | None = None,
        fault_category: str | None = None,
        intent_known: bool = False,
    ):
        """Run the agentic tool loop then stream the final synthesis.

        Yields tuples of (event_type, payload):
          ("token",          str)  — a text delta from the streaming response
          ("job_card_start", dict) — job card metadata envelope: {metadata: {...}}
          ("job_card_step",  dict) — one step object from the job card
          ("done",           dict) — final: {suggestions, artifact, job_card, images}

        Pattern:
          1. Run the while-loop synchronously — tool calls must complete before
             we can synthesise the answer.
          2. After the last tool result is appended, open a *streaming* Anthropic
             call with messages.stream().  This yields content_block_delta events
             whose delta.text fields are the live tokens.
          3. After the stream closes, parse suggestions from the accumulated text.
        """
        # ----- resolve product / prompt / tools (same as ask()) -----
        try:
            product = get_product(product_id)
        except KeyError:
            log.warning(
                "Product %r not in registry; using generic system prompt.", product_id
            )
            product = ProductInfo(
                product_id=product_id,
                name=product_id,
                description="technical product",
                pdf_directory="files",
                persona="Be direct, precise, and practical.",
                structured_keywords=(),
            )

        system_prompt = _build_system_prompt(product)
        tools = _build_tools(product_id)
        artifact_prompts = _build_artifact_prompts(product.name, product_id)

        if image_data and image_media_type:
            user_content: str | list = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_media_type,
                        "data": image_data,
                    },
                },
                {"type": "text", "text": query},
            ]
        else:
            user_content = query

        messages: list[dict] = [
            *[{"role": m["role"], "content": m["content"]} for m in history],
            {"role": "user", "content": user_content},
        ]

        images: list[dict] = []
        artifact: dict | None = None
        job_card: dict | None = None

        # ----- intent_known fast path: skip Haiku entirely, 1 API call total -----
        if intent_known and fault_category:
            _sq = fault_category.replace("_", " ")
            _results = self._tool_search_knowledge(
                query=_sq, product_id=product_id
            )[:3]
            _ctx = "\n".join(r.get("text", "") for r in _results)
            job_card = self._tool_generate_job_card(
                fault_description=_sq,
                context=_ctx,
                product_name=product.name,
                artifact_type_keys=list(product.artifact_types.keys()) if product.artifact_types else None,
            )
            yield ("job_card_start", {"metadata": job_card["metadata"]})
            for _step in job_card.get("steps", []):
                yield ("job_card_step", _step)
            yield ("done", {
                "answer": "",
                "suggestions": [],
                "artifact": None,
                "job_card": job_card,
                "images": [],
            })
            return

        # ----- synchronous tool loop -----
        response = _with_retry(
            self._claude.messages.create,
            model=config.haiku,
            max_tokens=2048,
            system=system_prompt,
            tools=tools,
            tool_choice={"type": "auto", "disable_parallel_tool_use": True},
            messages=messages,
        )

        iterations = 0
        _job_card_called = False
        while response.stop_reason == "tool_use":
            _effective_cap = 3 if _job_card_called else _MAX_TOOL_ITERATIONS
            if iterations >= _effective_cap:
                break
            iterations += 1
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name  = block.name
                tool_input = block.input
                tool_id    = block.id
                log.info("Tool call: %s  input=%s", tool_name, tool_input)

                try:
                    if tool_name == "search_knowledge":
                        raw_result = self._tool_search_knowledge(
                            query=tool_input.get("query", query),
                            product_id=tool_input.get("product_id", product_id),
                        )
                    elif tool_name == "get_manual_image":
                        raw_result = self._tool_get_manual_image(
                            product_id=tool_input.get("product_id", product_id),
                            page_number=int(tool_input["page_number"]),
                            doc_slug=tool_input.get("doc_slug"),
                            highlight_label=tool_input.get("highlight_label"),
                        )
                        images.append(raw_result)
                    elif tool_name == "render_artifact":
                        html = self._tool_render_artifact(
                            artifact_type=tool_input["artifact_type"],
                            context=tool_input.get("context", ""),
                            artifact_prompts=artifact_prompts,
                        )
                        raw_result = {"html_length": len(html)}
                        artifact = {"type": tool_input["artifact_type"], "html": html}

                    elif tool_name == "generate_job_card":
                        _fd = tool_input.get("fault_description", query)
                        _ctx = tool_input.get("context", "")
                        job_card = self._tool_generate_job_card(
                            fault_description=_fd,
                            context=_ctx,
                            product_name=product.name,
                            artifact_type_keys=list(product.artifact_types.keys()) if product.artifact_types else None,
                        )
                        raw_result = {"step_count": len(job_card.get("steps", []))}
                        _job_card_called = True

                    else:
                        raw_result = {"error": f"Unknown tool: {tool_name}"}
                except Exception as exc:
                    log.warning("Tool %s raised: %s", tool_name, exc)
                    raw_result = {"error": str(exc)}

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(raw_result),
                })

            messages.append({"role": "user", "content": tool_results})

            # Peek at next response to decide if we need another iteration.
            # If it's not tool_use we'll break and fall into the streaming call.
            response = _with_retry(
                self._claude.messages.create,
                model=config.haiku,
                max_tokens=2048,
                system=system_prompt,
                tools=tools,
                tool_choice={"type": "auto", "disable_parallel_tool_use": True},
                messages=messages,
            )

        # ----- skip synthesis when a job card was generated -----
        # The job card is the complete response. A Haiku text summary after
        # it wastes tokens and produces a confusing double-response in the UI.
        if job_card is not None:
            yield ("job_card_start", {"metadata": job_card["metadata"]})
            for _step in job_card.get("steps", []):
                yield ("job_card_step", _step)
            yield ("done", {
                "answer": "",
                "suggestions": [],
                "artifact": None,
                "job_card": job_card,
                "images": images,
            })
            return

        # ----- streaming final synthesis -----
        # If the last response already has text (e.g. a clarifying question
        # with no tool calls), emit it word-by-word to keep the SSE path
        # uniform and avoid a redundant API call.

        final_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                final_text += block.text

        if final_text:
            # Model answered without a final tool → just stream what we have
            # by yielding it word-by-word so the SSE layer stays uniform.
            # This path also handles the cached first-response case.
            log.info("Streaming %d-char text from end_turn response", len(final_text))
            for word in final_text.split(" "):
                yield ("token", word + " ")
        else:
            # All tool calls done; response may have been empty (tool-only).
            # Make one real streaming synthesis call with the full context.
            messages.append({"role": "assistant", "content": response.content})
            log.info("Making streaming synthesis call (iterations=%d)", iterations)
            full_text = ""
            try:
                with _with_retry(
                    self._claude.messages.stream,
                    model=config.haiku,
                    max_tokens=2048,
                    system=system_prompt,
                    messages=messages,
                ) as stream:
                    for text_chunk in stream.text_stream:
                        full_text += text_chunk
                        yield ("token", text_chunk)
                final_text = full_text
            except Exception as exc:
                log.warning("Streaming synthesis failed, falling back to non-streaming: %s", exc)
                fb = _with_retry(
                    self._claude.messages.create,
                    model=config.haiku,
                    max_tokens=2048,
                    system=system_prompt,
                    messages=messages,
                )
                for block in fb.content:
                    if hasattr(block, "text"):
                        final_text += block.text
                for word in final_text.split(" "):
                    yield ("token", word + " ")

        answer, suggestions = self._parse_answer(final_text)
        yield ("done", {
            "answer": answer,
            "suggestions": suggestions,
            "artifact": artifact,
            "job_card": None,
            "images": images,
        })

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _tool_search_knowledge(self, query: str, product_id: str) -> list[dict]:
        """ChromaDB retrieval with keyword-based chunk_type boosting.

        Returns results with doc_slug so the agent can reference the right document.
        Uses the local sentence-transformers model — no GCP credentials needed.
        """
        chroma = self._get_chroma_collection(product_id)
        if self._embed_model is None or chroma is None:
            return [{"text": "Knowledge base not available.", "page_number": 0, "chunk_type": "none", "doc_slug": ""}]

        # Load product-specific structured keywords for chunk-type boosting.
        # Falls back to generic keywords if registry lookup fails.
        try:
            from config import get_product
            product = get_product(product_id)
            structured_kw = [k.lower() for k in product.structured_keywords]
        except Exception:
            structured_kw = ["setting", "specification", "table", "amperage", "voltage"]

        query_lower = query.lower()
        if any(w in query_lower for w in structured_kw + ["setting", "%", "spec"]):
            preferred_types = ["structured", "vision_caption", "text"]
        elif any(w in query_lower for w in
                 ["how", "setup", "connect", "wire", "terminal",
                  "cable", "diagram", "show", "layout", "module"]):
            preferred_types = ["vision_caption", "structured", "text"]
        elif any(w in query_lower for w in
                 ["why", "problem", "issue", "fault", "error",
                  "not working", "troubleshoot", "diagnostic", "flash", "LED"]):
            preferred_types = ["text", "vision_caption", "structured"]
        else:
            preferred_types = ["vision_caption", "text", "structured"]

        try:
            embedding: list[float] = self._embed_model.encode(
                query, normalize_embeddings=True
            ).tolist()
        except Exception as exc:
            log.warning("Embedding failed: %s", exc)
            return []

        seen_ids: set[str] = set()
        results: list[dict] = []
        top_k = config.top_k

        for chunk_type in preferred_types:
            try:
                resp = chroma.query(
                    query_embeddings=[embedding],
                    where={"$and": [
                        {"product_id": {"$eq": product_id}},
                        {"chunk_type": {"$eq": chunk_type}},
                    ]},
                    n_results=3,
                    include=["documents", "metadatas", "distances"],
                )
            except Exception as exc:
                log.warning("ChromaDB query failed for type %s: %s", chunk_type, exc)
                continue

            ids   = resp.get("ids",       [[]])[0]
            docs  = resp.get("documents", [[]])[0]
            metas = resp.get("metadatas", [[]])[0]

            for cid, doc, meta in zip(ids, docs, metas):
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                results.append({
                    "text":        doc,
                    "chunk_type":  meta.get("chunk_type", chunk_type),
                    "page_number": meta.get("page_number", 0),
                    "doc_slug":    meta.get("doc_slug", ""),
                    "section":     meta.get("section_title", ""),
                })
                if len(results) >= top_k:
                    return results

        return results[:top_k]

    def _tool_get_manual_image(
        self,
        product_id: str,
        page_number: int,
        doc_slug: str | None = None,
        highlight_label: str | None = None,
    ) -> dict:
        """Return image URL + optional highlight bbox.

        Looks up annotation from assets/{product_id}/annotations/{doc_slug}/page_N.json.
        Falls back to first available doc_slug if not specified.
        """
        resolved_slug = doc_slug or self._resolve_default_doc_slug(product_id)

        ann_path = (
            self._assets / product_id / "annotations" / resolved_slug / f"page_{page_number}.json"
        )
        highlight = None

        if ann_path.exists() and highlight_label:
            try:
                annotations: list[dict] = json.loads(ann_path.read_text())
                label_lower = highlight_label.lower()
                for ann in annotations:
                    lbl = (ann.get("label") or "").lower()
                    if lbl and label_lower in lbl:
                        bp = ann["bbox_pct"]
                        highlight = {
                            "x": bp["x"], "y": bp["y"],
                            "w": bp["w"], "h": bp["h"],
                            "label": ann.get("label", ""),
                        }
                        break
            except Exception as exc:
                log.warning(
                    "Failed to load annotations page %d [%s]: %s",
                    page_number, resolved_slug, exc,
                )

        return {
            "page_number": page_number,
            "doc_slug": resolved_slug,
            "url": f"/image/{product_id}/{resolved_slug}/{page_number}",
            "highlight": highlight,
        }

    def _resolve_default_doc_slug(self, product_id: str) -> str:
        """Return the first doc_slug found under assets/{product_id}/pages/."""
        pages_base = self._assets / product_id / "pages"
        if pages_base.exists():
            subdirs = sorted(d.name for d in pages_base.iterdir() if d.is_dir())
            if subdirs:
                return subdirs[0]
        return "owner-manual"

    def _tool_render_artifact(
        self,
        artifact_type: str,
        context: str,
        artifact_prompts: dict[str, str],
    ) -> str:
        """Generate self-contained HTML using Sonnet. Three-stage fallback."""
        template = artifact_prompts.get(
            artifact_type,
            artifact_prompts.get("settings_configurator", list(artifact_prompts.values())[0]),
        )
        prompt = template.format(context=context)

        html = self._call_sonnet(prompt, system=_HTML_SYSTEM_PROMPT)
        html = _wrap_html_fragment(html)
        if _is_valid_html(html):
            return html

        log.warning("Artifact stage 1 invalid, retrying simpler (type=%s)", artifact_type)
        html = self._call_sonnet(
            _FALLBACK_HTML_PROMPT.format(context=context),
            system=_HTML_SYSTEM_PROMPT,
        )
        html = _wrap_html_fragment(html)
        if _is_valid_html(html):
            return html

        log.warning("Artifact stage 2 invalid, using hardcoded table (type=%s)", artifact_type)
        return _wrap_html_fragment(_minimal_html_table(context))

    def _tool_generate_job_card(
        self,
        fault_description: str,
        context: str,
        product_name: str,
        artifact_type_keys: list[str] | None = None,
    ) -> dict:
        """Generate a validated diagnostic job card via Sonnet.

        Calls Sonnet with a JSON-only system prompt, strips any residual
        markdown fences (```json blocks that _strip_code_fences won't catch),
        parses JSON, then validates against the job card schema.
        Uses _with_retry directly (not _call_sonnet) to pass a system prompt.
        """
        valid_types = ", ".join(artifact_type_keys) if artifact_type_keys else "wiring_diagram, settings_configurator"
        prompt = (
            "Generate a diagnostic job card for the following fault on the "
            f"{product_name}. "
            "Output ONLY a raw JSON object matching this schema exactly — "
            "no explanation, no markdown fences, no text outside the JSON:\n\n"
            '{"type":"job_card","metadata":{"equipment":"<string>",'
            '"asset_id":"<string>","fault_description":"<string>",'
            '"priority":"LOW|MEDIUM|HIGH|CRITICAL"},'
            '"steps":[{"id":1,"instruction":"<one action, one sentence max>",'
            '"note":"<what to look for, 15 words max>",'
            '"yes_label":"<1-3 words>","no_label":"<1-3 words>",'
            '"yes_next":2,"no_next":"escalate",'
            '"source_citation":"p.N §X.Y",'
            '"artifact_trigger":null}]}\n\n'
            "RULES:\n"
            "1. source_citation REQUIRED on every step. Format MUST be 'p.N' followed by "
            "optional section, e.g. 'p.36 §4.2' or 'p.33'. Use the page number from the "
            "retrieved content. NEVER write prose in source_citation — only 'p.N ...'.\n"
            "2. artifact_trigger is null unless the retrieved chunk explicitly "
            "references a settings table, wiring diagram, or visual aid. "
            f"If set: type must be one of {valid_types}. label must be ≤3 words, "
            "action-oriented (e.g. 'Show wiring diagram').\n"
            "3. priority: CRITICAL=immediate safety risk, HIGH=operational failure, "
            "MEDIUM=degraded performance, LOW=advisory.\n"
            "4. yes_next / no_next: integer step id, or the string 'escalate', "
            "or the string 'complete'.\n\n"
            f"Fault: {fault_description}\n\n"
            "Retrieved content:\n"
            f"{context}"
        )

        response = _with_retry(
            self._claude.messages.create,
            model=config.sonnet,
            max_tokens=4096,
            system=_JOB_CARD_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Strip ```json fences — _strip_code_fences only handles html/htm tags
        if text.startswith("```"):
            first_nl = text.find("\n")
            if first_nl != -1:
                text = text[first_nl + 1:]
                if text.rstrip().endswith("```"):
                    text = text.rstrip()[:-3].rstrip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            log.warning("Job card JSON parse failed: %s | raw[:200]=%s", exc, text[:200])
            return _minimal_job_card(fault_description, product_name)

        return _validate_job_card(data, fault_description, product_name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _call_sonnet(self, prompt: str, system: str | None = None) -> str:
        try:
            kwargs: dict = dict(
                model=config.sonnet,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            if system:
                kwargs["system"] = system
            response = _with_retry(self._claude.messages.create, **kwargs)
            raw = response.content[0].text.strip()
            # Claude sometimes wraps HTML in markdown code fences — strip them.
            return _strip_code_fences(raw)
        except Exception as exc:
            log.warning("Sonnet call failed: %s", exc)
            return ""

    def _parse_answer(self, text: str) -> tuple[str, list[str]]:
        """Split Claude's final text into (answer_body, [3 suggestions])."""
        suggestions: list[str] = []

        match = re.search(
            r"---SUGGESTIONS---\s*(.*?)\s*---END---",
            text,
            re.DOTALL,
        )
        if match:
            answer = text[: match.start()].strip()
            raw_suggestions = match.group(1).strip()
            for line in raw_suggestions.splitlines():
                line = re.sub(r"^\d+\.\s*", "", line).strip()
                if line:
                    suggestions.append(line)
            suggestions = suggestions[:3]
        else:
            answer = text.strip()

        return answer, suggestions


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _is_valid_html(html: str) -> bool:
    """Accept any string that contains at least one HTML tag.

    We no longer require a full <!DOCTYPE html> document because _wrap_html_fragment
    will promote bare fragments into a proper document before rendering.
    The only things we reject are empty strings and plain prose (no tags).
    """
    stripped = html.strip()
    return bool(stripped) and "<" in stripped and ">" in stripped


def _wrap_html_fragment(html: str) -> str:
    """Promote a bare HTML fragment into a full document, if needed.

    If Sonnet already produced a complete document (starts with <!DOCTYPE or <html>)
    this is a no-op.  Otherwise the fragment is wrapped in a minimal shell that
    inherits the dark design language used everywhere else in the product.
    """
    stripped = html.strip()
    lc = stripped.lower()
    if lc.startswith("<!doctype") or lc.startswith("<html"):
        return stripped
    return (
        "<!DOCTYPE html><html lang='en'>"
        "<head><meta charset='UTF-8'>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        "<link href='https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,300..700;1,9..144,300..700&family=Geist:wght@400;500&family=Geist+Mono:wght@400;500;600&display=swap' rel='stylesheet'>"
        "<style>"
        "body{margin:0;padding:20px;background:#f3ede1;color:#1d1a15;"
        "font-family:'Geist',system-ui,sans-serif;font-size:14px;"
        "font-feature-settings:'ss01','ss02'}"
        "table{width:100%;border-collapse:collapse;margin-top:16px}"
        "th{background:#e8e0d0;color:#b84d14;font-family:'Geist Mono',monospace;"
        "font-size:10px;text-transform:uppercase;letter-spacing:0.1em;"
        "padding:10px 14px;border-bottom:2px solid #d9cfba;text-align:left}"
        "td{padding:10px 14px;border-bottom:1px dashed #d9cfba;color:#1d1a15}"
        "tr:nth-child(even) td{background:#fbf6ea}"
        "</style></head>"
        f"<body>{stripped}</body></html>"
    )


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences wrapping HTML output.

    Claude commonly returns:
        ```html
        <!DOCTYPE html>…</html>
        ```

    This extracts just the HTML so it can be used as iframe srcDoc
    without literal fence text rendering at the top.
    """
    # Match opening fence with optional language tag, then closing fence
    m = re.match(
        r"^```(?:html|htm)?\s*\n(.*?)```\s*$",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    # Also handle case where only opening fence exists (no closing)
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            stripped = text[first_newline + 1 :]
            # Remove trailing ``` if present
            if stripped.rstrip().endswith("```"):
                stripped = stripped.rstrip()[:-3].rstrip()
            return stripped.strip()
    return text


def _minimal_html_table(context: str) -> str:
    rows = "".join(
        f"<tr><td style='padding:4px 8px;border:1px solid #ccc'>{line.strip()}</td></tr>\n"
        for line in context.splitlines()
        if line.strip()
    )
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<title>Product Data</title></head><body>"
        "<h2 style='font-family:sans-serif'>Product Data</h2>"
        "<table style='border-collapse:collapse;font-family:sans-serif;font-size:14px'>"
        f"{rows}</table></body></html>"
    )


# ---------------------------------------------------------------------------
# Job card helpers
# ---------------------------------------------------------------------------

_VALID_ARTIFACT_TRIGGER_TYPES: frozenset[str] = frozenset({
    "diagnostic_lookup",
    "wiring_diagram",
    "voltage_calculator",
    # Legacy types kept for backwards compatibility
    "diagnostic_table",
    "settings_configurator",
    "module_layout",
    "duty_cycle_calculator",
    "polarity_diagram",
})

_JOB_CARD_SYSTEM_PROMPT = (
    "You are a technical documentation parser. "
    "Output ONLY a raw JSON object. "
    "No explanation, no preamble, no markdown fences. "
    "Start your response with { and end with }."
)


def _validate_job_card(data: dict, fault_description: str, equipment: str) -> dict:
    """Validate and annotate a raw job card dict from Sonnet.

    Risk 2 Option C: steps missing source_citation get citation_missing=True
    rather than being dropped. artifact_trigger with invalid type is nulled.
    Structurally broken steps (missing id/instruction/yes_next/no_next) are dropped.
    """
    data["type"] = "job_card"

    meta = data.get("metadata")
    if not isinstance(meta, dict):
        data["metadata"] = {
            "equipment": equipment,
            "asset_id": "unknown",
            "fault_description": fault_description,
            "priority": "MEDIUM",
        }
    else:
        meta.setdefault("equipment", equipment)
        meta.setdefault("asset_id", "unknown")
        meta.setdefault("fault_description", fault_description)
        if meta.get("priority") not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            meta["priority"] = "MEDIUM"

    steps = data.get("steps")
    if not isinstance(steps, list):
        data["steps"] = []
        return data

    valid_steps = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if not all(k in step for k in ("id", "instruction", "yes_next", "no_next")):
            continue
        # Flag missing citation — never drop silently (Risk 2 Option C)
        if not step.get("source_citation"):
            step["citation_missing"] = True
        # Null out artifact_trigger if type is not in the valid set
        trigger = step.get("artifact_trigger")
        if trigger is not None:
            if (
                not isinstance(trigger, dict)
                or trigger.get("type") not in _VALID_ARTIFACT_TRIGGER_TYPES
            ):
                step["artifact_trigger"] = None
        valid_steps.append(step)

    data["steps"] = valid_steps
    return data


def _minimal_job_card(fault_description: str, equipment: str) -> dict:
    """Fallback job card when Sonnet output is not parseable JSON."""
    return {
        "type": "job_card",
        "metadata": {
            "equipment": equipment,
            "asset_id": "unknown",
            "fault_description": fault_description,
            "priority": "MEDIUM",
        },
        "steps": [
            {
                "id": 1,
                "instruction": "Contact technical support — automated diagnosis unavailable.",
                "note": "Manual diagnosis required.",
                "yes_label": "Understood",
                "no_label": "Escalate",
                "yes_next": "complete",
                "no_next": "escalate",
                "source_citation": "",
                "citation_missing": True,
                "artifact_trigger": None,
            }
        ],
    }
