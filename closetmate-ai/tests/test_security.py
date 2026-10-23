"""security.py — password hashing, JWT access tokens, refresh-token storage, auth dependencies."""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
import uuid
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

import security
from conftest import TEST_JWT_SECRET, bearer
from database import db_session
from settings import get_settings


def _claims(sub: str = "user-1", **overrides) -> dict:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "type": "access",
        "iss": "closetmate",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": uuid.uuid4().hex,
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not None}


def _encode(payload: dict, secret: str = TEST_JWT_SECRET, algorithm: str = "HS256") -> str:
    return jwt.encode(payload, secret, algorithm=algorithm)


def _b64(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _status_of(exc_info) -> int:
    return exc_info.value.status_code


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

class TestPasswords:
    def test_hash_then_verify_round_trip(self):
        hashed = security.hash_password("s3cret-pass")
        assert security.verify_password("s3cret-pass", hashed) is True

    def test_wrong_password_is_rejected(self):
        hashed = security.hash_password("s3cret-pass")
        assert security.verify_password("s3cret-pasS", hashed) is False

    def test_hash_is_salted_and_not_plaintext(self):
        first = security.hash_password("same-password")
        second = security.hash_password("same-password")
        assert first != second
        assert "same-password" not in first
        assert first.startswith("$2")

    @pytest.mark.slow
    def test_production_work_factor_is_at_least_12(self, real_bcrypt_cost):
        hashed = security.hash_password("work-factor-check")
        cost = int(hashed.split("$")[2])
        assert cost >= 12

    def test_password_over_72_bytes_is_refused_when_hashing(self):
        with pytest.raises(ValueError, match="72"):
            security.hash_password("a" * 73)

    def test_72_byte_password_is_accepted(self):
        pw = "a" * 72
        assert security.verify_password(pw, security.hash_password(pw)) is True

    def test_limit_is_in_bytes_not_characters(self):
        multibyte = "é" * 37                       # 37 characters, 74 bytes
        assert len(multibyte) < 72 < len(multibyte.encode())
        with pytest.raises(ValueError):
            security.hash_password(multibyte)

    def test_verify_returns_false_instead_of_raising_for_overlong_password(self):
        hashed = security.hash_password("short-one")
        assert security.verify_password("a" * 200, hashed) is False

    @pytest.mark.parametrize("garbage", ["", "not-a-bcrypt-hash", "$2b$04$tooshort"])
    def test_verify_returns_false_for_malformed_hash(self, garbage):
        assert security.verify_password("whatever", garbage) is False

    def test_unicode_password_round_trip(self):
        pw = "pässwörd-密码-🔐"
        assert security.verify_password(pw, security.hash_password(pw)) is True

    def test_verify_or_dummy_burns_a_comparison_for_unknown_users(self, monkeypatch):
        calls = []
        real = security.verify_password

        def spy(password, password_hash):
            calls.append(password_hash)
            return real(password, password_hash)

        monkeypatch.setattr(security, "verify_password", spy)
        assert security.verify_password_or_dummy("anything", None) is False
        assert len(calls) == 1 and calls[0].startswith("$2")      # compared against the dummy hash

    def test_verify_or_dummy_with_real_hash(self):
        hashed = security.hash_password("right-password")
        assert security.verify_password_or_dummy("right-password", hashed) is True
        assert security.verify_password_or_dummy("wrong-password", hashed) is False


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------

class TestAccessTokens:
    def test_round_trip_returns_the_subject(self):
        token, expires_in = security.create_access_token("user-42")
        assert security.decode_access_token(token) == "user-42"
        assert expires_in == get_settings().access_token_minutes * 60

    def test_claims_contain_issuer_type_and_unique_jti(self):
        t1, _ = security.create_access_token("u")
        t2, _ = security.create_access_token("u")
        c1 = jwt.decode(t1, TEST_JWT_SECRET, algorithms=["HS256"], issuer="closetmate")
        c2 = jwt.decode(t2, TEST_JWT_SECRET, algorithms=["HS256"], issuer="closetmate")
        assert c1["type"] == "access" and c1["iss"] == "closetmate"
        assert c1["jti"] != c2["jti"]
        assert c1["exp"] - c1["iat"] == 15 * 60

    def test_lifetime_is_configurable(self, set_env):
        set_env(ACCESS_TOKEN_MINUTES=1)
        _, expires_in = security.create_access_token("u")
        assert expires_in == 60

    def test_expired_token_is_401_token_expired(self):
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        token = _encode(_claims(iat=past - timedelta(minutes=5), exp=past))
        with pytest.raises(HTTPException) as exc:
            security.decode_access_token(token)
        assert _status_of(exc) == 401
        assert exc.value.detail == "Token expired"
        assert exc.value.headers == {"WWW-Authenticate": "Bearer"}

    def test_small_clock_skew_is_tolerated(self):
        just_expired = datetime.now(timezone.utc) - timedelta(seconds=3)
        token = _encode(_claims(exp=just_expired, iat=just_expired - timedelta(minutes=1)))
        assert security.decode_access_token(token) == "user-1"

    def test_token_signed_with_wrong_secret_is_401(self):
        token = _encode(_claims(), secret="a-completely-different-secret-value-123456")
        with pytest.raises(HTTPException) as exc:
            security.decode_access_token(token)
        assert _status_of(exc) == 401 and exc.value.detail == "Invalid token"

    def test_alg_none_token_is_rejected(self):
        header = _b64({"alg": "none", "typ": "JWT"})
        body = _b64({**_claims(), "iat": int(time.time()), "exp": int(time.time()) + 300})
        forged = f"{header}.{body}."
        with pytest.raises(HTTPException) as exc:
            security.decode_access_token(forged)
        assert _status_of(exc) == 401

    def test_token_with_different_hs_algorithm_is_rejected(self):
        token = _encode(_claims(), algorithm="HS384")       # right secret, wrong alg
        with pytest.raises(HTTPException) as exc:
            security.decode_access_token(token)
        assert _status_of(exc) == 401

    def test_non_access_token_type_is_401(self):
        with pytest.raises(HTTPException) as exc:
            security.decode_access_token(_encode(_claims(type="refresh")))
        assert _status_of(exc) == 401 and exc.value.detail == "Invalid token"

    def test_token_without_type_claim_is_401(self):
        payload = _claims()
        del payload["type"]
        with pytest.raises(HTTPException) as exc:
            security.decode_access_token(_encode(payload))
        assert _status_of(exc) == 401

    @pytest.mark.parametrize("missing", ["exp", "iat", "sub"])
    def test_required_claims_must_be_present(self, missing):
        payload = _claims()
        del payload[missing]
        with pytest.raises(HTTPException) as exc:
            security.decode_access_token(_encode(payload))
        assert _status_of(exc) == 401

    def test_wrong_issuer_is_401(self):
        with pytest.raises(HTTPException) as exc:
            security.decode_access_token(_encode(_claims(iss="someone-else")))
        assert _status_of(exc) == 401

    def test_empty_subject_is_401(self):
        with pytest.raises(HTTPException) as exc:
            security.decode_access_token(_encode(_claims(sub="")))
        assert _status_of(exc) == 401

    @pytest.mark.parametrize(
        "token",
        ["", "garbage", "a.b.c", f"dev-{uuid.uuid4()}", "dev-token", "Bearer abc"],
    )
    def test_garbage_and_legacy_dev_tokens_are_401(self, token):
        with pytest.raises(HTTPException) as exc:
            security.decode_access_token(token)
        assert _status_of(exc) == 401

    def test_tampered_payload_is_401(self):
        token, _ = security.create_access_token("victim")
        header, _payload, sig = token.split(".")
        evil = _b64({**_claims(sub="admin"), "iat": int(time.time()), "exp": int(time.time()) + 300})
        with pytest.raises(HTTPException) as exc:
            security.decode_access_token(f"{header}.{evil}.{sig}")
        assert _status_of(exc) == 401


# ---------------------------------------------------------------------------
# current_user_id dependency (direct calls)
# ---------------------------------------------------------------------------

class TestCurrentUserIdDependency:
    def test_valid_bearer_returns_user_id(self):
        token, _ = security.create_access_token("abc")
        assert security.current_user_id(f"Bearer {token}") == "abc"

    def test_scheme_is_case_insensitive(self):
        token, _ = security.create_access_token("abc")
        assert security.current_user_id(f"bEaReR {token}") == "abc"

    @pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer a b", "Basic dXNlcjpwYXNz", "token-only"])
    def test_missing_or_malformed_header_is_401_with_challenge(self, header):
        with pytest.raises(HTTPException) as exc:
            security.current_user_id(header)
        assert _status_of(exc) == 401
        assert exc.value.headers == {"WWW-Authenticate": "Bearer"}


class TestRequireSameUser:
    def test_same_user_passes(self):
        security.require_same_user("u1", "u1")

    def test_different_user_is_403(self):
        with pytest.raises(HTTPException) as exc:
            security.require_same_user("u1", "u2")
        assert _status_of(exc) == 403 and exc.value.detail == "Forbidden"

    def test_comparison_is_exact(self):
        with pytest.raises(HTTPException):
            security.require_same_user("U1", "u1")


# ---------------------------------------------------------------------------
# Auth dependency over HTTP (uses /auth/usage, which only needs a valid token)
# ---------------------------------------------------------------------------

class TestAuthOverHttp:
    PROTECTED = "/auth/usage"

    def test_missing_authorization_header_is_401_with_www_authenticate(self, client):
        resp = client.get(self.PROTECTED)
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == "Bearer"

    @pytest.mark.parametrize("header", ["Bearer", "Bearer a b", "Basic abc", "abc", "Bearer "])
    def test_malformed_authorization_header_is_401(self, client, header):
        resp = client.get(self.PROTECTED, headers={"Authorization": header})
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == "Bearer"

    def test_legacy_dev_token_is_401(self, client):
        resp = client.get(self.PROTECTED, headers=bearer(f"dev-{uuid.uuid4()}"))
        assert resp.status_code == 401

    def test_expired_token_is_401(self, client):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        token = _encode(_claims(iat=past - timedelta(minutes=5), exp=past))
        resp = client.get(self.PROTECTED, headers=bearer(token))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token expired"

    def test_wrong_secret_is_401(self, client):
        token = _encode(_claims(), secret="x" * 40)
        assert client.get(self.PROTECTED, headers=bearer(token)).status_code == 401

    def test_alg_none_is_401(self, client):
        now = int(time.time())
        forged = f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64({**_claims(), 'iat': now, 'exp': now + 300})}."
        assert client.get(self.PROTECTED, headers=bearer(forged)).status_code == 401

    def test_refresh_typed_token_is_401(self, client):
        assert client.get(self.PROTECTED, headers=bearer(_encode(_claims(type="refresh")))).status_code == 401

    def test_valid_token_is_accepted(self, client):
        token, _ = security.create_access_token("some-user")
        assert client.get(self.PROTECTED, headers=bearer(token)).status_code == 200

    def test_opaque_refresh_token_cannot_be_used_as_access_token(self, client, alice):
        assert client.get(self.PROTECTED, headers=bearer(alice.refresh_token)).status_code == 401

    def test_get_current_user_rejects_token_of_deleted_user(self, client, alice, sql):
        sql("DELETE FROM users WHERE user_id = :u", u=alice.user_id)
        resp = client.get("/auth/profile", headers=alice.headers)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User no longer exists"


