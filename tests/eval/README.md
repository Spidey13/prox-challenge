# Diagnostiq Eval Harness

Headless evaluation suite for the support agent: drives `SupportAgent.ask_streaming()`
directly (no server), scores every answer on five dimensions, and gates CI on
aggregate thresholds.

## Results so far

| Run (2026-06-09) | Retrieval recall | Route match | Faithfulness |
|---|---|---|---|
| Run 1 — baseline | 0.79 | 0.71 | **0.26** |
| Run 2 — after fixes | 0.79 | 0.76 | **0.63** |

Run 1 caught the agent answering a voltage-lookup question with **invented values**
("ON ≈ 12–24 VDC" — the manual says 32 VDC) *despite retrieving the correct page*.
Root cause: the free-text synthesis prompt had no grounding rule (job cards did).
Fixes between runs: grounding rules in both generation prompts, a retrieval config
bug (`n_results` returned 3 chunks instead of the configured 5), and a judge context
window that was truncating evidence mid-table. Full trail: `history.jsonl`,
`_diag_run1.json` (before), `_diag.json` (after).

## Architecture

| File | Role |
|---|---|
| `golden_set.json` | 21 cases, ground truth verified against the source PDFs (0-based `page_number`). Covers faults→job cards, specs→artifacts, plain knowledge, IOM maintenance, catalog lookups, routing edges (ambiguous/out-of-scope). |
| `harness.py` | Drains the agent's streaming generator into a gradable `CaseResult`; infers the output route. |
| `graders.py` | Deterministic, no-LLM checks: retrieval recall (`all`/`any` region modes), route match, must/must-not contain, artifact type, job-card/image presence, page citations. |
| `judge.py` | One binary LLM-judge call per case (Haiku, `temperature=0`, pinned model): is every claim supported by the retrieved chunks? Rubric anchored with few-shot traps from the golden set. |
| `report.py` | Aggregation, per-case table, CI thresholds, `history.jsonl` trend log (one line per full run, with git SHA). |
| `test_eval.py` | The pytest gate: hard per-case structural asserts + soft aggregate thresholds (so LLM nondeterminism can't flake the build). Known boundary cases are non-strict `xfail`. |
| `_diagnose.py` | Calibration tool — per-case dump with resume (saves after every case; an interrupted run loses nothing). Not a test. |

## Running it (costs real API money)

```bash
uv run python -m pytest tests/eval -v              # full suite ≈ $0.60–1.00
uv run python -m pytest tests/eval -v -m "not judge"  # skip LLM judge (cheaper, still pays agent calls)
uv run python tests/eval/_diagnose.py              # calibration dump, resumable
```

Skips cleanly when `ANTHROPIC_API_KEY` is unset (CI without secrets stays green).
**Run policy: batch your agent changes and run once per batch — never per tweak.**

## Thresholds

Set just under the run-2 baseline so the gate catches **regressions**, and ratcheted
upward as the agent improves: recall ≥ 0.75, route ≥ 0.70, faithfulness ≥ 0.55
(goal: 0.90). Rationale lives next to the numbers in `report.py`.

## Grading conventions worth knowing

- `expected_pages` uses ChromaDB's **0-based** `page_number` (printed page = value + 1).
- `recall_mode: "any"` marks fault cases whose ground truth is a troubleshooting-table
  *region* — hitting any page of it proves retrieval found the right place.
- `expected_route` may be a list when two routes are genuinely defensible
  (e.g. "LED 2-flash" as job card *or* diagnostic-lookup artifact); those cases use
  `expect_payload_any` instead of hard job-card/artifact asserts.
- Judge verdicts default to PASS on unparseable output — a broken judge should
  show up as suspicious perfection, not false alarms.
