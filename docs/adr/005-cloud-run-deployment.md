# ADR 005 — Single-container GCP Cloud Run deployment

**Status:** Accepted  
**Date:** 2025-04

---

## Context

The app has two parts: a FastAPI backend and a React SPA. Options for hosting:

| Option | Frontend | Backend | Credential surface | Cost |
|--------|----------|---------|-------------------|------|
| A — split hosting | Vercel | Cloud Run | Two services, CORS config | Free tiers on both |
| **B — single container** | `frontend/dist/` baked in | FastAPI + StaticFiles | One service | One Cloud Run bill |
| C — Cloud Run + Cloud Storage | GCS bucket | Cloud Run | Two services, CORS config | Storage + egress |

Option A requires CORS headers, two deploy pipelines, and two secret stores. Option C adds GCS bucket management and CDN configuration. Option B is the simplest: one image, one deploy, one secret (`ANTHROPIC_API_KEY`), no CORS.

FastAPI's `StaticFiles` mount serves the Vite-built SPA from `/assets` and the `spa_fallback` route returns `index.html` for any path not matched by an API route — React Router handles client-side navigation on the SPA side.

---

## Decision

Multi-stage Dockerfile:

```
Stage 1 (node:20-slim)          Stage 2 (python:3.11-slim)
──────────────────────          ───────────────────────────
npm ci                          COPY --from=stage1 /app/dist  frontend/dist/
npm run build → /app/dist       pip install -r requirements.txt
                                ENV HF_HOME=/app/.cache/hf
                                RUN python -c "from sentence_transformers import ..."
                                CMD uvicorn main:app --host 0.0.0.0 --port 8080
```

`ENV HF_HOME` + the warm-up `RUN` step bakes the embedding model weights (~80 MB) into the image layer. Cloud Run sees a cold start with no network download — the model is already on disk.

Deploy target: Cloud Run, `us-central1`, 2 GiB RAM, 2 vCPU, min-instances 0.

---

## Consequences

- 2 GiB is the minimum comfortable memory: sentence-transformers (~380 MB) + ChromaDB index + Python runtime leave ~1 GiB for the FastAPI workers and Anthropic response buffering. Going below 2 GiB risks OOM on the first request.
- `--min-instances 0` scales to zero when idle, so there's no cost during off-hours. Cold start after scale-to-zero is fast (model is in the layer; only Python imports run).
- The `ANTHROPIC_API_KEY` secret is injected via Cloud Run's `--set-secrets` flag, which maps a Secret Manager secret version to an environment variable. The key never touches `cloudbuild.yaml` or source control.
- GCP credentials (`GOOGLE_CLOUD_PROJECT`) are **not** mounted in the Cloud Run service — serving requires only the Anthropic key. Re-ingestion (if needed) runs locally with `uv run python run_ingest.py`.
