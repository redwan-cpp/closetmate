"""
Rule-based outfit recommendation context engine.

Logic:
1. Fetch user's wardrobe items from DB
2. Map occasion → preferred cultural_style and formality_level
3. Filter items by those preferences
4. Build combinations: (top + bottom) or (dress alone), optionally + footwear
5. Return up to 3 outfit combinations
"""
from __future__ import annotations

import sqlite3
from typing import List, Optional

# ---------------------------------------------------------------------------
# Occasion → style/formality mapping
# ---------------------------------------------------------------------------
_OCCASION_MAP: dict[str, dict] = {
    # Bengali / South Asian cultural occasions
    "holud":        {"cultural_style": "traditional", "formality": "festive"},
    "wedding":      {"cultural_style": "traditional", "formality": "formal"},
    "eid":          {"cultural_style": "traditional", "formality": "festive"},
    "puja":         {"cultural_style": "traditional", "formality": "festive"},
    "ceremony":     {"cultural_style": "traditional", "formality": "formal"},
    # Everyday
    "casual":       {"cultural_style": None,           "formality": "casual"},
    "party":        {"cultural_style": None,           "formality": "festive"},
    "office":       {"cultural_style": None,           "formality": "formal"},
    "date":         {"cultural_style": None,           "formality": "casual"},
    "outdoor":      {"cultural_style": None,           "formality": "casual"},
}

# Weather thresholds
_HOT_THRESHOLD = 30.0      # °C
_HUMID_THRESHOLD = 75.0    # %

# Category groupings
_TOP_CATEGORIES = {"shirt", "top", "kurta", "panjabi", "outerwear", "saree"}
_BOTTOM_CATEGORIES = {"jeans", "trousers", "bottom", "skirt"}
_DRESS_CATEGORIES = {"dress", "saree"}
_FOOT_CATEGORIES = {"footwear"}


def _describe_item(item: sqlite3.Row) -> str:
    """Produce a readable description of a wardrobe item."""
    parts = []
    if item["primary_color"]:
        parts.append(item["primary_color"])
    if item["category"]:
        parts.append(item["category"].lower())
    return " ".join(parts) if parts else f"item-{item['item_id'][:6]}"


def _score_item(item: sqlite3.Row, preferred_style: Optional[str],
                preferred_formality: Optional[str],
                is_hot: bool, is_humid: bool) -> int:
    """Higher score = better match."""
    score = 0
    if preferred_style and item["cultural_style"] and \
            item["cultural_style"].lower() == preferred_style.lower():
        score += 3
    formality = (item["formality_level"] or "").lower()
    if preferred_formality and formality == preferred_formality.lower():
        score += 2
    # Prefer lighter materials in hot/humid weather
    material = (item["material"] or "").lower()
    if is_hot or is_humid:
        if material in {"cotton", "linen", "muslin", "silk"}:
            score += 1
    return score


def recommend_outfits(
    user_id: str,
    occasion: str,
    environment: str,
    temperature: float,
    humidity: float,
    db: sqlite3.Connection,
) -> List[List[str]]:
    """
    Return up to 3 outfit combinations for the given context.
    Each combination is a list of item description strings.
    """
    rows = db.execute(
        "SELECT * FROM wardrobe_items WHERE user_id = ?",
        (user_id,),
    ).fetchall()

    if not rows:
        return []

    ctx = _OCCASION_MAP.get(occasion.lower(), {"cultural_style": None, "formality": "casual"})
    preferred_style = ctx["cultural_style"]
    preferred_formality = ctx["formality"]
    is_hot = temperature >= _HOT_THRESHOLD
    is_humid = humidity >= _HUMID_THRESHOLD

    # Score and sort all items
    scored = sorted(
        rows,
        key=lambda r: _score_item(r, preferred_style, preferred_formality, is_hot, is_humid),
        reverse=True,
    )

    # Separate into groups
    tops = [r for r in scored if (r["category"] or "").lower() in _TOP_CATEGORIES
            and (r["category"] or "").lower() not in _DRESS_CATEGORIES]
    bottoms = [r for r in scored if (r["category"] or "").lower() in _BOTTOM_CATEGORIES]
    dresses = [r for r in scored if (r["category"] or "").lower() in _DRESS_CATEGORIES]
    footwear = [r for r in scored if (r["category"] or "").lower() in _FOOT_CATEGORIES]

    outfits: List[List[str]] = []
    foot_desc = [_describe_item(footwear[0])] if footwear else []

    # Build top+bottom combos
    for top in tops[:3]:
        for bottom in bottoms[:3]:
            if len(outfits) >= 3:
                break
            combo = [_describe_item(top), _describe_item(bottom)] + foot_desc
            outfits.append(combo)
        if len(outfits) >= 3:
            break

    # Fill remaining slots with dress combos
    for dress in dresses:
        if len(outfits) >= 3:
            break
        outfits.append([_describe_item(dress)] + foot_desc)

    # If still empty, return top items as suggestions
    if not outfits:
        for item in scored[:3]:
            outfits.append([_describe_item(item)])

    return outfits[:3]
