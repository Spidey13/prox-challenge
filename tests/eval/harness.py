"""Headless driver for the Diagnostiq agent.

``run_case`` calls ``SupportAgent.ask_streaming`` directly (no server), drains
the generator, and returns a result bundle the graders can score. The agent's
``done`` payload already carries ``retrieval_trace`` (agent.py exposes it on
every done event), so no agent change is needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_REFUSE_RE = re.compile(
    r"don'?t see|not in the manual|isn'?t in the manual|no information|couldn'?t find|"
    r"(?:not|isn'?t) covered|unable to find|outside (?:my|the) (?:scope|knowledge)|"
    r"different manufacturer",
    re.IGNORECASE,
)

# Clarify answers don't reliably end with "?" (run-1: ended with a bullet list of
# example symptoms) — detect ask-for-more-detail phrasing instead.
_CLARIFY_RE = re.compile(
    r"more detail|can you tell me|could you (?:tell|describe|share)|what exactly|"
    r"need a bit more|to help you effectively",
    re.IGNORECASE,
)


@dataclass
class CaseResult:
    answer: str
    suggestions: list
    artifact: dict | None
    job_card: dict | None
    images: list
    retrieval_trace: list
    route: str
    text_blob: str = field(default="")


def _infer_route(answer: str, artifact: dict | None, job_card: dict | None, trace: list) -> str:
    """Map the done payload onto the golden set's expected_route vocabulary."""
    if job_card:
        return "job_card"
    if artifact:
        return "artifact"
    a = (answer or "").strip()
    if _REFUSE_RE.search(a):
        return "refuse"
    if not trace and ("?" in a) and (a.endswith("?") or _CLARIFY_RE.search(a)):
        return "clarify"
    return "text"


def _build_text_blob(answer: str, artifact: dict | None, job_card: dict | None) -> str:
    """All graded text in one lowercased-searchable string.

    Job-card cases have answer="" — their content lives in the steps, so we fold
    metadata + step instructions/notes/citations in. Artifact cases fold in the
    rendered html so must_contain / page-citation checks can see it.
    """
    parts: list[str] = [answer or ""]
    if job_card:
        meta = job_card.get("metadata", {})
        parts.append(str(meta.get("fault_description", "")))
        parts.append(str(meta.get("equipment", "")))
        for s in job_card.get("steps", []):
            parts.append(str(s.get("instruction", "")))
            parts.append(str(s.get("note", "")))
            parts.append(str(s.get("source_citation", "")))
    if artifact:
        parts.append(str(artifact.get("type", "")))
        parts.append(str(artifact.get("html", "")))
    return " ".join(parts)


def run_case(agent, case: dict, product_id: str = "trane_precedent") -> CaseResult:
    done: dict = {}
    for event_type, payload in agent.ask_streaming(case["query"], product_id, history=[]):
        if event_type == "done":
            done = payload
            break

    answer = done.get("answer", "") or ""
    artifact = done.get("artifact")
    job_card = done.get("job_card")
    trace = done.get("retrieval_trace", []) or []
    images = done.get("images", []) or []

    route = _infer_route(answer, artifact, job_card, trace)
    blob = _build_text_blob(answer, artifact, job_card)
    return CaseResult(
        answer=answer,
        suggestions=done.get("suggestions", []) or [],
        artifact=artifact,
        job_card=job_card,
        images=images,
        retrieval_trace=trace,
        route=route,
        text_blob=blob,
    )
