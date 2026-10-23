"""routers/auth.py — register / login / refresh / logout / profile / usage."""
from __future__ import annotations

import time

import pytest

from conftest import DEFAULT_PASSWORD, TEST_QUOTAS, Account, bearer

VALID = {
    "name": "Alice Example",
    "email": "alice@example.com",
    "password": DEFAULT_PASSWORD,
    "gender": "female",
}


def register(client, **overrides):
    return client.post("/auth/register", json={**VALID, **overrides})


def login(client, email=VALID["email"], password=DEFAULT_PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

class TestSkinToneRedos:
    """REGRESSION: a backtracking regex in skin-tone parsing could freeze a worker for minutes."""

    EVIL = [" " * 500 + ")", "(" * 500, "a (" * 200, " " * 5000 + "x ("]

    @pytest.mark.parametrize("evil", EVIL, ids=["spaces-paren", "open-parens", "repeated-groups", "spaces-then-open"])
    def test_register_rejects_pathological_skin_tone_quickly(self, client, sql, evil):
        started = time.perf_counter()
        resp = register(client, skin_tone=evil)
        assert resp.status_code == 422
        assert time.perf_counter() - started < 1.0
        assert sql("SELECT 1 FROM users") == []

    @pytest.mark.parametrize("evil", EVIL, ids=["spaces-paren", "open-parens", "repeated-groups", "spaces-then-open"])
    def test_profile_patch_rejects_pathological_skin_tone_quickly(self, client, alice, evil):
        started = time.perf_counter()
        resp = client.patch("/auth/profile", json={"skin_tone": evil}, headers=alice.headers)
        assert resp.status_code == 422
        assert time.perf_counter() - started < 1.0


class TestRegister:
    def test_creates_account_and_returns_only_the_user_id(self, client, sql):
        resp = register(client)
        assert resp.status_code == 201
        assert set(resp.json()) == {"user_id"}
        row = sql("SELECT * FROM users WHERE user_id = :u", u=resp.json()["user_id"])[0]
        assert row["email"] == "alice@example.com"
        assert row["password_hash"].startswith("$2") and DEFAULT_PASSWORD not in row["password_hash"]

    def test_email_is_stored_lowercase_and_duplicates_ignore_case(self, client, sql):
        assert register(client, email="Alice@Example.COM").status_code == 201
        assert sql("SELECT email FROM users")[0]["email"] == "alice@example.com"
        dup = register(client, email="ALICE@example.com")
        assert dup.status_code == 400
        assert dup.json()["detail"] == "Email already registered"

    def test_duplicate_email_is_400(self, client, sql):
        assert register(client).status_code == 201
        resp = register(client, name="Someone else")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Email already registered"
        assert len(sql("SELECT 1 FROM users")) == 1

    def test_name_is_trimmed(self, client, sql):
        register(client, name="  Alice  ")
        assert sql("SELECT name FROM users")[0]["name"] == "Alice"

    def test_whitespace_only_name_is_rejected(self, client):
        assert register(client, name="     ").status_code == 422

    def test_skin_tone_and_body_shape_are_stored_normalised(self, client, sql):
        resp = register(client, skin_tone="Light_Medium (Cool)", body_shape=" Inverted Triangle ")
        assert resp.status_code == 201
        row = sql("SELECT skin_tone, body_shape FROM users")[0]
        assert row["skin_tone"] == "light-medium (cool)"
        assert row["body_shape"] == "inverted_triangle"

    def test_legacy_skin_tone_values_are_mapped(self, client, sql):
        register(client, skin_tone="medium_dark")
        assert sql("SELECT skin_tone FROM users")[0]["skin_tone"] == "medium-deep"

    def test_optional_profile_fields_default_to_null(self, client, sql):
        register(client)
        row = sql("SELECT body_shape, skin_tone, style_preference FROM users")[0]
        assert row == {"body_shape": None, "skin_tone": None, "style_preference": None}

    def test_blank_optional_fields_are_stored_as_null(self, client, sql):
        register(client, skin_tone="", body_shape="  ")
        row = sql("SELECT body_shape, skin_tone FROM users")[0]
        assert row == {"body_shape": None, "skin_tone": None}

    @pytest.mark.parametrize(
        "overrides",
        [
            {"password": "short7!"},                    # 7 chars
            {"password": "x" * 73},                     # 73 bytes
            {"password": "€" * 25},                     # 25 chars but 75 bytes
            {"password": "x" * 200},                    # beyond the schema max_length as well
            {"email": "not-an-email"},
            {"email": "missing-at.example.com"},
            {"email": ""},
            {"body_shape": "banana"},
            {"skin_tone": "banana"},
            {"name": ""},
            {"gender": ""},
            {"name": "n" * 101},
            {"style_preference": "s" * 201},
            {"skin_tone": "light" + "x" * 40},
            {"body_shape": "pear" + "x" * 40},
        ],
    )
    def test_invalid_payload_is_422(self, client, sql, overrides):
        resp = register(client, **overrides)
        assert resp.status_code == 422
        assert sql("SELECT 1 FROM users") == []

    @pytest.mark.parametrize("field", ["name", "email", "password", "gender"])
    def test_missing_required_field_is_422(self, client, field):
        payload = {k: v for k, v in VALID.items() if k != field}
        assert client.post("/auth/register", json=payload).status_code == 422

    def test_validation_errors_do_not_echo_the_submitted_password(self, client):
        secret = "p@ss7!!"                                   # 7 chars: too short
        resp = register(client, password=secret)
        assert resp.status_code == 422
        assert secret not in resp.text
        assert all(set(err) == {"loc", "msg", "type"} for err in resp.json()["detail"])

    @pytest.mark.parametrize("password", ["x" * 8, "x" * 72, "é" * 36])
    def test_boundary_passwords_are_accepted(self, client, password):
        assert register(client, password=password).status_code == 201

    def test_unicode_and_emoji_in_free_text_fields(self, client, sql):
        resp = register(client, name="Zoë 🌸 田中", gender="non-binary")
        assert resp.status_code == 201
        assert sql("SELECT name FROM users")[0]["name"] == "Zoë 🌸 田中"

    def test_sql_metacharacters_in_name_are_stored_verbatim(self, client, sql):
        evil = "Robert'); DROP TABLE users;--"
        assert register(client, name=evil).status_code == 201
        assert sql("SELECT name FROM users")[0]["name"] == evil

    def test_client_cannot_choose_user_id_or_id_like_fields(self, client, sql):
        resp = client.post("/auth/register", json={**VALID, "user_id": "attacker-chosen", "password_hash": "x"})
        assert resp.status_code == 201
        assert resp.json()["user_id"] != "attacker-chosen"
        assert sql("SELECT user_id FROM users")[0]["user_id"] == resp.json()["user_id"]

    def test_registration_is_rate_limited_per_ip(self, client):
        for i in range(10):
            assert register(client, email=f"user{i}@example.com").status_code == 201
        resp = register(client, email="one-too-many@example.com")
        assert resp.status_code == 429
        assert int(resp.headers["retry-after"]) >= 1
        assert resp.json()["detail"]["code"] == "rate_limited"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_success_returns_token_pair(self, client):
        user_id = register(client).json()["user_id"]
        resp = login(client)
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"token", "refresh_token", "token_type", "expires_in", "user_id"}
        assert body["user_id"] == user_id
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 15 * 60
        assert body["token"].count(".") == 2
        assert body["refresh_token"] != body["token"]

    def test_email_is_case_insensitive(self, client):
        register(client)
        assert login(client, email="ALICE@EXAMPLE.COM").status_code == 200

    def test_issued_access_token_authenticates(self, client):
        register(client)
        token = login(client).json()["token"]
        assert client.get("/auth/profile", headers=bearer(token)).status_code == 200

    def test_wrong_password_and_unknown_email_are_indistinguishable(self, client):
        register(client)
        wrong_pw = login(client, password="not-the-password")
        unknown = login(client, email="nobody@example.com")
        assert wrong_pw.status_code == unknown.status_code == 401
        assert wrong_pw.json() == unknown.json() == {"detail": "Invalid credentials"}

    def test_overlong_password_is_a_clean_401(self, client):
        register(client)
        assert login(client, password="x" * 100).status_code == 401

    @pytest.mark.parametrize("payload", [{}, {"email": "a@example.com"}, {"password": "x"}, {"email": "bad", "password": "x"}, {"email": "a@example.com", "password": ""}])
    def test_malformed_login_is_422(self, client, payload):
        assert client.post("/auth/login", json=payload).status_code == 422

    def test_each_login_creates_an_independent_session(self, client, sql):
        register(client)
        first, second = login(client).json(), login(client).json()
        assert first["refresh_token"] != second["refresh_token"]
        assert len(sql("SELECT 1 FROM refresh_tokens")) == 2

    def test_login_never_returns_password_hash(self, client):
        register(client)
        assert "$2" not in login(client).text


