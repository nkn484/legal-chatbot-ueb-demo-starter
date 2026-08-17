# Architecture — Modular Monolith

```text
Zalo Personal
   -> Experimental Bridge
   -> ChannelPort/Webhook
   -> Conversation
   -> Chat Orchestrator
      -> Retrieval -> Citation -> Document/Chunk/Provenance
      -> LLMProviderPort -> ShineShopAdapter [ACTIVE]
                         -> AnthropicAdapter [LATER]

LegalSourcePort
   -> VBQPPLAdapter [ACTIVE]
   -> VNUAdapter [LATER]
   -> UEBAdapter [LATER]
```

Suggested backend tree:
```text
src/legal_chatbot/
  api/ core/ providers/ sources/ documents/ ingestion/
  retrieval/ citations/ conversation/ chat/ channels/ db/
```

Use FastAPI + PostgreSQL + pgvector + Docker Compose. Zalo bridge may be separate Node/TypeScript process. Extract microservices only after measured need.
