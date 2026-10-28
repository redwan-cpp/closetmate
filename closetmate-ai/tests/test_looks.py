"""routers/wardrobe.py — saved looks: POST /wardrobe/looks, GET /wardrobe/looks/{user_id}, DELETE /wardrobe/looks/{id}."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

import database
from conftest import bearer
from settings import get_settings

LOOK_KEYS = {"look_id", "name", "created_at", "items"}
LOOK_ITEM_KEYS = {"item_id", "image_path", "thumb_url", "category", "subcategory", "primary_color", "slot"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def save(client, account, item_ids, **extra):
    return client.post("/wardrobe/looks", headers=account.headers,
                       json={"user_id": account.user_id, "item_ids": item_ids, **extra})


def save_ok(client, account, item_ids, **extra) -> str:
    resp = save(client, account, item_ids, **extra)
    assert resp.status_code == 201, resp.text
    return resp.json()["look_id"]


def looks_of(client, account, **params):
    return client.get(f"/wardrobe/looks/{account.user_id}", params=params, headers=account.headers)


def delete_look(client, account, look_id):
    return client.delete(f"/wardrobe/looks/{look_id}", headers=account.headers)


def pieces(add_item, account, n, **overrides):
    return [add_item(account, subcategory=f"piece-{i}", **overrides) for i in range(n)]


def look_rows(sql, user_id=None):
    if user_id is None:
        return sql("SELECT * FROM saved_looks ORDER BY created_at")
    return sql("SELECT * FROM saved_looks WHERE user_id = :u ORDER BY created_at", u=user_id)


def seed_look(sql, user_id, item_ids, created_at, *, name=None, look_id=None, raw_ids=None):
    look_id = look_id or str(uuid.uuid4())
    sql("INSERT INTO saved_looks (look_id, user_id, name, item_ids, created_at) VALUES (:l, :u, :n, :ids, :c)",
        l=look_id, u=user_id, n=name, ids=raw_ids if raw_ids is not None else json.dumps(item_ids), c=created_at)
    return look_id


@pytest.fixture
def clock(monkeypatch):
    """routers.wardrobe's ``datetime.now`` ticks one minute per call, so created_at ordering is exact."""
    import routers.wardrobe as wardrobe

    state = {"now": datetime(2030, 1, 1, tzinfo=timezone.utc)}

    class TickingDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            state["now"] += timedelta(minutes=1)
            return state["now"]

    monkeypatch.setattr(wardrobe, "datetime", TickingDatetime)
    return state


# ---------------------------------------------------------------------------
# POST /wardrobe/looks
# ---------------------------------------------------------------------------

