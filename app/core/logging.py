import logging

import structlog

ALLOWED = {
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
    return {key: value for key, value in event.items() if key in ALLOWED}


def configure_logging(level="INFO"):
    logging.basicConfig(level=level, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    logging.getLogger("aiogram").setLevel(logging.CRITICAL)
    structlog.configure(
        processors=[
            safe_fields,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
