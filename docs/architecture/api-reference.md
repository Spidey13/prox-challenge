# API Reference

All routes are served by FastAPI on port 8080. In development the frontend (port 5173) proxies to 8080. In production both are on 8080 (single container).

---

## POST /ask

Stream a response to a user message via Server-Sent Events.

**Request body**

```json
{
  "message":          "string (required)",
  "product_id":       "string (required)",
  "conversation_id":  "string (required)",
  "image_data":       "string | null  — base64-encoded image",
  "image_media_type": "string | null  — e.g. image/jpeg",
  "fault_category":   "string | null  — e.g. wont_start",
  "intent_known":     "boolean        — true when fault_category set by UI button"
}
```

**SSE event stream**

| Event `type` | Payload | When |
|---|---|---|
| `token` | `{"content": "..."}` | Each text delta during synthesis |
| `job_card_start` | `{"metadata": {equipment, priority, fault_description, asset_id}}` | Fault path only — before steps |
| `job_card_step` | `{"step": {id, instruction, note, yes_label, no_label, yes_next, no_next, source_citation, artifact_trigger}}` | One per step, in order |
| `done` | `{"suggestions": [...], "artifact": {...}\|null, "job_card": {...}\|null, "images": [...]}` | Always last |

**Routing by `intent_known`**

```
intent_known=true + fault_category set
  └─► skip Haiku entirely
      search_knowledge(fault_category) → generate_job_card
      total: 1 Sonnet API call

intent_known=false
  └─► Haiku classifies intent (1 call)
      tool loop (up to 8 calls)
      synthesis stream (1 call)
```

**Cache behavior**: fault button queries key on `{product_id}:{fault_category}`. Text/photo queries key on the raw message string. Cache hits replay the SSE stream without calling any model.

---

## POST /ingest

Run the PDF ingestion pipeline. Blocking — use for initial setup or on-demand re-ingestion.

**Request body**

```json
{
  "product_id": "string (required)",
  "pdf_path":   "string | null  — omit to ingest all PDFs in the product's directory",
  "fresh":      "boolean        — clear existing data first"
}
```

**Response**

```json
{
  "status": "ok",
  "mode": "single | multi",
  "chunks_written": 1234,
  "pages_processed": 56,
  "annotations_saved": 56
}
```

---

## POST /explain-step

Fetch the manual page image and optional artifact for a job card step. Used when the user taps the manual-ref button on a step.

**Request body**

```json
{
  "product_id":      "string (required)",
  "source_citation": "string  — e.g. p.34 §6.2",
  "instruction":     "string | null  — used for fallback page lookup via knowledge base",
  "artifact_type":   "string | null  — if set, Sonnet renders an HTML artifact for this step",
  "fault_context":   "string | null  — context passed to the artifact prompt"
}
```

**Response**

```json
{
  "manual_image": {
    "page_number": 33,
    "doc_slug": "owner-manual",
    "url": "/image/vulcan_220/owner-manual/33",
    "highlight": {"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.3, "label": "Terminal strip"} | null
  },
  "artifact_html": "<!DOCTYPE html>...</html>" | null
}
```

Page lookup priority: parsed `p.N` from `source_citation` → fallback to `search_knowledge(instruction)` top result if the citation is missing or resolves to page 0.

---

## GET /image/{product_id}/{doc_slug}/{page_number}

Serve a rendered page PNG. Response is cached for 1 hour (`Cache-Control: max-age=3600`).

Assets live at `assets/{product_id}/pages/{doc_slug}/page_{page_number}.png`.

Returns 404 if the image does not exist.

---

## GET /annotations/{product_id}/{doc_slug}/{page_number}

Return the annotation JSON for a page. Annotations are stored at `assets/{product_id}/annotations/{doc_slug}/page_{page_number}.json`.

Each annotation:

```json
{
  "label": "Terminal strip",
  "bbox_pct": {"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.3}
}
```

Returns 404 if no annotation file exists for the page.

---

## GET /documents/{product_id}

List all ingested documents for a product.

**Response**

```json
{
  "product_id": "vulcan_220",
  "documents": [
    {"doc_slug": "owner-manual", "page_count": 56},
    {"doc_slug": "quick-start",  "page_count": 4}
  ]
}
```

---

## GET /health

Returns `{"status": "ok", "version": "1.0.0"}`. Used by Cloud Run health checks.

---

## SPA fallback

Any path not matched by an API route returns `frontend/dist/index.html`. React Router handles client-side navigation. This route is only mounted when `frontend/dist/` exists (production Docker build).

---

## Error handling

All streaming errors are surfaced as a `done` event with an `error` field rather than an HTTP 4xx/5xx, so the SSE stream closes cleanly:

```json
{"type": "done", "suggestions": [], "artifact": null, "images": [], "error": "..."}
```

Non-streaming routes return standard FastAPI `HTTPException` with the appropriate status code.
