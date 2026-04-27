# Job Card Flow

The job card is a second output mode alongside `render_artifact`. For any fault or diagnosis query, the agent generates a structured JSON diagnostic checklist instead of an HTML artifact. The frontend drives it as a branching YES/NO state machine.

---

## Routing decision

Haiku classifies query intent before calling any tool:

```
Query intent
     │
     ├─── FAULT / DIAGNOSIS  ──► generate_job_card (after search_knowledge)
     │    "not working", "won't start", "overheating", "fault", ...
     │
     ├─── SETTINGS / SPECS   ──► render_artifact
     │    "wiring diagram", "show me", "what is the setting for", ...
     │
     └─── PLAIN KNOWLEDGE    ──► text answer (± get_manual_image)
```

When the user taps a fault button in the UI, `intent_known=true` is sent. This skips Haiku entirely — the agent calls `search_knowledge` and `generate_job_card` directly (1 API call total instead of 2–4).

---

## SSE event sequence

```
POST /ask
  │
  ├── data: {"type": "job_card_start", "metadata": {equipment, priority, ...}}
  ├── data: {"type": "job_card_step",  "step": {id:1, instruction, yes_next, no_next, ...}}
  ├── data: {"type": "job_card_step",  "step": {id:2, ...}}
  ├── data: {"type": "job_card_step",  "step": {id:N, ...}}
  └── data: {"type": "done",           "job_card": {full object}, "artifact": null}
```

Steps stream progressively — the UI can render each step as it arrives. The `done` event carries the full assembled object for caching.

---

## Job card schema

```json
{
  "type": "job_card",
  "metadata": {
    "equipment": "Vulcan OmniPro 220",
    "asset_id": "unknown",
    "fault_description": "welder won't arc",
    "priority": "HIGH"
  },
  "steps": [
    {
      "id": 1,
      "instruction": "Check that the power switch is in the ON position.",
      "note": "Switch should click and indicator light should illuminate.",
      "yes_label": "Light on",
      "no_label": "No light",
      "yes_next": 2,
      "no_next": "escalate",
      "source_citation": "p.12 §3.1",
      "artifact_trigger": null
    }
  ]
}
```

`artifact_trigger` is non-null only when the retrieved chunk references a specific diagram or settings table. When set, tapping the step opens the relevant HTML artifact inline.

---

## Frontend state machine (`useJobCard.js`)

```
           ┌──────────┐
           │ loading  │  waiting for first job_card_step event
           └────┬─────┘
                │ steps[0] arrives
                ▼
           ┌──────────┐
           │  active  │  user answers steps via swipe / Y / N
           └────┬─────┘
                │
        ┌───────┴────────┐
        │                │
   yes_next=N       yes_next='complete'
   no_next=N        no_next='escalate'
        │                │
        ▼                ▼
   advance        ┌──────────────┐
   currentStepId  │  complete    │  or  │ escalated │
                  └──────────────┘      └───────────┘
```

State lives in `useJobCard(jobCard)`. `JobCardPanel` is a pure render layer — it receives the hook's return values and calls `answerYes()` / `answerNo()`.

Button gating: if `yes_next` or `no_next` points to a step ID not yet in `steps[]` (still arriving via SSE), the button is disabled silently.

---

## Hallucination guard

Sonnet's system prompt for `generate_job_card`:

> Output ONLY a raw JSON object. No explanation, no preamble, no markdown fences.

Every step requires a `source_citation` field in the format `p.N §X.Y`. Steps missing a citation are flagged `citation_missing: true` by `_validate_job_card()` and the UI renders the manual-ref button in a muted state. Steps are never fabricated without a citation — if the retrieved context contains nothing relevant, Sonnet produces fewer steps rather than inventing them.

---

## Cache key

Fault button queries key on `"{product_id}:{fault_category}"` (e.g. `vulcan_220:wont_start`) — deterministic across sessions because the same fault on the same product always retrieves the same manual content. Text-path and photo-path queries key on the raw query string.
