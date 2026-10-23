"""ratelimit.py — sliding-window limiter, FastAPI dependencies and client-IP resolution."""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

import ratelimit
import security
from conftest import bearer
from ratelimit import SlidingWindowLimiter, client_ip, get_limiter, rate_limit_ip, rate_limit_user


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_limiter(clock, max_events=3, window=10.0) -> SlidingWindowLimiter:
    return SlidingWindowLimiter(max_events, window, clock=clock)


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# SlidingWindowLimiter
# ---------------------------------------------------------------------------

class TestHit:
    def test_allows_up_to_the_maximum_then_denies(self, clock):
        limiter = make_limiter(clock)
        assert [limiter.hit("k")[0] for _ in range(5)] == [True, True, True, False, False]

    def test_allowed_hits_report_zero_retry_after(self, clock):
        assert make_limiter(clock).hit("k") == (True, 0)

    def test_denied_hit_reports_how_long_to_wait(self, clock):
        limiter = make_limiter(clock, max_events=2, window=10)
        limiter.hit("k")
        clock.advance(4)
        limiter.hit("k")
        clock.advance(1)                                   # first event is 5 s old, 5 s remain
        allowed, retry_after = limiter.hit("k")
        assert allowed is False
        assert 5 <= retry_after <= 6                       # whole seconds, rounded up

    def test_retry_after_is_at_least_one_second(self, clock):
        limiter = make_limiter(clock, max_events=1, window=10)
        limiter.hit("k")
        clock.advance(9.999)
        assert limiter.hit("k")[1] >= 1

    def test_denied_hits_are_not_recorded(self, clock):
        limiter = make_limiter(clock, max_events=2, window=10)
        limiter.hit("k"), limiter.hit("k")
        for _ in range(50):
            limiter.hit("k")                               # hammering while blocked ...
        clock.advance(10)                                  # ... must not extend the block
        assert limiter.hit("k")[0] is True

    def test_events_expire_after_the_window(self, clock):
        limiter = make_limiter(clock, max_events=2, window=10)
        limiter.hit("k"), limiter.hit("k")
        assert limiter.hit("k")[0] is False
        clock.advance(9.99)
        assert limiter.hit("k")[0] is False
        clock.advance(0.02)                                # 10.01 s after the first events
        assert limiter.hit("k")[0] is True

    def test_window_is_sliding_not_fixed(self, clock):
        limiter = make_limiter(clock, max_events=2, window=10)
        limiter.hit("k")                                   # t=0
        clock.advance(6)
        limiter.hit("k")                                   # t=6
        clock.advance(5)                                   # t=11: the t=0 event expired, t=6 still counts
        assert limiter.hit("k")[0] is True
        assert limiter.hit("k")[0] is False

    def test_exact_window_boundary_counts_as_expired(self, clock):
        limiter = make_limiter(clock, max_events=1, window=10)
        limiter.hit("k")
        clock.advance(10)
        assert limiter.hit("k")[0] is True

    def test_keys_are_independent(self, clock):
        limiter = make_limiter(clock, max_events=1)
        assert limiter.hit("a")[0] is True
        assert limiter.hit("a")[0] is False
        assert limiter.hit("b")[0] is True

    def test_zero_max_events_denies_everything(self, clock):
        # Regression: used to raise IndexError (events[0] on an empty deque).
        limiter = make_limiter(clock, max_events=0)
        allowed, retry_after = limiter.hit("k")
        assert allowed is False and retry_after >= 1
        assert limiter.peek("k")[0] is False

    def test_hit_is_thread_safe(self):
        limiter = SlidingWindowLimiter(10, 60)
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda _: limiter.hit("shared")[0], range(80)))
        assert sum(results) == 10


class TestPeek:
    def test_unknown_key_is_allowed(self, clock):
        assert make_limiter(clock).peek("never-seen") == (True, 0)

    def test_peek_records_nothing(self, clock):
        limiter = make_limiter(clock, max_events=3)
        for _ in range(100):
            assert limiter.peek("k") == (True, 0)
        assert [limiter.hit("k")[0] for _ in range(4)] == [True, True, True, False]

    def test_peek_does_not_create_keys(self, clock):
        limiter = make_limiter(clock)
        limiter.peek("ghost")
        assert "ghost" not in limiter._events

    def test_peek_reports_a_full_window(self, clock):
        limiter = make_limiter(clock, max_events=2, window=10)
        limiter.hit("k"), limiter.hit("k")
        allowed, retry_after = limiter.peek("k")
        assert allowed is False and 10 <= retry_after <= 11

    def test_peek_sees_window_expiry(self, clock):
        limiter = make_limiter(clock, max_events=1, window=10)
        limiter.hit("k")
        assert limiter.peek("k")[0] is False
        clock.advance(10)
        assert limiter.peek("k") == (True, 0)

    def test_peek_does_not_consume_a_slot(self, clock):
        limiter = make_limiter(clock, max_events=1)
        limiter.peek("k")
        assert limiter.hit("k")[0] is True


