---
description: Plan M08 ChannelPort and Zalo Personal bridge
agent: plan
---

Before planning:
- read `AGENTS.md`, `contracts/demo-profile.json`, `contracts/source-registry.json`;
- inspect repository and `.demo-run/state.json` if present;
- never edit `.demo-run/state.json`;
- this command is planning-only: do not implement yet.

Plan must include: goal, current facts, minimal files, interfaces, tests, external assumptions, risks/fallback, out-of-scope, acceptance criteria, stop condition. Use `NOT_MEASURED` for unverified facts.

# M08 — Zalo Channel
Plan `ChannelPort`, normalized message contracts, authenticated backend webhook, isolated Node/TS personal bridge, private session handling, inbound dedup, outbound rate limit, friendly formatting, E2E test. Bridge must never retrieve or call SHINE directly. If live integration is blocked, report measured blocker; do not bypass ChannelPort.
