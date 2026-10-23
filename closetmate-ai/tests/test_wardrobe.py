"""routers/wardrobe.py — add / list / delete items, log-worn, worn-history, /recommend quota refunds."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

import database


def log_worn(client, account, item_ids):
    return client.post(
        "/wardrobe/log-worn",
        json={"user_id": account.user_id, "item_ids": item_ids},
        headers=account.headers,
    )


def history(client, account, **params):
    return client.get(f"/wardrobe/worn-history/{account.user_id}", params=params, headers=account.headers)


# ---------------------------------------------------------------------------
# Add / list / delete
# ---------------------------------------------------------------------------

class TestAddItem:
    def test_returns_201_and_a_uuid_item_id(self, client, alice):
        resp = client.post(
            "/wardrobe/add-item",
            json={"user_id": alice.user_id, "image_path": "uploads/x.jpg", "category": "top"},
            headers=alice.headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "success"
        assert str(uuid.UUID(body["item_id"])) == body["item_id"]

    def test_optional_fields_default_to_null(self, client, alice, sql):
        client.post(
            "/wardrobe/add-item",
            json={"user_id": alice.user_id, "image_path": "uploads/p.jpg", "category": "shoes"},
            headers=alice.headers,
        )
        row = sql("SELECT * FROM wardrobe_items")[0]
        assert row["category"] == "shoes"
        assert all(row[c] is None for c in ("subcategory", "primary_color", "material", "pattern",
                                            "formality_level", "cultural_style"))

    def test_owner_is_taken_from_the_token(self, client, alice, add_item, sql):
        item_id = add_item(alice)
        assert sql("SELECT user_id FROM wardrobe_items WHERE item_id = :i", i=item_id)[0]["user_id"] == alice.user_id

    @pytest.mark.parametrize(
        "overrides",
        [
            {"category": "c" * 61},
            {"image_path": "p" * 2049},
            {"subcategory": "s" * 61},
            {"formality": "f" * 41},
            {"culture": "c" * 41},
            {"category": None},
            {"image_path": None},
        ],
    )
    def test_invalid_payload_is_422(self, client, alice, sql, overrides):
        payload = {"user_id": alice.user_id, "image_path": "uploads/p.jpg", "category": "top", **overrides}
        payload = {k: v for k, v in payload.items() if v is not None}
        resp = client.post("/wardrobe/add-item", json=payload, headers=alice.headers)
        assert resp.status_code == 422
        assert sql("SELECT 1 FROM wardrobe_items") == []

    def test_unicode_and_sql_characters_are_stored_verbatim(self, client, alice, add_item, sql):
        nasty = "Kurta ' OR 1=1 -- 🧵 कुर्ता"
        item_id = add_item(alice, subcategory=nasty[:60])
        assert sql("SELECT subcategory FROM wardrobe_items WHERE item_id = :i", i=item_id)[0]["subcategory"] == nasty[:60]
        assert len(sql("SELECT 1 FROM wardrobe_items")) == 1

    def test_requires_authentication(self, client, alice):
        resp = client.post("/wardrobe/add-item", json={"user_id": alice.user_id, "image_path": "uploads/p", "category": "top"})
        assert resp.status_code == 401


class TestListItems:
    def test_empty_wardrobe_is_an_empty_list(self, client, alice):
        resp = client.get(f"/wardrobe/items/{alice.user_id}", headers=alice.headers)
        assert resp.status_code == 200 and resp.json() == []

    def test_lists_items_with_all_fields(self, client, alice, add_item):
        item_id = add_item(
            alice, image_path="https://storage.googleapis.com/closetmate-test/a.jpg", category="top", subcategory="kurta",
            primary_color="navy", material="silk", pattern="paisley", formality="festive", culture="south_asian",
        )
        items = client.get(f"/wardrobe/items/{alice.user_id}", headers=alice.headers).json()
        assert len(items) == 1
        item = items[0]
        assert item["item_id"] == item_id and item["user_id"] == alice.user_id
        assert (item["category"], item["subcategory"], item["primary_color"]) == ("top", "kurta", "navy")
        assert (item["material"], item["pattern"]) == ("silk", "paisley")
        assert item["formality_level"] == "festive" and item["cultural_style"] == "south_asian"
        assert item["image_path"] == "https://storage.googleapis.com/closetmate-test/a.jpg"
        datetime.fromisoformat(item["created_at"])

    def test_newest_item_comes_first(self, client, alice, add_item):
        ids = [add_item(alice, subcategory=f"item-{n}") for n in range(4)]
        listed = [i["item_id"] for i in client.get(f"/wardrobe/items/{alice.user_id}", headers=alice.headers).json()]
        assert listed == list(reversed(ids))

    def test_large_wardrobe_is_returned_in_full(self, client, alice, sql):
        now = datetime.now(timezone.utc).isoformat()
        with database.engine.begin() as conn:
            conn.execute(
                text("INSERT INTO wardrobe_items (item_id, user_id, category, created_at) VALUES (:i, :u, 'top', :c)"),
                [{"i": str(uuid.uuid4()), "u": alice.user_id, "c": now} for _ in range(2000)],
            )
        items = client.get(f"/wardrobe/items/{alice.user_id}", headers=alice.headers).json()
        assert len(items) == 2000

    def test_only_the_callers_items_are_listed(self, client, two_users, add_item):
        alice, bob = two_users
        a, b = add_item(alice), add_item(bob)
        listed = {i["item_id"] for i in client.get(f"/wardrobe/items/{alice.user_id}", headers=alice.headers).json()}
        assert listed == {a} and b not in listed


class TestDeleteItem:
    def test_deletes_the_item(self, client, alice, add_item, sql):
        item_id = add_item(alice)
        resp = client.delete(f"/wardrobe/item/{item_id}", headers=alice.headers)
        assert resp.status_code == 200
        assert resp.json() == {"status": "deleted", "item_id": item_id}
        assert sql("SELECT 1 FROM wardrobe_items") == []

    def test_only_the_named_item_is_deleted(self, client, alice, add_item):
        keep, drop = add_item(alice), add_item(alice)
        client.delete(f"/wardrobe/item/{drop}", headers=alice.headers)
        listed = [i["item_id"] for i in client.get(f"/wardrobe/items/{alice.user_id}", headers=alice.headers).json()]
        assert listed == [keep]

    def test_missing_item_is_404(self, client, alice):
        resp = client.delete(f"/wardrobe/item/{uuid.uuid4()}", headers=alice.headers)
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Item not found"

    def test_deleting_twice_is_404_the_second_time(self, client, alice, add_item):
        item_id = add_item(alice)
        assert client.delete(f"/wardrobe/item/{item_id}", headers=alice.headers).status_code == 200
        assert client.delete(f"/wardrobe/item/{item_id}", headers=alice.headers).status_code == 404

    def test_sql_injection_in_item_id_is_harmless(self, client, alice, add_item):
        add_item(alice)
        resp = client.delete("/wardrobe/item/x' OR '1'='1", headers=alice.headers)
        assert resp.status_code == 404
        assert len(client.get(f"/wardrobe/items/{alice.user_id}", headers=alice.headers).json()) == 1


# ---------------------------------------------------------------------------
# log-worn
# ---------------------------------------------------------------------------

class TestLogWorn:
    def test_logs_an_outfit_for_today(self, client, alice, add_item, sql):
        a, b = add_item(alice), add_item(alice)
        resp = log_worn(client, alice, [a, b])
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "logged"
        assert body["worn_date"] == datetime.now(timezone.utc).date().isoformat()
        row = sql("SELECT * FROM worn_logs WHERE log_id = :l", l=body["log_id"])[0]
        assert row["user_id"] == alice.user_id and json.loads(row["item_ids"]) == [a, b]

    def test_only_owned_ids_are_kept(self, client, alice, add_item, sql):
        mine = add_item(alice)
        resp = log_worn(client, alice, [mine, "not-a-real-id", str(uuid.uuid4())])
        assert resp.status_code == 200
        assert json.loads(sql("SELECT item_ids FROM worn_logs")[0]["item_ids"]) == [mine]

    def test_order_of_ids_is_preserved(self, client, alice, add_item, sql):
        a, b, c = add_item(alice), add_item(alice), add_item(alice)
        log_worn(client, alice, [c, a, b])
        assert json.loads(sql("SELECT item_ids FROM worn_logs")[0]["item_ids"]) == [c, a, b]

    def test_no_owned_ids_is_400_and_nothing_is_stored(self, client, alice, sql):
        resp = log_worn(client, alice, ["ghost-1", "ghost-2"])
        assert resp.status_code == 400
        assert resp.json()["detail"] == "None of these items are in your wardrobe"
        assert sql("SELECT 1 FROM worn_logs") == []

    def test_empty_list_is_422(self, client, alice):
        assert log_worn(client, alice, []).status_code == 422

    def test_more_than_20_ids_is_422(self, client, alice):
        assert log_worn(client, alice, [str(uuid.uuid4()) for _ in range(21)]).status_code == 422

    def test_exactly_20_ids_is_accepted(self, client, alice, add_item):
        ids = [add_item(alice) for _ in range(20)]
        assert log_worn(client, alice, ids).status_code == 200

    def test_sql_injection_attempt_in_ids_is_harmless(self, client, alice, add_item, sql):
        mine = add_item(alice)
        resp = log_worn(client, alice, [mine, "x') OR 1=1 --"])
        assert resp.status_code == 200
        assert json.loads(sql("SELECT item_ids FROM worn_logs")[0]["item_ids"]) == [mine]

    def test_requires_authentication(self, client, alice):
        assert client.post("/wardrobe/log-worn", json={"user_id": alice.user_id, "item_ids": ["x"]}).status_code == 401


# ---------------------------------------------------------------------------
# worn-history
# ---------------------------------------------------------------------------

class TestWornHistory:
    def test_empty_history(self, client, alice):
        resp = history(client, alice)
        assert resp.status_code == 200 and resp.json() == []

    def test_returns_each_logs_items_newest_log_first(self, client, alice, add_item):
        shirt = add_item(alice, subcategory="shirt", primary_color="white", image_path="uploads/shirt.jpg")
        jeans = add_item(alice, subcategory="jeans", primary_color="blue", image_path="uploads/jeans.jpg")
        shoes = add_item(alice, subcategory="sneakers", primary_color="black", image_path="uploads/shoes.jpg")
        first = log_worn(client, alice, [jeans, shirt]).json()["log_id"]       # note: jeans before shirt
        second = log_worn(client, alice, [shoes]).json()["log_id"]

        logs = history(client, alice).json()
        assert [entry["log_id"] for entry in logs] == [second, first]
        assert [i["item_id"] for i in logs[0]["items"]] == [shoes]
        assert [i["item_id"] for i in logs[1]["items"]] == [jeans, shirt]       # log order, not DB order
        jeans_out = logs[1]["items"][0]
        assert jeans_out == {
            "item_id": jeans, "image_path": "uploads/jeans.jpg", "category": "top",
            "subcategory": "jeans", "primary_color": "blue",
            "slot": "bottom",                         # subcategory wins over the (wrong) category
        }
        assert logs[1]["items"][1]["slot"] == "top" and logs[0]["items"][0]["slot"] == "shoes"
        assert logs[0]["worn_date"] == datetime.now(timezone.utc).date().isoformat()

    def test_ordering_is_by_date_first(self, client, alice, add_item, sql):
        item = add_item(alice)
        newer = log_worn(client, alice, [item]).json()["log_id"]
        sql("INSERT INTO worn_logs (log_id, user_id, worn_date, item_ids, created_at) "
            "VALUES ('old-log', :u, '2001-01-01', :ids, '2099-01-01T00:00:00+00:00')",
            u=alice.user_id, ids=json.dumps([item]))
        # created_at of 'old-log' is later, but its worn_date is much older.
        assert [e["log_id"] for e in history(client, alice).json()] == [newer, "old-log"]

    def test_tolerates_a_deleted_item(self, client, alice, add_item):
        keep, gone = add_item(alice), add_item(alice)
        log_worn(client, alice, [gone, keep])
        client.delete(f"/wardrobe/item/{gone}", headers=alice.headers)
        resp = history(client, alice)
        assert resp.status_code == 200
        assert [i["item_id"] for i in resp.json()[0]["items"]] == [keep]

    def test_log_whose_items_are_all_deleted_has_empty_items(self, client, alice, add_item):
        only = add_item(alice)
        log_worn(client, alice, [only])
        client.delete(f"/wardrobe/item/{only}", headers=alice.headers)
        entry = history(client, alice).json()[0]
        assert entry["items"] == []

    def test_corrupt_item_ids_json_does_not_break_history(self, client, alice, add_item, sql):
        good = add_item(alice)
        for n, raw in enumerate(["this is not json", json.dumps([1, None, {"a": 1}, good]), json.dumps({"k": "v"}), "null"]):
            sql("INSERT INTO worn_logs (log_id, user_id, worn_date, item_ids, created_at) "
                "VALUES (:l, :u, '2020-01-01', :ids, :c)",
                l=f"log-{n}", u=alice.user_id, ids=raw, c=f"2020-01-01T00:00:0{n}+00:00")
        resp = history(client, alice, limit=50)
        assert resp.status_code == 200
        by_id = {e["log_id"]: [i["item_id"] for i in e["items"]] for e in resp.json()}
        assert by_id["log-0"] == []
        assert by_id["log-1"] == [good]                  # non-string entries are dropped
        assert by_id["log-3"] == []

    def test_default_limit_is_seven(self, client, alice, add_item):
        item = add_item(alice)
        for _ in range(9):
            log_worn(client, alice, [item])
        assert len(history(client, alice).json()) == 7

    def test_limit_parameter_is_honoured(self, client, alice, add_item):
        item = add_item(alice)
        for _ in range(5):
            log_worn(client, alice, [item])
        assert len(history(client, alice, limit=2).json()) == 2
        assert len(history(client, alice, limit=50).json()) == 5

    @pytest.mark.parametrize("limit", [0, -1, 51, 1000])
    def test_out_of_range_limit_is_422(self, client, alice, limit):
        assert history(client, alice, limit=limit).status_code == 422

    @pytest.mark.parametrize("limit", [1, 50])
    def test_boundary_limits_are_accepted(self, client, alice, limit):
        assert history(client, alice, limit=limit).status_code == 200

    def test_non_numeric_limit_is_422(self, client, alice):
        assert history(client, alice, limit="many").status_code == 422

    def test_history_only_contains_the_callers_logs(self, client, two_users, add_item):
        alice, bob = two_users
        log_worn(client, bob, [add_item(bob)])
        assert history(client, alice).json() == []

    def test_foreign_item_ids_inside_a_log_are_never_resolved(self, client, two_users, add_item, sql):
        """Defence in depth: even a log row that references someone else's item leaks nothing."""
        alice, bob = two_users
        bobs_item = add_item(bob, subcategory="secret-jacket")
        sql("INSERT INTO worn_logs (log_id, user_id, worn_date, item_ids, created_at) "
            "VALUES ('planted', :u, '2024-01-01', :ids, '2024-01-01T00:00:00+00:00')",
            u=alice.user_id, ids=json.dumps([bobs_item]))
        resp = history(client, alice)
        assert resp.status_code == 200
        assert resp.json()[0]["items"] == []
        assert "secret-jacket" not in resp.text


