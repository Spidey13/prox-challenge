# ADR 001 — Dual-embedding architecture (Vertex for ingestion, local for serving)

**Status:** Accepted  
**Date:** 2025-04

---

## Context

RAG systems must align the query embedding model with the document embedding model, or retrieval degrades silently. Two candidate approaches:

| Option | Ingestion model | Serving model | Reviewer requirement |
|--------|-----------------|---------------|----------------------|
| A — full Vertex | `text-embedding-004` (768-dim) | `text-embedding-004` | `GOOGLE_CLOUD_PROJECT` + credentials |
| B — full local | `all-MiniLM-L6-v2` (384-dim) | `all-MiniLM-L6-v2` | none |
| **C — dual** | `text-embedding-004` (768-dim) | `all-MiniLM-L6-v2` (384-dim) | `ANTHROPIC_API_KEY` only |

Option A requires reviewers and Cloud Run to hold GCP credentials for every query. Option B loses ingestion quality (MiniLM has no vision caption understanding). Option C gets the best of both: Vertex quality for the offline ingestion step, then a ~80 MB model baked into the image for zero-credential serving.

---

## Decision

Use Vertex `text-embedding-004` during ingestion. After ingestion, run `migrate_embeddings.py` to re-encode all stored chunks with `sentence-transformers/all-MiniLM-L6-v2` and overwrite the ChromaDB collection. Ship the converted `chroma_db/` in the repo.

At query time, embed the user's query with `all-MiniLM-L6-v2` — the same model as the stored vectors. Cosine similarity is valid.

---

## Consequences

- Reviewers and Cloud Run only need `ANTHROPIC_API_KEY`.
- `chroma_db/` is committed to the repo (~a few MB compressed). This is fine for a single-product demo; it would move to a mounted volume or Cloud Storage for multi-product production use.
- Re-ingestion still requires GCP credentials — that path is isolated to `ingest.py` / `run_ingest.py` and is not needed to run the agent.
- The dimension mismatch (768 vs 384) is resolved at migration time, not at query time. There is no runtime conversion.

```
Ingestion (offline, GCP)           Serving (online, no GCP)
─────────────────────────          ────────────────────────
PDF → Gemini caption               User query
      │                                    │
      ▼                                    ▼
Vertex text-embedding-004        all-MiniLM-L6-v2 (local)
  768-dim vectors                  384-dim vector
      │                                    │
      ▼                                    ▼
ChromaDB (768-dim)  ──migrate──►  ChromaDB (384-dim)  ◄── cosine search
```
