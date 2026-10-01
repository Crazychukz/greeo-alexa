"""Structured logs that never contain secrets.

Every log record passes through RedactSecrets before it is formatted, so a token that
reaches a log call by accident (in a message, an argument, or an exception) is replaced.
Logs identify listeners by numeric id, never by name or external id.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

REDACTED = "[redacted]"
SECRET_PATTERNS = (
    # Authorization header values and bearer tokens in any form.
    re.compile(r"(?i)(authorization['\"]?\s*[:=]\s*['\"]?)(?:bearer\s+)?[^\s'\",}]+"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    # Greeo demo tokens, wherever they appear.
    re.compile(r"()greeo_[A-Za-z0-9_-]{16,}"),
    # Common secret-bearing keys in dicts, query strings and JSON.
    re.compile(
        r"(?i)((?:access_token|refresh_token|client_secret|api[_-]?key|password|token)"
        r"['\"]?\s*[:=]\s*['\"]?)[^\s'\",}&]+"
    ),
)


def redact(text: str) -> str:
    """Replace anything that looks like a credential."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: match.group(1) + REDACTED, text)
    return text


class RedactSecrets(logging.Filter):
    """Render the message, redact it, and drop the raw arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        if record.exc_info:
            # Format the traceback now so it can be redacted too.
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, and the error if any."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_text:
            entry["error"] = record.exc_text
        return json.dumps(entry, ensure_ascii=False)
