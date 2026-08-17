# Testing & Minimum Security

Unit: domain validation, citation mapping, provider/source/channel normalization, conversation bounds.
Integration: PostgreSQL/pgvector, VBQPPL read path, SHINE bounded request, webhook auth.
E2E: known document -> index -> question -> evidence -> SHINE -> citation -> response; final demo extends through Zalo.

DEMO_BLOCKER security: no secrets, input validation, no external stack trace, webhook auth, VBQPPL read-only allowlist, prompt-injection isolation, citation validation, provider timeout, SQL safety.
