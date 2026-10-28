"""services/outfit_layout.py — slots, palette matching, look_meta — and the `slot` field on wardrobe responses."""
from __future__ import annotations

import itertools

import pytest

from services import outfit_layout
from services.outfit_layout import SLOTS, color_in_palette, look_meta, outfit_slot, palette_for_skin_tone
from services.skin_tone_detector import _TONE_COLORS


# ---------------------------------------------------------------------------
# outfit_slot
# ---------------------------------------------------------------------------

class TestOutfitSlot:
    def test_the_six_slots(self):
        assert SLOTS == ("outer", "dress", "top", "bottom", "shoes", "accessory")

    @pytest.mark.parametrize("category,subcategory,expected", [
        ("top", "t-shirt", "top"),
        ("top", "panjabi", "top"),
        ("traditional", "saree", "dress"),
        ("traditional", "lehenga", "dress"),
        ("traditional", "salwar kameez", "dress"),
        ("traditional", "unknown thing", "dress"),
        ("bottom", "jeans", "bottom"),
        ("top", "jacket", "outer"),                  # subcategory wins over category
        ("outerwear", None, "outer"),
        ("footwear", "sneakers", "shoes"),
        ("accessory", "watch", "accessory"),
        ("accessory", "belt", "accessory"),
        (None, None, "accessory"),
        ("  Footwear ", "Heels", "shoes"),
        ("dress", "dress", "dress"),
    ])
    def test_documented_cases(self, category, subcategory, expected):
        assert outfit_slot(category, subcategory) == expected

    @pytest.mark.parametrize("category,subcategory,expected", [
        ("TOP", "T-SHIRT", "top"),
        (" Top ", "  Tank_Top  ", "top"),
        ("traditional", "Salwar_Kameez", "dress"),
        ("traditional", "SALWAR-KAMEEZ", "dress"),
        ("accessory", "Flip-Flops", "shoes"),
        ("accessory", "flip_flops", "shoes"),
        ("whatever", "Ao-Dai", "dress"),
        ("whatever", "TRENCH_COAT", "outer"),
        ("FOOTWEAR", None, "shoes"),
        ("\tOuterwear\n", "", "outer"),
    ])
    def test_case_whitespace_underscore_and_hyphen_insensitive(self, category, subcategory, expected):
        assert outfit_slot(category, subcategory) == expected

    @pytest.mark.parametrize("category,subcategory,expected", [
        ("accessory", "jeans", "bottom"),
        ("footwear", "shirt", "top"),
        ("bottom", "dress", "dress"),
        ("top", "sneakers", "shoes"),
        ("dress", "blazer", "outer"),
        ("outerwear", "hoodie", "top"),                # a hoodie is a top even when filed under outerwear
        ("traditional", "kurta", "top"),               # a known part beats the "traditional = dress" fallback
        ("traditional", "dupatta", "outer"),
        ("traditional", "palazzo", "bottom"),
    ])
    def test_subcategory_always_wins_over_category(self, category, subcategory, expected):
        assert outfit_slot(category, subcategory) == expected

    @pytest.mark.parametrize("category,expected", [
        ("footwear", "shoes"), ("shoes", "shoes"), ("shoe", "shoes"),
        ("dress", "dress"), ("traditional", "dress"),
        ("outerwear", "outer"),
        ("bottom", "bottom"), ("bottoms", "bottom"),
        ("top", "top"), ("tops", "top"),
        ("accessory", "accessory"), ("accessories", "accessory"), ("hat", "accessory"),
    ])
    def test_category_alone_decides_when_there_is_no_usable_subcategory(self, category, expected):
        assert outfit_slot(category, None) == expected
        assert outfit_slot(category, "") == expected
        assert outfit_slot(category, "   ") == expected
        assert outfit_slot(category, "something nobody has heard of") == expected

    @pytest.mark.parametrize("category,subcategory", [
        (None, None), ("", ""), ("   ", None), (None, "   "), ("???", "!!!"),
        ("🧢", "🧣"), ("accessory'; DROP TABLE wardrobe_items; --", None), ("x" * 10_000, "y" * 10_000),
    ])
    def test_unknown_or_hostile_input_is_an_accessory(self, category, subcategory):
        assert outfit_slot(category, subcategory) == "accessory"

    def test_every_listed_garment_maps_to_its_own_slot(self):
        groups = {
            "dress": outfit_layout._DRESS_SUBS, "shoes": outfit_layout._SHOE_SUBS, "outer": outfit_layout._OUTER_SUBS,
            "bottom": outfit_layout._BOTTOM_SUBS, "top": outfit_layout._TOP_SUBS,
        }
        for slot, names in groups.items():
            for name in names:
                assert outfit_slot("accessory", name) == slot, name
                assert outfit_slot(None, name.upper()) == slot, name

    def test_no_garment_is_listed_under_two_slots(self):
        groups = [outfit_layout._DRESS_SUBS, outfit_layout._SHOE_SUBS, outfit_layout._OUTER_SUBS,
                  outfit_layout._BOTTOM_SUBS, outfit_layout._TOP_SUBS]
        for a, b in itertools.combinations(groups, 2):
            assert not (a & b), a & b

    def test_the_result_is_always_one_of_the_slots(self):
        cats = [None, "", "top", "bottom", "dress", "footwear", "outerwear", "traditional", "accessory", "weird"]
        subs = [None, "", "saree", "jeans", "belt", "jacket", "sneakers", "unknown", "T-Shirt"]
        for cat, sub in itertools.product(cats, subs):
            assert outfit_slot(cat, sub) in SLOTS


