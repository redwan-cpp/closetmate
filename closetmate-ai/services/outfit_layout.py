"""
outfit_layout.py — what role does each wardrobe item play in an outfit?

The app composes outfits as collages (a "lookboard"): a dress or a top+bottom in the
middle, outerwear behind, shoes underneath, accessories down the side. To place an item
it only needs a *slot*, which this module derives from the item's category and
subcategory. Doing it on the server keeps one source of truth for chat, saved looks and
worn history.

Also here: a light colour check used for the "in your best colours" chip on a look.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence

SLOTS = ("outer", "dress", "top", "bottom", "shoes", "accessory")

# Complete garments: nothing separate is worn with them.
_DRESS_SUBS = frozenset({
    "dress", "jumpsuit", "gown", "romper", "saree", "sari", "lehenga", "anarkali", "sharara",
    "gharara", "salwar kameez", "sherwani", "abaya", "thobe", "kaftan", "caftan", "jalabiya",
    "jilbab", "kimono", "hanfu", "cheongsam", "qipao", "hanbok", "ao dai",
})
_TOP_SUBS = frozenset({
    "top", "shirt", "t-shirt", "tshirt", "polo", "blouse", "panjabi", "punjabi", "kurta", "kurti",
    "hoodie", "sweater", "sweatshirt", "pullover", "cardigan", "tank top", "crop top", "tunic",
})
_OUTER_SUBS = frozenset({
    "jacket", "coat", "blazer", "vest", "waistcoat", "shawl", "dupatta", "trench coat", "parka",
    "poncho", "cape", "puffer",
})
_BOTTOM_SUBS = frozenset({
    "jeans", "trousers", "pants", "shorts", "skirt", "leggings", "chinos", "palazzo", "pajama",
    "pyjama", "churidar", "salwar", "dhoti", "lungi", "joggers", "sweatpants",
})
_SHOE_SUBS = frozenset({
    "shoes", "sneakers", "sandals", "boots", "loafers", "heels", "slippers", "flats", "oxfords",
    "kolhapuri", "mojari", "flip flops",
})


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower().replace("_", " ").replace("-", " ") if value else ""


def _norm_keep_hyphen(value: Optional[str]) -> str:
    return (value or "").strip().lower().replace("_", " ")


def outfit_slot(category: Optional[str], subcategory: Optional[str]) -> str:
    """Return one of SLOTS. Subcategory wins over category; unknown things are accessories."""
    sub = _norm_keep_hyphen(subcategory)
    sub_flat = _norm(subcategory)
    cat = _norm(category)

    for names, slot in (
        (_DRESS_SUBS, "dress"), (_SHOE_SUBS, "shoes"), (_OUTER_SUBS, "outer"),
        (_BOTTOM_SUBS, "bottom"), (_TOP_SUBS, "top"),
    ):
        if sub in names or sub_flat in names:
            return slot

    if cat in ("footwear", "shoes", "shoe"):
        return "shoes"
    if cat == "dress":
        return "dress"
    if cat == "outerwear":
        return "outer"
    if cat in ("bottom", "bottoms"):
        return "bottom"
    if cat in ("top", "tops"):
        return "top"
    if cat == "traditional":
        return "dress"          # unknown traditional garment: treat as a complete outfit
    return "accessory"


# ---------------------------------------------------------------------------
# colour check
# ---------------------------------------------------------------------------

# Words that describe shade, not hue — "warm ivory" and "ivory white" share "ivory".
_SHADE_WORDS = frozenset({
    "light", "dark", "deep", "soft", "bright", "pale", "rich", "bold", "warm", "cool",
    "dusty", "muted", "pastel", "matte", "neon", "burnt", "icy", "baby", "hot", "electric",
})


def _hue_words(color: str) -> frozenset:
    words = {w for w in _norm(color).split() if w}
    return frozenset(w for w in words if w not in _SHADE_WORDS) or frozenset(words)


def color_in_palette(item_color: Optional[str], palette: Iterable[str]) -> bool:
    """True when the item's colour shares a hue word with any palette colour."""
    item = _hue_words(item_color or "")
    if not item:
        return False
    return any(item & _hue_words(entry) for entry in palette)


def palette_for_skin_tone(skin_tone: Optional[str]) -> List[str]:
    """The flattering-colour list for a stored skin tone ("light-medium (warm)")."""
    from models.profile import split_skin_tone
    from services.skin_tone_detector import _TONE_COLORS

    band, undertone = split_skin_tone(skin_tone)
    table = _TONE_COLORS.get(band, {})
    return list(table.get(undertone) or table.get("neutral") or [])


def look_meta(
    items: Sequence[Dict[str, Optional[str]]],
    skin_tone: Optional[str],
    weather: Optional[dict],
) -> Dict[str, object]:
    """
    Facts shown as chips on an outfit card. Only states what we can actually check:
    how many pieces are in the user's recommended colours, and the weather we used.
    """
    meta: Dict[str, object] = {"weather": weather or None, "palette": None}
    palette = palette_for_skin_tone(skin_tone)
    colors = [i.get("color") for i in items if i.get("color")]
    if palette and colors:
        matched = [c for c in colors if color_in_palette(c, palette)]
        band, undertone = _tone_labels(skin_tone)
        meta["palette"] = {
            "matched": len(matched),
            "total": len(colors),
            "tone": band,
            "undertone": undertone,
        }
    return meta


def _tone_labels(skin_tone: Optional[str]):
    from models.profile import split_skin_tone
    band, undertone = split_skin_tone(skin_tone)
    return (None if band == "unknown" else band), (None if undertone == "unknown" else undertone)