class TestSaveLook:
    def test_returns_201_saved_with_a_uuid_look_id(self, client, alice, add_item):
        a, b = pieces(add_item, alice, 2)
        resp = save(client, alice, [a, b])
        assert resp.status_code == 201
        body = resp.json()
        assert set(body) == {"status", "look_id"} and body["status"] == "saved"
        assert str(uuid.UUID(body["look_id"])) == body["look_id"]

    def test_the_row_is_stored_with_owner_items_name_and_a_utc_timestamp(self, client, alice, add_item, sql):
        a, b = pieces(add_item, alice, 2)
        before = datetime.now(timezone.utc)
        look_id = save_ok(client, alice, [a, b], name="Brunch")
        (row,) = look_rows(sql)
        assert row["look_id"] == look_id and row["user_id"] == alice.user_id and row["name"] == "Brunch"
        assert json.loads(row["item_ids"]) == [a, b]
        stamp = datetime.fromisoformat(row["created_at"])
        assert stamp.utcoffset() == timedelta(0)
        assert before - timedelta(seconds=1) <= stamp <= datetime.now(timezone.utc) + timedelta(seconds=1)

    def test_a_look_may_be_a_single_item(self, client, alice, add_item):
        (a,) = pieces(add_item, alice, 1)
        assert save(client, alice, [a]).status_code == 201

    def test_the_order_of_the_ids_is_the_order_that_is_stored(self, client, alice, add_item, sql):
        a, b, c = pieces(add_item, alice, 3)
        save_ok(client, alice, [c, a, b])
        assert json.loads(look_rows(sql)[0]["item_ids"]) == [c, a, b]

    def test_repeated_ids_in_one_request_are_stored_once(self, client, alice, add_item, sql):
        a, b = pieces(add_item, alice, 2)
        save_ok(client, alice, [a, b, a, b, a])
        assert json.loads(look_rows(sql)[0]["item_ids"]) == [a, b]

    # -- names ---------------------------------------------------------------

    @pytest.mark.parametrize("given,stored", [
        ("  Date night  ", "Date night"),
        ("", None),
        ("   ", None),
        ("\t\n", None),
        (None, None),
        ("a" * 60, "a" * 60),
        ("Eid ✨ 🎉 नमस्ते", "Eid ✨ 🎉 नमस्ते"),
        ("x'; DROP TABLE saved_looks; --", "x'; DROP TABLE saved_looks; --"),
    ])
    def test_name_is_stripped_and_blank_becomes_null(self, client, alice, add_item, sql, given, stored):
        (a,) = pieces(add_item, alice, 1)
        save_ok(client, alice, [a], name=given)
        assert look_rows(sql)[0]["name"] == stored

    def test_omitting_the_name_stores_null(self, client, alice, add_item, sql):
        (a,) = pieces(add_item, alice, 1)
        save_ok(client, alice, [a])
        assert look_rows(sql)[0]["name"] is None

    def test_a_61_character_name_is_422_and_nothing_is_stored(self, client, alice, add_item, sql):
        (a,) = pieces(add_item, alice, 1)
        assert save(client, alice, [a], name="a" * 61).status_code == 422
        assert look_rows(sql) == []

    def test_the_length_limit_is_checked_before_stripping(self, client, alice, add_item):
        (a,) = pieces(add_item, alice, 1)
        assert save(client, alice, [a], name="  " + "a" * 60).status_code == 422

    @pytest.mark.parametrize("bad", [123, ["x"], {"n": 1}, True])
    def test_a_non_string_name_is_422(self, client, alice, add_item, bad):
        (a,) = pieces(add_item, alice, 1)
        assert save(client, alice, [a], name=bad).status_code == 422

    # -- item_ids bounds -----------------------------------------------------

    def test_eight_items_is_the_maximum(self, client, alice, add_item, sql):
        ids = pieces(add_item, alice, 8)
        assert save(client, alice, ids).status_code == 201
        assert json.loads(look_rows(sql)[0]["item_ids"]) == ids

    def test_nine_ids_is_422(self, client, alice, add_item, sql):
        ids = pieces(add_item, alice, 9)
        assert save(client, alice, ids).status_code == 422
        assert look_rows(sql) == []

    def test_the_cap_counts_ids_before_duplicates_are_removed(self, client, alice, add_item):
        (a,) = pieces(add_item, alice, 1)
        assert save(client, alice, [a] * 9).status_code == 422
        assert save(client, alice, [a] * 8).status_code == 201

    def test_an_empty_list_is_422(self, client, alice):
        assert save(client, alice, []).status_code == 422

    @pytest.mark.parametrize("body", [
        {"item_ids": ["x"]},                                   # no user_id
        {"user_id": "<me>"},                                   # no item_ids
        {"user_id": "<me>", "item_ids": "abc"},
        {"user_id": "<me>", "item_ids": [1, 2]},
        {"user_id": "<me>", "item_ids": [None]},
        {"user_id": "<me>", "item_ids": {"a": 1}},
        {},
    ])
    def test_malformed_payloads_are_422(self, client, alice, sql, body):
        body = {k: (alice.user_id if v == "<me>" else v) for k, v in body.items()}
        assert client.post("/wardrobe/looks", headers=alice.headers, json=body).status_code == 422
        assert look_rows(sql) == []

    def test_a_non_json_body_is_422(self, client, alice):
        assert client.post("/wardrobe/looks", headers=alice.headers, content=b"not json").status_code == 422

    # -- ownership -------------------------------------------------------------

    def test_ids_that_are_not_the_callers_are_silently_dropped(self, client, two_users, add_item, sql):
        alice, bob = two_users
        mine = add_item(alice)
        theirs = add_item(bob)
        resp = save(client, alice, [theirs, mine, "no-such-item"])
        assert resp.status_code == 201
        (row,) = look_rows(sql)
        assert json.loads(row["item_ids"]) == [mine]

    def test_when_none_of_the_ids_is_owned_the_answer_is_400_and_nothing_is_stored(self, client, two_users, add_item, sql):
        alice, bob = two_users
        theirs = add_item(bob)
        resp = save(client, alice, [theirs, "ghost"])
        assert resp.status_code == 400
        assert resp.json()["detail"] == "None of these items are in your wardrobe"
        assert look_rows(sql) == []

    def test_a_very_long_or_hostile_id_is_just_not_owned(self, client, alice, sql):
        assert save(client, alice, ["x" * 5000, "' OR 1=1 --", "💥"]).status_code == 400
        assert look_rows(sql) == []

    def test_saving_under_another_users_id_is_403_even_with_the_callers_own_items(self, client, two_users, add_item, sql):
        alice, bob = two_users
        mine = add_item(alice)
        resp = client.post("/wardrobe/looks", headers=alice.headers, json={"user_id": bob.user_id, "item_ids": [mine]})
        assert resp.status_code == 403
        assert look_rows(sql) == []

    def test_the_look_belongs_to_the_token_not_to_a_body_field(self, client, two_users, add_item, sql):
        alice, bob = two_users
        save_ok(client, alice, [add_item(alice)])
        assert [r["user_id"] for r in look_rows(sql)] == [alice.user_id]
        assert looks_of(client, bob).json() == []

    @pytest.mark.parametrize("headers", [{}, bearer("not.a.jwt"), bearer("")])
    def test_without_a_valid_token_it_is_401(self, client, alice, add_item, sql, headers):
        (a,) = pieces(add_item, alice, 1)
        resp = client.post("/wardrobe/looks", headers=headers, json={"user_id": alice.user_id, "item_ids": [a]})
        assert resp.status_code == 401
        assert look_rows(sql) == []

    # -- saving the same outfit twice -----------------------------------------

    def test_the_same_set_again_returns_200_exists_with_the_same_id(self, client, alice, add_item, sql):
        a, b, c = pieces(add_item, alice, 3)
        first = save_ok(client, alice, [a, b, c], name="Original")
        again = save(client, alice, [a, b, c], name="Different")
        assert again.status_code == 200
        assert again.json() == {"status": "exists", "look_id": first}
        (row,) = look_rows(sql)
        assert row["name"] == "Original"                           # the existing look is left alone

    @pytest.mark.parametrize("order", [[2, 1, 0], [1, 0, 2], [0, 0, 1, 2, 2]])
    def test_any_order_and_duplicates_count_as_the_same_set(self, client, alice, add_item, sql, order):
        ids = pieces(add_item, alice, 3)
        first = save_ok(client, alice, ids)
        resp = save(client, alice, [ids[i] for i in order])
        assert resp.status_code == 200 and resp.json() == {"status": "exists", "look_id": first}
        assert len(look_rows(sql)) == 1

    def test_a_subset_or_superset_is_a_different_look(self, client, alice, add_item, sql):
        a, b, c = pieces(add_item, alice, 3)
        first = save_ok(client, alice, [a, b])
        assert save_ok(client, alice, [a]) != first
        assert save_ok(client, alice, [a, b, c]) != first
        assert len(look_rows(sql)) == 3

    def test_foreign_ids_are_ignored_when_comparing_sets(self, client, two_users, add_item, sql):
        alice, bob = two_users
        a, b = pieces(add_item, alice, 2)
        first = save_ok(client, alice, [a, b])
        resp = save(client, alice, [b, add_item(bob), a])
        assert resp.status_code == 200 and resp.json()["look_id"] == first
        assert len(look_rows(sql)) == 1

    def test_after_deleting_a_look_the_same_set_can_be_saved_again(self, client, alice, add_item):
        a, b = pieces(add_item, alice, 2)
        first = save_ok(client, alice, [a, b])
        assert delete_look(client, alice, first).status_code == 200
        second = save(client, alice, [a, b])
        assert second.status_code == 201 and second.json()["look_id"] != first

    def test_unreadable_rows_do_not_break_the_comparison(self, client, alice, add_item, sql):
        a, b = pieces(add_item, alice, 2)
        for n, raw in enumerate(["not json", "null", "5", '{"k": 1}', "[1, 2]", '["a", 2]']):
            seed_look(sql, alice.user_id, None, f"2020-01-0{n + 1}T00:00:00+00:00", raw_ids=raw)
        resp = save(client, alice, [a, b])
        assert resp.status_code == 201
        assert save(client, alice, [b, a]).status_code == 200

    # -- cap ---------------------------------------------------------------------

    def test_default_cap_is_200(self):
        assert get_settings().max_saved_looks == 200

    def test_at_the_cap_a_new_look_is_403_looks_full(self, client, alice, add_item, set_env, sql):
        set_env(MAX_SAVED_LOOKS=2)
        a, b, c = pieces(add_item, alice, 3)
        save_ok(client, alice, [a])
        save_ok(client, alice, [b])
        resp = save(client, alice, [c])
        assert resp.status_code == 403
        detail = resp.json()["detail"]
        assert detail["code"] == "looks_full" and "2" in detail["message"]
        assert len(look_rows(sql)) == 2

    def test_saving_an_existing_set_at_the_cap_is_still_200_exists(self, client, alice, add_item, set_env):
        set_env(MAX_SAVED_LOOKS=1)
        (a,) = pieces(add_item, alice, 1)
        first = save_ok(client, alice, [a])
        resp = save(client, alice, [a])
        assert resp.status_code == 200 and resp.json()["look_id"] == first

    def test_the_cap_is_per_user(self, client, two_users, add_item, set_env):
        alice, bob = two_users
        set_env(MAX_SAVED_LOOKS=1)
        save_ok(client, alice, [add_item(alice)])
        assert save(client, alice, [add_item(alice)]).status_code == 403
        assert save(client, bob, [add_item(bob)]).status_code == 201

    def test_deleting_a_look_frees_a_place(self, client, alice, add_item, set_env):
        set_env(MAX_SAVED_LOOKS=1)
        a, b = pieces(add_item, alice, 2)
        first = save_ok(client, alice, [a])
        assert save(client, alice, [b]).status_code == 403
        delete_look(client, alice, first)
        assert save(client, alice, [b]).status_code == 201

    def test_the_cap_is_read_from_the_environment_on_every_request(self, client, alice, add_item, set_env):
        a, b = pieces(add_item, alice, 2)
        set_env(MAX_SAVED_LOOKS=1)
        save_ok(client, alice, [a])
        assert save(client, alice, [b]).status_code == 403
        set_env(MAX_SAVED_LOOKS=5)
        assert save(client, alice, [b]).status_code == 201

    def test_invalid_cap_setting_falls_back_to_the_default(self, set_env):
        set_env(MAX_SAVED_LOOKS="lots")
        assert get_settings().max_saved_looks == 200
        set_env(MAX_SAVED_LOOKS="")
        assert get_settings().max_saved_looks == 200

    def test_rejected_saves_leave_no_trace(self, client, alice, add_item, set_env, sql):
        set_env(MAX_SAVED_LOOKS=1)
        a, b = pieces(add_item, alice, 2)
        save_ok(client, alice, [a])
        save(client, alice, [b])                       # looks_full
        save(client, alice, ["ghost"])                 # 400
        save(client, alice, [b], name="n" * 61)        # 422
        assert len(look_rows(sql)) == 1


