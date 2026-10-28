"""routers/chat.py — `category` / `slot` on suggested items and the `look_meta` chips on an outfit reply."""
from __future__ import annotations

import json

import pytest

from services.skin_tone_detector import _TONE_COLORS
from services.weather_service import WeatherData

# light-medium (warm): caramel, warm beige, mustard, burnt orange, cream, gold, warm olive
WARM = "light-medium (warm)"
IN_PALETTE = ["cream", "mustard", "caramel"]
OUTSIDE_PALETTE = ["black", "navy", "red"]

WEATHER = WeatherData(
    city="Dhaka", country="BD", temperature=31.0, feels_like=36.0, humidity=80, wind_speed=9.0,
    condition="Rain", condition_icon="rain", uv_index=6.0, is_day=True,
)

ITEM_KEYS = {"subcategory", "color", "item_id", "image_url", "thumb_url", "category", "slot"}


def chat(client, account, message="what should I wear?", **extra):
    return client.post("/chat/message", headers=account.headers,
                       json={"user_id": account.user_id, "message": message, **extra})


def outfit_reply(items: list, text: str = "Here you go.") -> str:
    return f"{text} <outfit>{json.dumps({'items': items})}</outfit>"


def pick(item_id, subcategory, color):
    return {"item_id": item_id, "subcategory": subcategory, "color": color}


@pytest.fixture
def tone_user(make_account):
    return make_account(email="warm@example.com", skin_tone=WARM)


def ask(client, account, fake_llm, items, **extra):
    fake_llm.openai_reply = outfit_reply(items)
    resp = chat(client, account, **extra)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# category + slot on every suggested item
# ---------------------------------------------------------------------------

