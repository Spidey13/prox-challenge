"""Multi-product support agent — Anthropic tool_use agentic loop.

Claude decides which tools to call. We execute them and feed results back.
The loop runs until stop_reason != "tool_use" (end_turn, max_tokens, etc.).

Model assignments:
  Haiku  — agent loop (query rewriting implicitly via system prompt + context)
  Sonnet — render_artifact HTML codegen only (reliable structured output)
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

_MAX_TOOL_ITERATIONS = 5       # guard against runaway loops at 5 RPM
_MIN_ARTIFACT_LEN    = 300     # minimum HTML length considered valid
_RETRY_BASE_SECS     = 13.0    # 60s / 5 RPM + 1s buffer
_MAX_RETRIES         = 4

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
2. For questions about connections, wiring, polarity, or the front panel, \
   also call get_manual_image with the relevant page number and doc_slug.
3. For questions about duty cycles, settings matrices, or troubleshooting \
   paths, also call render_artifact with the appropriate artifact_type.
4. For ambiguous questions ("it's not working"), ask one clarifying \
   question in your text answer without calling any tools.
5. Never invent specifications. If search_knowledge returns nothing \
   useful, say "I don't see that in the manual" and cite the closest \
   page found.
6. When search results include a doc_slug field, use it to call \
   get_manual_image with the correct doc_slug so the right document \
   page image is shown.

RESPONSE FORMAT:
After all tool calls are done, write your answer as plain prose. \
End with exactly this block (no extra text before or after the dashes):

---SUGGESTIONS---
1. <first follow-up question>
2. <second follow-up question>
3. <third follow-up question>
---END---
"""


def _build_system_prompt(product: ProductInfo) -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(
        product_name=product.name,
        product_description=product.description,
        product_persona=product.persona,
    )


# ---------------------------------------------------------------------------
# Tool definitions (JSON Schema, passed to Claude in each request)
# ---------------------------------------------------------------------------

def _build_tools(product_id: str) -> list[dict]:
    """Return tool schema with the correct product_id default."""
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
                "user asks about something visual: the front panel, a wiring diagram, "
                "polarity setup, or any 'show me' question. "
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
                "Use for: duty_cycle_calculator, polarity_diagram, "
                "troubleshooting_flowchart, settings_configurator, wiring_diagram. "
                "Pass the relevant retrieved context so the artifact contains real data."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "artifact_type": {
                        "type": "string",
                        "enum": [
                            "duty_cycle_calculator",
                            "polarity_diagram",
                            "troubleshooting_flowchart",
                            "settings_configurator",
                            "wiring_diagram",
                        ],
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
    ]


# ---------------------------------------------------------------------------
# Artifact prompts (Sonnet-generated HTML) — product name injected at render time
# ---------------------------------------------------------------------------

_ARTIFACT_PROMPT_TEMPLATES: dict[str, str] = {
    "duty_cycle_calculator": (
        "Generate a self-contained HTML duty cycle calculator for the "
        "{product_name}. Use this manual data:\n{{context}}\n\n"
        "The calculator must:\n"
        "- Have dropdowns for Welding Process (MIG/FCAW/TIG/STICK) and Input Voltage (120V/240V)\n"
        "- Show a results table with Max Amperage and Duty Cycle %\n"
        "- Populate from the actual values in the context above\n"
        "- Use a clean minimal design with inline CSS only\n"
        "- Work with zero JavaScript errors\n"
        "- Be fully self-contained (no external dependencies)\n"
        "Output ONLY the HTML. No explanation."
    ),
    "polarity_diagram": (
        "Generate a self-contained HTML page showing a polarity connection "
        "diagram for the {product_name}. Use this data:\n{{context}}\n\n"
        "Must show:\n"
        "- A visual SVG diagram of the welder's front panel connection points\n"
        "- Color-coded cables: red for electrode positive, black for negative\n"
        "- Labels for each socket/terminal\n"
        "- A toggle or tabs to switch between welding processes\n"
        "- Which cable goes where for each process (MIG/FCAW/TIG/STICK)\n"
        "Use inline SVG. No external dependencies. Output ONLY the HTML."
    ),
    "troubleshooting_flowchart": (
        "Generate a self-contained HTML troubleshooting flowchart using "
        "this manual data:\n{{context}}\n\n"
        "Must show:\n"
        "- A clickable step-by-step diagnostic flow\n"
        "- Each step has: symptom or check → yes/no branches → solution\n"
        "- Use simple HTML/CSS buttons for navigation (no Mermaid, no D3)\n"
        "- Mobile-friendly large tap targets\n"
        "- Clean minimal design\n"
        "No external dependencies. Output ONLY the HTML."
    ),
    "settings_configurator": (
        "Generate a self-contained HTML settings configurator for the "
        "{product_name} using this data:\n{{context}}\n\n"
        "Must have:\n"
        "- Inputs: welding process, material type, material thickness\n"
        "- Output panel: recommended voltage, wire speed, gas flow, polarity, notes\n"
        "- Populate recommendations from the actual values in context\n"
        "- Real-time update as user changes inputs (vanilla JS)\n"
        "No external dependencies. Output ONLY the HTML."
    ),
    "wiring_diagram": (
        "Generate a self-contained HTML page with an SVG wiring diagram "
        "using this data:\n{{context}}\n\n"
        "Must show:\n"
        "- Clean SVG schematic of the relevant connections\n"
        "- Labeled terminals and cables\n"
        "- Color-coded by voltage/signal type\n"
        "- A brief text explanation below the diagram\n"
        "No external dependencies. Output ONLY the HTML."
    ),
}

