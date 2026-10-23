"""quota.py — monthly per-user caps, refunds, the paid-call (no-refund) rule and the global daily cap."""
from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

import quota
from conftest import TEST_QUOTAS
from quota import (
    QuotaResult,
    consume_global,
    consume_quota,
    current_period,
    enforce_quota,
    metered,
    refund_quota,
    release_quota,
    usage_summary,
)


def run(coro):
    return asyncio.run(coro)


def utc(*args, **kwargs) -> datetime:
    return datetime(*args, tzinfo=timezone.utc, **kwargs)


# ---------------------------------------------------------------------------
# Period helpers
# ---------------------------------------------------------------------------

class TestPeriod:
    def test_current_period_format_is_year_dash_month(self):
        assert re.fullmatch(r"\d{4}-\d{2}", current_period())

    @pytest.mark.parametrize(
        "when,expected",
        [(utc(2026, 1, 5), "2026-01"), (utc(2026, 12, 31, 23, 59), "2026-12"), (utc(2027, 3, 1), "2027-03")],
    )
    def test_period_for_a_given_instant(self, when, expected):
        assert current_period(when) == expected

    @pytest.mark.parametrize(
        "when,expected",
        [
            (utc(2026, 1, 1, 0, 0, 0), 31 * 86400),           # whole of January remains
            (utc(2026, 2, 28, 23, 59, 58), 2),
            (utc(2026, 2, 28, 23, 59, 59), 1),
            (utc(2028, 2, 29, 23, 59, 0), 60),                # leap day
            (utc(2026, 1, 31, 23, 59, 59, 500_000), 1),       # never 0 / negative
        ],
    )
    def test_seconds_until_next_period(self, when, expected):
        assert quota._seconds_until_next_period(when) == expected


# ---------------------------------------------------------------------------
# consume_quota
# ---------------------------------------------------------------------------

class TestConsumeQuota:
    def test_counts_up_to_the_limit_then_denies(self, usage_count):
        assert consume_quota("u1", "chat") == QuotaResult(True, 1, 2)
        assert consume_quota("u1", "chat") == QuotaResult(True, 2, 2)
        assert consume_quota("u1", "chat") == QuotaResult(False, 2, 2)
        assert consume_quota("u1", "chat") == QuotaResult(False, 2, 2)
        assert usage_count("u1", "chat") == 2                     # denied calls never increment

    def test_row_is_stored_under_the_current_period(self, sql):
        consume_quota("u1", "vision")
        row = sql("SELECT * FROM usage_counters")[0]
        assert row == {"user_id": "u1", "feature": "vision", "period": current_period(), "count": 1}

    @pytest.mark.parametrize("limit", [0, -1, -100])
    def test_limit_zero_or_negative_denies_everything(self, set_env, sql, limit):
        set_env(QUOTA_FREE_CHAT_MONTHLY=limit)
        result = consume_quota("u1", "chat")
        assert result == QuotaResult(False, 0, limit)
        assert sql("SELECT 1 FROM usage_counters") == []

    def test_unknown_feature_is_denied(self, sql):
        assert consume_quota("u1", "teleportation").allowed is False
        assert sql("SELECT 1 FROM usage_counters") == []

    def test_users_have_independent_budgets(self):
        for _ in range(2):
            consume_quota("u1", "chat")
        assert consume_quota("u1", "chat").allowed is False
        assert consume_quota("u2", "chat").allowed is True

    def test_features_have_independent_budgets(self):
        for _ in range(2):
            consume_quota("u1", "chat")
        assert consume_quota("u1", "insights").allowed is True

    def test_each_feature_uses_its_own_limit(self):
        for feature, limit in TEST_QUOTAS.items():
            allowed = [consume_quota("u1", feature).allowed for _ in range(limit + 1)]
            assert allowed == [True] * limit + [False], feature

    def test_a_new_month_starts_a_fresh_budget(self, monkeypatch, usage_count):
        for _ in range(3):
            consume_quota("u1", "chat")
        monkeypatch.setattr(quota, "current_period", lambda now=None: "2099-01")
        assert consume_quota("u1", "chat") == QuotaResult(True, 1, 2)

    def test_previous_months_counters_are_ignored(self, sql):
        sql("INSERT INTO usage_counters (user_id, feature, period, count) VALUES ('u1', 'chat', '2000-01', 99)")
        assert consume_quota("u1", "chat") == QuotaResult(True, 1, 2)

    def test_changing_the_limit_takes_effect_immediately(self, set_env):
        consume_quota("u1", "chat")
        consume_quota("u1", "chat")
        assert consume_quota("u1", "chat").allowed is False
        set_env(QUOTA_FREE_CHAT_MONTHLY=3)
        assert consume_quota("u1", "chat") == QuotaResult(True, 3, 3)

    def test_concurrent_consumers_can_never_exceed_the_limit(self, set_env, usage_count):
        set_env(QUOTA_FREE_CHAT_MONTHLY=3)
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: consume_quota("racer", "chat"), range(24)))
        assert sum(r.allowed for r in results) == 3
        assert usage_count("racer", "chat") == 3


