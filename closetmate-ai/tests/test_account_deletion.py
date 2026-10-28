"""POST /auth/delete-account — erase an account and everything it owns, and nothing else."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from conftest import DEFAULT_PASSWORD
from services import photo_store as ps


def delete(client, account, password=DEFAULT_PASSWORD, **kwargs):
    return client.post("/auth/delete-account", headers=account.headers, json={"password": password}, **kwargs)


def photo(client, account):
    buf = io.BytesIO()
    Image.new("RGB", (20, 30), (10, 20, 30)).save(buf, format="PNG")
    resp = client.post("/photos", headers=account.headers, files={"file": ("p.png", buf.getvalue(), "image/png")})
    assert resp.status_code == 201, resp.text
    return resp.json()


def fill(client, account, add_item, sql):
    """Give an account one of everything it can own. Returns what was created."""
    stored = photo(client, account)
    item = add_item(account, image_path=stored["image_path"])
    legacy = add_item(account, category="bottom", subcategory="jeans", image_path="uploads/processed/old.jpg")
    client.post("/wardrobe/looks", headers=account.headers, json={"user_id": account.user_id, "item_ids": [item, legacy]})
    client.post("/wardrobe/log-worn", headers=account.headers, json={"user_id": account.user_id, "item_ids": [item]})
    sql("INSERT INTO usage_counters (user_id, feature, period, count) VALUES (:u, 'chat', '2026-10', 3)", u=account.user_id)
    sql("INSERT INTO ai_usage (user_id, feature, provider, model, ok, created_at) "
        "VALUES (:u, 'chat', 'openai', 'm', 1, '2026-10-01T00:00:00+00:00')", u=account.user_id)
    return stored, item


TABLES = ("users", "wardrobe_items", "saved_looks", "worn_logs", "refresh_tokens", "usage_counters", "photos")


def counts(sql, user_id):
    return {t: sql(f"SELECT count(*) AS n FROM {t} WHERE user_id = :u", u=user_id)[0]["n"] for t in TABLES}


class TestDeleting:
    def test_everything_the_account_owns_is_gone(self, client, alice, add_item, sql):
        fill(client, alice, add_item, sql)
        assert all(n > 0 for n in counts(sql, alice.user_id).values())               # the fixture really filled it
        resp = delete(client, alice)
        assert resp.status_code == 204 and resp.content == b""
        assert counts(sql, alice.user_id) == {t: 0 for t in TABLES}

    def test_the_stored_photos_are_removed_from_storage(self, client, alice, add_item, sql):
        stored, _ = fill(client, alice, add_item, sql)
        store = ps.get_store()
        assert store.get(stored["image_path"])
        delete(client, alice)
        assert store.get(stored["image_path"]) is None
        assert not list((store.root / "photos").glob(f"{alice.user_id}/*"))

    def test_ai_usage_is_kept_for_cost_accounting_without_the_user_id(self, client, alice, add_item, sql):
        fill(client, alice, add_item, sql)
        delete(client, alice)
        rows = sql("SELECT user_id FROM ai_usage")
        assert len(rows) == 1 and rows[0]["user_id"] is None

    def test_the_user_can_no_longer_sign_in(self, client, alice):
        delete(client, alice)
        assert client.post("/auth/login", json={"email": alice.email, "password": alice.password}).status_code == 401

    def test_the_refresh_token_stops_working(self, client, alice):
        delete(client, alice)
        assert client.post("/auth/refresh", json={"refresh_token": alice.refresh_token}).status_code == 401

    def test_the_email_can_be_registered_again_as_a_fresh_account(self, client, alice, add_item, sql):
        fill(client, alice, add_item, sql)
        delete(client, alice)
        again = client.post("/auth/register", json={"name": "New", "email": alice.email, "password": DEFAULT_PASSWORD,
                                                    "gender": "female"})
        assert again.status_code == 201 and again.json()["user_id"] != alice.user_id

    def test_deleting_twice_is_404(self, client, alice):
        assert delete(client, alice).status_code == 204
        assert delete(client, alice).status_code == 404


class TestOtherPeopleAreUntouched:
    def test_another_users_data_and_photos_survive(self, client, two_users, add_item, sql):
        alice, bob = two_users
        bobs_photo, _ = fill(client, bob, add_item, sql)
        before = counts(sql, bob.user_id)
        fill(client, alice, add_item, sql)
        assert delete(client, alice).status_code == 204
        assert counts(sql, bob.user_id) == before
        assert ps.get_store().get(bobs_photo["image_path"])
        assert client.get(f"/wardrobe/items/{bob.user_id}", headers=bob.headers).status_code == 200

    def test_a_user_whose_id_merely_starts_the_same_keeps_their_photos(self, client, alice, sql):
        mine = photo(client, alice)
        lookalike = f"{alice.user_id}x"
        key = f"photos/{lookalike}/{'d' * 32}.jpg"
        ps.get_store().put(key, b"theirs", "image/jpeg")
        sql("INSERT INTO photos (photo_id, user_id, key, thumb_key, size_bytes, created_at) "
            "VALUES (:p, :u, :k, :k, 6, '2026-10-01T00:00:00+00:00')", p="d" * 32, u=lookalike, k=key)
        delete(client, alice)
        assert ps.get_store().get(key) == b"theirs" and ps.get_store().get(mine["image_path"]) is None
        assert sql("SELECT count(*) AS n FROM photos WHERE user_id = :u", u=lookalike)[0]["n"] == 1


class TestPasswordIsRequired:
    def test_a_wrong_password_is_403_and_deletes_nothing(self, client, alice, add_item, sql):
        stored, _ = fill(client, alice, add_item, sql)
        before = counts(sql, alice.user_id)
        resp = delete(client, alice, "not-the-password")
        assert resp.status_code == 403 and resp.json()["detail"] == "Incorrect password"
        assert counts(sql, alice.user_id) == before and ps.get_store().get(stored["image_path"])

    def test_a_wrong_password_is_not_a_401_which_the_app_treats_as_session_expiry(self, client, alice):
        assert delete(client, alice, "nope").status_code != 401

    def test_the_account_still_works_after_a_failed_attempt(self, client, alice):
        delete(client, alice, "nope")
        assert client.post("/auth/login", json={"email": alice.email, "password": alice.password}).status_code == 200

    def test_each_account_is_checked_against_its_own_password(self, client, make_account):
        a = make_account(email="a@example.com", password="alice-own-password-1")
        b = make_account(email="b@example.com", password="bobs-own-password-22")
        assert delete(client, a, "bobs-own-password-22").status_code == 403
        assert delete(client, b, "alice-own-password-1").status_code == 403
        assert delete(client, a, "alice-own-password-1").status_code == 204

    @pytest.mark.parametrize("body", [{}, {"password": ""}, {"password": None}, {"password": 5}, {"pass": "x"}, {"password": "x" * 129}])
    def test_a_malformed_body_is_422(self, client, alice, body):
        assert client.post("/auth/delete-account", headers=alice.headers, json=body).status_code == 422

    def test_it_needs_a_token(self, client, alice):
        assert client.post("/auth/delete-account", json={"password": alice.password}).status_code == 401

    def test_a_garbage_token_is_refused(self, client, alice):
        resp = client.post("/auth/delete-account", json={"password": alice.password},
                           headers={"Authorization": "Bearer not-a-token"})
        assert resp.status_code == 401

    def test_five_attempts_an_hour_then_429(self, client, alice):
        codes = [delete(client, alice, "wrong").status_code for _ in range(6)]
        assert codes[:5] == [403] * 5 and codes[5] == 429
        assert delete(client, alice).status_code == 429                              # even the right password waits


class TestWhenSomethingFails:
    def test_if_storage_is_down_nothing_is_deleted_and_the_user_can_try_again(
        self, client, alice, add_item, sql, monkeypatch, caplog
    ):
        stored, _ = fill(client, alice, add_item, sql)
        before = counts(sql, alice.user_id)
        store = ps.get_store()
        monkeypatch.setattr(store, "delete_user", lambda uid: (_ for _ in ()).throw(OSError("bucket down")))
        resp = delete(client, alice)
        assert resp.status_code == 503 and "nothing was deleted" in resp.json()["detail"]
        assert counts(sql, alice.user_id) == before                                   # account, closet, photos: all intact
        assert store.get(stored["image_path"]) is not None
        assert "could not remove the stored photos" in caplog.text
        # The account still works, so retrying is possible once storage is back.
        assert client.post("/auth/login", json={"email": alice.email, "password": alice.password}).status_code == 200
        monkeypatch.undo()
        assert delete(client, alice).status_code == 204
        assert counts(sql, alice.user_id) == {t: 0 for t in TABLES}

    def test_a_database_failure_halfway_leaves_the_account_and_its_rows_in_place(self, client_no_raise, alice, add_item, sql):
        fill(client_no_raise, alice, add_item, sql)
        before = counts(sql, alice.user_id)
        sql("ALTER TABLE ai_usage RENAME TO ai_usage_x")             # the UPDATE inside the transaction will now fail
        try:
            resp = client_no_raise.post("/auth/delete-account", headers=alice.headers,
                                        json={"password": alice.password})
        finally:
            sql("ALTER TABLE ai_usage_x RENAME TO ai_usage")
        assert resp.status_code == 500
        after = counts(sql, alice.user_id)
        # The photos were removed first (so a retry has nothing left to fail on); everything else is untouched.
        assert after["photos"] == 0 and {k: v for k, v in after.items() if k != "photos"} ==             {k: v for k, v in before.items() if k != "photos"}
        assert delete(client_no_raise, alice).status_code == 204                      # and a retry completes it


class TestATokenOutlivesTheAccount:
    """Access tokens are not checked against the database, so they survive a deletion by up to 15 minutes."""

    def test_the_old_token_cannot_create_anything_afterwards(self, client, alice, add_item, sql):
        stored, item = fill(client, alice, add_item, sql)
        assert delete(client, alice).status_code == 204
        buf = io.BytesIO()
        Image.new("RGB", (20, 30), (1, 2, 3)).save(buf, format="PNG")
        upload = client.post("/photos", headers=alice.headers, files={"file": ("p.png", buf.getvalue(), "image/png")})
        item_resp = client.post("/wardrobe/add-item", headers=alice.headers, json={
            "user_id": alice.user_id, "image_path": "uploads/x.jpg", "category": "top"})
        worn = client.post("/wardrobe/log-worn", headers=alice.headers, json={"user_id": alice.user_id, "item_ids": ["x"]})
        look = client.post("/wardrobe/looks", headers=alice.headers, json={"user_id": alice.user_id, "item_ids": ["x"]})
        assert [r.status_code for r in (upload, item_resp, worn, look)] == [401, 401, 401, 401]
        assert all(r.headers["www-authenticate"] == "Bearer" for r in (upload, item_resp, worn, look))
        assert counts(sql, alice.user_id) == {t: 0 for t in TABLES}                   # nothing was created for a ghost
        assert not list((ps.get_store().root / "photos").glob(f"{alice.user_id}/*"))
