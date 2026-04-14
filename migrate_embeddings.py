"""Re-embed ChromaDB from Vertex text-embedding-004 to sentence-transformers.

This migration reads all existing documents and metadata from ChromaDB,
re-embeds them with all-MiniLM-L6-v2 (384-dim, runs on CPU, no API key),
and writes them back. This enables query-time serving without GCP credentials.

Usage:
    python migrate_embeddings.py [--product-id vulcan_220]
"""

from __future__ import annotations

import argparse
import logging
import time

import chromadb
from sentence_transformers import SentenceTransformer

from config import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

LOCAL_MODEL_NAME = "all-MiniLM-L6-v2"
BATCH_SIZE = 256


def migrate(product_id: str) -> None:
    """Re-embed all chunks for a product using the local model."""
    start = time.time()

    log.info("Loading local embedding model: %s", LOCAL_MODEL_NAME)
    model = SentenceTransformer(LOCAL_MODEL_NAME)

    client = chromadb.PersistentClient(path=config.chroma_path)

    try:
        old_collection = client.get_collection(name=product_id)
    except Exception as exc:
        log.error("Collection %r not found: %s", product_id, exc)
        return

    # Read everything from the existing collection
    total = old_collection.count()
    log.info("Collection %r has %d chunks", product_id, total)

    if total == 0:
        log.info("Nothing to migrate.")
        return

    # Fetch all items (ChromaDB supports get() with no filters to return all)
    all_data = old_collection.get(
        include=["documents", "metadatas"],
        limit=total,
    )

    ids = all_data["ids"]
    documents = all_data["documents"]
    metadatas = all_data["metadatas"]

    log.info("Re-embedding %d chunks with %s ...", len(documents), LOCAL_MODEL_NAME)

    # Embed in batches
    all_embeddings = []
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i : i + BATCH_SIZE]
        embeddings = model.encode(batch, show_progress_bar=False, normalize_embeddings=True)
        all_embeddings.extend(embeddings.tolist())
        log.info("  Embedded batch %d-%d / %d", i, min(i + BATCH_SIZE, len(documents)), len(documents))

    # Update the embedding_model metadata
    for meta in metadatas:
        meta["embedding_model"] = LOCAL_MODEL_NAME

    # Delete old collection and recreate with new embeddings
    log.info("Deleting old collection and recreating with new embeddings ...")
    client.delete_collection(name=product_id)
    new_collection = client.get_or_create_collection(
        name=product_id,
        metadata={"hnsw:space": "cosine"},
    )

    # Write in batches (ChromaDB has a batch size limit)
    write_batch = 500
    written = 0
    for i in range(0, len(ids), write_batch):
        new_collection.upsert(
            ids=ids[i : i + write_batch],
            documents=documents[i : i + write_batch],
            embeddings=all_embeddings[i : i + write_batch],
            metadatas=metadatas[i : i + write_batch],
        )
        written += len(ids[i : i + write_batch])

    elapsed = time.time() - start
    log.info(
        "Migration complete: %d chunks re-embedded in %.1fs (model: %s, dim: %d)",
        written, elapsed, LOCAL_MODEL_NAME, len(all_embeddings[0]),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-embed ChromaDB with local model")
    parser.add_argument("--product-id", default="vulcan_220")
    args = parser.parse_args()
    migrate(args.product_id)