# ---------------------------------------------------------------------------
# refunds
# ---------------------------------------------------------------------------

class TestRefund:
    def test_refund_gives_one_unit_back(self, usage_count):
        consume_quota("u1", "chat")
        consume_quota("u1", "chat")
        refund_quota("u1", "chat")
        assert usage_count("u1", "chat") == 1
        assert consume_quota("u1", "chat").allowed is True

    def test_refund_never_goes_below_zero(self, usage_count):
        consume_quota("u1", "chat")
        refund_quota("u1", "chat")
        refund_quota("u1", "chat")
        assert usage_count("u1", "chat") == 0

    def test_refund_without_a_row_is_a_noop(self, sql):
        refund_quota("nobody", "chat")
        assert sql("SELECT 1 FROM usage_counters") == []

    def test_refund_touches_only_that_user_and_feature(self, usage_count):
        consume_quota("u1", "chat")
        consume_quota("u2", "chat")
        consume_quota("u1", "insights")
        refund_quota("u1", "chat")
        assert (usage_count("u1", "chat"), usage_count("u2", "chat"), usage_count("u1", "insights")) == (0, 1, 1)

    def test_release_quota_refunds(self, usage_count):
        consume_quota("u1", "chat")
        run(release_quota("u1", "chat"))
        assert usage_count("u1", "chat") == 0

    def test_release_quota_never_raises(self, monkeypatch):
        def boom(*_a):
            raise RuntimeError("database is down")

        monkeypatch.setattr(quota, "refund_quota", boom)
        assert run(release_quota("u1", "chat")) is None

    def test_release_quota_is_a_noop_after_a_paid_provider_call(self, usage_count):
        async def scenario():
            quota._begin_tracking()
            consume_quota("u1", "chat")
            quota.mark_billed()
            await release_quota("u1", "chat")

        run(scenario())
        assert usage_count("u1", "chat") == 1


# ---------------------------------------------------------------------------
# usage_summary
# ---------------------------------------------------------------------------

class TestUsageSummary:
    def test_all_features_present_with_limits_and_zero_usage(self):
        assert usage_summary("u1") == {f: {"used": 0, "limit": n} for f, n in TEST_QUOTAS.items()}

    def test_reflects_usage_for_this_user_only(self):
        consume_quota("u1", "chat")
        consume_quota("u1", "vision")
        consume_quota("u2", "chat")
        summary = usage_summary("u1")
        assert summary["chat"] == {"used": 1, "limit": 2}
        assert summary["vision"] == {"used": 1, "limit": 3}
        assert summary["bgremove"]["used"] == 0

    def test_old_periods_and_internal_counters_are_excluded(self, sql):
        sql("INSERT INTO usage_counters VALUES ('u1', 'chat', '2000-01', 50)")
        assert usage_summary("u1")["chat"]["used"] == 0
        assert set(usage_summary("u1")) == set(TEST_QUOTAS)       # no "ai_calls" leak

    def test_limits_follow_settings(self, set_env):
        set_env(QUOTA_FREE_CHAT_MONTHLY=9)
        assert usage_summary("u1")["chat"]["limit"] == 9


# ---------------------------------------------------------------------------
# enforce_quota / metered
# ---------------------------------------------------------------------------

