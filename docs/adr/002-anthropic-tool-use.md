# ADR 002 — Anthropic native tool_use over orchestration frameworks

**Status:** Accepted  
**Date:** 2025-04

---

## Context

Agent loops can be built at different abstraction levels:

| Option | Approach | Control | Debuggability |
|--------|----------|---------|---------------|
| A — LangChain / LlamaIndex | Framework manages tool dispatch, memory, routing | Low | Low — hidden chains |
| B — Anthropic `tool_use` (native) | We write the `while stop_reason == "tool_use"` loop | Full | Direct — inspect every message |
| C — Anthropic Agents SDK | Managed loop, streaming built in | Medium | Medium |

Framework choices (A) trade control for convenience. When something goes wrong — wrong tool called, missing context, rate limit retry — the failure surfaces deep inside the framework's call stack. Given this is a domain-specific agent with tight routing rules (fault → job card, specs → artifact, plain → text), we need to enforce the routing ourselves, not hope a framework infers it.

---

## Decision

Write the tool loop directly in `agent.py`. The loop is ~30 lines:

```python
while response.stop_reason == "tool_use":
    if iterations >= _effective_cap:
        break
    iterations += 1
    messages.append({"role": "assistant", "content": response.content})
    tool_results = []
    for block in response.content:
        if block.type != "tool_use":
            continue
        result = dispatch(block.name, block.input)
        tool_results.append({"type": "tool_result", "tool_use_id": block.id, ...})
    messages.append({"role": "user", "content": tool_results})
    response = call_claude(messages)
```

No framework dependency. The full message list is always visible. Rate-limit retry is a 10-line `_with_retry` wrapper around every `messages.create()` call.

---

## Consequences

- Zero framework dependency risk — no LangChain version pins, no hidden prompt injection.
- The tool loop is straightforward to extend: add a tool to `_build_tools()`, add an `elif` in the dispatch block, done.
- We own the retry logic (`_with_retry`, 13 s base delay, 4 retries, exponential backoff). Works correctly; tested against the free-tier 5 RPM limit.
- The `ask()` and `ask_streaming()` methods are nearly identical (sync vs streaming final step). Some duplication, but it's explicit and auditable.
