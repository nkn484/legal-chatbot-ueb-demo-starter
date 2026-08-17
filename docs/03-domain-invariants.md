# Domain Invariants

1. Every document has provenance (`SOURCE_FETCH` or `MANUAL_UPLOAD`).
2. Manual upload never impersonates VBQPPL/VNU/UEB.
3. Content changes produce a distinct immutable version/hash.
4. Citation resolves `citation -> chunk -> document_version -> document -> provenance`.
5. LLM cannot manufacture legal URL/number/article/citation metadata.
6. Insufficient evidence => clarification/refusal, not fabrication.
7. Chat is provider-independent.
8. Ingestion is source-independent.
9. Chat is channel-independent.
10. Conversation context is bounded.
11. Secrets never enter Git/logs/prompts/responses.