class TestEnforceQuota:
    def test_allows_until_the_limit_then_raises_429(self):
        run(enforce_quota("u1", "chat"))
        run(enforce_quota("u1", "chat"))
        with pytest.raises(HTTPException) as exc:
            run(enforce_quota("u1", "chat"))
        assert exc.value.status_code == 429
        assert exc.value.detail["code"] == "quota_exceeded"
        assert exc.value.detail["feature"] == "chat"
        assert exc.value.detail["limit"] == 2
        assert "2" in exc.value.detail["message"] and "chat" in exc.value.detail["message"]
        assert 1 <= int(exc.value.headers["Retry-After"]) <= 31 * 86400

    def test_disabled_feature_is_429_with_limit_zero(self, set_env):
        set_env(QUOTA_FREE_BGREMOVE_MONTHLY=0)
        with pytest.raises(HTTPException) as exc:
            run(enforce_quota("u1", "bgremove"))
        assert exc.value.status_code == 429 and exc.value.detail["limit"] == 0


class TestMetered:
    def test_success_keeps_the_unit(self, usage_count):
        async def scenario():
            async with metered("u1", "chat"):
                return "ok"

        assert run(scenario()) == "ok"
        assert usage_count("u1", "chat") == 1

    def test_unexpected_exception_refunds_and_propagates(self, usage_count):
        async def scenario():
            async with metered("u1", "chat"):
                raise RuntimeError("our bug")

        with pytest.raises(RuntimeError, match="our bug"):
            run(scenario())
        assert usage_count("u1", "chat") == 0

    @pytest.mark.parametrize("code,refunded", [(400, False), (404, False), (422, False), (499, False),
                                               (500, True), (502, True), (503, True)])
    def test_http_exceptions_refund_only_for_server_errors(self, usage_count, code, refunded):
        async def scenario():
            async with metered("u1", "chat"):
                raise HTTPException(status_code=code, detail="x")

        with pytest.raises(HTTPException):
            run(scenario())
        assert usage_count("u1", "chat") == (0 if refunded else 1)

    def test_cancellation_refunds(self, usage_count):
        async def scenario():
            async with metered("u1", "chat"):
                raise asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            run(scenario())
        assert usage_count("u1", "chat") == 0

    def test_no_refund_once_a_provider_call_has_succeeded(self, usage_count):
        async def scenario():
            async with metered("u1", "insights"):
                quota.mark_billed()
                raise RuntimeError("could not parse the provider's answer")

        with pytest.raises(RuntimeError):
            run(scenario())
        assert usage_count("u1", "insights") == 1

    def test_no_refund_for_a_billed_5xx_either(self, usage_count):
        async def scenario():
            async with metered("u1", "insights"):
                quota.mark_billed()
                raise HTTPException(status_code=502, detail="bad provider payload")

        with pytest.raises(HTTPException):
            run(scenario())
        assert usage_count("u1", "insights") == 1

    def test_over_limit_raises_429_and_does_not_refund_other_units(self, usage_count):
        async def use():
            async with metered("u1", "chat"):
                pass

        run(use())
        run(use())
        with pytest.raises(HTTPException) as exc:
            run(use())
        assert exc.value.status_code == 429
        assert usage_count("u1", "chat") == 2

    def test_billed_flag_survives_a_worker_thread(self):
        async def scenario():
            quota._begin_tracking()
            assert quota.was_billed() is False
            await asyncio.to_thread(quota.mark_billed)
            return quota.was_billed()

        assert run(scenario()) is True

    def test_flag_helpers_are_safe_outside_a_tracked_request(self):
        async def scenario():
            quota.mark_billed()                    # no tracking started: must not raise
            return quota.was_billed()

        assert run(scenario()) is False

    def test_each_metered_request_starts_with_a_clean_flag(self, usage_count):
        async def billed():
            async with metered("u1", "chat"):
                quota.mark_billed()

        async def second():
            async with metered("u2", "chat"):
                assert quota.was_billed() is False
                raise RuntimeError("fails before any paid call")

        async def both():
            await billed()
            with pytest.raises(RuntimeError):
                await second()

        run(both())
        assert usage_count("u2", "chat") == 0               # refunded: the earlier request's flag did not leak


class TestRequireQuotaDependency:
    def make_client(self):
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()

        @app.get("/metered")
        def metered_route(uid: str = Depends(quota.require_quota("insights"))):
            return {"uid": uid}

        return TestClient(app)

    def test_authenticates_consumes_a_unit_and_returns_the_user_id(self, alice, usage_count):
        resp = self.make_client().get("/metered", headers=alice.headers)
        assert resp.status_code == 200 and resp.json() == {"uid": alice.user_id}
        assert usage_count(alice.user_id, "insights") == 1

    def test_rejects_unauthenticated_callers_without_consuming_anything(self, sql):
        assert self.make_client().get("/metered").status_code == 401
        assert sql("SELECT 1 FROM usage_counters") == []

    def test_returns_429_once_the_cap_is_reached(self, alice):
        client = self.make_client()
        assert [client.get("/metered", headers=alice.headers).status_code for _ in range(3)] == [200, 200, 429]


