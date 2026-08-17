---
description: Plan M04 ingestion and index
agent: plan
---

Before planning:
- read `AGENTS.md`, `contracts/demo-profile.json`, `contracts/source-registry.json`;
- inspect repository and `.demo-run/state.json` if present;
- never edit `.demo-run/state.json`;
- this command is planning-only: do not implement yet.

Plan must include: goal, current facts, minimal files, interfaces, tests, external assumptions, risks/fallback, out-of-scope, acceptance criteria, stop condition. Use `NOT_MEASURED` for unverified facts.

# M04 — Ingestion + Index
Plan `SourceDocument -> normalize -> identity -> immutable version/hash -> text -> chunk -> embedding -> pgvector index`. Preserve provenance, idempotent identical reingestion, no silent overwrite, configurable embedding port, CPU-friendly demo defaults, integration tests. Avoid distributed worker unless measured need.