# ---------------------------------------------------------------------------
# color_in_palette
# ---------------------------------------------------------------------------

class TestColorInPalette:
    @pytest.mark.parametrize("item,palette,expected", [
        ("warm ivory", ["ivory white"], True),          # shade word "warm" ignored, "ivory" shared
        ("navy blue", ["denim blue"], True),
        ("red", ["blue", "green"], False),
        (None, ["red"], False),
        ("", ["red"], False),
        ("   ", ["red"], False),
    ])
    def test_documented_cases(self, item, palette, expected):
        assert color_in_palette(item, palette) is expected

    @pytest.mark.parametrize("item,palette,expected", [
        ("light", ["light"], True),                      # a shade word alone still compares as itself
        ("light", ["dark"], False),
        ("warm", ["warm"], True),
        ("warm", ["cool"], False),
        ("light blue", ["dark blue"], True),             # shade differs, hue matches
        ("light blue", ["light green"], False),          # shade matches, hue differs: not a match
        ("warm gray", ["warm ivory"], False),
        ("off white", ["warm white"], True),
        ("dusty rose", ["rose"], True),
        ("burnt orange", ["orange"], True),
        ("bright pink", ["hot pink", "navy"], True),
    ])
    def test_shade_words_are_ignored_unless_they_are_all_there_is(self, item, palette, expected):
        assert color_in_palette(item, palette) is expected

    @pytest.mark.parametrize("item,palette", [
        ("IVORY", ["warm Ivory"]),
        ("  navy-blue ", ["Denim  Blue"]),
        ("navy_blue", ["denim blue"]),
        ("Cobalt", ["cobalt blue"]),
    ])
    def test_matching_is_case_whitespace_and_separator_insensitive(self, item, palette):
        assert color_in_palette(item, palette) is True

    @pytest.mark.parametrize("item,palette", [
        ("red", ["reddish"]),                            # whole words only
        ("blue", ["blueberry"]),
        ("red", []),
        ("red", [""]),
        ("red", [None]),
        ("red", ["  "]),
    ])
    def test_no_match(self, item, palette):
        assert color_in_palette(item, palette) is False

    def test_any_palette_entry_is_enough(self):
        assert color_in_palette("mustard", ["teal", "plum", "mustard yellow"]) is True

    def test_accepts_any_iterable_of_colours(self):
        assert color_in_palette("teal", (c for c in ["plum", "teal"])) is True
        assert color_in_palette("teal", {"plum", "teal"}) is True
        assert color_in_palette("teal", iter(())) is False

    def test_emoji_and_symbols_do_not_crash(self):
        assert color_in_palette("🔴", ["🔴"]) is True
        assert color_in_palette("red!!!", ["red"]) is False         # punctuation is part of the word
        assert color_in_palette("x" * 10_000, ["x" * 10_000]) is True


# ---------------------------------------------------------------------------
# palette_for_skin_tone
# ---------------------------------------------------------------------------

ALL_TONES = [(band, under) for band, table in _TONE_COLORS.items() for under in table]


