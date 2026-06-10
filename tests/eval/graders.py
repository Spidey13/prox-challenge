"""Deterministic graders for the Diagnostiq eval harness — no LLM calls.

Each grader returns ``(passed: bool, detail: str)`` so failures stay legible.
Ports the assertion helpers from the legacy ``tests/eval.py`` and adds
retrieval recall + routing checks against the golden set.
"""
from __future__ import annotations

import re

_PAGE_RE = re.compile(r"(?:page|p\.?|pg\.?)\s*\d+", re.IGNORECASE)


def check_must_contain(blob_lower: str, keywords: list[str]) -> tuple[bool, str]:
    missing = [k for k in keywords if k.lower() not in blob_lower]
    return (not missing, f"missing keywords {missing}" if missing else "")


def check_must_not_contain(blob_lower: str, keywords: list[str]) -> tuple[bool, str]:
    present = [k for k in keywords if k.lower() in blob_lower]
    return (not present, f"forbidden content present {present}" if present else "")


def check_artifact_type(artifact: dict | None, expected: str | None) -> tuple[bool, str]:
    if expected is None:
        return (True, "")
    if not artifact:
        return (False, f"expected artifact {expected!r}, got none")
    got = artifact.get("type")
    if got != expected:
        return (False, f"artifact type {got!r} != expected {expected!r}")
    if len(artifact.get("html", "")) < 50:
        return (False, "artifact html too short / missing")
    return (True, "")


def check_job_card(job_card: dict | None, expect: bool | None) -> tuple[bool, str]:
    if expect is None:  # don't-care (case uses expect_payload_any instead)
        return (True, "")
    if expect and not job_card:
        return (False, "expected a job card, got none")
    if not expect and job_card:
        return (False, "unexpected job card produced")
    return (True, "")


def check_payload_any(
    artifact: dict | None, job_card: dict | None, kinds: list[str]
) -> tuple[bool, str]:
    """At least one of the named payloads must be present (ambiguous-route cases)."""
    if not kinds:
        return (True, "")
    have = {"artifact": bool(artifact), "job_card": bool(job_card)}
    if any(have.get(k, False) for k in kinds):
        return (True, "")
    return (False, f"expected one of {kinds}, got neither")


def check_image(images: list, expect: bool) -> tuple[bool, str]:
    if expect and not images:
        return (False, "expected a surfaced image, got none")
    return (True, "")


def check_cite_page(blob: str, must: bool) -> tuple[bool, str]:
    if not must:
        return (True, "")
    if _PAGE_RE.search(blob):
        return (True, "")
    return (False, "no page citation (expected 'p.N' or 'page N')")


def check_route(actual: str, expected: str | list[str]) -> tuple[bool, str]:
    allowed = expected if isinstance(expected, list) else [expected]
    return (actual in allowed, f"route {actual!r} not in expected {allowed}")


def retrieval_recall(
    trace: list[dict],
    expected_pages: list[int],
    expected_doc_slug: str = "manual",
    mode: str = "all",
) -> float:
    """Recall of expected pages in the trace with matching doc_slug.

    mode="all" — fraction of expected pages found (multi-page ground truth where
    every page matters, e.g. a code table split across two pages).
    mode="any" — 1.0 if ANY expected page is found (fault cases whose ground
    truth is a troubleshooting-table REGION; hitting any page of it proves
    retrieval found the right place).
    Returns 1.0 when there is nothing to retrieve (clarify/refuse cases).
    """
    if not expected_pages:
        return 1.0
    found = {(c.get("page_number"), c.get("doc_slug")) for c in trace}
    hits = sum(1 for p in expected_pages if (p, expected_doc_slug) in found)
    if mode == "any":
        return 1.0 if hits else 0.0
    return hits / len(expected_pages)
