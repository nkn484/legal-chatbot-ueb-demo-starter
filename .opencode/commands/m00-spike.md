---
description: Plan M00 external integration feasibility spike
agent: plan
---

Before planning:
- read `AGENTS.md`, `contracts/demo-profile.json`, `contracts/source-registry.json`;
- inspect repository and `.demo-run/state.json` if present;
- never edit `.demo-run/state.json`;
- this command is planning-only: do not implement yet.

Plan must include: goal, current facts, minimal files, interfaces, tests, external assumptions, risks/fallback, out-of-scope, acceptance criteria, stop condition. Use `NOT_MEASURED` for unverified facts.

# M00 — Integration Feasibility Spike
Plan minimal measured spikes for SHINE SHOP, VBQPPL and Zalo Personal.

SHINE: private credential, exact model discovery, one bounded Responses request, status/request-id/retry behavior; never print key.
VBQPPL: inspect SOAP operations; propose minimal READ_ONLY allowlist for discovery/metadata/content; never call mutations.
Zalo: isolated `Zalo -> bridge -> normalized webhook -> echo -> bridge -> Zalo`; record session/account/rate-limit risks.
Expected evidence files under `docs/evidence/`. No M01 implementation.