class TestSuggestedItemFields:
    def test_every_suggested_item_has_exactly_the_documented_keys(self, client, alice, fake_llm, add_item):
        shirt = add_item(alice, subcategory="shirt")
        body = ask(client, alice, fake_llm, [pick(shirt, "shirt", "white")])
        assert set(body["suggested_items"][0]) == ITEM_KEYS
        assert set(body) == {"reply", "suggested_items", "weather_summary", "look_meta"}

    @pytest.mark.parametrize("category,subcategory,slot", [
        ("traditional", "saree", "dress"),
        ("traditional", "lehenga", "dress"),
        ("traditional", "panjabi", "top"),
        ("top", "t-shirt", "top"),
        ("bottom", "jeans", "bottom"),
        ("top", "jacket", "outer"),
        ("outerwear", "coat", "outer"),
        ("footwear", "sneakers", "shoes"),
        ("accessory", "watch", "accessory"),
        ("accessory", "belt", "accessory"),
        ("dress", "dress", "dress"),
    ])
    def test_category_comes_from_the_wardrobe_row_and_slot_from_outfit_slot(
        self, client, alice, fake_llm, add_item, category, subcategory, slot
    ):
        item = add_item(alice, category=category, subcategory=subcategory, primary_color="red")
        (suggested,) = ask(client, alice, fake_llm, [pick(item, subcategory, "red")])["suggested_items"]
        assert suggested["category"] == category and suggested["slot"] == slot

    def test_a_saree_is_a_dress(self, client, alice, fake_llm, add_item):
        saree = add_item(alice, category="traditional", subcategory="saree", primary_color="red")
        (item,) = ask(client, alice, fake_llm, [pick(saree, "saree", "red")])["suggested_items"]
        assert item["slot"] == "dress" and item["category"] == "traditional" and item["item_id"] == saree

    def test_a_full_outfit_keeps_the_models_order_and_gets_a_slot_each(self, client, alice, fake_llm, add_item):
        shirt = add_item(alice, category="top", subcategory="shirt")
        jeans = add_item(alice, category="bottom", subcategory="jeans")
        shoes = add_item(alice, category="footwear", subcategory="sneakers")
        watch = add_item(alice, category="accessory", subcategory="watch")
        items = ask(client, alice, fake_llm, [
            pick(watch, "watch", "silver"), pick(shirt, "shirt", "white"),
            pick(jeans, "jeans", "blue"), pick(shoes, "sneakers", "white"),
        ])["suggested_items"]
        assert [(i["item_id"], i["slot"]) for i in items] == [
            (watch, "accessory"), (shirt, "top"), (jeans, "bottom"), (shoes, "shoes")]

    def test_the_rows_subcategory_decides_the_slot_not_what_the_model_called_it(self, client, alice, fake_llm, add_item):
        jacket = add_item(alice, category="top", subcategory="jacket")
        (item,) = ask(client, alice, fake_llm, [pick(jacket, "shirt", "blue")])["suggested_items"]
        assert item["slot"] == "outer" and item["category"] == "top"

    def test_a_row_without_a_subcategory_falls_back_to_the_models_subcategory(self, client, alice, fake_llm, add_item):
        item_id = add_item(alice, category="footwear", subcategory=None)
        (item,) = ask(client, alice, fake_llm, [pick(item_id, "boots", "brown")])["suggested_items"]
        assert item["category"] == "footwear" and item["slot"] == "shoes"

    def test_a_missing_item_id_is_resolved_and_its_category_and_slot_follow(self, client, alice, fake_llm, add_item):
        saree = add_item(alice, category="traditional", subcategory="saree", primary_color="red")
        (item,) = ask(client, alice, fake_llm, [{"subcategory": "Saree", "color": "Red"}])["suggested_items"]
        assert item["item_id"] == saree and item["category"] == "traditional" and item["slot"] == "dress"

    def test_something_not_in_the_wardrobe_has_no_category_and_a_slot_from_the_models_words(
        self, client, alice, fake_llm
    ):
        items = ask(client, alice, fake_llm, [
            {"subcategory": "cape", "color": "gold"},
            {"subcategory": "saree", "color": "red"},
            {"subcategory": "mystery object", "color": "grey"},
        ])["suggested_items"]
        assert [(i["category"], i["slot"]) for i in items] == [(None, "outer"), (None, "dress"), (None, "accessory")]

    def test_an_invented_item_id_gets_no_category(self, client, alice, fake_llm):
        (item,) = ask(client, alice, fake_llm, [pick("made-up-id", "sneakers", "white")])["suggested_items"]
        assert item["category"] is None and item["slot"] == "shoes"

    def test_another_users_item_id_does_not_leak_their_category(self, client, two_users, fake_llm, add_item):
        alice, bob = two_users
        bobs = add_item(bob, category="traditional", subcategory="saree", image_path="uploads/bobs-private.jpg")
        body = ask(client, alice, fake_llm, [pick(bobs, "hat", "red")])
        (item,) = body["suggested_items"]
        assert item["category"] is None and item["slot"] == "accessory" and item["image_url"] is None
        assert "bobs-private" not in json.dumps(body)

    def test_the_slot_is_always_one_of_the_six(self, client, alice, fake_llm, add_item):
        add_item(alice, category="top", subcategory="shirt")
        items = ask(client, alice, fake_llm, [
            {"subcategory": s, "color": "x"} for s in ("shirt", "", "🎩", "x" * 300, "DRESS", "Sandals")
        ])["suggested_items"]
        assert {i["slot"] for i in items} <= {"outer", "dress", "top", "bottom", "shoes", "accessory"}


# ---------------------------------------------------------------------------
# look_meta
# ---------------------------------------------------------------------------

class TestLookMetaIsPresentOnlyForOutfits:
    def test_no_outfit_block_means_no_look_meta(self, client, alice, fake_llm):
        fake_llm.openai_reply = "Just chatting."
        assert chat(client, alice).json()["look_meta"] is None

    @pytest.mark.parametrize("reply", [
        "Oops <outfit>{not json</outfit>",
        'Empty <outfit>{"items": []}</outfit>',
        'Strings <outfit>{"items": ["shirt"]}</outfit>',
    ])
    def test_unusable_outfit_blocks_mean_no_look_meta(self, client, tone_user, fake_llm, reply):
        fake_llm.openai_reply = reply
        body = chat(client, tone_user).json()
        assert body["suggested_items"] is None and body["look_meta"] is None

    def test_with_items_look_meta_has_exactly_weather_and_palette(self, client, alice, fake_llm):
        body = ask(client, alice, fake_llm, [pick(None, "shirt", "white")])
        assert body["look_meta"] == {"weather": None, "palette": None}


