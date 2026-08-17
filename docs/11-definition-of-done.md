# Definition of Demo Done

Measured end-to-end target:
```text
VBQPPL document -> provenance/version -> chunk/index -> retrieval -> validated citations -> SHINE -> bounded conversation -> Zalo -> user
```

Must include: SHINE live request; VBQPPL read-only live evidence; at least one indexed official document; insufficient-evidence behavior; follow-up conversation; Zalo receive/send path or USER-approved fallback only if a measured external blocker exists; repeatable local/Docker startup; health/readiness; structured logs; secret-free Git; regression tests.