class TestLoginBruteForceProtection:
    def test_lockout_after_eight_failures_even_with_the_right_password(self, client):
        register(client)
        for _ in range(8):
            assert login(client, password="wrong-password").status_code == 401
        locked = login(client, password="wrong-password")
        assert locked.status_code == 429
        assert 1 <= int(locked.headers["retry-after"]) <= 601
        assert locked.json()["detail"]["code"] == "rate_limited"
        assert login(client).status_code == 429          # correct password is also refused while locked

    def test_successful_login_clears_the_failure_counter(self, client):
        register(client)
        for _ in range(7):
            assert login(client, password="wrong-password").status_code == 401
        assert login(client).status_code == 200
        for _ in range(7):                                 # a fresh budget of failures
            assert login(client, password="wrong-password").status_code == 401
        assert login(client).status_code == 200

    def test_failures_are_counted_per_email_not_globally(self, client):
        register(client)
        register(client, email="bob@example.com")
        for _ in range(8):
            login(client, password="wrong-password")
        assert login(client).status_code == 429
        assert login(client, email="bob@example.com").status_code == 200

    def test_failures_for_different_letter_case_share_one_counter(self, client):
        register(client)
        for i in range(8):
            login(client, email="ALICE@example.com" if i % 2 else "alice@EXAMPLE.com", password="wrong-password")
        assert login(client).status_code == 429

    def test_unknown_emails_are_also_throttled(self, client):
        for _ in range(8):
            assert login(client, email="ghost@example.com").status_code == 401
        assert login(client, email="ghost@example.com").status_code == 429


