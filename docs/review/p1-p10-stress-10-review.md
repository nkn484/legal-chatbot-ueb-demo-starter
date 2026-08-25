# P1-P10 Stress Test Review

Decision: `PIPELINE_REWORK`

The legal pipeline feature gate was enabled for the test process. Seven of ten
controlled inputs completed P1-P10 with real PostgreSQL P3/P6/P8 readers and
non-empty P10 output. Three inputs did not reach terminal answer because of
engineering state/validation failures, not because of a provider or database
outage.

The stress result confirms the feature can process many real requests under
fallback-safe mode, but it is not yet robust across the ten-case workload. The
failed P6 family-state cases and P2 validation case require separate corrective
work before declaring broad demo request handling reliable.

P11 remained OFF. No full legal-quality evaluation, P12 run, external Zalo send
or benchmark scoring was performed.