_FALLBACK_HTML_PROMPT = (
    "Generate a plain HTML table showing this data: {context}. "
    "Simple black and white. No JavaScript."
)


def _build_artifact_prompts(product_name: str) -> dict[str, str]:
    """Expand artifact prompt templates with the given product name."""
    return {
        key: template.format(product_name=product_name)
        for key, template in _ARTIFACT_PROMPT_TEMPLATES.items()
    }


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
    """Multi-product support agent using the Anthropic tool_use loop.

    The public interface is unchanged:
        result = agent.ask(query, product_id, history)
    Returns: {answer, suggestions, artifact, images}
    """

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
    # Public entry point
    # ------------------------------------------------------------------

    def ask(
        self,
        query: str,
        product_id: str,
        history: list[dict],
        image_data: str | None = None,
        image_media_type: str | None = None,
    ) -> dict:
        """Run the Anthropic tool_use agentic loop for one user turn.

        Args:
            query: The user's text question.
            product_id: Product to query against.
            history: Prior conversation turns (role/content dicts).
            image_data: Optional base64-encoded image for vision input.
            image_media_type: MIME type of the image (e.g. "image/jpeg").

        Returns: {answer, suggestions, artifact, images}
        """
        # Load product from registry for dynamic prompt/tool building.
        # Fall back gracefully if registry entry is missing.
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
        artifact_prompts = _build_artifact_prompts(product.name)

        # Build the user message content — image block first (if provided),
        # then text.  Claude performs best when images precede the text prompt.
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
            log.info(
                "Vision input attached (%s, %d chars base64)",
                image_media_type, len(image_data),
            )
        else:
            user_content = query

        messages: list[dict] = [
            *[{"role": m["role"], "content": m["content"]} for m in history],
            {"role": "user", "content": user_content},
        ]

        images: list[dict] = []
        artifact: dict | None = None

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
        while response.stop_reason == "tool_use" and iterations < _MAX_TOOL_ITERATIONS:
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

            # Check whether the next response will still need tools, or if
            # we've reached end_turn.  We use a non-streaming call here so we
            # can decide whether to continue iterating or break into the
            # streaming synthesis call below.
            response = _with_retry(
                self._claude.messages.create,
                model=config.haiku,
                max_tokens=2048,
                system=system_prompt,
                tools=tools,
                tool_choice={"type": "auto", "disable_parallel_tool_use": True},
                messages=messages,
            )

        # ── Tool loop finished.  'response' now holds the final end_turn reply. ──
        # For streaming mode, callers use ask_streaming() which replaces this
        # last non-streaming call with a live-token stream.  For compatibility
        # (cache path) we keep the synchronous text extraction here.
        final_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                final_text += block.text

        answer, suggestions = self._parse_answer(final_text)

        return {
            "answer": answer,
            "suggestions": suggestions,
            "artifact": artifact,
            "images": images,
        }

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
    ):
        """Run the agentic tool loop then stream the final synthesis.

        Yields tuples of (event_type, payload):
          ("token",  str)          — a text delta from the streaming response
          ("done",   dict)         — final metadata: {suggestions, artifact, images}

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
        artifact_prompts = _build_artifact_prompts(product.name)

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
        while response.stop_reason == "tool_use" and iterations < _MAX_TOOL_ITERATIONS:
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

        # ----- streaming final synthesis -----
        # At this point `response` has stop_reason == "end_turn" (or we hit
        # max iterations).  We already have the full text in `response`, so we
        # stream it as a generator for the SSE layer — preserving the same UX
        # as truly streaming, without a redundant API call.
        #
        # Real streaming: append the assistant's end_turn message to messages,
        # then make a final streaming call so tokens arrive live.
        #
        # If the last response was already *not* tool_use (no tools called on
        # this turn, e.g. a clarifying question), the final text is in
        # `response` — we skip the duplicate streaming call and emit tokens
        # from the existing response to avoid billable API waste.

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

        query_lower = query.lower()
        if any(w in query_lower for w in
               ["duty cycle", "amperage", "amp", "voltage", "%",
                "wire speed", "ipm", "settings"]):
            preferred_types = ["structured", "vision_caption", "text"]
        elif any(w in query_lower for w in
                 ["how", "setup", "connect", "wire", "polarity",
                  "socket", "terminal", "cable", "diagram", "show"]):
            preferred_types = ["vision_caption", "structured", "text"]
        elif any(w in query_lower for w in
                 ["why", "problem", "issue", "porosity", "spatter",
                  "crack", "not working", "error", "troubleshoot"]):
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

        html = self._call_sonnet(prompt)
        if _is_valid_html(html):
            return html

        log.warning("Artifact stage 1 invalid, retrying simpler (type=%s)", artifact_type)
        html = self._call_sonnet(_FALLBACK_HTML_PROMPT.format(context=context))
        if _is_valid_html(html):
            return html

        log.warning("Artifact stage 2 invalid, using hardcoded table (type=%s)", artifact_type)
        return _minimal_html_table(context)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _call_sonnet(self, prompt: str) -> str:
        try:
            response = _with_retry(
                self._claude.messages.create,
                model=config.sonnet,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            # Claude often wraps HTML in markdown code fences like:
            #   ```html\n<!DOCTYPE html>...\n```
            # Strip the fences so the iframe gets clean HTML.
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
    return len(html) > _MIN_ARTIFACT_LEN and "</html>" in html.lower()


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
