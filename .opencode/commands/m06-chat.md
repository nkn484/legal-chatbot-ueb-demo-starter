---
description: Plan M06 grounded chat orchestration
agent: plan
---

Before planning:
- read `AGENTS.md`, `contracts/demo-profile.json`, `contracts/source-registry.json`;
- inspect repository and `.demo-run/state.json` if present;
- never edit `.demo-run/state.json`;
- this command is planning-only: do not implement yet.

Plan must include: goal, current facts, minimal files, interfaces, tests, external assumptions, risks/fallback, out-of-scope, acceptance criteria, stop condition. Use `NOT_MEASURED` for unverified facts.

# M06 — Grounded Chat
Plan `question -> retrieval -> sufficiency -> LLMProviderPort -> structured result -> citation validation -> ANSWER/REFUSAL`. Treat retrieved text as untrusted data. Produce short channel-friendly answers. No Zalo-specific logic.
