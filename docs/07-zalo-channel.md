# Zalo Personal Channel

Official Zalo developer surface centers on Official Account APIs/webhooks. Therefore personal-account automation is an experimental bridge boundary.

Bridge duties only: receive event, normalize, authenticate webhook, send outbound message. It must not perform retrieval, call SHINE, or access legal business DB directly.

Use a test account for spike/demo; keep session/cookies out of Git/logs. Architecture must allow replacing the bridge with Zalo OA later without changing Chat/Retrieval.
