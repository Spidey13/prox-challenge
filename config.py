"""Application configuration loaded from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Product registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProductInfo:
    """Metadata for one product loaded from products.json."""

    product_id: str
    name: str
    description: str
    pdf_directory: str
    persona: str
    structured_keywords: tuple[str, ...]
    # Routing / prompt injection — fault diagnosis keywords for this domain
    fault_triggers: tuple[str, ...]
    fault_examples: tuple[str, ...]
    # Artifact types available for this product: {type_key: prompt_template}
    artifact_types: dict[str, str]
    # Frontend scenario cards for the empty state
    scenarios: tuple[dict, ...]
    # Escalation copy for job card no-path modal
    escalation_copy: dict[str, Any]

    def get_pdf_paths(self) -> list[Path]:
        """Return sorted list of all PDFs in pdf_directory."""
        base = Path(self.pdf_directory)
        if not base.exists():
            return []
        return sorted(base.glob("*.pdf"))


def load_product_registry(
    registry_path: str | None = None,
) -> dict[str, ProductInfo]:
    """Load products.json and return a mapping of product_id -> ProductInfo.

    Falls back to an empty dict (not an error) so the agent can still serve
    from a pre-built ChromaDB even if the registry file is missing.
    """
    path = Path(registry_path or os.getenv("PRODUCTS_FILE", "products.json"))
    if not path.exists():
        return {}
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Could not parse {path}: {exc}") from exc

    registry: dict[str, ProductInfo] = {}
    for pid, entry in raw.items():
        registry[pid] = ProductInfo(
            product_id=pid,
            name=entry["name"],
            description=entry["description"],
            pdf_directory=entry.get("pdf_directory", "files"),
            persona=entry.get("persona", "Be direct, precise, and practical."),
            structured_keywords=tuple(entry.get("structured_keywords", [])),
            fault_triggers=tuple(entry.get("fault_triggers", [])),
            fault_examples=tuple(entry.get("fault_examples", [])),
            artifact_types=dict(entry.get("artifact_types", {})),
            scenarios=tuple(entry.get("scenarios", [])),
            escalation_copy=dict(entry.get("escalation_copy", {})),
        )
    return registry


def get_product(product_id: str, registry: dict[str, ProductInfo] | None = None) -> ProductInfo:
    """Look up a product by ID; raises KeyError with a helpful message if not found."""
    reg = registry if registry is not None else _registry
    if product_id not in reg:
        known = ", ".join(sorted(reg.keys())) or "(none registered)"
        raise KeyError(
            f"Unknown product_id {product_id!r}. "
            f"Registered products: {known}. "
            "Add an entry to products.json."
        )
    return reg[product_id]


# Module-level registry loaded once at import time.
_registry: dict[str, ProductInfo] = load_product_registry()


# ---------------------------------------------------------------------------
# App config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    """Claude via direct Anthropic API; Gemini + embeddings via Vertex AI."""

    # Anthropic (required for agent)
    anthropic_api_key: str

    # Google Cloud (required for ingestion; optional for serving-only deployments)
    google_cloud_project: str
    vertex_location: str

    # Paths
    chroma_path: str
    assets_path: str
    default_product_id: str

    # Model IDs — direct Anthropic API format
    embed_model: str          # Vertex text-embedding-004 (ingestion only)
    local_embed_model: str    # sentence-transformers model (query-time serving)
    haiku: str
    sonnet: str
    gemini: str

    # Ingestion / retrieval knobs
    chunk_size: int
    chunk_overlap: int
    top_k: int
    page_dpi: int
    gemini_rpm_delay: float
    ingest_workers: int
    embed_batch_token_limit: int
    embed_max_input_tokens: int


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(
            f"Missing required environment variable: {name}. "
            "Set it in .env (see .env.example)."
        )
    return value


def _optional(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip() or default


def load_config() -> Config:
    return Config(
        anthropic_api_key=_require("ANTHROPIC_API_KEY"),
        # google_cloud_project falls back to empty string — only required for ingestion
        google_cloud_project=_optional("GOOGLE_CLOUD_PROJECT", ""),
        vertex_location=_optional("VERTEX_LOCATION", "us-central1"),
        chroma_path=_optional("CHROMA_PATH", "./chroma_db"),
        assets_path=_optional("ASSETS_PATH", "./assets"),
        default_product_id=_optional("DEFAULT_PRODUCT_ID", "trane_precedent"),
        embed_model=_optional("EMBED_MODEL", "text-embedding-004"),
        local_embed_model=_optional("LOCAL_EMBED_MODEL", "all-MiniLM-L6-v2"),
        # Direct Anthropic API model IDs (not Vertex @snapshot format)
        haiku=_optional("HAIKU", "claude-haiku-4-5-20251001"),
        sonnet=_optional("SONNET", "claude-sonnet-4-5-20250929"),
        # Vertex publisher model id. New projects: use 2.5+ (2.0-flash-001 restricted for new customers per Google).
        gemini=_optional("GEMINI", "gemini-2.5-flash"),
        chunk_size=int(os.getenv("CHUNK_SIZE", "500")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "50")),
        top_k=int(os.getenv("TOP_K", "5")),
        page_dpi=int(os.getenv("PAGE_DPI", "200")),
        gemini_rpm_delay=float(os.getenv("GEMINI_RPM_DELAY", "4.1")),
        ingest_workers=int(os.getenv("INGEST_WORKERS", "3")),
        embed_batch_token_limit=int(os.getenv("EMBED_BATCH_TOKEN_LIMIT", "15000")),
        embed_max_input_tokens=int(os.getenv("EMBED_MAX_INPUT_TOKENS", "2000")),
    )


config = load_config()
