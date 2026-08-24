# M2 evaluation control-set methodology

## Purpose and boundary

This is a non-authoritative evaluation control set. It supports repeatable retrieval-behavior checks; it does not establish legal correctness, legal authority, completeness, or currentness. These artifacts are not fed into production logic, retrieval, prompting, runtime configuration, or corpus ingestion.

Human review is required before interpreting any evaluation result. The labels are controls for system behavior only, not expected legal answers. This document does not record or imply that human legal review has occurred.

## Set construction

- **Set B** contains 30 Vietnamese paraphrases: exactly three controls for each controlled parent case `Q01` through `Q10`. They preserve only the controlled question's meaning. Each is labeled `RETRIEVAL_COMPARABLE_TO_PARENT`; this is not a legal-answer or expected-document assertion.
- **Set C** contains 24 generic negative and boundary controls. Its labels permit a policy-level behavior such as clarification, refusal, or use of available evidence. They do not require a specific source, legal conclusion, authority, or currentness claim.

| Set | Category | Count |
| --- | --- | ---: |
| B | `PARAPHRASE` | 30 |
| C | `SINGLE_SOURCE_SUFFICIENCY` | 3 |
| C | `NO_EVIDENCE` | 4 |
| C | `UNRELATED_TO_UEB` | 3 |
| C | `UEB_MENTION_NO_ALL_SOURCES` | 3 |
| C | `AMBIGUOUS_DOCUMENT_IDENTITY` | 3 |
| C | `GENERAL_ADMINISTRATIVE_NONLEGAL` | 4 |
| C | `SYNTHETIC_METADATA_NUMBER` | 4 |
| **Total** |  | **54** |

## Reproducibility and linting

The machine-readable source is UTF-8 JSON. Its canonical form is JSON serialized with sorted keys, compact separators, and UTF-8 encoding. Canonical JSON SHA-256:

SHA-256: `41b25c2d6561f78405915241a56f654ed9dfcacecbe8a0c61c408e072fdaf6e8`

Run the evaluation-only validator from the repository root:

```text
python scripts/validate_m2_evaluation_set.py
```

It validates JSON schema and case IDs, counts, three paraphrases per parent, normalized duplicate questions, question bounds, URLs, UUIDs, control characters, and JSON/XLSX parity. It also performs no-benchmark-number linting: it loads only document-number tokens from the controlled workbook grading column and rejects an exact normalized token appearing in these artifacts. The parser neither outputs nor carries forward controlled workbook questions, answers, or review comments. Synthetic metadata-number queries in Set C use evaluation-only numbers and are linted against the same benchmark token set.

To regenerate the reviewer XLSX from JSON and immediately verify parity:

```text
python scripts/validate_m2_evaluation_set.py --write-xlsx
```

The validator performs no model, provider, database, network, retrieval-runtime, or production writes.