# ---------------------------------------------------------------------------
# add-item guard rails
# ---------------------------------------------------------------------------

class TestAddItemImagePath:
    @pytest.mark.parametrize(
        "path",
        [
            "uploads/processed/a.jpg",
            "https://storage.googleapis.com/bucket/a.jpg",
            "file:///data/user/0/app/cache/a.jpg",
            "content://media/external/images/1",
        ],
    )
    def test_known_locations_are_accepted(self, client, alice, path):
        resp = client.post("/wardrobe/add-item", headers=alice.headers,
                           json={"user_id": alice.user_id, "image_path": path, "category": "top"})
        assert resp.status_code == 201

    @pytest.mark.parametrize(
        "path",
        [
            "http://storage.googleapis.com/bucket/a.jpg",
            "https://evil.example.com/a.jpg",
            "https://storage.googleapis.com.evil.example.com/a.jpg",
            "javascript:alert(1)",
            "data:image/png;base64,AAAA",
            "//evil.example.com/a.jpg",
            "/etc/passwd",
            "a.jpg",
            "",
        ],
    )
    def test_arbitrary_hosts_and_schemes_are_rejected(self, client, alice, sql, path):
        resp = client.post("/wardrobe/add-item", headers=alice.headers,
                           json={"user_id": alice.user_id, "image_path": path, "category": "top"})
        assert resp.status_code == 422
        assert sql("SELECT 1 FROM wardrobe_items") == []

    @pytest.mark.parametrize(
        "path",
        [
            "uploads/../health",
            "uploads/a/../../b.jpg",
            "uploads/..\\health",
            # Percent-encoded forms: URL parsers (React Native fetch) normalise these to "..".
            "uploads/%2e%2e/health",
            "uploads/%2E%2E/health",
            "uploads/%252e%252e/health",       # double-encoded
        ],
    )
    def test_dot_dot_segments_are_rejected(self, client, alice, path, sql):
        resp = client.post("/wardrobe/add-item", headers=alice.headers,
                           json={"user_id": alice.user_id, "image_path": path, "category": "top"})
        assert resp.status_code == 422
        assert sql("SELECT 1 FROM wardrobe_items") == []


