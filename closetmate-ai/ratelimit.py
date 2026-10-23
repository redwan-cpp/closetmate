"""
ratelimit.py — small in-process sliding-window rate limiter.

This is a *first line of defence*: state is per process, so on Cloud Run each
instance counts separately. It stops scripted abuse and login brute-forcing
from a single source; edge protection (Cloud Armor / Cloudflare) comes in
Phase 3. Per-user cost control is the job of quota.py, which is stored in the
database and therefore exact.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Tuple

from fastapi import Depends, HTTPException, Request, status

from security import current_user_id
from settings import get_settings

_MAX_TRACKED_KEYS = 10_000


class SlidingWindowLimiter:
    def __init__(self, max_events: int, window_seconds: float,
                 clock: Callable[[], float] = time.monotonic):
        self.max_events = max_events
        self.window = window_seconds
        self._clock = clock
        self._events: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> Tuple[bool, int]:
        """Record an event. Returns (allowed, retry_after_seconds)."""
        now = self._clock()
        cutoff = now - self.window
        with self._lock:
            events = self._events.get(key)
            if events is None:
                events = self._events[key] = deque()
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.max_events:
                return False, self._retry_after(events, now)
            events.append(now)
            if len(self._events) > _MAX_TRACKED_KEYS:
                self._purge(cutoff)
            return True, 0

    def _retry_after(self, events: Deque[float], now: float) -> int:
        # An empty deque happens when max_events == 0 (everything is denied): wait a full window.
        if not events:
            return max(1, int(self.window) + 1)
        return max(1, int(events[0] + self.window - now) + 1)

    def peek(self, key: str) -> Tuple[bool, int]:
        """Like hit() but records nothing. Returns (allowed, retry_after_seconds)."""
        now = self._clock()
        cutoff = now - self.window
        with self._lock:
            events = self._events.get(key)
            if events is None:
                return True, 0
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.max_events:
                return False, self._retry_after(events, now)
            return True, 0

    def clear(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def _purge(self, cutoff: float) -> None:
        """Drop idle keys; if an attacker is minting keys faster than they expire, evict the oldest."""
        for key in [k for k, q in self._events.items() if not q or q[-1] <= cutoff]:
            del self._events[key]
        excess = len(self._events) - int(_MAX_TRACKED_KEYS * 0.8)
        if excess > 0:
            for key in list(self._events)[:excess]:      # dicts iterate in insertion order
                del self._events[key]

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


_LIMITERS: Dict[str, SlidingWindowLimiter] = {}
_REGISTRY_LOCK = threading.Lock()


def get_limiter(name: str, max_events: int, window_seconds: float) -> SlidingWindowLimiter:
    with _REGISTRY_LOCK:
        limiter = _LIMITERS.get(name)
        if limiter is None:
            limiter = _LIMITERS[name] = SlidingWindowLimiter(max_events, window_seconds)
        return limiter


def reset_all() -> None:
    """Test hook: forget every counter."""
    with _REGISTRY_LOCK:
        for limiter in _LIMITERS.values():
            limiter.reset()


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={"code": "rate_limited", "message": "Too many requests. Please slow down."},
        headers={"Retry-After": str(retry_after)},
    )


def client_ip(request: Request) -> str:
    """
    The caller's IP for rate limiting.

    X-Forwarded-For is client-controlled at its LEFT end (a caller can send any
    value, and each proxy appends to the right), so we never read the leftmost
    entry. With TRUSTED_PROXY_HOPS=N we take the Nth entry from the RIGHT, i.e.
    the address our own N proxies saw. With 0 we use the socket peer address.
    """
    hops = get_settings().trusted_proxy_hops
    if hops > 0:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops][:64]
    return request.client.host if request.client else "unknown"


def rate_limit_ip(name: str, max_events: int, window_seconds: float):
    """Dependency factory: limit by client IP."""
    limiter = get_limiter(name, max_events, window_seconds)

    def _dep(request: Request) -> None:
        allowed, retry_after = limiter.hit(client_ip(request))
        if not allowed:
            raise _too_many(retry_after)

    return _dep


def rate_limit_user(name: str, max_events: int, window_seconds: float):
    """Dependency factory: limit by authenticated user id."""
    limiter = get_limiter(name, max_events, window_seconds)

    def _dep(user_id: str = Depends(current_user_id)) -> None:
        allowed, retry_after = limiter.hit(user_id)
        if not allowed:
            raise _too_many(retry_after)

    return _dep
