---
description: Plan M07 bounded multi-turn conversation; never implement without approval
agent: plan
---

Before planning:
- read `AGENTS.md`, `contracts/demo-profile.json`, `contracts/source-registry.json`;
- inspect repository and `.demo-run/state.json` if present;
- never edit `.demo-run/state.json`;
- this command is planning-only: refuse implementation unless user gives explicit approval.

Current gate: M06 `PASS`; M07 `NOT_STARTED`; M08 `NOT_STARTED`. M07 depends on M06 and owns the
`multi-turn conversation` DEMO_BLOCKER. Use `demo_gate` only; never directly edit state. Do not start
M07 before explicit user approval.

Plan must include: goal, current facts, minimal files, interfaces, tests, external assumptions,
risks/fallback, out-of-scope, acceptance criteria, stop condition. Use `NOT_MEASURED` for unverified facts.

# M07 — Conversation
Plan channel-neutral state over M06: server-generated opaque UUID conversation ID; bounded recent turns,
mechanical rolling summary, active topic, document/citation references; never unlimited history. No auth
claim or Zalo identity; M08 later owns ChannelPort/Zalo mapping/payload/session/cookie/bridge. No public
API, provider/source adapters, semantic work or M09.

Required future phases/gates: (1) contracts/policy + M06 optional context/retrieval-query seam + schema;
(2) repository/concurrency/idempotency/retention; (3) bounded context/summary/service with fake M06;
(4) PG vertical, separately gated optional live path, regressions/evidence/submit. Require Oracle gates
between phases. Three normalized tables are required: conversations, exchanges, exchange references;
no free JSONB state bag. Preserve M05 authority and never delete M05 evidence.

Guardrails/evidence: context ≤1000, prompt ceiling remains 12000; current text ≤4000 or fixed
clarification; temporal guard only scans current question; history is untrusted context, never evidence.
Prove bounds, no unlimited history, one M06 call for reserved work, duplicate/no-second-call, busy,
concurrency, lease/no replay, CAS conflicts, refs server-derived, retention/deletion, M05 preservation,
privacy sentinels, `0004→0003→0001→0004`, M00–M06 regressions and Docker health. Do not log delivery
key/raw user/assistant/summary/topic/reference IDs/prompt/provider body. After future M07 submission,
stop before M08.