# ---------------------------------------------------------------------------
# GET /wardrobe/looks/{user_id}
# ---------------------------------------------------------------------------

class TestListLooks:
    def test_no_looks_is_an_empty_list(self, client, alice):
        resp = looks_of(client, alice)
        assert resp.status_code == 200 and resp.json() == []

    def test_listing_requires_a_token(self, client, alice):
        assert client.get(f"/wardrobe/looks/{alice.user_id}").status_code == 401

    def test_another_users_id_is_403(self, client, two_users, add_item):
        alice, bob = two_users
        save_ok(client, bob, [add_item(bob)])
        resp = client.get(f"/wardrobe/looks/{bob.user_id}", headers=alice.headers)
        assert resp.status_code == 403
        assert "look_id" not in resp.text

    def test_shape_of_a_look_and_its_items(self, client, alice, add_item):
        shirt = add_item(alice, category="top", subcategory="shirt", primary_color="white", image_path="uploads/s.webp")
        saree = add_item(alice, category="traditional", subcategory="saree", primary_color="red", image_path="uploads/r.webp")
        look_id = save_ok(client, alice, [saree, shirt], name="Wedding")
        (look,) = looks_of(client, alice).json()
        assert set(look) == LOOK_KEYS
        assert look["look_id"] == look_id and look["name"] == "Wedding"
        assert datetime.fromisoformat(look["created_at"]).utcoffset() == timedelta(0)
        assert look["items"] == [
            {"item_id": saree, "image_path": "uploads/r.webp", "thumb_url": None, "category": "traditional",
             "subcategory": "saree", "primary_color": "red", "slot": "dress"},
            {"item_id": shirt, "image_path": "uploads/s.webp", "thumb_url": None, "category": "top",
             "subcategory": "shirt", "primary_color": "white", "slot": "top"},
        ]
        assert all(set(i) == LOOK_ITEM_KEYS for i in look["items"])

    def test_unnamed_look_has_a_null_name(self, client, alice, add_item):
        save_ok(client, alice, [add_item(alice)])
        assert looks_of(client, alice).json()[0]["name"] is None

    def test_items_come_back_in_the_saved_order_not_the_database_order(self, client, alice, add_item):
        a, b, c = pieces(add_item, alice, 3)
        save_ok(client, alice, [c, a, b])
        assert [i["item_id"] for i in looks_of(client, alice).json()[0]["items"]] == [c, a, b]

    def test_slots_follow_the_current_wardrobe_row(self, client, alice, add_item):
        cases = [("footwear", "sneakers", "shoes"), ("top", "jacket", "outer"), ("bottom", "jeans", "bottom"),
                 ("accessory", "watch", "accessory")]
        ids = [add_item(alice, category=c, subcategory=s) for c, s, _ in cases]
        save_ok(client, alice, ids)
        assert [i["slot"] for i in looks_of(client, alice).json()[0]["items"]] == [slot for *_, slot in cases]

    def test_newest_first(self, client, alice, add_item, clock):
        a, b, c = pieces(add_item, alice, 3)
        first, second, third = (save_ok(client, alice, [i]) for i in (a, b, c))
        assert [l["look_id"] for l in looks_of(client, alice).json()] == [third, second, first]

    def test_ordering_comes_from_created_at_not_insertion_order(self, client, alice, add_item, sql):
        (a,) = pieces(add_item, alice, 1)
        newest = seed_look(sql, alice.user_id, [a], "2031-01-01T00:00:00+00:00")
        oldest = seed_look(sql, alice.user_id, [a], "2001-01-01T00:00:00+00:00")
        middle = seed_look(sql, alice.user_id, [a], "2016-01-01T00:00:00+00:00")
        assert [l["look_id"] for l in looks_of(client, alice).json()] == [newest, middle, oldest]

    def test_a_deleted_item_disappears_from_its_looks(self, client, alice, add_item):
        a, b, c = pieces(add_item, alice, 3)
        save_ok(client, alice, [a, b, c])
        client.delete(f"/wardrobe/item/{b}", headers=alice.headers)
        (look,) = looks_of(client, alice).json()
        assert [i["item_id"] for i in look["items"]] == [a, c]

    def test_a_look_whose_items_are_all_gone_is_omitted(self, client, alice, add_item):
        a, b = pieces(add_item, alice, 2)
        gone = save_ok(client, alice, [a])
        kept = save_ok(client, alice, [b])
        client.delete(f"/wardrobe/item/{a}", headers=alice.headers)
        assert [l["look_id"] for l in looks_of(client, alice).json()] == [kept]
        assert gone not in looks_of(client, alice).text

    def test_the_stored_row_of_a_look_is_not_rewritten_when_items_vanish(self, client, alice, add_item, sql):
        a, b = pieces(add_item, alice, 2)
        save_ok(client, alice, [a, b])
        client.delete(f"/wardrobe/item/{a}", headers=alice.headers)
        looks_of(client, alice)
        assert json.loads(look_rows(sql)[0]["item_ids"]) == [a, b]

    def test_one_item_can_appear_in_several_looks(self, client, alice, add_item):
        a, b, c = pieces(add_item, alice, 3)
        save_ok(client, alice, [a, b])
        save_ok(client, alice, [a, c])
        looks = looks_of(client, alice).json()
        assert len(looks) == 2 and all(a in [i["item_id"] for i in l["items"]] for l in looks)

    def test_a_full_eight_item_look(self, client, alice, add_item):
        ids = pieces(add_item, alice, 8)
        save_ok(client, alice, ids)
        assert [i["item_id"] for i in looks_of(client, alice).json()[0]["items"]] == ids

    # -- limit -------------------------------------------------------------------

    @pytest.fixture
    def five_looks(self, client, alice, add_item, clock):
        ids = pieces(add_item, alice, 5)
        return [save_ok(client, alice, [i]) for i in ids]          # oldest -> newest

    def test_default_limit_is_50(self, client, alice, add_item, sql):
        (a,) = pieces(add_item, alice, 1)
        for n in range(55):
            seed_look(sql, alice.user_id, [a], f"2020-01-01T00:{n // 60:02d}:{n % 60:02d}+00:00")
        assert len(looks_of(client, alice).json()) == 50

    def test_limit_keeps_the_newest(self, client, alice, five_looks):
        assert [l["look_id"] for l in looks_of(client, alice, limit=2).json()] == [five_looks[4], five_looks[3]]

    @pytest.mark.parametrize("limit,count", [(1, 1), (5, 5), (100, 5)])
    def test_limit_bounds_are_inclusive(self, client, alice, five_looks, limit, count):
        resp = looks_of(client, alice, limit=limit)
        assert resp.status_code == 200 and len(resp.json()) == count

    @pytest.mark.parametrize("limit", [0, 101, -1, "abc", 1.5, 10 ** 12])
    def test_limit_outside_1_to_100_is_422(self, client, alice, limit):
        assert looks_of(client, alice, limit=limit).status_code == 422

    # -- isolation -----------------------------------------------------------------

    def test_a_user_only_ever_sees_their_own_looks(self, client, two_users, add_item):
        alice, bob = two_users
        a_look = save_ok(client, alice, [add_item(alice)], name="alice-look")
        b_look = save_ok(client, bob, [add_item(bob)], name="bob-look")
        assert [l["look_id"] for l in looks_of(client, alice).json()] == [a_look]
        assert [l["look_id"] for l in looks_of(client, bob).json()] == [b_look]
        assert "bob-look" not in looks_of(client, alice).text

    def test_other_users_newer_looks_do_not_use_up_the_limit(self, client, two_users, add_item, sql):
        alice, bob = two_users
        mine = seed_look(sql, alice.user_id, [add_item(alice)], "2001-01-01T00:00:00+00:00")
        bobs_item = add_item(bob)
        for n in range(3):
            seed_look(sql, bob.user_id, [bobs_item], f"2030-01-0{n + 1}T00:00:00+00:00")
        assert [l["look_id"] for l in looks_of(client, alice, limit=1).json()] == [mine]

    def test_a_look_row_owned_by_someone_else_is_not_listed_even_if_it_points_at_my_items(
        self, client, two_users, add_item, sql
    ):
        alice, bob = two_users
        mine = add_item(alice)
        seed_look(sql, bob.user_id, [mine], "2020-01-01T00:00:00+00:00", name="bobs-look")
        body = looks_of(client, alice)
        assert body.status_code == 200 and body.json() == [] and "bobs-look" not in body.text

    def test_another_users_items_inside_a_look_row_are_never_exposed(self, client, two_users, add_item, sql):
        alice, bob = two_users
        mine, theirs = add_item(alice, subcategory="mine"), add_item(bob, subcategory="secret-jacket")
        only_theirs = seed_look(sql, alice.user_id, [theirs], "2020-01-01T00:00:00+00:00")
        mixed = seed_look(sql, alice.user_id, [theirs, mine], "2020-01-02T00:00:00+00:00")
        body = looks_of(client, alice)
        assert body.status_code == 200
        assert [l["look_id"] for l in body.json()] == [mixed]
        assert [i["item_id"] for i in body.json()[0]["items"]] == [mine]
        assert theirs not in body.text and "secret-jacket" not in body.text and only_theirs not in body.text

    # -- damaged data ----------------------------------------------------------------

    def test_unreadable_item_lists_are_skipped_not_fatal(self, client, alice, add_item, sql):
        (a,) = pieces(add_item, alice, 1)
        for n, raw in enumerate(["this is not json", "null", '{"k": "v"}', "[]", "5"]):
            seed_look(sql, alice.user_id, None, f"2020-01-0{n + 1}T00:00:00+00:00", raw_ids=raw)
        good = seed_look(sql, alice.user_id, [a], "2021-01-01T00:00:00+00:00")
        resp = looks_of(client, alice)
        assert resp.status_code == 200 and [l["look_id"] for l in resp.json()] == [good]

    def test_non_string_entries_in_a_stored_list_are_dropped(self, client, alice, add_item, sql):
        (a,) = pieces(add_item, alice, 1)
        look_id = seed_look(sql, alice.user_id, None, "2020-01-01T00:00:00+00:00",
                            raw_ids=json.dumps([1, None, {"a": 1}, a, ["x"]]))
        (look,) = looks_of(client, alice).json()
        assert look["look_id"] == look_id and [i["item_id"] for i in look["items"]] == [a]

    def test_listing_uses_one_query_per_table_however_many_looks_there_are(self, client, alice, add_item, sql):
        ids = pieces(add_item, alice, 8)
        for n in range(20):
            seed_look(sql, alice.user_id, ids, f"2020-01-01T00:{n:02d}:00+00:00")
        statements = []

        def record(_conn, _cursor, statement, *_a, **_k):
            statements.append(statement)

        event.listen(database.engine, "before_cursor_execute", record)
        try:
            assert len(looks_of(client, alice).json()) == 20
        finally:
            event.remove(database.engine, "before_cursor_execute", record)
        assert sum("FROM wardrobe_items" in s for s in statements) == 1
        assert sum("FROM saved_looks" in s for s in statements) == 1


