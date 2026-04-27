"""Smoke test — run this BEFORE full ingestion to validate the whole stack.

Usage:
    python tests/smoke_test.py

Tests (in order):
  1. Config loads and ANTHROPIC_API_KEY is set
  2. Direct Anthropic API key works — Haiku responds
  3. Sonnet responds (needed for render_artifact)
  4. Tool_use round-trip — Claude calls search_knowledge, we feed back a
     fake result, Claude produces a final answer
  5. Vertex embedding (only if GOOGLE_CLOUD_PROJECT is set)
  6. Single-page ingest (page 0 of owner-manual.pdf)

Each test prints PASS or FAIL with a clear message.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

# Ensure repo root is on sys.path when running from tests/
sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def run(label: str, fn):
    try:
        fn()
        print(f"  [{PASS}] {label}")
        return True
    except Exception as exc:
        print(f"  [{FAIL}] {label}")
        print(f"         {exc}")
        if os.getenv("SMOKE_VERBOSE"):
            traceback.print_exc()
        return False


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def test_config():
    from config import config  # noqa: PLC0415
    assert config.anthropic_api_key, "ANTHROPIC_API_KEY is empty"
    assert config.anthropic_api_key.startswith("sk-ant-"), (
        f"Key looks wrong: {config.anthropic_api_key[:12]}…"
    )


def test_haiku():
    from config import config
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    resp = client.messages.create(
        model=config.haiku,
        max_tokens=32,
        messages=[{"role": "user", "content": "Reply with the single word: READY"}],
    )
    text = resp.content[0].text.strip()
    assert "READY" in text.upper(), f"Unexpected response: {text!r}"


def test_sonnet():
    from config import config
    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    resp = client.messages.create(
        model=config.sonnet,
        max_tokens=32,
        messages=[{"role": "user", "content": "Reply with the single word: READY"}],
    )
    text = resp.content[0].text.strip()
    assert "READY" in text.upper(), f"Unexpected response: {text!r}"


def test_tool_use_loop():
    """Full tool_use round-trip with a fake search result injected."""
    from config import config

    # Minimal tool definition matching our real schema
    tools = [
        {
            "name": "search_knowledge",
            "description": "Search the equipment manual.",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        }
    ]

    client = anthropic.Anthropic(api_key=config.anthropic_api_key)
    messages = [
        {"role": "user", "content": "What does the RTRM system LED blinking twice every two seconds indicate?"}
    ]

    resp = client.messages.create(
        model=config.haiku,
        max_tokens=256,
        system="You are a field service support agent. Use search_knowledge before answering.",
        tools=tools,
        tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        messages=messages,
    )

    assert resp.stop_reason == "tool_use", (
        f"Expected stop_reason=tool_use, got {resp.stop_reason!r}"
    )
    tool_block = next(b for b in resp.content if b.type == "tool_use")
    assert tool_block.name == "search_knowledge"

    # Feed back a fake tool result
    fake_result = json.dumps([{
        "text": "At 240V, MIG at 200A: duty cycle 30%. Maximum continuous amperage 200A.",
        "page_number": 14,
        "chunk_type": "structured",
    }])

    messages.append({"role": "assistant", "content": resp.content})
    messages.append({
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": tool_block.id, "content": fake_result}],
    })

    resp2 = client.messages.create(
        model=config.haiku,
        max_tokens=256,
        system="You are a welding support agent. Use search_knowledge before answering.",
        tools=tools,
        tool_choice={"type": "auto", "disable_parallel_tool_use": True},
        messages=messages,
    )

    assert resp2.stop_reason == "end_turn", (
        f"Expected end_turn after tool result, got {resp2.stop_reason!r}"
    )
    final_text = next(b.text for b in resp2.content if hasattr(b, "text"))
    assert "30" in final_text or "duty" in final_text.lower(), (
        f"Answer doesn't mention duty cycle: {final_text!r}"
    )


def test_vertex_embedding():
    from config import config
    if not config.google_cloud_project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT not set — skipping (set it to test)")

    import vertexai
    from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

    vertexai.init(project=config.google_cloud_project, location=config.vertex_location)
    model = TextEmbeddingModel.from_pretrained(config.embed_model)
    results = model.get_embeddings([TextEmbeddingInput("duty cycle", "RETRIEVAL_QUERY")])
    vec = results[0].values
    assert len(vec) > 100, f"Embedding vector too short: {len(vec)}"


def test_single_page_ingest():
    """Ingest only page 0 of owner-manual.pdf as a quick pipeline check."""
    from config import config

    if not config.google_cloud_project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT not set — skipping")

    pdf_path = Path(__file__).parent.parent / "files" / "owner-manual.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Monkey-patch Ingester to process only page 0
    import fitz
    from ingest import Ingester

    ingester = Ingester("trane_precedent_smoke", str(pdf_path))
    ingester._init_clients()
    ingester._make_dirs()

    doc = fitz.open(str(pdf_path))
    page = doc[0]
    png, pw, ph = ingester._render_page(page, 0)
    annotations = ingester._extract_bboxes(page, 0, pw, ph)
    caption = ingester._gemini_caption(png, 0)
    assert caption, "Gemini returned empty caption for page 0"
    doc.close()
    print(f"         caption preview: {caption[:80]}…")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\nTrane Precedent RTU - Smoke Tests\n")

    results = [
        run("Config loads + ANTHROPIC_API_KEY set",   test_config),
        run("Haiku responds (direct Anthropic API)",   test_haiku),
        run("Sonnet responds (direct Anthropic API)",  test_sonnet),
        run("tool_use round-trip (search -> answer)",   test_tool_use_loop),
        run("Vertex embedding (needs GCP project)",    test_vertex_embedding),
        run("Single-page ingest (page 0, needs GCP)", test_single_page_ingest),
    ]

    passed = sum(results)
    total  = len(results)
    print(f"\n{passed}/{total} passed\n")

    # Exit 1 if critical tests (1-4) failed; Vertex tests are optional
    critical = results[:4]
    sys.exit(0 if all(critical) else 1)
