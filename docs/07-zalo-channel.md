# Official Zalo Bot Channel

M08 uses the official Zalo Bot Manager and Bot API. A user chats from a personal Zalo account with the managed bot; the bot receives official webhook events and replies through `sendMessage`. QR, browser cookies, Personal-account automation and `zca-js` are not used.

Channel adapter duties only: authenticate and normalize the official webhook, derive opaque identities, call the channel-neutral conversation boundary, format server-owned citations, and send one bounded outbound message. Raw Zalo IDs and credentials never enter Chat/Retrieval/Conversation contracts.

Use runtime-only bot token/webhook secret and a public HTTPS callback configured through Bot Manager. Do not log or commit tokens, raw payloads, raw IDs, user text, answer text or citations. M00 Bot/ngrok evidence is regression evidence, not proof of M08 durability or retry semantics.
