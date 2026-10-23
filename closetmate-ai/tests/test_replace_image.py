"""PATCH /wardrobe/item/{item_id}/image — upgrade an item's photo (e.g. to a studio shot) in place."""
from __future__ import annotations

import pytest

NEW = "file:///data/user/0/app/files/closetmate_images/item_1.webp"


def replace(client, account, item_id, image_path=NEW, **kwargs):
    return client.patch(f"/wardrobe/item/{item_id}/image", headers=account.headers,
                        json={"image_path": image_path}, **kwargs)


def stored_path(sql, item_id):
    return sql("SELECT image_path FROM wardrobe_items WHERE item_id = :i", i=item_id)[0]["image_path"]


class TestReplacingAPhoto:
    def test_the_owner_can_replace_it(self, client, alice, add_item, sql):
        item = add_item(alice)
        resp = replace(client, alice, item)
        assert resp.status_code == 200 and resp.json() == {"status": "updated", "item_id": item}
        assert stored_path(sql, item) == NEW

    def test_only_the_photo_changes(self, client, alice, add_item, sql):
        item = add_item(alice, category="bottom", subcategory="jeans", primary_color="navy")
        before = sql("SELECT * FROM wardrobe_items WHERE item_id = :i", i=item)[0]
        replace(client, alice, item)
        after = sql("SELECT * FROM wardrobe_items WHERE item_id = :i", i=item)[0]
        assert {k: v for k, v in after.items() if k != "image_path"} == {k: v for k, v in before.items() if k != "image_path"}
        assert after["image_path"] == NEW

    def test_the_wardrobe_list_shows_the_new_photo(self, client, alice, add_item):
        item = add_item(alice)
        replace(client, alice, item)
        listed = client.get(f"/wardrobe/items/{alice.user_id}", headers=alice.headers).json()
        assert [i["image_path"] for i in listed if i["item_id"] == item] == [NEW]

    def test_saved_looks_keep_the_item_and_show_its_new_photo(self, client, alice, add_item):
        top, bottom = add_item(alice), add_item(alice, category="bottom", subcategory="jeans")
        client.post("/wardrobe/looks", headers=alice.headers, json={"user_id": alice.user_id, "item_ids": [top, bottom]})
        replace(client, alice, top)
        look = client.get(f"/wardrobe/looks/{alice.user_id}", headers=alice.headers).json()[0]
        assert {i["item_id"]: i["image_path"] for i in look["items"]}[top] == NEW

    def test_worn_history_keeps_the_item(self, client, alice, add_item):
        item = add_item(alice)
        client.post("/wardrobe/log-worn", headers=alice.headers, json={"user_id": alice.user_id, "item_ids": [item]})
        replace(client, alice, item)
        history = client.get(f"/wardrobe/worn-history/{alice.user_id}", headers=alice.headers).json()
        assert [i["item_id"] for log in history for i in log["items"]] == [item]

    def test_it_can_be_replaced_more_than_once(self, client, alice, add_item, sql):
        item = add_item(alice)
        replace(client, alice, item, "uploads/processed/a.webp")
        replace(client, alice, item, "uploads/processed/b.webp")
        assert stored_path(sql, item) == "uploads/processed/b.webp"

    @pytest.mark.parametrize("path", [
        "file:///data/x.webp",
        "content://media/external/images/1",
        "uploads/processed/x.webp",
        "https://storage.googleapis.com/bucket/x.webp",
    ])
    def test_the_same_locations_as_add_item_are_accepted(self, client, alice, add_item, path):
        assert replace(client, alice, add_item(alice), path).status_code == 200


class TestWhoMayReplaceIt:
    def test_a_stranger_gets_404_and_nothing_changes(self, client, two_users, add_item, sql):
        alice, bob = two_users
        item = add_item(alice)
        before = stored_path(sql, item)
        assert replace(client, bob, item).status_code == 404
        assert stored_path(sql, item) == before

    def test_an_unknown_item_is_404(self, client, alice):
        assert replace(client, alice, "no-such-item").status_code == 404

    def test_a_deleted_item_is_404(self, client, alice, add_item):
        item = add_item(alice)
        client.delete(f"/wardrobe/item/{item}", headers=alice.headers)
        assert replace(client, alice, item).status_code == 404

    def test_it_needs_a_token(self, client, alice, add_item):
        item = add_item(alice)
        assert client.patch(f"/wardrobe/item/{item}/image", json={"image_path": NEW}).status_code == 401

    def test_a_garbage_token_is_refused(self, client, alice, add_item):
        item = add_item(alice)
        resp = client.patch(f"/wardrobe/item/{item}/image", json={"image_path": NEW},
                            headers={"Authorization": "Bearer not-a-token"})
        assert resp.status_code == 401


class TestWhatItWillNotAccept:
    @pytest.mark.parametrize("path", [
        "http://evil.example/x.png",
        "https://evil.example/x.png",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "uploads/../health",
        "uploads/%2e%2e/health",
        "uploads/%252e%252e/health",
        "uploads\\..\\health",
        "",
        "javascript:alert(1)",
        "data:image/png;base64,AAAA",
    ])
    def test_unknown_or_traversing_locations_are_422_and_leave_the_photo_alone(self, client, alice, add_item, sql, path):
        item = add_item(alice)
        before = stored_path(sql, item)
        assert replace(client, alice, item, path).status_code == 422
        assert stored_path(sql, item) == before

    def test_an_overlong_path_is_422(self, client, alice, add_item):
        assert replace(client, alice, add_item(alice), "uploads/" + "a" * 2048).status_code == 422

    @pytest.mark.parametrize("body", [{}, {"image_path": None}, {"image_path": 5}, {"image_path": ["uploads/a"]}, {"path": NEW}])
    def test_a_malformed_body_is_422(self, client, alice, add_item, body):
        item = add_item(alice)
        assert client.patch(f"/wardrobe/item/{item}/image", headers=alice.headers, json=body).status_code == 422

    def test_extra_fields_cannot_change_anything_else(self, client, alice, add_item, sql):
        item = add_item(alice, category="top")
        client.patch(f"/wardrobe/item/{item}/image", headers=alice.headers,
                     json={"image_path": NEW, "category": "shoes", "user_id": "someone-else", "item_id": "x"})
        row = sql("SELECT category, user_id, item_id FROM wardrobe_items WHERE item_id = :i", i=item)[0]
        assert (row["category"], row["user_id"], row["item_id"]) == ("top", alice.user_id, item)

    def test_a_sql_looking_item_id_is_just_a_missing_item(self, client, alice, add_item, sql):
        add_item(alice)
        resp = client.patch("/wardrobe/item/x'%20OR%20'1'='1/image", headers=alice.headers, json={"image_path": NEW})
        assert resp.status_code == 404
        assert sql("SELECT count(*) AS n FROM wardrobe_items WHERE image_path = :p", p=NEW)[0]["n"] == 0


class TestRateLimit:
    def test_sixty_a_minute_then_429(self, client, alice, add_item):
        item = add_item(alice)
        codes = [replace(client, alice, item).status_code for _ in range(61)]
        assert codes[:60] == [200] * 60 and codes[60] == 429

    def test_it_is_per_user(self, client, two_users, add_item):
        alice, bob = two_users
        mine, theirs = add_item(alice), add_item(bob)
        for _ in range(60):
            replace(client, alice, mine)
        assert replace(client, alice, mine).status_code == 429
        assert replace(client, bob, theirs).status_code == 200
