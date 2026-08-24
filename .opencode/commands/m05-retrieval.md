---
description: Plan M05 hybrid retrieval and citation
agent: plan
---

Before planning:
- read `AGENTS.md`, `contracts/demo-profile.json`, `contracts/source-registry.json`;
- inspect repository and `.demo-run/state.json` if present;
- never edit `.demo-run/state.json`;
- this command is planning-only: do not implement yet.

Plan must include: goal, current facts, minimal files, interfaces, tests, external assumptions, risks/fallback, out-of-scope, acceptance criteria, stop condition. Use `NOT_MEASURED` for unverified facts.

# M05 — Retrieval + Citation
Plan Retrieval + Citation only: no M06/Chat/LLM/provider/channel/conversation. Plan lexical-only live search with bounded query/top-k and `LATEST_INGESTED` filtering: greatest `version_number` per stable document identity, applied before rank/limit; this is latest ingested snapshot, not legally current/effective. `local-hash-v1` is `demo_non_semantic`, `semantic_ready=false`: no vector query/SQL/live RRF contribution; RRF may be a fake-list-only pure test helper. Include `0003` generated stored simple-FTS vector + GIN, atomic retrieval-run/citation traceability, and resolver `citation -> chunk -> version -> document -> selected provenance`; LLM must never supply authoritative citation metadata. Do not infer amendment/replacement/repeal/validity/legal effect from text or metadata; temporal/as-of/current-effect requests return `UNSUPPORTED_TEMPORAL_SCOPE` without misleading citations. Historical immutable citations remain resolvable after newer ingestion; reject only malformed/dangling, foreign/mismatched-run, provenance-version-mismatched, or explicit scope-violating citations.
