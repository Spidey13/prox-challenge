# ADR 004 — Job card as a separate output mode from render_artifact

**Status:** Accepted  
**Date:** 2025-04

---

## Context

When a user describes a fault ("welder won't arc", "overheating"), two approaches:

| Option | Approach |
|--------|----------|
| A — HTML artifact | Sonnet generates a troubleshooting flowchart as an HTML page inside the existing iframe |
| **B — structured job card** | Sonnet outputs validated JSON; the frontend drives a native branching UI |

Option A is fast to build — `troubleshooting_flowchart` would be just another `artifact_type`. But it has problems:

- HTML flowcharts are hard to interact with on mobile (small tap targets, no state).
- The iframe can't call back to the app (artifact is sandboxed with no `fetch`). A YES/NO checklist that needs to track state, log results, and show a timer requires a real React component.
- Hallucination is undetectable inside an HTML blob. A JSON schema with required `source_citation` per step lets `_validate_job_card()` flag uncited steps.

---

## Decision

Job cards are a first-class output mode alongside `render_artifact`, not a variant of it. Haiku's system prompt routes explicitly:

```
FAULT/DIAGNOSIS  → generate_job_card  (after search_knowledge)
SETTINGS/SPECS   → render_artifact
PLAIN KNOWLEDGE  → text answer
```

`generate_job_card` is a separate tool — it cannot be called in the same turn as `render_artifact`. Sonnet receives a tight prompt with the JSON schema and the `source_citation` requirement. `_validate_job_card()` enforces the schema server-side before the JSON reaches the frontend.

The `troubleshooting_flowchart` artifact type is removed from the `render_artifact` tool enum so Haiku cannot route fault queries there by mistake.

---

## Consequences

- Job card state (timer, history, audit log) lives in `useJobCard.js` — a pure state machine that takes the streaming JSON and tracks YES/NO answers. No global state store needed.
- `JobCardPanel.jsx` is a pure render layer: it receives hook output and calls `answerYes()` / `answerNo()`. This makes it straightforward to test the state machine in isolation.
- Steps with missing `source_citation` are flagged `citation_missing: true` by the validator and rendered with a muted manual-ref button. They are never silently dropped.
- `artifact_trigger` on a step allows the job card to link out to an HTML artifact for that specific step (e.g. "show wiring diagram"). This bridges the two output modes without merging them.
