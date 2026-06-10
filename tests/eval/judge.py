"""LLM-as-judge faithfulness grader — one binary call per judged case.

Model defaults to ``config.haiku`` (project decision: near-free, fast). Haiku is
noisier than Sonnet, so the rubric is tight and binary and anchored with two
few-shot examples drawn from the golden set's faithfulness traps. Override with
the ``DIAGNOSTIQ_JUDGE_MODEL`` env var (e.g. to spot-check with Sonnet).
"""
from __future__ import annotations

import os
import re

_MAX_CHUNKS = 8
# 2000, not 700: run-1 calibration showed 700 truncated tables mid-row and the
# judge FAILed answers whose support sat past the cutoff (electrical-mca gave
# the catalog's correct MCA 54 / fuse 70 and was still failed). Haiku input is
# near-free; don't starve the judge.
_MAX_CHUNK_CHARS = 2000
_MAX_ANSWER_CHARS = 3000

_SYSTEM = (
    "You are a STRICT faithfulness grader for an HVAC field-support assistant. "
    "Decide whether EVERY factual/technical claim in the ASSISTANT ANSWER is "
    "supported by the RETRIEVED CONTEXT.\n"
    "Reply with EXACTLY one line beginning with PASS or FAIL, then ' — ' and a "
    "short reason.\n"
    "Rules:\n"
    "- A specific code, number, voltage, page, terminal, or step that is NOT in "
    "the context is a FAIL (hallucination).\n"
    "- Generic safety advice (lockout/tagout, PPE) is always allowed.\n"
    "- If the answer correctly says the information is not in the manual, that is "
    "PASS.\n"
    "- An LED 'N flashes' pattern that the context says maps to MANY possible "
    "diagnostics must NOT be reduced to a single named cause — doing so is FAIL.\n"
    "- Pointing to a separate document for a value the context lacks (e.g. a "
    "superheat chart in 'Service Facts') is PASS; inventing the value is FAIL.\n\n"
    "Example 1 -> FAIL — names '2 flashes = supply fan fail' as the cause when "
    "context says 2 flashes means one of ~20 diagnostics.\n"
    "Example 2 -> PASS — gives the superheat procedure and says the target chart "
    "is in the Service Facts, without inventing a number."
)


def judge_model() -> str:
    env = os.getenv("DIAGNOSTIQ_JUDGE_MODEL")
    if env:
        return env
    from config import config
    return config.haiku


def _format_context(trace: list[dict]) -> str:
    if not trace:
        return "(no chunks retrieved)"
    lines = []
    seen: set[tuple] = set()  # traces repeat chunks across search calls — dedupe
    for c in trace:
        if len(lines) >= _MAX_CHUNKS:
            break
        slug = c.get("doc_slug", "?")
        pg = c.get("page_number", "?")
        txt = re.sub(r"\s+", " ", str(c.get("text", "")))[:_MAX_CHUNK_CHARS]
        key = (slug, pg, txt[:80])
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"[{slug} p{pg}] {txt}")
    return "\n".join(lines)


def judge_faithfulness(client, model: str, query: str, answer: str, trace: list[dict]) -> dict:
    """Return {'passed': bool, 'reason': str, 'raw': str}."""
    context = _format_context(trace)
    answer = (answer or "").strip()[:_MAX_ANSWER_CHARS] or "(empty answer)"
    user = (
        f"QUESTION:\n{query}\n\n"
        f"RETRIEVED CONTEXT:\n{context}\n\n"
        f"ASSISTANT ANSWER:\n{answer}\n\n"
        "Verdict:"
    )
    resp = client.messages.create(
        model=model,
        max_tokens=120,
        temperature=0,  # deterministic grading — same input always same verdict
        system=_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    raw = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
    verdict = raw.lstrip().upper()
    # FAIL only when explicitly stated; default PASS to avoid false alarms on
    # an unparseable judge reply (recorded via raw for inspection).
    passed = not verdict.startswith("FAIL")
    return {"passed": passed, "reason": raw or "(no judge output)", "raw": raw}