class TestClearResetPurge:
    def test_clear_forgets_one_key_only(self, clock):
        limiter = make_limiter(clock, max_events=1)
        limiter.hit("a"), limiter.hit("b")
        limiter.clear("a")
        assert limiter.hit("a")[0] is True
        assert limiter.hit("b")[0] is False

    def test_clear_of_unknown_key_is_harmless(self, clock):
        make_limiter(clock).clear("nothing-here")

    def test_reset_forgets_everything(self, clock):
        limiter = make_limiter(clock, max_events=1)
        limiter.hit("a"), limiter.hit("b")
        limiter.reset()
        assert limiter.hit("a")[0] and limiter.hit("b")[0]

    def test_stale_keys_are_purged_when_the_table_is_full(self, clock, monkeypatch):
        monkeypatch.setattr(ratelimit, "_MAX_TRACKED_KEYS", 10)
        limiter = make_limiter(clock, window=10)
        for n in range(10):                                # exactly at the cap: no purge yet
            limiter.hit(f"old-{n}")
        clock.advance(100)                                 # everything above is long expired
        limiter.hit("fresh")                               # 11 keys > cap -> purge
        assert set(limiter._events) == {"fresh"}

    def test_key_flood_is_bounded_even_when_nothing_has_expired(self, clock, monkeypatch):
        monkeypatch.setattr(ratelimit, "_MAX_TRACKED_KEYS", 10)
        limiter = make_limiter(clock, window=1000)         # nothing ever expires during the test
        for n in range(200):
            limiter.hit(f"spoofed-{n}")
            assert len(limiter._events) <= 10
        assert "spoofed-199" in limiter._events            # the newest key survives
        assert "spoofed-0" not in limiter._events          # the oldest was evicted

    def test_live_keys_survive_a_purge_of_stale_ones(self, clock, monkeypatch):
        monkeypatch.setattr(ratelimit, "_MAX_TRACKED_KEYS", 5)
        limiter = make_limiter(clock, max_events=1, window=10)
        for n in range(4):
            limiter.hit(f"stale-{n}")                      # t=0
        clock.advance(6)
        limiter.hit("keep")                                # t=6
        clock.advance(5)                                   # t=11: stale-* expired, keep (5 s old) has not
        limiter.hit("new")                                 # 6 keys > cap -> purge
        assert set(limiter._events) == {"keep", "new"}
        assert limiter.hit("keep")[0] is False             # still remembered as rate-limited


class TestRegistry:
    def test_get_limiter_returns_one_instance_per_name(self):
        name = unique("registry")
        first = get_limiter(name, 5, 60)
        assert get_limiter(name, 999, 1) is first            # later parameters are ignored
        assert first.max_events == 5 and first.window == 60
        assert get_limiter(unique("registry"), 5, 60) is not first

    def test_reset_all_clears_every_registered_limiter(self):
        a, b = get_limiter(unique("a"), 1, 60), get_limiter(unique("b"), 1, 60)
        a.hit("k"), b.hit("k")
        ratelimit.reset_all()
        assert a.hit("k")[0] and b.hit("k")[0]


# ---------------------------------------------------------------------------
# FastAPI dependencies (tiny dedicated app so we control the limits)
# ---------------------------------------------------------------------------

def tiny_app(*dependencies) -> TestClient:
    app = FastAPI()

    @app.get("/ping", dependencies=list(dependencies))
    def ping():
        return {"ok": True}

    return TestClient(app)


class TestRateLimitIpDependency:
    def test_returns_429_with_retry_after_once_the_limit_is_exceeded(self):
        client = tiny_app(Depends(rate_limit_ip(unique("ip"), 2, 60)))
        assert client.get("/ping").status_code == 200
        assert client.get("/ping").status_code == 200
        resp = client.get("/ping")
        assert resp.status_code == 429
        assert resp.json()["detail"] == {"code": "rate_limited", "message": "Too many requests. Please slow down."}
        assert 1 <= int(resp.headers["retry-after"]) <= 61

    def test_limits_are_independent_per_named_limiter(self):
        one = tiny_app(Depends(rate_limit_ip(unique("one"), 1, 60)))
        two = tiny_app(Depends(rate_limit_ip(unique("two"), 1, 60)))
        assert one.get("/ping").status_code == 200
        assert one.get("/ping").status_code == 429
        assert two.get("/ping").status_code == 200

    def test_reset_all_restores_the_budget(self):
        client = tiny_app(Depends(rate_limit_ip(unique("ip"), 1, 60)))
        client.get("/ping")
        assert client.get("/ping").status_code == 429
        ratelimit.reset_all()
        assert client.get("/ping").status_code == 200


