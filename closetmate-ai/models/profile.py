"""
Canonical profile values and normalisation.

The skin-tone string used to drift between layers (``light-medium`` vs
``light_medium`` vs ``light-medium (warm)``). Everything now passes through
``normalize_skin_tone`` so the database only ever holds::

    "<band>"            e.g. "medium-deep"
    "<band> (<tone>)"   e.g. "light-medium (warm)"
"""
from __future__ import annotations

from typing import Optional, Tuple

SKIN_BANDS = ("light", "light-medium", "medium", "medium-deep", "deep")
UNDERTONES = ("warm", "cool", "neutral")

BODY_SHAPES = frozenset({
    "hourglass", "pear", "apple", "rectangle", "inverted_triangle",
    "oval", "athletic", "petite", "tall", "curvy",
})

# Values the older profile screen could write. Mapped onto the canonical bands.
_LEGACY_BANDS = {
    "fair": "light",
    "light_medium": "light-medium",
    "medium_dark": "medium-deep",
    "medium_deep": "medium-deep",
    "dark": "deep",
}

# Longest legitimate value is "medium-deep (neutral)" (22 chars). The cap, and parsing
# with plain string methods instead of a regex, rule out catastrophic backtracking on
# attacker-supplied input (a regex here was measured freezing a worker for minutes).
MAX_SKIN_TONE_LEN = 40


def split_skin_tone(value: Optional[str]) -> Tuple[str, str]:
    """Return (band, undertone); ``"unknown"`` for whatever is missing or malformed."""
    unknown = ("unknown", "unknown")
    if not value:
        return unknown
    text = str(value).strip().lower()
    if not text or len(text) > MAX_SKIN_TONE_LEN:
        return unknown

    band_part, paren, rest = text.partition("(")
    undertone = "unknown"
    if paren:
        # exactly one "(...)" group, closing the string: "light-medium (warm)"
        if not rest.endswith(")") or "(" in rest or ")" in rest[:-1]:
            return unknown
        undertone = rest[:-1].strip()
    if ")" in band_part:
        return unknown

    band = band_part.strip().replace("_", "-")
    if not band:
        return unknown
    band = _LEGACY_BANDS.get(band.replace("-", "_"), band)
    if band in UNDERTONES:                      # legacy undertone-only value
        return "medium", band
    return (band if band in SKIN_BANDS else "unknown",
            undertone if undertone in UNDERTONES else "unknown")


def normalize_skin_tone(value: Optional[str]) -> Optional[str]:
    """Canonicalise a client-supplied skin tone. Raises ValueError if invalid."""
    if value is None or not str(value).strip():
        return None
    band, undertone = split_skin_tone(str(value))
    if band == "unknown":
        raise ValueError(f"Unknown skin tone {value!r}. Expected one of {', '.join(SKIN_BANDS)}.")
    return band if undertone == "unknown" else f"{band} ({undertone})"


def normalize_body_shape(value: Optional[str]) -> Optional[str]:
    if value is None or not str(value).strip():
        return None
    shape = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if shape not in BODY_SHAPES:
        raise ValueError(f"Unknown body shape {value!r}.")
    return shape
