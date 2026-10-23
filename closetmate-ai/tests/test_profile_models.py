"""models/profile.py — canonical skin tone / body shape normalisation."""
from __future__ import annotations

import time

import pytest

from models.profile import (
    BODY_SHAPES,
    MAX_SKIN_TONE_LEN,
    SKIN_BANDS,
    normalize_body_shape,
    normalize_skin_tone,
    split_skin_tone,
)


class TestNormalizeSkinTone:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("light_medium", "light-medium"),
            ("Light-Medium (Warm)", "light-medium (warm)"),
            ("fair", "light"),
            ("medium_dark", "medium-deep"),
            ("medium_deep", "medium-deep"),
            ("dark", "deep"),
            ("warm", "medium (warm)"),          # legacy undertone-only value
            ("cool", "medium (cool)"),
            ("neutral", "medium (neutral)"),
            ("LIGHT", "light"),
            ("  deep  ", "deep"),
            ("deep (cool)", "deep (cool)"),
            ("deep(cool)", "deep (cool)"),
            ("fair (warm)", "light (warm)"),
            ("light_medium (Cool)", "light-medium (cool)"),
            ("light (purple)", "light"),        # unknown undertone is dropped, band kept
        ],
    )
    def test_canonicalises_known_values(self, raw, expected):
        assert normalize_skin_tone(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
    def test_blank_values_become_none(self, raw):
        assert normalize_skin_tone(raw) is None

    @pytest.mark.parametrize("raw", ["banana", "banana (warm)", "light (warm", "light (warm) extra", "()", "12345"])
    def test_rejects_unknown_values(self, raw):
        with pytest.raises(ValueError, match="Unknown skin tone"):
            normalize_skin_tone(raw)

    @pytest.mark.parametrize("band", SKIN_BANDS)
    def test_every_canonical_band_is_a_fixed_point(self, band):
        assert normalize_skin_tone(band) == band
        assert normalize_skin_tone(f"{band} (warm)") == f"{band} (warm)"

    def test_is_idempotent(self):
        once = normalize_skin_tone("Medium_Dark (Cool)")
        assert normalize_skin_tone(once) == once

    def test_error_message_lists_valid_bands(self):
        with pytest.raises(ValueError) as exc:
            normalize_skin_tone("banana")
        assert "light-medium" in str(exc.value)


class TestSkinToneInputHardening:
    def test_values_longer_than_the_cap_are_rejected(self):
        assert MAX_SKIN_TONE_LEN == 40
        too_long = "light (" + "w" * MAX_SKIN_TONE_LEN + ")"
        assert split_skin_tone(too_long) == ("unknown", "unknown")
        with pytest.raises(ValueError):
            normalize_skin_tone("l" * (MAX_SKIN_TONE_LEN + 1))

    def test_longest_legitimate_value_still_fits(self):
        longest = "medium-deep (neutral)"
        assert len(longest) <= MAX_SKIN_TONE_LEN
        assert normalize_skin_tone(longest) == longest

    @pytest.mark.parametrize(
        "evil",
        ["(" * 50_000, ")" * 50_000, "(" + " " * 50_000 + "x", " " * 50_000 + "x ", "a (" * 20_000, "	" * 30_000 + "(x"],
        ids=["open-parens", "close-parens", "paren-then-spaces", "spaces-then-x", "repeated-groups", "tabs-then-paren"],
    )
    def test_pathological_input_is_rejected_quickly(self, evil):
        """Regression: a backtracking regex used to freeze a worker on input like this."""
        started = time.perf_counter()
        with pytest.raises(ValueError):
            normalize_skin_tone(evil)
        assert split_skin_tone(evil) == ("unknown", "unknown")
        assert time.perf_counter() - started < 0.1

    @pytest.mark.parametrize("raw", ["light (warm))", "light ((warm)", "light) (warm)", "(warm)"])
    def test_malformed_parentheses_are_unknown(self, raw):
        assert split_skin_tone(raw) == ("unknown", "unknown")


class TestSplitSkinTone:
    @pytest.mark.parametrize("raw", [None, "", "banana", "light (warm", "!!!"])
    def test_unusable_input_is_unknown_unknown(self, raw):
        assert split_skin_tone(raw) == ("unknown", "unknown")

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("medium-deep (cool)", ("medium-deep", "cool")),
            ("light", ("light", "unknown")),
            ("warm", ("medium", "warm")),
            ("fair (warm)", ("light", "warm")),
            ("light_medium (cool)", ("light-medium", "cool")),
            ("light (xyz)", ("light", "unknown")),
            ("Deep (NEUTRAL)", ("deep", "neutral")),
        ],
    )
    def test_splits_band_and_undertone(self, raw, expected):
        assert split_skin_tone(raw) == expected


class TestNormalizeBodyShape:
    @pytest.mark.parametrize("shape", sorted(BODY_SHAPES))
    def test_every_valid_shape_round_trips(self, shape):
        assert normalize_body_shape(shape) == shape

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Hourglass", "hourglass"),
            (" PEAR ", "pear"),
            ("Inverted Triangle", "inverted_triangle"),
            ("inverted-triangle", "inverted_triangle"),
        ],
    )
    def test_case_spaces_and_hyphens_are_normalised(self, raw, expected):
        assert normalize_body_shape(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_blank_values_become_none(self, raw):
        assert normalize_body_shape(raw) is None

    @pytest.mark.parametrize("raw", ["banana", "triangle", "pear;DROP TABLE users", "😀"])
    def test_rejects_unknown_shapes(self, raw):
        with pytest.raises(ValueError, match="Unknown body shape"):
            normalize_body_shape(raw)