# ---------------------------------------------------------------------------
# DELETE /wardrobe/looks/{look_id}
# ---------------------------------------------------------------------------

class TestDeleteLook:
    def test_deletes_the_look(self, client, alice, add_item, sql):
        a, b = pieces(add_item, alice, 2)
        keep, drop = save_ok(client, alice, [a]), save_ok(client, alice, [b])
        resp = delete_look(client, alice, drop)
        assert resp.status_code == 200 and resp.json() == {"status": "deleted", "look_id": drop}
        assert [r["look_id"] for r in look_rows(sql)] == [keep]
        assert [l["look_id"] for l in looks_of(client, alice).json()] == [keep]

    def test_the_items_in_the_look_stay_in_the_wardrobe(self, client, alice, add_item):
        a, b = pieces(add_item, alice, 2)
        delete_look(client, alice, save_ok(client, alice, [a, b]))
        assert {i["item_id"] for i in client.get(f"/wardrobe/items/{alice.user_id}", headers=alice.headers).json()} == {a, b}

    def test_another_users_look_is_404_and_still_there(self, client, two_users, add_item, sql):
        alice, bob = two_users
        look_id = save_ok(client, bob, [add_item(bob)])
        resp = delete_look(client, alice, look_id)
        assert resp.status_code == 404 and resp.json()["detail"] == "Look not found"
        assert [r["look_id"] for r in look_rows(sql, bob.user_id)] == [look_id]
        assert [l["look_id"] for l in looks_of(client, bob).json()] == [look_id]

    @pytest.mark.parametrize("look_id", ["no-such-look", str(uuid.uuid4()), "' OR 1=1 --", "💥", "x" * 500])
    def test_unknown_ids_are_404(self, client, alice, add_item, sql, look_id):
        save_ok(client, alice, [add_item(alice)])
        assert delete_look(client, alice, look_id).status_code == 404
        assert len(look_rows(sql)) == 1

    def test_deleting_twice_is_404_the_second_time(self, client, alice, add_item):
        look_id = save_ok(client, alice, [add_item(alice)])
        assert delete_look(client, alice, look_id).status_code == 200
        assert delete_look(client, alice, look_id).status_code == 404

    @pytest.mark.parametrize("headers", [{}, bearer("garbage")])
    def test_requires_a_valid_token(self, client, alice, add_item, sql, headers):
        look_id = save_ok(client, alice, [add_item(alice)])
        assert client.delete(f"/wardrobe/looks/{look_id}", headers=headers).status_code == 401
        assert len(look_rows(sql)) == 1


