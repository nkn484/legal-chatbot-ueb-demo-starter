---
description: Plan M03 legal source abstraction and VBQPPL
agent: plan
---

Before planning:
- read `AGENTS.md`, `contracts/demo-profile.json`, `contracts/source-registry.json`;
- inspect repository and `.demo-run/state.json` if present;
- never edit `.demo-run/state.json`;
- this command is planning-only: do not implement yet.

Plan must include: goal, current facts, minimal files, interfaces, tests, external assumptions, risks/fallback, out-of-scope, acceptance criteria, stop condition. Use `NOT_MEASURED` for unverified facts.

# M03 — Source Abstraction + VBQPPL
Plan `LegalSourcePort`, registry integration, normalized source models, VBQPPL SOAP adapter using M00 read-only allowlist, VNU/UEB NOT_IMPLEMENTED placeholders, provenance mapping, errors/tests. Never guess VNU/UEB URLs. Never call SOAP mutation operations.
