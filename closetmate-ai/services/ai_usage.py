"""
ai_usage.py — record every LLM / vision call so cost is measured, not guessed.

One row per call goes into ``ai_usage``. ``scripts/usage_report.py`` turns the
rows into per-feature / per-user spend using prices from the environment.
Logging must never break a user request, so this module never raises.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from database import db_session

log = logging.getLogger(__name__)


def error_label(exc: BaseException) -> str:
    """Class name only — exception messages can contain prompt or user content."""
    return type(exc).__name__


def log_ai_usage(
    *,
    user_id: Optional[str],
    feature: str,
    provider: str,
    model: str,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    latency_ms: Optional[int] = None,
    ok: bool = True,
    error: Optional[str] = None,
) -> None:
    try:
        with db_session() as db:
            db.execute(
                text("""
                    INSERT INTO ai_usage
                        (user_id, feature, provider, model, input_tokens, output_tokens,
                         latency_ms, ok, error, created_at)
                    VALUES (:user_id, :feature, :provider, :model, :input_tokens,
                            :output_tokens, :latency_ms, :ok, :error, :created_at)
                """),
                {
                    "user_id": user_id,
                    "feature": feature,
                    "provider": provider,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": latency_ms,
                    "ok": 1 if ok else 0,
                    "error": error[:120] if error else None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
    except Exception:  # noqa: BLE001
        log.warning("could not record ai usage", exc_info=True)
        return
    log.info(
        "ai_call feature=%s provider=%s model=%s in=%s out=%s ms=%s ok=%s",
        feature, provider, model, input_tokens, output_tokens, latency_ms, ok,
    )
