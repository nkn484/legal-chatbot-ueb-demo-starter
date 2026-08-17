# ADR-002 — Three Integration Ports
Status: ACCEPTED

Architecture invariants: `LLMProviderPort`, `LegalSourcePort`, `ChannelPort`.
They isolate the three known change axes: SHINE→Claude, VBQPPL→VNU→UEB, Zalo Personal→OA/Web/other channel.
