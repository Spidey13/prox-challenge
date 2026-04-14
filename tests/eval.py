"""Evaluation harness for the Vulcan OmniPro 220 support agent.

Calls POST /ask for each test case and checks assertions against the
structured response. Run after ingestion and with the backend server running.

Usage:
    python tests/eval.py [--base-url http://localhost:8080]

TODO: add LLM-as-judge — call Claude to verify factual consistency of
response against retrieved chunks.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

import httpx

# ---------------------------------------------------------------------------
# Test case definition
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    query: str
    must_contain: list[str] = field(default_factory=list)
    must_trigger_artifact: str | None = None
    must_surface_image: bool = False
    must_cite_page: bool = False
    preferred_chunk_type: str | None = None


TEST_CASES: list[TestCase] = [
    TestCase(
        query="What is the duty cycle for MIG welding at 200A on 240V?",
        must_contain=["duty cycle", "%"],
        must_trigger_artifact="duty_cycle_calculator",
        must_cite_page=True,
    ),
    TestCase(
        query="What polarity setup do I need for TIG welding?",
        must_contain=["electrode", "negative", "positive"],
        must_trigger_artifact="polarity_diagram",
        must_surface_image=True,
    ),
    TestCase(
        query="I'm getting porosity in my flux-cored welds. What should I check?",
        must_contain=["porosity", "gas", "wire"],
        must_trigger_artifact="troubleshooting_flowchart",
        must_cite_page=True,
    ),
    TestCase(
        query="What wire feed speed for 1/4 inch steel with MIG?",
        must_contain=["ipm", "wire speed"],
        preferred_chunk_type="structured",
        must_cite_page=True,
    ),
    TestCase(
        query="Show me the front panel controls",
        must_surface_image=True,
        must_contain=["panel", "control"],
    ),
]

PRODUCT_ID = "vulcan_220"
CONVERSATION_ID = "eval_run_001"


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

def check_must_contain(answer_lower: str, keywords: list[str]) -> tuple[bool, str]:
    missing = [kw for kw in keywords if kw.lower() not in answer_lower]
    if missing:
        return False, f"missing keywords: {missing}"
    return True, ""


def check_artifact(artifact: dict | None, expected_type: str) -> tuple[bool, str]:
    if artifact is None:
        return False, "no artifact returned"
    if artifact.get("type") != expected_type:
        return False, f"artifact type {artifact.get('type')!r} != expected {expected_type!r}"
    if not artifact.get("html") or len(artifact["html"]) < 50:
        return False, "artifact html too short or missing"
    return True, ""


def check_image(images: list) -> tuple[bool, str]:
    if not images:
        return False, "no images returned"
    return True, ""


def check_page_cited(answer_lower: str) -> tuple[bool, str]:
    # Loose check: "page" followed by any digit anywhere in the answer
    import re
    if re.search(r"page\s+\d+", answer_lower):
        return True, ""
    return False, "no page reference found in answer"


# ---------------------------------------------------------------------------
# SSE stream consumer
# ---------------------------------------------------------------------------

def consume_sse(response: httpx.Response) -> dict:
    """Parse SSE stream from /ask and return the `done` event payload."""
    accumulated = ""
    done_event: dict = {}

    for line in response.iter_lines():
        if not line.startswith("data: "):
            continue
        raw = line[6:].strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue

        if event.get("type") == "token":
            accumulated += event.get("content", "")
        elif event.get("type") == "done":
            done_event = event
            break

    done_event.setdefault("answer", accumulated)
    return done_event


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_eval(base_url: str = "http://localhost:8080") -> None:
    total = len(TEST_CASES)
    passed = 0
    failed = 0

    print(f"\n{'='*60}")
    print(f"  Vulcan OmniPro 220 — Agent Eval  ({total} tests)")
    print(f"  Backend: {base_url}")
    print(f"{'='*60}\n")

    for i, tc in enumerate(TEST_CASES, 1):
        label = tc.query[:55] + ("…" if len(tc.query) > 55 else "")
        failures: list[str] = []

        try:
            with httpx.Client(base_url=base_url, timeout=120) as client:
                with client.stream(
                    "POST",
                    "/ask",
                    json={
                        "message": tc.query,
                        "product_id": PRODUCT_ID,
                        "conversation_id": f"{CONVERSATION_ID}_{i}",
                    },
                ) as resp:
                    resp.raise_for_status()
                    result = consume_sse(resp)

        except Exception as exc:
            print(f"  [{i}/{total}] FAIL  {label}")
            print(f"         ↳ Request error: {exc}\n")
            failed += 1
            continue

        answer_lower = result.get("answer", "").lower()
        artifact = result.get("artifact")
        images = result.get("images", [])

        if tc.must_contain:
            ok, msg = check_must_contain(answer_lower, tc.must_contain)
            if not ok:
                failures.append(f"must_contain: {msg}")

        if tc.must_trigger_artifact:
            ok, msg = check_artifact(artifact, tc.must_trigger_artifact)
            if not ok:
                failures.append(f"must_trigger_artifact: {msg}")

        if tc.must_surface_image:
            ok, msg = check_image(images)
            if not ok:
                failures.append(f"must_surface_image: {msg}")

        if tc.must_cite_page:
            ok, msg = check_page_cited(answer_lower)
            if not ok:
                failures.append(f"must_cite_page: {msg}")

        if failures:
            print(f"  [{i}/{total}] FAIL  {label}")
            for f in failures:
                print(f"         ↳ {f}")
            print()
            failed += 1
        else:
            print(f"  [{i}/{total}] PASS  {label}")
            passed += 1

    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed out of {total}")
    print(f"{'='*60}\n")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run agent eval suite")
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()
    run_eval(base_url=args.base_url)