# ---------------------------------------------------------------------------
# App-wide daily AI budget
# ---------------------------------------------------------------------------

class TestGlobalDailyCap:
    @staticmethod
    def today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def test_consume_global_stops_at_the_limit(self, sql):
        assert [consume_global("2026-01-01", 2) for _ in range(4)] == [True, True, False, False]
        row = sql("SELECT * FROM usage_counters")[0]
        assert row["user_id"] == "__global__" and row["feature"] == "ai_calls" and row["count"] == 2

    def test_cap_is_shared_across_users_and_refunds_the_user_who_hit_it(self, set_env, usage_count, sql):
        set_env(GLOBAL_DAILY_AI_CALLS=2)
        run(enforce_quota("u1", "chat"))
        run(enforce_quota("u2", "chat"))
        with pytest.raises(HTTPException) as exc:
            run(enforce_quota("u3", "chat"))
        assert exc.value.status_code == 503
        assert exc.value.detail["code"] == "at_capacity"
        assert exc.value.headers["Retry-After"] == "3600"
        assert usage_count("u3", "chat") == 0                       # not the user's fault: unit returned
        glob = sql("SELECT count, period FROM usage_counters WHERE user_id = '__global__'")[0]
        assert glob == {"count": 2, "period": self.today()}

    @pytest.mark.parametrize("feature", ["chat", "vision", "insights"])
    def test_every_ai_feature_draws_from_the_global_budget(self, set_env, feature):
        set_env(GLOBAL_DAILY_AI_CALLS=1)
        run(enforce_quota("u1", feature))
        with pytest.raises(HTTPException) as exc:
            run(enforce_quota("u2", feature))
        assert exc.value.status_code == 503

    def test_image_features_are_not_part_of_the_ai_budget(self, set_env, sql):
        set_env(GLOBAL_DAILY_AI_CALLS=1, QUOTA_FREE_BGREMOVE_MONTHLY=10)
        for _ in range(5):
            run(enforce_quota("u1", "bgremove"))
        assert sql("SELECT 1 FROM usage_counters WHERE user_id = '__global__'") == []

    def test_zero_disables_the_cap(self, set_env, sql):
        set_env(GLOBAL_DAILY_AI_CALLS=0, QUOTA_FREE_CHAT_MONTHLY=50)
        for n in range(10):
            run(enforce_quota(f"user-{n}", "chat"))
        assert sql("SELECT 1 FROM usage_counters WHERE user_id = '__global__'") == []

    def test_a_user_over_their_own_limit_is_429_and_does_not_burn_global_budget(self, set_env, sql):
        set_env(GLOBAL_DAILY_AI_CALLS=100)
        run(enforce_quota("u1", "chat"))
        run(enforce_quota("u1", "chat"))
        with pytest.raises(HTTPException) as exc:
            run(enforce_quota("u1", "chat"))
        assert exc.value.status_code == 429
        assert sql("SELECT count FROM usage_counters WHERE user_id = '__global__'")[0]["count"] == 2

    def test_global_counter_never_appears_in_user_usage(self, set_env):
        set_env(GLOBAL_DAILY_AI_CALLS=5)
        run(enforce_quota("u1", "chat"))
        assert usage_summary("__global__")["chat"]["used"] == 0


# ---------------------------------------------------------------------------
# End-to-end through /chat/message and /chat/insights
# ---------------------------------------------------------------------------

def chat(client, account, message="hello", **extra):
    return client.post("/chat/message", headers=account.headers,
                       json={"user_id": account.user_id, "message": message, **extra})


def insights(client, account):
    return client.get(f"/chat/insights/{account.user_id}", headers=account.headers)


