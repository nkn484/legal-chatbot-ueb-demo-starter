---
description: Plan M02 provider abstraction and SHINE adapter
agent: plan
---

Before planning:
- read `AGENTS.md`, `contracts/demo-profile.json`, `contracts/source-registry.json`;
- inspect repository and `.demo-run/state.json` if present;
- never edit `.demo-run/state.json`;
- this command is planning-only: do not implement yet.

Plan must include: goal, current facts, minimal files, interfaces, tests, external assumptions, risks/fallback, out-of-scope, acceptance criteria, stop condition. Use `NOT_MEASURED` for unverified facts.

# M02 — Provider Abstraction
Plan `LLMProviderPort`, normalized request/result, registry/factory, SHINE Responses adapter, timeout/bounded retry, request-id/error normalization, Claude extension point, mocked tests and bounded live SHINE test. Chat must not import SHINE client. No Chat/RAG implementation.