# ---------------------------------------------------------------------------
# Schema and settings that back the feature
# ---------------------------------------------------------------------------

class TestSavedLooksSchema:
    def test_table_columns(self, sql):
        columns = {r["name"]: r for r in sql("PRAGMA table_info(saved_looks)")}
        assert set(columns) == {"look_id", "user_id", "name", "item_ids", "created_at"}
        assert columns["look_id"]["pk"] == 1
        assert columns["name"]["notnull"] == 0
        assert all(columns[c]["notnull"] == 1 for c in ("user_id", "item_ids", "created_at"))

    def test_index_covers_user_and_created_at(self, sql):
        (index,) = sql("SELECT name, tbl_name FROM sqlite_master WHERE type = 'index' AND name = 'idx_looks_user'")
        assert index["tbl_name"] == "saved_looks"
        columns = [r["name"] for r in sql("PRAGMA index_info(idx_looks_user)")]
        assert columns == ["user_id", "created_at"]

    def test_look_id_is_unique(self, sql):
        from sqlalchemy.exc import IntegrityError

        seed_look(sql, "u", ["x"], "2020-01-01", look_id="same")
        with pytest.raises(IntegrityError):
            seed_look(sql, "u", ["y"], "2020-01-02", look_id="same")

    def test_the_per_test_wipe_covers_saved_looks(self, sql):
        import conftest

        assert "saved_looks" in conftest._TABLES
        seed_look(sql, "u", ["x"], "2020-01-01")
        conftest._wipe_database()
        assert look_rows(sql) == []