# ---------------------------------------------------------------------------
# Refresh / logout
# ---------------------------------------------------------------------------

def refresh(client, token):
    return client.post("/auth/refresh", json={"refresh_token": token})


def logout(client, token):
    return client.post("/auth/logout", json={"refresh_token": token})


class TestRefresh:
    def test_rotation_returns_a_new_working_pair(self, client, alice):
        resp = refresh(client, alice.refresh_token)
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == alice.user_id
        assert body["refresh_token"] != alice.refresh_token
        assert client.get("/auth/profile", headers=bearer(body["token"])).status_code == 200
        assert refresh(client, body["refresh_token"]).status_code == 200      # chain keeps working

    def test_replaying_the_old_refresh_token_is_401_and_revokes_every_session(self, client, alice, login_user, bob):
        second_device = login_user(Account(alice.user_id, alice.email, alice.password))
        rotated = refresh(client, alice.refresh_token).json()

        replay = refresh(client, alice.refresh_token)
        assert replay.status_code == 401

        assert refresh(client, rotated["refresh_token"]).status_code == 401      # the new one is dead too
        assert refresh(client, second_device.refresh_token).status_code == 401   # so is the other device
        assert refresh(client, bob.refresh_token).status_code == 200             # other users unaffected

    def test_unknown_but_well_formed_token_is_401(self, client):
        resp = refresh(client, "x" * 43)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid refresh token"

    @pytest.mark.parametrize("token", ["garbage", "", "x" * 201])
    def test_tokens_outside_the_length_bounds_are_422(self, client, token):
        assert refresh(client, token).status_code == 422

    def test_access_token_is_not_accepted_as_a_refresh_token(self, client, alice):
        # A JWT is longer than the 200-char schema bound, so this is rejected up-front (422);
        # either way no new tokens are issued.
        resp = refresh(client, alice.token)
        assert resp.status_code in (401, 422)
        assert "refresh_token" not in resp.json()

    def test_refresh_for_a_deleted_user_is_401_and_revokes_sessions(self, client, alice, sql):
        sql("DELETE FROM users WHERE user_id = :u", u=alice.user_id)
        resp = refresh(client, alice.refresh_token)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User no longer exists"
        assert sql("SELECT 1 FROM refresh_tokens WHERE revoked_at IS NULL") == []

    def test_expired_refresh_token_is_401(self, client, alice, sql):
        sql("UPDATE refresh_tokens SET expires_at = '2000-01-01T00:00:00+00:00'")
        resp = refresh(client, alice.refresh_token)
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Refresh token expired"

    def test_refresh_does_not_require_an_access_token(self, client, alice):
        assert refresh(client, alice.refresh_token).status_code == 200