class TestPaletteForSkinTone:
    def test_documented_case(self):
        assert palette_for_skin_tone("light-medium (warm)") == _TONE_COLORS["light-medium"]["warm"]

    @pytest.mark.parametrize("band,undertone", ALL_TONES)
    def test_every_band_and_undertone_resolves_to_its_own_list(self, band, undertone):
        assert palette_for_skin_tone(f"{band} ({undertone})") == _TONE_COLORS[band][undertone]

    @pytest.mark.parametrize("band", list(_TONE_COLORS))
    def test_band_without_undertone_uses_the_neutral_list(self, band):
        assert palette_for_skin_tone(band) == _TONE_COLORS[band]["neutral"]

    def test_legacy_spellings_are_understood(self):
        assert palette_for_skin_tone("medium_dark (warm)") == _TONE_COLORS["medium-deep"]["warm"]
        assert palette_for_skin_tone("fair") == _TONE_COLORS["light"]["neutral"]
        assert palette_for_skin_tone("LIGHT_MEDIUM (Cool)") == _TONE_COLORS["light-medium"]["cool"]
        assert palette_for_skin_tone("warm") == _TONE_COLORS["medium"]["warm"]        # undertone-only legacy value

    def test_an_unrecognised_undertone_falls_back_to_neutral(self):
        assert palette_for_skin_tone("deep (rosy)") == _TONE_COLORS["deep"]["neutral"]

    @pytest.mark.parametrize("value", [
        None, "", "   ", "unknown", "purple (warm)", "(warm)", "garbage", "light (warm", "light warm)",
        "light (warm) (cool)", "x" * 200, 123, "💀",
    ])
    def test_unknown_or_malformed_tones_give_an_empty_list(self, value):
        assert palette_for_skin_tone(value) == []

    def test_result_is_a_copy_so_callers_cannot_corrupt_the_table(self):
        palette = palette_for_skin_tone("light-medium (warm)")
        palette.append("hot pink")
        palette.clear()
        assert palette_for_skin_tone("light-medium (warm)") == _TONE_COLORS["light-medium"]["warm"] != []


# ---------------------------------------------------------------------------
# look_meta
# ---------------------------------------------------------------------------

WARM = "light-medium (warm)"            # caramel, warm beige, mustard, burnt orange, cream, gold, warm olive
RAIN = {"city": "Dhaka", "temperature": 31.0, "condition": "Rain"}


def colours(*names):
    return [{"color": n} for n in names]


class TestLookMeta:
    def test_shape_with_everything_known(self):
        meta = look_meta(colours("cream", "mustard", "navy"), WARM, RAIN)
        assert meta == {
            "weather": RAIN,
            "palette": {"matched": 2, "total": 3, "tone": "light-medium", "undertone": "warm"},
        }

    def test_weather_is_echoed_untouched(self):
        assert look_meta(colours("cream"), WARM, RAIN)["weather"] is RAIN

    @pytest.mark.parametrize("weather", [None, {}])
    def test_missing_weather_is_none(self, weather):
        assert look_meta(colours("cream"), WARM, weather)["weather"] is None

    @pytest.mark.parametrize("tone", [None, "", "unknown", "purple (warm)", "(warm)", 42])
    def test_unknown_skin_tone_means_no_palette(self, tone):
        assert look_meta(colours("cream", "mustard"), tone, RAIN) == {"weather": RAIN, "palette": None}

    @pytest.mark.parametrize("items", [
        [], [{}], [{"color": None}], [{"color": ""}], [{"slot": "top"}, {"color": None}, {"color": ""}],
    ])
    def test_no_colour_on_any_item_means_no_palette(self, items):
        assert look_meta(items, WARM, None) == {"weather": None, "palette": None}

    def test_all_pieces_in_the_palette(self):
        palette = look_meta(colours("cream", "gold", "caramel"), WARM, None)["palette"]
        assert palette["matched"] == palette["total"] == 3

    def test_no_piece_in_the_palette(self):
        palette = look_meta(colours("black", "navy", "red"), WARM, None)["palette"]
        assert (palette["matched"], palette["total"]) == (0, 3)

    def test_items_without_a_colour_are_not_counted_in_the_total(self):
        palette = look_meta([{"color": "cream"}, {"color": None}, {}, {"color": ""}, {"color": "black"}], WARM, None)["palette"]
        assert (palette["matched"], palette["total"]) == (1, 2)

    def test_the_same_colour_twice_counts_twice(self):
        palette = look_meta(colours("cream", "cream", "black"), WARM, None)["palette"]
        assert (palette["matched"], palette["total"]) == (2, 3)

    def test_shade_words_do_not_stop_a_match(self):
        palette = look_meta(colours("light caramel", "warm beige"), WARM, None)["palette"]
        assert palette["matched"] == 2

    def test_band_only_tone_has_a_none_undertone_and_uses_the_neutral_list(self):
        meta = look_meta(colours("teal", "black"), "light-medium", None)
        assert meta["palette"] == {"matched": 1, "total": 2, "tone": "light-medium", "undertone": None}

    def test_legacy_tone_is_reported_in_canonical_form(self):
        meta = look_meta(colours("rust"), "medium_dark (warm)", None)["palette"]
        assert (meta["tone"], meta["undertone"]) == ("medium-deep", "warm")

    def test_only_the_documented_keys_are_returned(self):
        meta = look_meta(colours("cream"), WARM, RAIN)
        assert set(meta) == {"weather", "palette"}
        assert set(meta["palette"]) == {"matched", "total", "tone", "undertone"}

    def test_inputs_are_not_mutated(self):
        items = colours("cream", "black")
        snapshot = [dict(i) for i in items]
        weather = dict(RAIN)
        look_meta(items, WARM, weather)
        assert items == snapshot and weather == RAIN

    def test_accepts_any_sequence_of_items(self):
        assert look_meta(tuple(colours("cream")), WARM, None)["palette"]["matched"] == 1


