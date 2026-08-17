---
description: Plan M01 FastAPI/PostgreSQL foundation
agent: plan
---

Before planning:
- read `AGENTS.md`, `contracts/demo-profile.json`, `contracts/source-registry.json`;
- inspect repository and `.demo-run/state.json` if present;
- never edit `.demo-run/state.json`;
- this command is planning-only: do not implement yet.

Plan must include: goal, current facts, minimal files, interfaces, tests, external assumptions, risks/fallback, out-of-scope, acceptance criteria, stop condition. Use `NOT_MEASURED` for unverified facts.

# M01 — Foundation
Plan smallest runnable FastAPI project: validated settings, JSON logging, error handling, `/live`, `/ready`, PostgreSQL16+pgvector Docker Compose, SQLAlchemy2 async, Alembic, pytest. Do not implement Provider/RAG/Zalo yet. PASS target: compose up, DB ready, API starts, health works, tests pass.
