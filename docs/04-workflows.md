# Workflows

## Ingestion
`Trigger -> Source Registry -> LegalSourcePort -> VBQPPL -> Normalize -> Dedup/Version -> Extract -> Chunk -> Embed -> Index -> READY`

## Chat
`Inbound -> Conversation -> standalone query -> Hybrid Retrieval -> Evidence Filter -> sufficient? -> SHINE via LLMProviderPort -> Citation Validation -> channel-friendly response`

## Zalo
`Zalo Personal -> isolated bridge -> normalized webhook -> ChannelPort -> Chat Core -> normalized outbound -> bridge -> Zalo`
