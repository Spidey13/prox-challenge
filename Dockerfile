# ── Stage 1: Build the React frontend ──────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install --silent
COPY frontend/ ./
RUN npm run build          # outputs to /frontend/dist


# ── Stage 2: Python backend ─────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY . .

# Pre-download the HuggingFace embedding model into the Docker image
# This prevents an 80MB download and model init delay on every Cloud Run cold start
ENV HF_HOME=/app/.cache/huggingface
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy built frontend (from Stage 1) into the location FastAPI will serve from
COPY --from=frontend-build /frontend/dist ./frontend/dist

# chroma_db/ and assets/ are already in the repo (pre-ingested, all-MiniLM-L6-v2 embeddings).
# No GCP credentials needed at runtime — only ANTHROPIC_API_KEY.

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