class TestRateLimitUserDependency:
    def test_requires_a_token(self):
        client = tiny_app(Depends(rate_limit_user(unique("user"), 5, 60)))
        assert client.get("/ping").status_code == 401

    def test_limits_each_user_separately(self):
        client = tiny_app(Depends(rate_limit_user(unique("user"), 1, 60)))
        alice, _ = security.create_access_token("alice-id")
        bob, _ = security.create_access_token("bob-id")
        assert client.get("/ping", headers=bearer(alice)).status_code == 200
        limited = client.get("/ping", headers=bearer(alice))
        assert limited.status_code == 429 and "retry-after" in limited.headers
        assert client.get("/ping", headers=bearer(bob)).status_code == 200

    def test_a_new_token_for_the_same_user_shares_the_budget(self):
        client = tiny_app(Depends(rate_limit_user(unique("user"), 1, 60)))
        first, _ = security.create_access_token("same-user")
        second, _ = security.create_access_token("same-user")
        assert client.get("/ping", headers=bearer(first)).status_code == 200
        assert client.get("/ping", headers=bearer(second)).status_code == 429


# ---------------------------------------------------------------------------
# client_ip — X-Forwarded-For is counted from the RIGHT
# ---------------------------------------------------------------------------

def make_request(xff: str | None = None, peer: str | None = "10.0.0.9") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    scope = {
        "type": "http", "method": "GET", "path": "/", "headers": headers,
        "client": (peer, 5555) if peer else None,
    }
    return Request(scope)


class TestClientIp:
    def test_without_trusted_proxies_the_socket_peer_is_used_and_xff_ignored(self, set_env):
        set_env(TRUSTED_PROXY_HOPS=0)
        assert client_ip(make_request("6.6.6.6, 7.7.7.7")) == "10.0.0.9"

    def test_one_hop_takes_the_rightmost_entry(self, set_env):
        set_env(TRUSTED_PROXY_HOPS=1)
        assert client_ip(make_request("1.1.1.1, 2.2.2.2, 3.3.3.3")) == "3.3.3.3"

    def test_leftmost_spoofed_entry_is_never_trusted(self, set_env):
        set_env(TRUSTED_PROXY_HOPS=1)
        assert client_ip(make_request("203.0.113.66, 198.51.100.7")) == "198.51.100.7"
        assert client_ip(make_request("203.0.113.66")) == "203.0.113.66"       # only one entry: it is ours

    def test_two_hops_take_the_second_from_the_right(self, set_env):
        set_env(TRUSTED_PROXY_HOPS=2)
        assert client_ip(make_request("spoofed, real-client, lb")) == "real-client"

    def test_not_enough_entries_falls_back_to_the_peer(self, set_env):
        set_env(TRUSTED_PROXY_HOPS=2)
        assert client_ip(make_request("only-one")) == "10.0.0.9"

    def test_missing_header_falls_back_to_the_peer(self, set_env):
        set_env(TRUSTED_PROXY_HOPS=1)
        assert client_ip(make_request(None)) == "10.0.0.9"

    def test_blank_entries_and_whitespace_are_ignored(self, set_env):
        set_env(TRUSTED_PROXY_HOPS=1)
        assert client_ip(make_request("1.1.1.1,  ,  9.9.9.9 ,")) == "9.9.9.9"

    def test_no_peer_at_all_is_unknown(self, set_env):
        set_env(TRUSTED_PROXY_HOPS=0)
        assert client_ip(make_request(None, peer=None)) == "unknown"

    def test_oversized_entries_are_truncated(self, set_env):
        set_env(TRUSTED_PROXY_HOPS=1)
        assert len(client_ip(make_request("a" * 500))) == 64

    def test_rotating_the_spoofed_leftmost_ip_does_not_evade_the_limiter(self, set_env, client):
        """End-to-end through the real /auth/register limiter behind one trusted proxy."""
        set_env(TRUSTED_PROXY_HOPS=1)
        statuses = []
        for n in range(12):
            resp = client.post(
                "/auth/register",
                headers={"X-Forwarded-For": f"198.51.100.{n}, 203.0.113.5"},     # leftmost changes every time
                json={"name": "N", "email": f"u{n}@example.com", "password": "long-enough-pw", "gender": "x"},
            )
            statuses.append(resp.status_code)
        assert statuses[:10] == [201] * 10
        assert statuses[10:] == [429, 429]

    def test_distinct_real_clients_behind_the_proxy_get_separate_budgets(self, set_env, client):
        set_env(TRUSTED_PROXY_HOPS=1)
        for n in range(10):
            client.post("/auth/register", headers={"X-Forwarded-For": "203.0.113.5"},
                        json={"name": "N", "email": f"a{n}@example.com", "password": "long-enough-pw", "gender": "x"})
        other = client.post("/auth/register", headers={"X-Forwarded-For": "203.0.113.99"},
                            json={"name": "N", "email": "b@example.com", "password": "long-enough-pw", "gender": "x"})
        assert other.status_code == 201
