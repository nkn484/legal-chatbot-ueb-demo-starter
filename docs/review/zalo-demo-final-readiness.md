# Zalo Demo Final Readiness

Final decision: `P2_LIVE_REWORK`

The Zalo integration remains frozen and reusable through the existing
`/webhooks/zalo-bot` route, `ChannelService`, `ConversationService`, Official
Bot sender and durable delivery deduplication. `LegalChatApplication.ask()` is
connected at the existing grounded-chat seam and local P1-P10 PostgreSQL
execution is operational.

## P2 Live

`gpt-5.6-terra` was measured at 3, 5, 8, 12 and the user-authorized 18-second
budget. The 18-second five-call acceptance produced only 3/5 complete,
schema-valid calls, and successful responses did not meet the separate material
dimension acceptance. P2 remains deterministic-first.

## P4 Live

At 25 seconds, a 3-document x 4-sub-intent batch completed live in 13.30
seconds, while 1- and 2-document batches returned invalid structured output.
The representative Q06 matrix opened its circuit after a batch failure and
completed with 0% live assessment coverage. Per-batch deterministic fallback
and circuit suppression remain the production-safe behavior.

## Zalo External Test

The local processing path emitted one ETA status before one final P10 answer,
with correlation ID preserved. No real external Zalo message was sent: the P2
5/5 live acceptance failed, so performing the external test would not satisfy
the required `DEMO_READY` evidence. No webhook, token configuration or Official
Bot sender was rebuilt or replaced.

No full Set A, P12 or P11 run occurred. This result does not change legal
semantics, P5/P6 behavior, legal quality or release readiness.
