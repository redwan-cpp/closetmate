"""
quota.py — per-user, per-feature monthly usage limits.

This is the cost brake: every metered feature (LLM chat, vision scans,
background removal, insights) is counted in the ``usage_counters`` table, which
is shared by all Cloud Run instances, so the limit is exact.

A slot is consumed *before* the expensive call and refunded if our side fails
(provider outage, timeout) so users are never charged for our errors.
"""
from __future__ import annotations

import asyncio
import calendar
import contextvars
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy import text

from database import db_session
from security import current_user_id
from settings import QUOTA_FEATURES, get_settings


@dataclass(frozen=True)
class QuotaResult:
    allowed: bool
    used: int
    limit: int


# ---------------------------------------------------------------------------
# "Was this request already billed by a provider?"
#
# A refund is only fair when OUR side failed before any paid call succeeded. If a
# provider already answered (and charged us), a later parse/validation failure must
# NOT refund — otherwise a user could craft input that makes the app pay for a call
# and then give them the unit back, repeatedly. Provider code calls mark_billed();
# the flag is a mutable list so it survives asyncio.to_thread's context copy.
# ---------------------------------------------------------------------------
_billed_flag: contextvars.ContextVar[Optional[List[bool]]] = contextvars.ContextVar(
    "quota_billed_flag", default=None
)
_AI_FEATURES = frozenset({"chat", "vision", "insights"})


def _begin_tracking() -> None:
    _billed_flag.set([False])


def mark_billed() -> None:
    """Record that a paid provider call succeeded during the current metered request."""
    flag = _billed_flag.get()
    if flag is not None:
        flag[0] = True


def was_billed() -> bool:
    flag = _billed_flag.get()
    return bool(flag and flag[0])


def current_period(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def _seconds_until_next_period(now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    days = calendar.monthrange(now.year, now.month)[1]
    end = now.replace(day=days, hour=23, minute=59, second=59, microsecond=0)
    return max(1, int((end - now).total_seconds()) + 1)


def consume_quota(user_id: str, feature: str) -> QuotaResult:
    """Atomically take one unit. The upsert only fires while count < limit."""
    limit = get_settings().quota_limit(feature)
    if limit <= 0:
        return QuotaResult(False, 0, limit)

    with db_session() as db:
        row = db.execute(
            text("""
                INSERT INTO usage_counters (user_id, feature, period, count)
                VALUES (:u, :f, :p, 1)
                ON CONFLICT (user_id, feature, period) DO UPDATE
                    SET count = usage_counters.count + 1
                    WHERE usage_counters.count < :limit
                RETURNING count
            """),
            {"u": user_id, "f": feature, "p": current_period(), "limit": limit},
        ).fetchone()
    if row is None:
        return QuotaResult(False, limit, limit)
    return QuotaResult(True, int(row["count"]), limit)


def refund_quota(user_id: str, feature: str) -> None:
    with db_session() as db:
        db.execute(
            text("""
                UPDATE usage_counters SET count = count - 1
                WHERE user_id = :u AND feature = :f AND period = :p AND count > 0
            """),
            {"u": user_id, "f": feature, "p": current_period()},
        )


def usage_summary(user_id: str) -> Dict[str, Dict[str, int]]:
    """{feature: {used, limit}} for the current period — for the client's usage meter."""
    settings = get_settings()
    with db_session() as db:
        rows = db.execute(
            text("SELECT feature, count FROM usage_counters WHERE user_id = :u AND period = :p"),
            {"u": user_id, "p": current_period()},
        ).fetchall()
    used = {r["feature"]: int(r["count"]) for r in rows}
    return {
        feature: {"used": used.get(feature, 0), "limit": settings.quota_limit(feature)}
        for feature in QUOTA_FEATURES
    }


def consume_global(period: str, limit: int) -> bool:
    """Take one unit from the app-wide daily AI budget. False once ``limit`` is reached."""
    with db_session() as db:
        row = db.execute(
            text("""
                INSERT INTO usage_counters (user_id, feature, period, count)
                VALUES ('__global__', 'ai_calls', :p, 1)
                ON CONFLICT (user_id, feature, period) DO UPDATE
                    SET count = usage_counters.count + 1
                    WHERE usage_counters.count < :limit
                RETURNING count
            """),
            {"p": period, "limit": limit},
        ).fetchone()
    return row is not None


async def enforce_quota(user_id: str, feature: str) -> None:
    """Consume one unit or raise 429 (user over limit) / 503 (app-wide daily cap). Async-safe."""
    _begin_tracking()
    result = await asyncio.to_thread(consume_quota, user_id, feature)
    if not result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "quota_exceeded",
                "feature": feature,
                "limit": result.limit,
                "message": f"You've used all {result.limit} free {feature} requests this month.",
            },
            headers={"Retry-After": str(_seconds_until_next_period())},
        )

    # App-wide circuit breaker: free-tier farming (many accounts) must not be able to
    # run up an unbounded provider bill. 0 disables it.
    cap = get_settings().global_daily_ai_calls
    if cap > 0 and feature in _AI_FEATURES:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if not await asyncio.to_thread(consume_global, today, cap):
            await asyncio.to_thread(refund_quota, user_id, feature)   # not the user's doing
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "at_capacity",
                        "message": "The stylist is at capacity right now. Please try again later."},
                headers={"Retry-After": "3600"},
            )


async def release_quota(user_id: str, feature: str) -> None:
    """
    Give a unit back after OUR failure. No-op if a paid provider call already
    succeeded in this request. Shielded so a client disconnect can't skip it; never raises.
    """
    if was_billed():
        return
    try:
        await asyncio.shield(asyncio.to_thread(refund_quota, user_id, feature))
    except Exception:  # noqa: BLE001 — a failed refund must not mask the real error
        pass


@asynccontextmanager
async def metered(user_id: str, feature: str):
    """
    Consume a unit, run the body, and refund only if WE failed before any paid call
    succeeded (provider outage, our bug, cancellation). A 4xx raised in the body is the
    caller's fault and is not refunded. A 429/503 from the consume step itself never refunds.

        async with metered(uid, "chat"):
            return await do_the_expensive_thing()
    """
    await enforce_quota(user_id, feature)
    try:
        yield
    except HTTPException as exc:
        if exc.status_code >= 500:
            await release_quota(user_id, feature)
        raise
    except (Exception, asyncio.CancelledError):
        await release_quota(user_id, feature)
        raise


def require_quota(feature: str):
    """Dependency factory: authenticate, consume a unit, return the user_id."""

    async def _dep(user_id: str = Depends(current_user_id)) -> str:
        await enforce_quota(user_id, feature)
        return user_id

    return _dep
