# Operational telemetry

Structured JSON logs allowlist identifiers, event/status/error code, service/environment, trace/request/job/workspace/provider/model IDs and duration. Global sanitization removes credential-like material. SDK/HTTP raw logs remain suppressed. W3C traceparent is propagated across API, Telegram, durable job receipt, worker and outgoing HTTP; baggage and arbitrary incoming attributes are ignored.

The bounded in-process registry emits Prometheus-compatible counters and latency histograms at authenticated `/admin/metrics`. It includes model calls/tokens/estimated cost, latency/errors/fallbacks, tools, integration calls, API/Telegram updates, jobs/duration/failures, queue/worker lag, storage, DB pool and Redis errors. Queue/storage/active-job gauges are refreshed from SQL. Histograms have fixed buckets and no user labels, preventing unbounded cardinality. Aggregate deployment metrics by scraping each replica; counters are not represented as durable billing.

`ErrorTracker` is a pluggable sanitized interface: exception class, function/line frames, service/version and trace ID only. It never exports messages, source text, locals, headers or uploads. External error/trace exporters are optional and have not been provisioned. SQL usage/audit/graph data remains durable independently of process metrics.

`/health` is liveness; `/ready` checks DB, Redis and active bot/worker tasks, not all providers. Production/staging startup checks critical dependencies. Version metadata is exposed through admin health. Local tests prove traces/metrics/redaction, not a deployed observability backend.
