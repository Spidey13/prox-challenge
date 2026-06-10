"""Aggregation + readable report for the eval suite.

``RESULTS`` is a module-level list the test module appends to as cases run; the
pytest terminal-summary hook (in conftest) and the aggregate gate test both read
it. Also runnable standalone after a run for the table.
"""
from __future__ import annotations

# CI gate thresholds — set just under the calibrated 2026-06-09 run-2 baseline
# (recall 0.79, route 0.76, faithfulness 0.63) so the gate catches REGRESSIONS
# from today's behavior. Ratchet upward as the agent improves; 0.90 faithfulness
# remains the goal, not the gate.
THRESHOLDS = {
    "recall": 0.75,        # aggregate mean retrieval recall
    "faithfulness": 0.55,  # judge pass-rate over judged cases
    "route": 0.70,         # route-match rate over all cases
}

RESULTS: list[dict] = []


def record(entry: dict) -> None:
    RESULTS.append(entry)


def reset() -> None:
    RESULTS.clear()


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 1.0


def aggregate() -> dict:
    judged = [r for r in RESULTS if r.get("faith") is not None]
    return {
        "n": len(RESULTS),
        "recall": _mean([r["recall"] for r in RESULTS]),
        "route": _mean([1.0 if r["route_ok"] else 0.0 for r in RESULTS]),
        "faithfulness": _mean([1.0 if r["faith"] else 0.0 for r in judged]),
        "n_judged": len(judged),
    }


def render() -> str:
    if not RESULTS:
        return "(no eval results recorded)"
    rows = ["", "=" * 78, "  Diagnostiq Eval — per-case", "=" * 78,
            f"  {'case':28} {'route':>16}  {'recall':>6}  {'faith':>5}",
            "  " + "-" * 74]
    for r in sorted(RESULTS, key=lambda x: x["id"]):
        rt = f"{r['route']}" + ("" if r["route_ok"] else f"!={r['exp_route']}")
        faith = "-" if r["faith"] is None else ("PASS" if r["faith"] else "FAIL")
        flag = " " if r["route_ok"] and r["recall"] >= r.get("min", 0.0) else "*"
        rows.append(f" {flag}{r['id']:28} {rt:>16}  {r['recall']:>6.2f}  {faith:>5}")
    agg = aggregate()
    rows += [
        "  " + "-" * 74,
        f"  recall {agg['recall']:.2f} (>= {THRESHOLDS['recall']})   "
        f"route {agg['route']:.2f} (>= {THRESHOLDS['route']})   "
        f"faith {agg['faithfulness']:.2f} (>= {THRESHOLDS['faithfulness']}, "
        f"n={agg['n_judged']})",
        "=" * 78,
    ]
    return "\n".join(rows)


def threshold_failures() -> list[str]:
    agg = aggregate()
    fails = []
    if agg["recall"] < THRESHOLDS["recall"]:
        fails.append(f"recall {agg['recall']:.2f} < {THRESHOLDS['recall']}")
    if agg["route"] < THRESHOLDS["route"]:
        fails.append(f"route-match {agg['route']:.2f} < {THRESHOLDS['route']}")
    if agg["n_judged"] and agg["faithfulness"] < THRESHOLDS["faithfulness"]:
        fails.append(f"faithfulness {agg['faithfulness']:.2f} < {THRESHOLDS['faithfulness']}")
    return fails


def save_history(path=None) -> None:
    """Append this run's aggregate (+ git SHA, timestamp) to history.jsonl.

    One line per eval run — the longitudinal record that turns single scores
    into a trend. Called from the pytest terminal-summary hook; safe no-op on
    partial runs (fewer than half the cases) so -k filters don't pollute it.
    """
    import datetime
    import json
    import subprocess
    from pathlib import Path

    if not RESULTS:
        return
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=Path(__file__).parent,
        ).stdout.strip() or "unknown"
    except OSError:
        sha = "unknown"
    entry = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "git_sha": sha,
        **{k: round(v, 4) if isinstance(v, float) else v for k, v in aggregate().items()},
        "thresholds": THRESHOLDS,
    }
    target = Path(path) if path else Path(__file__).parent / "history.jsonl"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    print(render())
