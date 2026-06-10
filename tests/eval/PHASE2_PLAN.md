# Phase 2 Plan — Eval Harness + Graders

Status: **approved 2026-06-09**, execution next. Grounded in the current `agent.py`.
Companion to [`golden_set.json`](golden_set.json) (21 cases) and [`CRITERIA.md`](CRITERIA.md).

## Phase 0 — already done (no agent.py change needed)

`ask_streaming()` (agent.py:405) already accumulates `retrieval_trace: list[dict]`
(line 480) and emits it in **all three** `("done", {...})` payloads — fast path
(505), job-card path (614), synthesis path (675). Each chunk dict carries
`text, chunk_type, page_number, doc_slug, section` (from `_tool_search_knowledge`,
agent.py:750-756). The harness reads the generator directly; `main.py`/SSE untouched.
(The "Phase 0 prerequisite" note in the root CLAUDE.md is stale.)

## Preconditions to RUN (not to build)

- Re-ingest completed (`uv pip install -r requirements.txt`, then
  `uv run python local_ingest.py trane_precedent --fresh`) — the 5 new-doc cases fail
  recall against the old DB.
- `ANTHROPIC_API_KEY` set. Suite calls the **live** agent (Haiku loop + Haiku judge);
  cheap (well under $1/run) and ~1-2 min for 21 cases.

## Decisions (locked)

- **Judge model = `config.haiku`** (user decision 2026-06-09). Near-free, fast.
  Tradeoff: noisier than Sonnet — mitigate with a tight binary rubric + 2 few-shot
  anchors drawn from the encoded trap cases (2-flash "no single cause"; superheat
  "no invented number"). Overridable via `DIAGNOSTIQ_JUDGE_MODEL` env var if we want
  to spot-check with Sonnet.
- Real agent, not mocked — this is an integration/quality gate.
- Nondeterminism handling: **content checks hard per-case; routing/recall/faithfulness
  aggregate thresholds with `xfail` escapes.** No temperature change to agent.py in v2
  (follow-up: optional `temperature=0` eval flag).

## Files (all new, under `tests/eval/`)

| File | Responsibility |
|------|----------------|
| `harness.py` | `run_case(agent, case) -> CaseResult`. Drains `ask_streaming(query, product_id, history=[])`, keeps the `done` payload. `CaseResult` = `answer, suggestions, artifact, job_card, images, retrieval_trace, route`. **Route inference:** `job_card` set → "job_card"; `artifact` set → "artifact"; else text → "refuse" if `/don'?t see|not in the manual|no information/i`, "clarify" if `retrieval_trace` empty AND answer ends `?`, else "text". |
| `graders.py` | Deterministic, no LLM. Ports `check_must_contain / check_page_cited / check_artifact / check_image` from `tests/eval.py`; adds `retrieval_recall(trace, expected_pages, expected_doc_slug)->float` (fraction of expected pages present with matching doc_slug, default slug `manual`), `check_route`, `check_artifact_type`, `check_job_card_present`, `check_image_present`, `check_must_not_contain`, `check_cite_page`. Each returns `(passed, detail)`. |
| `judge.py` | `judge_faithfulness(client, model, query, answer_or_jobcard, trace) -> {passed, reason}`. One binary Haiku call per case where `faithfulness==true`. Reuses `agent._claude`. Job-card cases serialize steps + `source_citation`s as the "answer". |
| `conftest.py` | `scope="session"` `SupportAgent()` fixture (loads MiniLM + Chroma once). Loads `golden_set.json`. Skips module with clear message if no `ANTHROPIC_API_KEY`. |
| `test_eval.py` | `parametrize` over cases (id = case id). **Hard asserts:** must_contain, must_not_contain, artifact type, job-card/image presence, page-citation. **Aggregate (session-end):** recall ≥ 0.80, faithfulness ≥ 0.90, route-match ≥ 0.85. `xfail` on routing-boundary probes (`enter-test-mode`, `electrical-mca-lookup`). Markers: `eval` on all, `judge` on judged cases → `-m "not judge"` runs the free deterministic subset. |
| `report.py` | Aggregates the collector into a readable per-case table (`route ✓/✗ · recall 0.xx · faith PASS/FAIL`) + the 3 aggregate metrics + cost estimate. Pytest session-finish hook; also runnable standalone. |

## Grading dimensions (recap from CRITERIA.md)

1. Retrieval recall (deterministic, aggregate ≥ 0.80)
2. Routing (aggregate ≥ 0.85, xfail escapes)
3. Structure (hard per-case)
4. Faithfulness (Haiku judge, aggregate ≥ 0.90)
5. Safety/refusal (special cases: loto-before-service, out-of-scope-other-product)

## Verification

1. `uv run pytest tests/eval -v` — all 21 cases headless, no server.
2. Assert `retrieval_trace` non-empty for `voltage-readings-lookup`.
3. `report.py`: per-case + aggregates; judge-call count == judged-case count.
4. **Regression proof:** force `top_k=1` (or wrong query) and confirm the recall gate
   fails — proves the harness catches what it's for.

## Open question for the calibration run

Thresholds (0.80 / 0.90 / 0.85) are starting guesses — run once, then calibrate to
observed numbers before committing them as the CI gate.

## Sequence after this

Build the six files → calibration run together → tune thresholds → (later) wire as the
Go gateway CI quality gate.
