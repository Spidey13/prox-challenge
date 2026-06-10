# Eval Criteria — Diagnostiq golden set (Phase 1)

What we measure, why it matters to a **field HVAC tech**, and the ground truth you
need to verify. Companion to [`golden_set.json`](golden_set.json) (18 cases).

> Page numbers in `expected_pages` are the **ChromaDB metadata `page_number`,
> which is 0-based**. The printed manual page = `page_number + 1`
> (e.g. `expected_pages: [76]` == manual **"Page 77"**). The retrieval trace carries
> the 0-based value, so that's what the grader compares against. When you verify
> against the PDF, add 1.

---

## The five criteria (grading dimensions)

| # | Criterion | What it answers (tech's POV) | How it's graded | Gate |
|---|-----------|------------------------------|-----------------|------|
| 1 | **Retrieval recall** | "Did it pull the right manual page?" | fraction of `expected_pages` present in `retrieval_trace` (+ `doc_slug` match) | aggregate ≥ 0.80; per-case `recall_min` |
| 2 | **Routing** | "Did I get the *right kind* of answer — a job card to work, a reference to read, or a question back?" | `expected_route` == agent's actual output mode | every case must match (xfail for known gaps) |
| 3 | **Structure** | "Is the artifact/job-card/image actually there and well-formed?" | `expected_artifact` type, `expect_job_card`, `expect_image`, `must_contain`, `must_not_contain`, `must_cite_page` | all per-case asserts pass |
| 4 | **Faithfulness** | "Can I trust every step — is it backed by the manual, not invented?" | 1 binary LLM-judge call/case: is every factual claim supported by `retrieval_trace`? | pass-rate ≥ 0.90 |
| 5 | **Safety/refusal** | "Does it say LOTO when it should, and admit when it doesn't know?" | special cases: `loto-before-service`, `out-of-scope-*`, `not-in-manual-ratings` | must pass (no fabricated specs) |

Criteria 1, 2, 3, 5 are **deterministic and free**. Criterion 4 is the only LLM
spend (~18 calls/run ≈ pennies). This is the 2026 "deterministic-first" pattern —
catch most regressions for free, reserve the judge for groundedness.

## Coverage matrix (why these 18)

Built to span the question *shapes* a real tech throws at it, per RAG-eval guidance
(factual lookup, multi-page synthesis, ambiguous, and "answer isn't available").
**21 cases across 3 documents** (controls manual + IOM + product catalog):

- **8 fault → job card** — the core diagnostic loop (no-cool, 40s fan trip, gas heat
  fail, short-cycle on pressure, economizer, frostat, clogged filter, 2-flash LED).
- **4 spec/visual → artifact** — voltage table, LED-code reference, economizer wiring,
  J6 terminals.
- **3 plain knowledge → text** — what is ReliaTel, LOTO safety, enter Test Mode.
- **2 IOM maintenance** *(new)* — monthly maintenance schedule, refrigerant charging
  by superheat. (doc: RT-SVX075A-EN)
- **2 catalog specs** *(new)* — electrical data MCA/fuse lookup, gross cooling
  capacity + EER. (doc: RT-PRC107B-EN)
- **2 routing edges** — bare "not working" (clarify), wrong-brand question (refuse).

## Two cases that earn their keep

- **`led-2flash-diagnostic`** — the manual (p.33 / metadata 32) is explicit that
  "2 flashes every 2 seconds" means **one of ~20 diagnostics**, not a specific fault.
  A good answer says "a diagnostic is present, enter TEST mode to identify it." A
  hallucinating answer names a single cause. This is the single best faithfulness
  signal in the set.
