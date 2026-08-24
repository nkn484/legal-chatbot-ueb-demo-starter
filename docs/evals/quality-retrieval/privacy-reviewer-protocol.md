# Privacy and expert reviewer protocol

## Permitted result fields

Markdown, JSON, and CSV evaluation outputs may contain case IDs, approved document numbers, source IDs, status labels, ranks, scores, aggregate counts, opaque unit IDs, repair query class, and repair round/count. They must not contain raw questions, answers, chunks, queries, prompts, URLs, UUIDs, credentials, user identifiers, raw chat payloads, or provider material. Raw analyzer and repair text is memory-only. Oracle expected identities are used after scoring only.

Static leakage lint for production is not part of this documentation-only lane. The offline validator lints these plan files and future machine-contract shapes for the listed prohibited content boundaries.

## Full-text review

The existing expert rubric baseline is **4/10** scores at least 7 and an average of **5.49/10**. Review full retrieved documents and generated answers only after the final configuration is frozen. The approved external full-text score workbook is the controlled review location; raw content and full-text scores do not enter machine JSON/CSV in this plan lane.

Each review record reports a non-personal reviewer ID or approved pseudonymous role, the rubric/contract version, configuration ID/version, and score. It does not make authority, legal effect, currentness, hierarchy, replacement, completeness, or applicability claims. Report aggregate before/after averages and the score threshold only.

Reviewer scoring is evaluation evidence, not a production activation mechanism. A future blinded confirmation set is needed before rollout, but it is not a prerequisite for finishing the evaluation/no-go decision.