class TestWeatherInLookMeta:
    def test_weather_summary_is_echoed(self, client, alice, fake_llm, monkeypatch):
        import routers.chat as chat_router

        monkeypatch.setattr(chat_router, "get_weather_by_city", lambda city: WEATHER)
        body = ask(client, alice, fake_llm, [pick(None, "shirt", "white")],
                   weather={"city": "Dhaka", "environment": "outdoor"})
        assert body["weather_summary"]["city"] == "Dhaka"
        assert body["look_meta"]["weather"] == body["weather_summary"]
        assert body["look_meta"]["weather"]["temperature"] == 31.0

    def test_a_failed_weather_lookup_leaves_weather_empty(self, client, alice, fake_llm, monkeypatch):
        import routers.chat as chat_router

        def boom(_city):
            raise ConnectionError("down")

        monkeypatch.setattr(chat_router, "get_weather_by_city", boom)
        body = ask(client, alice, fake_llm, [pick(None, "shirt", "white")], weather={"city": "Dhaka"})
        assert body["weather_summary"] is None and body["look_meta"]["weather"] is None

    def test_weather_without_an_outfit_has_no_look_meta(self, client, alice, fake_llm, monkeypatch):
        import routers.chat as chat_router

        monkeypatch.setattr(chat_router, "get_weather_by_city", lambda city: WEATHER)
        body = chat(client, alice, weather={"city": "Dhaka"}).json()
        assert body["weather_summary"]["city"] == "Dhaka" and body["look_meta"] is None


