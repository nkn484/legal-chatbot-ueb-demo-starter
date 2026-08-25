# Set A Hybrid Stress Test - Provider Healthy

## Measured Run

The API was recreated after the provider configuration change. Local and public
ngrok health endpoints returned `200`. The stress runner used the current
PostgreSQL corpus, hybrid retrieval, and the configured provider adapter.

| Metric | Measured value |
|---|---:|
| Set A cases | 10 |
| Final answer outcome | 10 `ANSWER_GROUNDED` |
| Provider calls, success/failure | 10, `10 / 0` |
| Provider output validation failures | 0 |
| Citations per case | 3 |
| Semantic embedding calls, success/failure | 20, `20 / 0` |
| Real route p50 / p95 ms | `13,419.00 / 26,033.26` |
| API probe network errors | 0 |

## Retrieval and Selection Diagnostics

| Case | Source coverage | Final expected-document hit | Corpus blocker | Selected documents |
|---|---:|---|---|---|
| Q01 | 33.33% | none | `2725/QD-DHKT:NOT_IN_CATALOG` | 2566/QD-DHKT; 2795/QD-DHKT |
| Q02 | 33.33% | 812/QD-DHKT | none | 812/QD-DHKT |
| Q03 | 33.33% | none | none | 2566/QD-DHKT; 3577/QD-DHKT; 4588/DHKT-TCNS |
| Q04 | 66.67% | 4822/QD-DHKT | none | 2868/QD-DHQGHN; 4822/QD-DHKT |
| Q05 | 66.67% | none | none | 1144/QD-DHKT; 3089/QD-DHQGHN; 599/QD-DHQGHN |
| Q06 | 50.00% | 1666/QD-DHKT | `5858/QD-DHQGHN:QUARANTINED` | 16/NQ-HĐTĐHKT; 1666/QD-DHKT; 4606/UQ-DHKT |
| Q07 | 50.00% | none | none | 4555/QD-DHQGHN |
| Q08 | 50.00% | none | none | 1144/QD-DHKT |
| Q09 | 100.00% | 1768/QD-DHKT | none | 1768/QD-DHKT; 4868/QD-DHQGHN |
| Q10 | 100.00% | 08/2021/TT-BGDDT; 3626/QD-DHQGHN | `2725/QD-DHKT:NOT_IN_CATALOG` | 08/2021/TT-BGDDT; 2841/QD-DHKT; 3626/QD-DHQGHN |

The mean source coverage is `58.33%`; final expected-document hits appear in
five cases. This table is evaluation-only and does not feed production logic.

## Quality Target Assessment

The full-text baseline from 2026-08-22 is `5.49/10` and `4/10 PASS`. This run
establishes answer production and grounding, but it has not undergone blinded
independent legal review. Therefore the new legal-quality score and PASS count
are `NOT_MEASURED`; the `>= 8.50/10` and `>= 9/10 PASS` release target is not
established.

## Selection Root Causes To Address Before a Release Claim

1. Documents missing from the authorized catalog and quarantined evidence are
   candidate-generation gaps, not ranking defects.
2. The run used a raw hybrid path with a fixed final evidence budget of three;
   multi-issue questions can lose required authority coverage at this cutoff.
3. The deterministic question analyzer, concept-aware lexical construction,
   coverage matrix, dynamic evidence budget and one-shot repair were not active
   in this legacy stress-runner profile.
4. Direct-authority/applicability discipline must be evaluated before relying
   on semantic similarity as final legal selection.
5. High p95 provider latency requires a separate performance decision, but it
   does not change the legal-quality result.

Next required evidence is a sealed Set B/C run, approved generalized quality
ablation, and blinded legal review of the actual answers.
