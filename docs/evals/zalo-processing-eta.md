# Zalo Processing ETA

Local controlled Q06 emitted `PROCESSING` before `FINAL`. The initial ETA was
the configured, user-facing range `30–60 giây`; the real PostgreSQL P1-P10
answer completed in 7.46 seconds and preserved the correlation ID.

Processing status is sent once per existing delivery HMAC. A processing-send
failure cannot block the existing terminal answer path. The estimator retains
only bounded runtime durations and switches from configured range to rolling
runtime telemetry after successful history exists.
