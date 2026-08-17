---
description: Plan M09 demo hardening
agent: plan
---

Before planning:
- read `AGENTS.md`, `contracts/demo-profile.json`, `contracts/source-registry.json`;
- inspect repository and `.demo-run/state.json` if present;
- never edit `.demo-run/state.json`;
- this command is planning-only: do not implement yet.

Plan must include: goal, current facts, minimal files, interfaces, tests, external assumptions, risks/fallback, out-of-scope, acceptance criteria, stop condition. Use `NOT_MEASURED` for unverified facts.

# M09 — Demo Hardening
Plan only demo reliability: repeatable startup, migrations, health/readiness, bounded retries/timeouts, basic backup notes, smoke/E2E script, secret scan, structured logs, troubleshooting, demo data, limitations. Do not introduce deferred production infrastructure without measured need. Final target: `Zalo -> Conversation -> Retrieval -> Citation -> SHINE -> validated response -> Zalo`.
