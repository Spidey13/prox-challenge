"""PDF ingestion pipeline — multi-document, multi-product support.

Pipeline per-page (8 steps):
  1. Render pages as PNG at PAGE_DPI.
  2. Extract embedded image bounding boxes via pymupdf (no API call).
  3. Gemini vision captioning — dense literal transcription.
  4. Gemini structured extraction — duty cycle / polarity / wire-feed JSON.
  5. Raw text extraction + hierarchical tiktoken chunking with context enrichment.
  6. Embed all chunks via Vertex text-embedding-004 (token-aware batching).
  7. Write chunks + embeddings to ChromaDB (idempotent MD5 IDs, rich metadata).
  8. Print completion report and ingestion metrics summary.

Production features:
  - Multi-PDF per product: all PDFs in product.pdf_directory are ingested.
  - Per-PDF asset subdirectories: assets/{product_id}/pages/{doc_slug}/page_N.png
  - doc_id metadata: "{product_id}/{doc_slug}" on every chunk.
  - Parallel page processing via ThreadPoolExecutor (INGEST_WORKERS).
  - Pages fail independently without aborting the full job.
  - Resumable runs: completed pages tracked per-PDF in a JSON state file.
  - Hierarchical chunking: parent (full-page) + child (windowed) chunks.
  - Contextual enrichment: [Product | Doc | Page | Section | Type] prefix.
  - Token-aware embedding batching respects per-input and per-batch limits.
  - Defensive JSON parsing on all Gemini structured-extraction responses.
  - Structured chunk schema with doc_id, chunk_id, parent_chunk_id, ingested_at.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import chromadb
import fitz  # pymupdf
import tiktoken
import vertexai
from google import genai
from google.genai import types as genai_types
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

from config import ProductInfo, config, get_product

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s"
)
log = logging.getLogger(__name__)

# Gemini Flash cost estimate: ~$0.0001 per page (vision input + output tokens).
# Vertex text-embedding-004: ~$0.000025 per 1k chars.
_COST_PER_GEMINI_CALL = 0.0001
_COST_PER_EMBED_BATCH = 0.0005


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PageResult:
    """Result of processing a single PDF page."""

    page_idx: int
    chunks: list[dict] = field(default_factory=list)
    annotations: list[dict] = field(default_factory=list)
    structured_ok: bool = True
    error: str | None = None


@dataclass
class IngestionMetrics:
    """Accumulates counters across the full ingestion run."""

    total_pages: int = 0
    pages_processed: int = 0
    pages_skipped: int = 0
    pages_failed: int = 0
    chunks_written: int = 0
    parent_chunks: int = 0
    child_chunks: int = 0
    vision_captions: int = 0
    structured_ok: int = 0
    structured_failed: int = 0
    gemini_calls: int = 0
    embed_batches: int = 0
    annotations_saved: int = 0
    start_time: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Ingester — one PDF file
# ---------------------------------------------------------------------------


class Ingester:
    """Run the full ingestion pipeline for one PDF file.

    Args:
        product_id: Logical product identifier, e.g. ``"vulcan_220"``.
        pdf_path:   Path to the source PDF file.
        product:    Optional pre-loaded ProductInfo. Looked up from registry
                    if not provided.
    """

    def __init__(
        self,
        product_id: str,
        pdf_path: str,
        product: ProductInfo | None = None,
    ) -> None:
        self.product_id = product_id
        self.pdf_path = Path(pdf_path)
        self.doc_slug = self.pdf_path.stem          # e.g. "owner-manual"
        self.doc_id = f"{product_id}/{self.doc_slug}"  # e.g. "vulcan_220/owner-manual"

        # Load product metadata from registry if not supplied.
        # Fall back to a generic ProductInfo so the ingester works even for
        # product IDs not registered in products.json (e.g. smoke tests).
        if product is not None:
            self._product = product
        else:
            try:
                self._product = get_product(product_id)
            except KeyError:
                log.warning(
                    "Product %r not found in registry; using generic metadata.",
                    product_id,
                )
                from config import ProductInfo as _PI  # local to avoid top-level cycle
                self._product = _PI(
                    product_id=product_id,
                    name=product_id,
                    description="technical product",
                    pdf_directory="files",
                    persona="Be direct, precise, and practical.",
                    structured_keywords=("setting", "voltage", "amperage"),
                )

        assets_root = Path(config.assets_path) / product_id
        self._pages_dir = assets_root / "pages" / self.doc_slug
        self._annotations_dir = assets_root / "annotations" / self.doc_slug
        self._state_path = assets_root / f"ingest_state_{self.doc_slug}.json"

        # Lazily initialised clients
        self._genai_client: genai.Client | None = None
        self._embed_model: TextEmbeddingModel | None = None
        self._chroma: chromadb.Collection | None = None

        # Thread safety for state file and Gemini rate limiting
        self._state_lock = threading.Lock()
        self._gemini_sem = threading.Semaphore(config.ingest_workers)

        # Shared tiktoken encoder (thread-safe after construction)
        self._enc = tiktoken.get_encoding("cl100k_base")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> dict:
        """Orchestrate all pipeline steps and return a summary dict."""
        metrics = IngestionMetrics(start_time=time.time())

        log.info(
            "Ingestion started  product=%s  doc=%s  pdf=%s",
            self.product_id,
            self.doc_slug,
            self.pdf_path,
        )

        self._init_clients()
        self._make_dirs()

        pdf_hash = self._md5_file(self.pdf_path)
        state = self._load_state(pdf_hash)

        doc = fitz.open(str(self.pdf_path))
        n_pages = len(doc)
        log.info("PDF opened: %d pages", n_pages)

        metrics.total_pages = n_pages
        already_done = {int(k) for k in state.get("pages", {}).keys()}
        pages_to_process = [i for i in range(n_pages) if i not in already_done]
        metrics.pages_skipped = len(already_done)
        log.info(
            "Pages to process: %d  (skipping %d already done)",
            len(pages_to_process),
            metrics.pages_skipped,
        )

        all_chunks: list[dict] = []
        ingestion_ts = datetime.now(timezone.utc).isoformat()
        # Track successfully processed pages for state commit after ChromaDB write.
        completed_pages: list[tuple[int, int]] = []  # (page_idx, n_chunks)

        with ThreadPoolExecutor(max_workers=config.ingest_workers) as pool:
            futures = {
                pool.submit(self._process_single_page, doc, i, ingestion_ts): i
                for i in pages_to_process
            }
            for future in as_completed(futures):
                page_idx = futures[future]
                try:
                    result: PageResult = future.result()
                except Exception as exc:
                    log.error("Unexpected error on page %d: %s", page_idx, exc)
                    metrics.pages_failed += 1
                    continue

                if result.error:
                    log.warning("Page %d failed: %s", result.page_idx, result.error)
                    metrics.pages_failed += 1
                    continue

                all_chunks.extend(result.chunks)
                metrics.annotations_saved += len(result.annotations)
                if result.structured_ok:
                    metrics.structured_ok += 1
                else:
                    metrics.structured_failed += 1
                metrics.pages_processed += 1
                metrics.gemini_calls += 2

                for c in result.chunks:
                    ct = c.get("chunk_type", "")
                    if ct == "vision_caption":
                        metrics.vision_captions += 1
                    elif ct == "text_parent":
                        metrics.parent_chunks += 1
                    elif ct == "text":
                        metrics.child_chunks += 1

                # Defer state save until after ChromaDB write to keep state
                # consistent: a page is only "done" once its chunks are committed.
                completed_pages.append((result.page_idx, len(result.chunks)))

        doc.close()

        log.info("Embedding %d chunks …", len(all_chunks))
        embeddings, embed_batch_count = self._embed_chunks(all_chunks)
        metrics.embed_batches = embed_batch_count

        log.info("Writing to ChromaDB collection %r …", self.product_id)
        written = self._write_chroma(all_chunks, embeddings)
        metrics.chunks_written = written

        # Commit state only after a successful ChromaDB write.
        for page_idx, n_chunks in completed_pages:
            self._mark_page_done(state, page_idx, n_chunks, pdf_hash)

        self._print_summary(metrics)

        return {
            "doc_id": self.doc_id,
            "doc_slug": self.doc_slug,
            "pages_processed": metrics.pages_processed,
            "pages_skipped": metrics.pages_skipped,
            "pages_failed": metrics.pages_failed,
            "chunks_written": metrics.chunks_written,
            "chunks_by_type": {
                "vision_caption": metrics.vision_captions,
                "text_parent": metrics.parent_chunks,
                "text": metrics.child_chunks,
                "structured": metrics.structured_ok,
            },
            "annotations_saved": metrics.annotations_saved,
        }

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _init_clients(self) -> None:
        vertexai.init(
            project=config.google_cloud_project,
            location=config.vertex_location,
        )
        self._genai_client = genai.Client(
            vertexai=True,
            project=config.google_cloud_project,
            location="global",
        )
        self._embed_model = TextEmbeddingModel.from_pretrained(config.embed_model)

        chroma_client = chromadb.PersistentClient(path=config.chroma_path)
        self._chroma = chroma_client.get_or_create_collection(
            name=self.product_id,
            metadata={"hnsw:space": "cosine"},
        )

    def _make_dirs(self) -> None:
        self._pages_dir.mkdir(parents=True, exist_ok=True)
        self._annotations_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # State file (resumable runs)
    # ------------------------------------------------------------------

    @staticmethod
    def _md5_file(path: Path) -> str:
        h = hashlib.md5()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _load_state(self, pdf_hash: str) -> dict:
        if self._state_path.exists():
            try:
                state = json.loads(self._state_path.read_text(encoding="utf-8"))
                if state.get("pdf_hash") == pdf_hash:
                    log.info(
                        "Resuming %s: %d pages already done.",
                        self.doc_slug,
                        len(state.get("pages", {})),
                    )
                    return state
                log.info("PDF hash changed for %s — resetting state.", self.doc_slug)
            except Exception as exc:
                log.warning("Could not read state file, starting fresh: %s", exc)
        return {
            "product_id": self.product_id,
            "doc_id": self.doc_id,
            "pdf_hash": pdf_hash,
            "pages": {},
        }

    def _save_state(self, state: dict) -> None:
        self._state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _mark_page_done(self, state: dict, page_idx: int, n_chunks: int, pdf_hash: str) -> None:
        with self._state_lock:
            state["pages"][str(page_idx)] = {
                "status": "done",
                "chunks": n_chunks,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            self._save_state(state)

    # ------------------------------------------------------------------
    # Per-page processing (run inside thread pool)
    # ------------------------------------------------------------------

    def _process_single_page(
        self, doc: fitz.Document, page_idx: int, ingestion_ts: str
    ) -> PageResult:
        """Process one PDF page through steps 1-5. Never raises."""
        try:
            page = doc[page_idx]

            page_png, page_w, page_h = self._render_page(page, page_idx)
            annotations = self._extract_bboxes(page, page_idx, page_w, page_h)

            with self._gemini_sem:
                time.sleep(config.gemini_rpm_delay)
                caption = self._gemini_caption(page_png, page_idx)

            raw_text = page.get_text("text")
            section_title = self._detect_section_title(raw_text)

            chunks: list[dict] = []
            structured_ok = True

            if caption:
                chunks.append(
                    self._make_chunk(
                        chunk_type="vision_caption",
                        text=caption,
                        page_idx=page_idx,
                        section_title=section_title,
                        ingestion_ts=ingestion_ts,
                    )
                )

            caption_lower = caption.lower()
            if any(kw in caption_lower for kw in self._product.structured_keywords):
                with self._gemini_sem:
                    time.sleep(config.gemini_rpm_delay)
                    structured_chunks, structured_ok = self._gemini_structured(
                        caption, page_idx, section_title, ingestion_ts
                    )
                chunks.extend(structured_chunks)

                if annotations:
                    label = " ".join(caption.split()[:20])
                    for ann in annotations:
                        ann["label"] = label

            ann_path = self._annotations_dir / f"page_{page_idx}.json"
            ann_path.write_text(json.dumps(annotations, indent=2), encoding="utf-8")

            text_chunks = self._chunk_text(raw_text, page_idx, section_title, ingestion_ts)
            chunks.extend(text_chunks)

            log.info(
                "Page %d done [%s]: %d chunks, section=%r",
                page_idx,
                self.doc_slug,
                len(chunks),
                section_title,
            )
            return PageResult(
                page_idx=page_idx,
                chunks=chunks,
                annotations=annotations,
                structured_ok=structured_ok,
            )

        except Exception as exc:
            log.warning(
                "Page %d [%s] processing failed: %s", page_idx, self.doc_slug, exc, exc_info=True
            )
            return PageResult(page_idx=page_idx, error=str(exc))

    # ------------------------------------------------------------------
    # Chunk factory
    # ------------------------------------------------------------------

    def _make_chunk(
        self,
        *,
        chunk_type: str,
        text: str,
        page_idx: int,
        section_title: str,
        ingestion_ts: str,
        parent_chunk_id: str = "",
        metadata: dict | None = None,
    ) -> dict:
        enriched = self._enrich_text(text, page_idx, section_title, chunk_type)
        chunk_key = f"{self.doc_id}_{page_idx}_{chunk_type}_{hashlib.md5(text.encode()).hexdigest()}"
        chunk_id = hashlib.md5(chunk_key.encode()).hexdigest()

        base = {
            "product_id": self.product_id,
            "doc_id": self.doc_id,
            "doc_slug": self.doc_slug,
            "page": page_idx,
            "chunk_type": chunk_type,
            "text": enriched,
            "raw_text": text,
            "chunk_id": chunk_id,
            "parent_chunk_id": parent_chunk_id,
            "section_title": section_title,
            "ingestion_ts": ingestion_ts,
        }
        if metadata:
            base["metadata"] = metadata
        return base

    def _enrich_text(
        self, text: str, page_idx: int, section_title: str, chunk_type: str
    ) -> str:
        """Prepend document-level context header to chunk text."""
        header = (
            f"[Product: {self._product.name} | "
            f"Document: {self.doc_slug} | "
            f"Page: {page_idx + 1} | "
            f"Section: {section_title} | "
            f"Type: {chunk_type}]\n"
        )
        return header + text

    # ------------------------------------------------------------------
    # Step 1 — render page PNG
    # ------------------------------------------------------------------

    def _render_page(self, page: fitz.Page, n: int) -> tuple[Path, int, int]:
        pix = page.get_pixmap(dpi=config.page_dpi)
        png_path = self._pages_dir / f"page_{n}.png"
        pix.save(str(png_path))
        return png_path, pix.width, pix.height

    # ------------------------------------------------------------------
    # Step 2 — extract embedded image bboxes
    # ------------------------------------------------------------------

    def _extract_bboxes(
        self, page: fitz.Page, n: int, page_w: int, page_h: int
    ) -> list[dict]:
        page_rect = page.rect
        annotations: list[dict] = []

        for img_info in page.get_image_info():
            raw = img_info.get("bbox")
            if not raw:
                continue
            x0, y0, x1, y1 = raw

            x_pct = x0 / page_rect.width
            y_pct = y0 / page_rect.height
            w_pct = (x1 - x0) / page_rect.width
            h_pct = (y1 - y0) / page_rect.height

            annotations.append(
                {
                    "page": n,
                    "doc_slug": self.doc_slug,
                    "bbox_pct": {"x": x_pct, "y": y_pct, "w": w_pct, "h": h_pct},
                    "bbox_px": {
                        "x": int(x_pct * page_w),
                        "y": int(y_pct * page_h),
                        "w": int(w_pct * page_w),
                        "h": int(h_pct * page_h),
                    },
                    "label": None,
                }
            )
        return annotations

    # ------------------------------------------------------------------
    # Step 3 — Gemini vision captioning
    # ------------------------------------------------------------------

    def _gemini_caption(self, png_path: Path, n: int) -> str:
        prompt = (
            f"You are analyzing page {n + 1} of the {self._product.name} "
            f"'{self.doc_slug}' document.\n\n"
            "Extract ALL of the following from this page:\n\n"
            "1. ALL visible text, including text inside diagrams and labels on "
            "diagrams. Preserve exact numbers, units, and labels.\n\n"
            "2. Tables: reproduce each table with its complete structure. Use "
            "markdown table format. Include all row and column headers. "
            "Every cell value matters — duty cycle percentages, amperages, "
            "voltages, wire speeds must be exact.\n\n"
            "3. Diagrams: describe each diagram precisely. For wiring or "
            "polarity diagrams, state exactly which terminal connects to "
            "what and the left/right/top/bottom spatial relationships. "
            "For the front panel, list every control and indicator from "
            "left to right, top to bottom.\n\n"
            '4. Figure references: note any "Figure X" or "See page Y" '
            "references exactly as written.\n\n"
            "5. Safety warnings: reproduce any WARNING or CAUTION text "
            "word-for-word.\n\n"
            "Write your response as dense, precise technical prose. "
            "Do not summarize or paraphrase specifications — give exact values."
        )
        try:
            png_bytes = png_path.read_bytes()
            response = self._genai_client.models.generate_content(
                model=config.gemini,
                contents=[
                    prompt,
                    genai_types.Part.from_bytes(
                        data=png_bytes,
                        mime_type="image/png",
                    ),
                ],
            )
            return (getattr(response, "text", None) or "").strip()
        except Exception as exc:
            log.warning("Gemini caption failed on page %d [%s]: %s", n, self.doc_slug, exc)
            return ""

    # ------------------------------------------------------------------
    # Step 4 — Gemini structured extraction (defensive JSON parsing)
    # ------------------------------------------------------------------

    def _gemini_structured(
        self,
        caption: str,
        n: int,
        section_title: str,
        ingestion_ts: str,
    ) -> tuple[list[dict], bool]:
        prompt = (
            f"From this page of the {self._product.name} '{self.doc_slug}' document, "
            "extract any structured specifications as JSON. Return ONLY a JSON array.\n"
            "Each item must be one of these schemas:\n\n"
            'Duty cycle:\n{"type":"duty_cycle","process":"MIG|FCAW|TIG|STICK",'
            '"voltage_input":120|240,"amperage":number,"duty_cycle_pct":number}\n\n'
            'Polarity setup:\n{"type":"polarity","process":"MIG|FCAW|TIG|STICK",'
            '"electrode_terminal":"positive|negative",'
            '"work_terminal":"positive|negative","notes":"any extra notes"}\n\n'
            'Wire/feed setting:\n{"type":"wire_feed","material":"steel|aluminum|stainless",'
            '"thickness_in":number,"wire_speed_ipm":number,"voltage":number,"wire_gauge":"..."}\n\n'
            'General setting:\n{"type":"setting","process":"...","parameter":"...",'
            '"value":"...","unit":"..."}\n\n'
            "If no structured data exists on this page, return: []\n"
            "Return ONLY the JSON array. No explanation text.\n\n"
            f"Page content:\n{caption}"
        )
        try:
            response = self._genai_client.models.generate_content(
                model=config.gemini,
                contents=prompt,
            )
            raw = (getattr(response, "text", None) or "").strip()
            items = self._parse_structured_json(raw, n)
            chunks = [
                self._make_chunk(
                    chunk_type="structured",
                    text=json.dumps(item),
                    page_idx=n,
                    section_title=section_title,
                    ingestion_ts=ingestion_ts,
                    metadata=item,
                )
                for item in items
            ]
            return chunks, True
        except Exception as exc:
            log.warning("Structured extraction failed on page %d [%s]: %s", n, self.doc_slug, exc)
            return [], False

    def _parse_structured_json(self, raw: str, page_idx: int) -> list[dict]:
        if not raw:
            log.warning(
                "Structured extraction page %d [%s]: empty response — skipping.",
                page_idx, self.doc_slug,
            )
            return []

        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", raw, flags=re.MULTILINE)
        cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE).strip()

        if not cleaned:
            return []

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            cleaned2 = re.sub(r",\s*([\]\}])", r"\1", cleaned)
            try:
                parsed = json.loads(cleaned2)
            except json.JSONDecodeError as exc:
                log.warning(
                    "Structured extraction page %d [%s]: malformed JSON (%s). Raw: %r",
                    page_idx, self.doc_slug, exc, raw[:200],
                )
                return []

        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict):
            log.warning(
                "Structured extraction page %d [%s]: response was a dict — wrapping.",
                page_idx, self.doc_slug,
            )
            items = [parsed]
        else:
            log.warning(
                "Structured extraction page %d [%s]: unexpected type %s — skipping.",
                page_idx, self.doc_slug, type(parsed).__name__,
            )
            return []

        valid = [item for item in items if isinstance(item, dict)]
        if len(valid) != len(items):
            log.warning(
                "Structured extraction page %d [%s]: dropped %d non-dict items.",
                page_idx, self.doc_slug, len(items) - len(valid),
            )
        return valid

    # ------------------------------------------------------------------
    # Section title detection
    # ------------------------------------------------------------------

    def _detect_section_title(self, raw_text: str) -> str:
        for line in raw_text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if 3 <= len(stripped) <= 80 and stripped.isupper():
                if re.search(r"[A-Z]", stripped):
                    return stripped
        return "unknown"

    # ------------------------------------------------------------------
    # Step 5 — hierarchical text chunking with context enrichment
    # ------------------------------------------------------------------

    def _chunk_text(
        self,
        text: str,
        n: int,
        section_title: str,
        ingestion_ts: str,
    ) -> list[dict]:
        if not text.strip():
            return []

        chunks: list[dict] = []

        parent_key = f"{self.doc_id}_page_{n}_parent"
        parent_id = hashlib.md5(parent_key.encode()).hexdigest()
        parent_chunk = self._make_chunk(
            chunk_type="text_parent",
            text=text,
            page_idx=n,
            section_title=section_title,
            ingestion_ts=ingestion_ts,
        )
        parent_chunk["chunk_id"] = parent_id
        chunks.append(parent_chunk)

        tokens = self._enc.encode(text)
        size = config.chunk_size
        overlap = config.chunk_overlap
        start = 0
        child_idx = 0
        while start < len(tokens):
            end = min(start + size, len(tokens))
            chunk_text = self._enc.decode(tokens[start:end])
            child_chunk = self._make_chunk(
                chunk_type="text",
                text=chunk_text,
                page_idx=n,
                section_title=section_title,
                ingestion_ts=ingestion_ts,
                parent_chunk_id=parent_id,
            )
            child_chunk["chunk_id"] = hashlib.md5(
                f"{self.doc_id}_{n}_text_{child_idx}".encode()
            ).hexdigest()
            chunks.append(child_chunk)
            child_idx += 1
            if end == len(tokens):
                break
            start += size - overlap

        return chunks

    # ------------------------------------------------------------------
    # Step 6 — token-aware embedding
    # ------------------------------------------------------------------

    def _embed_chunks(
        self, chunks: list[dict]
    ) -> tuple[list[list[float]], int]:
        max_input = config.embed_max_input_tokens
        batch_limit = config.embed_batch_token_limit

        all_embeddings: list[list[float]] = [None] * len(chunks)  # type: ignore[list-item]
        batch_indices: list[int] = []
        batch_texts: list[str] = []
        batch_tokens = 0
        batch_count = 0

        def embed_with_split_fallback(
            indices: list[int], texts: list[str], depth: int = 0
        ) -> None:
            """Embed a list of texts, splitting in half on token-limit errors."""
            nonlocal batch_count
            if not texts:
                return
            try:
                inputs = [TextEmbeddingInput(t, "RETRIEVAL_DOCUMENT") for t in texts]
                results = self._embed_model.get_embeddings(inputs)
                for idx, result in zip(indices, results):
                    all_embeddings[idx] = result.values
                batch_count += 1
            except Exception as exc:
                # Vertex raises InvalidArgument when the batch exceeds 20k tokens.
                # Split the batch in half and retry each half independently.
                if depth >= 4 or len(texts) <= 1:
                    log.error(
                        "Embedding failed after splitting, giving up on %d chunk(s): %s",
                        len(texts), exc,
                    )
                    return
                log.warning(
                    "Embedding batch too large (%d items), splitting in half (depth=%d): %s",
                    len(texts), depth, exc,
                )
                mid = len(texts) // 2
                embed_with_split_fallback(indices[:mid], texts[:mid], depth + 1)
                embed_with_split_fallback(indices[mid:], texts[mid:], depth + 1)

        def flush_batch() -> None:
            if not batch_texts:
                return
            embed_with_split_fallback(list(batch_indices), list(batch_texts))

        for i, chunk in enumerate(chunks):
            text = chunk["text"]
            tok_count = len(self._enc.encode(text))

            if tok_count > max_input:
                log.warning(
                    "Chunk %d [%s] exceeds per-input limit (%d > %d); truncating.",
                    i, self.doc_slug, tok_count, max_input,
                )
                text = self._enc.decode(self._enc.encode(text)[:max_input])
                tok_count = max_input

            if batch_tokens + tok_count > batch_limit and batch_texts:
                flush_batch()
                batch_indices = []
                batch_texts = []
                batch_tokens = 0

            batch_indices.append(i)
            batch_texts.append(text)
            batch_tokens += tok_count

        flush_batch()

        return all_embeddings, batch_count

    # ------------------------------------------------------------------
    # Step 7 — write to ChromaDB with structured metadata schema
    # ------------------------------------------------------------------

    def _write_chroma(self, chunks: list[dict], embeddings: list[list[float]]) -> int:
        ids, docs, metas, embs = [], [], [], []
        seen_ids: set[str] = set()
        duplicates = 0

        for chunk, embedding in zip(chunks, embeddings):
            if embedding is None:
                log.warning(
                    "Skipping chunk (no embedding): doc=%s page=%d type=%s",
                    self.doc_slug, chunk.get("page"), chunk.get("chunk_type"),
                )
                continue

            chunk_id = chunk.get("chunk_id") or hashlib.md5(
                f"{self.doc_id}_{chunk['page']}_{chunk['chunk_type']}_{chunk['text'][:50]}".encode()
            ).hexdigest()

            # Skip duplicate IDs — can happen when Gemini returns identical
            # structured items from the same page.
            if chunk_id in seen_ids:
                duplicates += 1
                continue
            seen_ids.add(chunk_id)

            ids.append(chunk_id)
            docs.append(chunk["text"])
            embs.append(embedding)
            metas.append(
                {
                    # Existing fields (backward compat)
                    "product_id": chunk["product_id"],
                    "page_number": chunk["page"],
                    "chunk_type": chunk["chunk_type"],
                    "source": "ingest_v2",
                    # Multi-doc fields
                    "doc_id": self.doc_id,
                    "doc_slug": self.doc_slug,
                    "chunk_id": chunk_id,
                    "parent_chunk_id": chunk.get("parent_chunk_id", ""),
                    "section_title": chunk.get("section_title", "unknown"),
                    "embedding_model": config.embed_model,
                    "ingested_at": chunk.get("ingestion_ts", ""),
                }
            )

        if duplicates:
            log.warning(
                "Dropped %d duplicate chunk ID(s) before ChromaDB write [%s].",
                duplicates, self.doc_slug,
            )

        batch_size = 500
        written = 0
        for i in range(0, len(ids), batch_size):
            self._chroma.upsert(
                ids=ids[i : i + batch_size],
                documents=docs[i : i + batch_size],
                embeddings=embs[i : i + batch_size],
                metadatas=metas[i : i + batch_size],
            )
            written += len(ids[i : i + batch_size])

        return written

    # ------------------------------------------------------------------
    # Step 8 — ingestion metrics summary
    # ------------------------------------------------------------------

    def _print_summary(self, m: IngestionMetrics) -> None:
        elapsed = time.time() - m.start_time
        est_cost = (
            m.gemini_calls * _COST_PER_GEMINI_CALL
            + m.embed_batches * _COST_PER_EMBED_BATCH
        )
        lines = [
            "",
            f"=== Ingestion Summary [{self.doc_slug}] ===",
            f"Product:              {self.product_id}",
            f"Document:             {self.doc_slug}",
            f"Total pages:          {m.total_pages}",
            f"  Processed:          {m.pages_processed}",
            f"  Skipped (cached):   {m.pages_skipped}",
            f"  Failed:             {m.pages_failed}",
            f"Chunks written:       {m.chunks_written}",
            f"  Parent chunks:      {m.parent_chunks}",
            f"  Child chunks:       {m.child_chunks}",
            f"  Vision captions:    {m.vision_captions}",
            f"  Structured OK:      {m.structured_ok}",
            f"  Structured failed:  {m.structured_failed}",
            f"Annotations saved:    {m.annotations_saved}",
            f"Gemini API calls:     {m.gemini_calls}",
            f"Embed batches:        {m.embed_batches}",
            f"Total time:           {elapsed:.1f}s",
            f"Est. API cost:        ~${est_cost:.4f}",
            "=" * (len(f"=== Ingestion Summary [{self.doc_slug}] ===") + 1),
            "",
        ]
        print("\n".join(lines))
        log.info(
            "Ingestion complete [%s] (%.1fs, %d chunks written)",
            self.doc_slug, elapsed, m.chunks_written,
        )


# ---------------------------------------------------------------------------
# Multi-PDF orchestration
# ---------------------------------------------------------------------------


def ingest_product(product_id: str, fresh: bool = False) -> list[dict]:
    """Ingest all PDFs for a product. Returns list of per-PDF report dicts.

    Args:
        product_id: Must be registered in products.json.
        fresh:      If True, delete existing ChromaDB collection and all
                    state files before ingesting.
    """
    from config import get_product  # avoid circular at module level

    product = get_product(product_id)
    pdf_paths = product.get_pdf_paths()

    if not pdf_paths:
        raise FileNotFoundError(
            f"No PDFs found in {product.pdf_directory!r} for product {product_id!r}."
        )

    log.info(
        "Product %r: found %d PDF(s) in %s",
        product_id, len(pdf_paths), product.pdf_directory,
    )

    if fresh:
        _clear_product_data(product_id)

    reports = []
    total_start = time.time()

    for pdf_path in pdf_paths:
        log.info("--- Starting %s ---", pdf_path.name)
        ingester = Ingester(product_id, str(pdf_path), product=product)
        report = ingester.run()
        reports.append(report)

    # Combined summary across all PDFs
    total_elapsed = time.time() - total_start
    total_chunks = sum(r["chunks_written"] for r in reports)
    total_pages = sum(r["pages_processed"] for r in reports)
    total_skipped = sum(r["pages_skipped"] for r in reports)

    print(
        f"\n{'='*50}\n"
        f"  COMBINED SUMMARY — {product_id}\n"
        f"  Documents ingested: {len(reports)}\n"
        f"  Total pages processed: {total_pages} (skipped: {total_skipped})\n"
        f"  Total chunks written: {total_chunks}\n"
        f"  Total time: {total_elapsed:.1f}s\n"
        f"{'='*50}\n"
    )

    return reports


def _clear_product_data(product_id: str) -> None:
    """Delete ChromaDB collection, state files, and rendered assets for a product."""
    import shutil

    log.info("--fresh: clearing existing data for product %r", product_id)

    # Delete ChromaDB collection
    try:
        chroma_client = chromadb.PersistentClient(path=config.chroma_path)
        chroma_client.delete_collection(product_id)
        log.info("Deleted ChromaDB collection %r", product_id)
    except Exception as exc:
        log.warning("Could not delete ChromaDB collection: %s", exc)

    # Delete rendered assets (pages + annotations)
    assets_dir = Path(config.assets_path) / product_id
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
        log.info("Deleted assets directory: %s", assets_dir)
