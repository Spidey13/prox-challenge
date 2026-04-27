"""Local-only ingestion pipeline — no GCP credentials required.

Uses PyMuPDF for text extraction and sentence-transformers/all-MiniLM-L6-v2
for embeddings. Produces the same ChromaDB collection format as the main
ingest.py pipeline so the agent serves correctly without modification.

Usage:
    uv run python local_ingest.py [product_id] [--fresh]
    uv run python local_ingest.py trane_precedent --fresh
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import chromadb
import fitz  # pymupdf
import tiktoken

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------
CHUNK_SIZE = 500        # target tokens per text chunk
CHUNK_OVERLAP = 50      # token overlap between consecutive child chunks
TOP_K = 5

_TOKENIZER = tiktoken.get_encoding("cl100k_base")


def _tok(text: str) -> list[int]:
    return _TOKENIZER.encode(text)


def _chunk_text(text: str, max_tokens: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    tokens = _tok(text)
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunks.append(_TOKENIZER.decode(tokens[start:end]))
        if end == len(tokens):
            break
        start = end - overlap
    return chunks


def _doc_slug(pdf_path: Path) -> str:
    """Convert a PDF filename to a URL-friendly slug."""
    stem = pdf_path.stem.lower()
    stem = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")
    return stem


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Per-page extraction
# ---------------------------------------------------------------------------

def _extract_page(
    doc: fitz.Document,
    page_index: int,
    product_id: str,
    product_name: str,
    doc_slug: str,
    doc_id: str,
) -> list[dict]:
    """Extract all text chunks from a single PDF page."""
    page = doc[page_index]
    raw_text = page.get_text("text").strip()
    if not raw_text:
        return []

    page_header = f"[{product_name} | {doc_slug} | Page {page_index + 1}]"
    full_text = f"{page_header}\n{raw_text}"

    now = datetime.now(timezone.utc).isoformat()
    chunks: list[dict] = []

    # Parent chunk — full page text
    parent_id = _md5(f"{doc_id}:{page_index}:parent")
    chunks.append({
        "id": parent_id,
        "text": full_text[:4000],  # cap at ~4k chars
        "metadata": {
            "product_id": product_id,
            "doc_id": doc_id,
            "doc_slug": doc_slug,
            "page_number": page_index,
            "chunk_type": "text",
            "parent_chunk_id": "",
            "ingested_at": now,
        },
    })

    # Child chunks — windowed splits of the raw text
    sub_chunks = _chunk_text(raw_text)
    for i, sub in enumerate(sub_chunks):
        if not sub.strip():
            continue
        enriched = f"{page_header}\n{sub}"
        child_id = _md5(f"{doc_id}:{page_index}:child:{i}")
        chunks.append({
            "id": child_id,
            "text": enriched,
            "metadata": {
                "product_id": product_id,
                "doc_id": doc_id,
                "doc_slug": doc_slug,
                "page_number": page_index,
                "chunk_type": "text",
                "parent_chunk_id": parent_id,
                "ingested_at": now,
            },
        })

    return chunks


# ---------------------------------------------------------------------------
# Main ingestion function
# ---------------------------------------------------------------------------

def local_ingest(product_id: str, fresh: bool = False) -> None:
    from config import get_product, config

    # Load product
    product = get_product(product_id)
    pdf_paths = product.get_pdf_paths()
    if not pdf_paths:
        log.warning("No PDFs found for product '%s' in '%s'", product_id, product.pdf_directory)
        return

    log.info("Product '%s': found %d PDF(s)", product_id, len(pdf_paths))

    # Load local embedding model
    log.info("Loading local embedding model '%s'…", config.local_embed_model)
    from sentence_transformers import SentenceTransformer
    embed_model = SentenceTransformer(config.local_embed_model)

    # Connect to ChromaDB
    chroma = chromadb.PersistentClient(config.chroma_path)

    if fresh:
        try:
            chroma.delete_collection(product_id)
            log.info("Deleted existing collection '%s'", product_id)
        except Exception:
            log.info("No existing collection '%s' to delete", product_id)

    collection = chroma.get_or_create_collection(
        name=product_id,
        metadata={"hnsw:space": "cosine"},
    )

    # Process each PDF
    for pdf_path in pdf_paths:
        doc_slug = _doc_slug(pdf_path)
        doc_id = f"{product_id}/{doc_slug}"
        log.info("Processing %s  (doc_id=%s)", pdf_path.name, doc_id)

        doc = fitz.open(str(pdf_path))
        all_chunks: list[dict] = []
        page_count = len(doc)

        # Render page PNGs for citation viewer
        pages_dir = Path(config.assets_path) / product_id / "pages" / doc_slug
        pages_dir.mkdir(parents=True, exist_ok=True)
        page_dpi = int(config.page_dpi)

        for page_idx in range(page_count):
            # Render page image
            page = doc[page_idx]
            zoom = page_dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            png_path = pages_dir / f"page_{page_idx}.png"
            pix.save(str(png_path))

            # Extract text chunks
            page_chunks = _extract_page(
                doc=doc,
                page_index=page_idx,
                product_id=product_id,
                product_name=product.name,
                doc_slug=doc_slug,
                doc_id=doc_id,
            )
            all_chunks.extend(page_chunks)

            if (page_idx + 1) % 20 == 0:
                log.info("  … %d pages processed, %d chunks + images so far", page_idx + 1, len(all_chunks))

        doc.close()
        log.info("  Rendered %d page images to %s", page_count, pages_dir)

        if not all_chunks:
            log.warning("No text extracted from %s", pdf_path.name)
            continue

        log.info("  Extracted %d chunks from %d pages", len(all_chunks), page_count)

        # Embed in batches of 64
        texts = [c["text"] for c in all_chunks]
        batch_size = 64
        embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            vecs = embed_model.encode(batch, show_progress_bar=False).tolist()
            embeddings.extend(vecs)
            log.info("  Embedded %d / %d chunks", min(i + batch_size, len(texts)), len(texts))

        # Upsert to ChromaDB in batches of 500
        upsert_batch = 500
        for i in range(0, len(all_chunks), upsert_batch):
            batch_chunks = all_chunks[i : i + upsert_batch]
            batch_embeddings = embeddings[i : i + upsert_batch]
            collection.upsert(
                ids=[c["id"] for c in batch_chunks],
                embeddings=batch_embeddings,
                documents=[c["text"] for c in batch_chunks],
                metadatas=[c["metadata"] for c in batch_chunks],
            )

        log.info("  Upserted %d chunks for %s", len(all_chunks), pdf_path.name)

    final_count = collection.count()
    log.info("Done. Collection '%s' now has %d chunks total.", product_id, final_count)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Local-only PDF ingestion (no GCP required)."
    )
    parser.add_argument("product_id", nargs="?", help="Product ID from products.json")
    parser.add_argument("--fresh", action="store_true", help="Delete and rebuild the collection")
    parser.add_argument("--list", action="store_true", help="List registered products and exit")
    args = parser.parse_args()

    from config import _registry
    if args.list:
        for pid, p in _registry.items():
            pdfs = p.get_pdf_paths()
            print(f"  {pid:20s}  {p.name}  ({len(pdfs)} PDFs)")
        raise SystemExit(0)

    if not args.product_id:
        from config import config as _config
        args.product_id = _config.default_product_id

    local_ingest(args.product_id, fresh=args.fresh)