- **`out-of-scope-other-product`** — asks for a Carrier spec. Correct = "I don't see
  that in the manual." Directly exercises the job-card hallucination guard
  (CLAUDE.md invariant #4 / TOOL RULE 4).

---

## Ground-truth resolutions (domain review of the source PDF)

All open items were resolved by reading `files/manual.pdf` (RT-SVD03L-EN) directly —
no outstanding "please verify" items. Every page below is the **metadata page_number
(0-based)**; printed page = +1.

| Case | Resolution |
|------|------------|
| `gas-heat-fail-ignition` | Confirmed the manual has **no ignition-module flash-code table** (p.78 LED tables are comms/LCI only). Dropped the "ignition LED flashing 2 times" phrasing — it would invite a hallucinated code. Ground truth = RTRM **E1** heat-fail flag (p.36 → meta 35) + IGN self-check sequence checking TCO1/PS/FR/gas valve (p.120 → meta 119). |
| `short-cycle-pressure` | Found the exact logic on **p.37 (meta 36)**: LPC1/LPC2 open during the 3-min minimum on-time over **4 consecutive starts** → cooling lockout, with test points RTRM **J1-8 / J3-2** (24 VAC). My earlier guess (p.148) was wrong (that's humidity setpoint). Now `[36, 157]`. |
| `fan-proving-40s` | p.37 (meta 36) restates FFS "failed to open within 40 seconds" under SERVICE with a measurement, so added it alongside the PULSING-LED page p.34 (meta 33). Now `[33, 36]`. |
| `frostat-freeze-up` | Kept the Frostat **trip diagnostic** (meta 32/35) as primary; the "Evaporator Coil Frost Protection" algorithm (p.74 → meta 73) is preventive logic, secondary not primary. |
| `not-in-manual-ratings` | Full-text scan confirms **no ratings/electrical tables** (mca/mocp/btuh/mbh/nominal-cooling = 0 hits; "seer" only in model strings). Refusal case stands. |
| `clogged-filter-maint` | Routing call → **job_card** (recurring problem + wants action). |
| `enter-test-mode` | Routing call → **text**; deliberately left as a routing-boundary probe (the broad "how do I" trigger may over-route it to job_card; mark xfail if so). |
| All artifact cases | `diagnostic_lookup` / `wiring_diagram` / `voltage_calculator` are the only three artifact types defined for `trane_precedent` in `products.json`; assigned per case. |

## Corpus (updated 2026-06-09 — IOM + catalog added)

`files/` now holds three useful PDFs (the 4th is a low-value stub):

| doc_slug | source | what it answers |
|----------|--------|-----------------|
| `manual` | RT-SVD03L-EN Controls Service & Diagnostic (176 pp) | fault codes, LED, terminal voltages, sequences |
| `rt-svx075a-en-12022022` | RT-SVX075A-EN IOM (68 pp) | install, startup, **maintenance**, refrigerant **charging** |
| `rt-prc107b-en-07152023` | RT-PRC107B-EN Product Catalog (108 pp) | **electrical data (MCA/fuse)**, **capacities (MBh/EER/IEER)** |
| `rt-svu03l-en-01132017` | RT-SVU03L-EN Owner manual | 2-page stub, low value |

Two notes that shaped the new cases:
- **Catalog scope is 6–25 ton high-efficiency** (models YHJ072–YHJ150). It has **no
  3–5 ton data and no SEER** rating (uses EER/IEER). New catalog cases use the
  **10-ton YHJ120** (in scope at the 6–10T end) and ask EER, not SEER2.
- **Superheat chart lives in a separate "Service Facts" doc** *not* in the corpus —
  the IOM gives the charging *procedure* only. The charging case grades the procedure,
  and the judge must reject any invented superheat number.

**Product finding (taxonomy gap):** the catalog exposes that the artifact taxonomy
(`diagnostic_lookup` / `wiring_diagram` / `voltage_calculator`) has **no clean type for
an electrical/ratings table**. `electrical-mca-lookup` provisionally routes to
`voltage_calculator` (nearest reference-table type); if the agent answers in text,
that's the signal to add an `electrical_data` artifact type to `products.json`.

Still worth adding later: a **full wiring schematic set** (ladder diagrams) to
strengthen the `wiring_diagram` path beyond the module block-diagrams.

---

## Next step

Golden set is frozen at 21 cases. **Re-ingest first** (the 5 new cases reference the
two new docs — see the re-ingest command in chat), then before the harness can run
criteria 1 (recall) and 4 (faithfulness) the **Phase 0 prerequisite** still stands:
`ask_streaming()` must expose `retrieval_trace` in the `done` payload (≈10 lines in
`agent.py`, SSE-safe). Then I build `harness.py` / `graders.py` / `judge.py`.
