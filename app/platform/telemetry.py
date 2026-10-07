"""Bounded Prometheus metrics and W3C trace context, without payload attributes."""

import contextvars
import re
import uuid
from collections import defaultdict
from contextlib import contextmanager

TRACE = contextvars.ContextVar("trace", default={})
COUNTERS = defaultdict(float)
HISTOGRAMS = defaultdict(lambda: [0, 0.0, [0] * 8])
BUCKETS = (0.01, 0.05, 0.1, 0.5, 1, 5, 30, float("inf"))
METRICS = {
    "telegram_updates_total",
    "api_requests_total",
    "active_jobs",
    "job_duration",
    "job_failures",
    "provider_latency",
    "provider_errors",
    "model_calls",
    "model_tokens",
    "model_cost",
    "fallback_count",
    "tool_calls",
    "approval_wait_time",
    "mcp_calls",
    "github_calls",
    "workspace_storage",
    "queue_depth",
    "worker_lag",
    "db_pool_usage",
    "redis_errors",
}


def metric(name, amount=1, observe=False):
    if name not in METRICS:
        return
    if observe:
        item = HISTOGRAMS[name]
        item[0] += 1
        item[1] += amount
        for i, bound in enumerate(BUCKETS):
            item[2][i] += amount <= bound
    else:
        COUNTERS[name] += amount


def render_metrics():
    for name in METRICS:
        if name not in HISTOGRAMS:
            COUNTERS.setdefault(name, 0)
    lines = [f"wakeelm_{name} {value}" for name, value in sorted(COUNTERS.items())]
    for name, (count, total, buckets) in sorted(HISTOGRAMS.items()):
        for bound, count_bucket in zip(BUCKETS, buckets):
            label = "+Inf" if bound == float("inf") else str(bound)
            lines.append(f'wakeelm_{name}_bucket{{le="{label}"}} {count_bucket}')
        lines.extend([f"wakeelm_{name}_count {count}", f"wakeelm_{name}_sum {total}"])
    return "\n".join(lines) + "\n"


@contextmanager
def trace_context(parent=None, **attributes):
    # Incoming IDs are identifiers only; no baggage or arbitrary attributes are accepted.
    trace_id = uuid.uuid4().hex
    if parent and re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-0[01]", parent):
        incoming = parent.split("-")[1]
        if incoming != "0" * 32:
            trace_id = incoming
    allowed = {
        k: v
        for k, v in attributes.items()
        if k in {"request_id", "job_id", "user_id", "workspace_id", "provider_id", "model_id"}
    }
    token = TRACE.set({"trace_id": trace_id, "span_id": uuid.uuid4().hex[:16], **allowed})
    try:
        yield TRACE.get()
    finally:
        TRACE.reset(token)


def trace_headers():
    trace = TRACE.get()
    return {"traceparent": f"00-{trace['trace_id']}-{trace['span_id']}-01"} if trace else {}


class ErrorTracker:
    """Pluggable safe sink; no exception message, locals or source text is ever exported."""

    def __init__(self, sink=None):
        self.sink = sink

    def capture(self, exc, version, service="bot-api"):
        frames = []
        tb = exc.__traceback__
        while tb and len(frames) < 20:
            frames.append({"function": tb.tb_frame.f_code.co_name, "line": tb.tb_lineno})
            tb = tb.tb_next
        event = {
            "type": type(exc).__name__,
            "frames": frames,
            "version": version,
            "service": service,
            "trace_id": TRACE.get().get("trace_id"),
        }
        if self.sink:
            self.sink(event)
        else:
            import structlog

            structlog.get_logger().error(
                "error_captured",
                error_code=event["type"],
                frames=frames,
                version=version,
                service=service,
                trace_id=event["trace_id"],
            )
        return event
