"""Structured JSON logging with secret redaction.

Every record passes through ``RedactingFilter`` so that API keys, bearer
tokens and session cookies never reach log sinks, even if a developer
accidentally logs them. Transcript text must not be logged at all; log IDs
and counts instead.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),  # OpenAI-style keys
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|x-api-key|password|secret|token)([\"'\s:=]+)([^\s\"',}]{4,})"),
]

REDACTED = "[REDACTED]"


def redact(text: str) -> str:
    """Remove anything that looks like a credential from free text."""
    out = text
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            out = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
        else:
            out = pattern.sub(REDACTED, out)
    return out


def redact_value(value: str, secret: str | None) -> str:
    """Redact a specific known secret plus generic patterns."""
    if secret and len(secret) >= 4:
        value = value.replace(secret, REDACTED)
    return redact(value)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: redact(str(v)) for k, v in record.args.items()}
            else:
                record.args = tuple(redact(str(a)) for a in record.args)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update({k: redact(str(v)) if isinstance(v, str) else v for k, v in extra.items()})
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # httpx logs full URLs at INFO; keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def log_event(logger: logging.Logger, msg: str, **fields: Any) -> None:
    logger.info(msg, extra={"fields": fields})
