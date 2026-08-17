# Development Standards

- Python 3.12+, type hints, Pydantic v2, SQLAlchemy 2 async, Alembic, httpx, pytest.
- External calls: explicit timeout, normalized error, bounded retry, bounded payload.
- Config: validated settings, fail-fast required values, no secret defaults.
- Structured logs: request/conversation/source/document/provider/operation/duration/outcome; never API key/token/Zalo session.
- Database: migrations, transactions, parameterized queries.
- Evidence: unexecuted checks are `NOT_MEASURED`, never PASS.
