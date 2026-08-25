# Zalo Legal Chat Demo Review

Final decision: `LLM_REWORK`

## Integration Result

The existing Zalo webhook, inbound parser, HMAC identity/delivery mechanism,
durable binding/outbound deduplication and Official Bot sender are reused. No
second webhook, token setting, sender or Zalo SDK was added.

The new channel-neutral entrypoint is `LegalChatApplication.ask()`. M08 runtime
selects the P1-P10 bridge only under `LEGAL_CHAT_PIPELINE_ENABLED`; the existing
channel integration continues to own inbound/outbound behavior.

## Live LLM Readiness

P2 live is not ready. The only alternate available provider model,
`gpt-5.6-terra`, timed out in all five 3-second strict-schema attempts. P2
therefore remains deterministic-first and operational through its verified
fallback.

P4 has one successful 1 document x 1 sub-intent live proposal, but 3-candidate
and 8-candidate batches timed out at the bounded 15-second stage budget. The
matrix route remains deterministic classifier fallback with bounded batch
suppression. P4 live matrix quality is not established.

## Gate

The required real Zalo external send was not executed because P2 live acceptance
failed. Sending a real user-facing message under a `DEMO_READY` claim would be
misleading. The next required work is provider/model execution remediation for
P2, followed by a fresh five-run P2 acceptance probe and then the existing-Zalo
end-to-end test.

This does not alter P2/P4 legal semantics, P5/P6 corrections, P11 state, legal
quality, release readiness, or benchmark status.
