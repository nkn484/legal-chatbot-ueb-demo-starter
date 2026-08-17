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
Plan hybrid lexical/vector search, bounded top-k, active-version filtering, evidence object, citation resolver `citation -> chunk -> version -> provenance`, evidence-sufficiency decision, dangling/foreign citation rejection. LLM must never supply authoritative citation metadata.
