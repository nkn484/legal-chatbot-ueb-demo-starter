# ADR-001 — Modular Monolith for Demo
Status: ACCEPTED

Use one Python modular-monolith backend for demo speed and simpler E2E testing. Keep external adapters isolated. Zalo bridge may be separate due to different runtime/risk. Extract services only after measured scaling/security/deployment need.
