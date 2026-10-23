"""
logging_config.py — structured logging with a per-request correlation id.

* prod  : one JSON object per line. Cloud Logging maps ``severity`` and
          ``message`` automatically, so logs are searchable by request_id.
* dev   : readable single-line text.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(*, json_logs: bool, level: int = logging.INFO) -> None:
    """Idempotent: replaces any handlers installed earlier on the root logger."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    if json_logs:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"
        ))

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    # We log one line per request ourselves, so mute uvicorn's access log.
    logging.getLogger("uvicorn.access").disabled = True
    # Third-party chatter that would otherwise log every outbound request URL.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
