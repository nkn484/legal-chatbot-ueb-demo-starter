# Zalo Legal Chat Integration

Decision: `LLM_REWORK`

The existing Official Zalo Bot integration is reused unchanged: the configured
webhook path remains `/webhooks/zalo-bot`, existing inbound authentication and
deduplication remain in `ChannelService`, and the existing Official Bot sender
remains the only outbound adapter.

`LegalChatApplication.ask()` is connected at the existing grounded-chat seam,
so the channel does not call P1-P10 phases directly. A local real PostgreSQL
Q06 application run returned a non-empty P10 answer and preserved correlation
metadata.

| Stage | Live status | Safe production route |
| --- | --- | --- |
| P2 | Not ready: `gpt-5.6-terra` timed out 5/5 at 3 seconds | Deterministic-first fallback |
| P4 | One 1x1 batch succeeded; larger batches timed out | Deterministic classifier fallback for matrix batches |

No real Zalo message was sent. The external end-to-end test is intentionally
deferred because P2 live acceptance requires 5/5 complete and schema-valid
calls, which is not currently met. No token, prompt, response, chain-of-thought
or webhook secret appears in these artifacts.
