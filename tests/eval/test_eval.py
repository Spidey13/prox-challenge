"""Diagnostiq eval gate.

Per-case: hard asserts on content/structure (must_contain, must_not_contain,
artifact type, job-card/image presence, page citation). Soft/aggregate: routing,
retrieval recall, and faithfulness are recorded and enforced as thresholds by
``test_aggregate_thresholds`` (so LLM nondeterminism doesn't flake the build).

Run everything:        uv run pytest tests/eval -v
Free deterministic:    uv run pytest tests/eval -v -m "not judge"
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import graders
import harness
import judge
import report

CASES = json.loads(
    (Path(__file__).resolve().parent / "golden_set.json").read_text(encoding="utf-8")
)["cases"]

# Cases whose hard structural asserts are known routing-boundary risks — tracked,
# not build-breaking (non-strict xfail, so an unexpected pass is fine).
XFAIL = {
    "electrical-mca-lookup": "electrical ratings table has no clean artifact type yet",
    "enter-test-mode": "how-to query may over-route to a job card",
}


def _param(case: dict):
    marks = []
    if case.get("faithfulness"):
        marks.append(pytest.mark.judge)
    if case["id"] in XFAIL:
        marks.append(pytest.mark.xfail(reason=XFAIL[case["id"]], strict=False))
    return pytest.param(case, id=case["id"], marks=marks)


@pytest.mark.eval
@pytest.mark.parametrize("case", [_param(c) for c in CASES])
def test_case(case, agent, judge_client):
    result = harness.run_case(case=case, agent=agent)
    blob = result.text_blob.lower()

    # --- record aggregate metrics FIRST (so they survive a hard-assert failure) ---
    recall = graders.retrieval_recall(
        result.retrieval_trace,
        case["expected_pages"],
        case.get("expected_doc_slug", "manual"),
        mode=case.get("recall_mode", "all"),
    )
    route_ok, _ = graders.check_route(result.route, case["expected_route"])
    exp_route = case["expected_route"]
    exp_route_label = "|".join(exp_route) if isinstance(exp_route, list) else exp_route
    faith = None
    if case.get("faithfulness"):
        verdict = judge.judge_faithfulness(
            judge_client, judge.judge_model(), case["query"], result.text_blob, result.retrieval_trace
        )
        faith = verdict["passed"]
    report.record({
        "id": case["id"],
        "route": result.route,
        "exp_route": exp_route_label,
        "route_ok": route_ok,
        "recall": recall,
        "min": case.get("recall_min", 0.0),
        "faith": faith,
    })

    # --- hard per-case structural asserts ---
    checks = [
        graders.check_must_contain(blob, case.get("must_contain", [])),
        graders.check_must_not_contain(blob, case.get("must_not_contain", [])),
        graders.check_artifact_type(result.artifact, case.get("expected_artifact")),
        graders.check_job_card(result.job_card, case.get("expect_job_card", False)),
        graders.check_payload_any(result.artifact, result.job_card, case.get("expect_payload_any", [])),
        graders.check_image(result.images, case.get("expect_image", False)),
        graders.check_cite_page(blob, case.get("must_cite_page", False)),
    ]
    fails = [detail for ok, detail in checks if not ok]
    assert not fails, f"[{case['id']}] route={result.route} :: " + "; ".join(fails)


@pytest.mark.eval
def test_aggregate_thresholds():
    """Enforce the CI gate. Runs after the parametrized cases (file order)."""
    if len(report.RESULTS) < max(1, len(CASES) // 2):
        pytest.skip(
            f"only {len(report.RESULTS)}/{len(CASES)} cases recorded — "
            "aggregate gate needs a full run (don't filter with -k)"
        )
    fails = report.threshold_failures()
    assert not fails, "aggregate gate failed: " + "; ".join(fails)