class TestStudioSettings:
    def test_defaults(self):
        assert get_settings().studio_model == "u2netp"

    def test_override_and_blank(self, set_env):
        set_env(STUDIO_RMBG_MODEL=" isnet-general-use ")
        assert get_settings().studio_model == "isnet-general-use"
        set_env(STUDIO_RMBG_MODEL="   ")
        assert get_settings().studio_model == "u2netp"


# ---------------------------------------------------------------------------
# Two requests racing (a double-tap on "Save look")
# ---------------------------------------------------------------------------

class TestConcurrentSaves:
    """
    Both requests start together (a barrier ahead of the save's first read), and ``get_settings`` —
    called after the 'does this set already exist?' read and before the INSERT — sleeps, which widens
    the gap between check and insert. Without per-user serialisation both requests would pass the
    check inside that gap, exactly like two near-simultaneous taps.
    """

    @pytest.fixture
    def hold_requests_before_insert(self, monkeypatch):
        """Returns ``arm()``; call it once the wardrobe is set up (add-item also calls get_settings)."""
        import threading
        import time

        import routers.wardrobe as wardrobe

        real_settings = wardrobe.get_settings
        real_owned = wardrobe._owned_items

        def arm():
            barrier = threading.Barrier(2, timeout=10)

            def start_together(*args, **kwargs):
                barrier.wait()
                return real_owned(*args, **kwargs)

            def slow_settings():
                time.sleep(0.3)
                return real_settings()

            monkeypatch.setattr(wardrobe, "_owned_items", start_together)
            monkeypatch.setattr(wardrobe, "get_settings", slow_settings)

        return arm

    def race(self, client, account, payloads):
        from concurrent.futures import ThreadPoolExecutor

        def one(item_ids):
            return save(client, account, item_ids)

        with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
            return list(pool.map(one, payloads))

    def test_a_double_tap_stores_the_outfit_once(self, client, alice, add_item, sql, hold_requests_before_insert):
        a, b = pieces(add_item, alice, 2)
        hold_requests_before_insert()
        responses = self.race(client, alice, [[a, b], [b, a]])
        assert sorted(r.status_code for r in responses) == [200, 201]
        assert len(look_rows(sql)) == 1

    def test_two_racing_saves_cannot_overshoot_the_cap(self, client, alice, add_item, sql, set_env,
                                                      hold_requests_before_insert):
        set_env(MAX_SAVED_LOOKS=1)
        a, b = pieces(add_item, alice, 2)
        hold_requests_before_insert()
        responses = self.race(client, alice, [[a], [b]])
        assert sorted(r.status_code for r in responses) == [201, 403]
        assert len(look_rows(sql)) == 1