# ---------------------------------------------------------------------------
# Refresh tokens (storage layer)
# ---------------------------------------------------------------------------

class TestRefreshTokenStorage:
    def test_only_the_sha256_is_stored(self, sql):
        with db_session() as db:
            raw = security.issue_refresh_token(db, "user-x")
        rows = sql("SELECT * FROM refresh_tokens WHERE user_id = 'user-x'")
        assert len(rows) == 1
        assert rows[0]["token_hash"] == hashlib.sha256(raw.encode()).hexdigest()
        assert raw not in json.dumps(rows, default=str)
        assert rows[0]["revoked_at"] is None
        assert len(raw) >= 40                                  # 48 random bytes, urlsafe

    def test_each_token_is_unique(self):
        with db_session() as db:
            tokens = {security.issue_refresh_token(db, "u") for _ in range(20)}
        assert len(tokens) == 20

    def test_expiry_follows_settings(self, sql, set_env):
        set_env(REFRESH_TOKEN_DAYS=2)
        with db_session() as db:
            security.issue_refresh_token(db, "u")
        row = sql("SELECT created_at, expires_at FROM refresh_tokens")[0]
        delta = datetime.fromisoformat(row["expires_at"]) - datetime.fromisoformat(row["created_at"])
        assert delta == timedelta(days=2)

    def test_issuing_purges_that_users_expired_rows_only(self, sql):
        old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        for uid in ("u1", "u2"):
            sql(
                "INSERT INTO refresh_tokens (token_hash, user_id, created_at, expires_at) "
                "VALUES (:h, :u, :c, :e)",
                h=f"expired-{uid}", u=uid, c=old, e=old,
            )
        with db_session() as db:
            security.issue_refresh_token(db, "u1")
        remaining = {r["token_hash"] for r in sql("SELECT token_hash FROM refresh_tokens")}
        assert "expired-u1" not in remaining
        assert "expired-u2" in remaining

    def test_rotate_returns_user_and_new_token_and_revokes_old(self, sql):
        with db_session() as db:
            raw = security.issue_refresh_token(db, "u1")
        with db_session() as db:
            user_id, new_raw = security.rotate_refresh_token(db, raw)
        assert user_id == "u1" and new_raw != raw
        old = sql("SELECT revoked_at FROM refresh_tokens WHERE token_hash = :h",
                  h=hashlib.sha256(raw.encode()).hexdigest())[0]
        assert old["revoked_at"] is not None

    def test_rotate_unknown_token_is_401(self):
        with db_session() as db, pytest.raises(HTTPException) as exc:
            security.rotate_refresh_token(db, "never-issued-" * 3)
        assert _status_of(exc) == 401 and exc.value.detail == "Invalid refresh token"

    def test_rotate_expired_token_is_401(self, sql):
        with db_session() as db:
            raw = security.issue_refresh_token(db, "u1")
        sql("UPDATE refresh_tokens SET expires_at = :e", e=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
        with db_session() as db, pytest.raises(HTTPException) as exc:
            security.rotate_refresh_token(db, raw)
        assert _status_of(exc) == 401 and exc.value.detail == "Refresh token expired"

    def test_replaying_a_rotated_token_revokes_every_session_of_that_user(self, sql):
        with db_session() as db:
            a = security.issue_refresh_token(db, "u1")
            b = security.issue_refresh_token(db, "u1")
            other = security.issue_refresh_token(db, "u2")
        with db_session() as db:
            _, a2 = security.rotate_refresh_token(db, a)
        with db_session() as db, pytest.raises(HTTPException) as exc:
            security.rotate_refresh_token(db, a)                    # replay of the old token
        assert exc.value.detail == "Refresh token reuse detected"

        live = sql("SELECT user_id, count(*) AS n FROM refresh_tokens WHERE revoked_at IS NULL GROUP BY user_id")
        assert {r["user_id"] for r in live} == {"u2"}               # u1 fully revoked, u2 untouched
        for token in (a2, b):
            with db_session() as db, pytest.raises(HTTPException):
                security.rotate_refresh_token(db, token)
        with db_session() as db:
            assert security.rotate_refresh_token(db, other)[0] == "u2"

    def test_revoke_refresh_token_is_idempotent(self, sql):
        with db_session() as db:
            raw = security.issue_refresh_token(db, "u1")
        for _ in range(2):
            with db_session() as db:
                security.revoke_refresh_token(db, raw)
        assert sql("SELECT revoked_at FROM refresh_tokens")[0]["revoked_at"] is not None

    def test_revoke_all_only_touches_the_given_user(self, sql):
        with db_session() as db:
            security.issue_refresh_token(db, "u1")
            security.issue_refresh_token(db, "u1")
            security.issue_refresh_token(db, "u2")
        with db_session() as db:
            security.revoke_all_refresh_tokens(db, "u1")
        live = sql("SELECT user_id FROM refresh_tokens WHERE revoked_at IS NULL")
        assert [r["user_id"] for r in live] == ["u2"]


class TestConcurrentRefreshRace:
    """Two parties presenting the same refresh token: one may be a thief, so nobody keeps a session."""

    def test_losing_the_update_race_revokes_all_sessions(self, sql):
        class LosesTheRace:
            """Proxy that makes the guarded UPDATE look like another request got there first."""

            def __init__(self, real):
                self._real = real

            def execute(self, statement, params=()):
                result = self._real.execute(statement, params)
                if "SET revoked_at = :now WHERE token_hash = :h AND revoked_at IS NULL" in str(statement):
                    return SimpleNamespace(rowcount=0)
                return result

            def commit(self):
                self._real.commit()

        with db_session() as db:
            victim = security.issue_refresh_token(db, "u1")
            other_device = security.issue_refresh_token(db, "u1")
            bystander = security.issue_refresh_token(db, "u2")

        with db_session() as db:
            with pytest.raises(HTTPException) as exc:
                security.rotate_refresh_token(LosesTheRace(db), victim)
        assert _status_of(exc) == 401 and exc.value.detail == "Invalid refresh token"

        live = sql("SELECT user_id FROM refresh_tokens WHERE revoked_at IS NULL")
        assert [r["user_id"] for r in live] == ["u2"]                    # every u1 session is gone
        with db_session() as db, pytest.raises(HTTPException):
            security.rotate_refresh_token(db, other_device)
        with db_session() as db:
            assert security.rotate_refresh_token(db, bystander)[0] == "u2"

    def test_two_real_threads_never_both_keep_a_session(self, sql):
        for round_no in range(5):
            user = f"racer-{round_no}"
            with db_session() as db:
                raw = security.issue_refresh_token(db, user)
            barrier = threading.Barrier(2)
            outcomes = []

            def attempt():
                barrier.wait()
                try:
                    with db_session() as db:
                        outcomes.append(("ok", security.rotate_refresh_token(db, raw)[1]))
                except HTTPException as exc:
                    outcomes.append(("denied", exc.status_code))

            threads = [threading.Thread(target=attempt) for _ in range(2)]
            [t.start() for t in threads]
            [t.join(timeout=30) for t in threads]

            assert len(outcomes) == 2
            assert sum(kind == "ok" for kind, _ in outcomes) <= 1
            assert ("denied", 401) in outcomes                             # at least one party is refused
            assert sql("SELECT 1 FROM refresh_tokens WHERE user_id = :u AND revoked_at IS NULL", u=user) == []
