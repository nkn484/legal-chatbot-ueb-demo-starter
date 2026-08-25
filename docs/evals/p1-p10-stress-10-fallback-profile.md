# P1-P10 Stress Test: Ten Controlled Requests

Runtime profile: `LEGAL_CHAT_PIPELINE_ENABLED=true`, P2 deterministic-first,
P4 deterministic classifier fallback, P11 OFF.

Result: 7/10 requests completed through P10. Median completed duration was
3.02 seconds. This is an engineering-flow stress result only; it does not score
legal answer quality, citations or release readiness.

| Case | Status | Engineering observation |
| --- | --- | --- |
| Q01 | Failed | P6 rejected missing eligible P5 authority-family state. |
| Q02 | Completed | P10 answer non-empty. |
| Q03 | Failed | P6 rejected missing eligible P5 authority-family state. |
| Q04 | Completed | P10 answer non-empty. |
| Q05 | Completed | 15 P5 families; 15 P6 evidence. |
| Q06 | Completed | 11 P5 families; 20 P6 evidence. |
| Q07 | Completed | P10 answer non-empty. |
| Q08 | Failed | P2 sub-intent `retrieval_concepts` validation failure. |
| Q09 | Completed | P10 answer non-empty. |
| Q10 | Completed | P6 evidence 10; one material sub-intent remains unsupported. |

The input consists of one non-authoritative representative control per parent
case from the M2 Set B file. It supplies only question text and no expected
document IDs or Oracle data to runtime behavior.