class TestPaletteInLookMeta:
    def wardrobe(self, add_item, account, colours):
        return [add_item(account, category="top", subcategory=f"piece-{n}", primary_color=c)
                for n, c in enumerate(colours)]

    def outfit(self, ids, colours):
        return [pick(i, f"piece-{n}", c) for n, (i, c) in enumerate(zip(ids, colours))]

    def test_pieces_in_the_users_palette_all_match(self, client, tone_user, fake_llm, add_item):
        ids = self.wardrobe(add_item, tone_user, IN_PALETTE)
        palette = ask(client, tone_user, fake_llm, self.outfit(ids, IN_PALETTE))["look_meta"]["palette"]
        assert palette["matched"] == palette["total"] == 3

    def test_pieces_outside_the_palette_match_nothing(self, client, tone_user, fake_llm, add_item):
        ids = self.wardrobe(add_item, tone_user, OUTSIDE_PALETTE)
        palette = ask(client, tone_user, fake_llm, self.outfit(ids, OUTSIDE_PALETTE))["look_meta"]["palette"]
        assert palette["matched"] == 0 and palette["total"] == 3

    def test_a_mixed_outfit_counts_only_the_matching_pieces(self, client, tone_user, fake_llm, add_item):
        colours = ["cream", "black", "mustard", "navy"]
        ids = self.wardrobe(add_item, tone_user, colours)
        palette = ask(client, tone_user, fake_llm, self.outfit(ids, colours))["look_meta"]["palette"]
        assert (palette["matched"], palette["total"]) == (2, 4)

    def test_tone_and_undertone_are_reported(self, client, tone_user, fake_llm, add_item):
        (item,) = self.wardrobe(add_item, tone_user, ["cream"])
        palette = ask(client, tone_user, fake_llm, self.outfit([item], ["cream"]))["look_meta"]["palette"]
        assert palette == {"matched": 1, "total": 1, "tone": "light-medium", "undertone": "warm"}

    def test_shade_words_in_the_models_colour_names_still_match(self, client, tone_user, fake_llm, add_item):
        (item,) = self.wardrobe(add_item, tone_user, ["cream"])
        palette = ask(client, tone_user, fake_llm, [pick(item, "piece-0", "Warm Caramel")])["look_meta"]["palette"]
        assert palette["matched"] == 1

    @pytest.mark.parametrize("band,undertone", [("light", "cool"), ("medium", "warm"), ("medium-deep", "neutral"),
                                                 ("deep", "cool")])
    def test_each_bands_own_list_is_used(self, client, make_account, fake_llm, band, undertone):
        user = make_account(email=f"{band}-{undertone}@example.com", skin_tone=f"{band} ({undertone})")
        palette_colour = _TONE_COLORS[band][undertone][0]
        body = ask(client, user, fake_llm, [{"subcategory": "scarf", "color": palette_colour}])
        assert body["look_meta"]["palette"] == {
            "matched": 1, "total": 1, "tone": band, "undertone": undertone}

    def test_a_tone_without_an_undertone_uses_the_neutral_list(self, client, make_account, fake_llm):
        user = make_account(email="band@example.com", skin_tone="medium")
        neutral_colour = _TONE_COLORS["medium"]["neutral"][1]                    # "navy"
        palette = ask(client, user, fake_llm, [{"subcategory": "scarf", "color": neutral_colour}])["look_meta"]["palette"]
        assert palette == {"matched": 1, "total": 1, "tone": "medium", "undertone": None}

    def test_a_legacy_tone_in_the_database_is_read_in_canonical_form(self, client, alice, fake_llm, sql):
        sql("UPDATE users SET skin_tone = 'medium_dark (warm)' WHERE user_id = :u", u=alice.user_id)
        palette = ask(client, alice, fake_llm, [{"subcategory": "scarf", "color": "rust"}])["look_meta"]["palette"]
        assert palette == {"matched": 0, "total": 1, "tone": "medium-deep", "undertone": "warm"}

    def test_no_stored_skin_tone_means_no_palette(self, client, alice, fake_llm, add_item):
        ids = self.wardrobe(add_item, alice, IN_PALETTE)
        assert ask(client, alice, fake_llm, self.outfit(ids, IN_PALETTE))["look_meta"]["palette"] is None

    @pytest.mark.parametrize("stored", ["zzz", "purple (warm)", "light (", "x" * 200, ""])
    def test_a_garbled_stored_tone_means_no_palette_and_no_error(self, client, alice, fake_llm, sql, stored):
        sql("UPDATE users SET skin_tone = :t WHERE user_id = :u", t=stored, u=alice.user_id)
        body = ask(client, alice, fake_llm, [{"subcategory": "scarf", "color": "cream"}])
        assert body["look_meta"] == {"weather": None, "palette": None}

    def test_each_user_is_judged_against_their_own_tone(self, client, make_account, fake_llm):
        warm = make_account(email="w@example.com", skin_tone="light-medium (warm)")
        cool = make_account(email="c@example.com", skin_tone="light-medium (cool)")
        item = [{"subcategory": "scarf", "color": "mustard"}]                   # warm-list colour only
        assert ask(client, warm, fake_llm, item)["look_meta"]["palette"]["matched"] == 1
        assert ask(client, cool, fake_llm, item)["look_meta"]["palette"]["matched"] == 0

    def test_the_palette_is_computed_for_the_caller_not_for_other_users(self, client, two_users, fake_llm, sql):
        alice, bob = two_users
        sql("UPDATE users SET skin_tone = 'deep (warm)' WHERE user_id = :u", u=bob.user_id)
        assert ask(client, alice, fake_llm, [{"subcategory": "scarf", "color": "copper"}])["look_meta"]["palette"] is None

    # -- colour source: the wardrobe row, not the model's wording -------------------

    def test_the_chip_judges_the_real_garment_not_the_models_description(self, client, tone_user, fake_llm, add_item):
        black_shirt = add_item(tone_user, category="top", subcategory="shirt", primary_color="black")
        palette = ask(client, tone_user, fake_llm, [pick(black_shirt, "shirt", "cream")])["look_meta"]["palette"]
        assert palette["matched"] == 0

    def test_a_missing_colour_in_the_reply_is_read_from_the_wardrobe_row(self, client, tone_user, fake_llm, add_item):
        cream_top = add_item(tone_user, category="top", subcategory="shirt", primary_color="cream")
        palette = ask(client, tone_user, fake_llm, [{"item_id": cream_top, "subcategory": "shirt"}])["look_meta"]["palette"]
        assert (palette["matched"], palette["total"]) == (1, 1)

    def test_a_piece_with_no_known_colour_is_left_out_of_the_count(self, client, tone_user, fake_llm, add_item):
        cream_top = add_item(tone_user, category="top", subcategory="shirt", primary_color="cream")
        no_colour = add_item(tone_user, category="bottom", subcategory="jeans", primary_color="unknown")
        palette = ask(client, tone_user, fake_llm, [
            pick(cream_top, "shirt", "cream"), pick(no_colour, "jeans", "cream"),
        ])["look_meta"]["palette"]
        assert (palette["matched"], palette["total"]) == (1, 1)
