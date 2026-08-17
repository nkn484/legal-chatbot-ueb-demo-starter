---
description: Plan M07 bounded multi-turn conversation
agent: plan
---

Before planning:
- read `AGENTS.md`, `contracts/demo-profile.json`, `contracts/source-registry.json`;
- inspect repository and `.demo-run/state.json` if present;
- never edit `.demo-run/state.json`;
- this command is planning-only: do not implement yet.

Plan must include: goal, current facts, minimal files, interfaces, tests, external assumptions, risks/fallback, out-of-scope, acceptance criteria, stop condition. Use `NOT_MEASURED` for unverified facts.

# M07 — Conversation
Plan conversation ID, bounded recent turns, rolling summary, active legal topic, referenced docs and citations; follow-up to standalone retrieval query; token/context budget; isolation tests. Never send unlimited history.