class TestWardrobeCapacity:
    def test_a_full_closet_is_403_with_a_structured_error(self, client, alice, add_item, set_env, sql):
        set_env(MAX_WARDROBE_ITEMS=2)
        add_item(alice)
        add_item(alice)
        resp = client.post(
            "/wardrobe/add-item", headers=alice.headers,
            json={"user_id": alice.user_id, "image_path": "uploads/x.jpg", "category": "top"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "wardrobe_full"
        assert len(sql("SELECT 1 FROM wardrobe_items")) == 2

    def test_deleting_an_item_frees_a_slot(self, client, alice, add_item, set_env):
        set_env(MAX_WARDROBE_ITEMS=1)
        first = add_item(alice)
        client.delete(f"/wardrobe/item/{first}", headers=alice.headers)
        add_item(alice)

    def test_the_cap_is_per_user(self, two_users, add_item, set_env):
        alice, bob = two_users
        set_env(MAX_WARDROBE_ITEMS=1)
        add_item(alice)
        add_item(bob)

    def test_adding_items_is_rate_limited_per_user(self, client, alice, bob):
        payload = {"image_path": "uploads/x.jpg", "category": "top"}
        for _ in range(60):
            assert client.post("/wardrobe/add-item", headers=alice.headers,
                               json={**payload, "user_id": alice.user_id}).status_code == 201
        limited = client.post("/wardrobe/add-item", headers=alice.headers, json={**payload, "user_id": alice.user_id})
        assert limited.status_code == 429
        assert int(limited.headers["retry-after"]) >= 1
        assert client.post("/wardrobe/add-item", headers=bob.headers,
                           json={**payload, "user_id": bob.user_id}).status_code == 201


# ---------------------------------------------------------------------------
# POST /wardrobe/recommend — only the paid LLM refinement is metered
# ---------------------------------------------------------------------------

class TestWardrobeRecommendQuota:
    PAYLOAD = {"wardrobe": [{"item_id": "a", "category": "top"}], "occasion": "casual",
               "temperature": 25.0, "humidity": 50.0}

    @pytest.fixture
    def stub_engine(self, monkeypatch):
        import routers.wardrobe as wardrobe

        state = {"outfits": [{"items": ["a"]}], "refine": None, "refine_calls": 0}

        def fake_build(**kwargs):
            return state["outfits"]

        async def fake_refine(**kwargs):
            state["refine_calls"] += 1
            if state["refine"] is not None:
                raise state["refine"]
            return {"best_outfit": ["a"], "alternatives": []}

        monkeypatch.setattr(wardrobe, "build_outfits", fake_build)
        monkeypatch.setattr(wardrobe, "ai_refine_outfits", fake_refine)
        return state

    def test_invalid_occasion_is_400_and_never_consumes_quota(self, client, alice, usage_count):
        resp = client.post("/wardrobe/recommend", json={**self.PAYLOAD, "occasion": "moonwalk"}, headers=alice.headers)
        assert resp.status_code == 400
        assert usage_count(alice.user_id, "chat") == 0

    def test_no_outfits_is_404_and_never_consumes_quota(self, client, alice, usage_count, stub_engine):
        stub_engine["outfits"] = []
        resp = client.post("/wardrobe/recommend", json=self.PAYLOAD, headers=alice.headers)
        assert resp.status_code == 404
        assert usage_count(alice.user_id, "chat") == 0
        assert stub_engine["refine_calls"] == 0

    def test_success_consumes_one_chat_unit(self, client, alice, usage_count, stub_engine):
        resp = client.post("/wardrobe/recommend", json=self.PAYLOAD, headers=alice.headers)
        assert resp.status_code == 200
        assert usage_count(alice.user_id, "chat") == 1

    def test_third_request_hits_the_monthly_cap(self, client, alice, stub_engine):
        for _ in range(2):
            assert client.post("/wardrobe/recommend", json=self.PAYLOAD, headers=alice.headers).status_code == 200
        resp = client.post("/wardrobe/recommend", json=self.PAYLOAD, headers=alice.headers)
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == "quota_exceeded"
        assert stub_engine["refine_calls"] == 2

    def test_refinement_crash_is_500_and_refunded(self, client_no_raise, alice, usage_count, stub_engine):
        stub_engine["refine"] = RuntimeError("provider exploded")
        resp = client_no_raise.post("/wardrobe/recommend", json=self.PAYLOAD, headers=alice.headers)
        assert resp.status_code == 500
        assert "provider exploded" not in resp.json().get("detail", "")
        assert usage_count(alice.user_id, "chat") == 0

    def test_requires_authentication(self, client):
        assert client.post("/wardrobe/recommend", json=self.PAYLOAD).status_code == 401

    def test_is_rate_limited_per_user(self, client, alice, set_env):
        set_env(QUOTA_FREE_CHAT_MONTHLY=1000)
        bad = {**self.PAYLOAD, "occasion": "moonwalk"}
        codes = [client.post("/wardrobe/recommend", json=bad, headers=alice.headers).status_code for _ in range(11)]
        assert codes[:10] == [400] * 10 and codes[10] == 429