# ---------------------------------------------------------------------------
# `slot` on the wardrobe endpoints
# ---------------------------------------------------------------------------

ITEM_KEYS = {
    "item_id", "user_id", "category", "subcategory", "primary_color", "material", "pattern",
    "formality_level", "cultural_style", "image_path", "thumb_url", "created_at", "slot",
}


def items_of(client, account):
    resp = client.get(f"/wardrobe/items/{account.user_id}", headers=account.headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestSlotOnWardrobeResponses:
    def test_every_item_carries_a_string_slot_and_nothing_else_changed(self, client, alice, add_item):
        add_item(alice)
        (item,) = items_of(client, alice)
        assert isinstance(item["slot"], str) and item["slot"] in SLOTS
        assert set(item) == ITEM_KEYS

    def test_slots_follow_category_and_subcategory(self, client, alice, add_item):
        cases = {
            "saree": ("traditional", "saree", "dress"),
            "jeans": ("bottom", "jeans", "bottom"),
            "sneakers": ("footwear", "sneakers", "shoes"),
            "jacket": ("top", "jacket", "outer"),
            "watch": ("accessory", "watch", "accessory"),
            "shirt": ("top", "shirt", "top"),
        }
        ids = {name: add_item(alice, category=c, subcategory=s) for name, (c, s, _) in cases.items()}
        by_id = {i["item_id"]: i["slot"] for i in items_of(client, alice)}
        assert {name: by_id[item_id] for name, item_id in ids.items()} == {n: v[2] for n, v in cases.items()}

    def test_an_item_with_no_subcategory_uses_its_category(self, client, alice, add_item):
        add_item(alice, category="footwear", subcategory=None)
        assert items_of(client, alice)[0]["slot"] == "shoes"

    def test_a_row_with_null_category_and_subcategory_is_an_accessory(self, client, alice, sql):
        sql("INSERT INTO wardrobe_items (item_id, user_id, category, subcategory, created_at) "
            "VALUES ('legacy-1', :u, NULL, NULL, '2020-01-01T00:00:00+00:00')", u=alice.user_id)
        (item,) = items_of(client, alice)
        assert item["slot"] == "accessory" and item["category"] is None

    def test_the_slot_is_derived_on_read_not_stored(self, client, alice, add_item, sql):
        item_id = add_item(alice, category="top", subcategory="shirt")
        assert items_of(client, alice)[0]["slot"] == "top"
        sql("UPDATE wardrobe_items SET subcategory = 'skirt' WHERE item_id = :i", i=item_id)
        assert items_of(client, alice)[0]["slot"] == "bottom"
        assert "slot" not in {r["name"] for r in sql("PRAGMA table_info(wardrobe_items)")}

    def test_worn_history_items_carry_a_slot_too(self, client, alice, add_item):
        saree = add_item(alice, category="traditional", subcategory="saree")
        shoes = add_item(alice, category="footwear", subcategory="heels")
        client.post("/wardrobe/log-worn", json={"user_id": alice.user_id, "item_ids": [saree, shoes]},
                    headers=alice.headers)
        logs = client.get(f"/wardrobe/worn-history/{alice.user_id}", headers=alice.headers).json()
        assert [(i["item_id"], i["slot"]) for i in logs[0]["items"]] == [(saree, "dress"), (shoes, "shoes")]

    def test_other_users_wardrobes_are_unaffected(self, client, two_users, add_item):
        alice, bob = two_users
        add_item(alice, category="traditional", subcategory="saree")
        add_item(bob, category="footwear", subcategory="boots")
        assert [i["slot"] for i in items_of(client, alice)] == ["dress"]
        assert [i["slot"] for i in items_of(client, bob)] == ["shoes"]
