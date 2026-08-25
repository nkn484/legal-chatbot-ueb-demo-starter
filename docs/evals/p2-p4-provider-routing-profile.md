# P2/P4 Provider Routing Profile

Decision: `ROUTING_PASS`

P2 deterministic-first: `True`
P2 model: `None`
P2 budget: `3.0` seconds
P4 model: `gpt-5.6-sol`
P4 budget: `15.0` seconds
P4 batch size: `8`

## Measurements

P2 deterministic: `FALLBACK_DISABLED` in `0.9` ms; fallback used: `True`.
P2 optional live: `DEFERRED`.

| Probe | Duration ms | Outcome | Structured valid | LLM / fallback assessments |
| --- | ---: | --- | --- | --- |
| ONE_CANDIDATE_ONE_SUBINTENT | 3334.5 | LLM_PROPOSALS | True | 1 / 0 |
| THREE_CANDIDATES | 15009.2 | PROVIDER_TIMEOUT | False | 0 / 12 |
| REPRESENTATIVE_BATCH | 15013.6 | PROVIDER_TIMEOUT | False | 0 / 32 |

No raw prompts, responses, or chain-of-thought are persisted.