class TestChatQuotaEndToEnd:
    def test_third_message_is_429_with_structured_detail_and_retry_after(self, client, alice, fake_llm):
        assert chat(client, alice).status_code == 200
        assert chat(client, alice).status_code == 200
        resp = chat(client, alice)
        assert resp.status_code == 429
        assert resp.json()["detail"] == {
            "code": "quota_exceeded",
            "feature": "chat",
            "limit": 2,
            "message": "You've used all 2 free chat requests this month.",
        }
        assert int(resp.headers["retry-after"]) >= 1
        assert len(fake_llm.openai_calls) == 2                  # the 429 never reached the provider

    def test_quota_is_per_user(self, client, two_users, fake_llm):
        alice, bob = two_users
        chat(client, alice)
        chat(client, alice)
        assert chat(client, alice).status_code == 429
        assert chat(client, bob).status_code == 200

    def test_usage_endpoint_tracks_consumption(self, client, alice, fake_llm):
        chat(client, alice)
        assert client.get("/auth/usage", headers=alice.headers).json()["chat"] == {"used": 1, "limit": 2}

    def test_provider_outage_is_503_and_the_unit_is_refunded(self, client, alice, fake_llm, usage_count):
        fake_llm.openai_error = RuntimeError("openai down")
        fake_llm.gemini_reply = None
        for _ in range(4):                                       # more attempts than the cap of 2
            resp = chat(client, alice)
            assert resp.status_code == 503
        assert usage_count(alice.user_id, "chat") == 0
        fake_llm.openai_error = None
        assert chat(client, alice).status_code == 200            # full budget still available

    def test_gemini_fallback_success_keeps_the_unit(self, client, alice, fake_llm, usage_count):
        fake_llm.openai_error = RuntimeError("openai down")
        fake_llm.gemini_reply = "Fallback says wear the blue shirt."
        resp = chat(client, alice)
        assert resp.status_code == 200 and "blue shirt" in resp.json()["reply"]
        assert usage_count(alice.user_id, "chat") == 1

    def test_no_refund_when_a_provider_already_answered(self, client, alice, fake_llm, usage_count):
        """The provider charged us for an (empty) answer, so a later failure is not refundable."""
        fake_llm.mark_billed = True
        fake_llm.openai_reply = ""
        fake_llm.gemini_reply = None
        assert chat(client, alice).status_code == 503
        assert usage_count(alice.user_id, "chat") == 1

    def test_validation_errors_do_not_consume_quota(self, client, alice, fake_llm, usage_count):
        assert chat(client, alice, message="").status_code == 422
        assert chat(client, alice, message="x" * 1001).status_code == 422
        assert usage_count(alice.user_id, "chat") == 0

    def test_global_daily_cap_returns_503_at_capacity(self, client, two_users, fake_llm, set_env, usage_count):
        alice, bob = two_users
        set_env(GLOBAL_DAILY_AI_CALLS=1)
        assert chat(client, alice).status_code == 200
        resp = chat(client, bob)
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "at_capacity"
        assert usage_count(bob.user_id, "chat") == 0
        assert len(fake_llm.openai_calls) == 1


class TestInsightsQuotaEndToEnd:
    GOOD = '{"best_colors": ["navy"], "avoid_colors": ["lime"], "silhouettes": ["a-line"], "wardrobe_gaps": ["belt"], "general_tip": "Own it."}'

    def test_third_request_is_429_for_the_insights_feature(self, client, alice, fake_llm):
        fake_llm.openai_reply = self.GOOD
        assert insights(client, alice).status_code == 200
        assert insights(client, alice).status_code == 200
        resp = insights(client, alice)
        assert resp.status_code == 429
        assert resp.json()["detail"]["feature"] == "insights"

    def test_unparsable_answer_from_a_paid_call_is_502_and_not_refunded(self, client, alice, fake_llm, usage_count):
        fake_llm.mark_billed = True
        fake_llm.openai_reply = "definitely not json"
        assert insights(client, alice).status_code == 502
        assert usage_count(alice.user_id, "insights") == 1

    def test_unparsable_answer_without_a_paid_call_is_refunded(self, client, alice, fake_llm, usage_count):
        fake_llm.openai_reply = "definitely not json"
        assert insights(client, alice).status_code == 502
        assert usage_count(alice.user_id, "insights") == 0

    def test_total_provider_outage_is_503_and_refunded(self, client, alice, fake_llm, usage_count):
        fake_llm.openai_error = RuntimeError("down")
        assert insights(client, alice).status_code == 503
        assert usage_count(alice.user_id, "insights") == 0
