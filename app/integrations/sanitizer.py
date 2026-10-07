import json
import re

from app.core.exceptions import SafeError

PATTERNS = [
    (
        "private_key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"
        ),
    ),
    (
        "token",
        re.compile(
            r"(?:gh[pousr]_[A-Za-z0-9_]{15,}|github_pat_[A-Za-z0-9_]{15,}|sk-[A-Za-z0-9_-]{15,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16})"
        ),
    ),
    (
        "credential",
        re.compile(
            r"(?i)(?:authorization|cookie|password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)\s*[=:]\s*[\"']?(?:Bearer\s+)?[^\s,;\"'}]{4,}"
        ),
    ),
]


class ExternalToolOutputSanitizer:
    def __init__(self, limit=1000000, secrets=()):
        self.limit, self.secrets = limit, tuple(s for s in secrets if s and len(s) >= 4)

    def clean(self, value):
        def scrub(item):
            if isinstance(item, dict):
                return {
                    key: "[REDACTED]"
                    if re.fullmatch(
                        r"(?i)(authorization|cookie|password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)",
                        str(key),
                    )
                    else scrub(val)
                    for key, val in item.items()
                }
            if isinstance(item, list):
                return [scrub(val) for val in item]
            return item

        text = json.dumps(scrub(value), ensure_ascii=False) if not isinstance(value, str) else value
        if len(text.encode()) > self.limit:
            raise SafeError("RESPONSE_TOO_LARGE")
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        for _, pattern in PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        return text

    def context(self, value, origin_label):
        return {"origin": origin_label, "trust": "UNTRUSTED", "text": self.clean(value)}
