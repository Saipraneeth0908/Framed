"""Background worker: event loader, outbox relay, scheduled jobs, KPI exporter.

No ingress. Holds the `etl` role. Everything it does is idempotent, because
at-least-once delivery is the only kind worth designing for.
"""
