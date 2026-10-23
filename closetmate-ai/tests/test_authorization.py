"""
Authentication coverage and cross-tenant (IDOR) protection.

Two users, A (alice) and B (bob). Everything A does against B's ids must be
refused AND must leave B's data untouched.
"""
from __future__ import annotations

import json

import pytest

from conftest import bearer

# ---------------------------------------------------------------------------
# Every protected router answers 401 without a token
# ---------------------------------------------------------------------------

PROTECTED = [
    ("GET", "/wardrobe/items/some-user"),
    ("POST", "/wardrobe/add-item"),
    ("DELETE", "/wardrobe/item/some-item"),
    ("POST", "/wardrobe/recommend"),
    ("POST", "/wardrobe/log-worn"),
    ("GET", "/wardrobe/worn-history/some-user"),
    ("POST", "/wardrobe/looks"),
    ("GET", "/wardrobe/looks/some-user"),
    ("DELETE", "/wardrobe/looks/some-look"),
    ("POST", "/chat/message"),
    ("POST", "/chat/weather"),
    ("GET", "/chat/insights/some-user"),
    ("POST", "/upload/upload-clothing"),
    ("POST", "/upload/analyze-clothing"),
    ("POST", "/images/remove-bg"),
    ("POST", "/images/remove-background"),
    ("POST", "/images/style"),
    ("POST", "/images/studio-shot"),
    ("POST", "/images/analyze-lighting"),
    ("POST", "/remove-bg"),                  # root-level alias used by older app builds
    ("POST", "/remove-background"),
    ("POST", "/style"),
    ("POST", "/studio-shot"),
    ("POST", "/analyze-lighting"),
    ("POST", "/recommend/outfit"),
    ("GET", "/auth/profile"),
    ("PATCH", "/auth/profile"),
    ("GET", "/auth/usage"),
]


@pytest.mark.parametrize("method,path", PROTECTED, ids=[f"{m} {p}" for m, p in PROTECTED])
class TestProtectedRoutesNeedAToken:
    def test_no_token_is_401(self, client, method, path):
        resp = client.request(method, path)
        assert resp.status_code == 401, resp.text
        assert resp.headers["www-authenticate"] == "Bearer"

    def test_garbage_token_is_401(self, client, method, path):
        assert client.request(method, path, headers=bearer("not.a.jwt")).status_code == 401

    def test_legacy_dev_token_is_401(self, client, method, path):
        assert client.request(method, path, headers=bearer("dev-1234-legacy")).status_code == 401


