import logging

import structlog

ALLOWED = {
    "frames",
    "version",
    "user_id",
    "service",
    "environment",
    "trace_id",
    "job_id",
    "workspace_id",
    "model_id",
    "duration_ms",
    "event",
    "level",
    "timestamp",
    "request_id",
    "telegram_user_id",
    "provider_id",
    "operation",
    "status",
    "duration",
    "error_code",
    "input_tokens",
    "output_tokens",
}


def safe_fields(logger, method, event):
    import json

    from app.integrations.sanitizer import ExternalToolOutputSanitizer
    from app.platform.telemetry import TRACE

    event = {**TRACE.get(), **event}
    return json.loads(
        ExternalToolOutputSanitizer().clean(
            {key: value for key, value in event.items() if key in ALLOWED}
        )
    )


def configure_logging(level="INFO"):
    logging.basicConfig(level=level, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    logging.getLogger("aiogram").setLevel(logging.CRITICAL)
    logging.getLogger("mcp").setLevel(logging.CRITICAL)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            safe_fields,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