class TestLogout:
    def test_logout_revokes_the_refresh_token(self, client, alice):
        resp = logout(client, alice.refresh_token)
        assert resp.status_code == 204 and resp.content == b""
        assert refresh(client, alice.refresh_token).status_code == 401

    def test_logout_only_revokes_that_session(self, client, alice, login_user):
        other = login_user(Account(alice.user_id, alice.email, alice.password))
        logout(client, alice.refresh_token)
        assert refresh(client, other.refresh_token).status_code == 200

    def test_logout_is_idempotent(self, client, alice):
        assert logout(client, alice.refresh_token).status_code == 204
        assert logout(client, alice.refresh_token).status_code == 204

    def test_logout_with_unknown_token_does_not_reveal_anything(self, client):
        assert logout(client, "y" * 43).status_code == 204

    def test_logout_with_garbage_is_422(self, client):
        assert logout(client, "short").status_code == 422


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class TestGetProfile:
    def test_returns_the_callers_profile_without_secrets(self, client, make_account):
        acct = make_account(name="Pat", email="pat@example.com", body_shape="pear", skin_tone="deep (warm)")
        resp = client.get("/auth/profile", headers=acct.headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == acct.user_id
        assert body["name"] == "Pat" and body["email"] == "pat@example.com"
        assert body["body_shape"] == "pear" and body["skin_tone"] == "deep (warm)"
        assert "password_hash" not in body and "password" not in body
        assert body["created_at"]

    def test_requires_authentication(self, client):
        assert client.get("/auth/profile").status_code == 401


class TestPatchProfile:
    def test_returns_the_updated_user_and_persists_it(self, client, alice, sql):
        """REGRESSION: used to 500 with 'Can't operate on closed transaction'
        because it committed and then SELECTed inside an engine.begin() block."""
        resp = client.patch(
            "/auth/profile",
            json={"body_shape": "Hourglass", "skin_tone": "medium_dark"},
            headers=alice.headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["body_shape"] == "hourglass"
        assert resp.json()["skin_tone"] == "medium-deep"
        assert resp.json()["user_id"] == alice.user_id

        fetched = client.get("/auth/profile", headers=alice.headers).json()
        assert fetched["body_shape"] == "hourglass" and fetched["skin_tone"] == "medium-deep"
        row = sql("SELECT body_shape, skin_tone FROM users WHERE user_id = :u", u=alice.user_id)[0]
        assert row == {"body_shape": "hourglass", "skin_tone": "medium-deep"}

    def test_partial_update_leaves_other_fields_alone(self, client, make_account):
        acct = make_account(email="p@example.com", body_shape="pear", skin_tone="light")
        resp = client.patch("/auth/profile", json={"skin_tone": "deep (cool)"}, headers=acct.headers)
        assert resp.status_code == 200
        assert resp.json()["body_shape"] == "pear"
        assert resp.json()["skin_tone"] == "deep (cool)"

    def test_repeated_patches_keep_working(self, client, alice):
        for shape in ("pear", "apple", "oval"):
            resp = client.patch("/auth/profile", json={"body_shape": shape}, headers=alice.headers)
            assert resp.status_code == 200 and resp.json()["body_shape"] == shape

    @pytest.mark.parametrize("payload", [{"body_shape": "banana"}, {"skin_tone": "banana"}, {"body_shape": "pear", "skin_tone": "nope"}])
    def test_invalid_values_are_422_and_change_nothing(self, client, make_account, payload):
        acct = make_account(email="q@example.com", body_shape="pear", skin_tone="light")
        assert client.patch("/auth/profile", json=payload, headers=acct.headers).status_code == 422
        unchanged = client.get("/auth/profile", headers=acct.headers).json()
        assert unchanged["body_shape"] == "pear" and unchanged["skin_tone"] == "light"

    def test_empty_patch_returns_the_current_profile(self, client, alice):
        before = client.get("/auth/profile", headers=alice.headers).json()
        resp = client.patch("/auth/profile", json={}, headers=alice.headers)
        assert resp.status_code == 200
        assert resp.json() == before

    def test_null_values_are_ignored_rather_than_wiping_the_field(self, client, make_account):
        acct = make_account(email="n@example.com", body_shape="pear")
        resp = client.patch("/auth/profile", json={"body_shape": None}, headers=acct.headers)
        assert resp.status_code == 200 and resp.json()["body_shape"] == "pear"

    def test_cannot_mass_assign_other_columns(self, client, alice, sql):
        resp = client.patch(
            "/auth/profile",
            json={"email": "hijacked@example.com", "user_id": "someone-else",
                  "password_hash": "x", "name": "Mallory", "body_shape": "pear"},
            headers=alice.headers,
        )
        assert resp.status_code == 200
        row = sql("SELECT user_id, email, name, password_hash FROM users")[0]
        assert row["user_id"] == alice.user_id
        assert row["email"] == "alice@example.com" and row["name"] == "Alice"
        assert row["password_hash"].startswith("$2")

    def test_only_updates_the_callers_row(self, client, two_users, sql):
        alice, bob = two_users
        client.patch("/auth/profile", json={"body_shape": "pear"}, headers=alice.headers)
        assert sql("SELECT body_shape FROM users WHERE user_id = :u", u=bob.user_id)[0]["body_shape"] is None

    def test_requires_authentication(self, client):
        assert client.patch("/auth/profile", json={"body_shape": "pear"}).status_code == 401


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------

class TestUsage:
    def test_shape_and_limits(self, client, alice):
        resp = client.get("/auth/usage", headers=alice.headers)
        assert resp.status_code == 200
        assert resp.json() == {f: {"used": 0, "limit": limit} for f, limit in TEST_QUOTAS.items()}

    def test_reflects_consumed_units(self, client, alice, sql):
        from quota import consume_quota

        assert consume_quota(alice.user_id, "chat").allowed
        body = client.get("/auth/usage", headers=alice.headers).json()
        assert body["chat"] == {"used": 1, "limit": 2}
        assert body["vision"]["used"] == 0

    def test_is_per_user(self, client, two_users):
        from quota import consume_quota

        alice, bob = two_users
        consume_quota(alice.user_id, "chat")
        assert client.get("/auth/usage", headers=bob.headers).json()["chat"]["used"] == 0

    def test_requires_authentication(self, client):
        assert client.get("/auth/usage").status_code == 401