class TestPublicRoutes:
    def test_register_login_and_probes_need_no_token(self, client):
        assert client.get("/").status_code == 200
        assert client.get("/health").status_code == 200
        reg = client.post("/auth/register", json={
            "name": "Pub", "email": "pub@example.com", "password": "long-enough-pw", "gender": "other"})
        assert reg.status_code == 201
        login = client.post("/auth/login", json={"email": "pub@example.com", "password": "long-enough-pw"})
        assert login.status_code == 200
        bad = client.post("/auth/login", json={"email": "pub@example.com", "password": "wrong-password"})
        assert bad.status_code == 401 and bad.json()["detail"] == "Invalid credentials"   # not "Missing Authorization"

    def test_refresh_and_logout_authenticate_by_refresh_token_not_bearer(self, client, alice):
        assert client.post("/auth/logout", json={"refresh_token": alice.refresh_token}).status_code == 204

    def test_analyze_skin_tone_needs_no_token(self, client, monkeypatch, png_bytes):
        import routers.skin_tone as skin

        monkeypatch.setattr(skin, "detect_skin_tone", lambda _b: {"skin_tone": "medium", "undertone": "warm"})
        resp = client.post("/analyze-skin-tone", files={"file": ("selfie.png", png_bytes, "image/png")})
        assert resp.status_code == 200
        assert resp.json()["skin_tone"] == "medium"

    def test_analyze_skin_tone_is_ip_rate_limited(self, client, monkeypatch, png_bytes):
        import routers.skin_tone as skin

        monkeypatch.setattr(skin, "detect_skin_tone", lambda _b: {"skin_tone": "deep"})
        codes = [
            client.post("/analyze-skin-tone", files={"file": ("s.png", png_bytes, "image/png")}).status_code
            for _ in range(11)
        ]
        assert codes[:10] == [200] * 10
        assert codes[10] == 429

    def test_analyze_skin_tone_rejects_non_images_and_empty_files(self, client, monkeypatch):
        import routers.skin_tone as skin

        monkeypatch.setattr(skin, "detect_skin_tone", lambda _b: pytest.fail("must not be reached"))
        assert client.post("/analyze-skin-tone", files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 400
        assert client.post("/analyze-skin-tone", files={"file": ("a.png", b"", "image/png")}).status_code == 400
        assert client.post("/analyze-skin-tone", files={"file": ("a.png", b"not an image", "image/png")}).status_code == 422


# ---------------------------------------------------------------------------
# Cross-tenant access (IDOR)
# ---------------------------------------------------------------------------

class TestCrossTenantIsolation:
    def test_cannot_list_another_users_wardrobe(self, client, two_users, add_item):
        alice, bob = two_users
        add_item(bob)
        resp = client.get(f"/wardrobe/items/{bob.user_id}", headers=alice.headers)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Forbidden"
        assert "white" not in resp.text

    def test_cannot_add_items_to_another_users_wardrobe(self, client, two_users, sql):
        alice, bob = two_users
        resp = client.post(
            "/wardrobe/add-item", headers=alice.headers,
            json={"user_id": bob.user_id, "image_path": "uploads/x.jpg", "category": "top"},
        )
        assert resp.status_code == 403
        assert sql("SELECT 1 FROM wardrobe_items") == []

    def test_cannot_delete_another_users_item(self, client, two_users, add_item, sql):
        alice, bob = two_users
        bobs_item = add_item(bob)
        resp = client.delete(f"/wardrobe/item/{bobs_item}", headers=alice.headers)
        assert resp.status_code == 404                      # indistinguishable from "does not exist"
        assert resp.json()["detail"] == "Item not found"
        still_there = sql("SELECT user_id FROM wardrobe_items WHERE item_id = :i", i=bobs_item)
        assert still_there == [{"user_id": bob.user_id}]

    def test_cannot_log_another_users_items_as_worn(self, client, two_users, add_item, sql):
        alice, bob = two_users
        bobs_item = add_item(bob)
        resp = client.post("/wardrobe/log-worn", headers=alice.headers,
                           json={"user_id": alice.user_id, "item_ids": [bobs_item]})
        assert resp.status_code == 400
        assert sql("SELECT 1 FROM worn_logs") == []

    def test_mixed_log_keeps_only_the_callers_items(self, client, two_users, add_item, sql):
        alice, bob = two_users
        mine, theirs = add_item(alice), add_item(bob)
        resp = client.post("/wardrobe/log-worn", headers=alice.headers,
                           json={"user_id": alice.user_id, "item_ids": [theirs, mine]})
        assert resp.status_code == 200
        assert json.loads(sql("SELECT item_ids FROM worn_logs")[0]["item_ids"]) == [mine]

    def test_cannot_log_worn_on_behalf_of_another_user(self, client, two_users, add_item, sql):
        alice, bob = two_users
        bobs_item = add_item(bob)
        resp = client.post("/wardrobe/log-worn", headers=alice.headers,
                           json={"user_id": bob.user_id, "item_ids": [bobs_item]})
        assert resp.status_code == 403
        assert sql("SELECT 1 FROM worn_logs") == []

    def test_cannot_read_another_users_worn_history(self, client, two_users, add_item):
        alice, bob = two_users
        client.post("/wardrobe/log-worn", headers=bob.headers,
                    json={"user_id": bob.user_id, "item_ids": [add_item(bob)]})
        resp = client.get(f"/wardrobe/worn-history/{bob.user_id}", headers=alice.headers)
        assert resp.status_code == 403

    def test_cannot_read_another_users_insights(self, client, two_users, fake_llm, usage_count):
        alice, bob = two_users
        resp = client.get(f"/chat/insights/{bob.user_id}", headers=alice.headers)
        assert resp.status_code == 403
        assert fake_llm.openai_calls == []
        assert usage_count(alice.user_id, "insights") == 0       # refused before any quota is spent

    def test_cannot_chat_as_another_user(self, client, two_users, fake_llm, usage_count):
        alice, bob = two_users
        resp = client.post("/chat/message", headers=alice.headers,
                           json={"user_id": bob.user_id, "message": "what do I own?"})
        assert resp.status_code == 403
        assert fake_llm.openai_calls == []
        assert usage_count(alice.user_id, "chat") == 0 and usage_count(bob.user_id, "chat") == 0

    def test_cannot_request_recommendations_for_another_user(self, client, two_users):
        alice, bob = two_users
        resp = client.post("/recommend/outfit", headers=alice.headers,
                           json={"user_id": bob.user_id, "occasion": "casual"})
        assert resp.status_code == 403

    def test_own_resources_remain_accessible(self, client, two_users, add_item):
        alice, _bob = two_users
        item = add_item(alice)
        assert client.get(f"/wardrobe/items/{alice.user_id}", headers=alice.headers).status_code == 200
        assert client.get(f"/wardrobe/worn-history/{alice.user_id}", headers=alice.headers).status_code == 200
        assert client.delete(f"/wardrobe/item/{item}", headers=alice.headers).status_code == 200

    def test_user_id_comparison_is_exact(self, client, alice):
        assert client.get(f"/wardrobe/items/{alice.user_id.upper()}", headers=alice.headers).status_code == 403
        assert client.get(f"/wardrobe/items/{alice.user_id} ", headers=alice.headers).status_code == 403

    def test_a_token_for_a_nonexistent_user_sees_an_empty_closet_not_someone_elses(self, client, two_users, add_item):
        import security

        _alice, bob = two_users
        add_item(bob)
        ghost_token, _ = security.create_access_token("ghost-user-id")
        resp = client.get("/wardrobe/items/ghost-user-id", headers=bearer(ghost_token))
        assert resp.status_code == 200 and resp.json() == []
